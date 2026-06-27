from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .network_ops import CommandResult, enable_adapter, set_static_ip
from .old_tool_automation import automate_power_on
from .securecrt_automation import (
    build_tftp_copy_upgrade_target,
    launch_securecrt_tftp_copy_upgrade,
    resolve_serial_log_directory,
)
from .tftpd_automation import prepare_tftpd_server


POWER_RECYCLE_AFTER_UPGRADE_SECONDS = 90
POWER_ON_SETTLE_SECONDS = 120
BOOT_LOGIN_TIMEOUT_SECONDS = 600
TFTP_COMPLETE_TIMEOUT_SECONDS = 2400
FINAL_LOGIN_TIMEOUT_SECONDS = 1200
POWER_ON_WAIT_SECONDS = 10
TFTP_SUBNET_MASK = "255.255.255.0"
POST_TFTP_BOOT_RESET_STATUS = "POST_TFTP_BOOT_RESET_SENT"
VISIBLE_SECURECRT_STATUSES = {
    "ERROR_",
    POST_TFTP_BOOT_RESET_STATUS,
}


@dataclass(frozen=True)
class SingleTftpCopyUpgradeRequest:
    vlan: str
    server_interface: str
    tftp_server_ip: str
    firmware_path: Path
    power_serial_port: str
    final_username: str
    final_password: str
    restore_factory: bool = False


def run_single_tftp_copy_upgrade(
    tool_root: Path,
    old_tool_path: Path,
    request: SingleTftpCopyUpgradeRequest,
    on_output: Optional[Callable[[str], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    log_dir = resolve_serial_log_directory()
    securecrt_target = build_tftp_copy_upgrade_target(
        request.vlan,
        request.tftp_server_ip,
        log_dir,
        restore_factory=request.restore_factory,
        final_username=request.final_username,
        final_password=request.final_password,
    )
    launch_result = launch_securecrt_tftp_copy_upgrade(tool_root, securecrt_target)
    if not launch_result.success:
        return CommandResult(False, launch_result.message)
    emit(launch_result.message)
    emit(f"SecureCRT 日志文件：{securecrt_target.log_path}")

    emit(f"开始调用自动上电模块，程控电源串口：{request.power_serial_port}")
    power_result = automate_power_on(
        old_tool_path,
        serial_port=request.power_serial_port,
        wait_seconds=POWER_ON_WAIT_SECONDS,
        on_output=emit,
    )
    if not power_result.ok:
        return power_result

    _write_signal_file(securecrt_target.boot_enter_signal_path)
    emit("旧软件已关闭，已允许 SecureCRT 开始每隔 1 秒敲击回车。")

    boot_status = wait_for_upgrade_status(
        securecrt_target.status_path,
        "BOOT_LOGIN_COMPLETE",
        BOOT_LOGIN_TIMEOUT_SECONDS,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not boot_status.ok:
        return boot_status

    emit("boot 登录完成，准备 Tftpd64 传输环境。")
    network_result = prepare_tftp_network(
        request.server_interface,
        request.tftp_server_ip,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not network_result.ok:
        return network_result

    tftpd_result = prepare_tftpd_server(
        tool_root,
        request.firmware_path,
        request.server_interface,
        request.tftp_server_ip,
        on_output=emit,
    )
    if not tftpd_result.ok:
        return tftpd_result
    _write_signal_file(securecrt_target.command_signal_path)
    emit(f"已允许 SecureCRT 下发命令：{securecrt_target.tftp_command}")

    tftp_status = wait_for_upgrade_status(
        securecrt_target.status_path,
        "TFTP_COMPLETE",
        TFTP_COMPLETE_TIMEOUT_SECONDS,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not tftp_status.ok:
        return tftp_status

    emit("Tftp 传输完成，等待 1.5 分钟观察是否回到 boot。")
    sleep_fn(POWER_RECYCLE_AFTER_UPGRADE_SECONDS)

    if _has_status(Path(securecrt_target.status_path), POST_TFTP_BOOT_RESET_STATUS):
        emit("检测到 SecureCRT 已在 boot 阶段发送 reset，等待 120 秒后确认登录。")
        sleep_fn(POWER_ON_SETTLE_SECONDS)
    else:
        emit("未检测到 boot reset，开始重新上电。")
        repower_result = automate_power_on(
            old_tool_path,
            serial_port=request.power_serial_port,
            wait_seconds=POWER_ON_WAIT_SECONDS,
            on_output=emit,
        )
        if not repower_result.ok:
            return repower_result

        emit("已重新上电，等待 120 秒后确认登录。")
        sleep_fn(POWER_ON_SETTLE_SECONDS)

    _write_signal_file(securecrt_target.final_login_signal_path)
    emit("已允许 SecureCRT 开始确认重启后的登录提示。")
    final_status = wait_for_upgrade_status(
        securecrt_target.status_path,
        "DONE",
        FINAL_LOGIN_TIMEOUT_SECONDS,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not final_status.ok:
        return final_status

    return CommandResult(True, f"{request.vlan} 全包升级流程完成。")


def prepare_tftp_network(
    server_interface: str,
    tftp_server_ip: str,
    on_output: Optional[Callable[[str], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    emit(f"准备 TFTP 网卡：{server_interface} -> {tftp_server_ip}")
    enable_result = enable_adapter(server_interface)
    if not enable_result.ok:
        return enable_result
    emit(enable_result.message)
    sleep_fn(1)

    set_result = set_static_ip(server_interface, tftp_server_ip, TFTP_SUBNET_MASK)
    if not set_result.ok:
        return set_result
    emit(set_result.message)
    sleep_fn(1)
    return CommandResult(True, f"TFTP 网卡已准备好：{server_interface} / {tftp_server_ip}")


def wait_for_upgrade_status(
    status_path: str,
    expected_status: str,
    timeout_seconds: float,
    on_output: Optional[Callable[[str], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    deadline = time.monotonic() + timeout_seconds
    seen: set[str] = set()
    while time.monotonic() < deadline:
        statuses = _read_statuses(Path(status_path))
        for status in statuses:
            if status not in seen:
                seen.add(status)
                if on_output and _should_show_securecrt_status(status):
                    on_output(f"SecureCRT 状态：{status}")
            if status.startswith("ERROR_"):
                return CommandResult(False, f"SecureCRT 升级脚本失败：{status}")
            if status == expected_status:
                return CommandResult(True, f"已检测到状态：{expected_status}")
        sleep_fn(1)
    return CommandResult(False, f"等待 SecureCRT 状态超时：{expected_status}")


def _read_statuses(status_path: Path) -> list[str]:
    if not status_path.exists():
        return []
    for encoding in ("utf-16", "utf-8"):
        try:
            text = status_path.read_text(encoding=encoding, errors="ignore")
            break
        except OSError:
            return []
        except UnicodeError:
            continue
    else:
        return []
    statuses = []
    for line in text.splitlines():
        status = line.split("\t")[-1].strip()
        if status:
            statuses.append(status)
    return statuses


def _has_status(status_path: Path, expected_status: str) -> bool:
    return expected_status in _read_statuses(status_path)


def _should_show_securecrt_status(status: str) -> bool:
    return any(status.startswith(prefix) for prefix in VISIBLE_SECURECRT_STATUSES)


def _write_signal_file(path: str) -> None:
    Path(path).write_text("TFTP_READY\n", encoding="utf-8")

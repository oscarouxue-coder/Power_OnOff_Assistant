from __future__ import annotations

import time
import subprocess
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
TRANSFER_TFTP_COMMAND = "Tftp指令"
TRANSFER_TFTP_PUT = "Tftp Put"
TFTP_PUT_DEVICE_IP = "192.168.1.1"
TFTP_PUT_TIMEOUT_SECONDS = 600
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
    transfer_method: str = TRANSFER_TFTP_COMMAND


def run_single_tftp_copy_upgrade(
    tool_root: Path,
    old_tool_path: Path,
    request: SingleTftpCopyUpgradeRequest,
    on_output: Optional[Callable[[str], None]] = None,
    on_securecrt_pids: Optional[Callable[[tuple[int, ...]], None]] = None,
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
        transfer_method=request.transfer_method,
    )
    boot_enter_signal_sent = False

    def allow_boot_enter(reason: str) -> None:
        nonlocal boot_enter_signal_sent
        if boot_enter_signal_sent:
            return
        _write_signal_file(securecrt_target.boot_enter_signal_path)
        boot_enter_signal_sent = True
        emit(reason)

    def on_power_output(line: str) -> None:
        emit(line)
        if "已点击 Start ALL" in line:
            allow_boot_enter("旧工具已点击 Start ALL，已允许 SecureCRT 立即开始每隔 1 秒敲击回车。")

    launch_result = launch_securecrt_tftp_copy_upgrade(tool_root, securecrt_target)
    if not launch_result.success:
        return CommandResult(False, launch_result.message)
    securecrt_pids = tuple(getattr(launch_result, "securecrt_pids", ()) or ())
    if securecrt_pids and on_securecrt_pids:
        on_securecrt_pids(securecrt_pids)
    emit(launch_result.message)
    if securecrt_pids:
        emit(f"本次升级启动的 SecureCRT PID：{', '.join(str(pid) for pid in securecrt_pids)}")
    else:
        emit("未检测到本次新增的 SecureCRT 窗口 PID，收尾时将保留现有 SecureCRT 会话。")
    emit(f"SecureCRT 日志文件：{securecrt_target.log_path}")

    emit(f"开始调用自动上电模块，程控电源串口：{request.power_serial_port}")
    power_result = automate_power_on(
        old_tool_path,
        serial_port=request.power_serial_port,
        wait_seconds=POWER_ON_WAIT_SECONDS,
        on_output=on_power_output,
    )
    if not power_result.ok:
        return power_result

    allow_boot_enter("旧软件已关闭，已允许 SecureCRT 开始每隔 1 秒敲击回车。")

    boot_status = wait_for_upgrade_status(
        securecrt_target.status_path,
        "BOOT_LOGIN_COMPLETE",
        BOOT_LOGIN_TIMEOUT_SECONDS,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not boot_status.ok:
        return boot_status

    emit(f"boot 登录完成，准备 {request.transfer_method} 传输环境。")
    network_result = prepare_tftp_network(
        request.server_interface,
        request.tftp_server_ip,
        on_output=emit,
        sleep_fn=sleep_fn,
    )
    if not network_result.ok:
        return network_result

    if request.transfer_method == TRANSFER_TFTP_PUT:
        put_result = run_tftp_put_transfer(request.firmware_path, on_output=emit)
        if not put_result.ok:
            return put_result
        _write_signal_file(securecrt_target.command_signal_path)
        emit("Tftp Put 已完成，已允许 SecureCRT 进入最终登录监控。")
    else:
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


def run_tftp_put_transfer(
    firmware_path: Path,
    device_ip: str = TFTP_PUT_DEVICE_IP,
    on_output: Optional[Callable[[str], None]] = None,
    timeout_seconds: float = TFTP_PUT_TIMEOUT_SECONDS,
) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    command = ["tftp", "-i", device_ip, "put", str(firmware_path)]
    emit(f"执行 Tftp Put：tftp -i {device_ip} put \"{firmware_path}\"")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return CommandResult(False, "系统未找到 tftp 命令，请在 Windows 功能中启用 TFTP 客户端。")
    except subprocess.TimeoutExpired:
        return CommandResult(False, f"Tftp Put 执行超时（>{int(timeout_seconds)} 秒）。")
    except Exception as exc:
        return CommandResult(False, f"Tftp Put 执行异常：{exc}")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        emit(f"Tftp Put 输出：{stdout}")
    if stderr:
        emit(f"Tftp Put 错误：{stderr}")
    emit(f"Tftp Put 返回码：{result.returncode}")
    if result.returncode != 0:
        detail = stderr or stdout or "无输出"
        return CommandResult(False, f"Tftp Put 失败：{detail}")
    return CommandResult(True, "Tftp Put 成功。")


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

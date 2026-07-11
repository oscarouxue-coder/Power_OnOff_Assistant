from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from line_check_assistant.network_ops import CommandResult, enable_adapter, set_static_ip
from line_check_assistant.old_tool_automation import automate_power_on
from src.core import SerialSessionManager, TftpServerHandle, upload_firmware, vlan_to_serial_port
from src.models import FullPackageUpgradeRequest, SerialSettings


TRANSFER_TFTP_COMMAND = "Tftp指令"
TRANSFER_TFTP_PUT = "Tftp Put"
TFTP_PUT_DEVICE_IP = "192.168.1.1"
POWER_ON_WAIT_SECONDS = 10
POWER_RECYCLE_AFTER_UPGRADE_SECONDS = 90
POWER_ON_SETTLE_SECONDS = 120
BOOT_LOGIN_TIMEOUT_SECONDS = 600
TFTP_COMMAND_TIMEOUT_SECONDS = 1800
TFTP_PUT_TIMEOUT_SECONDS = 600
FINAL_LOGIN_TIMEOUT_SECONDS = 1200
TFTP_SUBNET_MASK = "255.255.255.0"
BOOT_USERNAME = "telecomadmin"
BOOT_PASSWORD = "nE7jA%5m"
FACTORY_RESET_COMMAND = "firstboot -y;reboot"


class SerialUpgradeController:
    def __init__(self, session, sleep_fn: Callable[[float], None] = time.sleep) -> None:
        self.session = session
        self.sleep = sleep_fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def wait_for_boot_login(self, power_started: threading.Event, timeout_seconds: float = BOOT_LOGIN_TIMEOUT_SECONDS) -> CommandResult:
        if not power_started.wait(timeout_seconds):
            return CommandResult(False, "等待旧开关机工具 Start ALL 信号超时。")
        start = self.session.cursor()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not self._cancel.is_set():
            self.session.write(b"\r")
            found = self.session.wait_for_any(("username:", "user name:", "passvord:", "password:", "#", ">"), 1, start)
            if found in ("#", ">"):
                return CommandResult(True, "boot 已进入命令行。")
            if found:
                result = self._login_boot()
                if result.ok:
                    return result
                start = self.session.cursor()
        return CommandResult(False, "进入 boot 或 boot 登录超时。")

    def _login_boot(self) -> CommandResult:
        for _attempt in range(3):
            cursor = self.session.cursor()
            prompt = self.session.wait_for_any(("username:", "user name:", "passvord:", "password:"), 5, cursor)
            if prompt is None:
                self.session.write(b"\r")
                continue
            if prompt.startswith("user"):
                self.session.write(BOOT_USERNAME.encode("utf-8"))
                self.sleep(0.3)
                self.session.write(b"\r")
                if self.session.wait_for_any(("passvord:", "password:"), 30, cursor) is None:
                    continue
            self.session.write(BOOT_PASSWORD.encode("utf-8"), sensitive=True)
            self.sleep(0.3)
            self.session.write(b"\r", sensitive=True)
            result = self.session.wait_for_any(("#", ">", "login incorrect", "incorrect"), 20, cursor)
            if result in ("#", ">"):
                return CommandResult(True, "boot 登录完成。")
        return CommandResult(False, "boot 登录失败。")

    def send_tftp_command_and_wait(self, command: str) -> CommandResult:
        cursor = self.session.cursor()
        self.session.send_line(command)
        if self.session.wait_for_all(("done", "write"), TFTP_COMMAND_TIMEOUT_SECONDS, cursor):
            return CommandResult(True, "检测到 TFTP 传输完成标记 done + write。")
        return CommandResult(False, "等待样机串口 TFTP 完成标记超时。")

    def monitor_post_tftp(self, seconds: float = POWER_RECYCLE_AFTER_UPGRADE_SECONDS) -> bool:
        cursor = self.session.cursor()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._cancel.is_set():
            marker = self.session.wait_for_any(("boot", "bood"), 1, cursor)
            if marker:
                self.sleep(1)
                self.session.send_line("reset")
                return True
        return False

    def login_final_system(self, username: str, password: str) -> CommandResult:
        cursor = self.session.cursor()
        for attempt in range(1, 6):
            self.session.write(b"\r")
            login_wait = 900 if attempt == 1 else 2
            if self.session.wait_for_any(("login",), login_wait, cursor) is None:
                continue
            self.session.send_line(username)
            if self.session.wait_for_any(("password", "passvord"), 60, cursor) is None:
                continue
            self.session.send_line(password, sensitive=True)
            result = self.session.wait_for_any(("#", ">", "login incorrect", "incorrect"), 60, cursor)
            if result in ("#", ">"):
                return CommandResult(True, "最终系统登录完成。")
            if attempt < 5:
                self.sleep(2)
        return CommandResult(False, "最终系统登录失败。")

    def restore_factory_if_enabled(self, enabled: bool) -> None:
        if not enabled:
            return
        self.session.write(FACTORY_RESET_COMMAND.encode("utf-8"))
        self.sleep(1)
        self.session.write(b"\r")
        self.sleep(8)


def prepare_tftp_network(server_interface: str, server_ip: str, on_output: Callable[[str], None] | None = None, sleep_fn=time.sleep) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    emit(f"准备 TFTP 网卡：{server_interface} -> {server_ip}")
    enabled = enable_adapter(server_interface)
    if not enabled.ok:
        return enabled
    emit(enabled.message)
    sleep_fn(1)
    configured = set_static_ip(server_interface, server_ip, TFTP_SUBNET_MASK)
    if not configured.ok:
        return configured
    emit(configured.message)
    sleep_fn(1)
    return CommandResult(True, f"TFTP 网卡已准备好：{server_interface} / {server_ip}")


def run_single_full_package_upgrade(
    tool_root: Path,
    old_tool_path: Path,
    request: FullPackageUpgradeRequest,
    session_manager: SerialSessionManager,
    on_output: Callable[[str], None] | None = None,
    on_session_ready: Callable[[str, object, Path], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    port = vlan_to_serial_port(request.vlan)
    owner = f"upgrade:{uuid.uuid4()}"
    log_dir = Path(r"F:\Aouxue\开关机环境搭建工具\开关机执行工具\样机串口日志")
    if not Path(log_dir.anchor).exists():
        log_dir = Path(r"D:\样机串口日志")
    log_path = log_dir / f"{request.vlan}_upgrade_{time.strftime('%Y%m%d_%H%M%S')}.log"
    session = None
    server = None
    controller = None
    try:
        settings = SerialSettings(port=port)
        session = session_manager.acquire_control(owner, settings, log_path)
        if on_session_ready:
            on_session_ready(request.vlan, session, log_path)
        controller = SerialUpgradeController(session, sleep_fn)
        power_started = threading.Event()
        boot_result: list[CommandResult] = []

        def boot_worker() -> None:
            boot_result.append(controller.wait_for_boot_login(power_started))

        worker = threading.Thread(target=boot_worker, name=f"boot-login-{port}", daemon=True)
        worker.start()

        def on_power_output(line: str) -> None:
            emit(line)
            if "已点击 Start ALL" in line:
                power_started.set()
                emit("旧工具已点击 Start ALL，已立即开始串口回车进入 boot。")

        emit(f"开始调用自动上电模块，程控电源串口：{request.power_serial_port}")
        power = automate_power_on(old_tool_path, serial_port=request.power_serial_port, wait_seconds=POWER_ON_WAIT_SECONDS, on_output=on_power_output)
        if not power.ok:
            controller.cancel()
            return power
        power_started.set()
        worker.join(timeout=BOOT_LOGIN_TIMEOUT_SECONDS + 5)
        if not boot_result:
            return CommandResult(False, "boot 登录线程未返回结果。")
        if not boot_result[0].ok:
            return boot_result[0]
        emit("boot 登录完成，准备传输环境。")

        network = prepare_tftp_network(request.server_interface, request.tftp_server_ip, emit, sleep_fn)
        if not network.ok:
            return network
        if request.transfer_method == TRANSFER_TFTP_PUT:
            upload_firmware(
                request.firmware_path,
                TFTP_PUT_DEVICE_IP,
                request.tftp_server_ip,
                timeout_seconds=TFTP_PUT_TIMEOUT_SECONDS,
                on_output=emit,
            )
        else:
            server = TftpServerHandle(request.tftp_server_ip, request.firmware_path)
            server.start()
            emit(f"TFTPy 服务已监听：{request.tftp_server_ip}:69，文件映射为 tclinux_allinone。")
            tftp_result = controller.send_tftp_command_and_wait(f"tftp {request.tftp_server_ip}:tclinux_allinone")
            if not tftp_result.ok:
                return tftp_result
            server.stop()
            server = None

        emit("TFTP 传输完成，开始观察 boot 重启标记。")
        reset_sent = controller.monitor_post_tftp()
        if reset_sent:
            emit("检测到 Boot/Bood，已发送 reset，等待 120 秒。")
            sleep_fn(POWER_ON_SETTLE_SECONDS)
        else:
            emit("未检测到 boot reset，开始重新上电。")
            repower = automate_power_on(old_tool_path, serial_port=request.power_serial_port, wait_seconds=POWER_ON_WAIT_SECONDS, on_output=emit)
            if not repower.ok:
                return repower
            sleep_fn(POWER_ON_SETTLE_SECONDS)
        final = controller.login_final_system(request.final_username, request.final_password)
        if not final.ok:
            return final
        controller.restore_factory_if_enabled(request.restore_factory)
        return CommandResult(True, f"{request.vlan} 全包升级流程完成。")
    except Exception as exc:
        return CommandResult(False, f"{request.vlan} 串行升级异常：{exc}")
    finally:
        if server is not None:
            server.stop()
        if controller is not None:
            controller.cancel()
        if session is not None:
            session_manager.release(owner, port)

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from line_check_assistant.network_ops import CommandResult, enable_adapter, set_static_ip
from src.config import DEFAULT_LOG_DIR
from src.core import SerialSessionManager, TftpServerHandle, upload_firmware, vlan_to_serial_port
from src.models import FullPackageUpgradeRequest, SerialSettings
from .power_on_service import power_on_selected_channels


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
BOOT_USERNAME_PROMPTS = ("username:", "user name:")
BOOT_PASSWORD_PROMPTS = ("passvord:", "password:")
BOOT_LOGIN_RESULT_PROMPTS = ("#", ">", "login incorrect", "incorrect")
BOOT_USERNAME_STABILITY_SECONDS = 1.0


class SerialUpgradeController:
    def __init__(self, session, sleep_fn: Callable[[float], None] = time.sleep) -> None:
        self.session = session
        self.sleep = sleep_fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def wait_for_boot_login(self, power_started: threading.Event, timeout_seconds: float = BOOT_LOGIN_TIMEOUT_SECONDS) -> CommandResult:
        if not power_started.wait(timeout_seconds):
            return CommandResult(False, "等待程控电源写入上电帧信号超时。")
        try:
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline and not self._cancel.is_set():
                # 每轮只发送一个探测回车。_login_boot 命中完整、稳定的 UserName 后，
                # 不会再进入本循环发送周期性回车。
                result = self._login_boot(max_attempts=1, username_timeout_seconds=1)
                if result.ok:
                    return result
        except RuntimeError as exc:
            # 串口异常(未打开 / 已关闭 / 写入失败)，立即停掉 cancel 让上层清理。
            self._cancel.set()
            return CommandResult(False, f"串口交互异常，boot 登录中断:{exc}")
        except Exception as exc:
            self._cancel.set()
            return CommandResult(False, f"boot 登录异常:{exc}")
        return CommandResult(False, "进入 boot 或 boot 登录超时。")

    def _wait_for_clean_boot_username(self, timeout_seconds: float) -> str | None:
        """发送一次探测回车，等待未夹带旧 Password 的完整 UserName 提示符。"""
        username_cursor = self.session.cursor()
        self.session.write(b"\r")
        username_prompt = self.session.wait_for_any(
            BOOT_USERNAME_PROMPTS,
            timeout_seconds,
            username_cursor,
        )
        if username_prompt not in BOOT_USERNAME_PROMPTS:
            return None

        # 某些上电瞬态会一次性吐出上一轮的 UserName/Password。此时尚未填写用户名，
        # 因而 Password 不可能是本轮用户名提交后的有效密码提示，必须整轮丢弃。
        early_password = self.session.wait_for_any(
            BOOT_PASSWORD_PROMPTS,
            BOOT_USERNAME_STABILITY_SECONDS,
            username_cursor,
        )
        if early_password in BOOT_PASSWORD_PROMPTS:
            return None
        return username_prompt

    def _login_boot(self, max_attempts: int = 3, username_timeout_seconds: float = 5) -> CommandResult:
        """按完整且稳定的 UserName/Password 提示符逐步登录 boot。"""
        for _attempt in range(max_attempts):
            try:
                username_prompt = self._wait_for_clean_boot_username(username_timeout_seconds)
                if username_prompt not in BOOT_USERNAME_PROMPTS:
                    continue

                # 仅在完整 UserName: / User Name: 提示符稳定到达后发送用户名。
                self.session.write(BOOT_USERNAME.encode("utf-8"))
                self.sleep(1.0)
                self.session.write(b"\r")

                # 用户名回车后重新取游标；此前缓存中的 Password: 不得触发密码发送。
                password_cursor = self.session.cursor()
                password_prompt = self.session.wait_for_any(BOOT_PASSWORD_PROMPTS, 30, password_cursor)
                if password_prompt not in BOOT_PASSWORD_PROMPTS:
                    continue

                # 仅在完整 Password: / Passvord: 提示符稳定到达后发送密码。
                self.session.write(BOOT_PASSWORD.encode("utf-8"), sensitive=True)
                self.sleep(1.0)
                self.session.write(b"\r", sensitive=True)
                result_cursor = self.session.cursor()
                result = self.session.wait_for_any(BOOT_LOGIN_RESULT_PROMPTS, 20, result_cursor)
                if result in ("#", ">"):
                    return CommandResult(True, "boot 登录完成。")
            except RuntimeError as exc:
                return CommandResult(False, f"串口交互异常，boot 登录失败:{exc}")
            except Exception as exc:
                return CommandResult(False, f"boot 登录异常:{exc}")
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

    def interrupt_boot_with_enter(self, enter_interval: float = 1.0, timeout_seconds: float = BOOT_LOGIN_TIMEOUT_SECONDS) -> CommandResult:
        """reboot 后每隔 enter_interval 秒发送一次回车,直到检测到 boot/login 提示符。

        用于在样机重启后通过串口回车中断自动启动,使其进入 boot 菜单;
        命中提示符后由调用方决定后续是 _login_boot 还是直接执行命令。
        """
        cursor = self.session.cursor()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not self._cancel.is_set():
            self.session.write(b"\r")
            found = self.session.wait_for_any(
                ("username:", "user name:", "passvord:", "password:", "#", ">"),
                enter_interval,
                cursor,
            )
            if found:
                return CommandResult(True, f"检测到串口提示符 {found!r},停止发送回车。")
        return CommandResult(False, "reboot 后未检测到 boot/login 提示符,样机可能未按预期重启。")

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


def _run_tftp_command_with_power_supply(
    request: FullPackageUpgradeRequest,
    controller: "SerialUpgradeController",
    port: str,
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None],
) -> CommandResult:
    """Tftp指令(样机主动拉固件)链路:程控电源上电中断 boot,TFTP 完成后未命中 reset 时再次上电复位。

    串口已开启且 controller 已绑定,本函数在 run_single_full_package_upgrade 的 try 块内调用,
    异常由调用方统一捕获。
    """
    emit(
        f"开始直接控制程控电源，串口：{request.power_serial_port}，"
        f"通道：{request.power_channel}。"
    )
    power_started = threading.Event()
    boot_result: list[CommandResult] = []

    def boot_worker() -> None:
        try:
            boot_result.append(controller.wait_for_boot_login(power_started))
        except Exception as exc:
            # 兜底:任何未在 wait_for_boot_login 内捕获的异常都变成 CommandResult 失败,
            # 避免 daemon 线程因为未处理 RuntimeError 退出后,主线程看到的是空 boot_result
            # (此时错误信息只有笼统的 "boot 登录线程未返回结果。",看不到底层原因)。
            controller.cancel()
            boot_result.append(CommandResult(False, f"boot 登录线程异常:{exc}"))

    worker = threading.Thread(target=boot_worker, name=f"boot-login-{port}", daemon=True)
    worker.start()

    def on_channel_powered(channel: int) -> None:
        if channel == request.power_channel:
            emit("程控电源已写入上电帧，等待电源动作完成后开始串口回车进入 boot。")

    power = power_on_selected_channels(
        request.power_serial_port,
        [request.power_channel],
        wait_seconds=POWER_ON_WAIT_SECONDS,
        on_output=emit,
        on_channel_powered=on_channel_powered,
    )
    if not power.ok:
        controller.cancel()
        return power
    # 程控电源动作完成后间隔 1 秒再触发 worker 发送首帧 \r;
    # 现场需求:先让上电状态稳定,再开始串口交互,避免首帧 \r 与上电瞬态信号叠加。
    sleep_fn(1.0)
    # 在电源函数返回且稳定等待结束后才放行 worker，避免 on_channel_powered 回调过早启动登录。
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

    server = TftpServerHandle(request.tftp_server_ip, request.firmware_path)
    server.start()
    # 当配置的 IP 在本机网卡上不可绑定时(例如 network_card_ip.ini 与实际网络状态不一致),
    # TftpServerHandle 会自动回退到 INADDR_ANY;这里使用实际监听值,便于现场排查。
    listened_ip = server.bind_ip_actually_used or "0.0.0.0"
    emit(f"TFTPy 服务已监听：{listened_ip}:{server.port}，文件映射为 tclinux_allinone。")
    tftp_result = controller.send_tftp_command_and_wait(
        f"tftp {request.tftp_server_ip}:tclinux_allinone"
    )
    if not tftp_result.ok:
        return tftp_result
    server.stop()

    emit("TFTP 传输完成，开始观察 boot 重启标记。")
    reset_sent = controller.monitor_post_tftp()
    if reset_sent:
        emit("检测到 Boot/Bood，已发送 reset，等待 120 秒。")
        sleep_fn(POWER_ON_SETTLE_SECONDS)
    else:
        emit("未检测到 boot reset，开始重新上电。")
        repower = power_on_selected_channels(
            request.power_serial_port,
            [request.power_channel],
            wait_seconds=POWER_ON_WAIT_SECONDS,
            on_output=emit,
        )
        if not repower.ok:
            return repower
        sleep_fn(POWER_ON_SETTLE_SECONDS)
    final = controller.login_final_system(request.final_username, request.final_password)
    if not final.ok:
        return final
    controller.restore_factory_if_enabled(request.restore_factory)
    return CommandResult(True, f"{request.vlan} 全包升级流程完成。")


def run_single_full_package_upgrade(
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
    # 统一使用全局默认日志目录(目前固定为 D:\Serial_Log),与其他串口日志合并保存
    log_dir = DEFAULT_LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
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

        # Tftp指令(样机主动拉固件):使用程控电源上电中断 boot,
        # TFTP 传输完成后未命中 boot reset 时再次上电复位。
        # 该分支内部自管 TFTPy server,不在主流程中启停。
        if request.transfer_method == TRANSFER_TFTP_COMMAND:
            return _run_tftp_command_with_power_supply(
                request=request,
                controller=controller,
                port=port,
                emit=emit,
                sleep_fn=sleep_fn,
            )

        # Tftp Put(本机推到 192.168.1.1):保持"手动上电 + reboot + 回车"流程,
        # 不操作程控电源,假设样机已由用户手动上电。
        emit(f"串口 {port} 已开启,准备用超级用户登录当前运行的样机系统。")

        emit(f"正在使用超级用户 {request.final_username} 登录样机...")
        final_login = controller.login_final_system(request.final_username, request.final_password)
        if not final_login.ok:
            return final_login
        emit(f"超级用户登录完成:{final_login.message}")

        # 第 2 步:触发样机重启,准备进入 boot 菜单。
        controller.session.send_line("reboot")
        sleep_fn(3)
        emit("已发送 reboot,准备每秒发送回车中断样机自动启动进入 boot。")

        # 第 3 步:每秒发送回车,直到检测到 boot/login 提示符。
        interrupt = controller.interrupt_boot_with_enter(
            enter_interval=1.0,
            timeout_seconds=BOOT_LOGIN_TIMEOUT_SECONDS,
        )
        if not interrupt.ok:
            return interrupt
        emit(f"{interrupt.message},准备登录 boot。")

        # 第 4 步:用 boot 用户名/密码完成 boot 登录,后续流程保持不变。
        boot_login = controller._login_boot()
        if not boot_login.ok:
            return boot_login
        emit("boot 登录完成，准备传输环境。")

        network = prepare_tftp_network(request.server_interface, request.tftp_server_ip, emit, sleep_fn)
        if not network.ok:
            return network
        # Tftp Put 分支:直接推送固件到 192.168.1.1。Tftp指令 分支在上方已经 return,不会落到这里。
        upload_firmware(
            request.firmware_path,
            TFTP_PUT_DEVICE_IP,
            request.tftp_server_ip,
            timeout_seconds=TFTP_PUT_TIMEOUT_SECONDS,
            on_output=emit,
        )

        emit("TFTP 传输完成，开始观察 boot 重启标记。")
        reset_sent = controller.monitor_post_tftp()
        if reset_sent:
            emit("检测到 Boot/Bood，已发递 reset，等待 120 秒。")
        else:
            # Tftp Put 流程不再操作程控电源,等待 120 秒后继续登录最终系统;
            # 若设备未自动重启,后续 login_final_system 会报错,由用户手动介入。
            emit("未检测到 boot reset，等待 120 秒后继续登录最终系统。")
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

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from line_check_assistant.network_ops import CommandResult, enable_adapter, set_static_ip
from src.config import DEFAULT_LOG_DIR
from src.core import SerialSessionManager, TftpServerHandle, upload_firmware, vlan_to_serial_port, wait_for_bindable_ip
from src.core.power_supply import ProgrammablePowerSupply
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
TFTP_BIND_READY_TIMEOUT_SECONDS = 15.0
BOOT_USERNAME = "telecomadmin"
BOOT_PASSWORD = "nE7jA%5m"
FACTORY_RESET_COMMAND = "firstboot -y;reboot"
BOOT_USERNAME_PROMPTS = ("username:", "user name:")
BOOT_PASSWORD_PROMPTS = ("passvord:", "password:")
BOOT_LOGIN_RESULT_PROMPTS = ("#", ">", "login incorrect", "incorrect")
TFTP_PUT_BOOT_RESULT_PROMPTS = ("=>", "ecnt>", "u-boot>", "#", ">", "username:", "user name:")
BOOT_USERNAME_STABILITY_SECONDS = 1.0

# _display() 使用 decode(errors="replace"),无效 UTF-8 字节会渲染为该字符。
# 检测到该字符即视为响应包含乱码字节。
GARBLED_REPLACEMENT_MARKER = "�"
GARBLED_LOGIN_RESULT_PROMPTS = ("#", ">", "ecnt>", "u-boot>")


def _looks_like_garbled_response(text: str) -> bool:
    """粗略判断：响应中包含 UTF-8 解码失败标记即视为乱码。"""
    return bool(text) and GARBLED_REPLACEMENT_MARKER in text


@dataclass(frozen=True)
class FullPackageUpgradeItemResult:
    request: FullPackageUpgradeRequest
    result: CommandResult


class UpgradePowerCycleCoordinator:
    """按程控电源 COM 口串行化短暂断电/上电帧，启动等待在锁外并行进行。

    同时持有每条 COM 口的 `ProgrammablePowerSupply` 长连接，使同一批次内多个通道的
    上下电复用同一个串口句柄，避免每台样机都 open/close 一次 COM。
    调用方需在批次结束后调用 `close()`，或用 `with` 语法自动收尾。
    """

    def __init__(
        self,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        supply_factory: Callable[..., ProgrammablePowerSupply] = ProgrammablePowerSupply,
    ) -> None:
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._supply_factory = supply_factory
        self._locks: dict[str, threading.Lock] = {}
        self._supplies: dict[str, ProgrammablePowerSupply] = {}
        self._locks_guard = threading.Lock()

    def __enter__(self) -> "UpgradePowerCycleCoordinator":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def _get_or_open_supply(
        self,
        port: str,
        on_output: Callable[[str], None] | None,
    ) -> ProgrammablePowerSupply:
        with self._locks_guard:
            supply = self._supplies.get(port)
            if supply is None:
                # supply 自身的 _on_output 会负责 emit 帧日志；这里只在 open/close 时各打一行。
                supply = self._supply_factory(port, on_output=on_output)
                supply.open()
                self._supplies[port] = supply
            return supply

    def power_on_channel(
        self,
        serial_port: str,
        channel: int,
        *,
        wait_seconds: float,
        on_output: Callable[[str], None] | None = None,
        on_channel_powered: Callable[[int], None] | None = None,
    ) -> CommandResult:
        port = serial_port.strip().upper()
        with self._locks_guard:
            lock = self._locks.setdefault(port, threading.Lock())

        with lock:
            command_started = self._monotonic()
            try:
                supply = self._get_or_open_supply(port, on_output)
                supply.power_on_channels([channel], on_channel_powered=on_channel_powered)
                result = CommandResult(True, f"程控电源已直接上电：{port}，通道 {channel}。")
            except Exception as exc:
                result = CommandResult(False, f"程控电源直接上电失败：{exc}")
            command_elapsed = self._monotonic() - command_started

        if result.ok:
            remaining = max(0.0, float(wait_seconds) - command_elapsed)
            if remaining:
                if on_output:
                    on_output(f"程控电源通道 {channel} 指令完成，继续等待样机启动：{remaining:.1f} 秒。")
                self._sleep(remaining)
        return result

    def close(self) -> None:
        """关闭本批次持有的所有程控电源 COM；幂等。"""
        with self._locks_guard:
            supplies = list(self._supplies.values())
            self._supplies.clear()
        for supply in supplies:
            try:
                supply.close()
            except Exception:
                # 关闭失败不抛：批次结束语义以"已尝试关闭"为准。
                pass


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
                    # 现场：UART 输出损坏导致 Password: 提示符也是乱码；UART 输入正常。
                    # 若用户名回显含有 UTF-8 替换标记,盲发密码一次,如果样机已接受账号
                    # 就能进入 shell;否则继续常规重试。
                    recent_text = self.session.peek_since(password_cursor)
                    if recent_text and _looks_like_garbled_response(recent_text):
                        salvage = self._try_login_after_garbled_username(password_cursor)
                        if salvage.ok:
                            return salvage
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

    def _try_login_after_garbled_username(self, password_cursor: int) -> CommandResult:
        """用户名回显异常时盲发一次密码,验证样机是否已接受账号。

        适用场景:UART 输出损坏导致 Password: 提示符也是乱码,但 UART 输入正常。
        如果样机实际已接受账号,密码后应进入 shell 提示符。
        """
        self.session.write(BOOT_PASSWORD.encode("utf-8"), sensitive=True)
        self.sleep(1.0)
        self.session.write(b"\r", sensitive=True)
        result_cursor = self.session.cursor()
        result = self.session.wait_for_any(GARBLED_LOGIN_RESULT_PROMPTS, 12, result_cursor)
        if result in GARBLED_LOGIN_RESULT_PROMPTS:
            return CommandResult(
                True,
                f"用户名回显乱码，盲发密码后检测到 shell 提示符 {result!r}。",
            )
        return CommandResult(False, "用户名回显乱码，盲发密码未检测到 shell 提示符。")

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

    def wait_for_tftp_put_boot_username(self, timeout_seconds: float = BOOT_LOGIN_TIMEOUT_SECONDS) -> CommandResult:
        """仅供 Tftp Put 使用：循环回车，等待同事流程使用的 UserName 提示符。"""
        cursor = self.session.cursor()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not self._cancel.is_set():
            self.session.write(b"\r")
            username_prompt = self.session.wait_for_any(BOOT_USERNAME_PROMPTS, 1.0, cursor)
            if username_prompt in BOOT_USERNAME_PROMPTS:
                return CommandResult(True, "检测到 UserName 提示符。")
        return CommandResult(False, "等待 UserName 提示符超时，未进入 boot 登录阶段。")

    def login_tftp_put_boot_after_username(self) -> CommandResult:
        """仅供 Tftp Put 使用：复用同事 serial_upgrade.py 的 UserName 后 boot 登录时序。"""
        for attempt in range(1, 4):
            try:
                # 同事脚本在 UserName: 后直接发送账号加回车，随后等待 Password:。
                # 游标必须在写用户名之前取得：部分样机在用户名回显的同一批数据中
                # 已输出 Password:；若等到写入后再取游标，会把该提示当成旧数据跳过。
                password_cursor = self.session.cursor()
                self.session.write(f"{BOOT_USERNAME}\r".encode("utf-8"))
                self.sleep(0.3)
                password_prompt = self.session.wait_for_any(BOOT_PASSWORD_PROMPTS, 10, password_cursor)
                if password_prompt not in BOOT_PASSWORD_PROMPTS:
                    # 现场：UART 输出损坏导致 Password: 提示符也是乱码;盲发密码一次验证登录。
                    recent_text = self.session.peek_since(password_cursor)
                    if recent_text and _looks_like_garbled_response(recent_text):
                        salvage = self._try_login_after_garbled_username(password_cursor)
                        if salvage.ok:
                            return salvage
                    return CommandResult(False, "boot 登录未检测到 Password 提示符。")

                # ECNT> 等 shell 提示同样可能在密码回显的同一批数据中到达，
                # 因此也必须在写密码前记录游标，不能等 1 秒后再开始等待。
                result_cursor = self.session.cursor()
                self.session.write(f"{BOOT_PASSWORD}\r".encode("utf-8"), sensitive=True)
                self.sleep(1.0)
                result = self.session.wait_for_any(TFTP_PUT_BOOT_RESULT_PROMPTS, 12, result_cursor)
                if result in ("=>", "ecnt>", "u-boot>", "#", ">"):
                    return CommandResult(True, "boot 登录完成。")
                if result in BOOT_USERNAME_PROMPTS and attempt < 3:
                    # 同事脚本检测到 UserName 再次出现时会重试账号密码。
                    self.sleep(1.0)
                    continue
                return CommandResult(False, "boot 登录后未检测到 shell 提示符。")
            except RuntimeError as exc:
                return CommandResult(False, f"串口交互异常，boot 登录失败:{exc}")
            except Exception as exc:
                return CommandResult(False, f"boot 登录异常:{exc}")
        return CommandResult(False, "boot 登录失败。")

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

    def restore_factory_if_enabled(
        self,
        enabled: bool,
        on_command_sent: Callable[[str], None] | None = None,
    ) -> None:
        if not enabled:
            return
        self.session.write(FACTORY_RESET_COMMAND.encode("utf-8"))
        if on_command_sent:
            on_command_sent(f"TX {FACTORY_RESET_COMMAND}")
        self.sleep(1)
        self.session.write(b"\r")
        self.sleep(8)


def prepare_tftp_network(
    server_interface: str,
    server_ip: str,
    on_output: Callable[[str], None] | None = None,
    sleep_fn=time.sleep,
    bind_ready_fn: Callable[[str, float], bool] | None = None,
) -> CommandResult:
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
    emit(f"等待 TFTP 网卡 IP {server_ip} 完成绑定（最长 {TFTP_BIND_READY_TIMEOUT_SECONDS:.0f} 秒）。")
    ready = (bind_ready_fn or wait_for_bindable_ip)(server_ip, TFTP_BIND_READY_TIMEOUT_SECONDS)
    if not ready:
        return CommandResult(
            False,
            f"TFTP 网卡 IP 在 {TFTP_BIND_READY_TIMEOUT_SECONDS:.0f} 秒内仍不可绑定：{server_interface} / {server_ip}。"
            "请检查网卡 IP 状态、重复 IP 或驱动。",
        )
    return CommandResult(True, f"TFTP 网卡已准备好：{server_interface} / {server_ip}")


def _power_cycle_current_channel(
    request: FullPackageUpgradeRequest,
    emit: Callable[[str], None],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    power_cycle_coordinator: UpgradePowerCycleCoordinator | None = None,
    wait_seconds: float = 0,
    on_channel_powered: Callable[[int], None] | None = None,
) -> CommandResult:
    """对当前请求对应的程控电源通道执行一次下电 + 上电。

    并行模式下走 UpgradePowerCycleCoordinator 串行化电源 COM 口;
    串行模式下走 power_on_selected_channels(内部已封装关闭 + 开启 + 1.5s/3s 缓冲)。
    """
    if power_cycle_coordinator is not None:
        return power_cycle_coordinator.power_on_channel(
            request.power_serial_port,
            request.power_channel,
            wait_seconds=wait_seconds,
            on_output=emit,
            on_channel_powered=on_channel_powered,
        )
    return power_on_selected_channels(
        request.power_serial_port,
        [request.power_channel],
        wait_seconds=wait_seconds,
        on_output=emit,
        on_channel_powered=on_channel_powered,
        sleep_fn=sleep_fn,
    )


def _run_tftp_command_with_power_supply(
    request: FullPackageUpgradeRequest,
    controller: "SerialUpgradeController",
    port: str,
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None],
    power_cycle_coordinator: UpgradePowerCycleCoordinator | None = None,
    strict_tftp_bind: bool = False,
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

    def power_on_current_channel(on_powered: Callable[[int], None] | None = None) -> CommandResult:
        return _power_cycle_current_channel(
            request=request,
            emit=emit,
            sleep_fn=sleep_fn,
            power_cycle_coordinator=power_cycle_coordinator,
            wait_seconds=POWER_ON_WAIT_SECONDS,
            on_channel_powered=on_powered,
        )

    power = power_on_current_channel(on_channel_powered)
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

    server = TftpServerHandle(
        request.tftp_server_ip,
        request.firmware_path,
        allow_any_fallback=not strict_tftp_bind,
    )
    try:
        server.start()
        listened_ip = server.bind_ip_actually_used or "0.0.0.0"
        emit(f"TFTPy 服务已监听：{listened_ip}:{server.port}，文件映射为 tclinux_allinone。")
        tftp_result = controller.send_tftp_command_and_wait(
            f"tftp {request.tftp_server_ip}:tclinux_allinone"
        )
        if not tftp_result.ok:
            return tftp_result
    finally:
        server.stop()

    emit("TFTP 传输完成，开始观察 boot 重启标记。")
    reset_sent = controller.monitor_post_tftp()
    if reset_sent:
        emit("检测到 Boot/Bood，已发送 reset，等待 120 秒。")
        sleep_fn(POWER_ON_SETTLE_SECONDS)
    else:
        emit("未检测到 boot reset，开始重新上电。")
        repower = power_on_current_channel()
        if not repower.ok:
            return repower
        sleep_fn(POWER_ON_SETTLE_SECONDS)
    final = controller.login_final_system(request.final_username, request.final_password)
    if not final.ok:
        return final
    controller.restore_factory_if_enabled(request.restore_factory, on_command_sent=emit)
    return CommandResult(True, f"{request.vlan} 全包升级流程完成。")


def run_single_full_package_upgrade(
    request: FullPackageUpgradeRequest,
    session_manager: SerialSessionManager,
    on_output: Callable[[str], None] | None = None,
    on_session_ready: Callable[[str, object, Path], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    power_cycle_coordinator: UpgradePowerCycleCoordinator | None = None,
    strict_tftp_bind: bool = False,
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
                power_cycle_coordinator=power_cycle_coordinator,
                strict_tftp_bind=strict_tftp_bind,
            )

        # Tftp Put(本机推到 192.168.1.1):先对当前通道下电 + 上电；
        # 串口看到 UserName 后，按同事 serial_upgrade.py 的 boot 登录时序进入 shell，
        # 上传仍使用主程序的 TFTPy Client。
        emit(
            f"Tftp Put 前置下电 + 上电：程控电源串口 {request.power_serial_port}，"
            f"通道 {request.power_channel}。"
        )
        power_cycle = _power_cycle_current_channel(
            request=request,
            emit=emit,
            sleep_fn=sleep_fn,
            power_cycle_coordinator=power_cycle_coordinator,
            wait_seconds=0,
        )
        if not power_cycle.ok:
            return power_cycle
        emit(f"程控电源下电 + 上电完成:{power_cycle.message}")
        emit(f"串口 {port} 已开启，准备等待 UserName 提示符进入 boot。")

        # 电源动作结束后先留出 1 秒稳定窗口，再开始循环回车等待 UserName。
        sleep_fn(1.0)
        username_prompt = controller.wait_for_tftp_put_boot_username()
        if not username_prompt.ok:
            return username_prompt
        emit("检测到 UserName 提示符，开始使用 boot 用户名和密码登录。")
        boot_login = controller.login_tftp_put_boot_after_username()
        if not boot_login.ok:
            return boot_login
        emit("boot 登录完成，准备使用 TFTPy 传输环境。")

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
        controller.restore_factory_if_enabled(request.restore_factory, on_command_sent=emit)
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


def run_parallel_tftp_command_upgrades(
    requests: Iterable[FullPackageUpgradeRequest],
    session_manager: SerialSessionManager,
    *,
    max_workers: int = 2,
    on_output: Callable[[str, str], None] | None = None,
    on_session_ready: Callable[[str, object, Path], None] | None = None,
    on_item_started: Callable[[FullPackageUpgradeRequest], None] | None = None,
    on_item_complete: Callable[[FullPackageUpgradeItemResult], None] | None = None,
) -> list[FullPackageUpgradeItemResult]:
    """以固定并行度执行样机主动拉取固件流程，单台失败不取消其它样机。"""
    all_requests = list(requests)
    pending = list(all_requests)
    if max_workers < 1:
        raise ValueError("并行升级数量必须至少为 1。")
    if any(request.transfer_method != TRANSFER_TFTP_COMMAND for request in pending):
        raise ValueError("并行升级仅支持 Tftp指令。")

    active: dict[object, FullPackageUpgradeRequest] = {}
    completed: dict[int, FullPackageUpgradeItemResult] = {}

    def run_one(request: FullPackageUpgradeRequest, coordinator: UpgradePowerCycleCoordinator) -> CommandResult:
        def emit(message: str) -> None:
            if on_output:
                on_output(request.vlan, message)

        return run_single_full_package_upgrade(
            request,
            session_manager,
            on_output=emit,
            on_session_ready=on_session_ready,
            power_cycle_coordinator=coordinator,
            strict_tftp_bind=True,
        )

    # coordinator 用 with 包裹，批次结束自动 close 所有持有的程控电源 COM。
    with UpgradePowerCycleCoordinator() as coordinator, ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="parallel-tftp"
    ) as executor:
        while pending or active:
            while pending and len(active) < max_workers:
                request = pending.pop(0)
                if on_item_started:
                    on_item_started(request)
                active[executor.submit(run_one, request, coordinator)] = request

            done, _pending_futures = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                request = active.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = CommandResult(False, f"{request.vlan} 并行升级异常：{exc}")
                item = FullPackageUpgradeItemResult(request=request, result=result)
                completed[id(request)] = item
                if on_item_complete:
                    on_item_complete(item)

    return [completed[id(request)] for request in all_requests]


def run_parallel_tftp_put_upgrades(
    requests: Iterable[FullPackageUpgradeRequest],
    session_manager: SerialSessionManager,
    *,
    max_workers: int = 2,
    on_output: Callable[[str, str], None] | None = None,
    on_session_ready: Callable[[str, object, Path], None] | None = None,
    on_item_started: Callable[[FullPackageUpgradeRequest], None] | None = None,
    on_item_complete: Callable[[FullPackageUpgradeItemResult], None] | None = None,
) -> list[FullPackageUpgradeItemResult]:
    """以固定并行度执行本机 TFTPy Client 推送固件流程，单台失败不取消其它样机。"""
    all_requests = list(requests)
    pending = list(all_requests)
    if max_workers < 1:
        raise ValueError("并行升级数量必须至少为 1。")
    if any(request.transfer_method != TRANSFER_TFTP_PUT for request in pending):
        raise ValueError("并行升级仅支持 Tftp Put。")

    # Tftp Put 的 TFTPy 是客户端；协调器只保护共享程控电源 COM 口，
    # 各 VLAN 的串口、网卡准备和上传仍由各 worker 独立推进。
    active: dict[object, FullPackageUpgradeRequest] = {}
    completed: dict[int, FullPackageUpgradeItemResult] = {}

    def run_one(request: FullPackageUpgradeRequest, coordinator: UpgradePowerCycleCoordinator) -> CommandResult:
        def emit(message: str) -> None:
            if on_output:
                on_output(request.vlan, message)

        return run_single_full_package_upgrade(
            request,
            session_manager,
            on_output=emit,
            on_session_ready=on_session_ready,
            power_cycle_coordinator=coordinator,
            strict_tftp_bind=False,
        )

    with UpgradePowerCycleCoordinator() as coordinator, ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="parallel-tftp-put"
    ) as executor:
        while pending or active:
            while pending and len(active) < max_workers:
                request = pending.pop(0)
                if on_item_started:
                    on_item_started(request)
                active[executor.submit(run_one, request, coordinator)] = request

            done, _pending_futures = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                request = active.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = CommandResult(False, f"{request.vlan} 并行升级异常：{exc}")
                item = FullPackageUpgradeItemResult(request=request, result=result)
                completed[id(request)] = item
                if on_item_complete:
                    on_item_complete(item)

    return [completed[id(request)] for request in all_requests]

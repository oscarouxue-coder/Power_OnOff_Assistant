"""AI 专用诊断传输：锁源 Telnet 优先，仅连接失效时回退共享串口。"""
from __future__ import annotations

import re
import time

from src.core.telnet_transport import TelnetSession


class DebugConnectionUnavailable(RuntimeError):
    pass


class DiagnosticTransport:
    def __init__(self, target, stop, emit, serial_acquire, busy=lambda _target: False,
                 telnet_factory=TelnetSession, clock=time.monotonic):
        self.target, self.stop, self.emit = target, stop, emit
        self.serial_acquire, self.busy = serial_acquire, busy
        self.telnet_factory, self.clock = telnet_factory, clock
        self.session = None
        self.release_serial = None
        self.kind = ""
        self.serial_cancel = None

    def check(self):
        if self.stop.is_set() or (self.serial_cancel is not None and self.serial_cancel.is_set()):
            raise InterruptedError("诊断采集已取消")
        if self.busy(self.target):
            raise RuntimeError("目标正在执行设备操作，跳过主动采集")

    @staticmethod
    def _shell(text):
        lines = str(text).replace("\r", "\n").strip().splitlines()
        if not lines or re.search(r"(?i)u-?boot|bootloader|bootrom|ecnt|bood|=>", lines[-1]):
            return False
        return bool(re.fullmatch(r"(?:[\w@:/~.()\[\] -]{0,160})?[#$]", lines[-1].strip()))

    def _wait(self, cursor, condition, seconds=10):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            self.check()
            if getattr(self.session, "error", None):
                raise DebugConnectionUnavailable("诊断连接接收失败")
            text = self.session.peek_since(cursor)
            if condition(text):
                return text
            if self.stop.wait(0.05):
                raise InterruptedError("诊断采集已取消")
        raise DebugConnectionUnavailable("诊断连接等待超时")

    def _login(self, serial=False):
        target = self.target
        # 串口只观察现有历史，不发唤醒键、不打断 Boot、不执行可编辑的登录后命令。
        cursor = max(0, self.session.cursor() - 8192) if serial else 0
        text = self._wait(cursor, lambda s: self._shell(s) or
                          s.rstrip().casefold().endswith(target.user_prompt.casefold()) or
                          s.rstrip().casefold().endswith(target.password_prompt.casefold()))
        if self._shell(text):
            if serial and not (re.search(r"(?i)BusyBox|Linux version|OpenWrt|login:", text)
                               or re.search(r"[\w-]+@[\w.-]+:[^\r\n]*[#$]\s*$", text)):
                raise DebugConnectionUnavailable("串口提示符身份不明，仅保留被动日志")
            return
        if text.rstrip().casefold().endswith(target.user_prompt.casefold()):
            cursor = self.session.cursor()
            self.emit(f"[AI Debug] TX 登录用户名：{target.username}")
            self.session.send_line(target.username, sensitive=True)
            text = self._wait(cursor, lambda s: self._shell(s) or s.rstrip().casefold().endswith(target.password_prompt.casefold()))
        if not self._shell(text):
            cursor = self.session.cursor()
            self.emit(f"[AI Debug] TX 登录密码：{target.password}")
            self.session.send_line(target.password, sensitive=True)
            text = self._wait(cursor, self._shell)
        if not self._shell(text):
            raise DebugConnectionUnavailable("未确认安全 Shell；不执行回车或登录后自定义命令")

    def open(self):
        self.check()
        target = self.target
        self.emit(f"[AI Debug] 尝试 Telnet：通道{target.channel}，源IP={target.bind_ip}，目标={target.host}:{target.telnet_port}")
        try:
            self.session = self.telnet_factory(bind_ip=target.bind_ip, device_host=target.host,
                device_port=target.telnet_port, known_secrets=(target.password,), connect_timeout=10)
            self._login()
            self.kind = "Telnet"
            self.emit("[AI Debug] Telnet 登录成功")
            return self
        except InterruptedError:
            self.close()
            raise
        except Exception as exc:
            if self.session is not None:
                self.session.close()
            self.session = None
            self.emit(f"[AI Debug] Telnet 不可用（{type(exc).__name__}），尝试目标串口；连接原因不代表根因")
        return self.fallback_serial()

    def fallback_serial(self):
        self.check()  # 忙碌不允许通过串口绕过。
        if self.session is not None:
            self.close()
        target = self.target
        try:
            self.session, self.release_serial, self.serial_cancel = self.serial_acquire(target, self.stop)
            self.kind = "串口"
            self._login(serial=True)
            self.emit(f"[AI Debug] 已复用通道{target.channel} {target.port}，Shell已确认")
            return self
        except Exception:
            self.close()
            raise

    def command(self, command, timeout=20, cleanup=False):
        if not cleanup:
            self.check()
        if self.session is None:
            raise DebugConnectionUnavailable("诊断连接未建立")
        # command 只来自本地工具注册表，禁止暴露给模型任意文本参数。
        self.emit(f"[AI Debug][{self.kind}] TX：{command}")
        cursor = self.session.cursor()
        self.session.send_line(command, sensitive=False)
        deadline, last_change, last_cursor = self.clock() + timeout, self.clock(), cursor
        while self.clock() < deadline:
            if not cleanup:
                self.check()
            current = self.session.cursor()
            if current != last_cursor:
                last_cursor, last_change = current, self.clock()
            if current - cursor > 768 * 1024:
                raise RuntimeError("采集输出超过768 KiB限制")
            text = self.session.peek_since(cursor)
            if self._shell(text) and current > cursor and self.clock() - last_change >= 0.2:
                return text
            if getattr(self.session, "error", None):
                raise DebugConnectionUnavailable("命令已下发但连接失效，执行结果待核实，不自动重发")
            time.sleep(0.05) if cleanup else self.stop.wait(0.05)
        raise DebugConnectionUnavailable("命令已下发但等待结束超时，执行结果待核实，不自动重发")

    def close(self):
        if self.release_serial:
            self.release_serial()
            self.release_serial = None
        elif self.session is not None:
            self.session.close()
        self.session = None

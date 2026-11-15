"""AI 专用诊断传输：锁源 Telnet 优先，仅连接失效时回退共享串口。"""
from __future__ import annotations

import re
import time

from src.core.telnet_transport import TelnetSession


class DebugConnectionUnavailable(RuntimeError):
    pass


class DebugSessionInvalid(DebugConnectionUnavailable):
    """An invalid/uncertain session must never trigger automatic command replay."""
    def __init__(self, reason, dispatched=False):
        super().__init__(reason)
        self.dispatched = dispatched


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
        self.invalid_reason = ""
        self._verified_cursor = 0

    def check(self, cleanup=False):
        if not cleanup and (self.stop.is_set() or (self.serial_cancel is not None and self.serial_cancel.is_set())):
            raise InterruptedError("诊断采集已取消")
        if self.busy(self.target):
            raise RuntimeError("目标正在执行设备操作，跳过主动采集")

    def _invalidate(self, reason, dispatched=False):
        self.invalid_reason = reason
        self.emit("[AI Debug] 会话失效：" + reason + "；不自动重发命令")
        self.close()
        raise DebugSessionInvalid(reason, dispatched)

    def _alive(self):
        session = self.session
        return (session is not None and not getattr(session, "error", None)
                and getattr(session, "_closed", False) is not True
                and getattr(session, "closed", False) is not True)

    def _guard_shell(self, cleanup=False):
        self.check(cleanup=cleanup)
        if self.invalid_reason:
            raise DebugSessionInvalid(self.invalid_reason)
        if not self._alive():
            self._invalidate("连接已关闭或接收失败，旧Shell资格失效")
        cursor = self.session.cursor()
        tail = self.session.peek_since(max(0, cursor - 8192))
        # Only inspect unsolicited output since the last completed interaction.
        # Historical boot messages inside a completed dmesg/logread are evidence.
        delta = self.session.peek_since(max(self._verified_cursor, cursor - 8192))
        reboot = re.search(r"(?im)^(?:U-Boot\s+\d|Booting Linux|Linux version\s+\d|reboot:\s*Restarting system)", delta)
        if reboot or not self._shell(tail):
            self._invalidate("当前不是可确认的Linux Shell或观察到重新启动/登录")

    def _send_login(self, value, prompt, label):
        self.check()
        if not self._alive():
            self._invalidate("登录期间连接失效")
        cursor = self.session.cursor()
        tail = self.session.peek_since(max(0, cursor - 8192))
        if not prompt or not tail.rstrip().casefold().endswith(prompt.casefold()):
            self._invalidate("登录提示已变化，未发送登录资料")
        self.emit(f"[AI Debug] TX 登录{label}：{value}")
        self.session.send_line(value, sensitive=True)

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
            self._send_login(target.username, target.user_prompt, "用户名")
            text = self._wait(cursor, lambda s: self._shell(s) or s.rstrip().casefold().endswith(target.password_prompt.casefold()))
        if not self._shell(text):
            cursor = self.session.cursor()
            self._send_login(target.password, target.password_prompt, "密码")
            text = self._wait(cursor, self._shell)
        if not self._shell(text):
            raise DebugConnectionUnavailable("未确认安全 Shell；不执行回车或登录后自定义命令")

    def open(self):
        self.check()
        self.invalid_reason = ""
        target = self.target
        self.emit(f"[AI Debug] 尝试 Telnet：通道{target.channel}，源IP={target.bind_ip}，目标={target.host}:{target.telnet_port}")
        try:
            self.session = self.telnet_factory(bind_ip=target.bind_ip, device_host=target.host,
                device_port=target.telnet_port, known_secrets=(target.password,), connect_timeout=10)
            self._login()
            self._verified_cursor = self.session.cursor()
            self.kind = "Telnet"
            self.emit("[AI Debug] Telnet 登录成功")
            return self
        except (InterruptedError, DebugSessionInvalid):
            self.close()
            raise
        except Exception as exc:
            if self.session is not None:
                self.session.close()
            self.session = None
            telnet_error = f"{type(exc).__name__}: {exc}"
            self.emit(f"[AI Debug] Telnet 不可用（{telnet_error}），尝试目标串口；连接原因不代表根因")
        try:
            return self.fallback_serial()
        except InterruptedError:
            raise
        except Exception as exc:
            raise DebugConnectionUnavailable(f"Telnet连接失败：{telnet_error}；串口连接失败：{exc}") from exc

    def fallback_serial(self):
        self.check()  # 忙碌不允许通过串口绕过。
        if self.session is not None:
            self.close()
        target = self.target
        try:
            self.session, self.release_serial, self.serial_cancel = self.serial_acquire(target, self.stop)
            self.kind = "串口"
            self._login(serial=True)
            self._verified_cursor = self.session.cursor()
            self.invalid_reason = ""
            self.emit(f"[AI Debug] 已复用通道{target.channel} {target.port}，Shell已确认")
            return self
        except Exception:
            self.close()
            raise

    def command(self, command, timeout=20, cleanup=False):
        self._guard_shell(cleanup=cleanup)
        # 单次诊断只传固定命令；完整对话命令须先经过独立风险审查/具体操作授权。
        self.emit(f"[AI Debug][{self.kind}] TX：{command}")
        cursor = self.session.cursor()
        try:
            self.session.send_line(command, sensitive=False)
        except Exception:
            self._invalidate("发送失败，可能已部分下发，执行结果待核实", dispatched=True)
        deadline, last_change, last_cursor = self.clock() + timeout, self.clock(), cursor
        while self.clock() < deadline:
            self.check(cleanup=cleanup)
            if not self._alive():
                self._invalidate("命令已下发但连接失效，执行结果待核实", dispatched=True)
            current = self.session.cursor()
            if current != last_cursor:
                last_cursor, last_change = current, self.clock()
            if current - cursor > 768 * 1024:
                self._invalidate("采集输出超过768 KiB限制，执行结果待核实", dispatched=True)
            text = self.session.peek_since(cursor)
            last_line = text.replace("\r", "\n").strip().splitlines()[-1:] or [""]
            login_prompts = tuple(p.casefold() for p in (self.target.user_prompt, self.target.password_prompt) if p)
            if (re.search(r"(?i)^(?:=>|U-Boot[^\n]*[>#]|Bootloader[^\n]*[>#])\s*$", last_line[0])
                    or (login_prompts and last_line[0].rstrip().casefold().endswith(login_prompts))):
                self._invalidate("命令期间进入Boot或重新登录，执行结果待核实", dispatched=True)
            if self._shell(text) and current > cursor and self.clock() - last_change >= 0.2:
                self._verified_cursor = current
                return text
            if getattr(self.session, "error", None):
                self._invalidate("命令已下发但连接失效，执行结果待核实", dispatched=True)
            time.sleep(0.05) if cleanup else self.stop.wait(0.05)
        self._invalidate("命令已下发但等待结束超时，执行结果待核实", dispatched=True)

    def close(self):
        if self.release_serial:
            self.release_serial()
            self.release_serial = None
        elif self.session is not None:
            self.session.close()
        self.session = None

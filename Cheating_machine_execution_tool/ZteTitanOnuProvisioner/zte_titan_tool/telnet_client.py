import re
import socket
import telnetlib
import threading
import time
from typing import Callable, Iterable, List, Optional, Pattern

from .commands import contains_cli_error
from .models import OltConnection
from .parser import clean_terminal_text


PROMPT_RE = re.compile(r"(?:^|\n)[^\n]*[>#]\s*$", re.MULTILINE)
LOGIN_FAILURE_RE = re.compile(
    r"incorrect|login failed|authentication failed|access denied",
    re.IGNORECASE,
)


class OltTelnetError(RuntimeError):
    pass


class OltCommandError(OltTelnetError):
    def __init__(self, command: str, output: str):
        super().__init__(f"OLT 拒绝命令：{command}")
        self.command = command
        self.output = output


class OperationCancelled(OltTelnetError):
    pass


class TitanTelnetSession:
    def __init__(
        self,
        connection: OltConnection,
        logger: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.connection = connection
        self.logger = logger or (lambda _message: None)
        self.cancel_event = cancel_event or threading.Event()
        self._tn: Optional[telnetlib.Telnet] = None

    def _log(self, message: str):
        self.logger(message.rstrip())

    def _check_cancelled(self):
        if self.cancel_event.is_set():
            self.close()
            raise OperationCancelled("操作已取消")

    def connect(self):
        errors = self.connection.validate()
        if errors:
            raise OltTelnetError("；".join(errors))
        self._check_cancelled()
        self._log(
            f"连接 {self.connection.host}:{self.connection.port}"
            + (
                f"，源地址 {self.connection.source_ip}"
                if self.connection.source_ip
                else ""
            )
        )
        source_address = (
            (self.connection.source_ip, 0) if self.connection.source_ip else None
        )
        sock = socket.create_connection(
            (self.connection.host, self.connection.port),
            timeout=self.connection.timeout,
            source_address=source_address,
        )
        sock.settimeout(0.5)
        self._tn = telnetlib.Telnet()
        self._tn.sock = sock
        self._login()
        self._log("登录成功")

    def _login(self):
        username_prompt = self._read_until_patterns(
            [
                re.compile(r"user\s*name\s*:", re.IGNORECASE),
                re.compile(r"username\s*:", re.IGNORECASE),
                re.compile(r"login\s*:", re.IGNORECASE),
            ],
            self.connection.timeout,
        )
        if not re.search(r"user\s*name|username|login", username_prompt, re.I):
            raise OltTelnetError("未检测到用户名提示")
        self._write_line(self.connection.username)
        password_prompt = self._read_until_patterns(
            [re.compile(r"password\s*:", re.IGNORECASE)],
            self.connection.timeout,
        )
        if not re.search(r"password", password_prompt, re.I):
            raise OltTelnetError("未检测到密码提示")
        self._write_line(self.connection.password)
        login_output = self._read_until_patterns(
            [PROMPT_RE, LOGIN_FAILURE_RE], self.connection.timeout + 5
        )
        if LOGIN_FAILURE_RE.search(login_output):
            raise OltTelnetError("OLT 登录失败，请检查用户名、密码和 VTY 限制")
        if not PROMPT_RE.search(login_output):
            raise OltTelnetError("登录后未检测到 ZXAN 提示符")

    def _write_line(self, text: str):
        if not self._tn:
            raise OltTelnetError("Telnet 会话尚未建立")
        self._check_cancelled()
        self._tn.write(text.encode("utf-8") + b"\r\n")

    def _read_available(self, duration: float = 0.25) -> bytes:
        if not self._tn:
            raise OltTelnetError("Telnet 会话尚未建立")
        end = time.monotonic() + duration
        data = bytearray()
        while time.monotonic() < end:
            self._check_cancelled()
            try:
                chunk = self._tn.read_very_eager()
            except EOFError as exc:
                raise OltTelnetError("OLT 关闭了 Telnet 连接") from exc
            except (OSError, socket.timeout):
                chunk = b""
            if chunk:
                data.extend(chunk)
                end = time.monotonic() + 0.15
            else:
                time.sleep(0.03)
        return bytes(data)

    def _read_until_patterns(
        self, patterns: Iterable[Pattern[str]], timeout: float
    ) -> str:
        end = time.monotonic() + timeout
        data = bytearray()
        compiled = list(patterns)
        while time.monotonic() < end:
            chunk = self._read_available(0.2)
            if chunk:
                data.extend(chunk)
                text = clean_terminal_text(data.decode("utf-8", errors="replace"))
                if any(pattern.search(text) for pattern in compiled):
                    return text
            time.sleep(0.03)
        text = clean_terminal_text(data.decode("utf-8", errors="replace"))
        tail = text[-500:].strip()
        raise OltTelnetError(f"等待 OLT 响应超时；末尾内容：{tail or '<空>'}")

    def execute(
        self,
        command: str,
        timeout: float = 20,
        fail_on_cli_error: bool = True,
    ) -> str:
        if not command or "\n" in command or "\r" in command:
            raise ValueError("每次只能执行一条非空命令")
        self._log(f">>> {command}")
        self._write_line(command)
        end = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < end:
            chunk = self._read_available(0.3)
            if chunk:
                data.extend(chunk)
                text = clean_terminal_text(data.decode("utf-8", errors="replace"))
                if "--More--" in text or "---- More" in text:
                    if not self._tn:
                        raise OltTelnetError("Telnet 会话已关闭")
                    self._tn.write(b" ")
                    data[:] = data.replace(b"--More--", b"")
                    data[:] = data.replace(b"---- More", b"")
                    continue
                if PROMPT_RE.search(text):
                    output = text.strip()
                    self._log(output)
                    if fail_on_cli_error and contains_cli_error(output):
                        raise OltCommandError(command, output)
                    return output
            time.sleep(0.03)
        partial = clean_terminal_text(data.decode("utf-8", errors="replace"))
        raise OltTelnetError(
            f"命令执行超时：{command}；末尾内容：{partial[-500:].strip() or '<空>'}"
        )

    def execute_many(self, commands: Iterable[str], timeout: float = 20) -> List[str]:
        outputs = []
        for command in commands:
            self._check_cancelled()
            outputs.append(self.execute(command, timeout=timeout))
        return outputs

    def best_effort_end(self):
        if not self._tn:
            return
        try:
            self.execute("end", timeout=3, fail_on_cli_error=False)
        except Exception:
            pass

    def close(self):
        tn, self._tn = self._tn, None
        if tn:
            try:
                tn.close()
            except Exception:
                pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

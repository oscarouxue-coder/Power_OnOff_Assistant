"""已注册 ONU 只读查询会话：避免配置块的 > 被误认为命令结束。"""

from __future__ import annotations

import re
import time
from typing import Iterable, Pattern

from src.core.zte_olt_telnet import (
    CLI_ERROR_RE,
    PROMPT_RE,
    OltCommandError,
    OltTelnetError,
    ZteOltTelnetSession,
    clean_terminal_text,
)


class RegisteredOnuQuerySession(ZteOltTelnetSession):
    """仅用于已注册查询，保留原接收等待与分页机制，不影响配置/删除会话。"""

    _query_prompt_re: Pattern[str] | None = None

    def _read_until_patterns(self, patterns: Iterable[Pattern[str]], timeout: float) -> str:
        compiled = tuple(patterns)
        text = super()._read_until_patterns(compiled, timeout)
        if PROMPT_RE in compiled and PROMPT_RE.search(text):
            prompt = text.rstrip().rsplit("\n", 1)[-1]
            if not prompt or not prompt.endswith(("#", ">")):
                raise OltTelnetError("登录后无法确认完整 OLT 提示符")
            self._query_prompt_re = re.compile(r"(?:^|\n)" + re.escape(prompt) + r"\s*\Z")
        return text

    def execute(self, command: str, timeout: float = 20, fail_on_cli_error: bool = True) -> str:
        # 保留原会话的逐条发送、0.3秒读取窗口、0.15秒空闲等待、分页和错误判据。
        # 此入口全程处于登录后的执行模式，不需要接受配置模式提示符。
        if not command or "\n" in command or "\r" in command:
            raise ValueError("每次只能执行一条非空命令")
        if self._query_prompt_re is None:
            raise OltTelnetError("已注册查询会话尚未确认 OLT 提示符")
        self._log(f"TX OLT {command}")
        self._write_line(command)
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
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
                if self._query_prompt_re.search(text):
                    output = text.strip()
                    self._log(output)
                    if fail_on_cli_error and CLI_ERROR_RE.search(output):
                        raise OltCommandError(command, output)
                    return output
            time.sleep(0.03)
        partial = clean_terminal_text(data.decode("utf-8", errors="replace"))
        raise OltTelnetError(
            f"命令执行超时：{command}；末尾内容：{partial[-500:].strip() or '<空>'}"
        )

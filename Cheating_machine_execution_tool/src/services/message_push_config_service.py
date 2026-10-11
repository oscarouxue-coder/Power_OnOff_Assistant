"""钉钉配置编辑服务；不发送消息，不在异常中包含凭据。"""
from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Mapping

from src.core.dingtalk_robot import send_text


DEFAULTS = {"dingtalk_flag": "0", "webhook": "", "secret": "", "at_all": "0"}
SECTION = "dingtalk_config"


def send_test_message(values: Mapping[str, object]) -> None:
    """显式试发使用页面快照，不保存配置，不受自动推送开关限制。"""
    values = MessagePushConfigService.validate(values)
    send_text(values['webhook'], values['secret'],
              'LineCheckAssistant 消息推送测试：收到此消息表示钉钉机器人推送正常。',
              at_all=values['at_all'] == '1')


class MessagePushConfigService:
    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> dict[str, str]:
        try:
            parser = configparser.RawConfigParser()
            if self.config_path.exists():
                with self.config_path.open(encoding="utf-8-sig") as stream:
                    parser.read_file(stream)
            values = {key: parser.get(SECTION, key, fallback=value)
                      for key, value in DEFAULTS.items()}
            return self.validate(values)
        except (OSError, UnicodeError, configparser.Error, ValueError):
            raise ValueError("消息推送配置读取失败，请检查 config.ini 的格式和访问权限。") from None

    @staticmethod
    def validate(values: Mapping[str, object]) -> dict[str, str]:
        result = {key: str(values.get(key, default)) for key, default in DEFAULTS.items()}
        for key in ("dingtalk_flag", "at_all"):
            if result[key] not in {"0", "1"}:
                raise ValueError("消息推送开关必须为 0 或 1。")
        if any("\n" in value or "\r" in value for value in result.values()):
            raise ValueError("消息推送字段不能包含换行。")
        return result

    def save(self, values: Mapping[str, object]) -> None:
        updates = self.validate(values)
        try:
            # 每次保存读取最新内容，保留同次保存中其它 store 刚更新的字段。
            raw = self.config_path.read_bytes() if self.config_path.exists() else b""
            bom = raw.startswith(b"\xef\xbb\xbf")
            lines = raw.decode("utf-8-sig").splitlines(keepends=True)
            newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
            start, end = None, len(lines)
            for index, line in enumerate(lines):
                section = re.match(r"^\s*\[([^]]+)\]", line)
                if section:
                    if start is not None:
                        end = index
                        break
                    if section[1].strip().lower() == SECTION:
                        start = index
            if start is None:
                if lines and not lines[-1].endswith(("\r", "\n")):
                    lines[-1] += newline
                lines.append(f"[{SECTION}]{newline}")
                start, end = len(lines) - 1, len(lines)
            pattern = re.compile(r"^([ \t]*)([^#;][^=:#\r\n]*?)([ \t]*[=:][ \t]*)([^\r\n]*)(\r?\n)?$")
            for index in range(start + 1, end):
                match = pattern.match(lines[index])
                if match:
                    key = match[2].strip().lower()
                    if key in updates:
                        lines[index] = f"{match[1]}{match[2]}{match[3]}{updates.pop(key)}{match[5] or ''}"
            if updates:
                if end and not lines[end - 1].endswith(("\r", "\n")):
                    lines[end - 1] += newline
                lines[end:end] = [f"{key} = {value}{newline}" for key, value in updates.items()]
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8"))
        except (OSError, UnicodeError):
            raise OSError("消息推送配置保存失败，请检查 config.ini 的格式和写入权限。") from None

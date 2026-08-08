"""新工具中编辑旧工具 ``config.ini [ui_defaults]`` 的配置存储。"""
from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Mapping


UI_DEFAULTS_SECTION = "ui_defaults"
OTHER_CONFIG_SECTION = "other_config"
TELNET_ENABLE_OPTION = "telnet_enable"
COMMAND_FAIL_RETRY_INTERVAL_OPTION = "command_fail_retry_interval_time"
REQUIRED_OPTIONS = (
    "communication_method",
    TELNET_ENABLE_OPTION,
    "baud_rate",
    "selected_profile",
    "startup_time",
    "interval_time",
    "number_of_tests",
    "wait_command_done",
)
NONNEGATIVE_INTEGER_OPTIONS = (
    "startup_time",
    "interval_time",
    "wait_command_done",
)


class LegacyUiDefaultsStore:
    """加载和保存 ``[ui_defaults]``，不改写配置文件其它内容。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> dict[str, str]:
        if not self.config_path.is_file():
            return {}
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")
        if not parser.has_section(UI_DEFAULTS_SECTION):
            return {}
        return {
            key: value.strip()
            for key, value in parser.items(UI_DEFAULTS_SECTION)
        }

    def save(self, values: Mapping[str, object]) -> None:
        normalized = self.validate(values)
        self._update_section(normalized)

    def validate(self, values: Mapping[str, object]) -> dict[str, str]:
        return self._validate(values)

    def update_telnet_enable_mirror(self, telnet_default_on: object) -> None:
        """保存 ``telnet_default_on`` 的反向镜像；配置文件不存在时不创建。"""
        if not self.config_path.is_file():
            return
        mirrored_value = "0" if bool(telnet_default_on) else "1"
        self._update_section({TELNET_ENABLE_OPTION: mirrored_value})

    def update_command_fail_retry_interval_mirror(self, interval: object) -> None:
        """同步旧工具 ``[other_config]`` 的同名重试间隔。"""
        if not self.config_path.is_file():
            return
        self._update_section(
            {COMMAND_FAIL_RETRY_INTERVAL_OPTION: str(interval).strip()},
            section_name=OTHER_CONFIG_SECTION,
        )

    @staticmethod
    def _validate(values: Mapping[str, object]) -> dict[str, str]:
        normalized = {
            str(key).strip(): str(value).strip()
            for key, value in values.items()
            if str(key).strip()
        }
        missing = [key for key in REQUIRED_OPTIONS if key not in normalized]
        if missing:
            raise ValueError(f"[ui_defaults] 缺少配置项：{', '.join(missing)}")

        communication_method = normalized["communication_method"].lower()
        if communication_method not in {"telnet", "ssh"}:
            raise ValueError("[ui_defaults] communication_method 只能是 telnet 或 ssh")
        normalized["communication_method"] = communication_method

        if normalized[TELNET_ENABLE_OPTION] not in {"0", "1"}:
            raise ValueError("[ui_defaults] telnet_enable 只能是 0 或 1")
        if not normalized["selected_profile"]:
            raise ValueError("[ui_defaults] selected_profile 不能为空")

        baud_rate = _parse_integer(normalized, "baud_rate")
        if baud_rate <= 0:
            raise ValueError("[ui_defaults] baud_rate 必须是正整数")
        for option in NONNEGATIVE_INTEGER_OPTIONS:
            if _parse_integer(normalized, option) < 0:
                raise ValueError(f"[ui_defaults] {option} 不能小于 0")
        if _parse_integer(normalized, "number_of_tests") < 1:
            raise ValueError("[ui_defaults] number_of_tests 不能小于 1")
        return normalized

    def _update_section(
        self,
        updates: Mapping[str, str],
        section_name: str = UI_DEFAULTS_SECTION,
    ) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.is_file():
            with self.config_path.open("r", encoding="utf-8", newline="") as file:
                lines = file.readlines()
        else:
            lines = []

        newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        section_start, section_end = _find_section_bounds(lines, section_name)
        if section_start is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            if lines and lines[-1].strip():
                lines.append(newline)
            lines.append(f"[{section_name}]{newline}")
            section_start = len(lines) - 1
            section_end = len(lines)

        pending = {key.lower(): (key, value) for key, value in updates.items()}
        option_pattern = re.compile(
            r"^(\s*)([^#;][^=:#]*?)(\s*=\s*)([^\r\n]*)(\r?\n)?$"
        )
        for index in range(section_start + 1, section_end):
            match = option_pattern.match(lines[index])
            if not match:
                continue
            normalized_key = match.group(2).strip().lower()
            replacement = pending.pop(normalized_key, None)
            if replacement is None:
                continue
            _key, value = replacement
            line_ending = match.group(5) or ""
            lines[index] = (
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
                f"{value}{line_ending}"
            )

        additions = [f"{key} = {value}{newline}" for key, value in pending.values()]
        if additions:
            if section_end > 0 and not lines[section_end - 1].endswith(("\n", "\r")):
                lines[section_end - 1] += newline
            lines[section_end:section_end] = additions

        with self.config_path.open("w", encoding="utf-8", newline="") as file:
            file.writelines(lines)


def _parse_integer(values: Mapping[str, str], option: str) -> int:
    raw_value = values[option]
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"[ui_defaults] {option} 必须是整数：{raw_value!r}") from exc


def _find_section_bounds(
    lines: list[str],
    section_name: str,
) -> tuple[int | None, int]:
    section_start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("[") and stripped.endswith("]")):
            continue
        current_section = stripped[1:-1].strip().lower()
        if section_start is not None:
            return section_start, index
        if current_section == section_name.lower():
            section_start = index
    return section_start, len(lines)


__all__ = [
    "COMMAND_FAIL_RETRY_INTERVAL_OPTION",
    "LegacyUiDefaultsStore",
    "OTHER_CONFIG_SECTION",
    "REQUIRED_OPTIONS",
    "TELNET_ENABLE_OPTION",
    "UI_DEFAULTS_SECTION",
]

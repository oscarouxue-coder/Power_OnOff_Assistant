from __future__ import annotations

from pathlib import Path
from typing import Optional


POWER_ON_NAME = "Fully_powered_on"
POWER_ON_FILE = "Fully_powered_on_config.ini"
POWER_ON_ENTRY = f"{POWER_ON_NAME} = {POWER_ON_FILE}"


POWER_ON_CONFIG_TEXT = """[telnet]
request_url = http://192.168.29.1
port = 23
user = sdmc
password = 1234
timeout = 10
input_user_flag = ogin:
input_password_flag = Password:
login_success_flag = #
telnet_need_enter_password_flag = 0
telnet_no_user_password_flag=0
only_power_off_on = 0

[order]

[connect_wifi]
"""


def prepare_power_on_default(config_dir: Path) -> str:
    config_dir.mkdir(parents=True, exist_ok=True)
    power_config = config_dir / POWER_ON_FILE
    if not power_config.exists():
        power_config.write_text(POWER_ON_CONFIG_TEXT, encoding="utf-8")

    main_config = config_dir / "config.ini"
    if not main_config.exists():
        main_config.write_text(f"[config]\n{POWER_ON_ENTRY}\n", encoding="utf-8")
        return f"已创建 {main_config}，并设置 {POWER_ON_NAME} 为第一项。"

    original = main_config.read_text(encoding="utf-8")
    updated = _move_power_entry_to_top(original)
    if updated != original:
        main_config.write_text(updated, encoding="utf-8")
        return f"已将 {POWER_ON_NAME} 移到 [config] 第一项，旧软件启动后应默认选中它。"
    return f"{POWER_ON_NAME} 已经是 [config] 第一项。"


def _move_power_entry_to_top(text: str) -> str:
    lines = text.splitlines()
    config_start = _find_section(lines, "config")
    if config_start is None:
        prefix = [f"[config]", POWER_ON_ENTRY, ""]
        return "\n".join(prefix + lines) + _final_newline(text)

    section_end = len(lines)
    for index in range(config_start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_end = index
            break

    before = lines[: config_start + 1]
    body = lines[config_start + 1 : section_end]
    after = lines[section_end:]

    filtered_body = [
        line for line in body
        if not _is_power_entry(line)
    ]
    new_body = [POWER_ON_ENTRY] + filtered_body
    return "\n".join(before + new_body + after) + _final_newline(text)


def _find_section(lines: list[str], section_name: str) -> Optional[int]:
    target = f"[{section_name.lower()}]"
    for index, line in enumerate(lines):
        if line.strip().lower() == target:
            return index
    return None


def _is_power_entry(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.startswith("#"):
        return False
    key = stripped.split("=", 1)[0].strip()
    return key.lower() == POWER_ON_NAME.lower()


def _final_newline(text: str) -> str:
    return "\n" if text.endswith(("\n", "\r\n")) else ""

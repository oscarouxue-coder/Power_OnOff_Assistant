from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_UPGRADE_MODE = "全包升级"
DEFAULT_UPGRADE_TRANSFER = "Tftp Put"
DEFAULT_UPGRADE_EXECUTION_MODE = "串行"
SAMPLE_UPGRADE_SECTION = "sample_upgrade"

# 全包升级并行上限：UI、coordinator 校验、tests 都引用此常量。
# 任何超过此值的配置会在 save/load 时被钳制到合法区间。
MAX_PARALLEL_UPGRADES = 8
# 默认仍保持 2 台，匹配当前真实样机已验收的行为，避免一升级就跳到 8 台。
DEFAULT_PARALLEL_COUNT = 2


def clamp_parallel_count(value: int | str | None) -> int:
    """把任意输入钳到 [1, MAX_PARALLEL_UPGRADES]；非法输入回退到默认值。"""
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL_COUNT
    if parsed < 1:
        return 1
    if parsed > MAX_PARALLEL_UPGRADES:
        return MAX_PARALLEL_UPGRADES
    return parsed


@dataclass
class SampleUpgradeSettings:
    upgrade_mode: str = DEFAULT_UPGRADE_MODE
    transfer_method: str = DEFAULT_UPGRADE_TRANSFER
    execution_mode: str = DEFAULT_UPGRADE_EXECUTION_MODE
    parallel_count: int = DEFAULT_PARALLEL_COUNT
    restore_factory: bool = False
    username: str = ""
    password: str = ""
    firmware_path: str = ""


class SampleUpgradeSettingsStore:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> SampleUpgradeSettings:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")

        return SampleUpgradeSettings(
            upgrade_mode=parser.get(SAMPLE_UPGRADE_SECTION, "upgrade_mode", fallback=DEFAULT_UPGRADE_MODE),
            transfer_method=parser.get(SAMPLE_UPGRADE_SECTION, "transfer_method", fallback=DEFAULT_UPGRADE_TRANSFER),
            execution_mode=parser.get(SAMPLE_UPGRADE_SECTION, "execution_mode", fallback=DEFAULT_UPGRADE_EXECUTION_MODE),
            parallel_count=clamp_parallel_count(
                parser.get(SAMPLE_UPGRADE_SECTION, "parallel_count", fallback=DEFAULT_PARALLEL_COUNT)
            ),
            restore_factory=parser.getboolean(SAMPLE_UPGRADE_SECTION, "restore_factory", fallback=False),
            username=parser.get(SAMPLE_UPGRADE_SECTION, "username", fallback=""),
            password=parser.get(SAMPLE_UPGRADE_SECTION, "password", fallback=""),
            firmware_path=parser.get(SAMPLE_UPGRADE_SECTION, "firmware_path", fallback=""),
        )

    def save(self, settings: SampleUpgradeSettings) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser[SAMPLE_UPGRADE_SECTION] = {
            "upgrade_mode": settings.upgrade_mode or DEFAULT_UPGRADE_MODE,
            "transfer_method": settings.transfer_method or DEFAULT_UPGRADE_TRANSFER,
            "execution_mode": settings.execution_mode or DEFAULT_UPGRADE_EXECUTION_MODE,
            "parallel_count": str(clamp_parallel_count(settings.parallel_count)),
            "restore_factory": "1" if settings.restore_factory else "0",
            "username": settings.username or "",
            "password": settings.password or "",
            "firmware_path": settings.firmware_path or "",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)
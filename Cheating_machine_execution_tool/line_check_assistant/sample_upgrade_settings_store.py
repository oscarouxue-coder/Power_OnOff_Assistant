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
# 写样机参数并行数默认 1(2026-07-19 用户要求):多台并发容易撞 UBUS HTTP / telnet login / NIC,
# 默认串行更稳;Spinbox 仍允许 1–8 现场上调,升级窗口不受影响。
DEFAULT_PARAMETER_PARALLEL_COUNT = 1


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
    # 写样机参数窗口的「首次登录账号 / 密码」,独立于升级超级凭据,但落到同一 ini 文件,方便现场单点维护。
    parameter_initial_username: str = ""
    parameter_initial_password: str = ""
    # 写样机参数流水线两个可选行为(2026-07-19),与 parameter_initial_* 同级存到 ini。
    # 默认关闭:clear_parameters / exit_aging 都需要操作员在写样机参数窗口勾选才生效。
    parameter_clear_parameters: bool = False
    parameter_exit_aging: bool = False
    # 2026-07-20:全流程执行管道(主界面「检查并执行测试」)新增两个字段:
    # - ``power_operation``:「自动上/下电」子任务的上/下电选项("up" / "down",默认 "up")
    # - ``parameter_table_path``:「写样机参数」子任务的参数表文件路径(.xlsx/.xls/.csv)
    power_operation: str = "up"
    parameter_table_path: str = ""


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
            parameter_initial_username=parser.get(SAMPLE_UPGRADE_SECTION, "parameter_initial_username", fallback=""),
            parameter_initial_password=parser.get(SAMPLE_UPGRADE_SECTION, "parameter_initial_password", fallback=""),
            parameter_clear_parameters=parser.getboolean(SAMPLE_UPGRADE_SECTION, "parameter_clear_parameters", fallback=False),
            parameter_exit_aging=parser.getboolean(SAMPLE_UPGRADE_SECTION, "parameter_exit_aging", fallback=False),
            power_operation=parser.get(
                SAMPLE_UPGRADE_SECTION,
                "power_operation",
                fallback="up",
            ),
            parameter_table_path=parser.get(
                SAMPLE_UPGRADE_SECTION,
                "parameter_table_path",
                fallback="",
            ),
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
            "parameter_initial_username": settings.parameter_initial_username or "",
            "parameter_initial_password": settings.parameter_initial_password or "",
            "parameter_clear_parameters": "1" if settings.parameter_clear_parameters else "0",
            "parameter_exit_aging": "1" if settings.parameter_exit_aging else "0",
            # 2026-07-20:全流程执行管道用的两个新字段。power_operation 仅接受 "up"/"down",
            # 非法值统一回退 "up";parameter_table_path 自由文本(可能是 Windows 长路径)。
            "power_operation": (settings.power_operation or "up").strip().lower()
            if (settings.power_operation or "up").strip().lower() in {"up", "down"}
            else "up",
            "parameter_table_path": settings.parameter_table_path or "",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)
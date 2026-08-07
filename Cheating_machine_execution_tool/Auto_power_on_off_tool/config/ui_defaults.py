"""旧工具主界面启动参数的集中配置加载与应用。"""
from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


UI_DEFAULTS_SECTION = "ui_defaults"
POWER_SUPPLY_SECTION = "power_supply"
POWER_SERIAL_OPTION = "serial_port"
POWER_CONFIG_FILENAME = "network_card_ip.ini"
POWER_SERIAL_SOURCE = "network_card_ip.ini [power_supply]"
TEST_PROJECT_CONFIG_FILENAME = "test_project_config.ini"
TELNET_DEFAULT_SECTION = "telnet"
TELNET_DEFAULT_OPTION = "telnet_default_on"
TELNET_ENABLE_SOURCE = "test_project_config.ini [telnet] telnet_default_on（反向）"


@dataclass(frozen=True)
class LegacyUiDefaults:
    communication_method: str
    telnet_enable: bool
    serial_num: str
    baud_rate: str
    selected_profile: str
    startup_time: int
    interval_time: int
    number_of_tests: int
    wait_command_done: int
    serial_num_source: str = POWER_SERIAL_SOURCE
    enabled_power_channels: tuple[int, ...] = ()
    telnet_enable_source: str = TELNET_ENABLE_SOURCE


def _read_integer(
    parser: configparser.RawConfigParser,
    option: str,
    *,
    minimum: int,
) -> int:
    raw_value = parser.get(UI_DEFAULTS_SECTION, option).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"[{UI_DEFAULTS_SECTION}] {option} 必须是整数：{raw_value!r}") from exc
    if value < minimum:
        raise ValueError(f"[{UI_DEFAULTS_SECTION}] {option} 不能小于 {minimum}：{value}")
    return value


def _load_power_settings(config_path: Path) -> tuple[str, tuple[int, ...]]:
    """读取新工具保存的程控电源 COM 和已选通道。"""
    power_config_path = config_path.parent / POWER_CONFIG_FILENAME
    if not power_config_path.is_file():
        return "", ()

    power_parser = configparser.RawConfigParser()
    power_parser.read(power_config_path, encoding="utf-8")
    serial_num = power_parser.get(
        POWER_SUPPLY_SECTION,
        POWER_SERIAL_OPTION,
        fallback="",
    ).strip().upper()
    enabled_channels = tuple(
        channel_number
        for channel_number in range(1, 17)
        if power_parser.has_section(f"channel_{channel_number}")
        and power_parser.getboolean(
            f"channel_{channel_number}",
            "enabled",
            fallback=True,
        )
    )
    return serial_num, enabled_channels


def _load_telnet_enable(config_path: Path) -> bool:
    """新工具默认已开 Telnet 时，旧工具不再执行 Telnet 开启动作。"""
    test_project_config_path = config_path.parent / TEST_PROJECT_CONFIG_FILENAME
    parser = configparser.RawConfigParser()
    parser.read(test_project_config_path, encoding="utf-8")
    raw_value = parser.get(
        TELNET_DEFAULT_SECTION,
        TELNET_DEFAULT_OPTION,
        fallback="1",
    ).strip()
    if raw_value not in {"0", "1"}:
        raise ValueError(
            f"[{TELNET_DEFAULT_SECTION}] {TELNET_DEFAULT_OPTION} 只能是 0 或 1："
            f"{raw_value!r}"
        )
    return raw_value == "0"


def load_legacy_ui_defaults(config_path: Path) -> LegacyUiDefaults:
    """从 ``config.ini`` 读取并校验旧工具主界面启动参数。"""
    if not config_path.is_file():
        raise FileNotFoundError(f"未找到配置文件：{config_path}")

    parser = configparser.RawConfigParser()
    parser.optionxform = str
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section(UI_DEFAULTS_SECTION):
        raise ValueError(f"配置文件缺少 [{UI_DEFAULTS_SECTION}] 段：{config_path}")

    communication_method = parser.get(
        UI_DEFAULTS_SECTION, "communication_method"
    ).strip().lower()
    if communication_method not in {"telnet", "ssh"}:
        raise ValueError(
            f"[{UI_DEFAULTS_SECTION}] communication_method 只能是 telnet 或 ssh："
            f"{communication_method!r}"
        )

    serial_num, enabled_power_channels = _load_power_settings(config_path)
    telnet_enable = _load_telnet_enable(config_path)

    baud_rate = parser.get(UI_DEFAULTS_SECTION, "baud_rate").strip()
    if not baud_rate.isdigit() or int(baud_rate) <= 0:
        raise ValueError(f"[{UI_DEFAULTS_SECTION}] baud_rate 必须是正整数：{baud_rate!r}")

    selected_profile = parser.get(UI_DEFAULTS_SECTION, "selected_profile").strip()
    if not selected_profile:
        raise ValueError(f"[{UI_DEFAULTS_SECTION}] selected_profile 不能为空")

    return LegacyUiDefaults(
        communication_method=communication_method,
        telnet_enable=telnet_enable,
        serial_num=serial_num,
        baud_rate=baud_rate,
        selected_profile=selected_profile,
        startup_time=_read_integer(parser, "startup_time", minimum=0),
        interval_time=_read_integer(parser, "interval_time", minimum=0),
        number_of_tests=_read_integer(parser, "number_of_tests", minimum=1),
        wait_command_done=_read_integer(parser, "wait_command_done", minimum=0),
        serial_num_source=POWER_SERIAL_SOURCE,
        enabled_power_channels=enabled_power_channels,
        telnet_enable_source=TELNET_ENABLE_SOURCE,
    )


def _select_combo_value(combo_box, value: str, *, add_when_missing: bool) -> bool:
    """按不区分大小写的文本选择 QComboBox 项。"""
    normalized = value.strip().lower()
    for index in range(combo_box.count()):
        if combo_box.itemText(index).strip().lower() == normalized:
            combo_box.setCurrentIndex(index)
            return True
    if add_when_missing:
        combo_box.addItem(value)
        combo_box.setCurrentIndex(combo_box.count() - 1)
        return True
    return False


def apply_legacy_ui_defaults(window, defaults: LegacyUiDefaults) -> None:
    """把已校验配置加载到旧工具主窗口。"""
    use_telnet = defaults.communication_method == "telnet"
    window.radioButton_telnet.setChecked(use_telnet)
    window.radioButton_ssh.setChecked(not use_telnet)
    window.checkBox_telnet_enable.setChecked(defaults.telnet_enable)

    _select_combo_value(
        window.comboBox_serial_num,
        defaults.serial_num,
        add_when_missing=True,
    )
    _select_combo_value(
        window.comboBox_band_rate,
        defaults.baud_rate,
        add_when_missing=True,
    )
    if not _select_combo_value(
        window.comboBox_schemes,
        defaults.selected_profile,
        add_when_missing=False,
    ):
        raise ValueError(
            f"[{UI_DEFAULTS_SECTION}] selected_profile 未出现在 [config] 方案列表："
            f"{defaults.selected_profile!r}"
        )

    window.lineEdit_start_need_times.setText(str(defaults.startup_time))
    window.lineEdit_interval_time.setText(str(defaults.interval_time))
    window.lineEdit_test_number.setText(str(defaults.number_of_tests))
    window.lineEdit_wait_command_done.setText(str(defaults.wait_command_done))


def apply_legacy_power_channel_selection(window, defaults: LegacyUiDefaults) -> None:
    """让旧工具电源通道勾选状态严格等于新工具当前选中配置。"""
    enabled_channels = set(defaults.enabled_power_channels)
    for channel_number, check_box in enumerate(window.channel_box_list, start=1):
        check_box.setChecked(channel_number in enabled_channels)


__all__ = [
    "LegacyUiDefaults",
    "POWER_SERIAL_SOURCE",
    "TELNET_ENABLE_SOURCE",
    "UI_DEFAULTS_SECTION",
    "apply_legacy_power_channel_selection",
    "apply_legacy_ui_defaults",
    "load_legacy_ui_defaults",
]

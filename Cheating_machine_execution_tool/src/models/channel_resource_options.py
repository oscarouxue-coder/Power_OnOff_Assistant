"""Original channel resource candidate rules shared by both workbenches."""
import re

from line_check_assistant.network_ops import adapter_alias_from_display
from line_check_assistant.serial_ports import port_from_display


POWER_SUPPLY_COUNT = 6
VLAN_PER_POWER_SUPPLY = 8
FIRST_VLAN_ID = 101
POWER_SERIAL_OPTIONS = ("", *(f"COM{101 + index}" for index in range(POWER_SUPPLY_COUNT)))


def _power_serial_group_index(serial_port: str) -> int:
    normalized_port = (port_from_display(serial_port) or serial_port or "").strip().upper()
    port_number = normalized_port[3:] if normalized_port.startswith("COM") else ""
    try:
        raw_index = int(port_number)
    except ValueError:
        return 0
    if 101 <= raw_index < 101 + POWER_SUPPLY_COUNT:
        return raw_index - 100
    if 1 <= raw_index <= POWER_SUPPLY_COUNT:
        # 兼容操作员口头所说的 COM1 / COM2；实际程控电源项仍为 COM101 / COM102。
        return raw_index
    return 0


def serial_options_for_power_serial_port(serial_port: str) -> list[str]:
    """按程控电源分组返回样机串口候选，每组连续8个COM口。"""
    power_index = _power_serial_group_index(serial_port)
    if not power_index:
        return [f"COM{index}" for index in range(1, POWER_SUPPLY_COUNT * VLAN_PER_POWER_SUPPLY + 1)]
    start_port = (power_index - 1) * VLAN_PER_POWER_SUPPLY + 1
    return [f"COM{index}" for index in range(start_port, start_port + VLAN_PER_POWER_SUPPLY)]


def vlan_options_for_power_serial_port(adapters: list[str], serial_port: str) -> list[str]:
    """返回指定程控电源 COM 口对应的 VLAN 网卡候选。

    每台程控电源管理连续 8 个 VLAN：COM101 对应 VLAN101–108、
    COM102 对应 VLAN109–116，依此类推。未选择 COM 时展示所有识别
    网卡；传入未知 COM 口时保留全部 VLAN 网卡，避免异常配置导致
    配置页没有可选项。
    """
    normalized_port = (port_from_display(serial_port) or serial_port or "").strip().upper()
    if not normalized_port:
        options_by_alias: dict[str, str] = {}
        for adapter in adapters:
            alias = adapter_alias_from_display(adapter)
            if alias:
                options_by_alias.setdefault(alias.lower(), adapter)
        return sorted(options_by_alias.values(), key=lambda value: adapter_alias_from_display(value).lower())

    power_index = _power_serial_group_index(normalized_port)

    start_vlan = FIRST_VLAN_ID + (power_index - 1) * VLAN_PER_POWER_SUPPLY
    end_vlan = start_vlan + VLAN_PER_POWER_SUPPLY - 1

    options_by_alias: dict[str, str] = {}
    for adapter in adapters:
        alias = adapter_alias_from_display(adapter)
        match = re.fullmatch(r"vlan(\d+)", alias, flags=re.IGNORECASE)
        if not match:
            continue
        vlan_id = int(match.group(1))
        if power_index and not start_vlan <= vlan_id <= end_vlan:
            continue
        options_by_alias.setdefault(alias.lower(), adapter)

    return sorted(
        options_by_alias.values(),
        key=lambda value: (
            int(re.search(r"\d+", adapter_alias_from_display(value)).group())
            if re.search(r"\d+", adapter_alias_from_display(value))
            else 999999,
            adapter_alias_from_display(value).lower(),
        ),
    )

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import List


DEFAULT_SUBNET_MASK = "255.255.255.0"
# 未配置程控电源时保持空值：业务流程会跳过上下电，而不是擅自使用 COM101。
DEFAULT_POWER_SERIAL_PORT = ""
POWER_SUPPLY_SECTION = "power_supply"


@dataclass
class ChannelConfig:
    section: str
    vlan_name: str = ""
    adapter_alias: str = ""
    network_card_ip: str = ""
    device_manage_ip: str = ""
    subnet_mask: str = DEFAULT_SUBNET_MASK
    # 样机进入工厂模式（ppctl set FACTORY_MODE=1 + firstboot -yr 重启之后），
    # 管理 IP 会切到另一网段（例如 192.168.29.1），PC 端 VLAN 网卡也需要切到该网段。
    # telnet 写参必须配置这两个字段；缺失则在启动批量写参时被预校验拒绝。
    factory_device_host: str = ""
    factory_bind_ip: str = ""
    enabled: bool = True

    @property
    def label(self) -> str:
        return self.section.replace("channel_", "通道 ")


class ChannelConfigStore:
    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> List[ChannelConfig]:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")

        channels: List[ChannelConfig] = []
        for section in parser.sections():
            if not section.lower().startswith("channel_"):
                continue
            channels.append(
                ChannelConfig(
                    section=section,
                    vlan_name=parser.get(section, "vlan_name", fallback=""),
                    adapter_alias=parser.get(section, "adapter_alias", fallback=""),
                    network_card_ip=parser.get(section, "network_card_ip", fallback=""),
                    device_manage_ip=parser.get(section, "device_manage_ip", fallback=""),
                    subnet_mask=parser.get(section, "subnet_mask", fallback=DEFAULT_SUBNET_MASK),
                    factory_device_host=parser.get(section, "factory_device_host", fallback=""),
                    factory_bind_ip=parser.get(section, "factory_bind_ip", fallback=""),
                    enabled=parser.getboolean(section, "enabled", fallback=True),
                )
            )

        return sorted(channels, key=_channel_sort_key)

    def load_power_serial_port(self) -> str:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")
        # 空值表示“不使用程控电源”，必须原样保留，不能在读取时又回填默认 COM101。
        return parser.get(POWER_SUPPLY_SECTION, "serial_port", fallback=DEFAULT_POWER_SERIAL_PORT).strip()

    def save(self, channels: List[ChannelConfig], power_serial_port: str = DEFAULT_POWER_SERIAL_PORT) -> None:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser[POWER_SUPPLY_SECTION] = {
            # 空值是有效配置：后续业务跳过程控电源操作。
            "serial_port": (power_serial_port or "").strip().upper(),
        }

        for channel in sorted(channels, key=lambda item: _channel_sort_key(item.section)):
            parser[channel.section] = {
                "vlan_name": channel.vlan_name,
                "adapter_alias": channel.adapter_alias,
                "network_card_ip": channel.network_card_ip,
                "device_manage_ip": channel.device_manage_ip,
                "subnet_mask": channel.subnet_mask or DEFAULT_SUBNET_MASK,
                "factory_device_host": channel.factory_device_host,
                "factory_bind_ip": channel.factory_bind_ip,
                "enabled": "1" if channel.enabled else "0",
            }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)


def _channel_sort_key(value: object) -> int:
    section = value.section if isinstance(value, ChannelConfig) else str(value)
    try:
        return int(section.lower().replace("channel_", ""))
    except ValueError:
        return 9999

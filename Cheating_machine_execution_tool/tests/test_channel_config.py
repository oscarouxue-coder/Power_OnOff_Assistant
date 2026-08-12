"""ChannelConfig 工厂模式新字段 round-trip 测试。"""
from __future__ import annotations

import configparser
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.config_store import (
    DEFAULT_SUBNET_MASK,
    ChannelConfig,
    ChannelConfigStore,
)


class ChannelConfigFactoryModeFieldsTests(unittest.TestCase):
    def _write_minimal_ini(self, path: Path, sections: dict[str, dict[str, str]]) -> None:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        for name, values in sections.items():
            parser[name] = values
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            parser.write(file)

    def test_load_includes_factory_bind_ip_and_device_host(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "network_card_ip.ini"
            self._write_minimal_ini(config_path, {
                "channel_3": {
                    "vlan_name": "VLAN103",
                    "adapter_alias": "VLAN103",
                    "serial_port": "com8",
                    "network_card_ip": "192.168.1.103",
                    "device_manage_ip": "192.168.1.1",
                    "subnet_mask": "255.255.255.0",
                    "factory_device_host": "192.168.29.1",
                    "factory_bind_ip": "192.168.29.103",
                    "enabled": "1",
                },
            })
            store = ChannelConfigStore(config_path)
            channels = store.load()
            self.assertEqual(len(channels), 1)
            channel = channels[0]
            self.assertEqual(channel.factory_device_host, "192.168.29.1")
            self.assertEqual(channel.factory_bind_ip, "192.168.29.103")
            self.assertEqual(channel.serial_port, "COM8")
            self.assertEqual(channel.subnet_mask, "255.255.255.0")
            self.assertEqual(channel.network_card_ip, "192.168.1.103")

    def test_load_defaults_factory_fields_to_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "network_card_ip.ini"
            self._write_minimal_ini(config_path, {
                "channel_5": {
                    "vlan_name": "VLAN105",
                    "adapter_alias": "VLAN105",
                    "network_card_ip": "192.168.1.105",
                    "device_manage_ip": "192.168.1.1",
                    "subnet_mask": DEFAULT_SUBNET_MASK,
                    "enabled": "1",
                },
            })
            store = ChannelConfigStore(config_path)
            channels = store.load()
            self.assertEqual(channels[0].factory_device_host, "")
            self.assertEqual(channels[0].factory_bind_ip, "")

    def test_save_round_trip_preserves_factory_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "network_card_ip.ini"
            store = ChannelConfigStore(config_path)
            channels = [
                ChannelConfig(
                    section="channel_7",
                    vlan_name="VLAN107",
                    adapter_alias="VLAN107",
                    serial_port="COM8",
                    network_card_ip="192.168.1.107",
                    device_manage_ip="192.168.1.1",
                    subnet_mask="255.255.255.0",
                    factory_device_host="192.168.29.1",
                    factory_bind_ip="192.168.29.107",
                    enabled=True,
                ),
            ]
            store.save(channels, power_serial_port="COM101")

            reloaded = ChannelConfigStore(config_path).load()
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(reloaded[0].factory_device_host, "192.168.29.1")
            self.assertEqual(reloaded[0].factory_bind_ip, "192.168.29.107")
            self.assertEqual(reloaded[0].serial_port, "COM8")

    def test_load_legacy_channel_without_serial_port_keeps_compatible_empty_value(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "network_card_ip.ini"
            self._write_minimal_ini(
                config_path,
                {"channel_8": {"vlan_name": "VLAN113", "enabled": "1"}},
            )

            channel = ChannelConfigStore(config_path).load()[0]

            self.assertEqual(channel.serial_port, "")

    def test_save_and_load_preserves_empty_power_serial_port(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "network_card_ip.ini"
            store = ChannelConfigStore(config_path)

            store.save([], power_serial_port="")

            self.assertEqual(store.load_power_serial_port(), "")


if __name__ == "__main__":
    unittest.main()

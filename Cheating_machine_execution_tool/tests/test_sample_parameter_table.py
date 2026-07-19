import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.sample_parameter_table import (
    generate_parameter_records,
    load_parameter_records,
    save_parameter_records_xlsx,
)
from src.models import PARAMETER_COLUMNS, ParameterGenerationTemplate


def template():
    return ParameterGenerationTemplate(
        sn_prefix="SN",
        xpon_prefix="XPON",
        ssid_24_prefix="WIFI24",
        ssid_5_prefix="WIFI5",
        suffix_length=6,
        fixed_values={column: "fixed" for column in PARAMETER_COLUMNS},
    )


class SampleParameterTableTests(unittest.TestCase):
    def test_generate_records_are_unique_and_local_unicast(self):
        records = generate_parameter_records(["vlan101", "vlan102", "vlan103"], template())

        self.assertEqual([record.vlan for record in records], ["vlan101", "vlan102", "vlan103"])
        self.assertEqual(len({record.values["MAC"] for record in records}), 3)
        self.assertEqual(len({record.values["SN"] for record in records}), 3)
        for record in records:
            first_octet = int(record.values["MAC"].split(":")[0], 16)
            self.assertEqual(first_octet & 0x01, 0)
            self.assertEqual(first_octet & 0x02, 0x02)

    def test_generate_records_share_same_mac_oui_within_batch(self):
        # 同批 MAC 前 3 字节（OUI）固定,后 3 字节每台唯一。
        records = generate_parameter_records(
            ["vlan101", "vlan102", "vlan103", "vlan104", "vlan105"], template()
        )

        ouis = {":".join(record.values["MAC"].split(":")[:3]) for record in records}
        nics = {":".join(record.values["MAC"].split(":")[3:]) for record in records}
        # 同批只有 1 个 OUI
        self.assertEqual(len(ouis), 1, f"OUI 应在同批内一致,实际 {ouis}")
        # NIC 标识（后 3 字节）每台唯一
        self.assertEqual(len(nics), 5)
        # 完整 MAC 仍全部唯一
        self.assertEqual(len({record.values["MAC"] for record in records}), 5)
        # 首字节仍保留本地管理(bit1=1)+ 单播(bit0=0)位
        first_octet = int(next(iter(ouis)).split(":")[0], 16)
        self.assertEqual(first_octet & 0x01, 0)
        self.assertEqual(first_octet & 0x02, 0x02)

    def test_generate_records_ssid_suffix_matches_mac_last_4_hex(self):
        # 2026-07-19:2.4G / 5G SSID 后缀取本机 MAC 末 4 位十六进制（大写）,
        # 同一行两个 SSID 自动共享该后缀,操作员可一眼对应到本机 MAC。
        # 例:MAC=CA:7A:85:18:B0:E8 → 后缀="B0E8"
        # 2.4G=ssid_24_prefix + "B0E8" / 5G=ssid_5_prefix + "B0E8"。
        tpl = template()
        records = generate_parameter_records(
            ["vlan101", "vlan102", "vlan103", "vlan104", "vlan105"], tpl
        )

        for record in records:
            mac = record.values["MAC"]
            mac_suffix = mac.replace(":", "")[-4:]  # 末 4 位十六进制
            self.assertEqual(len(mac_suffix), 4)
            self.assertRegex(mac_suffix, r"^[0-9A-F]{4}$")
            ssid_24 = record.values["2.4G SSID"]
            ssid_5 = record.values["5G SSID"]
            # 两个 SSID 必须以 MAC 末 4 位结尾
            self.assertTrue(
                ssid_24.endswith(mac_suffix),
                f"2.4G SSID {ssid_24} 应以 MAC 末 4 位 {mac_suffix} 结尾",
            )
            self.assertTrue(
                ssid_5.endswith(mac_suffix),
                f"5G SSID {ssid_5} 应以 MAC 末 4 位 {mac_suffix} 结尾",
            )
            # 两个 SSID 去掉各自前缀后必须完全相同
            self.assertEqual(
                ssid_24[len(tpl.ssid_24_prefix):],
                ssid_5[len(tpl.ssid_5_prefix):],
                f"同一行 2.4G / 5G SSID 后缀必须一致: 2.4G={ssid_24}, 5G={ssid_5}",
            )
            # 且这两个后缀就等于 MAC 末 4 位
            self.assertEqual(ssid_24[len(tpl.ssid_24_prefix):], mac_suffix)
            self.assertEqual(ssid_5[len(tpl.ssid_5_prefix):], mac_suffix)
        # 全列 SSID 仍保持唯一（不同样机 MAC 末 4 位不同）
        self.assertEqual(
            len({record.values["2.4G SSID"] for record in records}), 5
        )
        self.assertEqual(
            len({record.values["5G SSID"] for record in records}), 5
        )

    def test_legacy_duplicate_headers_are_shared_by_both_wireless_fields(self):
        headers = [
            "VLAN", "SN", "GPON SN", "MAC", "2.4G SSID", "WiFi Password", "5G SSID",
            "Country code", "Product Class", "Superuser Name", "Superuser Password", "User Name", "Password", "IP",
        ]
        values = [
            "vlan101", "SN1", "XPON1", "02:00:00:00:00:01", "wifi24", "legacy-password", "wifi5",
            "CN", "P1", "super", "super-password", "user", "user-password", "192.168.1.1",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(headers)
                writer.writerow(values)
            record = load_parameter_records(path)[0]

        self.assertEqual(record.values["2.4G WiFi Password"], "legacy-password")
        self.assertEqual(record.values["5G WiFi Password"], "legacy-password")
        self.assertEqual(record.values["2.4G Country Code"], "CN")
        self.assertEqual(record.values["5G Country Code"], "CN")

    def test_exported_xlsx_round_trips_canonical_columns(self):
        records = generate_parameter_records(["vlan101"], template())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parameters.xlsx"
            save_parameter_records_xlsx(path, records)
            loaded = load_parameter_records(path)

        self.assertEqual(loaded[0].vlan, "vlan101")
        self.assertEqual(dict(loaded[0].values), dict(records[0].values))

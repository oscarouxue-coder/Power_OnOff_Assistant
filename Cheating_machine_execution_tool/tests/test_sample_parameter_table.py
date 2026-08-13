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
        sn_prefix="1234567890",
        xpon_prefix="XPON",
        mac_prefix="A2B3C4",
        ssid_24_prefix="WIFI24",
        ssid_5_prefix="WIFI5",
        suffix_length=6,
        fixed_values={column: "fixed" for column in PARAMETER_COLUMNS},
    )


class SampleParameterTableTests(unittest.TestCase):
    def test_generated_xpon_sn_is_fixed_12_chars_with_upper_hex_last_8(self):
        records = generate_parameter_records(
            ["vlan101", "vlan102", "vlan103"], template()
        )

        serial_numbers = [record.values["GPON SN"] for record in records]
        self.assertEqual(len(set(serial_numbers)), 3)
        for serial_number in serial_numbers:
            self.assertEqual(len(serial_number), 12)
            self.assertTrue(serial_number.startswith("XPON"))
            self.assertRegex(serial_number[-8:], r"^[0-9A-F]{8}$")
        # 普通SN继续使用自己的可调后缀长度，并按默认模板生成16位纯数字。
        self.assertTrue(
            all(len(record.values["SN"]) == 16 for record in records)
        )
        self.assertTrue(all(record.values["SN"].isdigit() for record in records))

    def test_generated_xpon_sn_rejects_prefix_that_is_not_exactly_4_chars(self):
        for prefix in ("", "SN", "ABCDE"):
            tpl = ParameterGenerationTemplate(
                sn_prefix="12345678",
                xpon_prefix=prefix,
                mac_prefix="A2B3C4",
                ssid_24_prefix="WIFI24",
                ssid_5_prefix="WIFI5",
                suffix_length=8,
            )
            with self.subTest(prefix=prefix), self.assertRaisesRegex(
                ValueError, "XPON SN 前缀必须固定为 4 位"
            ):
                generate_parameter_records(["vlan101"], tpl)

    def test_generated_sn_is_numeric_and_total_length_does_not_exceed_16(self):
        records = generate_parameter_records(
            ["vlan101", "vlan102", "vlan103"], template()
        )

        serial_numbers = [record.values["SN"] for record in records]
        self.assertEqual(len(set(serial_numbers)), 3)
        for serial_number in serial_numbers:
            self.assertEqual(len(serial_number), 16)
            self.assertTrue(serial_number.startswith("1234567890"))
            self.assertRegex(serial_number, r"^[0-9]{16}$")

        shorter = ParameterGenerationTemplate(
            sn_prefix="1234",
            xpon_prefix="XPON",
            mac_prefix="A2B3C4",
            ssid_24_prefix="WIFI24",
            ssid_5_prefix="WIFI5",
            suffix_length=6,
        )
        value = generate_parameter_records(["vlan101"], shorter)[0].values["SN"]
        self.assertEqual(len(value), 10)
        self.assertRegex(value, r"^[0-9]{10}$")

    def test_generated_sn_rejects_non_numeric_prefix_or_total_over_16(self):
        non_numeric = ParameterGenerationTemplate(
            sn_prefix="12AB",
            xpon_prefix="XPON",
            mac_prefix="A2B3C4",
            ssid_24_prefix="WIFI24",
            ssid_5_prefix="WIFI5",
            suffix_length=6,
        )
        with self.assertRaisesRegex(ValueError, "SN 前缀必须为纯数字"):
            generate_parameter_records(["vlan101"], non_numeric)

        too_long = ParameterGenerationTemplate(
            sn_prefix="12345678901",
            xpon_prefix="XPON",
            mac_prefix="A2B3C4",
            ssid_24_prefix="WIFI24",
            ssid_5_prefix="WIFI5",
            suffix_length=6,
        )
        with self.assertRaisesRegex(ValueError, "不能超过 16 位"):
            generate_parameter_records(["vlan101"], too_long)

    def test_generate_records_are_unique_and_local_unicast(self):
        records = generate_parameter_records(["vlan101", "vlan102", "vlan103"], template())

        self.assertEqual([record.vlan for record in records], ["vlan101", "vlan102", "vlan103"])
        self.assertEqual(len({record.values["MAC"] for record in records}), 3)
        self.assertEqual(len({record.values["SN"] for record in records}), 3)
        for record in records:
            first_octet = int(record.values["MAC"].split(":")[0], 16)
            self.assertEqual(first_octet & 0x01, 0)
            self.assertEqual(first_octet & 0x02, 0x02)

    def test_generate_records_use_custom_mac_prefix_and_unique_hex_suffix(self):
        # 同批 MAC 前 3 字节由用户指定，后 3 字节每台随机且唯一。
        records = generate_parameter_records(
            ["vlan101", "vlan102", "vlan103", "vlan104", "vlan105"], template()
        )

        ouis = {":".join(record.values["MAC"].split(":")[:3]) for record in records}
        nics = {":".join(record.values["MAC"].split(":")[3:]) for record in records}
        self.assertEqual(ouis, {"A2:B3:C4"})
        # NIC 标识（后 3 字节）每台唯一
        self.assertEqual(len(nics), 5)
        # 完整 MAC 仍全部唯一
        self.assertEqual(len({record.values["MAC"] for record in records}), 5)
        # 用户前缀仍必须是单播地址；是否为本地管理地址由用户输入决定。
        first_octet = int(next(iter(ouis)).split(":")[0], 16)
        self.assertEqual(first_octet & 0x01, 0)
        for nic in nics:
            self.assertRegex(nic.replace(":", ""), r"^[0-9A-F]{6}$")

    def test_generate_records_accept_separated_lowercase_mac_prefix(self):
        tpl = ParameterGenerationTemplate(
            sn_prefix="1234567890",
            xpon_prefix="XPON",
            mac_prefix="a2:b3:c4",
            ssid_24_prefix="WIFI24",
            ssid_5_prefix="WIFI5",
            suffix_length=6,
        )

        mac = generate_parameter_records(["vlan101"], tpl)[0].values["MAC"]
        self.assertRegex(mac, r"^A2:B3:C4:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}$")

    def test_generate_records_reject_invalid_hex_or_multicast_mac_prefix(self):
        for prefix, message in (
            ("A2B3", "恰好 6 个十六进制字符"),
            ("A2B3G4", "必须为十六进制字符"),
            ("A3B3C4", "必须为单播地址"),
        ):
            tpl = ParameterGenerationTemplate(
                sn_prefix="1234567890",
                xpon_prefix="XPON",
                mac_prefix=prefix,
                ssid_24_prefix="WIFI24",
                ssid_5_prefix="WIFI5",
                suffix_length=6,
            )
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, message):
                generate_parameter_records(["vlan101"], tpl)

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

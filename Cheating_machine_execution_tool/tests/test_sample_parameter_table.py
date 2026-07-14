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

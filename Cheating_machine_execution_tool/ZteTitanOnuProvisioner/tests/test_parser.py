import unittest

from zte_titan_tool.parser import (
    parse_registered_onus,
    parse_service_mappings,
    parse_unconfigured_onus,
    speed_mode_to_cli,
)


UNCONFIGURED_OUTPUT = """
show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode
OltIndex            Model              SN               Speed Mode
-----------------------------------------------------------------------------
gpon_olt-1/1/5      NP7287XGS          SDMC176D42AA     XGS-PON
gpon_olt-1/1/5      NP7287XGS          SDMC126C7707     XGS-PON
ZXAN#
"""

REGISTERED_OUTPUT = """
interface gpon_olt-1/1/5
  onu 1 type NP7287XGS sn SDMCA6C83D80
  onu 17 type CXYG-04 sn SDMCBE4A7FA0
  onu 55 type CXP-55 sn CHEN20230518
ZXAN#
"""


class ParserTests(unittest.TestCase):
    def test_parses_unconfigured_onus(self):
        onus = parse_unconfigured_onus(UNCONFIGURED_OUTPUT)
        self.assertEqual(len(onus), 2)
        self.assertEqual(onus[0].olt_interface, "gpon_olt-1/1/5")
        self.assertEqual(onus[0].model, "NP7287XGS")
        self.assertEqual(onus[0].serial_number, "SDMC176D42AA")
        self.assertEqual(onus[0].speed_mode, "XGS-PON")
        self.assertEqual(onus[0].location, (1, 1, 5))

    def test_parses_registered_onus(self):
        self.assertEqual(
            parse_registered_onus(REGISTERED_OUTPUT),
            [
                (1, "NP7287XGS", "SDMCA6C83D80"),
                (17, "CXYG-04", "SDMCBE4A7FA0"),
                (55, "CXP-55", "CHEN20230518"),
            ],
        )

    def test_parses_service_mapping_formats(self):
        mappings = parse_service_mappings("1,170\n2=335\n3:600\n# comment")
        self.assertEqual([(item.service_id, item.vlan) for item in mappings], [(1, 170), (2, 335), (3, 600)])

    def test_rejects_invalid_mapping(self):
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            parse_service_mappings("1,170\nbad")

    def test_speed_mode_mapping(self):
        self.assertEqual(speed_mode_to_cli("XGS-PON"), "xgspon")
        self.assertEqual(speed_mode_to_cli("GPON"), "gpon")
        self.assertEqual(speed_mode_to_cli("unknown"), "auto")


if __name__ == "__main__":
    unittest.main()

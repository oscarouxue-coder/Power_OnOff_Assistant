import unittest

from zte_titan_tool.commands import (
    build_discovery_command,
    build_provision_commands,
    build_verify_commands,
    contains_cli_error,
)
from zte_titan_tool.models import OnuProvisionConfig, ServiceMapping


def sample_config():
    return OnuProvisionConfig(
        shelf=1,
        slot=1,
        pon=5,
        onu_id=55,
        onu_type="CXP-55",
        serial_number="CHEN20230518",
        real_speed="xgspon",
        tcont_id=1,
        tcont_profile="CXP-55",
        gemport_id=1,
        vport_id=1,
        services=[ServiceMapping(1, 170), ServiceMapping(2, 335)],
    )


class CommandTests(unittest.TestCase):
    def test_builds_titan_commands(self):
        commands = build_provision_commands(sample_config())
        self.assertEqual(commands[0], "configure terminal")
        self.assertIn("interface gpon_olt-1/1/5", commands)
        self.assertIn("onu 55 type CXP-55 sn CHEN20230518", commands)
        self.assertIn("interface gpon_onu-1/1/5:55", commands)
        self.assertIn("real-speed xgspon", commands)
        self.assertIn("tcont 1 profile CXP-55", commands)
        self.assertIn("gemport 1 tcont 1", commands)
        self.assertIn("pon-onu-mng gpon_onu-1/1/5:55", commands)
        self.assertIn("service 2 gemport 1 vlan 335", commands)
        self.assertIn("interface vport-1/1/5.55:1", commands)
        self.assertIn("service-port 2 user-vlan 335 vlan 335", commands)
        self.assertEqual(commands[-1], "end")

    def test_never_generates_write(self):
        commands = build_provision_commands(sample_config())
        self.assertNotIn("write", commands)

    def test_discovery_and_verification_commands(self):
        config = sample_config()
        self.assertEqual(
            build_discovery_command(1, 1, 5),
            "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode",
        )
        self.assertEqual(
            build_verify_commands(config)[0],
            "show collection pon-onu gpon_onu-1/1/5:55 config",
        )

    def test_cli_error_detection(self):
        self.assertTrue(contains_cli_error("%Error 140303: Invalid input detected"))
        self.assertTrue(contains_cli_error("Incomplete command."))
        self.assertFalse(contains_cli_error("Config state: success\nZXAN#"))

    def test_validation_rejects_duplicate_vlan(self):
        config = sample_config()
        duplicate = OnuProvisionConfig(
            **{
                **config.__dict__,
                "services": [ServiceMapping(1, 170), ServiceMapping(2, 170)],
            }
        )
        self.assertIn("VLAN 不能重复", duplicate.validate())


if __name__ == "__main__":
    unittest.main()

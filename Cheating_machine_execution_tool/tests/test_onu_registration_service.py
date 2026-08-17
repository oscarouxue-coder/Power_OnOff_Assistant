import threading
import unittest
from unittest.mock import MagicMock, patch

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver, parse_service_mappings, speed_mode_to_cli
from src.core.zte_olt_telnet import OltCommandError, ZteOltTelnetSession
from src.models.onu_registration_models import (
    DiscoveredOnu,
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OltConnection,
    OnuDiscoveryScope,
    OnuProvisionRequest,
    OnuServiceMapping,
)
from src.services.onu_registration_service import OnuRegistrationService, driver_for_family


def make_connection():
    return OltConnection(
        host="172.18.18.152",
        source_ip="172.33.5.35",
        username="zte",
        password="secret",
    )


def make_c300_request():
    onu = DiscoveredOnu(
        family=OLT_FAMILY_C300,
        pon_interface="gpon-olt_1/2/1",
        onu_interface="gpon-onu_1/2/1:3",
        suggested_onu_id=3,
        serial_number="GPONA62D6F78",
        state="unknown",
    )
    return OnuProvisionRequest(family=OLT_FAMILY_C300, onu=onu, onu_type="SD-41")


def make_c600_request():
    onu = DiscoveredOnu(
        family=OLT_FAMILY_C600,
        pon_interface="gpon_olt-1/1/5",
        model="CXP-55",
        serial_number="ZTEG12345678",
        speed_mode="XGS-PON",
    )
    return OnuProvisionRequest(
        family=OLT_FAMILY_C600,
        onu=onu,
        onu_id=55,
        onu_type="CXP-55",
        real_speed="xgspon",
        tcont_profile="CXP-55",
        services=(OnuServiceMapping(1, 170), OnuServiceMapping(2, 335)),
    )


class FakeSession:
    def __init__(self, responses=None, fail_once=None):
        self.responses = responses or {}
        self.fail_once = fail_once
        self.failed = False
        self.commands = []
        self.connected = False
        self.closed = False

    def __call__(self, _connection, logger=None, cancel_event=None):
        self.logger = logger
        self.cancel_event = cancel_event
        return self

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()
        return False

    def connect(self):
        self.connected = True

    def execute(self, command, timeout=20, fail_on_cli_error=True):
        self.commands.append(command)
        if self.fail_once == command and not self.failed:
            self.failed = True
            raise OltCommandError(command, "%Error")
        response = self.responses.get(command, f"{command}\nZXAN#")
        if isinstance(response, list):
            return response.pop(0)
        return response

    def execute_many(self, commands, timeout=20):
        return [self.execute(command, timeout=timeout) for command in commands]

    def best_effort_end(self):
        self.commands.append("<best-effort-end>")

    def close(self):
        self.closed = True


class DriverTests(unittest.TestCase):
    def test_driver_selection_keeps_c300_and_c600_separate(self):
        self.assertIsInstance(driver_for_family(OLT_FAMILY_C300), ZteC300OnuDriver)
        self.assertIsInstance(driver_for_family(OLT_FAMILY_C600), ZteC600OnuDriver)
        self.assertEqual(ZteC600OnuDriver().display_name, "中兴 C600")
        with self.assertRaisesRegex(ValueError, "不支持"):
            driver_for_family("C320")

    def test_c300_uses_underscore_interface_and_confirmed_fixed_template(self):
        commands = ZteC300OnuDriver().build_provision_commands(make_c300_request())

        self.assertEqual(commands[:4], [
            "configure terminal",
            "interface gpon-olt_1/2/1",
            "onu 3 type SD-41 sn GPONA62D6F78",
            "exit",
        ])
        self.assertIn("interface gpon-onu_1/2/1:3", commands)
        self.assertIn("service-port 4 vport 4 user-vlan 600 vlan 600", commands)
        self.assertIn("service VOICE gemport 3 vlan 335", commands)
        self.assertEqual(commands[-3:], ["mvlan 600", "exit", "end"])
        self.assertFalse(any("gpon_olt-" in command for command in commands))

    def test_c600_uses_hyphen_interfaces_and_vport_context(self):
        commands = ZteC600OnuDriver().build_provision_commands(make_c600_request())

        self.assertIn("interface gpon_olt-1/1/5", commands)
        self.assertIn("interface gpon_onu-1/1/5:55", commands)
        self.assertIn("interface vport-1/1/5.55:1", commands)
        self.assertIn("service 2 gemport 1 vlan 335", commands)
        self.assertIn("service-port 2 user-vlan 335 vlan 335", commands)
        self.assertFalse(any("gpon-olt_" in command for command in commands))
        self.assertNotIn("write", commands)

    def test_c300_and_c600_parse_their_own_discovery_formats(self):
        c300 = ZteC300OnuDriver().parse_discovery(
            "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\n"
        )
        c600 = ZteC600OnuDriver().parse_discovery(
            "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\n"
        )

        self.assertEqual(c300[0].onu_interface, "gpon-onu_1/2/1:3")
        self.assertEqual(c300[0].suggested_onu_id, 3)
        self.assertEqual(c600[0].pon_interface, "gpon_olt-1/1/5")
        self.assertEqual(c600[0].model, "CXP-55")

    def test_c600_mapping_and_speed_helpers_match_reference_input(self):
        self.assertEqual(
            parse_service_mappings("1,170\n2:335"),
            [OnuServiceMapping(1, 170), OnuServiceMapping(2, 335)],
        )
        self.assertEqual(speed_mode_to_cli("XGS-PON"), "xgspon")


class ServiceTests(unittest.TestCase):
    def test_c600_query_uses_pon_scoped_command(self):
        command = "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode"
        fake = FakeSession(
            responses={command: "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#"}
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.query_unregistered(
            OLT_FAMILY_C600,
            make_connection(),
            OnuDiscoveryScope(1, 1, 5),
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.onus), 1)
        self.assertEqual(fake.commands, [command])

    def test_c600_register_runs_precheck_provision_and_three_verifications(self):
        request = make_c600_request()
        discovery = "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode"
        fake = FakeSession(
            responses={
                "show running-config-interface gpon_olt-1/1/5": "ZXAN#",
                discovery: "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#",
            }
        )
        logs = []
        service = OnuRegistrationService(logger=logs.append, session_type=fake)

        result = service.register(make_connection(), [request])

        self.assertTrue(result.ok)
        self.assertIn("interface gpon_olt-1/1/5", fake.commands)
        self.assertIn("show collection pon-onu gpon_onu-1/1/5:55 config", fake.commands)
        self.assertIn("show service-port interface gpon_onu-1/1/5:55", fake.commands)
        self.assertIn("show gpon onu detail-info gpon_onu-1/1/5:55", fake.commands)
        self.assertTrue(any("阶段 1/3" in item for item in logs))
        self.assertTrue(any("阶段 3/3" in item for item in logs))

    def test_c600_precheck_rejects_occupied_onu_id_before_configure(self):
        request = make_c600_request()
        fake = FakeSession(
            responses={
                "show running-config-interface gpon_olt-1/1/5": (
                    "onu 55 type OLD sn ZTEG00000000\nZXAN#"
                ),
                "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode": (
                    "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#"
                ),
            }
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.register(make_connection(), [request])

        self.assertFalse(result.ok)
        self.assertIn("ONU ID 55 已存在", result.message)
        self.assertNotIn("configure terminal", fake.commands)

    def test_c300_failure_does_not_delete_when_cleanup_not_authorized(self):
        request = make_c300_request()
        fake = FakeSession(
            responses={
                "show gpon onu uncfg": [
                    "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\nZXAN#",
                    "No related information to show.\nZXAN#",
                ],
                "show gpon onu state": "ZXAN#",
            },
            fail_once="service Internet gemport 1 vlan 200",
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.register(make_connection(), [request], allow_c300_offline_cleanup=False)

        self.assertFalse(result.ok)
        self.assertNotIn("no onu", "\n".join(fake.commands))

    def test_c300_authorized_cleanup_deletes_offline_onus_and_retries(self):
        request = make_c300_request()
        fake = FakeSession(
            responses={
                "show gpon onu uncfg": [
                    "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\nZXAN#",
                    "No related information to show.\nZXAN#",
                ],
                "show gpon onu state": (
                    "1/2/1:8 enable disable DyingGasp 1(GPON)\n"
                    "1/2/5:2 enable enable working 1(GPON)\nZXAN#"
                ),
            },
            fail_once="service Internet gemport 1 vlan 200",
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.register(make_connection(), [request], allow_c300_offline_cleanup=True)

        self.assertTrue(result.ok)
        self.assertIn("no onu 8", fake.commands)
        self.assertNotIn("no onu 2", fake.commands)
        self.assertEqual(fake.commands.count("onu 3 type SD-41 sn GPONA62D6F78"), 2)

    def test_c600_never_allows_write(self):
        service = OnuRegistrationService(session_type=FakeSession())
        result = service.save_configuration(OLT_FAMILY_C600, make_connection())

        self.assertFalse(result.ok)
        self.assertIn("不提供自动 write", result.message)


class TelnetBindingTests(unittest.TestCase):
    @patch.object(ZteOltTelnetSession, "_login")
    @patch("src.core.zte_olt_telnet.telnetlib.Telnet")
    @patch("src.core.zte_olt_telnet.socket.create_connection")
    def test_session_binds_explicit_source_ip(self, create_connection, _telnet, _login):
        sock = MagicMock()
        create_connection.return_value = sock
        session = ZteOltTelnetSession(make_connection(), cancel_event=threading.Event())

        session.connect()

        create_connection.assert_called_once_with(
            ("172.18.18.152", 23),
            timeout=10.0,
            source_address=("172.33.5.35", 0),
        )
        sock.settimeout.assert_called_once_with(0.5)

    def test_connection_rejects_missing_source_ip(self):
        connection = OltConnection("172.18.18.152", "", "zte", "secret")
        self.assertTrue(any("源 IP" in error for error in connection.validate()))


if __name__ == "__main__":
    unittest.main()

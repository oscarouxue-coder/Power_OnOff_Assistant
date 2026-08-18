import threading
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver, parse_service_mappings, speed_mode_to_cli
from src.core.zte_olt_telnet import OltCommandError, ZteOltTelnetSession
from src.models.onu_registration_models import (
    C300CleanupCandidate,
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
        services=(
            OnuServiceMapping(1, 170),
            OnuServiceMapping(2, 335),
            OnuServiceMapping(6, 600),
        ),
    )


def c300_precheck_responses():
    return {
        "show gpon onu uncfg gpon-olt_1/2/1": (
            "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\nZXAN#"
        ),
        "show gpon onu baseinfo gpon-olt_1/2/1 3": (
            "%Code 62331-GPONSRV : ONU data is null.\nZXAN#"
        ),
        "show gpon onu by sn GPONA62D6F78": (
            "%Code 62310-GPONSRV : No related information to show.\nZXAN#"
        ),
    }


def c300_verify_responses():
    gemports = "\n\n".join(
        f"OLT: gpon-olt_1/2/1\nONU: 3\nGEM port: {index}\nT-CONT: 1\nStatus: active"
        for index in range(1, 7)
    )
    vports = "\n\n".join(
        f"ONU interface: gpon-onu_1/2/1:3\nVport: {index}\nMap type: 1:1\n  GEM port: {index}"
        for index in range(1, 7)
    )
    service_ports = "\n".join(
        f"{sport} {vport} {vlan} {vlan} -- -- -- -- {vlan} -- -- --\n"
        "  -- -- 1:1 -- -- -- -- OK YES"
        for sport, vport, vlan, _service in (
            (1, 1, 200, "Internet"),
            (2, 2, 46, "TR069"),
            (3, 3, 335, "VOICE"),
            (4, 4, 600, "IPTV"),
            (5, 5, 171, "Internet2"),
            (6, 6, 172, "Internet3"),
        )
    )
    return {
        "show gpon onu baseinfo gpon-olt_1/2/1 3": (
            "gpon-onu_1/2/1:3 SD-41 sn SN:GPONA62D6F78 ready\nZXAN#"
        ),
        "show gpon onu state gpon-olt_1/2/1 3": (
            "1/2/1:3 enable enable working 1(GPON)\nONU Number: 1/1\nZXAN#"
        ),
        "show gpon onu detail-info gpon-onu_1/2/1:3": (
            "ONU interface: gpon-onu_1/2/1:3\n"
            "Type: SD-41\nState: ready\nAdmin state: enable\nPhase state: working\n"
            "Config state: success\nAuthentication mode: sn\n"
            "SN Bind: enable with SN check\nSerial number: GPONA62D6F78\n"
            "Vport mode: gemport\nONU Status: enable\nZXAN#"
        ),
        "show gpon onu tcont gpon-olt_1/2/1 3": (
            "T-CONT: 1\nUsing following bandwidth profile:\n  Profile name: 1G\nZXAN#"
        ),
        "show gpon onu gemport gpon-olt_1/2/1 3": f"{gemports}\nZXAN#",
        "show gpon onu vport gpon-olt_1/2/1 3": f"{vports}\nZXAN#",
        "show service-port interface gpon-onu_1/2/1:3": f"{service_ports}\nZXAN#",
        "show gpon remote-onu service gpon-onu_1/2/1:3": (
            "Internet 1 -- -- 200\nTR069 2 -- -- 46\nVOICE 3 -- -- 335\n"
            "IPTV 4 -- -- 600\nInternet2 5 -- -- 171\nInternet3 6 -- -- 172\nZXAN#"
        ),
        "show gpon remote-onu mvlan gpon-onu_1/2/1:3": (
            "Multicast VLAN: 600\nZXAN#"
        ),
    }


def c300_register_responses():
    precheck = c300_precheck_responses()
    verification = c300_verify_responses()
    responses = {**precheck, **verification}
    command = "show gpon onu baseinfo gpon-olt_1/2/1 3"
    responses[command] = [precheck[command], verification[command]]
    return responses


def c600_precheck_responses():
    discovery = "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode"
    return {
        discovery: "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#",
        "show gpon onu baseinfo gpon_olt-1/1/5 55": (
            "%Error 222331: ONU data is null.\nZXAN#"
        ),
        "show gpon onu by sn ZTEG12345678": (
            "%Error 230285: No related information to show.\nZXAN#"
        ),
    }


def c600_verify_responses():
    collection = (
        "gpon_onu-1/1/5:55 CXP-55 sn SN:ZTEG12345678 ready\n"
        "interface gpon_onu-1/1/5:55\n"
        "  real-speed xgspon\n  tcont 1 profile CXP-55\n"
        "  sn-bind enable both\n  gemport 1 tcont 1\n"
        "pon-onu-mng gpon_onu-1/1/5:55\n"
        "  service 1 gemport 1 vlan 170\n"
        "  service 2 gemport 1 vlan 335\n"
        "  service 6 gemport 1 vlan 600\n"
        "  mvlan 600\n"
        "interface vport-1/1/5.55:1\n"
        "  service-port 1 user-vlan 170 vlan 170\n"
        "  service-port 2 user-vlan 335 vlan 335\n"
        "  service-port 6 user-vlan 600 vlan 600\nZXAN#"
    )
    service_ports = (
        "1 1 449 -- 170 170 -- -- -- -- 170 -- -- -- -- -- -- -- -- -- -- OK YES --\n"
        "2 1 450 -- 335 335 -- -- -- -- 335 -- -- -- -- -- -- -- -- -- -- OK YES --\n"
        "6 1 454 -- 600 600 -- -- -- -- 600 -- -- -- -- -- -- -- -- -- -- OK YES --\n"
        "Sport total number:\n3\nZXAN#"
    )
    detail = (
        "ONU interface: gpon_onu-1/1/5:55\nType: CXP-55\n"
        "Admin state: enable\nPhase state: working\nConfig state: success\n"
        "Authentication mode: sn\nSN Bind: enable with both check\n"
        "Serial number: ZTEG12345678\nVport mode: gemport\nONU Status: enable\nZXAN#"
    )
    return {
        "show gpon onu state gpon_olt-1/1/5 55": (
            "1/1/5:55 enable enable working XGS-PON\nONU Number: 1/1\nZXAN#"
        ),
        "show collection pon-onu gpon_onu-1/1/5:55 config": collection,
        "show service-port interface gpon_onu-1/1/5:55": service_ports,
        "show gpon onu detail-info gpon_onu-1/1/5:55": detail,
        "show gpon remote-onu mvlan gpon_onu-1/1/5:55": (
            "Multicast VLAN: 600\nZXAN#"
        ),
    }


def c600_register_responses():
    return {**c600_precheck_responses(), **c600_verify_responses()}


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
        self.assertIn("mvlan 600", commands)
        self.assertIn("service-port 2 user-vlan 335 vlan 335", commands)
        self.assertLess(commands.index("mvlan 600"), commands.index("interface vport-1/1/5.55:1"))
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

    def test_c300_precheck_uses_targeted_id_and_global_sn_queries(self):
        driver = ZteC300OnuDriver()
        request = make_c300_request()

        commands = driver.build_precheck_commands(request)
        outputs = [
            "ZXAN#",
            c300_precheck_responses()[commands[1]],
            c300_precheck_responses()[commands[2]],
            c300_precheck_responses()[commands[3]],
        ]

        self.assertEqual(commands, [
            "terminal length 0",
            "show gpon onu uncfg gpon-olt_1/2/1",
            "show gpon onu baseinfo gpon-olt_1/2/1 3",
            "show gpon onu by sn GPONA62D6F78",
        ])
        self.assertEqual(driver.validate_precheck(request, outputs), [])

    def test_c300_precheck_rejects_real_id_and_sn_conflict_formats(self):
        driver = ZteC300OnuDriver()
        request = make_c300_request()
        outputs = [
            "ZXAN#",
            "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\nZXAN#",
            "gpon-onu_1/2/1:3 SD-41 sn SN:GPONAAAAAAAA ready\nZXAN#",
            "Search result\n---\ngpon-onu_1/2/5:8\nZXAN#",
        ]

        errors = driver.validate_precheck(request, outputs)

        self.assertTrue(any("ONU ID 3 已存在" in error for error in errors))
        self.assertTrue(any("SN GPONA62D6F78 已注册在 gpon-onu_1/2/5:8" in error for error in errors))

    def test_c300_verification_parses_registration_transport_and_services(self):
        driver = ZteC300OnuDriver()
        request = make_c300_request()
        commands = driver.build_verify_commands(request)
        responses = c300_verify_responses()
        outputs = ["ZXAN#", *(responses[command] for command in commands[1:])]

        self.assertEqual(driver.validate_verification(request, outputs), [])
        self.assertIn("show gpon onu detail-info gpon-onu_1/2/1:3", commands)
        self.assertIn("show gpon remote-onu service gpon-onu_1/2/1:3", commands)
        self.assertIn("show gpon remote-onu mvlan gpon-onu_1/2/1:3", commands)

        broken = list(outputs)
        broken[-1] = "Multicast VLAN: 601\nZXAN#"
        self.assertIn("组播 VLAN 600 验证失败", driver.validate_verification(request, broken))

    def test_c600_mapping_and_discovered_speed_defaults_to_auto(self):
        self.assertEqual(
            parse_service_mappings("1,170\n2:335"),
            [OnuServiceMapping(1, 170), OnuServiceMapping(2, 335)],
        )
        self.assertEqual(speed_mode_to_cli("XGS-PON"), "auto")
        self.assertEqual(speed_mode_to_cli("GPON"), "auto")

    def test_c600_auto_speed_omits_real_speed_command_and_verification(self):
        driver = ZteC600OnuDriver()
        request = replace(make_c600_request(), real_speed="auto")

        commands = driver.build_provision_commands(request)
        verification = c600_verify_responses()
        collection_command = driver.build_verify_commands(request)[0]
        verification[collection_command] = verification[collection_command].replace(
            "  real-speed xgspon\n", ""
        )

        self.assertFalse(any(command.startswith("real-speed ") for command in commands))
        outputs = [verification[command] for command in driver.build_verify_commands(request)]
        self.assertEqual(driver.validate_verification(request, outputs), [])

    def test_c600_mvlan_verification_requires_fixed_vlan_600(self):
        driver = ZteC600OnuDriver()
        request = make_c600_request()
        commands = driver.build_verify_commands(request)
        responses = c600_verify_responses()
        outputs = [responses[command] for command in commands]

        self.assertEqual(driver.validate_verification(request, outputs), [])
        outputs[-1] = "Multicast VLAN: no related data.\nZXAN#"
        self.assertIn("C600 组播 VLAN 600 验证失败", driver.validate_verification(request, outputs))

    def test_c600_precheck_uses_exact_id_and_global_sn_queries(self):
        driver = ZteC600OnuDriver()
        request = make_c600_request()
        commands = driver.build_precheck_commands(request)
        responses = c600_precheck_responses()

        self.assertEqual(commands, [
            "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode",
            "show gpon onu baseinfo gpon_olt-1/1/5 55",
            "show gpon onu by sn ZTEG12345678",
        ])
        self.assertEqual(
            driver.validate_precheck(request, [responses[command] for command in commands]),
            [],
        )
        self.assertTrue(driver.precheck_allows_cli_error(commands[1]))
        self.assertTrue(driver.precheck_allows_cli_error(commands[2]))

    def test_c600_requires_vlan_600_when_mvlan_is_fixed(self):
        request = make_c600_request()
        request = replace(
            request,
            services=(OnuServiceMapping(1, 170), OnuServiceMapping(2, 335)),
        )

        errors = ZteC600OnuDriver().validate_request(request)

        self.assertIn("C600 固定 MVLAN 600，业务映射必须包含 VLAN 600", errors)

    def test_c600_global_sn_precheck_rejects_other_pon_registration(self):
        driver = ZteC600OnuDriver()
        request = make_c600_request()
        outputs = [
            "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#",
            "%Error 222331: ONU data is null.\nZXAN#",
            "SearchResult\n---\ngpon_onu-1/2/3:7\nZXAN#",
        ]

        errors = driver.validate_precheck(request, outputs)

        self.assertIn("SN ZTEG12345678 已注册在 gpon_onu-1/2/3:7", errors)

    def test_c600_service_port_parser_handles_real_terminal_wrapping(self):
        output = (
            "1     1     449      --      170      170    --       --       --       --     1\n"
            "70  --  --    --   --   --  --      --   --      --      --  OK     YES    --\n"
            "2     1     450      --      171      171    --       --       --       --     1\n"
            "71  --  --    --   --   --  --      --   --      --      --  OK     YES    --\n"
            "Sport total number:\n2\nZXAN#"
        )

        parsed = ZteC600OnuDriver.parse_service_port_statuses(output)

        self.assertEqual(parsed, {1: "OK/YES", 2: "OK/YES"})


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

    def test_c600_register_runs_global_precheck_readiness_and_full_verification(self):
        request = make_c600_request()
        fake = FakeSession(responses=c600_register_responses())
        logs = []
        service = OnuRegistrationService(logger=logs.append, session_type=fake)

        result = service.register(make_connection(), [request])

        self.assertTrue(result.ok)
        self.assertIn("interface gpon_olt-1/1/5", fake.commands)
        self.assertIn("show gpon onu by sn ZTEG12345678", fake.commands)
        self.assertIn("show gpon onu state gpon_olt-1/1/5 55", fake.commands)
        self.assertIn("show collection pon-onu gpon_onu-1/1/5:55 config", fake.commands)
        self.assertIn("show service-port interface gpon_onu-1/1/5:55", fake.commands)
        self.assertIn("show gpon onu detail-info gpon_onu-1/1/5:55", fake.commands)
        self.assertIn("show gpon remote-onu mvlan gpon_onu-1/1/5:55", fake.commands)
        self.assertTrue(any("阶段 1/3" in item for item in logs))
        self.assertTrue(any("阶段 3/3" in item for item in logs))

    def test_c600_precheck_rejects_occupied_onu_id_before_configure(self):
        request = make_c600_request()
        fake = FakeSession(
            responses={
                "show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode": (
                    "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\nZXAN#"
                ),
                "show gpon onu baseinfo gpon_olt-1/1/5 55": (
                    "gpon_onu-1/1/5:55 OLD sn SN:ZTEG00000000 ready\nZXAN#"
                ),
                "show gpon onu by sn ZTEG12345678": (
                    "%Error 230285: No related information to show.\nZXAN#"
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
            responses=c300_precheck_responses(),
            fail_once="service Internet gemport 1 vlan 200",
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.register(make_connection(), [request])

        self.assertFalse(result.ok)
        self.assertNotIn("no onu", "\n".join(fake.commands))

    def test_c300_authorized_cleanup_deletes_only_selected_same_pon_onu_and_retries(self):
        request = make_c300_request()
        responses = c300_register_responses()
        responses["show gpon onu state"] = (
            "1/2/1:8 enable disable DyingGasp 1(GPON)\n"
            "1/2/1:9 enable disable LOS 1(GPON)\n"
            "1/2/5:7 enable disable DyingGasp 1(GPON)\n"
            "1/2/5:2 enable enable working 1(GPON)\nZXAN#"
        )
        responses["show gpon onu baseinfo gpon-olt_1/2/1 8"] = (
            "gpon-onu_1/2/1:8 SD-41 sn SN:GPON12345678 ready\nZXAN#"
        )
        fake = FakeSession(
            responses=responses,
            fail_once="service Internet gemport 1 vlan 200",
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.register(
            make_connection(),
            [request],
            c300_cleanup_candidate=C300CleanupCandidate(
                "gpon-onu_1/2/1:8",
                "gpon-olt_1/2/1",
                8,
                "DyingGasp",
                "GPON12345678",
                "SD-41",
            ),
        )

        self.assertTrue(result.ok)
        self.assertIn("no onu 8", fake.commands)
        self.assertNotIn("no onu 9", fake.commands)
        self.assertNotIn("no onu 7", fake.commands)
        self.assertNotIn("no onu 2", fake.commands)
        self.assertEqual(fake.commands.count("onu 3 type SD-41 sn GPONA62D6F78"), 2)

    def test_c300_register_runs_targeted_precheck_and_full_verification(self):
        request = make_c300_request()
        responses = c300_register_responses()
        fake = FakeSession(responses=responses)
        service = OnuRegistrationService(session_type=fake)

        result = service.register(make_connection(), [request])

        self.assertTrue(result.ok, result.message)
        self.assertIn("show gpon onu by sn GPONA62D6F78", fake.commands)
        self.assertIn("show gpon onu tcont gpon-olt_1/2/1 3", fake.commands)
        self.assertIn("show service-port interface gpon-onu_1/2/1:3", fake.commands)

    def test_c300_cleanup_rejects_selected_onu_when_it_is_other_pon_or_online(self):
        driver = ZteC300OnuDriver()
        state = (
            "1/2/1:8 enable enable working 1(GPON)\n"
            "1/2/5:7 enable disable DyingGasp 1(GPON)\nZXAN#"
        )

        self.assertEqual(
            driver.build_cleanup_commands(
                make_c300_request(), state, "gpon-onu_1/2/1:8"
            ),
            [],
        )
        self.assertEqual(
            driver.build_cleanup_commands(
                make_c300_request(), state, "gpon-onu_1/2/5:7"
            ),
            [],
        )

    def test_c600_offline_after_config_is_not_reported_success(self):
        responses = c600_register_responses()
        responses["show gpon onu state gpon_olt-1/1/5 55"] = (
            "1/1/5:55 enable disable OffLine N/A\nONU Number: 0/1\nZXAN#"
        )
        fake = FakeSession(responses=responses)
        service = OnuRegistrationService(
            session_type=fake,
            readiness_timeout=0,
        )

        result = service.register(make_connection(), [make_c600_request()])

        self.assertFalse(result.ok)
        self.assertIn("配置已下发，但 ONU 未在 0 秒内上线", result.message)
        self.assertNotIn("show collection pon-onu", "\n".join(fake.commands))

    def test_cleanup_candidate_query_returns_only_same_pon_with_identity(self):
        responses = {
            "show gpon onu state": (
                "1/2/1:8 enable disable DyingGasp 1(GPON)\n"
                "1/2/1:9 enable enable working 1(GPON)\n"
                "1/2/5:7 enable disable LOS 1(GPON)\nZXAN#"
            ),
            "show gpon onu baseinfo gpon-olt_1/2/1 8": (
                "gpon-onu_1/2/1:8 SD-41 sn SN:GPON12345678 ready\nZXAN#"
            ),
        }
        fake = FakeSession(responses=responses)
        service = OnuRegistrationService(session_type=fake)

        result = service.query_c300_cleanup_candidates(
            make_connection(),
            make_c300_request(),
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.cleanup_candidates), 1)
        candidate = result.cleanup_candidates[0]
        self.assertEqual(candidate.onu_interface, "gpon-onu_1/2/1:8")
        self.assertEqual(candidate.serial_number, "GPON12345678")

    def test_both_olt_families_reject_multi_onu_registration(self):
        service = OnuRegistrationService(session_type=FakeSession())

        result = service.register(make_connection(), [make_c300_request(), make_c300_request()])

        self.assertFalse(result.ok)
        self.assertIn("C300 每次只能注册一台 ONU", result.message)

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

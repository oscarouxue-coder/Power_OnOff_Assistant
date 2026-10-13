import threading
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver, parse_service_mappings, speed_mode_to_cli
from src.core.zte_olt_telnet import OltCommandError, OperationCancelled, ZteOltTelnetSession
from src.models.onu_registration_models import (
    C300CleanupCandidate,
    DiscoveredOnu,
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OltConnection,
    OnuCommandPlan,
    OnuDiscoveryScope,
    OnuProvisionRequest,
    OnuServiceMapping,
    OnuTemplate,
    RegisteredOnu,
)
from src.services.onu_command_edit_service import OnuCommandEditService
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
        real_speed="auto",
        tcont_profile="WT-10G",
        services=(
            OnuServiceMapping(1, 170),
            OnuServiceMapping(2, 171),
            OnuServiceMapping(3, 172),
            OnuServiceMapping(4, 173),
            OnuServiceMapping(5, 335),
            OnuServiceMapping(6, 600),
            OnuServiceMapping(7, 50),
            OnuServiceMapping(8, 151),
            OnuServiceMapping(9, 150),
        ),
    )


def c300_precheck_responses():
    return {
        "show gpon onu uncfg": (
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
    services = (
        (1, 1, 170),
        (2, 1, 171),
        (3, 1, 172),
        (4, 1, 173),
        (5, 2, 335),
        (6, 3, 600),
        (7, 4, 50),
        (8, 1, 151),
        (9, 1, 150),
    )
    collection = (
        "gpon_onu-1/1/5:55 CXP-55 sn SN:ZTEG12345678 ready\n"
        "interface gpon_onu-1/1/5:55\n"
        "  tcont 1 profile WT-10G\n"
        "  tcont 2 profile DBA_FONE\n"
        "  tcont 3 profile DBA_IPTV\n"
        "  tcont 4 profile DBA_TR069\n"
        "  sn-bind enable both\n"
        "  gemport 1 tcont 1\n"
        "  gemport 2 tcont 2\n"
        "  gemport 3 tcont 3\n"
        "  gemport 4 tcont 4\n"
        "pon-onu-mng gpon_onu-1/1/5:55\n"
        + "".join(
            f"  service {service_id} gemport {gemport_id} vlan {vlan}\n"
            for service_id, gemport_id, vlan in services
        )
        + "  mvlan 600\n"
        + "interface vport-1/1/5.55:1\n"
        + "".join(
            f"  service-port {service_id} user-vlan {vlan} vlan {vlan}\n"
            for service_id, gemport_id, vlan in services
            if gemport_id == 1
        )
        + "interface vport-1/1/5.55:2\n"
        + "  service-port 5 user-vlan 335 vlan 335\n"
        + "interface vport-1/1/5.55:3\n"
        + "  service-port 6 user-vlan 600 vlan 600\n"
        + "  igmp fast-leave enable\n"
        + "  igmp version v2\n"
        + "interface vport-1/1/5.55:4\n"
        + "  service-port 7 user-vlan 50 vlan 50\n"
        + "igmp mvlan 600\n"
        + "  receive-port vport-1/1/5.55:3\n"
        + "ZXAN#"
    )
    service_ports = "".join(
        f"{service_id} {gemport_id} {448 + service_id} -- {vlan} {vlan} -- -- -- -- {vlan} "
        "-- -- -- -- -- -- -- -- -- -- OK YES --\n"
        for service_id, gemport_id, vlan in services
    ) + (
        f"Sport total number:\n{len(services)}\nZXAN#"
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
    def test_template_parsers_keep_pon_type_and_bandwidth_rate(self):
        c300_types = ZteC300OnuDriver().parse_templates(
            "onu_type",
            "ONU type name:          SD-41\nPON type:               gpon\nDescription: 4_eth_1_pots\n",
        )
        c600_types = ZteC600OnuDriver().parse_templates(
            "onu_type",
            "ONU type name:          OSCAR_XGS\nPON type:               gpon\nSpeed mode:             XGS-PON\n",
        )
        c300_dba = ZteC300OnuDriver().parse_templates(
            "dba",
            "Profile name :1G\n Type FBW(kbps) ABW(kbps) MBW(kbps)\n 4 0 0 1024000\n",
        )
        c600_dba = ZteC600OnuDriver().parse_templates(
            "dba",
            "Profile name :WT-10G\n Current used counter :5\n Type FBW(kbps) ABW(kbps) MBW(kbps)\n 4 0 0 9216000\n",
        )

        self.assertEqual(c300_types, [OnuTemplate("SD-41", "onu_type", pon_type="GPON")])
        self.assertEqual(c600_types, [OnuTemplate("OSCAR_XGS", "onu_type", pon_type="XGS-PON")])
        self.assertEqual(c300_types[0].display_text, "SD-41（GPON）")
        self.assertEqual(c600_types[0].display_text, "OSCAR_XGS（XGS-PON）")
        self.assertEqual(c300_dba[0].display_text, "1G（1G）")
        self.assertEqual(c600_dba[0].display_text, "WT-10G（10G）")

    def test_all_zero_scope_is_only_valid_for_whole_olt_discovery(self):
        all_olt = OnuDiscoveryScope(0, 0, 0)

        self.assertTrue(all_olt.is_all_olt)
        self.assertEqual(all_olt.validate(), [])
        self.assertTrue(OnuDiscoveryScope(0, 1, 1).validate())
        self.assertEqual(
            ZteC600OnuDriver().build_discovery_command(all_olt),
            "show pon onu uncfg sn model speed-mode",
        )

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
        self.assertIn("interface vport-1/1/5.55:2", commands)
        self.assertIn("interface vport-1/1/5.55:3", commands)
        self.assertIn("interface vport-1/1/5.55:4", commands)
        self.assertIn("tcont 1 profile WT-10G", commands)
        self.assertIn("tcont 2 profile DBA_FONE", commands)
        self.assertIn("tcont 3 profile DBA_IPTV", commands)
        self.assertIn("tcont 4 profile DBA_TR069", commands)
        self.assertIn("service 5 gemport 2 vlan 335", commands)
        self.assertIn("service 6 gemport 3 vlan 600", commands)
        self.assertIn("service 7 gemport 4 vlan 50", commands)
        self.assertIn("service 9 gemport 1 vlan 150", commands)
        self.assertIn("mvlan 600", commands)
        self.assertIn("service-port 5 user-vlan 335 vlan 335", commands)
        self.assertIn("igmp fast-leave enable", commands)
        self.assertIn("igmp version v2", commands)
        self.assertIn("igmp mvlan 600", commands)
        self.assertIn("receive-port vport-1/1/5.55:3", commands)
        self.assertFalse(any("gpon-olt_" in command for command in commands))
        self.assertNotIn("write", commands)

    def test_c300_parameterized_request_uses_selected_id_profile_and_business_ids(self):
        request = replace(
            make_c300_request(),
            onu_id=8,
            onu_type="SD-41-CUSTOM",
            tcont_id=2,
            tcont_profile="1G-CUSTOM",
            services=(
                OnuServiceMapping(11, 200), OnuServiceMapping(12, 46),
                OnuServiceMapping(13, 335), OnuServiceMapping(14, 600),
                OnuServiceMapping(15, 171), OnuServiceMapping(16, 172),
            ),
        )

        commands = ZteC300OnuDriver().build_provision_commands(request)

        self.assertIn("onu 8 type SD-41-CUSTOM sn GPONA62D6F78", commands)
        self.assertIn("tcont 2 profile 1G-CUSTOM", commands)
        self.assertIn("gemport 11 tcont 2", commands)
        self.assertIn("service-port 14 vport 14 user-vlan 600 vlan 600", commands)
        self.assertIn("service IPTV gemport 14 vlan 600", commands)

    def test_c600_rejects_internet_resource_ids_that_collide_with_fixed_layers(self):
        request = replace(make_c600_request(), tcont_id=2, gemport_id=4, vport_id=3)

        errors = ZteC600OnuDriver().validate_request(request)

        self.assertIn("上网 T-CONT ID 2 与语音/组播/TR069 固定业务冲突", errors)
        self.assertIn("上网 GEM Port 4 与语音/组播/TR069 固定业务冲突", errors)
        self.assertIn("上网 VPort ID 3 与语音/组播/TR069 固定业务冲突", errors)
        self.assertIn(
            "上网 VPort ID 必须与上网 GEM Port ID 一致（C600 gemport模式为1:1映射）",
            errors,
        )

        invalid_template_errors = ZteC600OnuDriver().validate_request(
            replace(make_c600_request(), onu_type="OSCAR XGS")
        )
        self.assertIn(
            "ONU 类型模板名称只能包含字母、数字、点、下划线和连字符",
            invalid_template_errors,
        )

    def test_c300_and_c600_parse_their_own_discovery_formats(self):
        c300 = ZteC300OnuDriver().parse_discovery(
            "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\n"
        )
        c600 = ZteC600OnuDriver().parse_discovery(
            "gpon_olt-1/1/5 CXP-55 ZTEG12345678 XGS-PON\n"
        )

        self.assertEqual(c300[0].onu_interface, "gpon-onu_1/2/1:3")
        self.assertEqual(c300[0].suggested_onu_id, 3)
        self.assertEqual(c300[0].registration_type, "SD-41（配置模板）")
        self.assertEqual(c300[0].pon_type, "GPON（根据接口推断）")
        self.assertEqual(
            c300[0].display_text,
            "gpon-onu_1/2/1:3  注册类型:SD-41（配置模板）  "
            "SN:GPONA62D6F78  PON类型:GPON（根据接口推断）  状态:unknown",
        )
        self.assertEqual(c600[0].pon_interface, "gpon_olt-1/1/5")
        self.assertEqual(c600[0].model, "CXP-55")
        self.assertEqual(
            c600[0].display_text,
            "gpon_olt-1/1/5  型号:CXP-55  SN:ZTEG12345678  速率:XGS-PON",
        )

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
            "show gpon onu uncfg",
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

    def test_c600_verification_rejects_wrong_vport_and_missing_igmp_receive_port(self):
        driver = ZteC600OnuDriver()
        request = make_c600_request()
        commands = driver.build_verify_commands(request)
        responses = c600_verify_responses()
        outputs = [responses[command] for command in commands]
        outputs[0] = outputs[0].replace(
            "  receive-port vport-1/1/5.55:3\n", ""
        )
        outputs[1] = outputs[1].replace(
            "5 2 453 --", "5 1 453 --"
        )

        errors = driver.validate_verification(request, outputs)

        self.assertTrue(any("receive-port" in error for error in errors))
        self.assertIn("C600 service-port 5 VPort异常：期望2，实际1", errors)

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
        details = ZteC600OnuDriver.parse_service_port_details(output)

        self.assertEqual(parsed, {1: "OK/YES", 2: "OK/YES"})
        self.assertEqual(details, {1: (1, "OK/YES"), 2: (1, "OK/YES")})

    def test_c300_registered_query_lists_all_states(self):
        driver = ZteC300OnuDriver()
        pon_interface = "gpon-olt_1/2/1"

        self.assertEqual(
            driver.build_registered_query_command(pon_interface),
            "show gpon onu state",
        )
        state = (
            "1/2/1:8 enable disable DyingGasp 1(GPON)\n"
            "1/2/1:9 enable enable working 1(GPON)\n"
            "1/2/5:7 enable disable LOS 1(GPON)\nZXAN#"
        )
        candidates = driver.parse_registered_candidates(pon_interface, state)

        self.assertEqual(
            [candidate.onu_interface for candidate in candidates],
            ["gpon-onu_1/2/1:8", "gpon-onu_1/2/1:9"],
        )
        self.assertEqual(candidates[0].onu_id, 8)
        self.assertEqual(candidates[0].state, "DyingGasp")
        self.assertEqual(candidates[1].state, "working")

    def test_c300_registered_delete_commands_target_one_onu(self):
        driver = ZteC300OnuDriver()
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C300,
            pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:8",
            onu_id=8,
            state="DyingGasp",
            serial_number="GPON12345678",
            onu_type="SD-41",
        )

        self.assertEqual(
            driver.build_delete_identity_command(candidate),
            "show gpon onu baseinfo gpon-olt_1/2/1 8",
        )
        self.assertEqual(
            driver.build_delete_commands(candidate),
            [
                "configure terminal",
                "interface gpon-olt_1/2/1",
                "no onu 8",
                "exit",
                "end",
            ],
        )
        self.assertTrue(driver.deleted_if_baseinfo_empty("%Code 62331-GPONSRV : ONU data is null.\nZXAN#"))
        self.assertFalse(driver.deleted_if_baseinfo_empty("gpon-onu_1/2/1:8 SD-41 sn SN:GPON12345678 ready\nZXAN#"))

    def test_c600_registered_query_lists_all_states(self):
        driver = ZteC600OnuDriver()
        pon_interface = "gpon_olt-1/1/5"

        self.assertEqual(
            driver.build_registered_query_command(pon_interface),
            "show running-config-interface gpon_olt-1/1/5",
        )
        self.assertEqual(
            driver.parse_registered_onu_defs(
                "interface gpon_olt-1/1/5\n"
                "onu 55 type CXP-55 sn ZTEG12345678\n"
                "onu 56 type CXP-55 sn ZTEG99999999\nZXAN#"
            ),
            [(55, "CXP-55", "ZTEG12345678"), (56, "CXP-55", "ZTEG99999999")],
        )
        self.assertEqual(
            RegisteredOnu(
                family=OLT_FAMILY_C600,
                pon_interface=pon_interface,
                onu_interface="gpon_onu-1/1/5:55",
                onu_id=55,
                state="OffLine",
                serial_number="ZTEG12345678",
                onu_type="OSCAR_XGS",
            ).display_text,
            "gpon_onu-1/1/5:55  类型模板:OSCAR_XGS  SN:ZTEG12345678  状态:OffLine",
        )
        self.assertEqual(
            driver.build_onu_state_command(pon_interface, 55),
            "show gpon onu state gpon_olt-1/1/5 55",
        )
        self.assertEqual(
            driver.parse_onu_state_label("1/1/5:55 enable disable OffLine N/A\nZXAN#"),
            "OffLine",
        )
        self.assertEqual(
            driver.parse_onu_state_label("1/1/5:56 enable enable working XGS-PON\nZXAN#"),
            "working",
        )

    def test_c600_registered_delete_commands_target_one_onu(self):
        driver = ZteC600OnuDriver()
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="OffLine",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )

        self.assertEqual(
            driver.build_delete_identity_command(candidate),
            "show gpon onu baseinfo gpon_olt-1/1/5 55",
        )
        self.assertEqual(
            driver.build_delete_commands(candidate),
            [
                "configure terminal",
                "interface gpon_olt-1/1/5",
                "no onu 55",
                "exit",
                "end",
            ],
        )
        self.assertTrue(driver.deleted_if_baseinfo_empty("%Error 222331: ONU data is null.\nZXAN#"))


class ServiceTests(unittest.TestCase):
    def test_template_query_runs_only_the_verified_read_only_command(self):
        output = (
            "ONU type name:          OSCAR_XGS\n"
            "PON type:               gpon\n"
            "Speed mode:             XGS-PON\nZXAN#"
        )
        fake = FakeSession(responses={"show onu-type": output})

        result = OnuRegistrationService(session_type=fake).query_templates(
            OLT_FAMILY_C600, make_connection(), "onu_type"
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.templates[0].display_text, "OSCAR_XGS（XGS-PON）")
        self.assertEqual(fake.commands, ["terminal length 0", "show onu-type"])

    def test_c300_whole_olt_query_does_not_filter_global_results(self):
        output = (
            "gpon-onu_1/2/1:3 GPONA62D6F78 unknown\n"
            "gpon-onu_1/2/2:5 GPONA62D6F79 unknown\nZXAN#"
        )
        fake = FakeSession(responses={"show gpon onu uncfg": output})

        result = OnuRegistrationService(session_type=fake).query_unregistered(
            OLT_FAMILY_C300, make_connection(), OnuDiscoveryScope(0, 0, 0)
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.onus), 2)
        self.assertEqual(fake.commands, ["terminal length 0", "show gpon onu uncfg"])

    def test_partial_zero_scope_is_rejected_before_any_olt_command(self):
        fake = FakeSession()

        result = OnuRegistrationService(session_type=fake).query_unregistered(
            OLT_FAMILY_C300, make_connection(), OnuDiscoveryScope(0, 1, 1)
        )

        self.assertFalse(result.ok)
        self.assertIn("同时为 0", result.message)
        self.assertEqual(fake.commands, [])

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

    def test_batch_rejects_duplicate_target_before_any_olt_command(self):
        service = OnuRegistrationService(session_type=FakeSession())

        result = service.register(make_connection(), [make_c300_request(), make_c300_request()])

        self.assertFalse(result.ok)
        self.assertIn("批量目标 SN 重复", result.message)

    @patch("src.services.onu_registration_service.driver_for_family")
    def test_batch_completes_all_prechecks_before_first_provision_command(self, driver_for_family):
        first = replace(make_c300_request(), onu_id=3)
        second = replace(
            first,
            onu=replace(
                first.onu,
                onu_interface="gpon-onu_1/2/1:4",
                suggested_onu_id=4,
                serial_number="GPONA62D6F79",
            ),
            onu_id=4,
        )
        driver = MagicMock()
        driver.validate_request.return_value = []
        driver.build_precheck_commands.side_effect = lambda request: [f"precheck {request.onu_id}"]
        driver.precheck_allows_cli_error.return_value = False
        driver.validate_precheck.return_value = []
        driver.build_provision_commands.side_effect = lambda request: [f"provision {request.onu_id}"]
        driver.build_readiness_command.side_effect = lambda request: f"ready {request.onu_id}"
        driver.readiness_state.return_value = (True, "working")
        driver.build_verify_commands.side_effect = lambda request: [f"verify {request.onu_id}"]
        driver.validate_verification.return_value = []
        driver_for_family.return_value = driver
        session = MagicMock()
        session.execute.return_value = "ZXAN#"
        session.execute_many.return_value = ["ZXAN#"]
        timeline = MagicMock()
        timeline.attach_mock(session.execute, "execute")
        timeline.attach_mock(session.execute_many, "execute_many")
        service = OnuRegistrationService(session_type=lambda *_args, **_kwargs: session)

        result = service.register(make_connection(), [first, second])

        self.assertTrue(result.ok, result.message)
        names_and_commands = [
            (
                call[0],
                call.args[0][0] if call[0] == "execute_many" else call.args[0],
            )
            for call in timeline.mock_calls
            if call[0] in {"execute", "execute_many"}
        ]
        self.assertEqual(
            names_and_commands[:3],
            [("execute", "precheck 3"), ("execute", "precheck 4"), ("execute_many", "provision 3")],
        )

    def test_c600_allows_explicit_independent_write(self):
        fake = FakeSession()
        service = OnuRegistrationService(session_type=fake)
        result = service.save_configuration(OLT_FAMILY_C600, make_connection())

        self.assertTrue(result.ok)
        self.assertEqual(fake.commands, ["write"])
        self.assertIn("已写入启动配置", result.message)

    def test_query_registered_candidates_lists_all_with_identity(self):
        responses = {
            "show running-config-interface gpon_olt-1/1/5": (
                "interface gpon_olt-1/1/5\n"
                "onu 55 type CXP-55 sn ZTEG12345678\n"
                "onu 56 type CXP-55 sn ZTEG99999999\nZXAN#"
            ),
            "show gpon onu state gpon_olt-1/1/5 55": (
                "1/1/5:55 enable disable OffLine N/A\nZXAN#"
            ),
            "show gpon onu state gpon_olt-1/1/5 56": (
                "1/1/5:56 enable enable working XGS-PON\nZXAN#"
            ),
        }
        fake = FakeSession(responses=responses)
        service = OnuRegistrationService(session_type=fake)

        result = service.query_registered_candidates(
            OLT_FAMILY_C600,
            make_connection(),
            "gpon_olt-1/1/5",
        )

        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(result.registered_onus), 2)
        self.assertEqual(
            [item.onu_interface for item in result.registered_onus],
            ["gpon_onu-1/1/5:55", "gpon_onu-1/1/5:56"],
        )
        self.assertEqual(result.registered_onus[0].serial_number, "ZTEG12345678")
        self.assertEqual(result.registered_onus[0].state, "OffLine")
        self.assertEqual(result.registered_onus[1].state, "working")

    def test_delete_registered_onu_rechecks_identity_and_verifies_after(self):
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="working",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )
        responses = {
            "show gpon onu baseinfo gpon_olt-1/1/5 55": [
                "gpon_onu-1/1/5:55 CXP-55 sn SN:ZTEG12345678 ready\nZXAN#",
                "%Error 222331: ONU data is null.\nZXAN#",
            ],
        }
        fake = FakeSession(responses=responses)
        service = OnuRegistrationService(session_type=fake)

        result = service.delete_registered_onu(OLT_FAMILY_C600, make_connection(), candidate)

        self.assertTrue(result.ok, result.message)
        self.assertIn("interface gpon_olt-1/1/5", fake.commands)
        self.assertEqual(fake.commands.count("no onu 55"), 1)
        self.assertIn("未执行 write", result.message)

    def test_delete_registered_onu_rejects_when_sn_changed(self):
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="OffLine",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )
        fake = FakeSession(
            responses={
                "show gpon onu baseinfo gpon_olt-1/1/5 55": (
                    "gpon_onu-1/1/5:55 CXP-55 sn SN:ZTEG99999999 ready\nZXAN#"
                ),
            }
        )
        service = OnuRegistrationService(session_type=fake)

        result = service.delete_registered_onu(OLT_FAMILY_C600, make_connection(), candidate)

        self.assertFalse(result.ok)
        self.assertIn("SN 已变化", result.message)
        self.assertNotIn("no onu", "\n".join(fake.commands))


class EditedRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.editor = OnuCommandEditService()

    def prepare(self, base, effective=None):
        commands = driver_for_family(base.family).build_provision_commands(effective or base)
        return self.editor.prepare(base, "\n".join(commands))

    @staticmethod
    def c300_batch():
        first = make_c300_request()
        second = replace(
            first,
            onu=replace(
                first.onu,
                onu_interface="gpon-onu_1/2/1:4",
                suggested_onu_id=4,
                serial_number="GPONA62D6F79",
            ),
            onu_id=4,
        )
        return first, second

    @staticmethod
    def batch_driver():
        driver = MagicMock()
        driver.validate_request.return_value = []
        driver.build_precheck_commands.side_effect = (
            lambda request: [f"precheck {request.onu.serial_number}"]
        )
        driver.precheck_allows_cli_error.return_value = False
        driver.validate_precheck.return_value = []
        driver.build_readiness_command.side_effect = (
            lambda request: f"ready {request.onu.serial_number}"
        )
        driver.readiness_state.return_value = (True, "working")
        driver.build_verify_commands.side_effect = (
            lambda request: [f"verify {request.onu.serial_number}"]
        )
        driver.validate_verification.return_value = []
        return driver

    def test_unedited_plans_preserve_c300_and_c600_command_sequences(self):
        for request, responses in (
            (make_c300_request(), c300_register_responses()),
            (make_c600_request(), c600_register_responses()),
        ):
            with self.subTest(family=request.family):
                plan = self.prepare(request)
                fake = FakeSession(responses=responses)
                result = OnuRegistrationService(session_type=fake).register(
                    make_connection(), [request], command_plans=[plan]
                )
                self.assertTrue(result.ok, result.message)
                start = fake.commands.index("configure terminal")
                self.assertEqual(tuple(fake.commands[start:start + len(plan.commands)]), plan.commands)
                self.assertNotIn("write", fake.commands)

    def test_c300_edited_commands_and_verification_use_new_business_values(self):
        base = make_c300_request()
        effective = replace(
            base,
            onu_type="SD-42",
            tcont_profile="2G",
            services=tuple(
                OnuServiceMapping(index, vlan)
                for index, vlan in enumerate((201, 46, 335, 600, 171, 172), 1)
            ),
        )
        plan = self.prepare(base, effective)
        responses = c300_register_responses()
        for command, output in responses.items():
            if isinstance(output, list):
                responses[command] = [item.replace("SD-41", "SD-42") for item in output]
            else:
                responses[command] = output.replace("SD-41", "SD-42").replace("200", "201").replace("1G", "2G")
        fake = FakeSession(responses=responses)
        logs = []
        result = OnuRegistrationService(logger=logs.append, session_type=fake).register(
            make_connection(), [base], command_plans=(plan,)
        )
        self.assertTrue(result.ok, result.message)
        self.assertIn("onu 3 type SD-42 sn GPONA62D6F78", fake.commands)
        self.assertIn("tcont 1 profile 2G", fake.commands)
        self.assertIn("service Internet gemport 1 vlan 201", fake.commands)
        self.assertNotIn("service Internet gemport 1 vlan 200", fake.commands)
        self.assertTrue(any(f"已编辑，实际 {len(plan.commands)} 条" in entry for entry in logs))

    def test_c600_edited_commands_and_verification_use_new_business_values(self):
        base = make_c600_request()
        effective = replace(
            base,
            onu_type="CXP-56",
            tcont_profile="WT-20G",
            real_speed="xgspon",
            services=tuple(
                replace(item, vlan=174) if item.vlan == 170 else item
                for item in base.services
            ),
        )
        plan = self.prepare(base, effective)
        responses = {
            command: output.replace("CXP-55", "CXP-56").replace("WT-10G", "WT-20G").replace("170", "174")
            for command, output in c600_register_responses().items()
        }
        collection = "show collection pon-onu gpon_onu-1/1/5:55 config"
        responses[collection] = responses[collection].replace("  tcont 1", "  real-speed xgspon\n  tcont 1")
        fake = FakeSession(responses=responses)
        result = OnuRegistrationService(session_type=fake).register(
            make_connection(), [base], command_plans=(plan,)
        )
        self.assertTrue(result.ok, result.message)
        self.assertIn("onu 55 type CXP-56 sn ZTEG12345678", fake.commands)
        self.assertIn("real-speed xgspon", fake.commands)
        self.assertIn("tcont 1 profile WT-20G", fake.commands)
        self.assertIn("service 1 gemport 1 vlan 174", fake.commands)
        self.assertNotIn("service 1 gemport 1 vlan 170", fake.commands)

    def test_invalid_plans_are_rejected_before_connecting(self):
        base = make_c300_request()
        valid = self.prepare(base)
        other = replace(base, onu=replace(base.onu, serial_number="GPONA62D6F79"))
        invalid_plans = (
            (),
            (valid, valid),
            (object(),),
            (self.prepare(other),),
            (replace(valid, request=replace(valid.request, onu_id=4)),),
            (replace(valid, request=replace(valid.request, onu_type="SD-42")),),
            (replace(valid, commands=valid.commands + ("write",)),),
            (replace(valid, commands=("reload",)),),
        )
        for plans in invalid_plans:
            with self.subTest(plans=plans):
                fake = FakeSession()
                result = OnuRegistrationService(session_type=fake).register(
                    make_connection(), [base], command_plans=plans
                )
                self.assertFalse(result.ok)
                self.assertFalse(fake.connected)
                self.assertNotIn("configure terminal", fake.commands)
                self.assertNotIn("write", fake.commands)
                self.assertNotIn("reload", fake.commands)

    def test_edited_batch_completes_all_prechecks_before_configuring_and_verifies_effective_requests(self):
        items = self.c300_batch()
        plans = tuple(self.prepare(item, replace(item, onu_type="SD-42")) for item in items)
        driver = self.batch_driver()
        fake = FakeSession()
        with patch("src.services.onu_registration_service.driver_for_family", return_value=driver):
            result = OnuRegistrationService(session_type=fake).register(
                make_connection(), items, command_plans=plans
            )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(fake.commands[:2], [f"precheck {item.onu.serial_number}" for item in items])
        self.assertEqual(fake.commands[2], "configure terminal")
        self.assertEqual(
            [call.args[0] for call in driver.validate_verification.call_args_list],
            [plan.request for plan in plans],
        )
        driver.build_provision_commands.assert_not_called()

    def test_edited_batch_precheck_failure_sends_no_configuration(self):
        items = self.c300_batch()
        plans = tuple(self.prepare(item) for item in items)
        driver = self.batch_driver()
        driver.validate_precheck.side_effect = [[], ["second target occupied"]]
        fake = FakeSession()
        with patch("src.services.onu_registration_service.driver_for_family", return_value=driver):
            result = OnuRegistrationService(session_type=fake).register(
                make_connection(), items, command_plans=plans
            )
        self.assertFalse(result.ok)
        self.assertNotIn("configure terminal", fake.commands)

    def test_edited_batch_cli_failure_stops_before_next_target(self):
        items = self.c300_batch()
        plans = tuple(self.prepare(item, replace(item, onu_type="SD-42")) for item in items)
        driver = self.batch_driver()
        failed_command = "onu 3 type SD-42 sn GPONA62D6F78"
        fake = FakeSession(fail_once=failed_command)
        with patch("src.services.onu_registration_service.driver_for_family", return_value=driver):
            result = OnuRegistrationService(session_type=fake).register(
                make_connection(), items, command_plans=plans
            )
        self.assertFalse(result.ok)
        self.assertNotIn("onu 4 type SD-42 sn GPONA62D6F79", fake.commands)
        driver.validate_verification.assert_not_called()
        self.assertTrue(fake.closed)

    def test_edited_batch_verification_failure_stops_before_next_target(self):
        items = self.c300_batch()
        plans = tuple(self.prepare(item) for item in items)
        driver = self.batch_driver()
        driver.validate_verification.return_value = ["unexpected business readback"]
        fake = FakeSession()
        with patch("src.services.onu_registration_service.driver_for_family", return_value=driver):
            result = OnuRegistrationService(session_type=fake).register(
                make_connection(), items, command_plans=plans
            )
        self.assertFalse(result.ok)
        self.assertNotIn("onu 4 type SD-41 sn GPONA62D6F79", fake.commands)
        self.assertEqual(driver.validate_verification.call_count, 1)

    def test_edited_batch_cancellation_stops_before_next_target(self):
        items = self.c300_batch()
        plans = tuple(self.prepare(item) for item in items)
        driver = self.batch_driver()

        class StoppedSession(FakeSession):
            def execute(self, command, timeout=20, fail_on_cli_error=True):
                if command == "onu 3 type SD-41 sn GPONA62D6F78":
                    self.commands.append(command)
                    raise OperationCancelled("操作已停止")
                return super().execute(command, timeout, fail_on_cli_error)

        fake = StoppedSession()
        with patch("src.services.onu_registration_service.driver_for_family", return_value=driver):
            result = OnuRegistrationService(session_type=fake).register(
                make_connection(), items, command_plans=plans, cancel_event=threading.Event()
            )
        self.assertFalse(result.ok)
        self.assertIn("操作已停止", result.message)
        self.assertNotIn("onu 4 type SD-41 sn GPONA62D6F79", fake.commands)
        self.assertTrue(fake.closed)

    def test_command_plan_collection_is_snapshotted_before_connecting(self):
        base = make_c300_request()
        plans = [self.prepare(base)]

        class MutatedInputSession(FakeSession):
            def connect(self):
                plans.clear()
                super().connect()

        fake = MutatedInputSession(responses=c300_register_responses())
        result = OnuRegistrationService(session_type=fake).register(
            make_connection(), [base], command_plans=plans
        )
        self.assertTrue(result.ok, result.message)
        self.assertIn("onu 3 type SD-41 sn GPONA62D6F78", fake.commands)

    def test_c300_cleanup_retry_reuses_edited_command_snapshot(self):
        base = make_c300_request()
        plan = self.prepare(base, replace(base, onu_type="SD-42"))
        responses = c300_register_responses()
        for command, output in responses.items():
            responses[command] = (
                [entry.replace("SD-41", "SD-42") for entry in output]
                if isinstance(output, list) else output.replace("SD-41", "SD-42")
            )
        responses["show gpon onu state"] = "1/2/1:8 enable disable DyingGasp 1(GPON)\nZXAN#"
        responses["show gpon onu baseinfo gpon-olt_1/2/1 8"] = (
            "gpon-onu_1/2/1:8 SD-41 sn SN:GPON12345678 ready\nZXAN#"
        )
        fake = FakeSession(responses=responses, fail_once="service Internet gemport 1 vlan 200")
        result = OnuRegistrationService(session_type=fake).register(
            make_connection(),
            [base],
            c300_cleanup_candidate=C300CleanupCandidate(
                "gpon-onu_1/2/1:8", "gpon-olt_1/2/1", 8, "DyingGasp", "GPON12345678", "SD-41"
            ),
            command_plans=(plan,),
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(fake.commands.count("onu 3 type SD-42 sn GPONA62D6F78"), 2)
        self.assertNotIn("onu 3 type SD-41 sn GPONA62D6F78", fake.commands)
        self.assertEqual(fake.commands.count("no onu 8"), 1)


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

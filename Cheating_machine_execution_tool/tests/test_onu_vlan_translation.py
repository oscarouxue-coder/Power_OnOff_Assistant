"""两侧 VLAN 的配置、资源、快照、执行与回读闭环。仅使用模拟 OLT。"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.onu_registration_store import OnuRegistrationConfig, OnuRegistrationStore
from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver, parse_service_mappings
from src.models.onu_registration_models import OnuServiceMapping
from src.services.onu_command_edit_service import OnuCommandEditService
from src.services.onu_registration_service import OnuRegistrationService
from test_onu_registration_service import (
    FakeSession, c600_precheck_responses, c600_verify_responses,
    make_c300_request, make_c600_request, make_connection,
)


def translated_request():
    return replace(make_c600_request(), services=tuple(
        OnuServiceMapping(item.service_id, {171: 111, 335: 112, 600: 113, 50: 114}.get(item.vlan, item.vlan), item.vlan)
        for item in make_c600_request().services
    ))


def translated_responses():
    # 从独立的原实机格式样本变更 VLAN，避免用待测生成器伪造回读。
    responses = c600_verify_responses()
    collection_key = "show collection pon-onu gpon_onu-1/1/5:55 config"
    collection = responses[collection_key]
    for service_id, gem, user, network in ((2, 1, 111, 171), (5, 2, 112, 335), (6, 3, 113, 600), (7, 4, 114, 50)):
        collection = collection.replace(
            f"service {service_id} gemport {gem} vlan {network}\n",
            f"service {service_id} gemport {gem} vlan {user}\n",
        ).replace(
            f"service-port {service_id} user-vlan {network} vlan {network}\n",
            f"service-port {service_id} user-vlan {user} vlan {network}\n",
        )
    collection = collection.replace("  mvlan 600\n", "  mvlan 113\n")
    collection = collection.replace("  igmp version v2\n", "  igmp version v2\n  mvlan-translate 600 to 113\n")
    responses[collection_key] = collection
    runtime_key = "show service-port interface gpon_onu-1/1/5:55"
    for network, user in ((171, 111), (335, 112), (600, 113), (50, 114)):
        responses[runtime_key] = responses[runtime_key].replace(f"-- {network} {network} --", f"-- {user} {user} --")
    responses["show gpon remote-onu mvlan gpon_onu-1/1/5:55"] = "Multicast VLAN: 113\nZXAN#"
    return responses


class OnuVlanTranslationTests(unittest.TestCase):
    def setUp(self):
        self.driver = ZteC600OnuDriver()
        self.request = translated_request()

    def outputs(self):
        responses = translated_responses()
        return [responses[command] for command in self.driver.build_verify_commands(self.request)]

    def test_old_two_columns_keep_original_semantics_and_separators(self):
        values = parse_service_mappings("1,170\n2:171\n3=172", allow_translation=True)
        self.assertEqual(values, [OnuServiceMapping(1, 170), OnuServiceMapping(2, 171), OnuServiceMapping(3, 172)])
        self.assertEqual([v.effective_network_vlan for v in values], [170, 171, 172])

    def test_three_columns_include_fixed_business_conversions(self):
        values = parse_service_mappings("# 注释\n2,111,171\n5,112,335\n6,113,600\n7,114,50", allow_translation=True)
        self.assertEqual(values, [OnuServiceMapping(2, 111, 171), OnuServiceMapping(5, 112, 335), OnuServiceMapping(6, 113, 600), OnuServiceMapping(7, 114, 50)])

    def test_explicit_equal_vlan_matches_legacy_model_and_default_snapshot(self):
        self.assertEqual(OnuServiceMapping(2, 171, 171), OnuServiceMapping(2, 171))
        base = make_c600_request()
        explicit = replace(base, services=tuple(OnuServiceMapping(i.service_id, i.vlan, i.vlan) for i in base.services))
        self.assertEqual(self.driver.build_provision_commands(explicit), self.driver.build_provision_commands(base))
        self.assertEqual(OnuCommandEditService().build_default(explicit).request, base)

    def test_invalid_three_column_format_reports_original_line(self):
        for invalid in ("2,111,", "2,111,171,200", "2,abc,171", "2,111,171 # comment", "2,111,-1"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "第 3 行"):
                parse_service_mappings("# comment\n\n" + invalid, allow_translation=True)

    def test_c300_parser_does_not_enable_third_column(self):
        with self.assertRaisesRegex(ValueError, "ServiceID,VLAN"):
            parse_service_mappings("2,111,171")

    def test_c300_driver_refuses_programmatic_conversion(self):
        base = replace(make_c300_request(), services=tuple(
            OnuServiceMapping(n, vlan, 201 if n == 1 else None)
            for n, vlan in enumerate((200, 46, 335, 600, 171, 172), 1)
        ))
        self.assertTrue(any("不支持 VLAN 转换" in error for error in ZteC300OnuDriver().validate_request(base)))

    def test_three_column_config_is_saved_reloaded_and_parsed(self):
        text = "1,170\n2,111,171\n5,112,335\n6,113,600\n7,114,50"
        with tempfile.TemporaryDirectory() as directory:
            store = OnuRegistrationStore(Path(directory) / "onu.ini")
            store.save(OnuRegistrationConfig(c600_services=text))
            loaded = store.load()
        self.assertEqual(loaded.c600_services, text)
        self.assertEqual(parse_service_mappings(loaded.c600_services, allow_translation=True)[2], OnuServiceMapping(5, 112, 335))

    def test_ui_collects_three_column_mapping_into_request(self):
        variable = lambda text: Mock(get=Mock(return_value=text))
        context = SimpleNamespace(
            _selected_unregistered_onus=Mock(return_value=[self.request.onu]),
            onu_family_var=variable("C600"), onu_c600_onu_id_var=variable("55"),
            onu_c600_onu_type_var=variable("CXP-55"), onu_c600_real_speed_var=variable("auto"),
            onu_c600_tcont_id_var=variable("1"), onu_c600_tcont_profile_var=variable("WT-10G"),
            onu_c600_gemport_id_var=variable("1"), onu_c600_vport_id_var=variable("1"),
            onu_c600_sn_bind_both_var=variable(True),
            onu_c600_services_text=variable("2,111,171\n5,112,335\n6,113,600\n7,114,50"),
        )
        request, = LineCheckAssistant._build_onu_provision_requests(context)
        self.assertEqual(request.services[0], OnuServiceMapping(2, 111, 171))
        self.assertEqual(request.services[2], OnuServiceMapping(6, 113, 600))

    def test_all_four_business_types_generate_correct_gem_and_vport(self):
        self.assertEqual(self.driver.validate_request(self.request), [])
        commands = self.driver.build_provision_commands(self.request)
        for service_id, gem, user, network in ((2, 1, 111, 171), (5, 2, 112, 335), (6, 3, 113, 600), (7, 4, 114, 50)):
            with self.subTest(network=network):
                self.assertIn(f"service {service_id} gemport {gem} vlan {user}", commands)
                entry = commands.index(f"service-port {service_id} user-vlan {user} vlan {network}")
                start = max(i for i in range(entry) if commands[i].startswith("interface "))
                self.assertEqual(commands[start], f"interface vport-1/1/5.55:{gem}")
        for command in ("tcont 2 profile DBA_FONE", "tcont 3 profile DBA_IPTV", "tcont 4 profile DBA_TR069", "mvlan 113", "igmp mvlan 600", "receive-port vport-1/1/5.55:3"):
            self.assertIn(command, commands)

    def test_multicast_translation_is_only_on_selected_vport(self):
        commands = self.driver.build_provision_commands(self.request)
        position = commands.index("mvlan-translate 600 to 113")
        self.assertEqual(commands[position - 1], "igmp version v2")
        self.assertEqual(commands[position + 1], "exit")
        self.assertEqual(commands.count("mvlan-translate 600 to 113"), 1)
        self.assertFalse(any(c.startswith("mvlan-translate") for c in self.driver.build_provision_commands(make_c600_request())))

    def test_network_vlan_decides_resources_even_if_user_vlan_is_reserved(self):
        request = replace(make_c600_request(), services=(OnuServiceMapping(1, 335, 171), OnuServiceMapping(5, 111, 335), OnuServiceMapping(6, 112, 600)))
        commands = self.driver.build_provision_commands(request)
        self.assertIn("service 1 gemport 1 vlan 335", commands)
        self.assertIn("service 5 gemport 2 vlan 111", commands)
        self.assertIn("service 6 gemport 3 vlan 112", commands)

    def test_only_fixed_business_conversion_preserves_idle_main_resource_parameters(self):
        request = replace(self.request, tcont_id=9, tcont_profile="UNUSED", gemport_id=9, vport_id=9,
                          services=tuple(i for i in self.request.services if i.effective_network_vlan in (335, 600, 50)))
        plan = OnuCommandEditService().build_default(request)
        self.assertEqual(plan.request, request)
        self.assertNotIn("tcont 9 profile UNUSED", plan.commands)

    def test_rejects_duplicate_user_vlan(self):
        request = replace(self.request, services=self.request.services + (OnuServiceMapping(10, 111, 200),))
        self.assertTrue(any("VLAN 不能重复" in error for error in self.driver.validate_request(request)))

    def test_rejects_duplicate_network_vlan(self):
        request = replace(self.request, services=self.request.services + (OnuServiceMapping(10, 200, 171),))
        self.assertTrue(any("网络侧 VLAN 不能重复" in error for error in self.driver.validate_request(request)))

    def test_requires_network_multicast_600_not_merely_user_600(self):
        request = replace(self.request, services=(OnuServiceMapping(6, 600, 601),))
        self.assertTrue(any("必须包含网络侧 VLAN 600" in error for error in self.driver.validate_request(request)))

    def test_rejects_network_vlan_out_of_range(self):
        for number in (0, 4095):
            with self.subTest(number=number):
                request = replace(self.request, services=self.request.services + (OnuServiceMapping(10, 200, number),))
                self.assertTrue(any("网络侧 VLAN" in error and "超出" in error for error in self.driver.validate_request(request)))

    def test_fixed_resource_conflict_is_checked_by_network_vlan(self):
        request = replace(self.request, tcont_id=2, gemport_id=2, vport_id=2)
        self.assertTrue(any("固定业务冲突" in error for error in self.driver.validate_request(request)))

    def test_generated_conversion_plan_round_trips_without_edited_flag(self):
        plan = OnuCommandEditService().build_default(self.request)
        self.assertEqual(plan.request, self.request)
        self.assertFalse(plan.edited)
        self.assertIn("service-port 2 user-vlan 111 vlan 171", plan.commands)

    def test_plan_rejects_inconsistent_user_vlan(self):
        text = "\n".join(self.driver.build_provision_commands(self.request))
        text = text.replace("service-port 2 user-vlan 111", "service-port 2 user-vlan 110")
        with self.assertRaisesRegex(ValueError, "user-vlan 必须"):
            OnuCommandEditService().prepare(self.request, text)

    def test_plan_rejects_conversion_in_wrong_vport_context(self):
        text = "\n".join(self.driver.build_provision_commands(self.request))
        text = text.replace("igmp version v2\nmvlan-translate 600 to 113", "igmp version v2")
        text = text.replace("service-port 7 user-vlan 114 vlan 50", "service-port 7 user-vlan 114 vlan 50\nmvlan-translate 600 to 113")
        with self.assertRaisesRegex(ValueError, "生成规则"):
            OnuCommandEditService().prepare(self.request, text)

    def test_full_readback_accepts_all_four_conversions(self):
        self.assertEqual(self.driver.validate_verification(self.request, self.outputs()), [])

    def test_readback_rejects_wrong_user_or_network_vlan(self):
        for old, new in (("user-vlan 111 vlan 171", "user-vlan 110 vlan 171"), ("user-vlan 112 vlan 335", "user-vlan 112 vlan 336")):
            with self.subTest(new=new):
                outputs = self.outputs()
                outputs[0] = outputs[0].replace(old, new)
                self.assertTrue(any("缺少 service-port" in error for error in self.driver.validate_verification(self.request, outputs)))

    def test_readback_rejects_missing_or_wrong_multicast_translation(self):
        for replacement in ("", "mvlan-translate 600 to 114"):
            with self.subTest(replacement=replacement):
                outputs = self.outputs()
                outputs[0] = outputs[0].replace("mvlan-translate 600 to 113", replacement)
                self.assertTrue(any("缺少组播转换" in error for error in self.driver.validate_verification(self.request, outputs)))

    def test_readback_rejects_multicast_rule_on_other_vport(self):
        outputs = self.outputs()
        outputs[0] = outputs[0].replace("  mvlan-translate 600 to 113\n", "")
        outputs[0] = outputs[0].replace("interface vport-1/1/5.55:4\n", "interface vport-1/1/5.55:4\n  mvlan-translate 600 to 113\n")
        self.assertTrue(any("缺少组播转换" in error for error in self.driver.validate_verification(self.request, outputs)))

    def test_readback_rejects_old_onu_mvlan(self):
        outputs = self.outputs()
        outputs[-1] = "Multicast VLAN: 600\nZXAN#"
        self.assertTrue(any("组播 VLAN 113 验证失败" in error for error in self.driver.validate_verification(self.request, outputs)))

    def test_readback_still_checks_actual_vport_and_runtime_status(self):
        outputs = self.outputs()
        outputs[1] = outputs[1].replace("5 2 453", "5 1 453").replace("OK YES", "ERROR NO", 1)
        errors = self.driver.validate_verification(self.request, outputs)
        self.assertTrue(any("VPort异常" in error for error in errors))
        self.assertTrue(any("运行状态异常" in error for error in errors))

    def test_registration_executes_confirmed_conversion_snapshot_and_logs_results(self):
        session = FakeSession({**c600_precheck_responses(), **translated_responses()})
        logs = []
        service = OnuRegistrationService(session_type=session, logger=logs.append)
        plan = OnuCommandEditService().build_default(self.request)
        result = service.register(make_connection(), [self.request], command_plans=(plan,))
        self.assertTrue(result.ok, result.message)
        start = session.commands.index("configure terminal")
        self.assertEqual(tuple(session.commands[start:start + len(plan.commands)]), plan.commands)
        self.assertNotIn("write", session.commands)
        self.assertTrue(session.closed)
        self.assertTrue(any("ONU侧 VLAN112 ↔ 网络侧 VLAN335" in line for line in logs))
        self.assertTrue(any("组播转换" in line and "VPort 3" in line for line in logs))
        self.assertEqual(sum("VLAN 转换回读成功" in line for line in logs), 4)

    def test_bad_conversion_readback_fails_registration(self):
        responses = translated_responses()
        key = "show collection pon-onu gpon_onu-1/1/5:55 config"
        responses[key] = responses[key].replace("user-vlan 111 vlan 171", "user-vlan 111 vlan 111")
        session = FakeSession({**c600_precheck_responses(), **responses})
        result = OnuRegistrationService(session_type=session).register(make_connection(), [self.request])
        self.assertFalse(result.ok)
        self.assertIn("service-port 2", result.message)
        self.assertNotIn("write", session.commands)

    def test_unsupported_multicast_command_stops_before_verification_or_write(self):
        session = FakeSession({**c600_precheck_responses(), **translated_responses()}, fail_once="mvlan-translate 600 to 113")
        result = OnuRegistrationService(session_type=session).register(make_connection(), [self.request])
        self.assertFalse(result.ok)
        self.assertNotIn("write", session.commands)
        self.assertNotIn(self.driver.build_verify_commands(self.request)[0], session.commands)
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()

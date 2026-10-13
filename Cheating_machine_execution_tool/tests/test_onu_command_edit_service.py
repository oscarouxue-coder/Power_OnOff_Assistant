from dataclasses import FrozenInstanceError, replace
import unittest

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.models.onu_registration_models import (
    DiscoveredOnu,
    OnuCommandPlan,
    OnuProvisionRequest,
    OnuServiceMapping,
)
from src.services.onu_command_edit_service import OnuCommandEditError, OnuCommandEditService


def c300_request():
    return OnuProvisionRequest(
        family="C300",
        onu=DiscoveredOnu(
            family="C300", pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:3", suggested_onu_id=3,
            serial_number="GPONA62D6F78",
        ),
        onu_type="SD-41",
    )


def c600_request():
    return OnuProvisionRequest(
        family="C600",
        onu=DiscoveredOnu(
            family="C600", pon_interface="gpon_olt-1/1/5",
            serial_number="ZTEG12345678",
        ),
        onu_id=55, onu_type="CXP-55", tcont_profile="WT-10G",
        services=(
            OnuServiceMapping(1, 170), OnuServiceMapping(2, 171),
            OnuServiceMapping(5, 335), OnuServiceMapping(6, 600),
            OnuServiceMapping(7, 50),
        ),
    )


def commands(request):
    driver = ZteC300OnuDriver() if request.family == "C300" else ZteC600OnuDriver()
    return driver.build_provision_commands(request)


class OnuCommandEditServiceTests(unittest.TestCase):
    def setUp(self):
        self.editor = OnuCommandEditService()

    def prepare(self, base, updated):
        return self.editor.prepare(base, "\n".join(commands(updated)))

    def assert_rejected(self, base, text, reason=None):
        with self.assertRaises(OnuCommandEditError) as context:
            self.editor.prepare(base, text)
        error = context.exception
        self.assertGreater(error.line_number, 0)
        self.assertIn(base.onu.serial_number, str(error))
        self.assertIn(base.onu.pon_interface, str(error))
        if reason:
            self.assertIn(reason, str(error))
        return error

    def test_default_commands_round_trip_for_both_families(self):
        for base in (c300_request(), c600_request()):
            with self.subTest(family=base.family):
                plan = self.editor.build_default(base)
                self.assertEqual(plan.commands, tuple(commands(base)))
                self.assertEqual(tuple(commands(plan.request)), plan.commands)
                self.assertFalse(plan.edited)
                self.assertIs(plan.request.onu, base.onu)
                self.assertEqual(plan.request.onu_id, base.onu_id)
                self.assertIsInstance(plan.request.services, tuple)
                self.assertEqual(self.editor.prepare(base, "\n".join(plan.commands)), plan)

    def test_c300_edits_type_tcont_and_six_mappings(self):
        base = c300_request()
        services = tuple(OnuServiceMapping(index + 10, vlan) for index, vlan in enumerate((201, 47, 336, 600, 174, 175)))
        updated = replace(base, onu_type="SD-42", tcont_id=9, tcont_profile="2G", services=services)
        plan = self.prepare(base, updated)
        self.assertTrue(plan.edited)
        self.assertEqual(plan.request, updated)
        self.assertIn("gemport 10 tcont 9", plan.commands)
        self.assertIn("service Internet gemport 10 vlan 201", plan.commands)
        self.assertEqual(plan.request.onu_id, None)

    def test_c600_edits_all_supported_fields(self):
        base = c600_request()
        updated = replace(
            base, onu_type="NP7287XGS", real_speed="xgspon", sn_bind_both=False,
            tcont_id=9, tcont_profile="NEW-10G", gemport_id=8, vport_id=8,
            services=(OnuServiceMapping(10, 200), OnuServiceMapping(11, 600)),
        )
        plan = self.prepare(base, updated)
        self.assertEqual(plan.request, updated)
        self.assertTrue(plan.edited)
        self.assertIn("interface vport-1/1/5.55:8", plan.commands)
        self.assertNotIn("sn-bind enable both", plan.commands)

    def test_c600_complete_business_group_addition_and_removal(self):
        base = c600_request()
        for services in (
            base.services + (OnuServiceMapping(20, 180),),
            tuple(item for item in base.services if item.vlan != 335),
            tuple(item for item in base.services if item.vlan != 50),
        ):
            with self.subTest(services=services):
                updated = replace(base, services=services)
                plan = self.prepare(base, updated)
                self.assertEqual(plan.request.services, services)
                self.assertEqual(plan.commands, tuple(commands(updated)))

    def test_c600_only_fixed_business_preserves_idle_main_resources(self):
        base = replace(c600_request(), tcont_id=9, gemport_id=10, vport_id=10, tcont_profile="IDLE")
        updated = replace(base, services=(OnuServiceMapping(6, 600), OnuServiceMapping(5, 335)))
        plan = self.prepare(base, updated)
        self.assertEqual(plan.request, updated)
        self.assertNotIn("tcont 9 profile IDLE", plan.commands)

    def test_c600_remote_service_order_drives_resource_and_vport_order(self):
        base = c600_request()
        updated = replace(base, services=(base.services[3], base.services[0], base.services[2]))
        plan = self.prepare(base, updated)
        self.assertEqual(plan.request.services, updated.services)
        self.assertEqual(plan.commands, tuple(commands(updated)))

    def test_comments_empty_lines_and_spaces_preserve_original_command_text(self):
        base = c600_request()
        generated = commands(base)
        text = "# 本批命令\n\n" + "\n".join("  " + line.replace(" ", "  ") + "  " for line in generated)
        plan = self.editor.prepare(base, text)
        self.assertFalse(plan.edited)
        self.assertEqual(plan.commands, tuple(line.replace(" ", "  ") for line in generated))

    def test_error_uses_original_text_line_including_comments_and_blanks(self):
        base = c300_request()
        generated = commands(base)
        generated[6] = "tcont bad profile 1G"
        text = "# 注释\n\n" + "\n".join(generated)
        error = self.assert_rejected(base, text, "格式无效")
        self.assertEqual(error.line_number, 9)

    def test_c300_error_target_uses_interface_id_without_discovery_suggestion(self):
        base = c300_request()
        base = replace(base, onu=replace(base.onu, suggested_onu_id=None))
        error = self.assert_rejected(base, "", "不能为空")
        self.assertIn("ONU ID 3", error.target_name)

    def test_target_sn_or_id_change_is_rejected(self):
        for base in (c300_request(), c600_request()):
            text = "\n".join(commands(base))
            for changed in (
                text.replace(base.onu.serial_number, "ZTEG87654321"),
                text.replace("onu 3 type", "onu 4 type") if base.family == "C300" else text.replace("onu 55 type", "onu 56 type"),
            ):
                with self.subTest(family=base.family, text=changed):
                    self.assert_rejected(base, changed, "SN 和 ONU ID 固定")

    def test_target_pon_or_onu_interface_change_is_rejected(self):
        for base in (c300_request(), c600_request()):
            text = "\n".join(commands(base))
            changed = text.replace("1/2/1", "1/2/2") if base.family == "C300" else text.replace("1/1/5", "1/1/6")
            self.assert_rejected(base, changed, "上下文")

    def test_c300_service_names_and_gem_vport_links_are_fixed(self):
        base = c300_request()
        text = "\n".join(commands(base))
        for changed in (
            text.replace("service Internet gemport", "service DATA gemport"),
            text.replace("service-port 1 vport 1", "service-port 1 vport 2"),
            text.replace("gemport 1 tcont 1", "gemport 1 tcont 2"),
        ):
            self.assert_rejected(base, changed)

    def test_c300_requires_all_six_services_and_multicast_600(self):
        base = c300_request()
        text = "\n".join(commands(base))
        self.assert_rejected(base, text.replace("service Internet gemport 1 vlan 200\n", ""), "六项")
        self.assert_rejected(base, text.replace("600", "601"), "600")

    def test_c600_rejects_partial_business_group_addition_or_removal(self):
        base = c600_request()
        text = "\n".join(commands(base))
        for changed in (
            text.replace("mvlan 600", "service 20 gemport 1 vlan 180\nmvlan 600", 1),
            text.replace("service 5 gemport 2 vlan 335\n", ""),
            text.replace("tcont 2 profile DBA_FONE\n", ""),
            text.replace("service-port 5 user-vlan 335 vlan 335\n", ""),
        ):
            self.assert_rejected(base, changed)

    def test_c600_rejects_fixed_layer_or_multicast_edits(self):
        base = c600_request()
        text = "\n".join(commands(base))
        for changed in (
            text.replace("DBA_FONE", "VOICE-NEW"),
            text.replace("service 5 gemport 2", "service 5 gemport 8"),
            text.replace("600", "601"),
            text.replace("igmp version v2", "igmp version v3"),
            text.replace("receive-port vport-1/1/5.55:3", "receive-port vport-1/1/5.55:1"),
        ):
            self.assert_rejected(base, changed)

    def test_c600_rejects_main_resource_conflict_and_unequal_vport(self):
        base = c600_request()
        text = "\n".join(commands(base))
        conflict = text.replace("tcont 1 profile WT-10G", "tcont 3 profile WT-10G").replace("gemport 1 tcont 1", "gemport 1 tcont 3")
        self.assert_rejected(base, conflict)
        changed = text.replace("interface vport-1/1/5.55:1", "interface vport-1/1/5.55:8")
        self.assert_rejected(base, changed, "上下文")

    def test_unknown_duplicate_reordered_missing_and_wrong_context_commands_rejected(self):
        for base in (c300_request(), c600_request()):
            generated = commands(base)
            swapped = list(generated)
            swapped[0], swapped[1] = swapped[1], swapped[0]
            for rows in (
                generated + ["show version"],
                generated[:2] + [generated[1]] + generated[2:],
                swapped,
                generated[:-1],
                [row for row in generated if row != "configure terminal"],
                generated[:5] + ["exit"] + generated[5:],
            ):
                with self.subTest(family=base.family, rows=rows):
                    self.assert_rejected(base, "\n".join(rows))

    def test_write_delete_and_reboot_rejected_at_original_line(self):
        base = c600_request()
        text = "\n".join(commands(base))
        for dangerous in ("write", "write memory", "no onu 55", "reboot", "reload", "reset", "delete file"):
            error = self.assert_rejected(base, "# comment\n" + dangerous + "\n" + text, "保存、删除或重启")
            self.assertEqual(error.line_number, 2)

    def test_control_characters_in_commands_and_comments_are_rejected(self):
        base = c300_request()
        text = "\n".join(commands(base))
        for char in ("\x00", "\x1b", "\x7f", "\x85", "\t", "\x0b", "\x0c", "\u200b", "\u2028", "\u2029", "\ufeff"):
            error = self.assert_rejected(base, "# comment" + char + "\n" + text, "控制字符")
            self.assertEqual(error.line_number, 1)

    def test_non_ascii_command_whitespace_rejected_but_comment_and_blank_lines_allowed(self):
        base = c300_request()
        text = "\n".join(commands(base))
        for whitespace in ("\u00a0", "\u3000"):
            for changed in (
                text.replace("configure terminal", f"configure{whitespace}terminal"),
                whitespace + text,
            ):
                error = self.assert_rejected(base, changed, "ASCII 空格")
                self.assertEqual(error.line_number, 1)
            plan = self.editor.prepare(base, whitespace + "\n# comment" + whitespace + "\n" + text)
            self.assertEqual(plan.commands, tuple(commands(base)))

    def test_empty_commands_rejected(self):
        for text in ("", " \n# comment\n", "\r\n"):
            self.assert_rejected(c600_request(), text, "不能为空")

    def test_c300_template_injection_is_rejected(self):
        base = c300_request()
        text = "\n".join(commands(base))
        for changed in (
            text.replace("type SD-41", "type SD-41;reboot"),
            text.replace("profile 1G", "profile 1G;reboot"),
        ):
            self.assert_rejected(base, changed, "名称")

    def test_invalid_mapping_and_duplicate_mapping_rejected(self):
        for base in (c300_request(), c600_request()):
            text = "\n".join(commands(base))
            ordinary_vlan = "200" if base.family == "C300" else "170"
            for changed in (text.replace(ordinary_vlan, "4095"), text.replace(ordinary_vlan, "600")):
                self.assert_rejected(base, changed)

    def test_explicit_auto_speed_and_unknown_sn_binding_rejected(self):
        base = c600_request()
        text = "\n".join(commands(base))
        self.assert_rejected(base, text.replace("tcont 1 profile", "real-speed auto\ntcont 1 profile"), "auto")
        self.assert_rejected(base, text.replace("sn-bind enable both", "sn-bind enable sn"), "双绑定")

    def test_command_plan_is_frozen_and_copies_mutable_inputs(self):
        base = c600_request()
        services = list(base.services)
        rows = commands(base)
        plan = OnuCommandPlan(replace(base, services=services), rows)
        services.clear()
        rows.clear()
        self.assertEqual(plan.request.services, base.services)
        self.assertGreater(len(plan.commands), 0)
        with self.assertRaises(FrozenInstanceError):
            plan.edited = True

    def test_batch_targets_do_not_share_edit_state(self):
        first = c600_request()
        second = replace(first, onu=replace(first.onu, serial_number="ZTEG87654321"), onu_id=56)
        first_plan = self.prepare(first, replace(first, onu_type="FIRST-NEW"))
        second_plan = self.editor.build_default(second)
        self.assertTrue(first_plan.edited)
        self.assertFalse(second_plan.edited)
        self.assertEqual(second_plan.request.onu_type, "CXP-55")
        self.assertEqual(second_plan.request.onu_id, 56)
        self.assertEqual(first_plan.request.onu_id, 55)


if __name__ == "__main__":
    unittest.main()

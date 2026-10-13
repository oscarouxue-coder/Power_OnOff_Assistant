from dataclasses import FrozenInstanceError, replace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.models.onu_registration_models import (
    DiscoveredOnu,
    OnuCommandPlan,
    OnuProvisionRequest,
    OnuServiceMapping,
)
from src.services.onu_command_edit_service import OnuCommandEditService
from src.ui.onu_command_editor import OnuCommandEditor, command_plan_summary


class FakeVariable:
    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class FakeCombo(FakeWidget):
    def __init__(self):
        super().__init__()
        self.index = -1

    def current(self, index=None):
        if index is not None:
            self.index = index
        return self.index


class FakeText(FakeWidget):
    def __init__(self):
        super().__init__()
        self.value = ""
        self.modified = False
        self.selection = None
        self.visible_index = None
        self.focused = False

    def get(self, _first, _last):
        return self.value

    def delete(self, _first, _last):
        self.value = ""
        self.modified = True

    def insert(self, _index, value):
        self.value = value
        self.modified = True

    def edit_reset(self):
        pass

    def edit_modified(self, value=None):
        if value is not None:
            self.modified = value
        return self.modified

    def tag_remove(self, _tag, _first, _last):
        self.selection = None

    def tag_add(self, tag, first, last):
        self.selection = (tag, first, last)

    def see(self, index):
        self.visible_index = index

    def focus_set(self):
        self.focused = True


def request_for(family="C600", number=1):
    if family == "C300":
        return OnuProvisionRequest(
            family=family,
            onu=DiscoveredOnu(
                family=family, pon_interface="gpon-olt_1/2/1",
                serial_number=f"GPON{number:08X}",
                onu_interface=f"gpon-onu_1/2/1:{number}", suggested_onu_id=number,
            ),
            onu_id=number, onu_type="SD-41", tcont_profile="1G",
            services=tuple(
                OnuServiceMapping(index, vlan)
                for index, vlan in enumerate((200, 46, 335, 600, 171, 172), 1)
            ),
        )
    return OnuProvisionRequest(
        family=family,
        onu=DiscoveredOnu(
            family=family, pon_interface="gpon_olt-1/1/5",
            serial_number=f"ZTEG{number:08X}",
        ),
        onu_id=number, onu_type="CXP-55", tcont_profile="WT-10G",
        services=(OnuServiceMapping(1, 171), OnuServiceMapping(6, 600)),
    )


def command_text(request):
    driver = ZteC300OnuDriver() if request.family == "C300" else ZteC600OnuDriver()
    return "\n".join(driver.build_provision_commands(request))


def fake_editor():
    editor = OnuCommandEditor.__new__(OnuCommandEditor)
    editor.parent = object()
    editor.on_ready_changed = Mock()
    editor.log = Mock()
    editor.service = OnuCommandEditService()
    editor.requests = ()
    editor.plans = None
    editor.busy = False
    editor.write_note_var = FakeVariable()
    editor.text = FakeText()
    return editor


class OnuCommandEditorTests(unittest.TestCase):
    def setUp(self):
        self.editor = fake_editor()
        self.requests = (request_for(number=1), request_for(number=2))
        self.editor.load_requests(self.requests, write_note="write：关闭，验证后另行保存")
        self.editor.on_ready_changed.reset_mock()

    def test_load_shows_target_identity_and_separates_write_from_commands(self):
        for request in self.requests:
            self.assertIn(request.onu.serial_number, self.editor.text.value)
            self.assertIn(request.onu.pon_interface, self.editor.text.value)
            self.assertIn(f"ONU ID {request.onu_id}", self.editor.text.value)
            self.assertIn(command_text(request), self.editor.text.value)
        self.assertNotIn("write", self.editor.text.value.splitlines())
        self.assertIn("write：关闭", self.editor.write_note_var.get())
        self.assertEqual(len(self.editor.capture_plans()), 2)

    def test_unedited_load_preserves_generated_commands_for_both_families(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                request = request_for(family)
                self.editor.load_requests((request,))
                plan, = self.editor.capture_plans()
                self.assertIsInstance(plan, OnuCommandPlan)
                self.assertEqual(plan.commands, tuple(command_text(request).splitlines()))
                self.assertEqual(plan.request, request)
                self.assertFalse(plan.edited)

    def test_all_targets_are_visible_in_order_without_selector(self):
        plans = self.editor.capture_plans()
        self.assertLess(
            self.editor.text.value.index(self.requests[0].onu.serial_number),
            self.editor.text.value.index(self.requests[1].onu.serial_number),
        )
        for request in self.requests:
            self.assertIn(command_text(request), self.editor.text.value)
        for plan in plans:
            self.assertFalse(any(command.startswith("# ") for command in plan.commands))
        self.assertIs(self.editor.capture_plans(), plans)
        self.assertEqual(self.editor.text.options["state"], "disabled")
        self.assertFalse(hasattr(self.editor, "target_combo"))
        self.assertFalse(hasattr(self.editor, "status_var"))

    def test_capture_rejects_unexpected_display_change_without_executing_text(self):
        plans = self.editor.capture_plans()
        self.editor.text.value += "\nwrite"
        with self.assertRaisesRegex(ValueError, "快照不一致"):
            self.editor.capture_plans()
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertIsNone(self.editor.plans)
        self.assertNotIn("write", plans[0].commands)
        self.assertIn("未连接 OLT", self.editor.log.call_args.args[0])

    def test_generated_snapshot_is_immutable(self):
        snapshot = self.editor.capture_plans()
        with self.assertRaises(FrozenInstanceError):
            snapshot[0].request.onu_type = "MUTATED"
        with self.assertRaises(TypeError):
            snapshot[0].commands[0] = "write"
        self.editor.clear()
        self.assertEqual(snapshot[0].commands, tuple(command_text(self.requests[0]).splitlines()))

    def test_clear_invalidates_plans_and_controls(self):
        self.editor.clear()
        self.assertEqual(self.editor.requests, ())
        self.assertIsNone(self.editor.plans)
        self.assertEqual(self.editor.text.value, "")
        self.assertEqual(self.editor.write_note_var.get(), "")
        self.editor.on_ready_changed.assert_called_with(False)
        with self.assertRaises(ValueError):
            self.editor.capture_plans()

    def test_text_stays_readonly_during_execution_and_after_unlock(self):
        plans = self.editor.capture_plans()
        preview = self.editor.text.value
        self.editor.set_busy(True)
        self.assertEqual(self.editor.text.options["state"], "disabled")
        self.editor.set_busy(False)
        self.assertEqual(self.editor.text.options["state"], "disabled")
        self.assertEqual(self.editor.text.value, preview)
        self.assertIs(self.editor.capture_plans(), plans)

    def test_reloading_after_invalidation_discards_old_batch(self):
        self.editor.clear()
        replacement = request_for(number=9)
        self.editor.load_requests((replacement,), write_note="新批次不保存")
        plan, = self.editor.capture_plans()
        self.assertEqual(plan.request, replacement)
        self.assertFalse(plan.edited)
        self.assertNotIn(self.requests[0].onu.serial_number, self.editor.text.value)

    def test_empty_batch_disables_preview(self):
        self.editor.load_requests(())
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertEqual(self.editor.text.options["state"], "disabled")
        with self.assertRaises(ValueError):
            self.editor.capture_plans()

    def test_summary_displays_both_vlan_sides(self):
        updated = replace(self.requests[0], services=(OnuServiceMapping(2, 111, 171), OnuServiceMapping(6, 112, 600)))
        self.editor.load_requests((updated,))
        summary = command_plan_summary(self.editor.capture_plans()[0])
        for expected in ("ONU VLAN111 ↔ 网络 VLAN171", "ONU VLAN112 ↔ 网络 VLAN600", "生成命令", "ONU ID 1"):
            self.assertIn(expected, summary)
        self.assertNotIn("已编辑", summary)


class OnuCommandEditorTkTests(unittest.TestCase):
    def test_real_tk_preview_is_always_readonly_and_has_no_edit_actions(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        try:
            ready = Mock()
            editor = OnuCommandEditor(root, on_ready_changed=ready, log=Mock())
            editor.frame.pack(fill="both", expand=True)
            request = request_for()
            editor.load_requests((request,), write_note="write：独立保存，默认关闭")
            root.update_idletasks()
            expected = command_text(request)
            self.assertEqual(editor.text.get("1.0", "end-1c"), expected)
            self.assertEqual(str(editor.text.cget("state")), "disabled")
            editor.text.delete("1.0", "end")
            editor.text.insert("end", "write")
            self.assertEqual(editor.text.get("1.0", "end-1c"), expected)
            # disabled Text 仍可选中复制，且没有编辑/校验/恢复按钮。
            editor.text.tag_add("sel", "1.0", "1.end")
            self.assertTrue(editor.text.tag_ranges("sel"))
            self.assertFalse(hasattr(editor, "validate_button"))
            self.assertFalse(hasattr(editor, "restore_button"))
            self.assertFalse(hasattr(editor, "validate"))
            self.assertFalse(hasattr(editor, "restore"))
            self.assertFalse(hasattr(editor, "target_combo"))
            self.assertFalse(hasattr(editor, "status_var"))
            self.assertFalse(any(isinstance(child, tk.ttk.Combobox) for child in editor.frame.winfo_children()))
            ready.assert_called_with(True)
            editor.set_busy(True)
            editor.set_busy(False)
            self.assertEqual(str(editor.text.cget("state")), "disabled")
            self.assertIsNotNone(editor.capture_plans())
            editor.load_requests((request, request_for(number=2)))
            for target in editor.requests:
                self.assertIn(command_text(target), editor.text.get("1.0", "end-1c"))
            self.assertEqual(len(editor.capture_plans()), 2)
            editor.clear()
            self.assertEqual(editor.text.get("1.0", "end-1c"), "")
            ready.assert_called_with(False)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()

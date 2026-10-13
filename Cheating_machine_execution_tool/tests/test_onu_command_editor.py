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
    editor.originals = ()
    editor.drafts = []
    editor.plans = None
    editor.validated_texts = ()
    editor.current_index = 0
    editor.busy = False
    editor.updating = False
    editor.target_var = FakeVariable()
    editor.status_var = FakeVariable()
    editor.write_note_var = FakeVariable()
    editor.target_combo = FakeCombo()
    editor.text = FakeText()
    editor.validate_button = FakeWidget()
    editor.restore_button = FakeWidget()
    return editor


class OnuCommandEditorTests(unittest.TestCase):
    def setUp(self):
        self.editor = fake_editor()
        self.requests = (request_for(number=1), request_for(number=2))
        self.editor.load_requests(self.requests, write_note="write：关闭，验证后另行保存")
        self.editor.on_ready_changed.reset_mock()
        self.editor.log.reset_mock()

    def replace_text(self, value, *, dispatch=True):
        self.editor.text.value = value
        self.editor.text.modified = True
        if dispatch:
            self.editor._on_modified()

    def switch(self, index):
        self.editor.target_combo.current(index)
        self.editor._switch_target()

    def test_load_shows_target_identity_and_separates_write_from_commands(self):
        labels = self.editor.target_combo.options["values"]
        for request, label in zip(self.requests, labels):
            self.assertIn(request.onu.serial_number, label)
            self.assertIn(request.onu.pon_interface, label)
            self.assertIn(f"ONU ID {request.onu_id}", label)
        self.assertEqual(self.editor.text.value, command_text(self.requests[0]))
        self.assertNotIn("write", self.editor.text.value.splitlines())
        self.assertIn("write：关闭", self.editor.write_note_var.get())
        self.assertIn("校验通过", self.editor.status_var.get())
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

    def test_modified_draft_disables_start_and_reports_pending_without_network(self):
        self.replace_text(command_text(replace(self.requests[0], onu_type="CUSTOM-ONU")))
        self.assertIsNone(self.editor.plans)
        self.assertIn("待校验", self.editor.status_var.get())
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertIn("尚未连接 OLT", self.editor.log.call_args.args[0])

    def test_switching_targets_preserves_separate_edits(self):
        first = command_text(replace(self.requests[0], onu_type="FIRST-TYPE"))
        second = command_text(replace(self.requests[1], onu_type="SECOND-TYPE"))
        self.replace_text(first)
        self.switch(1)
        self.replace_text(second)
        self.switch(0)
        self.assertEqual(self.editor.text.value, first)
        self.assertEqual(self.editor.drafts, [first, second])
        self.switch(1)
        self.assertEqual(self.editor.text.value, second)
        self.assertTrue(self.editor.validate())
        self.assertEqual([plan.request.onu_type for plan in self.editor.capture_plans()], ["FIRST-TYPE", "SECOND-TYPE"])

    def test_switch_detects_changes_before_modified_event_is_dispatched(self):
        first = command_text(replace(self.requests[0], onu_type="UNPROCESSED"))
        self.replace_text(first, dispatch=False)
        self.switch(1)
        self.assertEqual(self.editor.drafts[0], first)
        self.assertIsNone(self.editor.plans)
        self.assertIn("待校验", self.editor.status_var.get())
        self.editor.on_ready_changed.assert_called_with(False)

    def test_capture_reads_current_text_before_modified_event_is_dispatched(self):
        cached = self.editor.capture_plans()
        changed = command_text(replace(self.requests[0], onu_type="UNPROCESSED"))
        self.replace_text(changed, dispatch=False)
        with self.assertRaisesRegex(ValueError, "尚未校验"):
            self.editor.capture_plans()
        self.assertEqual(self.editor.drafts[0], changed)
        self.assertIsNone(self.editor.plans)
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertEqual(cached[0].request.onu_type, self.requests[0].onu_type)

    def test_validation_selects_invalid_target_and_original_text_line(self):
        self.switch(1)
        invalid = "# original line numbers\n\n" + self.editor.originals[1] + "\nwrite"
        self.replace_text(invalid)
        self.switch(0)
        self.assertFalse(self.editor.validate())
        line = len(invalid.splitlines())
        self.assertEqual(self.editor.current_index, 1)
        self.assertEqual(self.editor.target_combo.current(), 1)
        self.assertEqual(self.editor.text.value, invalid)
        self.assertEqual(self.editor.text.selection, ("sel", f"{line}.0", f"{line}.end"))
        self.assertEqual(self.editor.text.visible_index, f"{line}.0")
        self.assertTrue(self.editor.text.focused)
        self.assertIn(self.requests[1].onu.serial_number, self.editor.status_var.get())
        self.assertIn(f"第 {line} 行", self.editor.status_var.get())
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertIn("未连接 OLT", self.editor.log.call_args.args[0])

    def test_validation_returns_immutable_actual_plan_and_new_expectations(self):
        updated = replace(
            self.requests[0], onu_type="UPDATED-TYPE", tcont_profile="NEW-10G",
            services=(OnuServiceMapping(10, 180), OnuServiceMapping(11, 600)),
        )
        edited = command_text(updated)
        self.replace_text("# preserved locally\n\n" + edited)
        self.assertTrue(self.editor.validate())
        snapshot = self.editor.capture_plans()
        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot[0].request, updated)
        self.assertEqual(snapshot[0].commands, tuple(edited.splitlines()))
        self.assertTrue(snapshot[0].edited)
        self.assertFalse(snapshot[1].edited)
        self.editor.on_ready_changed.assert_called_with(True)
        with self.assertRaises(FrozenInstanceError):
            snapshot[0].edited = False
        with self.assertRaises(FrozenInstanceError):
            snapshot[0].request.onu_type = "MUTATED"
        with self.assertRaises(TypeError):
            snapshot[0].commands[0] = "write"
        self.replace_text(self.editor.originals[0])
        self.assertEqual(snapshot[0].commands, tuple(edited.splitlines()))
        self.assertEqual(snapshot[0].request.services, updated.services)
        self.assertIsNone(self.editor.plans)

    def test_restore_cancel_preserves_current_edit(self):
        changed = command_text(replace(self.requests[0], onu_type="KEEP-ME"))
        self.replace_text(changed)
        with patch("src.ui.onu_command_editor.messagebox.askyesno", return_value=False) as confirm:
            self.editor.restore()
        confirm.assert_called_once()
        self.assertIs(confirm.call_args.kwargs["parent"], self.editor.parent)
        self.assertEqual(self.editor.drafts[0], changed)
        self.assertEqual(self.editor.text.value, changed)
        self.assertIsNone(self.editor.plans)
        self.assertIn("取消", self.editor.log.call_args.args[0])

    def test_restore_confirm_changes_only_current_target_and_revalidates(self):
        self.replace_text(command_text(replace(self.requests[0], onu_type="FIRST-EDIT")))
        self.switch(1)
        second = command_text(replace(self.requests[1], onu_type="SECOND-EDIT"))
        self.replace_text(second)
        self.switch(0)
        with patch("src.ui.onu_command_editor.messagebox.askyesno", return_value=True) as confirm:
            self.editor.restore()
        confirm.assert_called_once()
        self.assertEqual(self.editor.drafts, [self.editor.originals[0], second])
        plans = self.editor.capture_plans()
        self.assertFalse(plans[0].edited)
        self.assertTrue(plans[1].edited)
        self.assertEqual(plans[1].request.onu_type, "SECOND-EDIT")
        self.editor.on_ready_changed.assert_called_with(True)

    def test_restore_unchanged_target_does_not_prompt(self):
        with patch("src.ui.onu_command_editor.messagebox.askyesno") as confirm:
            self.editor.restore()
        confirm.assert_not_called()
        self.assertFalse(self.editor.capture_plans()[0].edited)

    def test_clear_invalidates_all_drafts_plans_and_controls(self):
        self.replace_text(command_text(replace(self.requests[0], onu_type="OLD-EDIT")))
        self.editor.clear()
        self.assertEqual(self.editor.requests, ())
        self.assertEqual(self.editor.originals, ())
        self.assertEqual(self.editor.drafts, [])
        self.assertEqual(self.editor.validated_texts, ())
        self.assertIsNone(self.editor.plans)
        self.assertEqual(self.editor.text.value, "")
        self.assertEqual(self.editor.target_combo.options["values"], ())
        self.assertEqual(self.editor.target_var.get(), "")
        self.assertEqual(self.editor.write_note_var.get(), "")
        self.assertIn("重新生成", self.editor.status_var.get())
        for widget in (self.editor.target_combo, self.editor.text, self.editor.validate_button, self.editor.restore_button):
            self.assertEqual(widget.options["state"], "disabled")
        self.editor.on_ready_changed.assert_called_with(False)
        with self.assertRaises(ValueError):
            self.editor.capture_plans()

    def test_busy_blocks_validation_restore_and_switch_and_disables_controls(self):
        self.replace_text(command_text(replace(self.requests[0], onu_type="BUSY-EDIT")))
        self.editor.set_busy(True)
        drafts = list(self.editor.drafts)
        with patch.object(self.editor.service, "prepare") as prepare, patch(
            "src.ui.onu_command_editor.messagebox.askyesno"
        ) as confirm:
            self.assertFalse(self.editor.validate())
            self.editor.restore()
            self.switch(1)
        prepare.assert_not_called()
        confirm.assert_not_called()
        self.assertEqual(self.editor.current_index, 0)
        self.assertEqual(self.editor.drafts, drafts)
        for widget in (self.editor.target_combo, self.editor.text, self.editor.validate_button, self.editor.restore_button):
            self.assertEqual(widget.options["state"], "disabled")
        self.editor.set_busy(False)
        self.assertEqual(self.editor.target_combo.options["state"], "readonly")
        self.assertEqual(self.editor.text.options["state"], "normal")
        self.assertTrue(self.editor.validate())

    def test_reloading_after_invalidation_discards_old_batch_edits(self):
        self.replace_text(command_text(replace(self.requests[0], onu_type="STALE")))
        self.editor.clear()
        replacement = request_for(number=9)
        self.editor.load_requests((replacement,), write_note="新批次不保存")
        plan, = self.editor.capture_plans()
        self.assertEqual(plan.request, replacement)
        self.assertFalse(plan.edited)
        self.assertNotIn("STALE", self.editor.text.value)
        self.assertEqual(self.editor.write_note_var.get(), "新批次不保存")

    def test_empty_batch_disables_editor_and_no_operations_prompt(self):
        self.editor.load_requests(())
        self.assertFalse(self.editor.validate())
        with patch("src.ui.onu_command_editor.messagebox.askyesno") as confirm:
            self.editor.restore()
        confirm.assert_not_called()
        self.editor.on_ready_changed.assert_called_with(False)
        self.assertEqual(self.editor.text.options["state"], "disabled")
        self.assertEqual(self.editor.target_combo.options["state"], "disabled")

    def test_summary_uses_validated_new_business_parameters(self):
        updated = replace(
            self.requests[0], onu_type="NEW-TYPE", tcont_id=9, tcont_profile="NEW-DBA",
            services=(OnuServiceMapping(10, 180), OnuServiceMapping(11, 600)),
        )
        plan = self.editor.service.prepare(self.requests[0], command_text(updated))
        summary = command_plan_summary(plan)
        for expected in (updated.onu.serial_number, updated.onu.pon_interface, "ONU ID 1", "已编辑", "NEW-TYPE", "9/NEW-DBA", "10/180", "11/600"):
            self.assertIn(expected, summary)
        self.assertNotIn("1/171", summary)


class OnuCommandEditorTkTests(unittest.TestCase):
    def test_real_tk_component_has_separate_write_note_and_busy_states(self):
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
            self.assertEqual(editor.text.get("1.0", "end-1c"), command_text(request))
            self.assertNotIn("write", editor.text.get("1.0", "end-1c").splitlines())
            self.assertEqual(editor.write_note_var.get(), "write：独立保存，默认关闭")
            self.assertEqual(str(editor.target_combo.cget("state")), "readonly")
            self.assertEqual(str(editor.text.cget("state")), "normal")
            ready.assert_called_with(True)
            editor.set_busy(True)
            for widget in (editor.target_combo, editor.text, editor.validate_button, editor.restore_button):
                self.assertEqual(str(widget.cget("state")), "disabled")
            editor.set_busy(False)
            editor.clear()
            self.assertEqual(editor.text.get("1.0", "end-1c"), "")
            ready.assert_called_with(False)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()

"""Confirm the main-window bridge uses only the approved command snapshot."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.models.onu_registration_models import (
    DiscoveredOnu, OltConnection, OnuProvisionRequest, OnuServiceMapping,
)
from src.services.onu_command_edit_service import OnuCommandEditService


def make_request(onu_id=3, serial="SDMC176D42AA"):
    return OnuProvisionRequest(
        family="C600", onu=DiscoveredOnu("C600", "gpon_olt-1/1/5", serial),
        onu_id=onu_id, onu_type="NP7287XGS", tcont_profile="WT-10G",
        services=(OnuServiceMapping(1, 170), OnuServiceMapping(6, 600)),
    )


class OnuCommandEditorAppTests(unittest.TestCase):
    def context(self):
        requests = [make_request(), make_request(4, "SDMC126C7707")]
        service = OnuCommandEditService()
        plans = tuple(service.build_default(request) for request in requests)
        return SimpleNamespace(
            onu_register_running=False, onu_save_olt_running=False, onu_preview_ready=True,
            onu_family_var=Mock(get=Mock(return_value="C600")),
            onu_c600_write_after_success_var=Mock(get=Mock(return_value=False)),
            onu_registration_window=Mock(),
            onu_command_editor=Mock(capture_plans=Mock(return_value=plans), requests=tuple(requests)),
            _current_onu_connection=Mock(return_value=OltConnection(
                "192.0.2.1", "192.0.2.2", "operator", "test-password",
            )),
            _build_onu_provision_requests=Mock(return_value=requests),
            _set_onu_query_status=Mock(), _set_onu_registration_action_buttons_state=Mock(),
            _onu_register_selected_worker=Mock(), _log=Mock(),
        )

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno")
    def test_confirmation_and_worker_share_edited_snapshot_even_if_editor_changes(self, confirm, thread):
        context = self.context()
        base = context._build_onu_provision_requests.return_value[0]
        updated = replace(base, onu_type="CUSTOM", services=(OnuServiceMapping(1, 171), OnuServiceMapping(6, 600)))
        edited = OnuCommandEditService().prepare(base, "\n".join(ZteC600OnuDriver().build_provision_commands(updated)))
        plans = (edited, context.onu_command_editor.capture_plans.return_value[1])
        context.onu_command_editor.capture_plans.return_value = plans

        def approve(*_args, **_kwargs):
            context.onu_command_editor.capture_plans.return_value = ()
            return True

        confirm.side_effect = approve
        self.assertTrue(LineCheckAssistant._on_onu_register_selected_clicked(context))
        self.assertIs(thread.call_args.kwargs["args"][5], plans)
        message = confirm.call_args.args[1]
        self.assertIn("已编辑", message)
        self.assertIn("CUSTOM", message)
        self.assertIn("1/171", message)
        self.assertIn(f"共 {sum(len(plan.commands) for plan in plans)} 条", message)
        self.assertEqual(base.onu_type, "NP7287XGS")
        context._build_onu_provision_requests.assert_called_once()

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.messagebox.showwarning")
    def test_pending_edits_block_confirmation_and_worker(self, warning, confirm, thread):
        context = self.context()
        context.onu_preview_ready = False
        self.assertFalse(LineCheckAssistant._on_onu_register_selected_clicked(context))
        self.assertIn("校验编辑", warning.call_args.args[1])
        confirm.assert_not_called()
        thread.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.messagebox.showwarning")
    def test_capture_rejects_edit_before_modified_event_is_dispatched(self, warning, confirm, thread):
        context = self.context()
        context.onu_command_editor.capture_plans.side_effect = ValueError("编辑内容尚未校验")
        self.assertFalse(LineCheckAssistant._on_onu_register_selected_clicked(context))
        self.assertIn("尚未校验", warning.call_args.args[1])
        confirm.assert_not_called()
        thread.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno", return_value=False)
    def test_cancel_logs_skipped_and_does_not_start_worker(self, confirm, thread):
        context = self.context()
        self.assertFalse(LineCheckAssistant._on_onu_register_selected_clicked(context))
        self.assertFalse(context.onu_register_running)
        self.assertIn("跳过注册", context._log.call_args.args[0])
        thread.assert_not_called()

    @patch("line_check_assistant.app.OnuRegistrationService")
    def test_worker_passes_snapshot_without_reading_editor(self, factory):
        context = self.context()
        connection = context._current_onu_connection()
        requests = context._build_onu_provision_requests()
        plans = context.onu_command_editor.capture_plans()
        context.after = Mock()
        context.onu_cancel_event = Mock()
        del context.onu_command_editor
        LineCheckAssistant._onu_register_selected_worker(context, "C600", connection, requests, None, False, plans)
        factory.return_value.register.assert_called_once_with(
            connection, requests, c300_cleanup_candidate=None,
            cancel_event=context.onu_cancel_event, command_plans=plans,
        )
        self.assertEqual(context.after.call_args.args[0], 0)

    def test_invalidation_clears_editor_and_disables_start(self):
        context = self.context()
        context.onu_confirmation_summary_var = Mock()
        context.onu_register_button = Mock()
        LineCheckAssistant._invalidate_onu_preview(context)
        context.onu_command_editor.clear.assert_called_once()
        self.assertFalse(context.onu_preview_ready)
        context.onu_register_button.configure.assert_called_once_with(state="disabled")

    def test_query_completion_unlocks_editor_but_cannot_enable_unvalidated_start(self):
        context = self.context()
        context.onu_preview_ready = False
        context.onu_register_button = Mock()
        LineCheckAssistant._set_onu_registration_action_buttons_state(context, "normal")
        context.onu_command_editor.set_busy.assert_called_once_with(False)
        context.onu_register_button.configure.assert_called_once_with(state="disabled")

    def test_ready_callback_keeps_registration_disabled_during_write(self):
        context = self.context()
        context.onu_save_olt_running = True
        context.onu_register_button = Mock()
        LineCheckAssistant._on_onu_command_editor_ready_changed(context, True)
        context.onu_register_button.configure.assert_called_once_with(state="disabled")

    def test_c600_write_policy_is_separate_from_editable_commands(self):
        context = self.context()
        context.onu_c600_write_after_success_var.get.return_value = True
        context.onu_olt_ip_var = Mock(get=Mock(return_value="192.0.2.1"))
        context.onu_source_ip_var = Mock(get=Mock(return_value="192.0.2.2"))
        context.onu_confirmation_summary_var = Mock()
        context.onu_register_button = Mock()
        context.onu_notebook = Mock()
        context.onu_preview_tab = Mock()
        LineCheckAssistant._on_onu_preview_clicked(context)
        self.assertIn("独立会话执行 write", context.onu_command_editor.load_requests.call_args.kwargs["write_note"])
        self.assertNotIn("write", tuple(
            command for plan in context.onu_command_editor.capture_plans() for command in plan.commands
        ))

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.messagebox.showwarning")
    def test_delayed_business_text_event_cannot_reuse_old_preview(self, warning, confirm, thread):
        context = self.context()
        context._invalidate_onu_preview = Mock()
        original = context._build_onu_provision_requests.return_value[0]
        context._build_onu_provision_requests.return_value[0] = replace(original, onu_type="CHANGED")
        self.assertFalse(LineCheckAssistant._on_onu_register_selected_clicked(context))
        context._invalidate_onu_preview.assert_called_once()
        self.assertIn("重新生成", warning.call_args.args[1])
        confirm.assert_not_called()
        thread.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.messagebox.askyesno")
    def test_all_active_operations_block_preview_and_registration_entries(self, confirm, thread):
        for flag in (
            "onu_telnet_test_running", "onu_query_running", "onu_cleanup_query_running",
            "onu_register_running", "onu_save_olt_running", "onu_manage_query_running", "onu_manage_delete_running",
            "onu_template_query_running",
        ):
            with self.subTest(flag=flag):
                context = self.context()
                setattr(context, flag, True)
                LineCheckAssistant._on_onu_preview_clicked(context)
                self.assertFalse(LineCheckAssistant._on_onu_register_selected_clicked(context))
                context.onu_command_editor.load_requests.assert_not_called()
                context.onu_command_editor.capture_plans.assert_not_called()
        confirm.assert_not_called()
        thread.assert_not_called()

    def test_selection_change_during_execution_keeps_preview_buttons_disabled(self):
        context = self.context()
        context.onu_register_running = True
        context._selected_unregistered_onus = Mock(return_value=[make_request().onu])
        context.onu_next_config_button = Mock()
        context.onu_preview_button = Mock()
        context.onu_register_button = Mock()
        LineCheckAssistant._refresh_onu_selection_action_state(context)
        for button in (context.onu_next_config_button, context.onu_preview_button, context.onu_register_button):
            button.configure.assert_called_once_with(state="disabled")


if __name__ == "__main__":
    unittest.main()

from dataclasses import replace
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from src.models.onu_batch_delete import OnuBatchDeleteResult, OnuDeleteItemResult
from src.models.onu_registration_models import OltConnection, OnuOperationResult, RegisteredOnu


CONNECTION = OltConnection("192.0.2.1", "192.0.2.2", "test", "test")
TARGETS = tuple(RegisteredOnu("C600", "gpon_olt-1/1/1", f"gpon_onu-1/1/1:{index}", index,
                              "working", f"TEST{index:08X}", "TEST") for index in (1, 2))


def context():
    return SimpleNamespace(
        onu_manage_delete_running=False, onu_manage_query_running=False,
        onu_family_var=Mock(get=Mock(return_value="C600")), onu_registration_window=Mock(),
        onu_registered_candidates=TARGETS, onu_registered_query_context=("C600", CONNECTION, TARGETS[0].pon_interface),
        onu_registered_list=Mock(), onu_stop_button=Mock(), onu_manage_delete_button=Mock(),
        _selected_registered_onus=Mock(return_value=TARGETS), _current_onu_connection=Mock(return_value=CONNECTION),
        _current_onu_manage_pon_interface=Mock(return_value=TARGETS[0].pon_interface),
        _set_onu_query_status=Mock(), _set_onu_registration_action_buttons_state=Mock(),
        _onu_manage_delete_worker=Mock(), _clear_registered_candidates=Mock(), _log=Mock(),
    )


class BatchDeleteAppTests(unittest.TestCase):
    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.confirm_batch_delete", return_value=True)
    def test_snapshot_contains_only_checked_targets_and_shared_confirmation(self, confirm, thread):
        ctx = context()
        ctx._selected_registered_onus.return_value = (TARGETS[1],)
        LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
        confirm.assert_called_once_with(ctx.onu_registration_window, "C600", CONNECTION, TARGETS[0].pon_interface, (TARGETS[1],))
        self.assertEqual(thread.call_args.kwargs["args"], ("C600", CONNECTION, TARGETS[0].pon_interface, (TARGETS[1],)))
        self.assertTrue(ctx.onu_manage_delete_running)

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.confirm_batch_delete", return_value=False)
    def test_cancel_does_not_start_or_clear_selection(self, confirm, thread):
        ctx = context()
        LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
        thread.assert_not_called()
        ctx.onu_registered_list.show_results.assert_not_called()
        ctx._clear_registered_candidates.assert_not_called()
        self.assertFalse(ctx.onu_manage_delete_running)

    @patch("line_check_assistant.app.confirm_batch_delete")
    @patch("line_check_assistant.app.messagebox.showwarning")
    def test_empty_selection_does_not_confirm(self, warning, confirm):
        ctx = context()
        ctx._selected_registered_onus.return_value = ()
        LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
        confirm.assert_not_called()
        warning.assert_called_once()

    @patch("line_check_assistant.app.confirm_batch_delete")
    def test_changed_connection_or_scope_invalidates_old_candidates(self, confirm):
        for field in ("host", "source_ip", "username", "password", "pon", "family"):
            with self.subTest(field=field):
                ctx = context()
                if field == "pon":
                    ctx._current_onu_manage_pon_interface.return_value = "gpon_olt-1/1/2"
                elif field == "family":
                    ctx.onu_family_var.get.return_value = "C300"
                else:
                    ctx._current_onu_connection.return_value = replace(CONNECTION, **{field: "changed"})
                LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
                ctx._clear_registered_candidates.assert_called_once()
        confirm.assert_not_called()

    @patch("line_check_assistant.app.confirm_batch_delete")
    def test_registration_or_other_onu_operation_blocks_management(self, confirm):
        for flag in ("onu_register_running", "onu_telnet_test_running", "onu_template_query_running", "onu_save_olt_running"):
            ctx = context()
            setattr(ctx, flag, True)
            LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
            LineCheckAssistant._on_onu_manage_query_clicked(ctx)
            ctx._selected_registered_onus.assert_not_called()
        confirm.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.confirm_batch_delete")
    def test_target_change_during_confirmation_prevents_execution(self, confirm, thread):
        ctx = context()

        def changed(*_args):
            ctx.onu_registered_query_context = None
            return True

        confirm.side_effect = changed
        LineCheckAssistant._on_onu_manage_delete_clicked(ctx)
        thread.assert_not_called()

    def test_query_result_for_invalidated_context_is_discarded(self):
        ctx = context()
        ctx.onu_registered_query_context = None
        LineCheckAssistant._complete_onu_manage_query(ctx, "C600", CONNECTION.host,
                                                     OnuOperationResult(True, "OK", registered_onus=TARGETS))
        ctx.onu_registered_list.set_candidates.assert_not_called()
        ctx._clear_registered_candidates.assert_called_once()

    def test_finished_batch_keeps_failed_and_unexecuted_rows_and_disables_stop(self):
        ctx = context()
        result = OnuBatchDeleteResult(tuple(OnuDeleteItemResult(target, status, "test")
                                            for target, status in zip(TARGETS, ("failed", "not_executed"))))
        LineCheckAssistant._complete_onu_manage_delete(ctx, "C600", CONNECTION.host, result)
        ctx.onu_registered_list.show_results.assert_called_once_with(result)
        self.assertIsNone(ctx.onu_registered_query_context)
        ctx.onu_stop_button.configure.assert_called_once_with(state="disabled")
        ctx._clear_registered_candidates.assert_not_called()

    def test_connection_and_scope_variable_traces_clear_candidates(self):
        interpreter = tk.Tcl()
        ctx = context()
        names = (
            "onu_family_var", "onu_olt_ip_var", "onu_source_ip_var", "onu_username_var", "onu_password_var",
            "onu_manage_shelf_var", "onu_manage_slot_var", "onu_manage_pon_var",
            "onu_c600_shelf_var", "onu_c600_slot_var", "onu_c600_pon_var", "onu_c600_onu_id_var",
            "onu_c600_onu_type_var", "onu_c600_real_speed_var", "onu_c600_tcont_id_var", "onu_c600_tcont_profile_var",
            "onu_c600_gemport_id_var", "onu_c600_vport_id_var", "onu_c600_sn_bind_both_var",
            "onu_c300_shelf_var", "onu_c300_slot_var", "onu_c300_pon_var", "onu_c300_onu_id_var",
            "onu_c300_onu_type_var", "onu_c300_tcont_id_var", "onu_c300_tcont_profile_var", "onu_c300_allow_offline_cleanup_var",
        )
        for name in names:
            setattr(ctx, name, tk.StringVar(interpreter))
        ctx._on_onu_registration_input_changed = Mock()
        LineCheckAssistant._bind_onu_registration_autosave(ctx)
        for name in names[:8]:
            ctx._clear_registered_candidates.reset_mock()
            getattr(ctx, name).set("new value")
            ctx._clear_registered_candidates.assert_called_once()
        for name in names[8:]:
            ctx._clear_registered_candidates.reset_mock()
            getattr(ctx, name).set("new value")
            ctx._clear_registered_candidates.assert_not_called()

    @patch("line_check_assistant.app.OnuBatchDeleteService")
    def test_worker_delivers_final_batch_to_tk_main_thread(self, service_type):
        ctx = context()
        ctx.onu_cancel_event = threading.Event()
        ctx.after = Mock()
        ctx._complete_onu_manage_delete = Mock()
        LineCheckAssistant._onu_manage_delete_worker(ctx, "C600", CONNECTION, TARGETS[0].pon_interface, TARGETS)
        service_type.return_value.delete.assert_called_once_with("C600", CONNECTION, TARGETS[0].pon_interface, TARGETS, ctx.onu_cancel_event)
        ctx._complete_onu_manage_delete.assert_not_called()
        ctx.after.call_args.args[1]()
        ctx._complete_onu_manage_delete.assert_called_once_with("C600", CONNECTION.host, service_type.return_value.delete.return_value)

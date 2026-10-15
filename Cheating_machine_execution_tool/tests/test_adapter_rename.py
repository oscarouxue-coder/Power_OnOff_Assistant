"""重命名回归全部模拟系统操作，绝不修改测试电脑的网卡。"""
from __future__ import annotations

from dataclasses import asdict
import gc
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from tkinter import Tk
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import TelnetSettings
from src.core.network_adapter import read_adapter_identities, rename_adapter
from src.models.network_adapter import AdapterIdentity, AdapterRenameResult
from src.services.adapter_rename_service import (
    ADAPTER_NAME_HINT, AdapterRenameService, adapter_has_numeric_suffix, adapter_rename_is_busy,
    rename_unavailable_reason, synchronize_channel_adapter_names, validate_adapter_name,
)
from src.ui.adapter_rename_dialog import AdapterRenameDialog, offer_adapter_rename


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


OLD = AdapterIdentity("以太网", "guid-one", "Up")
NEW = AdapterIdentity("以太网101", "guid-one", "Up")


class AdapterNameTests(unittest.TestCase):
    def test_numeric_suffix_ignores_display_status(self):
        for name in ("VLAN101", "以太网101 [Up]", " Ethernet2 [Disconnected] "):
            with self.subTest(name=name):
                self.assertTrue(adapter_has_numeric_suffix(name))

    def test_missing_numeric_suffix(self):
        for name in ("以太网", "Ethernet", "网卡101abc", "", "以太网 [Up]"):
            with self.subTest(name=name):
                self.assertFalse(adapter_has_numeric_suffix(name))

    def test_valid_names_trim_whitespace(self):
        for name in ("VLAN2", "以太网101", "Ethernet 254", "网卡002"):
            with self.subTest(name=name):
                self.assertEqual(validate_adapter_name(f" {name} "), name)

    def test_invalid_names_are_rejected(self):
        for name in ("", "  ", "VLAN0", "VLAN1", "网卡001", "VLAN255", "VLAN300", "网卡101abc", "VLAN101 [Up]", "a\n101", 'a"101', "a/101"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_adapter_name(name)

    def test_rename_range_matches_user_hint(self):
        self.assertIn("2–254", ADAPTER_NAME_HINT)
        self.assertIn("非网关地址", ADAPTER_NAME_HINT)
        self.assertEqual(validate_adapter_name("VLAN2"), "VLAN2")
        self.assertEqual(validate_adapter_name("VLAN254"), "VLAN254")
        with self.assertRaisesRegex(ValueError, "2–254"):
            validate_adapter_name("VLAN1")

    @patch("src.services.adapter_rename_service.is_windows", return_value=True)
    @patch("src.services.adapter_rename_service.is_admin", return_value=False)
    def test_permission_failure_and_busy_message(self, _admin, _windows):
        self.assertIn("管理员", rename_unavailable_reason())
        self.assertIn("正在执行", rename_unavailable_reason(busy=True))

    @patch("src.services.adapter_rename_service.is_windows", return_value=False)
    def test_non_windows_rejected(self, _windows):
        self.assertIn("Windows", rename_unavailable_reason())

    def test_busy_checks_all_task_kinds(self):
        for flag in (
            "running", "power_on_running", "power_test_running", "parameter_write_running",
            "sample_upgrade_running", "dut_config_running", "onu_query_running",
            "onu_template_query_running", "onu_telnet_test_running", "onu_register_running",
            "onu_save_olt_running", "onu_manage_query_running", "onu_manage_delete_running",
            "onu_cleanup_query_running", "_project_info_query_count",
        ):
            with self.subTest(flag=flag):
                self.assertTrue(adapter_rename_is_busy(SimpleNamespace(**{flag: True})))
        self.assertTrue(adapter_rename_is_busy(SimpleNamespace(test_item_pretest_controls=SimpleNamespace(running=True))))
        self.assertTrue(adapter_rename_is_busy(SimpleNamespace(power_test_resume_session=SimpleNamespace(is_recovering=True))))
        self.assertTrue(adapter_rename_is_busy(SimpleNamespace(pipeline_window=Mock(is_running=Mock(return_value=True)))))
        self.assertFalse(adapter_rename_is_busy(SimpleNamespace()))


class AdapterCoreTests(unittest.TestCase):
    @patch("src.core.network_adapter.subprocess.run")
    def test_reads_stable_identity_and_status(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout='\ufeff{"Name":"以太网","InterfaceGuid":"{ABC-123}","Status":"Up"}', stderr="")
        self.assertEqual(read_adapter_identities(), (AdapterIdentity("以太网", "abc-123", "Up"),))
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertNotIn("以太网", run.call_args.args[0][-1])

    @patch("src.core.network_adapter.subprocess.run")
    def test_query_failure_and_missing_identity_rejected(self, run):
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="access denied")
        with self.assertRaisesRegex(RuntimeError, "access denied"):
            read_adapter_identities()
        run.return_value = SimpleNamespace(returncode=0, stdout='[{"Name":"以太网"}]', stderr="")
        with self.assertRaises(ValueError):
            read_adapter_identities()

    @patch("src.core.network_adapter.subprocess.run")
    def test_rename_uses_literal_argument_list_without_enable_or_ip_changes(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        rename_adapter("Ethernet & old", "以太网 101")
        self.assertEqual(run.call_args.args[0], ["netsh", "interface", "set", "interface", "name=Ethernet & old", "newname=以太网 101"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    @patch("src.core.network_adapter.subprocess.run")
    def test_rename_failure_propagates(self, run):
        run.return_value = SimpleNamespace(returncode=5, stdout="", stderr="denied")
        with self.assertRaisesRegex(RuntimeError, "denied"):
            rename_adapter("以太网", "以太网101")


class AdapterRenameServiceTests(unittest.TestCase):
    def service(self, after=(NEW,), *, before=(OLD,), error=None):
        reader = Mock(side_effect=[before, after])
        renamer = Mock(side_effect=error)
        return AdapterRenameService(reader=reader, renamer=renamer, availability=lambda: "")

    def test_success_requires_same_identity_and_logs_actual_command(self):
        service = self.service()
        logs = []
        result = service.rename("以太网 [Up]", " 以太网101 ", logs.append)
        self.assertTrue(result.ok)
        self.assertEqual(result.adapters, (NEW,))
        service.renamer.assert_called_once_with("以太网", "以太网101")
        self.assertTrue(any("netsh interface set interface" in line for line in logs))
        self.assertTrue(any("guid-one" in line for line in logs))

    def test_bad_input_or_permission_never_calls_system_mutation(self):
        for name, reason in (("bad", ""), ("以太网101", "需要管理员权限")):
            with self.subTest(name=name, reason=reason):
                service = self.service()
                service.availability = lambda: reason
                self.assertFalse(service.rename("以太网", name).ok)
                service.reader.assert_not_called()
                service.renamer.assert_not_called()

    def test_duplicate_names_are_case_insensitive(self):
        service = self.service(before=(OLD, AdapterIdentity("VLAN101", "other")))
        self.assertFalse(service.rename("以太网", "vlan101").ok)
        service.renamer.assert_not_called()

    def test_missing_or_ambiguous_target_never_modifies(self):
        for before in ((), (OLD, OLD)):
            with self.subTest(before=before):
                service = self.service(before=before)
                self.assertFalse(service.rename("以太网", "以太网101").ok)
                service.renamer.assert_not_called()

    def test_query_failure_never_modifies(self):
        service = self.service()
        service.reader.side_effect = RuntimeError("query failed")
        self.assertFalse(service.rename("以太网", "以太网101").ok)
        service.renamer.assert_not_called()

    def test_timeout_reconciles_success_without_retry(self):
        service = self.service(error=subprocess.TimeoutExpired("netsh", 15))
        self.assertTrue(service.rename("以太网", "以太网101").ok)
        service.renamer.assert_called_once()

    def test_failed_command_with_unchanged_identity_preserves_original(self):
        service = self.service(after=(OLD,), error=RuntimeError("denied"))
        result = service.rename("以太网", "以太网101")
        self.assertFalse(result.ok)
        self.assertFalse(result.uncertain)
        self.assertIn("denied", result.message)
        service.renamer.assert_called_once()

    def test_exit_zero_without_real_rename_is_failure(self):
        result = self.service(after=(OLD,)).rename("以太网", "以太网101")
        self.assertFalse(result.ok)

    def test_same_name_on_another_adapter_is_not_success(self):
        service = self.service(after=(AdapterIdentity("以太网101", "other-guid"),))
        result = service.rename("以太网", "以太网101")
        self.assertFalse(result.ok)
        self.assertTrue(result.uncertain)

    def test_readback_failure_is_uncertain_and_no_retry(self):
        service = self.service(after=RuntimeError("query failed"))
        result = service.rename("以太网", "以太网101")
        self.assertTrue(result.uncertain)
        self.assertIn("不要重复提交", result.message)
        service.renamer.assert_called_once()

    def test_duplicate_identity_readback_is_uncertain(self):
        result = self.service(after=(NEW, NEW)).rename("以太网", "以太网101")
        self.assertTrue(result.uncertain)

    def test_synchronize_preserves_unrelated_fields_and_updates_all_old_references(self):
        channels = [
            ChannelConfig("channel_1", "VLAN102", "VLAN102", "COM2", "192.168.1.102", "192.168.1.1"),
            ChannelConfig("channel_2", "以太网", "以太网", "COM9", "", "10.0.0.1", factory_bind_ip="10.0.29.9", enabled=False),
            ChannelConfig("channel_3", "VLAN103", "VLAN103", "COM3", "192.168.1.103", "192.168.1.1"),
        ]
        before = [asdict(c) for c in channels]
        synchronize_channel_adapter_names(channels, "channel_1", "以太网", "以太网101")
        for index in (0, 1):
            expected = dict(before[index], vlan_name="以太网101", adapter_alias="以太网101", network_card_ip="192.168.1.101" if index == 0 else "10.0.0.101")
            self.assertEqual(asdict(channels[index]), expected)
        self.assertEqual(asdict(channels[2]), before[2])

    def test_rename_preserves_existing_legacy_com_mapping(self):
        channel = ChannelConfig("channel_1", "VLAN102", "VLAN102", device_manage_ip="192.168.1.1")
        synchronize_channel_adapter_names([channel], "channel_1", "以太网", "以太网101")
        self.assertEqual(channel.serial_port, "COM2")
        self.assertEqual(LineCheckAssistant._serial_port_for_channel(channel), "COM2")


class AdapterRenameAppTests(unittest.TestCase):
    def context(self, original="VLAN102", selected="以太网 [Up]"):
        channel = ChannelConfig("channel_1", original, original, "COM2", "192.168.1.102", "192.168.1.1")
        context = SimpleNamespace(
            channels=[channel], channel_row_vars={"channel_1": {"vlan": Variable(selected)}},
            _channel_by_section=Mock(return_value=channel), _capture_channel_row=Mock(),
            _refresh_channel_list_item=Mock(), _select_channel_index=Mock(), _persist_config=Mock(),
            _log=Mock(), _on_adapter_renamed=Mock(),
        )
        return context

    @patch("line_check_assistant.app.offer_adapter_rename")
    def test_invalid_selection_restored_before_prompt_and_never_saved(self, offer):
        for original in ("VLAN102", ""):
            with self.subTest(original=original):
                context = self.context(original=original)
                before = asdict(context.channels[0])
                offer.side_effect = lambda *args, **kwargs: self.assertEqual(context.channel_row_vars["channel_1"]["vlan"].get(), original)
                LineCheckAssistant._on_row_vlan_changed(context, "channel_1")
                self.assertEqual(asdict(context.channels[0]), before)
                context._capture_channel_row.assert_not_called()
                context._persist_config.assert_not_called()
                self.assertEqual(offer.call_args.kwargs["old_name"], "以太网")

    @patch("line_check_assistant.app.offer_adapter_rename")
    def test_valid_selection_keeps_original_flow_including_out_of_range_suffix(self, offer):
        for name in ("VLAN101 [Up]", "以太网101", "VLAN1", "VLAN300"):
            with self.subTest(name=name):
                context = self.context(selected=name)
                LineCheckAssistant._on_row_vlan_changed(context, "channel_1")
                context._capture_channel_row.assert_called_once()
                context._persist_config.assert_called_once()
                offer.assert_not_called()

    def test_success_and_save_failure_both_keep_new_memory_and_refresh_targets(self):
        for failure in (None, OSError("disk full")):
            with self.subTest(failure=failure):
                context = self.context()
                context.store = Mock()
                context.store.save.side_effect = failure
                context._selected_channels = Mock(return_value=context.channels)
                context._selected_power_serial_port = Mock(return_value="")
                for name in ("_rebuild_channel_config_rows", "_refresh_upgrade_targets", "_refresh_dut_config_targets", "_refresh_parameter_preflight", "_invalidate_onu_preview"):
                    setattr(context, name, Mock())
                warning = LineCheckAssistant._on_adapter_renamed(context, "channel_1", "以太网", "以太网101", AdapterRenameResult(True, "done", (NEW,)))
                self.assertEqual(context.channels[0].adapter_alias, "以太网101")
                self.assertEqual(context.channels[0].network_card_ip, "192.168.1.101")
                self.assertEqual(context.channels[0].serial_port, "COM2")
                self.assertEqual(context.adapters, ["以太网101 [Up]"])
                context._persist_config.assert_not_called()
                context._refresh_upgrade_targets.assert_called_once()
                context._refresh_dut_config_targets.assert_called_once_with(capture_current=False)
                context._refresh_parameter_preflight.assert_called_once_with(capture_current=False)
                context._invalidate_onu_preview.assert_called_once()
                if failure:
                    self.assertIn("网卡已重命名，但配置保存失败", warning)
                else:
                    self.assertIsNone(warning)

    def test_preview_inputs_can_refresh_without_recapturing_channel_fields(self):
        channel = ChannelConfig("channel_1", "VLAN102", "VLAN102", "COM9", "10.0.0.102", "10.0.0.1", subnet_mask="255.255.0.0")
        before = asdict(channel)
        context = SimpleNamespace(
            channels=[channel], _capture_current_channel=Mock(side_effect=AssertionError("must not capture")),
            parameter_initial_username_var=Variable("operator"), parameter_initial_password_var=Variable("test"),
        )
        requests = LineCheckAssistant._collect_dut_telnet_requests(context, capture_current=False)
        ports = LineCheckAssistant._parameter_channel_ports(context, capture_current=False)
        self.assertEqual(requests[0].subnet_mask, "255.255.0.0")
        self.assertEqual(ports, [("VLAN102", "COM9")])
        self.assertEqual(asdict(channel), before)
        context._capture_current_channel.assert_not_called()

    def query_context(self):
        return SimpleNamespace(
            channels=[ChannelConfig("channel_1", "VLAN101", "VLAN101", network_card_ip="192.168.1.101", device_manage_ip="192.168.1.1")],
            current_index=0, _capture_current_channel=Mock(), _log=Mock(), log_queue=Mock(),
            test_item_config_window=Mock(), after=Mock(side_effect=lambda _delay, callback: callback()),
        )

    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.query_device_project_info", return_value="version")
    def test_concurrent_version_queries_block_rename_until_both_finish(self, query, thread):
        context = self.query_context()
        applied = Mock()
        LineCheckAssistant._start_project_info_query(context, TelnetSettings(), applied)
        first_worker = thread.call_args.kwargs["target"]
        LineCheckAssistant._start_project_info_query(context, TelnetSettings(), applied)
        second_worker = thread.call_args.kwargs["target"]
        self.assertEqual(context._project_info_query_count, 2)
        self.assertTrue(adapter_rename_is_busy(context))
        first_worker()
        self.assertTrue(adapter_rename_is_busy(context))
        second_worker()
        self.assertFalse(adapter_rename_is_busy(context))
        self.assertEqual(applied.call_count, 2)

    @patch("line_check_assistant.app.messagebox.showerror")
    @patch("line_check_assistant.app.threading.Thread")
    @patch("line_check_assistant.app.query_device_project_info", side_effect=RuntimeError("query failed"))
    def test_failed_version_query_clears_busy_marker(self, query, thread, error):
        context = self.query_context()
        LineCheckAssistant._start_project_info_query(context, TelnetSettings(), Mock())
        thread.call_args.kwargs["target"]()
        self.assertFalse(adapter_rename_is_busy(context))
        self.assertIn("query failed", error.call_args.args[1])

    @patch("line_check_assistant.app.threading.Thread")
    def test_version_query_thread_start_failure_clears_busy_marker(self, thread):
        thread.return_value.start.side_effect = RuntimeError("cannot start")
        context = self.query_context()
        with self.assertRaisesRegex(RuntimeError, "cannot start"):
            LineCheckAssistant._start_project_info_query(context, TelnetSettings(), Mock())
        self.assertFalse(adapter_rename_is_busy(context))


class AdapterRenameDialogTests(unittest.TestCase):
    @patch("src.ui.adapter_rename_dialog.AdapterRenameDialog")
    @patch("src.ui.adapter_rename_dialog.messagebox.askyesno", return_value=False)
    def test_decline_does_not_open_dialog(self, ask, dialog):
        log = Mock()
        self.assertIsNone(offer_adapter_rename(Mock(), section="channel_1", old_name="以太网", is_busy=Mock(), on_success=Mock(), log=log))
        dialog.assert_not_called()
        self.assertIn("取消建议", log.call_args.args[0])

    @patch("src.ui.adapter_rename_dialog.rename_unavailable_reason", return_value="")
    @patch("src.ui.adapter_rename_dialog.AdapterRenameDialog")
    @patch("src.ui.adapter_rename_dialog.messagebox.askyesno", return_value=True)
    def test_accept_opens_editable_dialog(self, ask, dialog, availability):
        result = offer_adapter_rename(Mock(), section="channel_1", old_name="以太网", is_busy=lambda: False, on_success=Mock(), log=Mock())
        self.assertIs(result, dialog.return_value)
        self.assertEqual(dialog.call_args.kwargs["old_name"], "以太网")

    @patch("src.ui.adapter_rename_dialog.messagebox.showwarning")
    @patch("src.ui.adapter_rename_dialog.rename_unavailable_reason", return_value="已有任务正在执行")
    @patch("src.ui.adapter_rename_dialog.AdapterRenameDialog")
    @patch("src.ui.adapter_rename_dialog.messagebox.askyesno", return_value=True)
    def test_accept_while_busy_or_without_admin_does_not_modify(self, ask, dialog, availability, warning):
        offer_adapter_rename(Mock(), section="channel_1", old_name="以太网", is_busy=lambda: True, on_success=Mock(), log=Mock())
        dialog.assert_not_called()
        availability.assert_called_once_with(busy=True)
        warning.assert_called_once()

    def dialog(self):
        dialog = object.__new__(AdapterRenameDialog)
        dialog.parent = Mock()
        dialog.window = Mock()
        dialog.old_name = "以太网"
        dialog.pending_name = "以太网101"
        dialog.name_var = Variable("以太网101")
        dialog.status_var = Variable()
        dialog.entry = Mock()
        dialog.submit_button = Mock()
        dialog.cancel_button = Mock()
        dialog.log = Mock()
        dialog.running = False
        dialog.uncertain = False
        dialog.events = queue.Queue()
        dialog.is_busy = lambda: False
        dialog.service = Mock()
        dialog.on_success = Mock(return_value=None)
        return dialog

    def test_cancel_input_never_submits(self):
        dialog = self.dialog()
        dialog.close()
        dialog.service.rename.assert_not_called()
        dialog.on_success.assert_not_called()
        dialog.window.destroy.assert_called_once()

    @patch("src.ui.adapter_rename_dialog.rename_unavailable_reason", return_value="")
    @patch("src.ui.adapter_rename_dialog.threading.Thread")
    def test_submit_runs_background_and_disallows_duplicate_or_close(self, thread, _availability):
        dialog = self.dialog()
        dialog.submit()
        dialog.submit()
        dialog.close()
        thread.assert_called_once()
        self.assertTrue(dialog.running)
        dialog.window.destroy.assert_not_called()
        dialog.on_success.assert_not_called()

    @patch("src.ui.adapter_rename_dialog.threading.Thread")
    def test_invalid_input_keeps_dialog_editable_without_worker(self, thread):
        dialog = self.dialog()
        dialog.name_var.set("bad")
        dialog.submit()
        thread.assert_not_called()
        self.assertFalse(dialog.running)
        dialog.window.destroy.assert_not_called()

    @patch("src.ui.adapter_rename_dialog.messagebox.showwarning")
    def test_worker_only_queues_and_main_poll_applies_success(self, warning):
        dialog = self.dialog()
        dialog.service.rename.return_value = AdapterRenameResult(True, "done", (NEW,))
        dialog.on_success.return_value = "网卡已重命名，但配置保存失败"
        dialog._worker("以太网101")
        dialog.on_success.assert_not_called()
        dialog.window.destroy.assert_not_called()
        dialog._poll()
        dialog.on_success.assert_called_once()
        warning.assert_called_once()
        dialog.window.destroy.assert_called_once()

    @patch("src.ui.adapter_rename_dialog.messagebox.showwarning")
    def test_uncertain_result_blocks_resubmission(self, warning):
        dialog = self.dialog()
        dialog._finish(AdapterRenameResult(False, "unknown", uncertain=True))
        dialog.submit()
        dialog.service.rename.assert_not_called()
        dialog.on_success.assert_not_called()
        self.assertTrue(dialog.uncertain)
        self.assertFalse(dialog.running)

    @patch("src.ui.adapter_rename_dialog.messagebox.showwarning")
    def test_failure_preserves_input_and_does_not_sync_config(self, warning):
        dialog = self.dialog()
        dialog._finish(AdapterRenameResult(False, "denied"))
        self.assertEqual(dialog.name_var.get(), "以太网101")
        dialog.on_success.assert_not_called()
        dialog.entry.configure.assert_called_with(state="normal")


@unittest.skipUnless(sys.platform == "win32", "Windows 独立 Tk 组件验证")
class AdapterRenameTkTests(unittest.TestCase):
    """只构造独立窗口，后台 service 全部替身，不实例化主程序。"""
    def setUp(self):
        self.root = Tk()
        self.root.geometry("700x450+160+120")
        self.root.update()
        self.service = Mock()
        self.applied = Mock(return_value=None)
        self.dialog = AdapterRenameDialog(
            self.root, old_name="以太网", is_busy=lambda: False,
            on_success=self.applied, log=Mock(), service=self.service,
        )
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        # Mock 的 emit 回调可间接保留窗口循环引用，必须在 Tk 主线程释放，
        # 避免后续设备 worker 触发 GC 时销毁 Tcl interpreter。
        self.dialog = None
        self.root = None
        self.service = None
        self.applied = None
        gc.collect()

    def pump_until(self, condition, seconds=3):
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)
        self.assertTrue(condition(), "Tk 后台回调没有按时完成")

    def test_modal_centered_window_and_editable_name(self):
        dialog = self.dialog
        self.assertEqual(dialog.window.grab_current(), dialog.window)
        self.assertEqual(str(dialog.entry.cget("state")), "normal")
        dialog.entry.insert(0, "以太网101")
        self.assertEqual(dialog.name_var.get(), "以太网101")
        # 公共居中工具设置的是顶层 geometry 坐标，不把 Windows 标题栏计入客户区。
        self.assertLessEqual(abs(dialog.window.winfo_x() + dialog.window.winfo_width() // 2 - (self.root.winfo_rootx() + self.root.winfo_width() // 2)), 2)
        self.assertLessEqual(abs(dialog.window.winfo_y() + dialog.window.winfo_height() // 2 - (self.root.winfo_rooty() + self.root.winfo_height() // 2)), 2)
        for widget in (dialog.entry, dialog.submit_button, dialog.cancel_button):
            self.assertTrue(widget.winfo_viewable())
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), dialog.window.winfo_rootx() + dialog.window.winfo_width())

    def test_invalid_input_and_cancel_never_call_service(self):
        self.dialog.name_var.set("Ethernet")
        self.dialog.submit()
        self.assertIn("数字结尾", self.dialog.status_var.get())
        self.assertEqual(str(self.dialog.entry.cget("state")), "normal")
        self.dialog.close()
        self.service.rename.assert_not_called()
        self.applied.assert_not_called()

    @patch("src.ui.adapter_rename_dialog.rename_unavailable_reason", return_value="")
    @patch("src.ui.adapter_rename_dialog.messagebox.showinfo")
    def test_background_rename_keeps_tk_responsive_and_applies_on_main_thread(self, info, _availability):
        entered = threading.Event()
        release = threading.Event()
        ticks = []
        worker_threads = []
        callback_threads = []

        def rename(old_name, new_name, emit):
            worker_threads.append(threading.get_ident())
            entered.set()
            if not release.wait(3):
                raise RuntimeError("模拟后台等待超时")
            emit("fake rename verified")
            return AdapterRenameResult(True, "done", (NEW,))

        self.service.rename.side_effect = rename
        self.applied.side_effect = lambda *_args: callback_threads.append(threading.get_ident())
        self.dialog.name_var.set("以太网101")
        try:
            self.dialog.submit()
            self.pump_until(entered.is_set)
            self.root.after(0, lambda: ticks.append("responsive"))
            self.root.update()
            self.assertEqual(ticks, ["responsive"])
            self.dialog.submit()
            self.dialog.close()
            self.assertTrue(self.dialog.window.winfo_exists())
            self.assertEqual(str(self.dialog.entry.cget("state")), "disabled")
            self.applied.assert_not_called()
        finally:
            release.set()
            self.pump_until(lambda: not self.dialog.running)
        self.service.rename.assert_called_once()
        self.assertNotEqual(worker_threads, [threading.get_ident()])
        self.assertEqual(callback_threads, [threading.get_ident()])
        info.assert_called_once()


if __name__ == "__main__":
    unittest.main()

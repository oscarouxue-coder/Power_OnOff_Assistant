"""自动任务状态生命周期、手动任务隔离及主线程双处状态显示。"""
from dataclasses import replace
import gc
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ai_integration as fixtures
from test_ai_debug import TARGET
from src.models.ai_diagnostics import MonitorStatus
from src.ui.ai_assistant_controller import AiAssistantController
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_monitor_status import AiMonitorStatusRow, monitor_presentation
from line_check_assistant.app import LineCheckAssistant


class MonitorServiceTests(unittest.TestCase):
    setUp = fixtures.ServiceTests.setUp
    stop_service = fixtures.ServiceTests.stop_service
    finish = fixtures.ServiceTests.finish

    def gate(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        return gate

    def test_enabled_run_end_and_new_batch_states(self):
        self.assertEqual(self.service.monitor_status(), MonitorStatus())
        self.service.enable_monitor(True)
        self.assertEqual(self.service.monitor_status(), MonitorStatus(enabled=True))
        self.service.observe({"type": "diagnostic_start", "run_id": "r1"})
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True, True))
        self.service.observe({"type": "diagnostic_end", "run_id": "r1"})
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True, False))
        self.service.observe({"type": "diagnostic_start", "run_id": "r2"})
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(False, True))

    def test_queued_until_execution_lock_then_running_and_cleaning(self):
        entered, release, closing, close_release = (self.gate() for _ in range(4))
        client = Mock()
        def complete(*_args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("测试等待模型超时")
            return SimpleNamespace(history=[], calls=[], text="完成")
        client.complete.side_effect = complete
        tool = Mock(used=0, recovery_state="无临时修改")
        tool.execute.return_value = {"ok": True}
        def close():
            closing.set()
            close_release.wait(3)
        tool.close.side_effect = close
        self.service.client_factory = Mock(return_value=client)
        self.service.tool_factory = Mock(return_value=tool)
        self.service.run_id, self.service.run_active = "r1", True
        self.service.enable_monitor(True)
        with self.service.operation_lock:
            self.service.submit("排查", 1, automatic=True)
            self.assertEqual(self.service.monitor_status().queued, 1)
            self.assertEqual(self.service.monitor_status().running, 0)
            self.assertFalse(entered.is_set())
        self.assertTrue(entered.wait(3))
        self.assertEqual(self.service.monitor_status().running, 1)
        release.set()
        self.assertTrue(closing.wait(3))
        self.assertEqual(self.service.monitor_status().cleaning, 1)
        self.service.enable_monitor(False)
        self.assertEqual(monitor_presentation(self.service.monitor_status())[0], "AI自动监控：已关闭，收尾中")
        close_release.set()
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(run_active=True))

    def test_multiple_channels_and_cancelled_queue_are_aggregated(self):
        entered, release = self.gate(), self.gate()
        def diagnose(*_args):
            entered.set()
            release.wait(3)
        self.service._diagnose = diagnose
        self.service.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        self.service.enable_monitor(True)
        self.service.submit("通道1", 1, automatic=True)
        self.assertTrue(entered.wait(3))
        self.service.submit("通道2", 2, automatic=True)
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True, False, queued=1, running=1))
        self.service.cancel_channel(2)
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True, False, running=1, cleaning=1))
        self.assertEqual(monitor_presentation(self.service.monitor_status())[0], "AI自动监控：诊断中")
        release.set()
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True))

    def test_manual_diagnostic_job_and_chat_do_not_count(self):
        entered, release = self.gate(), self.gate()
        def diagnose(*_args):
            entered.set()
            release.wait(3)
        self.service._diagnose = diagnose
        self.service.enable_monitor(True)
        self.service.submit("手动", 1)
        self.assertTrue(entered.wait(3))
        self.service.conversation = SimpleNamespace(idle=False)
        self.addCleanup(setattr, self.service, "conversation", None)
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True))
        release.set()
        self.finish()

    def test_cancel_before_execution_releases_tracking_without_diagnosing(self):
        self.service._diagnose = Mock()
        with self.service.operation_lock:
            self.service.submit("自动", 1, automatic=True)
            self.service.cancel_channel(1)
            self.assertEqual(self.service.monitor_status().cleaning, 1)
        self.finish()
        self.service._diagnose.assert_not_called()
        self.assertEqual(self.service.monitor_status(), MonitorStatus())

    def test_failures_leave_no_running_or_queued_state(self):
        self.service._diagnose = Mock(side_effect=RuntimeError("离线模型失败"))
        self.service.enable_monitor(True)
        self.service.submit("自动", 1, automatic=True)
        self.finish()
        self.assertEqual(self.service.monitor_status(), MonitorStatus(True))
        self.assertEqual(self.store.reports()[0][2]["status"], "失败")

    def test_local_snapshots_and_full_queue_do_not_leave_queued_state(self):
        self.service.configure(replace(self.profile, model=""), (TARGET,))
        self.service.submit("未配置模型", 1, automatic=True)
        self.assertEqual(self.service.monitor_status(), MonitorStatus())
        self.service.configure(self.profile, (TARGET,))
        with patch.object(self.store, "key", side_effect=RuntimeError("无密钥")):
            self.service.submit("无密钥", 1, automatic=True)
        with patch.object(self.service.jobs, "put_nowait", side_effect=queue.Full):
            self.service.submit("队列满", 1, automatic=True)
        self.assertEqual(self.service.monitor_status(), MonitorStatus())
        self.assertEqual(len(self.store.reports()), 3)


class PresentationTests(unittest.TestCase):
    def test_all_states_and_priority(self):
        cases = (
            (MonitorStatus(), "已关闭"),
            (MonitorStatus(True), "已开启，待测试"),
            (MonitorStatus(True, True), "监控中"),
            (MonitorStatus(True, True, queued=1), "诊断排队中"),
            (MonitorStatus(True, True, queued=1, running=1, cleaning=1), "诊断中"),
            (MonitorStatus(True, True, queued=1, cleaning=1), "收尾中"),
            (MonitorStatus(False, True, cleaning=1), "已关闭，收尾中"),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(monitor_presentation(status)[0], "AI自动监控：" + expected)


class MonitorUiTests(unittest.TestCase):
    setUp_service = fixtures.ServiceTests.setUp
    stop_service = fixtures.ServiceTests.stop_service
    finish = fixtures.ServiceTests.finish

    def setUp(self):
        self.setUp_service()
        gc.collect()
        self.root = tk.Tk()
        LineCheckAssistant._configure_theme(self.root)
        self.root.geometry("700x300")
        self.power_var = tk.StringVar(self.root, value="开关机测试状态：已停止")
        self.progress_var = tk.StringVar(self.root, value="开关机测试进度：等待开始")
        self.row = AiMonitorStatusRow(self.root, "Microsoft YaHei UI")
        self.row.attach(ttk.Label(self.row, textvariable=self.power_var, style="PowerStatusIdle.TLabel"),
                        ttk.Label(self.row, textvariable=self.progress_var, style="CardHint.TLabel"))
        self.row.pack(fill="x")
        self.dialog = AiDiagnosticsWindow(self.root, self.service, lambda: (TARGET,))
        self.dialog.open()
        self.controller = AiAssistantController.__new__(AiAssistantController)
        self.controller.master, self.controller.service = self.root, self.service
        self.controller.bridge = Mock()
        self.controller.dialog = self.dialog
        self.controller.closed = False
        self.controller.monitor_snapshot = None
        self.controller.on_monitor_status = Mock(wraps=self.row.show)
        self.controller.after_id = None
        self.addCleanup(self.close_ui)

    def close_ui(self):
        for identifier in (self.controller.after_id, self.dialog._poll_id):
            if identifier:
                self.root.after_cancel(identifier)
        self.root.destroy()
        self.controller = self.dialog = self.row = self.root = self.power_var = self.progress_var = None
        gc.collect()

    def sync(self):
        if self.controller.after_id:
            self.root.after_cancel(self.controller.after_id)
        self.controller._poll()

    def test_two_locations_sync_while_hidden_and_after_reopen(self):
        self.sync()
        self.assertEqual(self.row.ai_label.cget("text"), "AI自动监控：已关闭")
        self.dialog.hide()
        self.service.enable_monitor(True)
        self.service.observe({"type": "diagnostic_start", "run_id": "r1"})
        self.finish()
        self.sync()
        self.assertEqual(self.row.ai_label.cget("text"), "AI自动监控：监控中")
        self.assertEqual(self.dialog.monitor_status.get(), self.row.ai_label.cget("text"))
        self.assertTrue(self.dialog.monitor_panel.enabled.get())
        self.dialog.open()
        self.assertEqual(self.dialog.monitor_status.get(), "AI自动监控：监控中")
        self.service.observe({"type": "diagnostic_start", "run_id": "r2"})
        self.finish()
        self.sync()
        self.assertEqual(self.dialog.monitor_status.get(), "AI自动监控：已关闭")
        self.assertFalse(self.dialog.monitor_panel.enabled.get())

    def test_unchanged_snapshot_does_not_refresh_main_view(self):
        self.sync()
        logs = len(self.output)
        self.sync()
        self.controller.on_monitor_status.assert_called_once_with(MonitorStatus())
        self.assertEqual(len(self.output), logs)
        for snapshot in (MonitorStatus(True, True, queued=1), MonitorStatus(True, True, running=1),
                         MonitorStatus(True, True, cleaning=1), MonitorStatus(False, cleaning=1), MonitorStatus()):
            with patch.object(self.service, "monitor_status", return_value=snapshot):
                self.sync()
                self.assertEqual(self.dialog.monitor_status.get(), monitor_presentation(snapshot)[0])
                self.assertEqual(self.row.ai_label.cget("text"), self.dialog.monitor_status.get())

    def test_cancel_monitor_confirmation_keeps_both_locations_disabled(self):
        self.dialog.monitor_panel.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=False):
            self.dialog.monitor_panel.changed()
        self.sync()
        self.assertFalse(self.dialog.monitor_panel.enabled.get())
        self.assertEqual(self.dialog.monitor_status.get(), "AI自动监控：已关闭")
        self.assertEqual(self.row.ai_label.cget("text"), self.dialog.monitor_status.get())

    def test_parallel_layout_preserves_full_text_in_both_themes_and_narrow_width(self):
        style = ttk.Style(self.root)
        stopping = "开关机测试状态：正在停止（等待当前子任务安全退出）"
        self.power_var.set(stopping)
        self.row.show(MonitorStatus(False, cleaning=1))
        for theme in ("vista", "clam"):
            style.theme_use(theme)
            for width in (800, 560):
                with self.subTest(theme=theme, width=width):
                    self.root.geometry(f"{width}x300")
                    self.root.update()
                    labels = self.row.labels
                    for left, right in zip(labels, labels[1:]):
                        self.assertLessEqual(left.winfo_x() + left.winfo_width(), right.winfo_x())
                        self.assertAlmostEqual(left.winfo_y() + left.winfo_height() / 2,
                                               right.winfo_y() + right.winfo_height() / 2, delta=1)
                    self.assertLessEqual(labels[-1].winfo_x() + labels[-1].winfo_width(), self.row.winfo_width())
                    self.assertGreater(labels[1].winfo_width(), 100)
                    self.assertEqual(self.power_var.get(), stopping)
                    self.assertEqual(labels[1].cget("text"), "AI自动监控：已关闭，收尾中")
                    self.assertEqual(self.progress_var.get(), "开关机测试进度：等待开始")


if __name__ == "__main__":
    unittest.main()

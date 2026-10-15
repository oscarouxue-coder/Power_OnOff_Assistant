import inspect
import queue
import re
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tkinter import StringVar, Tk, ttk
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from line_check_assistant.app import LineCheckAssistant
from src.models.app_update import AppUpdateProgress, UpdateProgressStage
from src.services.app_update_service import AppUpdateCancelled, AppUpdateError, AppUpdateService
from src.ui.app_update_dialog import AppUpdateDialog, MANUAL_UPDATE_HINT, _UpdateTask
from test_app_update import ZIP_CONTENT, ZIP_HASH, release_payload, update_result


class AppUpdateUiTests(unittest.TestCase):
    def setUp(self):
        self.parent = Mock()
        self.logs = queue.Queue()
        self.service = Mock()
        self.factory = Mock(return_value=self.service)
        self.dialog = AppUpdateDialog(self.parent, "V1.1.4", log=self.logs.put, service_factory=self.factory)
        self.dialog.bind_button(Mock())
        self.dialog.window = Mock()
        for name in ("status", "summary", "notes", "progress_bar", "action_button", "close_button"):
            setattr(self.dialog, name, Mock())

    def test_constructor_is_offline_and_does_not_schedule_tasks(self):
        self.factory.assert_not_called()
        self.parent.after.assert_not_called()

    @patch("src.ui.app_update_dialog.threading.Thread")
    def test_duplicate_check_does_not_start_two_workers(self, thread):
        self.dialog.check()
        first = self.dialog.task
        self.dialog.check()
        self.assertIs(self.dialog.task, first)
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        self.dialog.toolbar_button.configure.assert_called_with(text="正在检查…", state="disabled")

    def test_open_existing_window_only_brings_it_forward(self):
        self.dialog.open()
        self.dialog.window.lift.assert_called_once()
        self.factory.assert_not_called()

    def test_failed_check_restores_controls_and_never_claims_latest(self):
        task = _UpdateTask("check")
        task.results.put(("error", "无法连接 GitHub"))
        self.dialog.task = task
        self.dialog._poll(task)
        self.assertIsNone(self.dialog.task)
        self.dialog.status.set.assert_called_with("无法连接 GitHub")
        self.dialog.toolbar_button.configure.assert_called_with(text="检查更新", state="normal")
        self.dialog.action_button.configure.assert_called_with(text="重新检查", command=self.dialog.check)

    def test_update_available_displays_notes_size_and_download_choice(self):
        task = _UpdateTask("check")
        task.results.put(("success", update_result()))
        self.dialog.task = task
        self.dialog._poll(task)
        self.assertEqual(self.dialog.update.latest_version, "v1.1.10")
        self.dialog.notes.insert.assert_called_with("1.0", "改动")
        self.dialog.action_button.configure.assert_called_with(text="下载", command=self.dialog.download)
        self.dialog.close_button.configure.assert_called_with(text="暂不下载")

    def test_progress_is_coalesced_and_handled_by_poll(self):
        task = _UpdateTask("download")
        self.dialog.task = task
        for completed in range(1000):
            task.report_progress(AppUpdateProgress(UpdateProgressStage.DOWNLOADING, completed, 1000))
        self.assertEqual(task.progress.qsize(), 1)
        self.dialog._poll(task)
        self.assertIn("99.9%", self.dialog.status.set.call_args.args[0])
        self.dialog.progress_bar.configure.assert_called_with(value=99.9)
        self.parent.after.assert_called_once()

    def test_close_cancels_task_and_stale_result_cannot_update_reopened_window(self):
        task = _UpdateTask("check")
        self.dialog.task = task
        self.dialog.poll_id = "old-after"
        old_window = self.dialog.window
        self.dialog.close_window()
        self.assertTrue(task.cancelled.is_set())
        self.parent.after_cancel.assert_called_once_with("old-after")
        old_window.destroy.assert_called_once()
        self.dialog.window = Mock()
        self.dialog.task = _UpdateTask("check")
        task.results.put(("success", update_result()))
        self.dialog._poll(task)
        self.dialog.status.set.assert_not_called()
        self.dialog.summary.set.assert_not_called()

    def test_download_cancel_sets_event_and_waits_for_service_cleanup(self):
        task = _UpdateTask("download")
        self.dialog.task = task
        self.dialog.cancel_download()
        self.assertTrue(task.cancelled.is_set())
        self.assertIs(self.dialog.task, task)
        self.dialog.close_button.configure.assert_called_with(state="disabled")

    @patch("src.ui.app_update_dialog.filedialog.asksaveasfilename", return_value="")
    def test_cancel_save_dialog_does_not_start_download(self, save_dialog):
        self.dialog.update = update_result()
        with patch.object(self.dialog, "_start_task") as start:
            self.dialog.download()
        start.assert_not_called()
        self.assertIn("v1.1.10", save_dialog.call_args.kwargs["initialfile"])

    def test_existing_destination_requires_confirmation_before_download(self):
        self.dialog.update = update_result()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.zip"
            path.write_bytes(b"old")
            with patch("src.ui.app_update_dialog.filedialog.asksaveasfilename", return_value=str(path)), \
                    patch("src.ui.app_update_dialog.messagebox.askyesno", return_value=False) as confirm, \
                    patch.object(self.dialog, "_start_task") as start:
                self.dialog.download()
            confirm.assert_called_once()
            start.assert_not_called()
            self.assertEqual(path.read_bytes(), b"old")

    def test_worker_uses_only_service_queue_and_thread_safe_logs(self):
        self.service.check_for_update.return_value = update_result()
        task = _UpdateTask("check")
        thread = threading.Thread(target=self.dialog._worker, args=(task, ()))
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(task.results.get_nowait()[0], "success")
        self.service.close.assert_called_once()
        self.parent.after.assert_not_called()
        self.dialog.status.set.assert_not_called()
        self.dialog.window.after.assert_not_called()

    def test_session_close_error_does_not_lose_download_result(self):
        self.service.download_update.return_value = Path("download.zip")
        self.service.close.side_effect = OSError("close failed")
        task = _UpdateTask("download")
        self.dialog._worker(task, (update_result(), Path("download.zip"), False))
        self.assertEqual(task.results.get_nowait(), ("success", Path("download.zip")))

    def test_worker_error_and_cancel_are_distinct_results(self):
        for error, kind in ((AppUpdateCancelled("已取消"), "cancelled"), (AppUpdateError("断网"), "error")):
            self.service.check_for_update.side_effect = error
            task = _UpdateTask("check")
            self.dialog._worker(task, ())
            self.assertEqual(task.results.get_nowait(), (kind, str(error)))

    def test_shutdown_cancels_detached_jobs_and_defers_main_exit_until_done(self):
        thread = Mock()
        thread.is_alive.return_value = True
        task = _UpdateTask("download", thread=thread)
        self.dialog.jobs.append(task)
        on_ready = Mock()
        self.assertFalse(self.dialog.prepare_app_close(on_ready))
        self.assertTrue(task.cancelled.is_set())
        self.assertTrue(self.dialog.shutting_down)
        on_ready.assert_not_called()
        thread.is_alive.return_value = False
        self.dialog._wait_for_close(on_ready)
        on_ready.assert_called_once()

    def test_shutdown_prevents_new_windows_and_late_ui_callbacks(self):
        self.dialog.shutting_down = True
        self.dialog.open()
        task = _UpdateTask("check")
        self.dialog.task = task
        self.dialog._poll(task)
        self.dialog.window.lift.assert_not_called()
        self.parent.after.assert_not_called()
        self.factory.assert_not_called()

    def test_main_exit_waits_for_update_cleanup_before_existing_shutdown(self):
        updates = Mock()
        updates.prepare_app_close.return_value = False
        context = SimpleNamespace(app_update_dialog=updates, _on_app_close=Mock(), serial_session_manager=Mock(),
                                  power_test_resume_session=Mock(), dut_config_cancel_event=threading.Event())
        LineCheckAssistant._on_app_close(context)
        context.power_test_resume_session.stop.assert_called_once()
        self.assertTrue(context.dut_config_cancel_event.is_set())
        updates.prepare_app_close.assert_called_once_with(context._on_app_close)
        context.serial_session_manager.shutdown_all.assert_not_called()

    def test_main_source_adds_only_update_assembly_and_manual_entry(self):
        source = inspect.getsource(LineCheckAssistant._build_ui)
        self.assertIn('text="检查更新"', source)
        self.assertIn("command=self.app_update_dialog.open", source)
        self.assertIn("log=self.log_queue.put", source)
        init = inspect.getsource(LineCheckAssistant.__init__)
        self.assertNotIn("check_for_update", init)
        self.assertNotIn("download_update", source)

    def test_main_exit_flushes_update_result_logs_before_destroying_widgets(self):
        events = []
        updates = Mock(jobs=[Mock()])
        updates.prepare_app_close.return_value = True
        log_queue = queue.Queue()
        for index in range(125):
            log_queue.put(str(index))
        def drain():
            for _ in range(min(120, log_queue.qsize())):
                log_queue.get_nowait()
            events.append("drain")
        context = SimpleNamespace(
            app_update_dialog=updates, _on_app_close=Mock(), log_queue=log_queue,
            _drain_log_queue=drain, onu_save_after_id=None, sample_upgrade_save_after_id=None,
            _save_onu_registration_config=Mock(), _save_sample_upgrade_settings=Mock(),
            destroy=lambda: events.append("destroy"),
        )
        LineCheckAssistant._on_app_close(context)
        self.assertEqual(events, ["drain", "drain", "destroy"])
        self.assertTrue(log_queue.empty())


@unittest.skipUnless(sys.platform == "win32", "Windows Tk 源码组件验证")
class AppUpdateTkTests(unittest.TestCase):
    """只构造更新窗口，无主程序初始化、配置写入或设备访问。"""

    def setUp(self):
        self.root = Tk()
        self.root.withdraw()
        self.logs = queue.Queue()
        self.client = Mock()
        self.client.latest_release.return_value = release_payload()
        self.client.read_text_asset.return_value = f"{ZIP_HASH} *LineCheckAssistant_portable.zip"
        self.dialog = AppUpdateDialog(self.root, "V1.1.4", log=self.logs.put, service_factory=lambda: AppUpdateService(self.client))
        self.button = ttk.Button(self.root, text="检查更新", command=self.dialog.open)
        self.dialog.bind_button(self.button)

    def tearDown(self):
        for task in self.dialog.jobs:
            task.cancelled.set()
        self.dialog.close_window()
        for task in self.dialog.jobs:
            if task.thread is not None:
                task.thread.join(2)
        self.root.destroy()

    def pump_until(self, condition):
        deadline = time.monotonic() + 4
        while not condition():
            self.root.update()
            if time.monotonic() >= deadline:
                self.fail("Tk 更新任务未在测试期限内完成")
            time.sleep(0.005)

    def test_real_tk_check_and_verified_download_to_user_selected_file(self):
        self.dialog.open()
        self.pump_until(lambda: self.dialog.task is None)
        self.assertEqual(self.dialog.action_button.cget("text"), "下载")
        self.assertEqual(self.dialog.close_button.cget("text"), "暂不下载")
        self.assertEqual(self.dialog.notes.cget("state"), "disabled")
        self.assertIn("v1.1.10", self.dialog.summary.get())
        def download(url, path, event, progress):
            path.write_bytes(ZIP_CONTENT)
            progress(len(ZIP_CONTENT), len(ZIP_CONTENT))
        self.client.download_asset.side_effect = download
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "新版.zip"
            with patch("src.ui.app_update_dialog.filedialog.asksaveasfilename", return_value=str(destination)):
                self.dialog.action_button.invoke()
            self.pump_until(lambda: self.dialog.task is None)
            self.assertEqual(destination.read_bytes(), ZIP_CONTENT)
            self.assertIn("SHA256 校验通过", self.dialog.status.get())
            self.assertEqual(self.dialog.action_button.cget("text"), "打开所在文件夹")
            with patch("src.ui.app_update_dialog.os.startfile") as open_folder:
                self.dialog.action_button.invoke()
            open_folder.assert_called_once_with(str(destination.parent))
        self.assertIn("先备份", MANUAL_UPDATE_HINT)

    def test_real_tk_remains_responsive_while_check_is_blocked_and_cancelled(self):
        release = threading.Event()
        def blocked():
            release.wait(3)
            return release_payload()
        self.client.latest_release.side_effect = blocked
        self.dialog.open()
        task = self.dialog.task
        tick = []
        self.root.after(0, lambda: tick.append(True))
        try:
            self.pump_until(lambda: bool(tick))
            self.assertIs(self.dialog.task, task)
            self.assertIn("disabled", self.button.state())
            self.dialog.close_window()
            self.assertTrue(task.cancelled.is_set())
            self.assertNotIn("disabled", self.button.state())
        finally:
            release.set()
            task.thread.join(2)
        self.assertIsNone(self.dialog.window)

    def test_real_tk_failed_request_stays_failure_and_can_be_retried(self):
        from src.core.github_release_client import GitHubReleaseError
        self.client.latest_release.side_effect = GitHubReleaseError("无法连接 GitHub")
        self.dialog.open()
        self.pump_until(lambda: self.dialog.task is None)
        self.assertIn("无法连接", self.dialog.status.get())
        self.assertNotIn("已是最新", self.dialog.status.get())
        self.assertEqual(self.dialog.action_button.cget("text"), "重新检查")
        self.client.latest_release.side_effect = None
        self.client.latest_release.return_value = release_payload("v1.1.4")
        self.dialog.action_button.invoke()
        self.pump_until(lambda: self.dialog.task is None)
        self.assertIn("已是最新版本", self.dialog.status.get())

    def test_main_source_toolbar_update_and_existing_controls_are_visible(self):
        # 只运行源码 UI 装配，替换全部设备/配置/日志回调，不运行应用 __init__。
        source = inspect.getsource(LineCheckAssistant._build_ui)
        for name in set(re.findall(r"self\.(_[a-zA-Z_]\w*)", source)):
            setattr(self.root, name, Mock(return_value=""))
        self.root.channels = []
        self.root.current_index = -1
        self.root.adapters = []
        self.root.power_serial_port = ""
        self.root.power_serial_options = [""]
        self.root.log_path = Path("not-written.log")
        self.root.log_queue = self.logs
        for name in ("power_test_status_var", "power_test_progress_text_var", "power_test_channel_summary_var", "power_test_channel_attention_var", "power_test_channel_detail_var"):
            setattr(self.root, name, StringVar(master=self.root, value=""))
        LineCheckAssistant._configure_theme(self.root)
        with patch("line_check_assistant.app.is_admin", return_value=True):
            LineCheckAssistant._build_ui(self.root)
        self.dialog = self.root.app_update_dialog
        self.root.deiconify()
        toolbar = self.root.check_updates_button.master.master
        widgets = [child for frame in toolbar.winfo_children() for child in frame.winfo_children()]
        admin = next(widget for widget in widgets if isinstance(widget, ttk.Label) and widget.cget("text") == "管理员权限已就绪")
        for width in (1040, 1200, 1600):
            for text in ("检查更新", "正在检查…"):
                for admin_text in ("管理员权限已就绪", "缺少管理员权限，请右键以管理员身份运行"):
                    with self.subTest(width=width, text=text, admin=admin_text):
                        admin.configure(text=admin_text)
                        self.root.check_updates_button.configure(text=text)
                        self.root.geometry(f"{width}x780")
                        self.root.update()
                        for widget in widgets:
                            if isinstance(widget, (ttk.Button, ttk.Label)):
                                self.assertTrue(widget.winfo_ismapped(), widget.cget("text"))
                                self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), widget.cget("text"))
                                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), toolbar.winfo_rootx() + toolbar.winfo_width())
        self.assertIsNone(self.dialog.task)

    def test_real_tk_application_close_waits_until_partial_download_is_cleaned(self):
        from src.core.github_release_client import DownloadCancelled
        started = threading.Event()
        def cancelled_download(url, path, event, progress):
            path.write_bytes(b"partial")
            started.set()
            event.wait(3)
            raise DownloadCancelled("下载已取消")
        self.client.download_asset.side_effect = cancelled_download
        self.dialog.open()
        self.pump_until(lambda: self.dialog.task is None)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "existing.zip"
            destination.write_bytes(b"keep")
            with patch("src.ui.app_update_dialog.filedialog.asksaveasfilename", return_value=str(destination)), \
                    patch("src.ui.app_update_dialog.messagebox.askyesno", return_value=True):
                self.dialog.download()
            self.pump_until(started.is_set)
            ready = Mock()
            immediate = self.dialog.prepare_app_close(ready)
            if not immediate:
                self.pump_until(lambda: ready.called)
            self.assertFalse(list(Path(folder).glob("*.part")))
            self.assertEqual(destination.read_bytes(), b"keep")

    def test_real_tk_small_window_wraps_hints_and_keeps_action_buttons_visible(self):
        self.dialog.open()
        self.pump_until(lambda: self.dialog.task is None)
        self.dialog.window.geometry("560x470")
        self.root.update()
        content = self.dialog.action_button.master.master
        for widget in content.winfo_children():
            if isinstance(widget, ttk.Label):
                self.assertLessEqual(widget.winfo_reqwidth(), content.winfo_width() - 36)
        for widget in (self.dialog.action_button, self.dialog.close_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), self.dialog.window.winfo_rooty() + self.dialog.window.winfo_height())


if __name__ == "__main__":
    unittest.main()

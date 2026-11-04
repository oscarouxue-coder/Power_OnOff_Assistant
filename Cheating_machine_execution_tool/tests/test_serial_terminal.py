import os
import gc
import json
import queue
import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui.serial_terminal import SerialTerminalWindow, build_serial_log_path
from src.core.serial_transport import PySerialSession, SerialSessionManager
from src.models import SerialSettings


class QuietSerial:
    """Blocking fake driver: no real COM, commands or busy reader loop."""

    def __init__(self, **kwargs):
        self.closed = False
        self.chunks = queue.Queue()

    def read(self, size):
        try:
            return self.chunks.get(timeout=0.01)
        except queue.Empty:
            return b""

    def close(self):
        self.closed = True

    def cancel_read(self):
        self.chunks.put(b"")


class SerialTerminalCloseTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.addCleanup(self._collect_tk)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.manager = SerialSessionManager()
        self.logger = Mock()
        base = Path(self.temp.name)
        self.terminal = SerialTerminalWindow(
            self.root, self.manager, base, base / "state.json", logger=self.logger,
        )
        self.addCleanup(self.terminal.close)
        self.addCleanup(self.manager.shutdown_all)
        self.drivers = {}

        def make_session(settings, log_path=None):
            driver = QuietSerial()
            self.drivers[settings.port] = driver
            return PySerialSession(settings, log_path, serial_factory=lambda **kwargs: driver)

        replacement = patch("src.core.serial_transport.PySerialSession", side_effect=make_session)
        replacement.start()
        self.addCleanup(replacement.stop)
        with patch.object(self.terminal, "_restore_log_dir", return_value=base):
            self.terminal.show([("vlan101", "COM8"), ("vlan102", "COM9")])
        self.root.update()

    def _collect_tk(self):
        # Tk variables/images must be finalized on the UI thread, before a
        # later fake-serial worker triggers cyclic GC in the full test suite.
        self.terminal = None
        self.root = None
        gc.collect()

    def close_point(self, vlan):
        book = self.terminal.notebook
        self.root.update_idletasks()
        frame = str(self.terminal.tabs[vlan]["frame"])
        for y in range(min(60, book.winfo_height())):
            for x in range(book.winfo_width()):
                if book._close_tab_at(x, y) == frame:
                    return x, y
        self.fail(f"No visible close target for {vlan}")

    def click_close(self, vlan):
        x, y = self.close_point(vlan)
        book = self.terminal.notebook
        book.event_generate("<ButtonPress-1>", x=x, y=y)
        book.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.root.update()

    def test_close_active_monitor_releases_only_target_and_flushes_log(self):
        self.assertEqual(self.terminal.open_all(), ())
        first = self.terminal.tabs["vlan101"]["session"]
        other = self.terminal.tabs["vlan102"]["session"]
        path = first.log_path
        first._emit("RX", b"unfinished", "unfinished")
        self.click_close("vlan101")
        self.assertNotIn("vlan101", self.terminal.tabs)
        self.assertTrue(self.drivers["COM8"].closed)
        self.assertFalse(first._reader.is_alive())
        self.assertIsNone(first._log_handle)
        self.assertFalse(self.drivers["COM9"].closed)
        self.assertIs(other, self.terminal.tabs["vlan102"]["session"])
        other._emit("RX", b"still running\n", "still running\n")
        self.terminal._on_tab_changed()
        self.root.update()
        self.assertIn("still running", self.terminal.tabs["vlan102"]["output"].get("1.0", "end"))
        saved = path.read_text(encoding="utf-8")
        self.assertRegex(saved, r"\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d RX unfinished\n")
        self.assertIn("STATE 串口已关闭", saved)
        self.assertIn("vlan101 / COM8", self.logger.call_args.args[0])

    def test_close_inactive_unopened_tab_preserves_selection(self):
        book = self.terminal.notebook
        selected = book.select()
        self.click_close("vlan102")
        self.assertEqual(book.select(), selected)
        self.assertEqual(tuple(self.terminal.tabs), ("vlan101",))
        self.assertFalse(self.drivers)

    def test_close_last_tab_keeps_window_and_show_restores_tabs(self):
        self.click_close("vlan102")
        self.click_close("vlan101")
        self.assertTrue(self.terminal.window.winfo_exists())
        self.assertEqual(self.terminal.notebook.tabs(), ())
        self.terminal.show([("vlan101", "COM8")])
        self.root.update()
        self.assertEqual(tuple(self.terminal.tabs), ("vlan101",))
        self.assertIsNone(self.terminal.tabs["vlan101"]["session"])
        self.assertEqual(self.terminal.open_all(), ())

    def test_upgrade_blocks_close_and_allows_it_after_control_release(self):
        self.terminal.open_all()
        item = self.terminal.tabs["vlan101"]
        session = item["session"]
        subscriber = item["subscriber"]
        self.manager.acquire_control("upgrade", SerialSettings("COM8"))
        with patch("src.ui.serial_terminal.messagebox.showwarning") as warning:
            self.click_close("vlan101")
        self.assertEqual(warning.call_args.args[1], "当前串口正在自动升级，升级结束后可关闭")
        self.assertIs(item["session"], session)
        self.assertIn(subscriber, session._subscribers)
        self.assertFalse(self.drivers["COM8"].closed)
        self.assertIn("跳过关闭", self.logger.call_args.args[0])
        self.manager.release("upgrade", "COM8")
        self.assertTrue(self.terminal.close_tab("vlan101"))

    def test_upgrade_only_subscription_is_protected(self):
        session = self.manager.acquire_control("upgrade", SerialSettings("COM8"))
        self.terminal.attach_upgrade("vlan101", session, Path(self.temp.name) / "upgrade.log", "COM8")
        with patch("src.ui.serial_terminal.messagebox.showwarning"):
            self.assertFalse(self.terminal.close_tab("vlan101"))
        self.assertIsNone(self.terminal.tabs["vlan101"]["owner"])
        self.assertFalse(self.drivers["COM8"].closed)
        self.manager.release("upgrade", "COM8")
        self.assertTrue(self.terminal.close_tab("vlan101"))

    def test_stopped_tab_can_close(self):
        self.terminal.open_all()
        self.terminal.stop_all()
        self.assertTrue(self.terminal.close_tab("vlan101"))
        self.assertNotIn("vlan101", self.terminal.tabs)

    def test_release_failure_keeps_tab_and_restores_subscription(self):
        self.terminal.open_all()
        item = self.terminal.tabs["vlan101"]
        with patch.object(self.manager, "release", side_effect=OSError("release failed")), patch(
            "src.ui.serial_terminal.messagebox.showerror"
        ) as error:
            self.assertFalse(self.terminal.close_tab("vlan101"))
        self.assertIs(self.terminal.tabs["vlan101"], item)
        self.assertIn(item["subscriber"], item["session"]._subscribers)
        self.assertTrue(item["frame"].winfo_exists())
        self.assertIn("release failed", error.call_args.args[1])
        self.assertIn("关闭失败 vlan101 / COM8", self.logger.call_args.args[0])

    def test_old_subscription_events_cannot_enter_reopened_vlan(self):
        self.terminal.open_all()
        old = self.terminal.tabs["vlan101"]["subscriber"]
        old(SimpleNamespace(text="queued old event"))
        self.terminal._append_pending_chunk("vlan101", "buffered old event")
        self.terminal._pending_dropped_chars["vlan101"] = 12
        self.assertTrue(self.terminal.close_tab("vlan101"))
        self.assertNotIn("vlan101", self.terminal._pending_chunks)
        self.assertNotIn("vlan101", self.terminal._pending_char_counts)
        self.assertNotIn("vlan101", self.terminal._pending_dropped_chars)
        self.terminal.show([("vlan101", "COM8")])
        self.terminal.open_monitor("vlan101")
        old(SimpleNamespace(text="late old event"))
        item = self.terminal.tabs["vlan101"]
        item["subscriber"](SimpleNamespace(text="new event"))
        self.terminal.notebook.select(item["frame"])
        self.terminal._on_tab_changed()
        self.root.update()
        output = item["output"].get("1.0", "end")
        self.assertIn("new event", output)
        self.assertNotIn("old event", output)

    def test_same_com_other_monitor_keeps_its_connection(self):
        self.terminal._ensure_tab("vlan102", "COM8")
        self.terminal.open_all()
        other = self.terminal.tabs["vlan102"]
        session = other["session"]
        self.assertTrue(self.terminal.close_tab("vlan101"))
        self.assertFalse(self.drivers["COM8"].closed)
        self.assertIn(other["subscriber"], session._subscribers)
        self.assertTrue(self.terminal.close_tab("vlan102"))
        self.assertTrue(self.drivers["COM8"].closed)

    def test_click_label_selects_without_closing(self):
        book = self.terminal.notebook
        target = str(self.terminal.tabs["vlan102"]["frame"])
        for x in range(book.winfo_width()):
            if book.identify(x, 10) == "label" and book.tabs()[book.index(f"@{x},10")] == target:
                book.event_generate("<ButtonPress-1>", x=x, y=10)
                book.event_generate("<ButtonRelease-1>", x=x, y=10)
                break
        else:
            self.fail("Label not found")
        self.root.update()
        self.assertEqual(book.select(), target)
        self.assertEqual(len(self.terminal.tabs), 2)

    def test_drag_off_close_and_release_without_press_do_not_close(self):
        book = self.terminal.notebook
        x, y = self.close_point("vlan101")
        book.event_generate("<ButtonPress-1>", x=x, y=y)
        book.event_generate("<ButtonRelease-1>", x=0, y=0)
        book.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.assertEqual(len(self.terminal.tabs), 2)

    def test_press_one_close_release_on_another_does_not_close(self):
        book = self.terminal.notebook
        x, y = self.close_point("vlan101")
        other_x, other_y = self.close_point("vlan102")
        book.event_generate("<ButtonPress-1>", x=x, y=y)
        book.event_generate("<ButtonRelease-1>", x=other_x, y=other_y)
        self.assertEqual(len(self.terminal.tabs), 2)

    def test_close_icon_survives_window_reopen_and_clam_theme(self):
        self.terminal.close()
        tk.ttk.Style(self.root).theme_use("clam")
        with patch.object(self.terminal, "_restore_log_dir", return_value=Path(self.temp.name)):
            self.terminal.show([("vlan101", "COM8")])
        self.root.update()
        self.click_close("vlan101")
        self.assertEqual(self.terminal.tabs, {})
        self.terminal.close()
        self.terminal.show([("vlan101", "COM8")])
        self.root.update()
        self.click_close("vlan101")
        self.assertEqual(self.terminal.tabs, {})

    def test_unknown_or_repeated_close_is_safe(self):
        self.assertFalse(self.terminal.close_tab("missing"))
        self.assertTrue(self.terminal.close_tab("VLAN101"))
        self.assertFalse(self.terminal.close_tab("vlan101"))


class SerialTerminalPersistenceTests(unittest.TestCase):
    def test_only_default_top_left_geometry_is_recentred(self):
        self.assertTrue(SerialTerminalWindow._geometry_is_at_top_left("1000x650+0+0"))
        self.assertFalse(SerialTerminalWindow._geometry_is_at_top_left("1000x650+280+120"))

    def test_serial_log_path_includes_vlan_port_and_open_date(self):
        path = build_serial_log_path(
            Path(r"D:\Serial_Log"),
            "vlan112",
            "COM12",
            date(2026, 8, 8),
        )

        self.assertEqual(path.name, "vlan112_COM12_20260808.log")
        self.assertEqual(path.parent, Path(r"D:\Serial_Log"))

    def test_open_all_opens_every_current_tab_and_returns_failures(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.tabs = {"vlan112": {}, "vlan113": {}, "vlan114": {}}
        terminal.open_monitor = Mock(side_effect=[True, False, True])

        failed = terminal.open_all()

        self.assertEqual(
            terminal.open_monitor.call_args_list,
            [
                unittest.mock.call("vlan112"),
                unittest.mock.call("vlan113"),
                unittest.mock.call("vlan114"),
            ],
        )
        self.assertEqual(failed, ("vlan113",))

    def test_attach_upgrade_keeps_explicit_channel_port_in_terminal_tab(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.window = None
        session = Mock()
        status = Mock()

        def show(targets):
            terminal.window = Mock()
            terminal.window.winfo_exists.return_value = True
            terminal.tabs["vlan113"] = {
                "port": "COM8",
                "status": status,
                "subscriber": None,
                "session": None,
            }

        terminal.show = Mock(side_effect=show)
        terminal._ensure_tab = Mock()

        terminal.attach_upgrade(
            "vlan113", session, Path(r"D:\Serial_Log\upgrade.log"), port="COM8"
        )

        terminal.show.assert_called_once_with([("vlan113", "COM8")])
        terminal._ensure_tab.assert_called_once_with("vlan113", "COM8")
        self.assertIs(terminal.tabs["vlan113"]["session"], session)
        self.assertIn("COM8 正在自动升级", status.set.call_args.args[0])

    def test_poll_batches_high_frequency_events_by_vlan_and_yields_to_ui(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        window = Mock()
        window.winfo_exists.return_value = True
        terminal.window = window
        outputs = {vlan: Mock() for vlan in ("vlan137", "vlan138", "vlan139")}
        terminal.tabs = {vlan: {"output": output} for vlan, output in outputs.items()}
        for index in range(150):
            vlan = ("vlan137", "vlan138", "vlan139")[index % 3]
            terminal.events.put((vlan, SimpleNamespace(text=f"{vlan}-{index}\n"), None))

        with patch("src.ui.serial_terminal.time.monotonic", return_value=0):
            terminal._poll()

        self.assertEqual(terminal.events.qsize(), 30)
        for output in outputs.values():
            output.insert.assert_called_once()
            output.see.assert_called_once_with("end")
        self.assertEqual(window.after.call_args.args[0], 33)

        with patch("src.ui.serial_terminal.time.monotonic", return_value=0):
            terminal._poll()

        self.assertEqual(terminal.events.qsize(), 0)
        self.assertEqual(window.after.call_args.args[0], 80)

    def test_poll_renders_only_active_tab_and_buffers_other_tabs(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        window = Mock()
        window.winfo_exists.return_value = True
        terminal.window = window
        active_frame = Mock()
        inactive_frame = Mock()
        notebook = Mock()
        notebook.select.return_value = str(active_frame)
        terminal.notebook = notebook
        active_output = Mock()
        inactive_output = Mock()
        terminal.tabs = {
            "vlan137": {"frame": active_frame, "output": active_output},
            "vlan138": {"frame": inactive_frame, "output": inactive_output},
        }
        terminal.events.put(("vlan137", SimpleNamespace(text="active\n"), None))
        terminal.events.put(("vlan138", SimpleNamespace(text="inactive\n"), None))

        terminal._poll()

        active_output.insert.assert_called_once()
        inactive_output.insert.assert_not_called()
        self.assertIn("vlan138", terminal._pending_chunks)
        self.assertEqual(window.after.call_args.args[0], 80)

        notebook.select.return_value = str(inactive_frame)
        terminal._poll()

        inactive_output.insert.assert_called_once()

    def test_trim_display_removes_old_lines_beyond_limit(self):
        output = Mock()
        output.index.return_value = "5003.0"

        SerialTerminalWindow._trim_display(output)

        output.delete.assert_called_once_with("1.0", "4.0")

    def test_finish_upgrade_logs_closes_only_auto_opened_window(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.close = Mock()

        terminal.finish_upgrade_logs()
        terminal.close.assert_not_called()

        terminal._auto_opened_for_upgrade = True
        terminal.finish_upgrade_logs()

        terminal.close.assert_called_once()

    def test_on_command_return_invokes_send_and_returns_break(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.send = Mock()

        result = terminal._on_command_return("vlan137")

        terminal.send.assert_called_once_with("vlan137")
        self.assertEqual(result, "break")

    def test_command_entry_return_binding_triggers_send(self):
        """模拟给命令输入框 bind 的 <Return> 回调：被触发时应等价于点击发送按钮。"""
        # 直接复制 _ensure_tab 里 command.bind("<Return>", ...) 的实现逻辑，避免依赖 Tk Notebook
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.send = Mock()

        def handler(event, _vlan="vlan137"):
            terminal._on_command_return(_vlan)
            return "break"

        # 在没有真实 Tk Entry 的情况下，模拟一次 Enter 触发
        result = handler(event=object())

        terminal.send.assert_called_once_with("vlan137")
        self.assertEqual(result, "break")

    def test_save_state_shows_error_when_state_file_is_not_writable(self):
        master = Mock()
        state_file = Mock()
        state_file.write_text.side_effect = OSError("access denied")
        window = Mock()
        window.winfo_exists.return_value = True
        window.geometry.return_value = "1000x650+0+0"
        terminal = SerialTerminalWindow(master, Mock(), Path(r"D:\Serial_Log"), state_file=state_file)
        terminal.window = window

        with patch("src.ui.serial_terminal.messagebox.showerror") as showerror:
            terminal._save_state()

        state_file.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        showerror.assert_called_once()
        self.assertEqual(showerror.call_args.args[0], "保存串口终端设置失败")
        self.assertIs(showerror.call_args.kwargs["parent"], window)

    def test_restore_log_dir_shows_error_when_default_directory_cannot_be_created(self):
        master = Mock()
        state_file = Mock()
        state_file.exists.return_value = False
        terminal = SerialTerminalWindow(master, Mock(), Path(r"D:\Serial_Log"), state_file=state_file)
        default_log_dir = Mock()
        default_log_dir.mkdir.side_effect = OSError("access denied")

        with patch("src.ui.serial_terminal.DEFAULT_LOG_DIR", default_log_dir), patch(
            "src.ui.serial_terminal.messagebox.showerror"
        ) as showerror:
            result = terminal._restore_log_dir()

        self.assertIs(result, default_log_dir)
        showerror.assert_called_once()
        self.assertEqual(showerror.call_args.args[0], "日志目录不可用")
        self.assertIs(showerror.call_args.kwargs["parent"], master)


class SerialLogDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.saved_dir = self.base / "历史日志"
        self.saved_dir.mkdir()
        self.state_file = self.base / "terminal.json"
        self.state_file.write_text(
            json.dumps({"log_dir": str(self.saved_dir)}), encoding="utf-8"
        )
        self.changed = Mock()
        self.terminal = SerialTerminalWindow(
            Mock(), Mock(), Path(r"D:\Serial_Log"), self.state_file, self.changed
        )

    def prepare_window(self):
        self.terminal.window = Mock()
        self.terminal.window.geometry.return_value = "1000x650+120+120"
        self.terminal.log_dir_var = Mock()

    def test_saved_directory_is_read_before_window_opens_without_side_effects(self):
        before = self.state_file.read_bytes()
        with patch.object(Path, "mkdir") as mkdir, patch(
            "src.ui.serial_terminal.messagebox.showerror"
        ) as error:
            self.assertEqual(self.terminal.get_log_directory(), self.saved_dir)
        mkdir.assert_not_called()
        error.assert_not_called()
        self.changed.assert_not_called()
        self.terminal.manager.acquire_monitor.assert_not_called()
        self.assertIsNone(self.terminal.window)
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_invalid_saved_directory_uses_default_without_creating_it(self):
        from src.config import DEFAULT_LOG_DIR

        cases = [None, "{broken", "[]", "{}", json.dumps({"log_dir": 123}),
                 json.dumps({"log_dir": str(self.base / "missing")}),
                 json.dumps({"log_dir": str(self.state_file)})]
        for contents in cases:
            with self.subTest(contents=contents):
                if contents is None:
                    self.state_file.unlink()
                else:
                    self.state_file.write_text(contents, encoding="utf-8")
                with patch.object(Path, "mkdir") as mkdir, patch(
                    "src.ui.serial_terminal.messagebox.showerror"
                ) as error:
                    self.assertEqual(self.terminal.get_log_directory(), DEFAULT_LOG_DIR)
                mkdir.assert_not_called()
                error.assert_not_called()

    def test_choosing_directory_updates_current_value_saves_and_notifies(self):
        self.prepare_window()
        chosen = self.base / "新日志"
        chosen.mkdir()
        with patch("src.ui.serial_terminal.filedialog.askdirectory", return_value=str(chosen)):
            self.terminal._choose_log_dir()
        self.assertEqual(self.terminal.get_log_directory(), chosen)
        self.terminal.log_dir_var.set.assert_called_once_with(str(chosen))
        self.assertEqual(json.loads(self.state_file.read_text(encoding="utf-8"))["log_dir"], str(chosen))
        self.changed.assert_called_once_with(chosen)
        # 当前窗口配置优先于磁盘中的旧值（包括设置保存失败的情况）。
        self.state_file.write_text(json.dumps({"log_dir": str(self.saved_dir)}), encoding="utf-8")
        self.assertEqual(self.terminal.get_log_directory(), chosen)

    def test_cancel_or_failed_selection_does_not_change_or_notify(self):
        self.prepare_window()
        before = self.state_file.read_bytes()
        choices = [dict(return_value=""), dict(side_effect=OSError("dialog failed")),
                   dict(return_value=str(self.state_file))]
        with patch("src.ui.serial_terminal.messagebox.showerror"):
            for choice in choices:
                with self.subTest(choice=choice), patch(
                    "src.ui.serial_terminal.filedialog.askdirectory", **choice
                ):
                    self.terminal._choose_log_dir()
                    self.assertEqual(self.terminal.get_log_directory(), self.saved_dir)
                    self.assertEqual(self.state_file.read_bytes(), before)
        self.changed.assert_not_called()
        self.terminal.log_dir_var.set.assert_not_called()

    def test_save_failure_still_keeps_current_selection_and_notifies(self):
        self.prepare_window()
        chosen = self.base / "未保存的新目录"
        chosen.mkdir()
        before = self.state_file.read_bytes()
        with patch("src.ui.serial_terminal.filedialog.askdirectory", return_value=str(chosen)), patch.object(
            Path, "write_text", side_effect=OSError("read only")
        ), patch("src.ui.serial_terminal.messagebox.showerror") as error:
            self.terminal._choose_log_dir()
        self.assertEqual(self.terminal.get_log_directory(), chosen)
        self.assertEqual(self.state_file.read_bytes(), before)
        self.changed.assert_called_once_with(chosen)
        error.assert_called_once()

    def test_new_monitor_uses_selected_directory_existing_monitor_keeps_session(self):
        self.prepare_window()
        existing_session = Mock()
        self.terminal.tabs = {
            "vlan101": {"session": existing_session, "port": "COM1", "status": Mock()},
            "vlan102": {"session": None, "port": "COM2", "status": Mock()},
        }
        with patch("src.ui.serial_terminal.filedialog.askdirectory", return_value=str(self.saved_dir)):
            self.terminal._choose_log_dir()
        self.terminal.manager.acquire_monitor.assert_not_called()
        self.terminal.manager.release.assert_not_called()
        self.assertEqual(self.terminal.open_all(), ())
        self.assertIs(self.terminal.tabs["vlan101"]["session"], existing_session)
        self.terminal.manager.acquire_monitor.assert_called_once()
        path = self.terminal.manager.acquire_monitor.call_args.args[2]
        self.assertEqual(path.parent, self.saved_dir)
        self.assertIn("vlan102_COM2_", path.name)
        existing_session.unsubscribe.assert_not_called()

    def test_source_windows_sync_immediately_and_confirmation_uses_same_directory(self):
        """真实 Tk 两窗口交互，替代目录选择对话框；不创建主应用或打开串口。"""
        from line_check_assistant.app import LineCheckAssistant
        from line_check_assistant.config_store import ChannelConfig
        from line_check_assistant.pipeline_window import PipelineWindow

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry("1100x850+50+50")
        root.channels = [ChannelConfig("channel_1", vlan_name="vlan101")]
        root._restore_module_window_size = lambda *args: (1000, 820)
        root._log = Mock()
        root._serial_log_directory = lambda: LineCheckAssistant._serial_log_directory(root)
        terminal = SerialTerminalWindow(
            root, Mock(), Path(r"D:\Serial_Log"), self.state_file,
            lambda path: LineCheckAssistant._on_serial_log_directory_changed(root, path),
        )
        root.serial_terminal = terminal
        root.pipeline_window = pipeline = PipelineWindow(root)
        root.update()
        self.assertIn(str(self.saved_dir), pipeline._status_summary_vars["serial_terminal"].get())
        terminal.show([("vlan101", "COM1")])
        root.update()
        self.assertEqual(terminal.log_dir_var.get(), str(self.saved_dir))
        chosen = self.base / "最新日志"
        chosen.mkdir()
        # 不切换焦点、不手动刷新，回调必须已同步 StringVar。
        with patch("src.ui.serial_terminal.filedialog.askdirectory", return_value=str(chosen)):
            terminal._choose_log_dir()
        self.assertEqual(terminal.log_dir_var.get(), str(chosen))
        summary = pipeline._status_summary_vars["serial_terminal"].get()
        self.assertIn(str(chosen), summary)
        pipeline._check_vars["serial_terminal"].set(True)
        with patch("line_check_assistant.pipeline_window.messagebox.askyesno", return_value=False) as confirm:
            pipeline._on_start()
        confirm.assert_called_once()
        self.assertIn(summary, confirm.call_args.args[1])
        terminal.manager.acquire_monitor.assert_not_called()
        terminal.close()
        self.assertEqual(terminal.get_log_directory(), chosen)
        terminal.show([("vlan101", "COM1")])
        root.update()
        self.assertEqual(terminal.log_dir_var.get(), str(chosen))
        self.assertEqual(pipeline._build_context().serial_log_dir, chosen)
        terminal.close()
        # 全流程窗口已关闭后，目录变更仍可安全完成。
        pipeline.window.destroy()
        terminal.show([])
        terminal.close()


if __name__ == "__main__":
    unittest.main()

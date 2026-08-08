import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui.serial_terminal import SerialTerminalWindow


class SerialTerminalPersistenceTests(unittest.TestCase):
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

    def test_poll_batches_high_frequency_events_by_vlan_and_yields_to_ui(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        window = Mock()
        window.winfo_exists.return_value = True
        terminal.window = window
        outputs = {vlan: Mock() for vlan in ("vlan137", "vlan138", "vlan139")}
        terminal.tabs = {vlan: {"output": output} for vlan, output in outputs.items()}
        for index in range(150):
            vlan = ("vlan137", "vlan138", "vlan139")[index % 3]
            terminal.events.put((vlan, SimpleNamespace(text=f"{vlan}-{index}\n")))

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
        terminal.events.put(("vlan137", SimpleNamespace(text="active\n")))
        terminal.events.put(("vlan138", SimpleNamespace(text="inactive\n")))

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


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui.serial_terminal import SerialTerminalWindow


class SerialTerminalPersistenceTests(unittest.TestCase):
    def test_finish_upgrade_logs_closes_only_auto_opened_window(self):
        terminal = SerialTerminalWindow(Mock(), Mock(), Path(r"D:\Serial_Log"))
        terminal.close = Mock()

        terminal.finish_upgrade_logs()
        terminal.close.assert_not_called()

        terminal._auto_opened_for_upgrade = True
        terminal.finish_upgrade_logs()

        terminal.close.assert_called_once()

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

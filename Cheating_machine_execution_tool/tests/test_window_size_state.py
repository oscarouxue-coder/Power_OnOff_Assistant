import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.app import MODULE_WINDOW_SIZE_SPECS, LineCheckAssistant
from src.ui.window_size_state import (
    clamp_module_window_size,
    load_module_window_size,
    save_module_window_size,
)
from tk_test_windows import install_offscreen_windows


class ModuleWindowSizeStateTests(unittest.TestCase):
    def test_sample_upgrade_minimum_size_is_820_by_620(self):
        self.assertEqual(
            MODULE_WINDOW_SIZE_SPECS["sample_upgrade"], (820, 720, 820, 620)
        )

    def test_save_and_load_keep_each_module_size_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "module-window-sizes.json"

            self.assertTrue(
                save_module_window_size(
                    path,
                    "sample_upgrade",
                    1080,
                    720,
                    default_width=820,
                    default_height=580,
                    min_width=760,
                    min_height=530,
                )
            )
            self.assertTrue(
                save_module_window_size(
                    path,
                    "onu_registration",
                    1440,
                    960,
                    default_width=1000,
                    default_height=900,
                    min_width=1000,
                    min_height=900,
                )
            )

            self.assertEqual(
                load_module_window_size(
                    path,
                    "sample_upgrade",
                    default_width=820,
                    default_height=580,
                    min_width=760,
                    min_height=530,
                    screen_width=1920,
                    screen_height=1080,
                ),
                (1080, 720),
            )
            self.assertEqual(
                load_module_window_size(
                    path,
                    "onu_registration",
                    default_width=1000,
                    default_height=900,
                    min_width=1000,
                    min_height=900,
                    screen_width=1920,
                    screen_height=1080,
                ),
                (1440, 960),
            )

    def test_load_clamps_saved_size_and_invalid_data_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "module-window-sizes.json"
            path.write_text(
                '{"window_sizes":{"sample_upgrade":{"width":9999,"height":"bad"}}}',
                encoding="utf-8",
            )

            self.assertEqual(
                load_module_window_size(
                    path,
                    "sample_upgrade",
                    default_width=820,
                    default_height=580,
                    min_width=760,
                    min_height=530,
                    screen_width=1366,
                    screen_height=768,
                ),
                (1366, 580),
            )
            self.assertEqual(
                clamp_module_window_size(
                    100,
                    100,
                    default_width=820,
                    default_height=580,
                    min_width=760,
                    min_height=530,
                ),
                (760, 530),
            )

    def test_app_restores_and_remembers_window_size_without_recording_position(self):
        class FakeWindow:
            def __init__(self):
                self.geometry_calls = []

            def winfo_screenwidth(self):
                return 1920

            def winfo_screenheight(self):
                return 1080

            def geometry(self, value):
                self.geometry_calls.append(value)

            def update_idletasks(self):
                return None

            def winfo_width(self):
                return 1090

            def winfo_height(self):
                return 710

        with tempfile.TemporaryDirectory() as directory:
            app = object.__new__(LineCheckAssistant)
            app._module_window_size_state_path = Path(directory) / "module-window-sizes.json"
            window = FakeWindow()

            self.assertTrue(
                LineCheckAssistant._remember_module_window_size(
                    app, window, "sample_upgrade"
                )
            )
            self.assertEqual(
                LineCheckAssistant._restore_module_window_size(
                    app, window, "sample_upgrade"
                ),
                (1090, 710),
            )
            self.assertEqual(window.geometry_calls, ["1090x710"])


class PowerTestHistoryWindowStateTests(unittest.TestCase):
    def setUp(self):
        install_offscreen_windows(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state_path = Path(directory.name) / "window-sizes.json"
        self.app = self.make_app()

    def make_app(self):
        app = tk.Tk()
        self.addCleanup(lambda: (app.update_idletasks(), app.destroy()))
        app.geometry("1000x700")
        app._module_window_size_state_path = self.state_path
        app.power_test_channel_history_window = None
        app.power_test_channel_history_text = None
        app.power_test_channel_history_title_var = tk.StringVar(app)
        app.power_test_channel_histories = {1: [(1, "retry", "第一次重试")], 2: []}
        app.power_test_channel_states = {}
        app.power_test_channel_progresses = {}
        app.channels = []
        for name in (
            "_restore_module_window_size", "_remember_module_window_size",
            "_open_power_test_channel_history_window",
            "_close_power_test_channel_history_window",
            "_refresh_power_test_channel_history_window",
        ):
            setattr(app, name, MethodType(getattr(LineCheckAssistant, name), app))
        app.update_idletasks()
        return app

    def open_history(self, channel=1, app=None):
        app = app or self.app
        app._open_power_test_channel_history_window(channel)
        app.update_idletasks()
        return app.power_test_channel_history_window

    def test_first_open_is_non_modal_owned_window_with_existing_default_size(self):
        window = self.open_history()
        self.assertEqual((window.winfo_width(), window.winfo_height()), (760, 440))
        self.assertEqual(window.minsize(), (560, 300))
        self.assertEqual(str(window.transient()), str(self.app))
        self.assertFalse(bool(window.attributes("-topmost")))
        self.assertIsNone(window.grab_current())
        self.assertEqual(window.cget("background"), "#eef2f5")
        LineCheckAssistant._bring_main_window_to_front(self.app)
        self.assertEqual(str(window.transient()), str(self.app))
        self.assertIn("第一次重试", self.app.power_test_channel_history_text.get("1.0", "end"))

    def test_close_button_and_titlebar_both_save_size_and_restore_for_other_channel(self):
        for close_method, size in (("button", (900, 510)), ("titlebar", (880, 490))):
            with self.subTest(close_method=close_method):
                window = self.open_history()
                window.geometry(f"{size[0]}x{size[1]}")
                window.update_idletasks()
                if close_method == "button":
                    container = window.winfo_children()[0]
                    button = next(child for child in container.winfo_children()
                                  if child.winfo_class() == "TButton")
                    button.invoke()
                else:
                    self.app.tk.call(window.protocol("WM_DELETE_WINDOW"))
                self.assertFalse(window.winfo_exists())
                self.assertIsNone(self.app.power_test_channel_history_text)
                restored = self.open_history(channel=2)
                self.assertEqual((restored.winfo_width(), restored.winfo_height()), size)
                self.app._close_power_test_channel_history_window()

    def test_switching_channel_reuses_window_without_resetting_size_or_history(self):
        window = self.open_history()
        window.geometry("910x520")
        window.update_idletasks()
        self.assertIs(self.open_history(channel=2), window)
        self.assertEqual((window.winfo_width(), window.winfo_height()), (910, 520))
        self.assertIn("本次未发生重试或失败", self.app.power_test_channel_history_text.get("1.0", "end"))
        self.open_history(channel=1)
        self.assertIn("第一次重试", self.app.power_test_channel_history_text.get("1.0", "end"))

    def test_recreated_app_restores_persisted_size(self):
        window = self.open_history()
        window.geometry("920x530")
        self.app._close_power_test_channel_history_window()
        restored = self.open_history(app=self.make_app())
        self.assertEqual((restored.winfo_width(), restored.winfo_height()), (920, 530))

    def test_reset_closes_history_and_remembers_size(self):
        window = self.open_history()
        window.geometry("930x540")
        LineCheckAssistant._reset_power_test_channel_states(self.app, [1])
        self.assertFalse(window.winfo_exists())
        self.assertNotIn(1, self.app.power_test_channel_histories)
        restored = self.open_history()
        self.assertEqual((restored.winfo_width(), restored.winfo_height()), (930, 540))

    def test_app_exit_closes_history_before_destroying_main_window(self):
        window = self.open_history()
        window.geometry("940x550")
        context = SimpleNamespace(
            power_test_channel_history_window=window,
            _close_power_test_channel_history_window=self.app._close_power_test_channel_history_window,
            onu_save_after_id=None, sample_upgrade_save_after_id=None,
            _save_onu_registration_config=Mock(), _save_sample_upgrade_settings=Mock(),
            destroy=Mock(side_effect=lambda: self.assertFalse(window.winfo_exists())),
        )
        LineCheckAssistant._on_app_close(context)
        context.destroy.assert_called_once_with()
        restored = self.open_history()
        self.assertEqual((restored.winfo_width(), restored.winfo_height()), (940, 550))

    def test_corrupt_state_falls_back_and_failed_save_does_not_block_repeated_close(self):
        self.state_path.write_text("invalid JSON", encoding="utf-8")
        window = self.open_history()
        self.assertEqual((window.winfo_width(), window.winfo_height()), (760, 440))
        with patch("src.ui.window_size_state._save_state", return_value=False):
            self.app._close_power_test_channel_history_window()
        self.app._close_power_test_channel_history_window()
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(self.app.power_test_channel_history_window)


if __name__ == "__main__":
    unittest.main()

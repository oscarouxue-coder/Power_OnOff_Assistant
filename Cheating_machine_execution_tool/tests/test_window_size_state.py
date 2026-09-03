import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.app import MODULE_WINDOW_SIZE_SPECS, LineCheckAssistant
from src.ui.window_size_state import (
    clamp_module_window_size,
    load_module_window_size,
    save_module_window_size,
)


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


if __name__ == "__main__":
    unittest.main()

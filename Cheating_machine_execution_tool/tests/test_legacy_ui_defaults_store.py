from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from line_check_assistant.legacy_ui_defaults_store import LegacyUiDefaultsStore


def _valid_values(**overrides: str) -> dict[str, str]:
    values = {
        "communication_method": "telnet",
        "telnet_enable": "0",
        "baud_rate": "19200",
        "selected_profile": "TEST_PROJECT",
        "startup_time": "240",
        "interval_time": "20",
        "number_of_tests": "500",
        "wait_command_done": "20",
    }
    values.update(overrides)
    return values


class LegacyUiDefaultsStoreTests(unittest.TestCase):
    def test_load_returns_every_ui_defaults_option_including_future_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "communication_method = telnet\n"
                "telnet_enable = 0\n"
                "future_option = keep-me\n"
                "[other]\nvalue = untouched\n",
                encoding="utf-8",
            )

            loaded = LegacyUiDefaultsStore(config_path).load()

        self.assertEqual(
            loaded,
            {
                "communication_method": "telnet",
                "telnet_enable": "0",
                "future_option": "keep-me",
            },
        )

    def test_save_updates_all_values_and_preserves_other_sections_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.ini"
            config_path.write_text(
                "[config]\n"
                "test_project = test_project_config.ini\n\n"
                "[ui_defaults]\n"
                "# keep ui comment\n"
                "communication_method = telnet\n"
                "telnet_enable = 1\n"
                "baud_rate = 9600\n\n"
                "[other]\n"
                "# keep other comment\n"
                "value = untouched\n",
                encoding="utf-8",
            )
            values = _valid_values(future_option="new-value")

            LegacyUiDefaultsStore(config_path).save(values)
            content = config_path.read_text(encoding="utf-8")
            loaded = LegacyUiDefaultsStore(config_path).load()

        self.assertEqual(loaded, values)
        self.assertIn("# keep ui comment", content)
        self.assertIn("# keep other comment", content)
        self.assertIn("value = untouched", content)

    def test_validation_rejects_invalid_known_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LegacyUiDefaultsStore(Path(tmp) / "config.ini")

            with self.assertRaisesRegex(ValueError, "communication_method"):
                store.validate(_valid_values(communication_method="serial"))
            with self.assertRaisesRegex(ValueError, "number_of_tests"):
                store.validate(_valid_values(number_of_tests="0"))

    def test_update_retry_interval_preserves_other_config_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "telnet_enable = 0\n\n"
                "[other_config]\n"
                "# keep retry comment\n"
                "command_fail_retry_interval_time = 60\n"
                "telnet_enable_fail_retry_times = 5\n",
                encoding="utf-8",
            )

            LegacyUiDefaultsStore(config_path).update_command_fail_retry_interval_mirror(10)
            content = config_path.read_text(encoding="utf-8")

        self.assertIn("command_fail_retry_interval_time = 10", content)
        self.assertIn("# keep retry comment", content)
        self.assertIn("telnet_enable_fail_retry_times = 5", content)
        self.assertIn("telnet_enable = 0", content)


if __name__ == "__main__":
    unittest.main()

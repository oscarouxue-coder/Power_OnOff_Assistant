from __future__ import annotations

import sys
import tempfile
import unittest
import configparser
from pathlib import Path
from types import SimpleNamespace


_ROOT = Path(__file__).resolve().parent.parent
_OLD_TOOL_ROOT = _ROOT / "Auto_power_on_off_tool"
if str(_OLD_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_OLD_TOOL_ROOT))

from config.ui_defaults import (  # noqa: E402
    POWER_SERIAL_SOURCE,
    LegacyUiDefaults,
    apply_legacy_power_channel_selection,
    apply_legacy_ui_defaults,
    load_legacy_ui_defaults,
)


class _FakeComboBox:
    def __init__(self, values: list[str]) -> None:
        self.values = list(values)
        self.current_index = 0

    def count(self) -> int:
        return len(self.values)

    def itemText(self, index: int) -> str:
        return self.values[index]

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = index

    def addItem(self, value: str) -> None:
        self.values.append(value)

    def currentText(self) -> str:
        return self.values[self.current_index]


class _FakeToggle:
    def __init__(self) -> None:
        self.checked = False

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class _FakeLineEdit:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


def _fake_window() -> SimpleNamespace:
    return SimpleNamespace(
        radioButton_telnet=_FakeToggle(),
        radioButton_ssh=_FakeToggle(),
        checkBox_telnet_enable=_FakeToggle(),
        comboBox_serial_num=_FakeComboBox(["COM101"]),
        comboBox_band_rate=_FakeComboBox(["19200", "38400"]),
        comboBox_schemes=_FakeComboBox(["请选择配置文件", "TEST_PROJECT"]),
        lineEdit_start_need_times=_FakeLineEdit(),
        lineEdit_interval_time=_FakeLineEdit(),
        lineEdit_test_number=_FakeLineEdit(),
        lineEdit_wait_command_done=_FakeLineEdit(),
        channel_box_list=[_FakeToggle() for _index in range(16)],
    )


class LegacyUiDefaultsTests(unittest.TestCase):
    def test_current_config_contains_all_legacy_ui_defaults(self) -> None:
        defaults = load_legacy_ui_defaults(
            _OLD_TOOL_ROOT / "config" / "config.ini"
        )

        self.assertEqual(defaults.communication_method, "telnet")
        self.assertFalse(defaults.telnet_enable)
        power_parser = configparser.RawConfigParser()
        power_parser.read(
            _OLD_TOOL_ROOT / "config" / "network_card_ip.ini",
            encoding="utf-8",
        )
        self.assertEqual(
            defaults.serial_num,
            power_parser.get("power_supply", "serial_port").strip().upper(),
        )
        self.assertEqual(defaults.serial_num_source, POWER_SERIAL_SOURCE)
        self.assertEqual(defaults.baud_rate, "19200")
        self.assertEqual(defaults.selected_profile, "TEST_PROJECT")
        self.assertEqual(defaults.startup_time, 240)
        self.assertEqual(defaults.interval_time, 20)
        self.assertEqual(defaults.number_of_tests, 500)
        self.assertEqual(defaults.wait_command_done, 20)

    def test_apply_loads_every_configured_value_into_ui(self) -> None:
        window = _fake_window()
        defaults = LegacyUiDefaults(
            communication_method="ssh",
            telnet_enable=False,
            serial_num="COM105",
            baud_rate="115200",
            selected_profile="test_project",
            startup_time=240,
            interval_time=20,
            number_of_tests=500,
            wait_command_done=20,
        )

        apply_legacy_ui_defaults(window, defaults)

        self.assertFalse(window.radioButton_telnet.checked)
        self.assertTrue(window.radioButton_ssh.checked)
        self.assertFalse(window.checkBox_telnet_enable.checked)
        self.assertEqual(window.comboBox_serial_num.currentText(), "COM105")
        self.assertEqual(window.comboBox_band_rate.currentText(), "115200")
        self.assertEqual(window.comboBox_schemes.currentText(), "TEST_PROJECT")
        self.assertEqual(window.lineEdit_start_need_times.text, "240")
        self.assertEqual(window.lineEdit_interval_time.text, "20")
        self.assertEqual(window.lineEdit_test_number.text, "500")
        self.assertEqual(window.lineEdit_wait_command_done.text, "20")

    def test_new_tool_power_serial_port_is_the_only_legacy_com_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            config_path = config_dir / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "communication_method = telnet\n"
                "telnet_enable = 1\n"
                "serial_num = COM105\n"
                "baud_rate = 19200\n"
                "selected_profile = TEST_PROJECT\n"
                "startup_time = 240\n"
                "interval_time = 20\n"
                "number_of_tests = 500\n"
                "wait_command_done = 20\n",
                encoding="utf-8",
            )
            (config_dir / "network_card_ip.ini").write_text(
                "[power_supply]\nserial_port = com102\n",
                encoding="utf-8",
            )

            defaults = load_legacy_ui_defaults(config_path)

        self.assertEqual(defaults.serial_num, "COM102")
        self.assertEqual(defaults.serial_num_source, POWER_SERIAL_SOURCE)

    def test_legacy_serial_num_is_empty_when_new_tool_has_no_com(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            config_path = config_dir / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "communication_method = telnet\n"
                "telnet_enable = 1\n"
                "serial_num = COM105\n"
                "baud_rate = 19200\n"
                "selected_profile = TEST_PROJECT\n"
                "startup_time = 240\n"
                "interval_time = 20\n"
                "number_of_tests = 500\n"
                "wait_command_done = 20\n",
                encoding="utf-8",
            )
            (config_dir / "network_card_ip.ini").write_text(
                "[power_supply]\nserial_port =\n",
                encoding="utf-8",
            )

            defaults = load_legacy_ui_defaults(config_path)

        self.assertEqual(defaults.serial_num, "")
        self.assertEqual(defaults.serial_num_source, POWER_SERIAL_SOURCE)
        window = _fake_window()
        apply_legacy_ui_defaults(window, defaults)
        self.assertEqual(window.comboBox_serial_num.currentText(), "")

    def test_power_channel_selection_matches_new_tool_enabled_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            config_path = config_dir / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "communication_method = telnet\n"
                "telnet_enable = 1\n"
                "baud_rate = 19200\n"
                "selected_profile = TEST_PROJECT\n"
                "startup_time = 240\n"
                "interval_time = 20\n"
                "number_of_tests = 500\n"
                "wait_command_done = 20\n",
                encoding="utf-8",
            )
            (config_dir / "network_card_ip.ini").write_text(
                "[power_supply]\n"
                "serial_port = COM102\n"
                "[channel_2]\n"
                "enabled = 1\n"
                "[channel_5]\n"
                "enabled = 0\n"
                "[channel_16]\n",
                encoding="utf-8",
            )

            defaults = load_legacy_ui_defaults(config_path)

        self.assertEqual(defaults.enabled_power_channels, (2, 16))
        window = _fake_window()
        for check_box in window.channel_box_list:
            check_box.setChecked(True)
        apply_legacy_power_channel_selection(window, defaults)
        self.assertEqual(
            [check_box.checked for check_box in window.channel_box_list],
            [False, True, *([False] * 13), True],
        )

    def test_telnet_enable_is_inverse_of_new_tool_telnet_default_on(self) -> None:
        for telnet_default_on, expected_telnet_enable in ((1, False), (0, True)):
            with self.subTest(telnet_default_on=telnet_default_on):
                with tempfile.TemporaryDirectory() as tmp:
                    config_dir = Path(tmp)
                    config_path = config_dir / "config.ini"
                    config_path.write_text(
                        "[ui_defaults]\n"
                        "communication_method = telnet\n"
                        "telnet_enable = 1\n"
                        "baud_rate = 19200\n"
                        "selected_profile = TEST_PROJECT\n"
                        "startup_time = 240\n"
                        "interval_time = 20\n"
                        "number_of_tests = 500\n"
                        "wait_command_done = 20\n",
                        encoding="utf-8",
                    )
                    (config_dir / "test_project_config.ini").write_text(
                        f"[telnet]\ntelnet_default_on = {telnet_default_on}\n",
                        encoding="utf-8",
                    )

                    defaults = load_legacy_ui_defaults(config_path)

                self.assertEqual(defaults.telnet_enable, expected_telnet_enable)

    def test_invalid_communication_method_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.ini"
            config_path.write_text(
                "[ui_defaults]\n"
                "communication_method = serial\n"
                "telnet_enable = 1\n"
                "serial_num = COM105\n"
                "baud_rate = 19200\n"
                "selected_profile = TEST_PROJECT\n"
                "startup_time = 240\n"
                "interval_time = 20\n"
                "number_of_tests = 500\n"
                "wait_command_done = 20\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "telnet 或 ssh"):
                load_legacy_ui_defaults(config_path)

    def test_telnet_retry_interval_does_not_overwrite_power_cycle_interval(self) -> None:
        source = (
            _OLD_TOOL_ROOT / "test_case" / "powe_on_off_telnet.py"
        ).read_text(encoding="utf-8")

        self.assertIn("self.telnet_enable_fail_retry_interval = int(", source)
        self.assertIn("interval_time = self.telnet_enable_fail_retry_interval", source)
        self.assertNotIn(
            "self.interval_time = int(\n"
            "                self.cf.read_ini('other_config', 'telnet_enable_fail_retry_interval'",
            source,
        )


if __name__ == "__main__":
    unittest.main()

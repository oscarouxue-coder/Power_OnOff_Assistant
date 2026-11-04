"""配置兼容、真实Tk控件交互与正式请求映射；不启动主程序或设备流程。"""
from dataclasses import replace
from pathlib import Path
import gc
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock

from line_check_assistant.test_item_config_store import ConnectWifiSettings, TestItemConfigStore, TestProjectConfig
from src.models.wifi_test_models import WifiTestOptions
from src.services.wifi_connection_service import validate_wifi_options
from src.services import legacy_power_test_service as legacy
from test_legacy_power_test_service import _write_config_tree


class WifiConfigTests(unittest.TestCase):
    def test_legacy_config_defaults_do_not_write_files_or_change_old_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.ini'
            original = '[connect_wifi]\nenable=1\ntest_2g_enable=0\nauth_mode=WPA3-PSK\n'
            path.write_text(original, encoding='utf-8')
            wifi = TestItemConfigStore(path).load().connect_wifi
            self.assertEqual((wifi.connection_test_mode, wifi.security_source, wifi.wireless_ping_enable,
                              wifi.wireless_ping_target), ('per_band', 'auto', 0, ''))
            self.assertEqual((wifi.test_2g_enable, wifi.auth_mode), (0, 'WPA3-PSK'))
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_new_settings_roundtrip_preserves_disabled_ping_target_and_manual_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TestItemConfigStore(Path(directory) / 'project.ini')
            wifi = ConnectWifiSettings(connection_test_mode='unified', security_source='auto',
                                       auth_mode='WPA3-PSK', wireless_ping_enable=False,
                                       wireless_ping_target='example.test')
            store.save(TestProjectConfig(connect_wifi=wifi))
            self.assertEqual(store.load().connect_wifi, wifi)

    def test_form_fields_reach_formal_request_and_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _write_config_tree(Path(directory))
            path = root / 'config' / 'test_project_config.ini'
            with path.open('a', encoding='utf-8') as file:
                file.write('\nconnection_test_mode=unified\nsecurity_source=manual\nwireless_ping_enable=1\n'
                           'wireless_ping_target=example.test\n')
            request = legacy.prepare_legacy_power_test_request(root, (legacy.LegacyPowerChannel(5, '192.0.2.2'),))
            self.assertEqual((request.wifi_connection_test_mode, request.wifi_security_source,
                              request.wireless_ping_enable, request.wireless_ping_target),
                             ('unified', 'manual', True, 'example.test'))
            self.assertIn('example.test', legacy.wifi_request_summary(request))
            self.assertIn('断开', legacy.wifi_request_summary(request))

    def test_formal_request_rejects_unsupported_solution_and_invalid_enabled_ping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _write_config_tree(Path(directory))
            path = root / 'config' / 'test_project_config.ini'
            initial = path.read_text(encoding='utf-8')
            for text in (initial.replace('openwrt', 'bcm'), initial + '\nwireless_ping_enable=1\n'):
                path.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    legacy.prepare_legacy_power_test_request(root, (legacy.LegacyPowerChannel(5, '192.0.2.2'),))


class WifiControlsTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.geometry('1060x680')
        self.book = ttk.Notebook(self.root)
        self.book.pack(fill='both', expand=True)
        from line_check_assistant.app import LineCheckAssistant
        owner = type('Owner', (), {'_log': lambda *_: None})()
        self.dirty = []
        self.control = LineCheckAssistant._build_test_item_wifi_tab(
            owner, self.book, ConnectWifiSettings(), lambda: self.dirty.append(True))
        self.extra = self.control['extra_controls']
        self.frame = self.book.nametowidget(self.book.tabs()[0])

    def tearDown(self):
        self.root.destroy()
        self.control = self.extra = self.frame = self.book = self.root = None
        gc.collect()

    def test_native_checks_mode_switch_preserves_band_selections(self):
        wifi = ConnectWifiSettings(test_2g_enable=0, test_5g_enable=1)
        self.control['load'](wifi)
        self.extra.mode.set('合一网络接入（任一频段）')
        connection_frame = next(child for child in self.frame.winfo_children()
                                if isinstance(child, tk.Frame) and len(child.winfo_children()) == 3)
        band_checks = connection_frame.winfo_children()[1:]
        self.assertTrue(all(isinstance(widget, tk.Checkbutton) for widget in band_checks))
        self.assertTrue(all(str(widget.cget('state')) == 'disabled' for widget in band_checks))
        self.extra.mode.set('分别验证频段')
        captured = self.control['capture']()
        self.assertEqual((captured.test_2g_enable, captured.test_5g_enable), (0, 1))
        self.assertTrue(all(str(widget.cget('state')) == 'normal' for widget in band_checks))

    def test_auto_manual_and_ping_toggle_keep_values_on_reload(self):
        settings = ConnectWifiSettings(enable=1, auth_mode='WPA3-PSK', cipher='AES',
                                       wireless_ping_target='example.test')
        self.control['load'](settings)
        self.assertEqual(str(self.extra.target_entry.cget('state')), 'disabled')
        self.extra.auto.set(0)
        self.extra.ping.set(1)
        captured = self.control['capture']()
        self.assertEqual((captured.security_source, captured.auth_mode, captured.wireless_ping_enable),
                         ('manual', 'WPA3-PSK', 1))
        self.assertEqual(str(self.extra.target_entry.cget('state')), 'normal')
        self.extra.auto.set(1)
        self.extra.ping.set(0)
        captured = self.control['capture']()
        self.assertEqual((captured.auth_mode, captured.wireless_ping_target), ('WPA3-PSK', 'example.test'))
        self.control['load'](captured)
        self.assertEqual(self.control['capture'](), captured)

    def test_enabled_ping_requires_target_but_master_off_can_keep_empty(self):
        self.control['load'](ConnectWifiSettings(enable=1, wireless_ping_enable=1))
        with self.assertRaises(ValueError):
            self.control['capture']()
        self.control['load'](ConnectWifiSettings(enable=0, wireless_ping_enable=1))
        self.assertEqual(self.control['capture']().wireless_ping_target, '')

    def test_added_controls_fit_configuration_tab_without_showing_device_windows(self):
        self.root.update_idletasks()
        self.assertLess(self.frame.winfo_reqheight(), 560)
        self.assertLess(self.frame.winfo_reqwidth(), 1100)


if __name__ == '__main__':
    unittest.main()

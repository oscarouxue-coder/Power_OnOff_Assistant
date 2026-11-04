"""全部网卡/串口模式：只读枚举、真实源码UI联动与配置兼容回归。"""
import inspect
import gc
import queue
import re
import sys
import tempfile
import unittest
from pathlib import Path
from tkinter import BooleanVar, Checkbutton, StringVar, Tk, Toplevel, ttk
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.core.serial_inventory import list_serial_port_names, normalize_com_port


class SerialInventoryTests(unittest.TestCase):
    def test_all_brands_large_numbers_sort_and_deduplicate(self):
        ports = [
            SimpleNamespace(device=name, manufacturer=brand)
            for name, brand in (
                ("COM1200", "FTDI"), ("COM10", "CH340"), ("com2", "Prolific"),
                ("COM2", None), ("COM106", "Bluetooth"), ("LPT1", None),
                ("", None), ("COM0", None), ("COM-1", None),
            )
        ]
        self.assertEqual(list_serial_port_names(lambda: ports), ["COM2", "COM10", "COM106", "COM1200"])

    def test_default_provider_is_pyserial_and_never_opens_a_port(self):
        with patch("serial.tools.list_ports.comports", return_value=[SimpleNamespace(device="COM99")]) as ports, \
                patch("serial.Serial") as serial:
            self.assertEqual(list_serial_port_names(), ["COM99"])
        ports.assert_called_once_with()
        serial.assert_not_called()

    def test_empty_and_failure_are_distinct(self):
        self.assertEqual(list_serial_port_names(lambda: []), [])
        with self.assertRaisesRegex(OSError, "枚举失败"):
            list_serial_port_names(Mock(side_effect=OSError("枚举失败")))

    def test_saved_com_round_trip_including_nonstandard_power_number(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ChannelConfigStore(Path(folder) / "network_card_ip.ini")
            channel = ChannelConfig(section="channel_1", enabled=True, vlan_name="VLAN101", serial_port="COM1200")
            store.save([channel], "COM77")
            self.assertEqual(normalize_com_port(store.load_power_serial_port()), "COM77")
            self.assertEqual(store.load()[0].serial_port, "COM1200")
            store.save([channel], "")
            self.assertEqual(normalize_com_port(store.load_power_serial_port()), "")
        for value, expected in ((" com0077 ", "COM77"), ("invalid", ""), ("COM0", "")):
            self.assertEqual(normalize_com_port(value), expected)
        # 启动必须读取有效编号，不能再因为不在固定候选中重置。
        source = inspect.getsource(LineCheckAssistant.__init__)
        self.assertIn("normalize_com_port(self.store.load_power_serial_port())", source)
        self.assertNotIn("self.power_serial_port not in self.power_serial_options", source)


class ResourceOptionsTkTests(unittest.TestCase):
    def setUp(self):
        # 复用真实主界面装配和相关回调；跳过应用初始化，不访问本机配置/设备。
        self.root = Tk()
        self.root.withdraw()
        self.addCleanup(self.close_root)
        source = inspect.getsource(LineCheckAssistant._build_ui)
        for name in set(re.findall(r"self\.(_[a-zA-Z_]\w*)", source)):
            setattr(self.root, name, Mock(return_value=""))
        methods = (
            "_rebuild_channel_config_rows", "_build_power_serial_options",
            "_selected_power_serial_port", "_current_channel_serial_options",
            "_current_vlan_options", "_vlan_adapter_options", "_read_all_serial_ports",
            "_update_resource_options", "_on_show_all_resources_changed",
            "_refresh_power_serial_ports", "_refresh_adapters", "_on_power_serial_changed",
        )
        for name in methods:
            setattr(self.root, name, getattr(LineCheckAssistant, name).__get__(self.root))
        self.root._serial_port_for_channel = LineCheckAssistant._serial_port_for_channel
        self.root._capture_channel_rows = Mock()
        self.root._persist_config = Mock()
        self.root._log_list = Mock()
        self.root._shared_device_manage_ip.return_value = "192.168.1.1"
        self.root.channels = [
            ChannelConfig(section="channel_1", enabled=True, vlan_name="VLAN101", serial_port="COM1"),
            ChannelConfig(section="channel_9", enabled=True, vlan_name="VLAN109", serial_port="COM9"),
        ]
        self.root.current_index = 0
        self.root.adapters = ["VLAN109 [Up]", "Wi-Fi [Down]", "VLAN101 [Up]", "Ethernet [Disabled]"]
        self.root.power_serial_port = "COM101"
        self.root.show_all_resources_var = BooleanVar(master=self.root, value=False)
        self.root.all_serial_ports = []
        self.root.power_serial_options = self.root._build_power_serial_options()
        self.root.log_path = Path("not-written.log")
        self.root.log_queue = queue.Queue()
        for name in (
            "power_test_status_var", "power_test_progress_text_var", "power_test_channel_summary_var",
            "power_test_channel_attention_var", "power_test_channel_detail_var",
        ):
            setattr(self.root, name, StringVar(master=self.root, value=""))
        LineCheckAssistant._configure_theme(self.root)
        with patch("line_check_assistant.app.is_admin", return_value=True):
            LineCheckAssistant._build_ui(self.root)
        self.root._log.reset_mock()
        self.checkbox = next(
            widget for widget in self.descendants(self.root)
            if isinstance(widget, Checkbutton) and widget.cget("text") == "显示所有网卡和串口"
        )

    def close_root(self):
        root, self.root = self.root, None
        if "app_update_dialog" in root.__dict__:
            root.app_update_dialog.close_window()
        root.destroy()
        self.checkbox = None
        del root
        # UI测试的Mock/绑定方法形成环，必须在主线程释放Tcl变量。
        gc.collect()

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def values(self, widget):
        return tuple(widget.cget("values"))

    def enable_all(self, ports=("COM2", "COM10", "COM1200")):
        with patch("line_check_assistant.app.list_serial_port_names", return_value=list(ports)) as enumerate_ports:
            self.checkbox.invoke()
        enumerate_ports.assert_called_once_with()

    def test_native_checkbox_defaults_off_and_fits_main_card(self):
        self.assertFalse(self.root.show_all_resources_var.get())
        self.assertEqual(self.checkbox.winfo_class(), "Checkbutton")
        self.assertEqual(self.values(self.root.power_serial_combo), ("", "COM101", "COM102", "COM103", "COM104", "COM105", "COM106"))
        self.root.deiconify()
        ip_entry = next(widget for widget in self.checkbox.master.winfo_children() if isinstance(widget, ttk.Entry))
        for width in (1040, 1200, 1600):
            self.root.geometry(f"{width}x780")
            self.root.update()
            self.assertTrue(self.checkbox.winfo_ismapped())
            self.assertGreaterEqual(self.checkbox.winfo_width(), self.checkbox.winfo_reqwidth())
            self.assertEqual(self.checkbox.grid_info()["row"], ip_entry.grid_info()["row"])
            self.assertGreaterEqual(self.checkbox.winfo_rootx(), ip_entry.winfo_rootx() + ip_entry.winfo_width())
            self.assertLessEqual(self.checkbox.winfo_rootx() + self.checkbox.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())

    def test_toggle_changes_every_dropdown_without_changing_selection_or_saving(self):
        before = {key: {name: var.get() for name, var in variables.items()} for key, variables in self.root.channel_row_vars.items()}
        widgets = dict(self.root.channel_row_combos)
        self.enable_all()
        self.assertEqual(self.values(self.root.power_serial_combo), ("", "COM2", "COM10", "COM1200"))
        for combos in widgets.values():
            self.assertEqual(self.values(combos["vlan"]), ("Ethernet [Disabled]", "VLAN101 [Up]", "VLAN109 [Up]", "Wi-Fi [Down]"))
            self.assertEqual(self.values(combos["serial_port"]), ("COM2", "COM10", "COM1200"))
        self.checkbox.invoke()
        for section, combos in widgets.items():
            self.assertIs(combos["vlan"], self.root.channel_row_combos[section]["vlan"])
            self.assertEqual(self.values(combos["vlan"]), ("VLAN101 [Up]",))
            self.assertEqual(self.values(combos["serial_port"]), tuple(f"COM{n}" for n in range(1, 9)))
        after = {key: {name: var.get() for name, var in variables.items()} for key, variables in self.root.channel_row_vars.items()}
        self.assertEqual(before, after)
        self.assertEqual(self.root.power_serial_var.get(), "COM101")
        self.root._capture_channel_rows.assert_not_called()
        self.root._persist_config.assert_not_called()

    def test_refresh_updates_both_serial_lists_and_adapters_without_losing_selection(self):
        self.enable_all()
        self.root.power_serial_var.set("COM1200")
        with patch("line_check_assistant.app.list_serial_port_names", return_value=["COM77"]):
            self.root._refresh_power_serial_ports()
        with patch("line_check_assistant.app.list_adapter_display_names", return_value=["Ethernet77 [Up]"]):
            self.root._refresh_adapters()
        self.assertEqual(self.root.power_serial_var.get(), "COM1200")
        self.assertEqual(self.values(self.root.power_serial_combo), ("", "COM77"))
        for combos in self.root.channel_row_combos.values():
            self.assertEqual(self.values(combos["serial_port"]), ("COM77",))
            self.assertEqual(self.values(combos["vlan"]), ("Ethernet77 [Up]",))
        self.root._persist_config.assert_not_called()

    def test_enumeration_failure_keeps_cache_and_empty_result_preserves_selection(self):
        self.enable_all()
        with patch("line_check_assistant.app.list_serial_port_names", side_effect=OSError("模拟失败")):
            self.root._refresh_power_serial_ports()
        self.assertEqual(self.root.all_serial_ports, ["COM2", "COM10", "COM1200"])
        self.assertTrue(any("枚举失败" in args.args[0] and "模拟失败" in args.args[0] for args in self.root._log.call_args_list))
        with patch("line_check_assistant.app.list_serial_port_names", return_value=[]):
            self.root._refresh_power_serial_ports()
        self.assertEqual(self.values(self.root.power_serial_combo), ("",))
        for section, combos in self.root.channel_row_combos.items():
            self.assertEqual(self.values(combos["serial_port"]), ())
            self.assertEqual(self.root.channel_row_vars[section]["serial_port"].get(), "COM1" if section == "channel_1" else "COM9")
        self.assertEqual(self.root.power_serial_var.get(), "COM101")

    def test_first_enumeration_failure_still_allows_empty_and_toggle_off(self):
        with patch("line_check_assistant.app.list_serial_port_names", side_effect=OSError("首次失败")):
            self.checkbox.invoke()
        self.assertEqual(self.values(self.root.power_serial_combo), ("",))
        self.checkbox.invoke()
        self.assertIn("COM101", self.values(self.root.power_serial_combo))
        self.root._persist_config.assert_not_called()

    def test_power_change_and_row_rebuild_keep_all_mode_and_original_config(self):
        self.enable_all()
        self.root.power_serial_var.set("COM77")
        self.root._on_power_serial_changed()
        for combos in self.root.channel_row_combos.values():
            self.assertEqual(self.values(combos["serial_port"]), ("COM2", "COM10", "COM1200"))
            self.assertIn("Wi-Fi [Down]", self.values(combos["vlan"]))
        self.assertIn("全部 3 个本机串口", self.root._log.call_args.args[0])
        self.root.power_serial_var.set("")
        self.root._on_power_serial_changed()
        self.assertIn("手动重启", self.root._log.call_args.args[0])
        self.checkbox.invoke()
        for combos in self.root.channel_row_combos.values():
            self.assertEqual(len(self.values(combos["serial_port"])), 48)
            self.assertIn("Wi-Fi [Down]", self.values(combos["vlan"]))

    def test_power_dialog_accepts_actual_port_and_keeps_saved_port_when_filtered(self):
        self.enable_all()
        self.root.power_serial_var.set("COM77")

        def confirm_dialog():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, Toplevel))
            combos = [widget for widget in self.descendants(dialog) if isinstance(widget, ttk.Combobox)]
            self.assertEqual(self.values(combos[0]), ("", "COM2", "COM10", "COM1200", "COM77"))
            self.assertEqual(combos[0].get(), "COM77")
            combos[0].set("COM1200")
            button = next(widget for widget in self.descendants(dialog) if widget.winfo_class() == "Button" and widget.cget("text") == "确定")
            button.invoke()

        self.root.wait_window = Mock(side_effect=lambda _window: confirm_dialog())
        self.assertEqual(LineCheckAssistant._select_power_com_port(self.root), ("COM1200", "上电"))
        self.checkbox.invoke()
        self.root.wait_window = Mock(side_effect=lambda window: window.destroy())
        self.assertEqual(LineCheckAssistant._select_power_com_port(self.root), (None, "上电"))
        self.root._persist_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()

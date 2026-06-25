import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig


class CurrentChannelSelectionTests(unittest.TestCase):
    def test_test_item_config_entry_reuses_open_window(self):
        config_window = Mock()
        config_window.winfo_exists.return_value = True
        context = SimpleNamespace(test_item_config_window=config_window)

        LineCheckAssistant._open_test_item_config(context)

        config_window.deiconify.assert_called_once_with()
        config_window.lift.assert_called_once_with()
        config_window.focus_force.assert_called_once_with()

    def test_serial_log_entry_reuses_open_window(self):
        serial_log_window = Mock()
        serial_log_window.winfo_exists.return_value = True
        context = SimpleNamespace(serial_log_window=serial_log_window)

        LineCheckAssistant._open_serial_log_module(context)

        serial_log_window.deiconify.assert_called_once_with()
        serial_log_window.lift.assert_called_once_with()
        serial_log_window.focus_force.assert_called_once_with()

    def test_upgrade_entry_reuses_open_window(self):
        upgrade_window = Mock()
        upgrade_window.winfo_exists.return_value = True
        context = SimpleNamespace(upgrade_window=upgrade_window, _refresh_upgrade_targets=Mock())

        LineCheckAssistant._open_upgrade_module(context)

        upgrade_window.deiconify.assert_called_once_with()
        upgrade_window.lift.assert_called_once_with()
        upgrade_window.focus_force.assert_called_once_with()
        context._refresh_upgrade_targets.assert_called_once_with()

    def test_selected_upgrade_vlans_only_contains_enabled_unique_vlans(self):
        context = SimpleNamespace(
            channels=[
                ChannelConfig(section="channel_1", vlan_name="VLAN108", enabled=True),
                ChannelConfig(section="channel_2", vlan_name="vlan101", enabled=True),
                ChannelConfig(section="channel_3", vlan_name="VLAN108", enabled=True),
                ChannelConfig(section="channel_4", vlan_name="VLAN102", enabled=False),
            ],
            _vlan_sort_key=lambda value: (int("".join(char for char in value if char.isdigit())), value),
        )

        vlans = LineCheckAssistant._selected_upgrade_vlans(context)

        self.assertEqual(vlans, ["vlan101", "vlan108"])

    def test_upgrade_status_shows_vlan_stage_and_progress(self):
        context = SimpleNamespace(upgrade_progress_var=Mock(), upgrade_status_var=Mock())

        LineCheckAssistant._set_upgrade_status(context, "vlan108", "下载固件", 35)

        context.upgrade_progress_var.set.assert_called_once_with(35.0)
        context.upgrade_status_var.set.assert_called_once_with("正在升级 vlan108：下载固件（35%）")

    def test_full_package_upgrade_shows_transfer_method(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put"), set=Mock()),
            upgrade_transfer_label=Mock(),
            upgrade_transfer_combo=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_transfer_visibility(context)

        context.upgrade_transfer_label.grid.assert_called_once_with()
        context.upgrade_transfer_combo.grid.assert_called_once_with()
        context.upgrade_transfer_label.grid_remove.assert_not_called()
        context.upgrade_transfer_combo.grid_remove.assert_not_called()

    def test_page_upgrade_hides_transfer_method(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put"), set=Mock()),
            upgrade_transfer_label=Mock(),
            upgrade_transfer_combo=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_transfer_visibility(context)

        context.upgrade_transfer_label.grid_remove.assert_called_once_with()
        context.upgrade_transfer_combo.grid_remove.assert_called_once_with()
        context.upgrade_transfer_label.grid.assert_not_called()
        context.upgrade_transfer_combo.grid.assert_not_called()

    def test_restore_factory_toggle_switches_value_and_updates_text(self):
        context = SimpleNamespace(
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False), set=Mock()),
            _refresh_upgrade_restore_factory_text=Mock(),
        )

        result = LineCheckAssistant._toggle_upgrade_restore_factory(context)

        context.upgrade_restore_factory_var.set.assert_called_once_with(True)
        context._refresh_upgrade_restore_factory_text.assert_called_once_with()
        self.assertEqual(result, "break")

    def test_restore_factory_text_uses_check_mark_when_enabled(self):
        context = SimpleNamespace(
            upgrade_restore_factory_var=Mock(get=Mock(return_value=True)),
            upgrade_restore_factory_text_var=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_restore_factory_text(context)

        context.upgrade_restore_factory_text_var.set.assert_called_once_with("☑ 恢复出厂")

    @patch("line_check_assistant.app.threading.Thread")
    def test_upgrade_start_queues_securecrt_serial_logs(self, thread_class):
        worker = thread_class.return_value
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_username_var=Mock(get=Mock(return_value="admin")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            upgrade_window=Mock(),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            _selected_upgrade_vlans=Mock(return_value=["vlan101", "vlan108"]),
            _set_upgrade_status=Mock(),
            _securecrt_launch_worker=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        context._set_upgrade_status.assert_called_once_with("", "正在启动 SecureCRT 并建立串口连接...", 0)
        thread_class.assert_called_once_with(
            target=context._securecrt_launch_worker,
            args=(["vlan101", "vlan108"],),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    @patch("line_check_assistant.app.threading.Thread")
    def test_full_package_tftp_copy_starts_single_upgrade_flow(self, thread_class):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp拷贝命令")),
            upgrade_username_var=Mock(get=Mock(return_value="admin")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            _start_single_tftp_copy_upgrade=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        context._start_single_tftp_copy_upgrade.assert_called_once_with()
        thread_class.assert_not_called()

    def test_upgrade_required_fields_warn_when_missing(self):
        context = SimpleNamespace(
            upgrade_window=Mock(),
            upgrade_username_var=Mock(get=Mock(return_value="")),
            upgrade_password_var=Mock(get=Mock(return_value="")),
            upgrade_firmware_var=Mock(get=Mock(return_value="")),
        )

        with patch("line_check_assistant.app.messagebox.showwarning") as showwarning:
            result = LineCheckAssistant._validate_upgrade_required_fields(context)

        self.assertFalse(result)
        showwarning.assert_called_once()
        self.assertIn("超级用户名、密码、升级固件", showwarning.call_args.args[1])

    @patch("line_check_assistant.app.messagebox.showwarning")
    @patch("line_check_assistant.app.threading.Thread")
    def test_upgrade_start_stops_when_required_fields_missing(self, thread_class, showwarning):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_username_var=Mock(get=Mock(return_value="")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            upgrade_window=Mock(),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=lambda: LineCheckAssistant._validate_upgrade_required_fields(context),
            _selected_upgrade_vlans=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        showwarning.assert_called_once()
        context._selected_upgrade_vlans.assert_not_called()
        thread_class.assert_not_called()

    def test_tftp_server_ip_prefers_channel_network_card_ip(self):
        channel = ChannelConfig(section="channel_1", vlan_name="VLAN148", network_card_ip="192.168.1.148")
        context = SimpleNamespace(device_ip_var=Mock(get=Mock(return_value="192.168.1.1")))

        self.assertEqual(LineCheckAssistant._tftp_server_ip_for_channel(context, channel), "192.168.1.148")

    def test_tftp_server_ip_falls_back_to_vlan_suffix(self):
        channel = ChannelConfig(section="channel_1", vlan_name="VLAN148")
        context = SimpleNamespace(device_ip_var=Mock(get=Mock(return_value="")))

        self.assertEqual(LineCheckAssistant._tftp_server_ip_for_channel(context, channel), "192.168.1.148")

    @patch("line_check_assistant.app.messagebox.showinfo")
    def test_success_is_reported_only_after_visible_securecrt_window(self, showinfo):
        result = SimpleNamespace(success=True, message="started", targets=(Mock(), Mock()), log_directory=r"F:\logs")
        context = SimpleNamespace(upgrade_window=Mock(), _set_upgrade_status=Mock(), _log=Mock())

        LineCheckAssistant._complete_securecrt_launch(context, result)

        context._set_upgrade_status.assert_called_once_with("", "SecureCRT 已打开 2 个目标串口，日志记录中", 0)
        context._log.assert_called_once_with("started")
        showinfo.assert_called_once()

    def test_password_eye_toggles_plain_text_display(self):
        context = SimpleNamespace(
            upgrade_password_visible=False,
            upgrade_password_entry=Mock(),
            upgrade_password_toggle=Mock(),
        )

        LineCheckAssistant._toggle_upgrade_password_visibility(context)

        self.assertTrue(context.upgrade_password_visible)
        context.upgrade_password_entry.configure.assert_called_once_with(show="")
        context.upgrade_password_toggle.configure.assert_called_once_with(relief="sunken")

    def test_enabling_table_row_makes_that_row_current(self):
        channel_1 = ChannelConfig(section="channel_1")
        context = SimpleNamespace(
            channels=[channel_1, ChannelConfig(section="channel_2")],
            _channel_by_section=Mock(return_value=channel_1),
            _capture_channel_row=Mock(),
            _refresh_channel_list_item=Mock(),
            _select_channel_index=Mock(),
            _persist_config=Mock(),
        )

        LineCheckAssistant._on_row_enabled_changed(context, "channel_1")

        context._select_channel_index.assert_called_once_with(0)
        context._persist_config.assert_called_once_with()

    def test_persist_config_only_writes_enabled_channels(self):
        channels = [
            ChannelConfig(section="channel_1", enabled=True),
            ChannelConfig(section="channel_2", enabled=False),
        ]
        context = SimpleNamespace(
            channels=channels,
            store=Mock(),
            _capture_current_channel=Mock(),
            _selected_power_serial_port=Mock(return_value="COM101"),
            _selected_channels=Mock(return_value=[channels[0]]),
            _refresh_upgrade_targets=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._persist_config(context)

        context.store.save.assert_called_once_with([channels[0]], "COM101")

    def test_launch_old_tool_passes_wait_seconds_by_enabled_channel_count(self):
        channels = [
            ChannelConfig(section="channel_1", enabled=True),
            ChannelConfig(section="channel_2", enabled=True),
            ChannelConfig(section="channel_3", enabled=True),
        ]
        context = SimpleNamespace(
            power_on_running=False,
            _capture_current_channel=Mock(),
            _selected_channels=Mock(return_value=channels),
            _power_on_wait_seconds=Mock(return_value=15),
            _select_power_com_port=Mock(return_value="COM106"),
            power_serial_var=Mock(),
            _power_on_worker=Mock(),
        )

        with patch("line_check_assistant.app.threading.Thread") as thread:
            LineCheckAssistant._launch_old_tool(context)

        context._power_on_wait_seconds.assert_called_once_with(channels)
        context._select_power_com_port.assert_called_once_with()
        context.power_serial_var.set.assert_called_once_with("COM106")
        thread.assert_called_once_with(target=context._power_on_worker, args=("COM106", 15), daemon=True)
        thread.return_value.start.assert_called_once_with()
        self.assertTrue(context.power_on_running)

    def test_launch_old_tool_warns_when_no_channel_enabled(self):
        context = SimpleNamespace(
            power_on_running=False,
            _capture_current_channel=Mock(),
            _selected_channels=Mock(return_value=[]),
            _select_power_com_port=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.showwarning") as showwarning:
            LineCheckAssistant._launch_old_tool(context)

        showwarning.assert_called_once()
        context._select_power_com_port.assert_not_called()
        self.assertFalse(context.power_on_running)

    def test_power_on_wait_seconds_uses_five_seconds_per_channel(self):
        channels = [
            ChannelConfig(section="channel_1", enabled=True),
            ChannelConfig(section="channel_2", enabled=True),
        ]

        self.assertEqual(LineCheckAssistant._power_on_wait_seconds(None, channels), 10)

    def test_select_channel_index_syncs_internal_and_list_selection(self):
        context = SimpleNamespace(
            channels=[ChannelConfig(section="channel_1"), ChannelConfig(section="channel_2")],
            current_index=1,
            _last_selected_index=1,
            channel_list=Mock(),
            _load_current_channel=Mock(),
        )

        LineCheckAssistant._select_channel_index(context, 0)

        self.assertEqual(context.current_index, 0)
        self.assertEqual(context._last_selected_index, 0)
        context.channel_list.selection_clear.assert_called_once_with(0, "end")
        context.channel_list.selection_set.assert_called_once_with(0)
        context._load_current_channel.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

import inspect
import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.app import (
    COLOR_DANGER,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    LineCheckAssistant,
    MAIN_LOG_EVENTS_PER_TICK,
    TEST_ITEM_DEFAULT_CONFIG_PATH,
    TEST_ITEM_COMMAND_GROUP_SPACING,
    TEST_ITEM_HIDDEN_UI_DEFAULT_OPTIONS,
    _clear_test_item_rows,
    serial_options_for_power_serial_port,
    vlan_options_for_power_serial_port,
)
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.network_ops import CommandResult, UnregisteredOnu
from line_check_assistant.onu_registration_store import OnuRegistrationConfig
from line_check_assistant.page_upgrade import PageUpgradeItemResult, PageUpgradeRequest
from line_check_assistant.sample_upgrade_settings_store import (
    DEFAULT_PARAMETER_PARALLEL_COUNT,
    SampleUpgradeSettings,
)
from line_check_assistant.test_item_config_store import TelnetSettings, TestItemConfigStore
from src.models import (
    C300CleanupCandidate,
    DiscoveredOnu,
    DutAdvancedQueryResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutTelnetEnableRequest,
    DutTelnetEnableResult,
    DutTelnetStatus,
    DutWanConnectionInfo,
    DutWanQueryResult,
    DutWifiRadioSettings,
    DutWifiSettings,
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OltConnection,
    OnuDiscoveryScope,
    OnuOperationResult,
    OnuProvisionRequest,
    OnuServiceMapping,
    RegisteredOnu,
)
from src.services.dut_advanced_config_service import (
    VOICE_SIP_MODE_OPTIONS,
    WIFI_BANDWIDTH_OPTIONS,
    WIFI_MODE_OPTIONS,
    WIFI_SECURITY_MODE_OPTIONS,
)
from src.ui.dut_config_window import (
    DUT_CONFIG_DEFAULT_HEIGHT,
    DUT_CONFIG_DEFAULT_WIDTH,
    DUT_CURRENT_STATUS_MAX_HEIGHT,
    DUT_CURRENT_STATUS_MIN_HEIGHT,
    DutConfigWindow,
    DUT_TARGET_SELECTED_MARK,
    DUT_TARGET_UNSELECTED_MARK,
    clamp_dut_window_size,
    clamp_dut_current_status_height,
    load_dut_current_status_heights,
    load_dut_window_size,
    normalize_wan_address_modes,
    reconcile_dut_target_selection,
    resolve_wan_form_rules,
    wan_connection_form_values,
    wan_lan_ports_from_port_bind,
    wan_port_bind_from_lan_ports,
    tr069_status_form_values,
    voice_choice_options,
    voice_status_form_values,
    wifi_choice_options,
    wifi_status_form_values,
    save_dut_current_status_heights,
    save_dut_window_size,
)


class CurrentChannelSelectionTests(unittest.TestCase):
    def test_parameter_generator_labels_xpon_sn_fixed_format_and_sn_length_separately(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._open_parameter_generator)

        self.assertIn('"SN 前缀（纯数字）": StringVar(value="12345678")', source)
        self.assertIn('"XPON SN 前缀（固定 4 位）": StringVar(value="XPON")', source)
        self.assertIn('"SN 随机后缀长度（总长≤16）": StringVar(value="8")', source)
        self.assertIn('sn_prefix=fields["SN 前缀（纯数字）"].get()', source)
        self.assertIn('xpon_prefix=fields["XPON SN 前缀（固定 4 位）"].get()', source)
        self.assertNotIn('"SN/GPON SN 随机后缀长度"', source)

    def test_parameter_generator_has_custom_hex_mac_prefix_field(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._open_parameter_generator)

        self.assertIn('"MAC 前6位（十六进制）": StringVar(value="020000")', source)
        self.assertIn('mac_prefix=fields["MAC 前6位（十六进制）"].get()', source)
        self.assertIn("MAC前6位由用户指定、后6位为唯一随机十六进制", source)

    def test_parameter_generator_centers_and_refreshes_client_area_after_layout(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._open_parameter_generator)
        button_index = source.index('text="取消"')
        center_index = source.index("center_toplevel_on_parent(")
        refresh_index = source.index("schedule_toplevel_client_refresh(")

        self.assertLess(button_index, center_index)
        self.assertLess(center_index, refresh_index)
        self.assertIn("self.parameter_writer_window", source[center_index:refresh_index])
        self.assertIn("window_width=680", source[center_index:refresh_index])
        self.assertIn("window_height=750", source[center_index:refresh_index])
        self.assertIn("on_first_refresh=lambda", source[refresh_index:])
        self.assertIn("已触发客户区首帧尺寸刷新", source[refresh_index:])
        self.assertNotIn("withdraw(", source)
        self.assertNotIn("after(0", source)

    def test_empty_power_serial_port_shows_all_detected_adapters(self):
        adapters = ["VLAN109 [Up]", "Ethernet [Up]", "VLAN101 [Down]"]

        self.assertEqual(
            vlan_options_for_power_serial_port(adapters, ""),
            ["Ethernet [Up]", "VLAN101 [Down]", "VLAN109 [Up]"],
        )

    def test_power_serial_port_limits_vlan_options_to_its_eight_vlan_group(self):
        adapters = [
            "VLAN100 [Up]",
            "VLAN101 [Up]",
            "VLAN108 [Down]",
            "VLAN109 [Up]",
            "VLAN116 [Up]",
            "VLAN117 [Up]",
            "Ethernet [Up]",
        ]

        self.assertEqual(
            vlan_options_for_power_serial_port(adapters, "COM101"),
            ["VLAN101 [Up]", "VLAN108 [Down]"],
        )
        self.assertEqual(
            vlan_options_for_power_serial_port(adapters, "COM102"),
            ["VLAN109 [Up]", "VLAN116 [Up]"],
        )

    def test_power_serial_port_accepts_operator_com_group_number(self):
        adapters = ["VLAN109", "VLAN116", "VLAN117"]

        self.assertEqual(
            vlan_options_for_power_serial_port(adapters, "COM2"),
            ["VLAN109", "VLAN116"],
        )

    def test_power_serial_port_limits_channel_com_options_to_its_eight_port_group(self):
        self.assertEqual(
            serial_options_for_power_serial_port("COM101"),
            [f"COM{index}" for index in range(1, 9)],
        )
        self.assertEqual(
            serial_options_for_power_serial_port("COM102"),
            [f"COM{index}" for index in range(9, 17)],
        )
        self.assertEqual(
            serial_options_for_power_serial_port("COM2"),
            [f"COM{index}" for index in range(9, 17)],
        )
        self.assertEqual(
            serial_options_for_power_serial_port(""),
            [f"COM{index}" for index in range(1, 49)],
        )

    def test_channel_serial_port_prefers_saved_selection_and_falls_back_to_vlan_mapping(self):
        configured = ChannelConfig(
            section="channel_1", vlan_name="VLAN113", serial_port="com8"
        )
        legacy = ChannelConfig(section="channel_2", vlan_name="VLAN113")

        self.assertEqual(
            LineCheckAssistant._serial_port_for_channel(configured),
            "COM8",
        )
        self.assertEqual(
            LineCheckAssistant._serial_port_for_channel(legacy),
            "COM13",
        )

    def test_channel_com_column_is_readonly_and_uses_grouped_options(self):
        import inspect

        table_source = inspect.getsource(LineCheckAssistant._rebuild_channel_config_rows)
        capture_source = inspect.getsource(LineCheckAssistant._capture_channel_row)

        self.assertIn('"通道对应 COM口"', table_source)
        self.assertIn("serial_options = self._current_channel_serial_options()", table_source)
        self.assertIn('"serial_port": serial_var', table_source)
        self.assertIn("state=\"readonly\"", table_source)
        self.assertIn("_on_row_serial_changed", table_source)
        self.assertIn('row_vars["serial_port"]', capture_source)

    def test_channel_selection_list_is_wide_enough_for_vlan_and_com_text(self):
        """主界面通道列表必须完整显示启用通道的 VLAN / COM 信息。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_ui)

        self.assertIn("self.channel_list = Listbox(", source)
        self.assertIn("width=34", source)

    def test_channel_list_right_click_menu_opens_selected_power_test_log(self):
        source = inspect.getsource(LineCheckAssistant._build_ui)

        self.assertIn('self.channel_list.bind("<Button-3>", self._on_channel_list_context_menu)', source)
        self.assertIn('label="打开本次开关机运行日志"', source)

    def test_channel_list_right_click_selects_the_clicked_row_before_showing_menu(self):
        context = SimpleNamespace(
            channels=[ChannelConfig(section="channel_1"), ChannelConfig(section="channel_2")],
            channel_list=Mock(),
            _select_channel_index=Mock(),
            channel_context_menu=Mock(),
        )
        context.channel_list.nearest.return_value = 1
        context.channel_list.bbox.return_value = (0, 20, 200, 18)
        event = SimpleNamespace(y=25, x_root=300, y_root=400)

        result = LineCheckAssistant._on_channel_list_context_menu(context, event)

        self.assertEqual(result, "break")
        context._select_channel_index.assert_called_once_with(1)
        context.channel_context_menu.tk_popup.assert_called_once_with(300, 400)
        context.channel_context_menu.grab_release.assert_called_once_with()

    @patch("line_check_assistant.app.os.startfile")
    @patch("line_check_assistant.app.latest_power_test_result_log")
    def test_open_selected_power_test_log_opens_latest_log_for_current_channel(
        self, latest_power_test_result_log, startfile
    ):
        result_path = Path(r"F:\\Power\\Auto_power_on_off_tool\\test_results\\device_2\\device_2_command_results_20260831002652.log")
        latest_power_test_result_log.return_value = result_path
        context = SimpleNamespace(
            current_index=1,
            channels=[ChannelConfig(section="channel_1"), ChannelConfig(section="channel_2")],
            _log=Mock(),
        )

        LineCheckAssistant._open_selected_power_test_log(context)

        latest_power_test_result_log.assert_called_once()
        self.assertEqual(latest_power_test_result_log.call_args.args[1], 2)
        startfile.assert_called_once_with(str(result_path))
        self.assertIn("已打开通道 2 最新日志", context._log.call_args.args[0])

    @patch("line_check_assistant.app.messagebox.showinfo")
    @patch("line_check_assistant.app.latest_power_test_result_log", return_value=None)
    def test_open_selected_power_test_log_reports_when_current_channel_has_no_result(
        self, _latest_power_test_result_log, showinfo
    ):
        context = SimpleNamespace(
            current_index=1,
            channels=[ChannelConfig(section="channel_1"), ChannelConfig(section="channel_2")],
            _log=Mock(),
        )

        LineCheckAssistant._open_selected_power_test_log(context)

        showinfo.assert_called_once()
        self.assertIn("通道 2 未找到结果文件", context._log.call_args.args[0])

    def test_parameter_and_serial_log_targets_use_saved_channel_com_selection(self):
        channels = [
            ChannelConfig(
                section="channel_1",
                vlan_name="VLAN113",
                serial_port="COM8",
                enabled=True,
            ),
            ChannelConfig(section="channel_2", vlan_name="VLAN112", enabled=True),
        ]
        context = SimpleNamespace(
            channels=channels,
            _capture_current_channel=Mock(),
            _vlan_sort_key=lambda value: (int("".join(filter(str.isdigit, value))), value),
        )

        parameter_targets = LineCheckAssistant._parameter_channel_ports(context)
        serial_targets = LineCheckAssistant._selected_serial_targets(context)

        self.assertEqual(
            parameter_targets,
            [("VLAN113", "COM8"), ("VLAN112", "COM12")],
        )
        self.assertEqual(
            serial_targets,
            [("vlan112", "COM12"), ("vlan113", "COM8")],
        )

    def test_drain_log_queue_limits_each_ui_tick_and_continues_when_backlogged(self):
        log_queue = queue.Queue()
        for index in range(MAIN_LOG_EVENTS_PER_TICK + 5):
            log_queue.put(f"parallel log {index}")
        context = SimpleNamespace(
            log_queue=log_queue,
            running=True,
            power_on_running=True,
            progress=Mock(),
            _log=Mock(),
            _drain_log_queue=Mock(),
            after=Mock(),
        )

        LineCheckAssistant._drain_log_queue(context)

        self.assertEqual(context._log.call_count, MAIN_LOG_EVENTS_PER_TICK)
        self.assertEqual(log_queue.qsize(), 5)
        self.assertEqual(context.after.call_args.args[0], 0)

        LineCheckAssistant._drain_log_queue(context)

        self.assertEqual(context._log.call_count, MAIN_LOG_EVENTS_PER_TICK + 5)
        self.assertEqual(log_queue.qsize(), 0)
        self.assertEqual(context.after.call_args.args[0], 200)

    def test_legacy_channel_cycle_start_log_uses_green_success_tag(self):
        """旧工具每轮通道测试开始日志应在新工具执行日志中显示为绿色。"""
        context = SimpleNamespace()

        self.assertEqual(
            LineCheckAssistant._log_tag_for(
                context,
                "[旧工具Logs][INFO] *******通道 【9】 开始第2次测试*******",
            ),
            "success",
        )
        self.assertEqual(
            LineCheckAssistant._log_tag_for(
                context,
                "[旧工具Logs][INFO] *******通道 【16】 开始第 12 次测试*******",
            ),
            "success",
        )
        self.assertEqual(
            LineCheckAssistant._log_tag_for(
                context,
                "[旧工具Logs][INFO] 通道 【9】 正在执行测试命令",
            ),
            "",
        )

    def test_test_item_config_entry_reuses_open_window(self):
        config_window = Mock()
        config_window.winfo_exists.return_value = True
        context = SimpleNamespace(test_item_config_window=config_window)

        LineCheckAssistant._open_test_item_config(context)

        config_window.deiconify.assert_called_once_with()
        config_window.lift.assert_called_once_with()
        config_window.focus_force.assert_called_once_with()

    def test_dut_config_toolbar_entry_is_next_to_serial_log(self):
        """DUT 配置入口必须位于主界面串口日志右侧。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_ui)
        serial_entry = 'text="串口日志", command=self._open_serial_log_module'
        dut_entry = 'text="DUT配置", command=self._open_dut_config_module'

        self.assertIn(serial_entry, source)
        self.assertIn(dut_entry, source)
        self.assertLess(source.index(serial_entry), source.index(dut_entry))

    def test_main_header_copy_is_removed_and_admin_status_moves_to_toolbar(self):
        """内容区不重复标题，管理员状态位于两个刷新按钮左侧。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_ui)
        self.assertNotIn('text="openWRT老化测试环境搭建助手"', source)
        self.assertNotIn('text="配置测试通道、完成自动上/下电并检查全部线路"', source)
        self.assertNotIn('text="运行步骤、检查结果和异常信息"', source)
        self.assertNotIn("title_area", source)
        refresh_adapter = 'text="刷新网卡", command=self._refresh_adapters'
        refresh_serial = 'text="刷新串口", command=self._refresh_power_serial_ports'
        admin_status = "text=admin_text"
        self.assertLess(source.index(refresh_adapter), source.index(refresh_serial))
        self.assertLess(source.index(refresh_serial), source.index(admin_status))
        self.assertIn('style="Success.TLabel" if admin_ok else "Danger.TLabel"', source)

    def test_main_window_title_uses_openwrt_aging_environment_name(self):
        """Windows 标题栏必须使用当前工具名称。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant.__init__)

        self.assertIn('self.title("openWRT老化测试环境搭建助手")', source)

    def test_main_card_shows_power_test_status_and_stop_button(self):
        """主界面空白区显示状态，并承接从全流程窗口移出的停止按钮。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_ui)
        self.assertIn("textvariable=self.power_test_status_var", source)
        self.assertIn("textvariable=self.power_test_progress_text_var", source)
        self.assertIn("self.power_test_channel_overview", source)
        self.assertIn("text=\"通道概览（收起）\"", source)
        self.assertIn('style="OverviewToggle.TButton"', source)
        self.assertIn("command=self._toggle_power_test_channel_overview", source)
        self.assertIn('mode="determinate", maximum=1, value=0', source)
        self.assertIn('style="PowerStatusIdle.TLabel"', source)
        self.assertIn('text="停止测试"', source)
        self.assertIn("command=self._stop_power_test", source)
        self.assertIn('state="disabled"', source)

    def test_power_test_status_controls_main_stop_button(self):
        status_var = Mock()
        status_label = Mock()
        stop_button = Mock()
        context = SimpleNamespace(
            power_test_running=False,
            power_test_status_var=status_var,
            power_test_status_label=status_label,
            stop_power_test_button=stop_button,
        )

        LineCheckAssistant._set_power_test_status(context, "running")
        self.assertTrue(context.power_test_running)
        status_var.set.assert_called_with("开关机测试状态：正在执行")
        status_label.configure.assert_called_with(style="PowerStatusRunning.TLabel")
        stop_button.configure.assert_called_with(state="normal")

        LineCheckAssistant._set_power_test_status(context, "stopping")
        self.assertTrue(context.power_test_running)
        status_var.set.assert_called_with(
            "开关机测试状态：正在停止（等待当前子任务安全退出）"
        )
        status_label.configure.assert_called_with(style="PowerStatusStopping.TLabel")
        stop_button.configure.assert_called_with(state="disabled")

        LineCheckAssistant._set_power_test_status(context, "completed")
        self.assertFalse(context.power_test_running)
        status_var.set.assert_called_with("开关机测试状态：已完成")
        status_label.configure.assert_called_with(style="PowerStatusCompleted.TLabel")
        stop_button.configure.assert_called_with(state="disabled")

    def test_power_test_progress_uses_configured_total_and_clamps_value(self):
        progress = Mock()
        progress_text = Mock()
        context = SimpleNamespace(
            progress=progress,
            power_test_progress_text_var=progress_text,
        )

        LineCheckAssistant._set_power_test_progress(context, 12, 500)
        progress.configure.assert_called_with(maximum=500, value=12)
        progress_text.set.assert_called_with("开关机测试进度：12/500")

        LineCheckAssistant._set_power_test_progress(context, 600, 500)
        progress.configure.assert_called_with(maximum=500, value=500)
        progress_text.set.assert_called_with("开关机测试进度：500/500")

    def test_power_test_progress_resets_when_total_is_unknown(self):
        progress = Mock()
        progress_text = Mock()
        context = SimpleNamespace(
            progress=progress,
            power_test_progress_text_var=progress_text,
        )

        LineCheckAssistant._set_power_test_progress(context, 9, 0)

        progress.configure.assert_called_once_with(maximum=1, value=0)
        progress_text.set.assert_called_once_with("开关机测试进度：等待开始")

    def test_power_test_status_styles_are_prominent_and_state_specific(self):
        """运行态使用高对比徽标，其余状态也有独立颜色语义。"""
        import inspect

        theme_source = inspect.getsource(LineCheckAssistant._configure_theme)
        status_source = inspect.getsource(LineCheckAssistant._set_power_test_status)

        self.assertIn('"padding": (14, 8)', theme_source)
        self.assertIn('"font": (FONT_FAMILY, 11, "bold")', theme_source)
        self.assertIn(
            '"PowerStatusRunning.TLabel", background=COLOR_PRIMARY, foreground="#ffffff"',
            theme_source,
        )
        for style_name in (
            "PowerStatusIdle.TLabel",
            "PowerStatusRunning.TLabel",
            "PowerStatusStopping.TLabel",
            "PowerStatusCompleted.TLabel",
            "PowerStatusStopped.TLabel",
            "PowerStatusFailed.TLabel",
        ):
            self.assertIn(style_name, status_source)

    def test_main_stop_button_delegates_to_pipeline_window(self):
        pipeline_window = Mock()
        pipeline_window.request_stop.return_value = True
        context = SimpleNamespace(pipeline_window=pipeline_window, _log=Mock())

        LineCheckAssistant._stop_power_test(context)

        pipeline_window.request_stop.assert_called_once_with()
        context._log.assert_not_called()

    def test_main_stop_button_recovers_stale_running_status(self):
        pipeline_window = Mock()
        pipeline_window.request_stop.return_value = False
        context = SimpleNamespace(
            pipeline_window=pipeline_window,
            power_test_running=True,
            _set_power_test_status=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._stop_power_test(context)

        context._set_power_test_status.assert_called_once_with("idle")
        self.assertIn("残留状态恢复为未运行", context._log.call_args.args[0])

    def test_dut_config_entry_reuses_open_window(self):
        dut_window = Mock()
        dut_window.exists.return_value = True
        context = SimpleNamespace(
            dut_config_window=dut_window,
            dut_config_running=False,
            _refresh_dut_config_targets=Mock(),
        )

        LineCheckAssistant._open_dut_config_module(context)

        dut_window.show.assert_called_once_with()
        context._refresh_dut_config_targets.assert_called_once_with()

    def test_dut_config_window_is_extensible_and_dispatches_through_service(self):
        """DUT 页面使用独立 Tab，UI 只调用 service，不复制 UBUS 协议。"""
        import inspect

        open_source = inspect.getsource(LineCheckAssistant._open_dut_config_module)
        start_source = inspect.getsource(LineCheckAssistant._start_dut_advanced_config)
        worker_source = inspect.getsource(LineCheckAssistant._dut_telnet_enable_worker)
        advanced_worker_source = inspect.getsource(LineCheckAssistant._dut_advanced_config_worker)
        window_source = inspect.getsource(DutConfigWindow.__init__)
        wan_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        voice_source = inspect.getsource(DutConfigWindow._build_voice_tab)
        tr069_source = inspect.getsource(DutConfigWindow._build_tr069_tab)
        wifi_source = inspect.getsource(DutConfigWindow._build_wifi_tab)
        show_source = inspect.getsource(DutConfigWindow.show)
        self.assertIn("DutConfigWindow(", open_source)
        self.assertIn("username_var=self.parameter_initial_username_var", open_source)
        self.assertIn("password_var=self.parameter_initial_password_var", open_source)
        self.assertIn("on_query_wan=self._query_dut_wan_connections", open_source)
        self.assertIn("on_query_telnet=self._query_dut_telnet_status", open_source)
        self.assertIn("on_query_voice=self._query_dut_voice_status", open_source)
        self.assertIn("on_query_tr069=self._query_dut_tr069_status", open_source)
        self.assertIn("on_query_wifi_2g=self._query_dut_wifi_2g_status", open_source)
        self.assertIn("on_query_wifi_5g=self._query_dut_wifi_5g_status", open_source)
        self.assertIn('self.notebook.add(telnet_tab, text="Telnet配置")', window_source)
        self.assertIn('self.notebook.add(tab, text="WAN配置")', wan_source)
        self.assertIn('self.notebook.add(tab, text="语音配置")', voice_source)
        self.assertIn('self.notebook.add(tab, text="TR069配置")', tr069_source)
        self.assertIn('text=f"{band} WiFi配置"', wifi_source)
        self.assertIn('values=("IPv4", "IPv6", "IPv4+IPv6（双栈）")', wan_source)
        self.assertIn('text="开启 Telnet"', window_source)
        self.assertIn(
            "self.window.after_idle(self._constrain_selected_current_status_height)",
            window_source,
        )
        self.assertIn("self.window.deiconify()", show_source)
        self.assertIn("self.window.lift()", show_source)
        self.assertIn("self.window.focus_force()", show_source)
        self.assertNotIn('show="*"', window_source)
        self.assertIn("run_dut_telnet_enable_batch(", worker_source)
        self.assertIn("run_dut_advanced_config_batch(", advanced_worker_source)
        self.assertIn(
            "shared_wifi_settle = increment_wifi_ssid and len(requests) > 1",
            start_source,
        )
        self.assertIn("shared_wifi_settle=shared_wifi_settle", advanced_worker_source)
        self.assertNotIn("UbusHttpClient(", open_source + worker_source)
        self.assertNotIn("bbfdm.", open_source + worker_source + advanced_worker_source)

    def test_dut_target_selection_preserves_manual_clear_and_selects_new_targets(self):
        self.assertEqual(
            reconcile_dut_target_selection(
                ("通道 12",),
                ("通道 12", "通道 13"),
                ("通道 12", "通道 13", "通道 14"),
            ),
            ("通道 12", "通道 14"),
        )
        self.assertEqual(
            reconcile_dut_target_selection((), (), ("通道 12", "通道 13")),
            ("通道 12", "通道 13"),
        )

    def test_dut_target_selection_is_shared_by_every_tab(self):
        class FakeTree:
            def __init__(self):
                self.rows = {
                    "row12": [DUT_TARGET_SELECTED_MARK, "通道 12", "vlan112", "ok"],
                    "row13": [DUT_TARGET_SELECTED_MARK, "通道 13", "vlan113", "ok"],
                }

            def item(self, row_id, option=None, **kwargs):
                if "values" in kwargs:
                    self.rows[row_id] = list(kwargs["values"])
                if option == "values":
                    return tuple(self.rows[row_id])
                return {"values": tuple(self.rows[row_id])}

        window = object.__new__(DutConfigWindow)
        window._trees = {"telnet": FakeTree(), "wifi_2g": FakeTree()}
        window._rows_by_feature = {
            "telnet": {"通道 12": "row12", "通道 13": "row13"},
            "wifi_2g": {"通道 12": "row12", "通道 13": "row13"},
        }
        window._summary_vars = {"telnet": Mock(), "wifi_2g": Mock()}
        window._target_channels = ("通道 12", "通道 13")
        window._selected_target_channels = {"通道 12"}
        window._target_errors_by_channel = {}

        window._sync_target_selection_display()

        for tree in window._trees.values():
            self.assertEqual(tree.rows["row12"][0], DUT_TARGET_SELECTED_MARK)
            self.assertEqual(tree.rows["row12"][-1], "配置完整，等待执行")
            self.assertEqual(tree.rows["row13"][0], DUT_TARGET_UNSELECTED_MARK)
            self.assertEqual(tree.rows["row13"][-1], "未选择，本次跳过")
        for summary in window._summary_vars.values():
            self.assertIn("已选择 1 台", summary.set.call_args.args[0])

    def test_dut_target_selection_click_and_bulk_actions_update_shared_state(self):
        class FakeTree:
            @staticmethod
            def identify_region(_x, _y):
                return "cell"

            @staticmethod
            def identify_column(_x):
                return "#1"

            @staticmethod
            def identify_row(_y):
                return "row12"

            @staticmethod
            def item(_row_id, _option=None):
                return (DUT_TARGET_SELECTED_MARK, "通道 12")

        window = SimpleNamespace(
            _running=False,
            _target_channels=("通道 12", "通道 13"),
            _selected_target_channels={"通道 12"},
            _invalidate_status_after_target_selection_change=Mock(),
            _sync_target_selection_display=Mock(),
        )

        result = DutConfigWindow._on_target_tree_click(
            window, FakeTree(), SimpleNamespace(x=5, y=5)
        )

        self.assertEqual(result, "break")
        self.assertEqual(window._selected_target_channels, set())
        window._invalidate_status_after_target_selection_change.assert_called_once_with()
        window._sync_target_selection_display.assert_called_once_with()

        DutConfigWindow.select_all_targets(window)
        self.assertEqual(
            window._selected_target_channels, {"通道 12", "通道 13"}
        )
        DutConfigWindow.clear_all_targets(window)
        self.assertEqual(window._selected_target_channels, set())

    def test_selected_dut_requests_follow_window_selection_without_changing_main_targets(self):
        requests = [
            DutTelnetEnableRequest(
                channel="通道 12", vlan="vlan112", adapter_alias="VLAN112",
                bind_ip="192.168.1.112", device_host="192.168.1.1",
                subnet_mask="255.255.255.0", username="user", password="pass",
            ),
            DutTelnetEnableRequest(
                channel="通道 13", vlan="vlan113", adapter_alias="VLAN113",
                bind_ip="192.168.1.113", device_host="192.168.1.1",
                subnet_mask="255.255.255.0", username="user", password="pass",
            ),
        ]
        window = Mock()
        window.exists.return_value = True
        window.selected_target_channels.return_value = ("通道 12",)
        context = SimpleNamespace(dut_config_window=window, dut_config_requests=requests)

        selected = LineCheckAssistant._selected_dut_config_requests(context, window)

        self.assertEqual([request.vlan for request in selected], ["vlan112"])
        self.assertEqual([request.vlan for request in requests], ["vlan112", "vlan113"])

    def test_wifi_advanced_requests_increment_ssid_in_selected_target_order(self):
        requests = [
            DutTelnetEnableRequest(
                channel=f"通道 {channel}", vlan=f"vlan1{channel}",
                adapter_alias=f"VLAN1{channel}", bind_ip=f"192.168.1.{channel}",
                device_host="192.168.1.1", subnet_mask="255.255.255.0",
                username="user", password="pass",
            )
            for channel in (12, 13, 15)
        ]
        window = Mock()
        window.exists.return_value = True
        window.selected_target_channels.return_value = (
            "通道 12", "通道 13", "通道 15"
        )
        context = SimpleNamespace(
            dut_config_window=window,
            dut_config_requests=requests,
        )

        advanced = LineCheckAssistant._collect_dut_advanced_requests(
            context,
            "wifi_2g",
            DutWifiSettings(
                band="2.4G", ssid="Aouxue_001", password="password123"
            ),
            increment_wifi_ssid=True,
        )

        self.assertEqual(
            [request.channel for request in advanced],
            ["通道 12", "通道 13", "通道 15"],
        )
        self.assertEqual(
            [request.settings.ssid for request in advanced],
            ["Aouxue_001", "Aouxue_002", "Aouxue_003"],
        )

    def test_dut_config_and_query_entrypoints_use_window_target_selection(self):
        import inspect

        sources = (
            inspect.getsource(LineCheckAssistant._start_dut_telnet_enable),
            inspect.getsource(LineCheckAssistant._query_dut_wan_connections),
            inspect.getsource(LineCheckAssistant._query_dut_current_status),
            inspect.getsource(LineCheckAssistant._collect_dut_advanced_requests),
        )
        for source in sources:
            self.assertIn("_selected_dut_config_requests", source)
        window_source = inspect.getsource(DutConfigWindow._advanced_target_area)
        self.assertIn('text="全选"', window_source)
        self.assertIn('text="清除"', window_source)
        self.assertIn('"selected"', window_source)

    def test_voice_and_tr069_tabs_query_current_status_and_map_common_values(self):
        import inspect

        voice_source = inspect.getsource(DutConfigWindow._build_voice_tab)
        tr069_source = inspect.getsource(DutConfigWindow._build_tr069_tab)
        query_source = inspect.getsource(LineCheckAssistant._query_dut_current_status)
        worker_source = inspect.getsource(LineCheckAssistant._dut_current_status_query_worker)

        self.assertIn('query_text="查询当前语音"', voice_source)
        self.assertIn('query_text="查询当前TR069"', tr069_source)
        self.assertIn('"当前状态"', inspect.getsource(DutConfigWindow._build_current_status_area))
        self.assertIn("不会下发配置命令", query_source)
        self.assertIn("run_dut_status_query_batch(", worker_source)
        self.assertNotIn("UbusHttpClient(", query_source + worker_source)

        voice = DutVoiceSettings(
            line_index="2",
            account_enabled=False,
            display_name="1002",
            sip_mode="IMSSIP",
        )
        voice_values = voice_status_form_values(voice)
        self.assertEqual(voice_values["line_index"], "2")
        self.assertFalse(voice_values["account_enabled"])
        self.assertEqual(voice_values["sip_mode"], "IMSSIP")

        tr069 = DutTr069Settings(
            acs_url="https://acs.example.com/acs",
            periodic_inform_enabled=False,
            manual_inform=True,
        )
        tr069_values = tr069_status_form_values(tr069)
        self.assertEqual(tr069_values["acs_url"], "https://acs.example.com/acs")
        self.assertFalse(tr069_values["periodic_inform_enabled"])
        self.assertNotIn("manual_inform", tr069_values)

    def test_voice_choice_options_follow_dut_reported_capabilities(self):
        options = voice_choice_options(
            DutVoiceSettings(
                dtmf_method="SIPINFO",
                sip_mode="IMSSIP",
                codecs=("G.711 U-law", "G.729", "G.711 U-law", "G.729", "G.711 U-law"),
                supported_dtmf_methods=("RFC2833", "SIPINFO"),
                supported_sip_modes=("SIP", "IMSSIP"),
                supported_codecs=("G.711 U-law", "G.729"),
            )
        )

        self.assertEqual(options["dtmf_method"], ("RFC2833", "SIPINFO"))
        self.assertEqual(options["sip_mode"], ("SIP", "IMSSIP"))
        self.assertEqual(options["codecs"], ("G.711 U-law", "G.729"))

    def test_tr069_capability_fields_disable_unsupported_controls(self):
        class FakeWidget:
            def __init__(self):
                self.state = "normal"

            def configure(self, **kwargs):
                self.state = kwargs["state"]

        window = object.__new__(DutConfigWindow)
        url_widget = FakeWidget()
        certificate_widget = FakeWidget()
        manual_widget = FakeWidget()
        window._tr069_capability_widgets = {
            "acs_url": url_widget,
            "certificate_enabled": certificate_widget,
            "manual_inform": manual_widget,
        }
        window._capability_disabled_widgets = set()
        window.tr069_manual_inform_var = Mock()

        window._apply_tr069_capabilities(("acs_url", "certificate_enabled"))

        self.assertEqual(url_widget.state, "normal")
        self.assertEqual(certificate_widget.state, "normal")
        self.assertEqual(manual_widget.state, "disabled")
        window.tr069_manual_inform_var.set.assert_called_once_with(False)

    def test_wifi_tabs_cover_required_fields_query_and_form_mapping(self):
        import inspect

        builder_source = inspect.getsource(DutConfigWindow._build_wifi_tab)
        update_form_source = inspect.getsource(DutConfigWindow._update_wifi_form)
        settings_source = inspect.getsource(DutConfigWindow.wifi_settings)
        open_source = inspect.getsource(LineCheckAssistant._open_dut_config_module)
        query_source = inspect.getsource(LineCheckAssistant._query_dut_current_status)
        query_worker_source = inspect.getsource(
            LineCheckAssistant._dut_current_status_query_worker
        )
        configure_source = inspect.getsource(LineCheckAssistant._start_dut_advanced_config)
        for label in (
            "WiFi 名称：",
            "WiFi 密码：",
            "信道：",
            "信道带宽：",
            "认证/加密模式：",
            "WiFi 协议类型：",
            "发射功率(%)：",
            "最大接入数：",
            "启用 WiFi",
            "隐藏 WiFi",
            "启用双频合一",
            "启用 WMM",
            "SSID递增",
        ):
            self.assertIn(label, builder_source)
        self.assertIn('"2.4G", "wifi_2g"', inspect.getsource(DutConfigWindow.__init__))
        self.assertIn('"5G", "wifi_5g"', inspect.getsource(DutConfigWindow.__init__))
        self.assertIn("on_start_wifi_2g", open_source)
        self.assertIn("on_start_wifi_5g", open_source)
        self.assertIn("ssid_index=ssid_index", query_worker_source)
        self.assertIn("settings.dual_band_enabled", configure_source)
        self.assertIn("increment_wifi_ssid", configure_source)
        self.assertIn("SSID={request.settings.ssid}", configure_source)
        self.assertIn("[SSID分配]", configure_source)
        self.assertIn('"ssid_increment": BooleanVar(value=False)', builder_source)
        self.assertIn('text=f"{band} 射频参数"', builder_source)
        self.assertIn('text=f"{peer_band} 射频参数（双频合一）"', builder_source)
        self.assertIn('"peer_channel": peer_channel_combo', builder_source)
        self.assertIn("peer_radio_group.grid_remove()", update_form_source)
        self.assertIn("peer_radio = (", settings_source)
        self.assertIn("DutWifiRadioSettings(", settings_source)
        self.assertIn("peer_radio=peer_radio", settings_source)
        self.assertIn(
            '_wifi_vars[feature]["ssid_increment"]',
            inspect.getsource(DutConfigWindow.wifi_ssid_increment_enabled),
        )
        self.assertNotIn("ssid_increment", query_source + query_worker_source)
        self.assertEqual(WIFI_BANDWIDTH_OPTIONS["5G"][-1], "160MHz")
        self.assertIn("WPA3-Personal-Transition", WIFI_SECURITY_MODE_OPTIONS)
        self.assertIn("b,g,n,ax", WIFI_MODE_OPTIONS["2.4G"])

        values = wifi_status_form_values(
            DutWifiSettings(
                band="5G",
                ssid_index="2",
                ssid="Lab_5G",
                password="password123",
                hidden=True,
                dual_band_enabled=True,
                channel_bandwidth="160MHz",
                operating_mode="a,n,ac,ax",
                peer_radio=DutWifiRadioSettings(
                    band="2.4G",
                    channel="6",
                    channel_bandwidth="40MHz",
                    operating_mode="b,g,n,ax",
                ),
            )
        )
        self.assertEqual(values["ssid_index"], "2")
        self.assertEqual(values["ssid"], "Lab_5G")
        self.assertTrue(values["hidden"])
        self.assertTrue(values["dual_band_enabled"])
        self.assertEqual(values["peer_channel"], "6")
        self.assertEqual(values["peer_channel_bandwidth"], "40MHz")

    def test_wifi_choice_options_follow_dut_reported_capabilities(self):
        options = wifi_choice_options(
            DutWifiSettings(
                band="2.4G",
                security_mode="WPA2-Personal",
                channel="auto",
                channel_bandwidth="20/40MHz",
                operating_mode="b,g,n,ax",
                transmit_power="100",
                supported_security_modes=(
                    "None",
                    "WPA2-Personal",
                    "WPA3-Personal-Transition",
                ),
                supported_channels=("auto", "1", "6", "11"),
                supported_bandwidths=("20/40MHz", "20MHz", "40MHz"),
                supported_modes=("b", "b,g", "b,g,n", "b,g,n,ax"),
                supported_transmit_powers=("25", "50", "75", "100"),
            )
        )

        self.assertEqual(
            options["security_mode"],
            ("None", "WPA2-Personal", "WPA3-Personal-Transition"),
        )
        self.assertEqual(options["channel"], ("auto", "1", "6", "11"))
        self.assertEqual(
            options["channel_bandwidth"], ("20/40MHz", "20MHz", "40MHz")
        )
        self.assertEqual(options["operating_mode"], ("b", "b,g", "b,g,n", "b,g,n,ax"))
        self.assertEqual(options["transmit_power"], ("25", "50", "75", "100"))

    def test_wifi_choice_options_fall_back_only_when_dut_omits_capability(self):
        options = wifi_choice_options(
            DutWifiSettings(
                band="5G",
                channel_bandwidth="160MHz",
                operating_mode="a,n,ac,ax",
            )
        )

        self.assertEqual(options["security_mode"], WIFI_SECURITY_MODE_OPTIONS)
        self.assertEqual(options["channel_bandwidth"], WIFI_BANDWIDTH_OPTIONS["5G"])
        self.assertEqual(options["operating_mode"], WIFI_MODE_OPTIONS["5G"])

    def test_dual_band_wifi_choices_keep_radios_independent_and_power_common(self):
        options = wifi_choice_options(
            DutWifiSettings(
                band="2.4G",
                channel="6",
                channel_bandwidth="40MHz",
                operating_mode="b,g,n,ax",
                transmit_power="60",
                dual_band_enabled=True,
                supported_channels=("1", "6", "11"),
                supported_bandwidths=("20MHz", "40MHz"),
                supported_modes=("b,g,n", "b,g,n,ax"),
                supported_transmit_powers=("40", "60", "80"),
                peer_radio=DutWifiRadioSettings(
                    band="5G",
                    channel="44",
                    channel_bandwidth="80MHz",
                    operating_mode="a,n,ac,ax",
                    transmit_power="60",
                    supported_channels=("36", "40", "44", "48"),
                    supported_bandwidths=("40MHz", "80MHz"),
                    supported_modes=("a,n,ac", "a,n,ac,ax"),
                    supported_transmit_powers=("20", "40", "60"),
                ),
            )
        )

        self.assertEqual(options["channel"], ("1", "6", "11"))
        self.assertEqual(options["peer_channel"], ("36", "40", "44", "48"))
        self.assertEqual(options["peer_channel_bandwidth"], ("40MHz", "80MHz"))
        self.assertEqual(options["peer_operating_mode"], ("a,n,ac", "a,n,ac,ax"))
        self.assertEqual(options["transmit_power"], ("40", "60"))

    def test_wifi_target_change_removes_previous_dut_capability_options(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class FakeCombo:
            def __init__(self):
                self.values = ()

            def configure(self, **kwargs):
                self.values = kwargs["values"]

        keys = (
            "security_mode",
            "channel",
            "channel_bandwidth",
            "operating_mode",
            "transmit_power",
        )
        window = object.__new__(DutConfigWindow)
        window._wifi_vars = {
            "wifi_2g": {key: FakeVar("OLD_DUT_ONLY") for key in keys}
        }
        window._wifi_choice_widgets = {
            "wifi_2g": {key: FakeCombo() for key in keys}
        }
        window._wifi_supported_options = {
            "wifi_2g": {key: ("OLD_DUT_ONLY",) for key in keys}
        }

        window._reset_wifi_choice_options("wifi_2g")

        for key in keys:
            self.assertNotIn(
                "OLD_DUT_ONLY", window._wifi_choice_widgets["wifi_2g"][key].values
            )
        self.assertEqual(
            window._wifi_vars["wifi_2g"]["security_mode"].get(), "WPA2-Personal"
        )
        self.assertEqual(window._wifi_vars["wifi_2g"]["channel"].get(), "auto")

    def test_telnet_and_wan_tabs_also_show_current_status_without_duplicate_wan_query(self):
        import inspect

        window_source = inspect.getsource(DutConfigWindow.__init__)
        wan_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        telnet_query_source = inspect.getsource(LineCheckAssistant._query_dut_telnet_status)
        wan_finish_source = inspect.getsource(LineCheckAssistant._finish_dut_wan_query)

        self.assertIn('text="查询当前Telnet"', window_source)
        self.assertIn('telnet_tab, "telnet"', window_source)
        self.assertIn('tab, "wan"', wan_source)
        self.assertIn('self._query_dut_current_status("telnet")', telnet_query_source)
        self.assertIn("set_wan_current_status_results(results)", wan_finish_source)
        self.assertNotIn(
            "run_dut_wan_query_batch",
            inspect.getsource(DutConfigWindow.set_wan_current_status_results),
        )

        telnet_text = DutConfigWindow._telnet_status_text(
            DutTelnetStatus(
                access_control_enabled=True,
                rule_present=True,
                rule_enabled=True,
                source_interfaces=("lan",),
                tcp_port_open=True,
                probe_message="TCP 23可连接",
            )
        )
        self.assertIn("AccessCtrl总开关=启用", telnet_text)
        self.assertIn("TCP 23=可连接", telnet_text)

        request = DutTelnetEnableRequest(
            channel="通道 8",
            vlan="vlan113",
            adapter_alias="VLAN113",
            bind_ip="192.168.1.113",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="user",
            password="password",
        )
        info = DutWanConnectionInfo(
            name="3_INTERNET_R_VID_172",
            mode="router",
            service_type="INTERNET",
            vlan_id="172",
        )
        result = DutWanQueryResult(
            request, True, "completed", "ok", (info.name,), (info,)
        )
        window = object.__new__(DutConfigWindow)
        window.clear_current_status = Mock()

        window.set_wan_current_status_results((result,))

        status_text = window.clear_current_status.call_args.args[1]
        self.assertIn("通道 8", status_text)
        self.assertIn("3_INTERNET_R_VID_172", status_text)
        self.assertIn("VLAN 172", status_text)

    def test_dut_current_status_heights_round_trip_and_clamp_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dut-ui-state.json"

            self.assertTrue(
                save_dut_current_status_heights(
                    path,
                    {"telnet": 9, "wan": 99, "wifi_2g": 1, "unknown": 7},
                )
            )
            self.assertEqual(
                load_dut_current_status_heights(path),
                {
                    "telnet": 9,
                    "wan": DUT_CURRENT_STATUS_MAX_HEIGHT,
                    "wifi_2g": DUT_CURRENT_STATUS_MIN_HEIGHT,
                },
            )
            self.assertEqual(clamp_dut_current_status_height("bad"), 4)
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(load_dut_current_status_heights(path), {})

    def test_dut_current_status_drag_resizes_and_persists_each_tab(self):
        class FakeText:
            def __init__(self, height):
                self.height = height

            def cget(self, name):
                self.assert_height_name(name)
                return self.height

            def configure(self, **kwargs):
                self.height = kwargs["height"]

            @staticmethod
            def assert_height_name(name):
                if name != "height":
                    raise AssertionError(name)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dut-ui-state.json"
            window = object.__new__(DutConfigWindow)
            window._current_status_texts = {
                "telnet": FakeText(4),
                "wan": FakeText(7),
            }
            window._current_status_heights = {}
            window._current_status_drag = {}
            window._state_path = path

            self.assertEqual(window._begin_current_status_resize("telnet", 100), "break")
            self.assertEqual(window._drag_current_status_resize("telnet", 172), "break")
            self.assertEqual(window._finish_current_status_resize("telnet"), "break")

            self.assertEqual(window._current_status_texts["telnet"].height, 8)
            self.assertEqual(
                load_dut_current_status_heights(path), {"telnet": 8, "wan": 7}
            )
            builder_source = __import__("inspect").getsource(
                DutConfigWindow._build_current_status_area
            )
            self.assertIn("拖动调整当前状态高度", builder_source)
            self.assertIn('"<B1-Motion>"', builder_source)

    def test_dut_window_size_round_trip_preserves_status_and_fits_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dut-ui-state.json"

            self.assertTrue(
                save_dut_current_status_heights(path, {"telnet": 8, "wan": 6})
            )
            self.assertTrue(save_dut_window_size(path, 1800, 1000))
            self.assertEqual(
                load_dut_window_size(
                    path, screen_width=1920, screen_height=1080
                ),
                (1800, 1000),
            )
            self.assertEqual(
                load_dut_current_status_heights(path),
                {"telnet": 8, "wan": 6},
            )

            self.assertTrue(
                save_dut_current_status_heights(path, {"telnet": 9})
            )
            self.assertEqual(
                load_dut_window_size(
                    path, screen_width=1600, screen_height=900
                ),
                (1600, 900),
            )
            self.assertEqual(
                clamp_dut_window_size("bad", None),
                (DUT_CONFIG_DEFAULT_WIDTH, DUT_CONFIG_DEFAULT_HEIGHT),
            )

            constructor_source = __import__("inspect").getsource(
                DutConfigWindow.__init__
            )
            destroy_source = __import__("inspect").getsource(
                DutConfigWindow.destroy
            )
            self.assertIn("load_dut_window_size(", constructor_source)
            self.assertIn("self.window.geometry", constructor_source)
            self.assertIn("save_dut_window_size", destroy_source)

    def test_dut_current_status_resize_stops_before_bottom_actions_are_clipped(self):
        class FakeText:
            def __init__(self, height):
                self.height = height

            def cget(self, name):
                if name != "height":
                    raise AssertionError(name)
                return self.height

            def configure(self, **kwargs):
                self.height = kwargs["height"]

        class FakeTab:
            @staticmethod
            def winfo_ismapped():
                return True

            @staticmethod
            def winfo_rooty():
                return 100

            @staticmethod
            def winfo_height():
                return 400

        class FakeActions:
            def __init__(self, text):
                self.text = text

            @staticmethod
            def winfo_ismapped():
                return True

            def winfo_rooty(self):
                return 270 + self.text.height * 18

            @staticmethod
            def winfo_height():
                return 40

            @staticmethod
            def winfo_reqheight():
                return 40

        class FakeWindow:
            @staticmethod
            def update_idletasks():
                return None

            @staticmethod
            def winfo_rooty():
                return 50

            @staticmethod
            def winfo_height():
                return 600

        class FakeBottomArea:
            @staticmethod
            def winfo_ismapped():
                return True

            @staticmethod
            def winfo_rooty():
                return 400

            @staticmethod
            def winfo_height():
                return 90

            @staticmethod
            def winfo_reqheight():
                return 90

        class FakePackTab:
            def __init__(self):
                self.first_slave = object()

            def pack_slaves(self):
                return [self.first_slave]

        class FakePackedActions:
            def __init__(self):
                self.pack_options = None

            def pack(self, **kwargs):
                self.pack_options = kwargs

        text = FakeText(4)
        window = object.__new__(DutConfigWindow)
        window.window = FakeWindow()
        window._current_status_texts = {"telnet": text}
        window._current_status_tabs = {"telnet": FakeTab()}
        window._current_status_action_frames = {"telnet": FakeActions(text)}
        window._current_status_bottom_areas = {"telnet": FakeBottomArea()}

        effective = window._fit_current_status_height("telnet", 16)

        self.assertEqual(effective, 10)
        self.assertEqual(text.height, 10)
        self.assertTrue(window._bottom_actions_fully_visible("telnet"))

        class FakeCompressedActions(FakeActions):
            @staticmethod
            def winfo_height():
                return 20

        window._current_status_action_frames["telnet"] = FakeCompressedActions(text)
        self.assertFalse(window._bottom_actions_fully_visible("telnet"))

        class FakeCompressedBottomArea(FakeBottomArea):
            @staticmethod
            def winfo_height():
                return 50

        window._current_status_action_frames["telnet"] = FakeActions(text)
        window._current_status_bottom_areas["telnet"] = FakeCompressedBottomArea()
        self.assertFalse(window._bottom_actions_fully_visible("telnet"))

        constructor_source = __import__("inspect").getsource(DutConfigWindow.__init__)
        target_source = __import__("inspect").getsource(
            DutConfigWindow._advanced_target_area
        )
        self.assertIn('_current_status_action_frames["telnet"]', constructor_source)
        self.assertIn('"<<NotebookTabChanged>>"', constructor_source)
        self.assertIn("_current_status_action_frames[feature]", target_source)
        self.assertIn("_pack_protected_bottom_area(telnet_tab, footer)", constructor_source)
        self.assertIn('_current_status_bottom_areas["telnet"] = footer', constructor_source)
        self.assertIn("ttk.Label(footer, textvariable=self.summary_var", constructor_source)
        self.assertIn("actions = ttk.Frame(footer)", constructor_source)
        self.assertIn("_pack_protected_bottom_area(tab, footer)", target_source)
        self.assertIn("_current_status_bottom_areas[feature] = footer", target_source)
        self.assertIn("ttk.Label(footer, textvariable=summary_var", target_source)
        self.assertIn("actions = ttk.Frame(footer)", target_source)

        pack_tab = FakePackTab()
        packed_actions = FakePackedActions()
        DutConfigWindow._pack_protected_bottom_area(pack_tab, packed_actions)
        self.assertEqual(packed_actions.pack_options["side"], "bottom")
        self.assertEqual(packed_actions.pack_options["fill"], "x")
        self.assertIs(
            packed_actions.pack_options["before"], pack_tab.first_slave
        )

    def test_status_display_only_applies_settings_when_batch_has_safe_common_value(self):
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="VLAN112",
            bind_ip="192.168.1.112",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="user",
            password="password",
        )
        settings = DutVoiceSettings(line_index="1", sip_mode="IMSSIP")
        result = DutAdvancedQueryResult(
            request, "voice", True, "completed", "ok", settings
        )
        window = object.__new__(DutConfigWindow)
        window.apply_current_status = Mock()
        window.clear_current_status = Mock()

        window.set_current_status_results("voice", (result,), None)

        window.apply_current_status.assert_not_called()
        self.assertIn(
            "未使用任意一台覆盖当前配置表单",
            window.clear_current_status.call_args.args[1],
        )

        window.set_current_status_results("voice", (result,), settings)

        window.apply_current_status.assert_called_once_with("voice", settings)
        self.assertIn(
            "同步到当前配置表单",
            window.clear_current_status.call_args.args[1],
        )

    def test_dut_success_row_uses_concise_operator_message(self):
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="VLAN112",
            bind_ip="192.168.1.112",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="user",
            password="password",
        )
        result = DutTelnetEnableResult(
            request,
            True,
            "completed",
            "Telnet 已开启并验证可用：192.168.1.112 -> 192.168.1.1:23（LAN-telnet 规则已就绪）",
        )
        window = object.__new__(DutConfigWindow)
        window._row_by_channel = {"通道 12": "row-12"}
        window.target_tree = Mock()
        window.target_tree.item.side_effect = [
            ("通道 12", "vlan112", "VLAN112", "192.168.1.112", "192.168.1.1", "等待执行"),
            None,
        ]

        window.update_result(result)

        self.assertEqual(
            window.target_tree.item.call_args_list[-1],
            call(
                "row-12",
                values=[
                    "通道 12",
                    "vlan112",
                    "VLAN112",
                    "192.168.1.112",
                    "192.168.1.1",
                    "成功：Telnet 已开启并验证可用",
                ],
            ),
        )

    def test_dut_option_checkbuttons_use_native_checkmark_indicator(self):
        """DUT 各 Tab 的选项框应使用原生勾号，不受 Clam 叉号样式影响。"""
        import inspect

        helper_source = inspect.getsource(DutConfigWindow._native_checkbutton)
        builder_source = "\n".join(
            (
                inspect.getsource(DutConfigWindow._build_wan_tab),
                inspect.getsource(DutConfigWindow._build_voice_tab),
                inspect.getsource(DutConfigWindow._build_tr069_tab),
                inspect.getsource(DutConfigWindow._build_wifi_tab),
            )
        )

        self.assertIn("Checkbutton(", helper_source)
        self.assertIn("selectcolor=DUT_CHECK_BACKGROUND", helper_source)
        self.assertIn("background=DUT_CHECK_BACKGROUND", helper_source)
        self.assertNotIn("ttk.Checkbutton(", builder_source)
        self.assertEqual(builder_source.count("self._native_checkbutton("), 8)
        for label in (
            "启用 NAT",
            "启用 SIP 账号",
            "启用周期 Inform",
            "启用 HTTP 连接请求",
            "启用证书",
            "配置后手动 Inform",
            "启用 WiFi",
            "隐藏 WiFi",
            "启用双频合一",
            "启用 WMM",
            "SSID递增",
        ):
            self.assertIn(label, builder_source)
        self.assertIn('text=f"LAN{port}"', builder_source)
        self.assertIn("command=self._sync_wan_port_bind_from_checks", builder_source)

    def test_voice_sip_mode_options_include_ont_imssip_without_removing_existing_modes(self):
        import inspect

        voice_source = inspect.getsource(DutConfigWindow._build_voice_tab)

        self.assertEqual(
            VOICE_SIP_MODE_OPTIONS,
            ("SIP", "IMSSIP", "UDP", "TCP", "TLS"),
        )
        self.assertIn('"SIP 模式："', voice_source)
        self.assertIn("values=VOICE_SIP_MODE_OPTIONS", voice_source)

    def test_dut_form_field_names_are_left_aligned_in_every_tab(self):
        import inspect

        field_source = inspect.getsource(DutConfigWindow._field)
        wan_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        voice_source = inspect.getsource(DutConfigWindow._build_voice_tab)
        tr069_source = inspect.getsource(DutConfigWindow._build_tr069_tab)
        wifi_source = inspect.getsource(DutConfigWindow._build_wifi_tab)
        window_source = inspect.getsource(DutConfigWindow)

        self.assertIn('anchor="w"', field_source)
        self.assertIn('sticky="w"', field_source)
        self.assertIn('text="现有连接名/索引：", anchor="w"', wan_source)
        self.assertIn('index_label.grid(row=0, column=2, sticky="w"', wan_source)
        self.assertIn("self._field(", wan_source)
        self.assertIn("self._field(", voice_source)
        self.assertIn("self._field(", tr069_source)
        self.assertIn("self._field(", wifi_source)
        self.assertNotIn('sticky="e"', window_source)
        self.assertNotIn('anchor="e"', window_source)

    def test_wan_form_rules_hide_irrelevant_fields_and_apply_protocol_mtu(self):
        import inspect

        ipoe = resolve_wan_form_rules("新增", "路由", "IPoE", "IPv4", "DHCP", "SLAAC")
        pppoe = resolve_wan_form_rules("新增", "路由", "PPPoE", "IPv6", "DHCP", "DHCPv6")
        bridge = resolve_wan_form_rules("新增", "桥接", "IPoE", "IPv4", "DHCP", "SLAAC")
        delete = resolve_wan_form_rules("删除", "路由", "IPoE", "IPv4", "DHCP", "SLAAC")

        self.assertEqual(ipoe.mtu_default, "1500")
        self.assertFalse(ipoe.show_pppoe_credentials)
        self.assertTrue(ipoe.show_ipv4_selector)
        self.assertFalse(ipoe.show_ipv4_static)
        self.assertEqual(pppoe.mtu_default, "1492")
        self.assertTrue(pppoe.show_pppoe_credentials)
        self.assertFalse(pppoe.show_ipv4_selector)
        self.assertTrue(pppoe.show_ipv6_selector)
        self.assertFalse(bridge.show_router)
        self.assertFalse(delete.show_config)
        self.assertTrue(delete.show_index)
        builder_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        updater_source = inspect.getsource(DutConfigWindow._update_wan_form_visibility)
        self.assertIn('trace_add("write"', builder_source)
        self.assertIn('self.wan_mtu_var.set("1492"', updater_source)
        self.assertIn('"wan_pppoe_username": rules.show_pppoe_credentials', updater_source)
        self.assertIn("grid_remove()", updater_source)

    def test_wan_address_modes_follow_supported_dual_stack_combinations(self):
        self.assertEqual(
            normalize_wan_address_modes("PPPoE", "IPv4+IPv6（双栈）", "静态", "静态"),
            ("DHCP", "SLAAC"),
        )
        self.assertEqual(
            normalize_wan_address_modes(
                "IPoE", "IPv4+IPv6（双栈）", "静态", "SLAAC", changed="ipv4_type"
            ),
            ("静态", "静态"),
        )
        self.assertEqual(
            normalize_wan_address_modes(
                "IPoE", "IPv4+IPv6（双栈）", "DHCP", "静态", changed="ipv6_type"
            ),
            ("静态", "静态"),
        )

    def test_wan_lan_port_multiselect_maps_masks_and_preserves_non_lan_bits(self):
        class Var:
            def __init__(self, value=False):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        self.assertEqual(wan_lan_ports_from_port_bind("8"), (4,))
        self.assertEqual(wan_lan_ports_from_port_bind("1&&8"), (1, 4))
        self.assertEqual(wan_lan_ports_from_port_bind("129"), (1, 8))
        self.assertEqual(wan_port_bind_from_lan_ports((1, 4)), "9")
        self.assertEqual(wan_port_bind_from_lan_ports((8,), preserved_mask=256), "384")

        context = SimpleNamespace(
            wan_lan_port_vars=tuple(Var() for _port in range(8)),
            wan_port_bind_var=Var("0"),
            _wan_non_lan_port_bind_mask=0,
        )
        DutConfigWindow._set_wan_port_bind_selection(context, "264")
        self.assertFalse(context.wan_lan_port_vars[0].get())
        self.assertTrue(context.wan_lan_port_vars[3].get())
        self.assertEqual(context._wan_non_lan_port_bind_mask, 256)
        DutConfigWindow._sync_wan_port_bind_from_checks(context)
        self.assertEqual(context.wan_port_bind_var.get(), "264")

    def test_iptv_multicast_vlan_field_is_conditional_and_mapped(self):
        import inspect

        iptv = resolve_wan_form_rules(
            "新增", "路由", "IPoE", "IPv4", "DHCP", "SLAAC", service_type="IPTV"
        )
        bridge_iptv = resolve_wan_form_rules(
            "修改", "桥接", "IPoE", "IPv4", "DHCP", "SLAAC", service_type="IPTV"
        )
        internet = resolve_wan_form_rules(
            "新增", "路由", "IPoE", "IPv4", "DHCP", "SLAAC", service_type="INTERNET"
        )
        delete = resolve_wan_form_rules(
            "删除", "路由", "IPoE", "IPv4", "DHCP", "SLAAC", service_type="IPTV"
        )
        values = wan_connection_form_values(
            DutWanConnectionInfo(
                name="5_IPTV_R_VID_600",
                service_type="IPTV",
                vlan_id="600",
                multicast_vlan_id="222",
            )
        )

        self.assertTrue(iptv.show_multicast_vlan)
        self.assertTrue(bridge_iptv.show_multicast_vlan)
        self.assertFalse(internet.show_multicast_vlan)
        self.assertFalse(delete.show_multicast_vlan)
        self.assertEqual(values["multicast_vlan_id"], "222")
        builder_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        updater_source = inspect.getsource(DutConfigWindow._update_wan_form_visibility)
        settings_source = inspect.getsource(DutConfigWindow.wan_settings)
        self.assertIn('"组播 VLAN ID："', builder_source)
        self.assertIn('(self.wan_service_type_var, "service_type")', builder_source)
        self.assertIn('"wan_multicast_vlan_id": rules.show_multicast_vlan', updater_source)
        self.assertIn("multicast_vlan_id=self.wan_multicast_vlan_id_var.get().strip()", settings_source)

    def test_wan_existing_connections_use_readonly_query_dropdown(self):
        import inspect

        builder_source = inspect.getsource(DutConfigWindow._build_wan_tab)
        query_source = inspect.getsource(LineCheckAssistant._query_dut_wan_connections)
        worker_source = inspect.getsource(LineCheckAssistant._dut_wan_query_worker)
        finish_source = inspect.getsource(LineCheckAssistant._finish_dut_wan_query)

        self.assertIn("self.wan_index_combo = ttk.Combobox(", builder_source)
        self.assertIn('state="readonly"', builder_source)
        self.assertIn('text="查询现有 WAN"', builder_source)
        self.assertIn("run_dut_wan_query_batch(", worker_source)
        self.assertIn("common_wan_connection_names(results)", finish_source)
        self.assertIn("common_wan_connection_details(results)", finish_source)
        self.assertIn('"<<ComboboxSelected>>"', builder_source)
        self.assertNotIn("UbusHttpClient(", query_source + worker_source)
        self.assertNotIn("bbfdm.", query_source + worker_source)

    @patch("line_check_assistant.app.messagebox.showinfo")
    def test_finish_wan_query_populates_only_common_connections(self, showinfo):
        window = Mock()
        window.exists.return_value = True
        context = SimpleNamespace(
            dut_config_running=True,
            dut_config_active_feature="wan_query",
            dut_config_cancel_event=threading.Event(),
            dut_config_window=window,
            _log=Mock(),
        )
        request_a = DutTelnetEnableRequest(
            "通道 12", "vlan112", "VLAN112", "192.168.1.112", "192.168.1.1",
            "255.255.255.0", "user", "password",
        )
        request_b = DutTelnetEnableRequest(
            "通道 13", "vlan113", "VLAN113", "192.168.1.113", "192.168.1.1",
            "255.255.255.0", "user", "password",
        )
        results = [
            DutWanQueryResult(
                request_a, True, "completed", "ok",
                ("3_INTERNET_R_VID_200", "5_IPTV_B_VID_600"),
            ),
            DutWanQueryResult(
                request_b, True, "completed", "ok",
                ("3_VOICE_R_VID_335", "5_IPTV_B_VID_600"),
            ),
        ]

        LineCheckAssistant._finish_dut_wan_query(context, results)

        window.set_wan_connections.assert_called_once_with(
            ("5_IPTV_B_VID_600",), target_count=2, connection_details={}
        )
        self.assertFalse(context.dut_config_running)
        showinfo.assert_called_once()

    def test_wan_connection_snapshot_maps_to_current_form_values(self):
        values = wan_connection_form_values(
            DutWanConnectionInfo(
                name="3_INTERNET_R_VID_172",
                index="3",
                mode="router",
                service_type="INTERNET",
                vlan_id="172",
                vlan_priority="0",
                port_bind="9",
                mtu="1500",
                nat_enabled=True,
                access_type="IPoE",
                ip_protocol="IPv4IPv6",
                ipv4_type="Dynamic",
                ipv6_type="DHCPv6",
            )
        )

        self.assertEqual(values["mode"], "路由")
        self.assertEqual(values["service_type"], "INTERNET")
        self.assertEqual(values["vlan_id"], "172")
        self.assertEqual(values["port_bind"], "9")
        self.assertEqual(values["ip_protocol"], "IPv4+IPv6（双栈）")
        self.assertEqual(values["ipv4_type"], "DHCP")
        self.assertEqual(values["ipv6_type"], "DHCPv6")

    def test_selecting_existing_wan_replaces_stale_form_values(self):
        class Var:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        info = DutWanConnectionInfo(
            name="3_INTERNET_R_VID_172",
            index="3",
            mode="router",
            service_type="INTERNET",
            vlan_id="172",
            vlan_priority="0",
            port_bind="0",
            mtu="1500",
            nat_enabled=True,
            access_type="IPoE",
            ip_protocol="IPv4",
            ipv4_type="Dynamic",
        )
        context = SimpleNamespace(
            wan_index_var=Var(info.name),
            _wan_connection_details={info.name: info},
            _updating_wan_form=False,
            _last_wan_access_type="PPPoE",
            _update_wan_form_visibility=Mock(),
            wan_query_status_var=Var(),
            wan_nat_var=Var(False),
            _set_wan_port_bind_selection=Mock(),
        )
        field_keys = (
            "mode", "service_type", "vlan_id", "multicast_vlan_id", "vlan_priority", "port_bind", "mtu",
            "access_type", "ip_protocol", "ipv4_type", "ipv4_address", "ipv4_netmask",
            "ipv4_gateway", "ipv4_primary_dns", "ipv4_secondary_dns", "ipv6_type",
            "ipv6_address", "ipv6_prefix", "ipv6_gateway", "ipv6_primary_dns",
            "ipv6_secondary_dns", "pppoe_username", "pppoe_password",
        )
        for key in field_keys:
            setattr(context, f"wan_{key}_var", Var("stale-value"))

        DutConfigWindow._apply_selected_wan_connection(context)

        self.assertEqual(context.wan_service_type_var.get(), "INTERNET")
        self.assertEqual(context.wan_vlan_id_var.get(), "172")
        self.assertEqual(context.wan_multicast_vlan_id_var.get(), "")
        self.assertEqual(context.wan_access_type_var.get(), "IPoE")
        self.assertEqual(context.wan_ip_protocol_var.get(), "IPv4")
        self.assertEqual(context.wan_pppoe_username_var.get(), "")
        self.assertEqual(context.wan_pppoe_password_var.get(), "")
        self.assertTrue(context.wan_nat_var.get())
        context._set_wan_port_bind_selection.assert_called_once_with("0")
        context._update_wan_form_visibility.assert_called_once_with("snapshot")
        self.assertIn("已同步当前 WAN 完整信息", context.wan_query_status_var.get())

    def test_dut_request_snapshot_uses_enabled_channel_and_plaintext_shared_password(self):
        context = SimpleNamespace(
            _capture_current_channel=Mock(),
            parameter_initial_username_var=Mock(get=Mock(return_value="telecomadmin")),
            parameter_initial_password_var=Mock(get=Mock(return_value="plain-password")),
            channels=[
                ChannelConfig(
                    section="channel_12",
                    vlan_name="VLAN112",
                    adapter_alias="VLAN112",
                    network_card_ip="192.168.1.112",
                    device_manage_ip="192.168.1.1",
                    enabled=True,
                ),
                ChannelConfig(section="channel_13", enabled=False),
            ],
        )

        requests = LineCheckAssistant._collect_dut_telnet_requests(context)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].channel, "通道 12")
        self.assertEqual(requests[0].vlan, "vlan112")
        self.assertEqual(requests[0].password, "plain-password")

    def test_start_dut_telnet_enable_confirms_and_starts_background_batch(self):
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="VLAN112",
            bind_ip="192.168.1.112",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="telecomadmin",
            password="plain-password",
        )
        unselected_invalid = DutTelnetEnableRequest(
            channel="通道 13",
            vlan="vlan113",
            adapter_alias="",
            bind_ip="",
            device_host="",
            subnet_mask="255.255.255.0",
            username="telecomadmin",
            password="plain-password",
        )
        window = Mock()
        window.exists.return_value = True
        window.parallel_count.return_value = "8"
        window.selected_target_channels.return_value = ("通道 12",)
        context = SimpleNamespace(
            dut_config_running=False,
            dut_config_window=window,
            dut_config_requests=[request, unselected_invalid],
            dut_config_validation_errors={"通道 13": "配置错误：未配置"},
            dut_config_cancel_event=None,
            _refresh_dut_config_targets=Mock(),
            _dut_telnet_enable_worker=Mock(),
            _log=Mock(),
        )
        thread = Mock()
        with patch("line_check_assistant.app.messagebox.askyesno", return_value=True), \
             patch("line_check_assistant.app.threading.Thread", return_value=thread) as thread_class:
            LineCheckAssistant._start_dut_telnet_enable(context)

        self.assertTrue(context.dut_config_running)
        self.assertIsInstance(context.dut_config_cancel_event, __import__("threading").Event)
        window.mark_all_pending.assert_called_once_with()
        window.set_running.assert_called_once_with(True)
        thread_class.assert_called_once()
        started_requests = thread_class.call_args.kwargs["args"][0]
        self.assertEqual([item.channel for item in started_requests], ["通道 12"])
        thread.start.assert_called_once_with()

    def test_start_dut_config_requires_a_window_selected_target(self):
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="VLAN112",
            bind_ip="192.168.1.112",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="telecomadmin",
            password="plain-password",
        )
        window = Mock()
        window.exists.return_value = True
        window.selected_target_channels.return_value = ()
        context = SimpleNamespace(
            dut_config_running=False,
            dut_config_window=window,
            dut_config_requests=[request],
            _refresh_dut_config_targets=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.showwarning") as warning, \
             patch("line_check_assistant.app.threading.Thread") as thread_class:
            LineCheckAssistant._start_dut_telnet_enable(context)

        self.assertIn("DUT配置目标表", warning.call_args.args[1])
        thread_class.assert_not_called()

    def test_stop_dut_telnet_enable_sets_shared_cancel_event(self):
        cancel_event = __import__("threading").Event()
        window = Mock()
        window.exists.return_value = True
        context = SimpleNamespace(
            dut_config_running=True,
            dut_config_cancel_event=cancel_event,
            dut_config_window=window,
            _log=Mock(),
        )

        LineCheckAssistant._stop_dut_telnet_enable(context)

        self.assertTrue(cancel_event.is_set())
        window.set_running.assert_called_once_with(True, stopping=True)

    def test_finish_dut_telnet_enable_restores_ui_and_summarizes(self):
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="VLAN112",
            bind_ip="192.168.1.112",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="user",
            password="pass",
        )
        window = Mock()
        window.exists.return_value = True
        context = SimpleNamespace(
            dut_config_running=True,
            dut_config_cancel_event=__import__("threading").Event(),
            dut_config_window=window,
            _log=Mock(),
        )
        result = DutTelnetEnableResult(request, True, "completed", "ok")

        with patch("line_check_assistant.app.messagebox.showinfo") as showinfo:
            LineCheckAssistant._finish_dut_telnet_enable(context, [result])

        self.assertFalse(context.dut_config_running)
        self.assertIsNone(context.dut_config_cancel_event)
        window.set_running.assert_called_once_with(False)
        self.assertIn("成功 1", window.set_summary.call_args.args[0])
        showinfo.assert_called_once()

    def test_complex_config_windows_use_standard_toplevel_lifecycle(self):
        """异常窗口必须和其它正常窗口一样交由Tk主事件循环首次绘制。"""
        import inspect

        test_item_source = inspect.getsource(LineCheckAssistant._open_test_item_config)
        dut_init_source = inspect.getsource(DutConfigWindow.__init__)
        dut_show_source = inspect.getsource(DutConfigWindow.show)
        first_show_source = test_item_source[
            test_item_source.index("dialog = Toplevel") : test_item_source.index("def close_dialog")
        ]

        for source in (first_show_source, dut_init_source):
            self.assertNotIn("withdraw(", source)
            self.assertNotIn("deiconify(", source)
            self.assertNotIn("update_idletasks(", source)
            self.assertNotIn(".update()", source)
        self.assertNotIn("after(0", test_item_source)
        self.assertNotIn("after(0", dut_init_source)
        self.assertIn("self.test_item_config_window.deiconify()", test_item_source)
        self.assertIn("self.test_item_config_window.lift()", test_item_source)
        self.assertIn("self.test_item_config_window.focus_force()", test_item_source)
        self.assertIn("self.window.deiconify()", dut_show_source)
        self.assertIn("self.window.lift()", dut_show_source)
        self.assertIn("self.window.focus_force()", dut_show_source)
        self.assertIn("schedule_toplevel_client_refresh(", test_item_source)
        self.assertIn("on_first_refresh=lambda", test_item_source)
        self.assertIn("schedule_toplevel_client_refresh(", dut_init_source)
        self.assertIn("schedule_toplevel_client_refresh(self.window)", dut_show_source)

    def test_clicking_main_window_lifts_it_without_forcing_widget_focus(self):
        import inspect

        context = SimpleNamespace(lift=Mock())

        LineCheckAssistant._bring_main_window_to_front(context)

        context.lift.assert_called_once_with()
        handler_source = inspect.getsource(
            LineCheckAssistant._bring_main_window_to_front
        )
        init_source = inspect.getsource(LineCheckAssistant.__init__)
        self.assertIn('"<ButtonPress-1>"', init_source)
        self.assertIn("self._bring_main_window_to_front", init_source)
        self.assertIn('add="+"', init_source)
        self.assertNotIn("focus_force", handler_source)

    def test_non_modal_feature_windows_do_not_stay_transient_above_main(self):
        import inspect

        from line_check_assistant.pipeline_window import PipelineWindow

        non_modal_sources = (
            inspect.getsource(LineCheckAssistant._open_sample_parameter_writer),
            inspect.getsource(LineCheckAssistant._open_onu_registration_module),
            inspect.getsource(LineCheckAssistant._open_upgrade_module),
            inspect.getsource(LineCheckAssistant._open_test_item_config),
            inspect.getsource(DutConfigWindow.__init__),
            inspect.getsource(PipelineWindow.__init__),
        )
        for source in non_modal_sources:
            self.assertNotIn(".transient(", source)

        for modal_source in (
            inspect.getsource(LineCheckAssistant._open_parameter_generator),
            inspect.getsource(LineCheckAssistant._select_power_com_port),
        ):
            self.assertIn(".transient(", modal_source)
            self.assertIn(".grab_set()", modal_source)

    def test_toplevel_client_refresh_pulses_and_restores_geometry(self):
        from src.ui.window_paint import schedule_toplevel_client_refresh

        class FakeWindow:
            def __init__(self):
                self.callbacks = []
                self.geometry_calls = []
                self.idle_updates = 0

            def after(self, delay, callback):
                self.callbacks.append((delay, callback))

            def winfo_exists(self):
                return True

            def state(self):
                return "normal"

            def update_idletasks(self):
                self.idle_updates += 1

            def winfo_width(self):
                return 960

            def winfo_height(self):
                return 940

            def winfo_x(self):
                return 10

            def winfo_y(self):
                return 20

            def winfo_screenwidth(self):
                return 1920

            def geometry(self, value):
                self.geometry_calls.append(value)

        refreshed = []
        window = FakeWindow()
        schedule_toplevel_client_refresh(
            window,
            on_first_refresh=lambda: refreshed.append(True),
        )

        self.assertEqual(
            [delay for delay, _callback in window.callbacks],
            [20, 120, 360],
        )
        for _delay, callback in window.callbacks:
            callback()
        self.assertEqual(
            window.geometry_calls,
            [
                "961x940+10+20",
                "960x940+10+20",
                "961x940+10+20",
                "960x940+10+20",
                "961x940+10+20",
                "960x940+10+20",
            ],
        )
        self.assertEqual(window.idle_updates, 9)
        self.assertEqual(refreshed, [True])

    def test_center_toplevel_uses_parent_screen_coordinates(self):
        from src.ui.window_paint import center_toplevel_on_parent

        window = Mock()
        window.winfo_width.return_value = 800
        window.winfo_reqwidth.return_value = 1500
        window.winfo_height.return_value = 600
        window.winfo_reqheight.return_value = 900
        parent = Mock()
        parent.winfo_width.return_value = 1200
        parent.winfo_height.return_value = 800
        parent.winfo_rootx.return_value = 1920
        parent.winfo_rooty.return_value = 40

        position = center_toplevel_on_parent(window, parent)

        self.assertEqual(position, "+2120+140")
        window.geometry.assert_called_once_with("+2120+140")

        window.reset_mock()
        position = center_toplevel_on_parent(
            window,
            parent,
            window_width=960,
            window_height=940,
        )

        self.assertEqual(position, "+2040-30")
        window.geometry.assert_called_once_with("+2040-30")
        window.update_idletasks.assert_not_called()
        parent.update_idletasks.assert_not_called()

    def test_toolbar_feature_windows_use_shared_centering(self):
        import inspect

        from line_check_assistant.pipeline_window import PipelineWindow
        from src.ui.serial_terminal import SerialTerminalWindow

        app_methods = (
            LineCheckAssistant._open_sample_parameter_writer,
            LineCheckAssistant._open_upgrade_module,
            LineCheckAssistant._open_onu_registration_module,
            LineCheckAssistant._select_power_com_port,
        )
        for method in app_methods:
            self.assertIn(
                "center_toplevel_on_parent(dialog, self)",
                inspect.getsource(method),
            )
        test_item_source = inspect.getsource(
            LineCheckAssistant._open_test_item_config
        )
        self.assertIn("center_toplevel_on_parent(", test_item_source)
        self.assertIn("window_width=960", test_item_source)
        self.assertIn("window_height=940", test_item_source)
        self.assertIn(
            "center_toplevel_on_parent(self.window, app)",
            inspect.getsource(PipelineWindow.__init__),
        )
        dut_source = inspect.getsource(DutConfigWindow.__init__)
        self.assertIn("center_toplevel_on_parent(", dut_source)
        self.assertIn("window_width=window_width", dut_source)
        self.assertIn("window_height=window_height", dut_source)
        serial_source = inspect.getsource(SerialTerminalWindow.show)
        self.assertIn("saved_geometry is None", serial_source)
        self.assertIn("self._geometry_is_at_top_left(saved_geometry)", serial_source)
        self.assertIn(
            "center_toplevel_on_parent(self.window, self.master)", serial_source
        )
        selector_source = inspect.getsource(LineCheckAssistant._select_power_com_port)
        self.assertNotIn("self.winfo_width() - 460", selector_source)
        self.assertNotIn("self.winfo_height() - 215", selector_source)

    def test_test_item_config_has_power_cycle_runtime_parameters_tab(self):
        """第五个 Tab 必须接入 config.ini [ui_defaults] 的加载、重载和保存。"""
        import inspect

        builder_source = inspect.getsource(LineCheckAssistant._build_test_item_ui_defaults_tab)
        open_source = inspect.getsource(LineCheckAssistant._open_test_item_config)

        self.assertIn('notebook.add(frame, text="开关机运行参数")', builder_source)
        self.assertIn('legacy_defaults_store.load()', open_source)
        self.assertIn('legacy_defaults_control["load"]', open_source)
        self.assertIn('legacy_defaults_store.save(captured_legacy_defaults)', open_source)
        self.assertEqual(
            TEST_ITEM_HIDDEN_UI_DEFAULT_OPTIONS,
            {
                "telnet_enable",
                "communication_method",
                "baud_rate",
                "selected_profile",
            },
        )
        self.assertIn('if option.lower() in TEST_ITEM_HIDDEN_UI_DEFAULT_OPTIONS:', builder_source)
        self.assertIn('continue', builder_source)
        self.assertNotIn('entry.configure(state="readonly")', builder_source)
        self.assertIn('captured = dict(loaded_values)', builder_source)
        self.assertIn('text=descriptions.get(option.lower(), option)', builder_source)
        self.assertIn('foreground=COLOR_TEXT', builder_source)
        self.assertNotIn('column=2', builder_source)

    def test_telnet_and_wifi_tabs_use_chinese_field_labels(self):
        """配置键名保留在存储层，操作员界面只显示对应中文含义。"""
        import inspect

        telnet_source = inspect.getsource(LineCheckAssistant._build_test_item_telnet_tab)
        wifi_source = inspect.getsource(LineCheckAssistant._build_test_item_wifi_tab)

        for label in (
            "设备默认已开启 Telnet",
            "Telnet 开启地址",
            "登录用户名",
            "登录密码（明文）",
            "Telnet 端口",
            "连接超时时间（秒）",
            "用户名提示符",
            "密码提示符",
            "登录成功提示符",
            "是否需要输入密码（0/1）",
            "免用户名密码登录（0/1）",
            "仅执行上下电（0/1）",
        ):
            self.assertIn(label, telnet_source)
        for old_label in (
            'text="request_url"',
            'text="user"',
            'text="password（明文）"',
            'text="input_user_flag"',
            'text="input_password_flag"',
            'text="login_success_flag"',
        ):
            self.assertNotIn(old_label, telnet_source)

        for label in (
            "连接 WiFi（主控）",
            "测试 2.4G WiFi",
            "测试 5G WiFi",
            "ONU 方案类型",
            "认证方式",
            "加密算法",
            "指定无线网卡",
            "刷新无线网卡",
        ):
            self.assertIn(label, wifi_source)
        self.assertNotIn('text="product_solution"', wifi_source)
        self.assertIn("list_wifi_interface_names()", wifi_source)
        self.assertIn("wifi.test_2g_enable", wifi_source)
        self.assertIn("wifi.wireless_card_name", wifi_source)

    def test_test_item_command_groups_use_wider_vertical_spacing(self):
        """测试项命令组之间应有明显留白，段内布局保持不变。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_test_item_order_tab)
        self.assertEqual(TEST_ITEM_COMMAND_GROUP_SPACING, 14)
        self.assertIn(
            'row_frame.pack(fill="x", pady=(0, TEST_ITEM_COMMAND_GROUP_SPACING))',
            source,
        )

    def test_default_test_item_snapshot_contains_current_order_baseline(self):
        """默认模板必须存在，并保存当前 9 条测试项命令。"""
        self.assertTrue(TEST_ITEM_DEFAULT_CONFIG_PATH.is_file())
        default_content = TEST_ITEM_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        self.assertNotIn("command_fail_retry_interval_time", default_content)
        default_order = TestItemConfigStore(TEST_ITEM_DEFAULT_CONFIG_PATH).load().order
        self.assertEqual(default_order.command_fail_retry_interval_time, 60)
        self.assertEqual(len(default_order.items), 9)
        self.assertEqual(default_order.items[0].command, "/userfs/bin/ponmgr gpon get info")
        self.assertEqual(default_order.items[-1].command, "ip route show table main | grep default")

    def test_test_item_tab_provides_confirmed_restore_default_action(self):
        """恢复默认必须只加载默认 [order]，并保留保存确认边界。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_test_item_order_tab)
        self.assertIn('text="恢复默认"', source)
        self.assertIn('messagebox.askyesno(', source)
        self.assertIn('TestItemConfigStore(default_config_path).load().order', source)
        self.assertIn('load(default_order)', source)
        self.assertIn('mark_dirty()', source)
        self.assertIn('仍需点击窗口底部“保存”', source)
        self.assertIn("指令重试间隔继续使用 config.ini 中的当前值", source)

    def test_restore_default_clears_every_existing_test_item_row(self):
        """清空动态命令行时不得边遍历边删除而隔行残留。"""
        row_widgets: list[dict] = []
        removed: list[str] = []

        def add_fake_row(name: str) -> None:
            row: dict = {}

            def remove() -> None:
                removed.append(name)
                row_widgets.remove(row)

            row["remove"] = remove
            row_widgets.append(row)

        for name in ("manual-1", "default-1", "manual-2", "default-2"):
            add_fake_row(name)

        _clear_test_item_rows(row_widgets)

        self.assertEqual(removed, ["manual-1", "default-1", "manual-2", "default-2"])
        self.assertEqual(row_widgets, [])

    def test_serial_log_entry_opens_internal_terminal_for_selected_vlans(self):
        context = SimpleNamespace(
            serial_terminal=Mock(),
            _selected_serial_targets=Mock(return_value=[("vlan101", "COM8")]),
        )

        LineCheckAssistant._open_serial_log_module(context)

        context.serial_terminal.show.assert_called_once_with([("vlan101", "COM8")])

    def test_pipeline_serial_logs_show_then_open_all(self):
        calls = []
        terminal = Mock()
        terminal.show.side_effect = lambda targets: calls.append(("show", targets))
        terminal.open_all.side_effect = lambda: calls.append(("open_all",)) or ()
        context = SimpleNamespace(
            serial_terminal=terminal,
            _selected_serial_targets=Mock(
                return_value=[("vlan112", "COM12"), ("vlan113", "COM16")]
            ),
            _log=Mock(),
        )

        LineCheckAssistant._open_pipeline_serial_logs(context)

        self.assertEqual(
            calls,
            [("show", [("vlan112", "COM12"), ("vlan113", "COM16")]), ("open_all",)],
        )
        context._log.assert_called_once()
        self.assertIn("已执行打开全部，共 2 个通道", context._log.call_args.args[0])

    def test_pipeline_serial_logs_raise_when_any_port_cannot_open(self):
        terminal = Mock()
        terminal.open_all.return_value = ("vlan113",)
        context = SimpleNamespace(
            serial_terminal=terminal,
            _selected_serial_targets=Mock(
                return_value=[("vlan112", "COM12"), ("vlan113", "COM16")]
            ),
            _log=Mock(),
        )

        with self.assertRaisesRegex(RuntimeError, "部分串口未能打开：vlan113"):
            LineCheckAssistant._open_pipeline_serial_logs(context)

        terminal.show.assert_called_once_with(
            [("vlan112", "COM12"), ("vlan113", "COM16")]
        )
        terminal.open_all.assert_called_once_with()
        self.assertIn("失败通道：vlan113", context._log.call_args.args[0])

    def test_onu_registration_entry_reuses_open_window(self):
        onu_registration_window = Mock()
        onu_registration_window.winfo_exists.return_value = True
        context = SimpleNamespace(onu_registration_window=onu_registration_window)

        LineCheckAssistant._open_onu_registration_module(context)

        onu_registration_window.deiconify.assert_called_once_with()
        onu_registration_window.lift.assert_called_once_with()
        onu_registration_window.focus_force.assert_called_once_with()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_onu_telnet_test_starts_worker_with_input_ip(self, thread_class, askyesno):
        worker = thread_class.return_value
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte123")
        context = SimpleNamespace(
            onu_telnet_test_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            _current_onu_connection=Mock(return_value=connection),
            onu_telnet_test_button=Mock(),
            _set_onu_telnet_status=Mock(),
            _onu_telnet_test_worker=Mock(),
            onu_registration_window=Mock(),
        )

        LineCheckAssistant._on_onu_telnet_test_clicked(context)

        self.assertTrue(context.onu_telnet_test_running)
        context._set_onu_telnet_status.assert_called_once_with("正在登录 C300：172.18.18.151:23", COLOR_WARNING)
        context.onu_telnet_test_button.configure.assert_called_once_with(state="disabled")
        askyesno.assert_called_once()
        thread_class.assert_called_once_with(
            target=context._onu_telnet_test_worker,
            args=(OLT_FAMILY_C300, connection),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_complete_onu_telnet_test_restores_button_and_logs_result(self):
        context = SimpleNamespace(
            onu_telnet_test_running=True,
            onu_telnet_test_button=Mock(),
            _set_onu_telnet_status=Mock(),
            _log=Mock(),
        )
        result = OnuOperationResult(True, "OLT Telnet 登录成功")

        LineCheckAssistant._complete_onu_telnet_test(context, OLT_FAMILY_C300, "172.18.18.151", result)

        self.assertFalse(context.onu_telnet_test_running)
        context.onu_telnet_test_button.configure.assert_called_once_with(state="normal")
        context._set_onu_telnet_status.assert_called_once_with(result.message, COLOR_SUCCESS)
        context._log.assert_called_once_with(
            "[ONU注册][C300] OLT 登录测试：172.18.18.151 - OLT Telnet 登录成功"
        )

    def test_failed_onu_telnet_test_uses_danger_color(self):
        context = SimpleNamespace(
            onu_telnet_test_running=True,
            onu_telnet_test_button=Mock(),
            _set_onu_telnet_status=Mock(),
            _log=Mock(),
        )
        result = OnuOperationResult(False, "OLT 登录失败：Access denied")

        LineCheckAssistant._complete_onu_telnet_test(context, OLT_FAMILY_C300, "172.18.18.151", result)

        context._set_onu_telnet_status.assert_called_once_with(result.message, COLOR_DANGER)

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_query_unregistered_onu_starts_worker_with_inputs(self, thread_class, askyesno):
        worker = thread_class.return_value
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")
        context = SimpleNamespace(
            onu_query_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            _current_onu_connection=Mock(return_value=connection),
            _current_onu_discovery_scope=Mock(return_value=OnuDiscoveryScope()),
            onu_query_button=Mock(),
            _set_onu_query_status=Mock(),
            _render_unregistered_onu_selection=Mock(),
            _onu_query_unregistered_worker=Mock(),
            onu_registration_window=Mock(),
        )

        LineCheckAssistant._on_onu_query_unregistered_clicked(context)

        self.assertTrue(context.onu_query_running)
        context._set_onu_query_status.assert_called_once_with("正在查询 C300 未注册 ONU...", COLOR_WARNING)
        context._render_unregistered_onu_selection.assert_called_once_with([])
        context.onu_query_button.configure.assert_called_once_with(state="disabled")
        askyesno.assert_called_once()
        thread_class.assert_called_once_with(
            target=context._onu_query_unregistered_worker,
            args=(OLT_FAMILY_C300, connection, OnuDiscoveryScope()),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_complete_onu_query_unregistered_shows_all_results(self):
        context = SimpleNamespace(
            onu_query_running=True,
            onu_query_button=Mock(),
            _set_onu_query_status=Mock(),
            _render_unregistered_onu_selection=Mock(),
            _log=Mock(),
        )
        onu = DiscoveredOnu(
            family=OLT_FAMILY_C300,
            pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:1",
            suggested_onu_id=1,
            serial_number="GPON1",
            state="unknown",
        )
        result = OnuOperationResult(True, "查询到 1 个未注册 ONU", onus=(onu,))

        LineCheckAssistant._complete_onu_query_unregistered(context, OLT_FAMILY_C300, "172.18.18.151", result)

        self.assertFalse(context.onu_query_running)
        context.onu_query_button.configure.assert_called_once_with(state="normal")
        context._set_onu_query_status.assert_called_once_with("查询到 1 个未注册 ONU，请选择要注册的 ONU", COLOR_SUCCESS)
        rendered = context._render_unregistered_onu_selection.call_args.args[0]
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0].onu_interface, "gpon-onu_1/2/1:1")
        context._log.assert_called_once_with(f"[ONU注册][C300] 查询未注册 ONU：172.18.18.151 - {result.message}")

    def test_switching_to_c300_uses_confirmed_olt_and_source_ip_defaults(self):
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_olt_ip_var=Mock(get=Mock(return_value="172.18.18.152")),
            onu_source_ip_var=Mock(get=Mock(return_value="172.33.5.35")),
            onu_username_var=Mock(get=Mock(return_value="c600-user")),
            onu_password_var=Mock(get=Mock(return_value="c600-pass")),
            onu_active_family=OLT_FAMILY_C600,
            onu_connection_profiles={
                OLT_FAMILY_C300: {
                    "olt_ip": "172.18.18.151",
                    "source_ip": "172.18.18.40",
                    "username": "zte",
                    "password": "zte",
                },
                OLT_FAMILY_C600: {
                    "olt_ip": "172.18.18.152",
                    "source_ip": "172.33.5.35",
                    "username": "c600-user",
                    "password": "c600-pass",
                },
            },
            _render_unregistered_onu_selection=Mock(),
            _invalidate_onu_preview=Mock(),
            _set_onu_telnet_status=Mock(),
            _set_onu_query_status=Mock(),
        )
        context._remember_onu_connection_profile = (
            LineCheckAssistant._remember_onu_connection_profile.__get__(context)
        )
        context._load_onu_connection_profile = (
            LineCheckAssistant._load_onu_connection_profile.__get__(context)
        )

        LineCheckAssistant._on_onu_family_changed(context)

        context.onu_olt_ip_var.set.assert_called_once_with("172.18.18.151")
        context.onu_source_ip_var.set.assert_called_once_with("172.18.18.40")
        context.onu_username_var.set.assert_called_once_with("zte")
        context.onu_password_var.set.assert_called_once_with("zte")

    def test_legacy_select_helper_keeps_only_first_onu_then_clear_removes_it(self):
        first = Mock()
        second = Mock()
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_unregistered_selection_vars=[(Mock(), first), (Mock(), second)],
            onu_c600_selection_var=Mock(),
            _invalidate_onu_preview=Mock(),
            _refresh_onu_selection_action_state=Mock(),
        )

        LineCheckAssistant._select_all_unregistered_onus(context)

        first.set.assert_called_once_with(True)
        second.set.assert_called_once_with(False)

        LineCheckAssistant._clear_unregistered_onu_selection(context)

        first.set.assert_has_calls([call(True), call(False)])
        second.set.assert_has_calls([call(False), call(False)])
        context.onu_c600_selection_var.set.assert_has_calls([call("0"), call("")])
        self.assertEqual(context._invalidate_onu_preview.call_count, 2)
        self.assertEqual(context._refresh_onu_selection_action_state.call_count, 2)

    def test_selected_unregistered_onus_returns_only_checked_items(self):
        selected = UnregisteredOnu("gpon-onu_1/2/1:1", "GPONA62D6F48", "unknown")
        unselected = UnregisteredOnu("gpon-onu_1/2/1:3", "GPONA62D6F78", "unknown")
        context = SimpleNamespace(
            onu_unregistered_selection_vars=[
                (selected, Mock(get=Mock(return_value=True))),
                (unselected, Mock(get=Mock(return_value=False))),
            ]
        )

        self.assertEqual(LineCheckAssistant._selected_unregistered_onus(context), [selected])

    def test_c300_onu_click_marks_clicked_item_selected(self):
        clicked = Mock(get=Mock(return_value=True))
        other = Mock()
        selected_onu = Mock()
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_unregistered_selection_vars=[(selected_onu, clicked), (Mock(), other)],
            _clear_c300_cleanup_candidates=Mock(),
            _invalidate_onu_preview=Mock(),
            _refresh_onu_selection_action_state=Mock(),
        )

        LineCheckAssistant._on_onu_selection_toggled(context, selected_onu, clicked)

        clicked.set.assert_called_once_with(True)
        other.set.assert_called_once_with(False)
        context._clear_c300_cleanup_candidates.assert_called_once_with()
        context._invalidate_onu_preview.assert_called_once_with()
        context._refresh_onu_selection_action_state.assert_called_once_with()

    def test_c300_cleanup_selection_resolves_only_explicit_candidate(self):
        first = C300CleanupCandidate(
            "gpon-onu_1/2/1:8", "gpon-olt_1/2/1", 8, "DyingGasp", "GPON12345678", "SD-41"
        )
        second = C300CleanupCandidate(
            "gpon-onu_1/2/1:9", "gpon-olt_1/2/1", 9, "LOS", "GPON87654321", "SD-41"
        )
        context = SimpleNamespace(
            onu_c300_cleanup_candidate_var=Mock(get=Mock(return_value=second.display_text)),
            onu_c300_cleanup_candidates=(first, second),
        )

        selected = LineCheckAssistant._selected_c300_cleanup_candidate(context)

        self.assertIs(selected, second)

    def test_onu_input_change_clears_stale_c300_cleanup_candidates(self):
        context = SimpleNamespace(
            onu_c300_cleanup_candidates=(Mock(),),
            _schedule_onu_registration_save=Mock(),
            _clear_c300_cleanup_candidates=Mock(),
            _invalidate_onu_preview=Mock(),
        )

        LineCheckAssistant._on_onu_registration_input_changed(context)

        context._schedule_onu_registration_save.assert_called_once_with()
        context._clear_c300_cleanup_candidates.assert_called_once_with()
        context._invalidate_onu_preview.assert_called_once_with()

    def test_complete_c300_cleanup_query_lists_same_pon_candidates_without_autoselect(self):
        candidate = C300CleanupCandidate(
            "gpon-onu_1/2/1:8", "gpon-olt_1/2/1", 8, "DyingGasp", "GPON12345678", "SD-41"
        )
        context = SimpleNamespace(
            onu_cleanup_query_running=True,
            onu_c300_cleanup_candidates=(),
            onu_c300_cleanup_combo=Mock(),
            onu_c300_cleanup_candidate_var=Mock(),
            onu_stop_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _invalidate_onu_preview=Mock(),
        )
        result = OnuOperationResult(
            True,
            "查询到 1 个同 PON 离线候选，请明确选择一台",
            cleanup_candidates=(candidate,),
        )

        LineCheckAssistant._complete_onu_cleanup_candidates(context, result)

        self.assertFalse(context.onu_cleanup_query_running)
        self.assertEqual(context.onu_c300_cleanup_candidates, (candidate,))
        context.onu_c300_cleanup_combo.configure.assert_called_once_with(
            values=(candidate.display_text,),
            state="readonly",
        )
        context.onu_c300_cleanup_candidate_var.set.assert_called_once_with("")

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_register_selected_onus_starts_worker_with_checked_items(self, thread_class, askyesno):
        worker = thread_class.return_value
        selected = DiscoveredOnu(
            family=OLT_FAMILY_C300,
            pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:1",
            suggested_onu_id=1,
            serial_number="GPONA62D6F48",
            state="unknown",
        )
        request = OnuProvisionRequest(family=OLT_FAMILY_C300, onu=selected, onu_type="SD-41")
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")
        context = SimpleNamespace(
            onu_register_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_c300_allow_offline_cleanup_var=Mock(get=Mock(return_value=False)),
            onu_registration_window=Mock(),
            _current_onu_connection=Mock(return_value=connection),
            _build_onu_provision_requests=Mock(return_value=[request]),
            _set_onu_query_status=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _onu_register_selected_worker=Mock(),
        )

        LineCheckAssistant._on_onu_register_selected_clicked(context)

        self.assertTrue(context.onu_register_running)
        context._set_onu_query_status.assert_called_once_with("正在注册 1 个 C300 ONU...", COLOR_WARNING)
        context._set_onu_registration_action_buttons_state.assert_called_once_with("disabled")
        askyesno.assert_called_once()
        thread_class.assert_called_once_with(
            target=context._onu_register_selected_worker,
            args=(OLT_FAMILY_C300, connection, [request], None, False),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_c300_register_passes_only_explicit_cleanup_interface(self, thread_class, _askyesno):
        candidate = C300CleanupCandidate(
            "gpon-onu_1/2/1:8", "gpon-olt_1/2/1", 8, "DyingGasp", "GPON12345678", "SD-41"
        )
        request = OnuProvisionRequest(
            family=OLT_FAMILY_C300,
            onu=DiscoveredOnu(
                family=OLT_FAMILY_C300,
                pon_interface="gpon-olt_1/2/1",
                onu_interface="gpon-onu_1/2/1:3",
                serial_number="GPONA62D6F78",
            ),
            onu_type="SD-41",
        )
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")
        context = SimpleNamespace(
            onu_register_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_c300_allow_offline_cleanup_var=Mock(get=Mock(return_value=True)),
            onu_registration_window=Mock(),
            _current_onu_connection=Mock(return_value=connection),
            _build_onu_provision_requests=Mock(return_value=[request]),
            _selected_c300_cleanup_candidate=Mock(return_value=candidate),
            _set_onu_query_status=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _onu_register_selected_worker=Mock(),
        )

        LineCheckAssistant._on_onu_register_selected_clicked(context)

        thread_class.assert_called_once_with(
            target=context._onu_register_selected_worker,
            args=(OLT_FAMILY_C300, connection, [request], candidate, False),
            daemon=True,
        )

    @patch("line_check_assistant.app.messagebox.showwarning")
    @patch("line_check_assistant.app.threading.Thread")
    def test_register_selected_onus_warns_when_nothing_checked(self, thread_class, showwarning):
        context = SimpleNamespace(
            onu_register_running=False,
            onu_registration_window=Mock(),
            _current_onu_connection=Mock(return_value=OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")),
            _build_onu_provision_requests=Mock(side_effect=ValueError("请先选择要注册的 ONU")),
            _set_onu_query_status=Mock(),
        )

        LineCheckAssistant._on_onu_register_selected_clicked(context)

        context._set_onu_query_status.assert_called_once_with("请先选择要注册的 ONU", COLOR_DANGER)
        showwarning.assert_called_once()
        thread_class.assert_not_called()

    def test_c600_request_uses_current_parameters_and_service_mapping(self):
        selected = DiscoveredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            serial_number="ZTEG12345678",
            model="CXP-55",
            speed_mode="XGS-PON",
        )
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C600)),
            _selected_unregistered_onus=Mock(return_value=[selected]),
            onu_c600_onu_id_var=Mock(get=Mock(return_value="55")),
            onu_c600_onu_type_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_real_speed_var=Mock(get=Mock(return_value="xgspon")),
            onu_c600_tcont_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_tcont_profile_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_gemport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_vport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_sn_bind_both_var=Mock(get=Mock(return_value=True)),
            onu_c600_services_text=Mock(get=Mock(return_value="1,170\n2,335\n6,600")),
        )

        requests = LineCheckAssistant._build_onu_provision_requests(context)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].onu_id, 55)
        self.assertEqual(
            requests[0].services,
            (
                OnuServiceMapping(1, 170),
                OnuServiceMapping(2, 335),
                OnuServiceMapping(6, 600),
            ),
        )

    def test_c300_request_allows_exactly_one_selected_onu(self):
        selected = DiscoveredOnu(
            family=OLT_FAMILY_C300,
            pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:3",
            suggested_onu_id=3,
            serial_number="GPONA62D6F78",
        )
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            _selected_unregistered_onus=Mock(return_value=[selected]),
        )

        requests = LineCheckAssistant._build_onu_provision_requests(context)

        self.assertEqual(len(requests), 1)
        self.assertIs(requests[0].onu, selected)

        context._selected_unregistered_onus.return_value = [selected, selected]
        with self.assertRaisesRegex(ValueError, "C300 每次只能选择一台"):
            LineCheckAssistant._build_onu_provision_requests(context)

    def test_c300_request_reads_parameterized_business_inputs(self):
        selected = DiscoveredOnu(
            family=OLT_FAMILY_C300, pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:3", suggested_onu_id=3,
            serial_number="GPONA62D6F78",
        )
        context = SimpleNamespace(
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            _selected_unregistered_onus=Mock(return_value=[selected]),
            onu_c300_onu_id_var=Mock(get=Mock(return_value="8")),
            onu_c300_onu_type_var=Mock(get=Mock(return_value="SD-41")),
            onu_c300_tcont_id_var=Mock(get=Mock(return_value="2")),
            onu_c300_tcont_profile_var=Mock(get=Mock(return_value="1G-CUSTOM")),
            onu_c300_services_text=Mock(get=Mock(return_value="11,200\n12,46\n13,335\n14,600\n15,171\n16,172")),
        )

        request = LineCheckAssistant._build_onu_provision_requests(context)[0]

        self.assertEqual((request.onu_id, request.tcont_id, request.tcont_profile), (8, 2, "1G-CUSTOM"))
        self.assertEqual(request.services[-1], OnuServiceMapping(16, 172))

    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.messagebox.showinfo")
    def test_c600_success_without_write_selection_does_not_save(self, showinfo, askyesno):
        context = SimpleNamespace(
            onu_register_running=True,
            onu_unregistered_selection_vars=[(Mock(), Mock())],
            onu_query_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
            onu_registration_window=Mock(),
        )
        connection = OltConnection("172.18.18.152", "172.33.5.35", "zte", "secret")
        result = OnuOperationResult(True, "C600 注册与验证成功")

        LineCheckAssistant._complete_onu_register_selected(
            context, OLT_FAMILY_C600, connection, result
        )

        askyesno.assert_not_called()
        showinfo.assert_called_once()
        context._log.assert_called_once_with(
            "[ONU注册][C600] 注册结果：172.18.18.152 - C600 注册与验证成功"
        )

    @patch("line_check_assistant.app.threading.Thread")
    def test_c600_success_with_write_selection_starts_save_worker(self, thread_class):
        worker = thread_class.return_value
        context = SimpleNamespace(
            onu_register_running=True,
            onu_save_olt_running=False,
            onu_unregistered_selection_vars=[(Mock(), Mock())],
            onu_query_button=Mock(),
            onu_stop_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
            _onu_save_olt_configuration_worker=Mock(),
            onu_registration_window=Mock(),
        )
        connection = OltConnection("172.18.18.152", "172.33.5.35", "zte", "secret")
        result = OnuOperationResult(True, "C600 注册与验证成功")

        LineCheckAssistant._complete_onu_register_selected(
            context, OLT_FAMILY_C600, connection, result, True
        )

        self.assertTrue(context.onu_save_olt_running)
        thread_class.assert_called_once_with(
            target=context._onu_save_olt_configuration_worker,
            args=(OLT_FAMILY_C600, connection),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_template_choice_uses_name_for_commands_but_keeps_manual_input(self):
        self.assertEqual(
            LineCheckAssistant._template_name_from_input("OSCAR_XGS（PON类型：XGS-PON）"),
            "OSCAR_XGS",
        )
        self.assertEqual(
            LineCheckAssistant._template_name_from_input("WT-10G（速率：10G）"),
            "WT-10G",
        )
        self.assertEqual(LineCheckAssistant._template_name_from_input("CUSTOM-TEMPLATE"), "CUSTOM-TEMPLATE")

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_c300_query_preserves_current_pon_scope(self, thread_class, _askyesno):
        worker = thread_class.return_value
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")
        scope = OnuDiscoveryScope(1, 2, 1)
        context = SimpleNamespace(
            onu_query_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            _current_onu_connection=Mock(return_value=connection),
            _current_onu_discovery_scope=Mock(return_value=scope),
            onu_query_button=Mock(),
            _set_onu_query_status=Mock(),
            _render_unregistered_onu_selection=Mock(),
            _onu_query_unregistered_worker=Mock(),
            onu_registration_window=Mock(),
        )

        LineCheckAssistant._on_onu_query_unregistered_clicked(context)

        context._current_onu_discovery_scope.assert_called_once_with()
        thread_class.assert_called_once_with(
            target=context._onu_query_unregistered_worker,
            args=(OLT_FAMILY_C300, connection, scope),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_main_onu_ui_uses_service_without_importing_standalone_c600_gui(self):
        module_source = inspect.getsource(sys.modules["line_check_assistant.app"])
        open_source = inspect.getsource(LineCheckAssistant._open_onu_registration_module)

        self.assertNotIn("ZteTitanOnuProvisioner", module_source)
        self.assertIn('text="1. 查询 ONU"', open_source)
        self.assertIn('text="2. 配置业务"', open_source)
        self.assertIn('text="3. 确认执行"', open_source)
        self.assertIn('text="OLT 连接"', open_source)
        self.assertIn('text="C600 查询范围"', open_source)
        self.assertIn('text="生成预览并进入下一步"', open_source)
        self.assertIn('text="完整验证成功后执行 write（危险，仅本次有效）"', open_source)
        self.assertIn('"ONU 类型模板"', open_source)
        self.assertIn(
            '"ONU 类型模板是 OLT 中的 onu-type 模板名称；默认带入查询到的 ONU 型号，可按实际兼容模板修改。"',
            open_source,
        )
        self.assertNotIn('"ONU 型号"', open_source)
        self.assertIn('"上网VPort"', open_source)
        self.assertIn('"TR069 50→4。GEM与VPort必须1:1对应。"', open_source)
        self.assertIn("self.onu_c600_write_after_success_var.set(False)", open_source)
        self.assertIn("ttk.Radiobutton", module_source)
        self.assertNotIn('text="全选"', open_source)
        self.assertLess(open_source.index('text="OLT 连接"'), open_source.index("self.onu_notebook ="))
        self.assertNotIn("TITAN", open_source)
        self.assertIn("OnuRegistrationService", module_source)

    def test_onu_window_reserves_bottom_rows_without_maximizing(self):
        open_source = inspect.getsource(LineCheckAssistant._open_onu_registration_module)

        self.assertIn('dialog.geometry("1000x900")', open_source)
        self.assertIn('dialog.minsize(1000, 900)', open_source)
        self.assertIn('content.rowconfigure(3, weight=1)', open_source)
        self.assertIn('self.onu_notebook.grid(row=3, column=0, sticky="nsew")', open_source)
        self.assertIn('height=8', open_source)
        self.assertIn('warning_label.grid(row=4, column=0', open_source)
        self.assertIn('self.onu_query_status_label.grid(row=5, column=0', open_source)
        self.assertIn('bottom_actions.grid(row=6, column=0', open_source)
        self.assertNotIn('self.onu_notebook.pack(', open_source)

    def test_onu_registered_manage_tab_and_danger_button_present(self):
        open_source = inspect.getsource(LineCheckAssistant._open_onu_registration_module)

        self.assertIn('text="4. 已注册管理"', open_source)
        self.assertIn('text="查询已注册 ONU"', open_source)
        self.assertIn('text="删除选中 ONU（危险）"', open_source)
        self.assertIn('style="Danger.TButton"', open_source)

    def test_current_onu_manage_pon_interface_builds_family_specific_path(self):
        def context_for(family, shelf="1", slot="2", pon="3"):
            return SimpleNamespace(
                onu_family_var=Mock(get=Mock(return_value=family)),
                onu_manage_shelf_var=Mock(get=Mock(return_value=shelf)),
                onu_manage_slot_var=Mock(get=Mock(return_value=slot)),
                onu_manage_pon_var=Mock(get=Mock(return_value=pon)),
            )

        self.assertEqual(
            LineCheckAssistant._current_onu_manage_pon_interface(context_for(OLT_FAMILY_C300)),
            "gpon-olt_1/2/3",
        )
        self.assertEqual(
            LineCheckAssistant._current_onu_manage_pon_interface(context_for(OLT_FAMILY_C600)),
            "gpon_olt-1/2/3",
        )
        with self.assertRaisesRegex(ValueError, "整数"):
            LineCheckAssistant._current_onu_manage_pon_interface(context_for(OLT_FAMILY_C300, shelf="x"))
        with self.assertRaisesRegex(ValueError, "1-64"):
            LineCheckAssistant._current_onu_manage_pon_interface(context_for(OLT_FAMILY_C300, pon="99"))

    def test_selected_registered_onu_resolves_only_explicit_candidate(self):
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="OffLine",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )
        context = SimpleNamespace(
            onu_registered_candidates=(candidate,),
            onu_registered_candidate_var=Mock(get=Mock(return_value=candidate.display_text)),
        )

        self.assertIs(LineCheckAssistant._selected_registered_onu(context), candidate)
        context.onu_registered_candidate_var.get.return_value = "其它"
        self.assertIsNone(LineCheckAssistant._selected_registered_onu(context))

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_onu_manage_query_clicked_starts_worker(self, thread_class, askyesno):
        worker = thread_class.return_value
        connection = OltConnection("172.18.18.152", "172.33.5.35", "zte", "zte")
        context = SimpleNamespace(
            onu_manage_query_running=False,
            onu_manage_delete_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C600)),
            onu_registration_window=Mock(),
            _current_onu_connection=Mock(return_value=connection),
            _current_onu_manage_pon_interface=Mock(return_value="gpon_olt-1/1/5"),
            _clear_registered_candidates=Mock(),
            _set_onu_query_status=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _onu_manage_query_worker=Mock(),
        )

        LineCheckAssistant._on_onu_manage_query_clicked(context)

        self.assertTrue(context.onu_manage_query_running)
        context._clear_registered_candidates.assert_called_once_with()
        context._set_onu_registration_action_buttons_state.assert_called_once_with("disabled")
        thread_class.assert_called_once_with(
            target=context._onu_manage_query_worker,
            args=(OLT_FAMILY_C600, connection, "gpon_olt-1/1/5"),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_complete_onu_manage_query_lists_candidates_without_autoselect(self):
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="OffLine",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )
        context = SimpleNamespace(
            onu_manage_query_running=True,
            onu_registered_candidates=(),
            onu_registered_combo=Mock(),
            onu_registered_candidate_var=Mock(),
            onu_manage_delete_button=Mock(),
            onu_stop_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
        )
        result = OnuOperationResult(
            True,
            "查询到 1 个离线/非 working 的已注册 ONU，请选择要删除的一台",
            registered_onus=(candidate,),
        )

        LineCheckAssistant._complete_onu_manage_query(context, OLT_FAMILY_C600, "172.18.18.152", result)

        self.assertFalse(context.onu_manage_query_running)
        self.assertEqual(context.onu_registered_candidates, (candidate,))
        context.onu_registered_combo.configure.assert_called_once_with(
            values=(candidate.display_text,),
            state="readonly",
        )
        context.onu_registered_candidate_var.set.assert_called_once_with("")
        context.onu_manage_delete_button.configure.assert_called_once_with(state="disabled")

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_onu_manage_delete_clicked_confirms_and_starts_worker(self, thread_class, askyesno):
        worker = thread_class.return_value
        candidate = RegisteredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            onu_interface="gpon_onu-1/1/5:55",
            onu_id=55,
            state="OffLine",
            serial_number="ZTEG12345678",
            onu_type="CXP-55",
        )
        connection = OltConnection("172.18.18.152", "172.33.5.35", "zte", "zte")
        context = SimpleNamespace(
            onu_manage_delete_running=False,
            onu_manage_query_running=False,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C600)),
            onu_registration_window=Mock(),
            _selected_registered_onu=Mock(return_value=candidate),
            _current_onu_connection=Mock(return_value=connection),
            _set_onu_query_status=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _onu_manage_delete_worker=Mock(),
        )

        LineCheckAssistant._on_onu_manage_delete_clicked(context)

        self.assertTrue(context.onu_manage_delete_running)
        askyesno.assert_called_once()
        thread_class.assert_called_once_with(
            target=context._onu_manage_delete_worker,
            args=(OLT_FAMILY_C600, connection, candidate),
            daemon=True,
        )
        worker.start.assert_called_once_with()

    def test_complete_onu_manage_delete_clears_candidates_on_success(self):
        context = SimpleNamespace(
            onu_manage_delete_running=True,
            onu_stop_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
            _clear_registered_candidates=Mock(),
        )
        result = OnuOperationResult(True, "已删除 gpon_onu-1/1/5:55 并确认其重新回到未注册状态（未执行 write）")

        LineCheckAssistant._complete_onu_manage_delete(context, OLT_FAMILY_C600, "172.18.18.152", result)

        self.assertFalse(context.onu_manage_delete_running)
        context._clear_registered_candidates.assert_called_once_with()
        context._set_onu_query_status.assert_called_once()

    @patch("line_check_assistant.app.messagebox.showwarning")
    def test_onu_config_step_requires_selection_then_advances(self, showwarning):
        context = SimpleNamespace(
            _selected_unregistered_onus=Mock(return_value=[]),
            _set_onu_query_status=Mock(),
            onu_registration_window=Mock(),
            onu_notebook=Mock(),
            onu_config_tab=Mock(),
        )

        LineCheckAssistant._go_to_onu_config_step(context)

        context.onu_notebook.select.assert_not_called()
        showwarning.assert_called_once()

        context._selected_unregistered_onus.return_value = [Mock()]
        LineCheckAssistant._go_to_onu_config_step(context)

        context.onu_notebook.select.assert_called_once_with(context.onu_config_tab)

    def test_c600_single_selection_advances_directly_to_configuration(self):
        context = SimpleNamespace(
            _on_onu_selection_toggled=Mock(),
            onu_notebook=Mock(),
            onu_config_tab=Mock(),
        )
        onu = Mock()
        variable = Mock()

        LineCheckAssistant._on_c600_onu_selected(context, onu, variable)

        variable.set.assert_called_once_with(True)
        context._on_onu_selection_toggled.assert_called_once_with(onu, variable)
        context.onu_notebook.select.assert_called_once_with(context.onu_config_tab)

    def test_c600_discovery_defaults_speed_command_to_auto(self):
        onu = DiscoveredOnu(
            family=OLT_FAMILY_C600,
            pon_interface="gpon_olt-1/1/5",
            serial_number="SDMC176D42AA",
            model="NP7287XGS",
            speed_mode="XGS-PON",
        )
        context = SimpleNamespace(
            onu_c600_onu_type_var=Mock(),
            onu_c600_real_speed_var=Mock(),
            _set_onu_query_status=Mock(),
        )

        LineCheckAssistant._fill_c600_from_discovered_onu(context, onu)

        context.onu_c600_onu_type_var.set.assert_called_once_with("NP7287XGS")
        context.onu_c600_real_speed_var.set.assert_called_once_with("auto")

    def test_invalidating_onu_preview_clears_commands_and_disables_registration(self):
        context = SimpleNamespace(
            onu_preview_ready=True,
            onu_confirmation_summary_var=Mock(),
            onu_command_preview_text=Mock(),
            onu_register_button=Mock(),
        )

        LineCheckAssistant._invalidate_onu_preview(context)

        self.assertFalse(context.onu_preview_ready)
        context.onu_confirmation_summary_var.set.assert_called_once_with(
            "参数或目标已变化，请重新生成命令预览。"
        )
        context.onu_command_preview_text.delete.assert_called_once_with("1.0", "end")
        context.onu_register_button.configure.assert_called_once_with(state="disabled")

    def test_onu_preview_builds_execution_summary_and_advances_to_confirmation(self):
        onu = DiscoveredOnu(
            family=OLT_FAMILY_C300,
            pon_interface="gpon-olt_1/2/1",
            onu_interface="gpon-onu_1/2/1:1",
            suggested_onu_id=1,
            serial_number="GPON12345678",
            state="unknown",
        )
        request = OnuProvisionRequest(family=OLT_FAMILY_C300, onu=onu, onu_type="SD-41")
        context = SimpleNamespace(
            _build_onu_provision_requests=Mock(return_value=[request]),
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C300)),
            onu_c300_allow_offline_cleanup_var=Mock(get=Mock(return_value=False)),
            onu_olt_ip_var=Mock(get=Mock(return_value="172.18.18.151")),
            onu_source_ip_var=Mock(get=Mock(return_value="172.18.18.40")),
            onu_confirmation_summary_var=Mock(),
            onu_command_preview_text=Mock(),
            onu_register_button=Mock(),
            onu_notebook=Mock(),
            onu_preview_tab=Mock(),
            _set_onu_query_status=Mock(),
            onu_registration_window=Mock(),
            onu_preview_ready=False,
        )

        LineCheckAssistant._on_onu_preview_clicked(context)

        self.assertTrue(context.onu_preview_ready)
        summary = context.onu_confirmation_summary_var.set.call_args.args[0]
        self.assertIn("OLT：C300 172.18.18.151", summary)
        self.assertIn("首条 CLI 错误停止且不删除 ONU", summary)
        context.onu_register_button.configure.assert_called_once_with(state="normal")
        context.onu_notebook.select.assert_called_once_with(context.onu_preview_tab)

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=False)
    def test_complete_onu_register_selected_restores_buttons_and_logs_result(self, askyesno):
        context = SimpleNamespace(
            onu_register_running=True,
            onu_unregistered_selection_vars=[(Mock(), Mock())],
            onu_query_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
            onu_registration_window=Mock(),
        )
        result = CommandResult(True, "已下发 1 个 ONU 注册配置（未保存 OLT 配置，请重新查询确认上线）")
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")

        LineCheckAssistant._complete_onu_register_selected(context, OLT_FAMILY_C300, connection, result)

        self.assertFalse(context.onu_register_running)
        context._set_onu_registration_action_buttons_state.assert_called_once_with("normal")
        context.onu_query_button.configure.assert_called_once_with(state="normal")
        context._set_onu_query_status.assert_called_once_with(result.message, COLOR_SUCCESS)
        context._log.assert_has_calls(
            [
                call(f"[ONU注册][C300] 注册结果：172.18.18.151 - {result.message}"),
                call("[ONU注册][C300] 保存 OLT 配置：172.18.18.151 - 用户选择暂不保存"),
            ]
        )
        askyesno.assert_called_once()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_complete_onu_register_selected_starts_save_worker_when_confirmed(self, thread_class, askyesno):
        worker = thread_class.return_value
        context = SimpleNamespace(
            onu_register_running=True,
            onu_save_olt_running=False,
            onu_unregistered_selection_vars=[(Mock(), Mock())],
            onu_query_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
            _onu_save_olt_configuration_worker=Mock(),
            onu_registration_window=Mock(),
        )
        result = CommandResult(True, "注册成功")
        connection = OltConnection("172.18.18.151", "172.18.18.40", "zte", "zte")

        LineCheckAssistant._complete_onu_register_selected(context, OLT_FAMILY_C300, connection, result)

        self.assertTrue(context.onu_save_olt_running)
        context._set_onu_query_status.assert_any_call("正在执行 write 保存 OLT 最新配置...", COLOR_WARNING)
        context._set_onu_registration_action_buttons_state.assert_has_calls([call("normal"), call("disabled")])
        thread_class.assert_called_once_with(
            target=context._onu_save_olt_configuration_worker,
            args=(OLT_FAMILY_C300, connection),
            daemon=True,
        )
        worker.start.assert_called_once_with()
        askyesno.assert_called_once()

    def test_complete_onu_save_olt_configuration_restores_buttons_and_logs(self):
        context = SimpleNamespace(
            onu_save_olt_running=True,
            onu_unregistered_selection_vars=[(Mock(), Mock())],
            onu_query_button=Mock(),
            _set_onu_registration_action_buttons_state=Mock(),
            _set_onu_query_status=Mock(),
            _log=Mock(),
        )
        result = CommandResult(True, "OLT 最新配置已写入启动配置")

        LineCheckAssistant._complete_onu_save_olt_configuration(context, OLT_FAMILY_C300, "172.18.18.151", result)

        self.assertFalse(context.onu_save_olt_running)
        context._set_onu_registration_action_buttons_state.assert_called_once_with("normal")
        context.onu_query_button.configure.assert_called_once_with(state="normal")
        context._set_onu_query_status.assert_called_once_with(result.message, COLOR_SUCCESS)
        context._log.assert_called_once_with(f"[ONU注册][C300] 保存 OLT 配置：172.18.18.151 - {result.message}")

    def test_set_onu_telnet_status_updates_text_and_color(self):
        context = SimpleNamespace(onu_telnet_status_var=Mock(), onu_status_label=Mock())

        LineCheckAssistant._set_onu_telnet_status(context, "Telnet 连通性测试通过", COLOR_SUCCESS)

        context.onu_telnet_status_var.set.assert_called_once_with("Telnet 连通性测试通过")
        context.onu_status_label.configure.assert_called_once_with(foreground=COLOR_SUCCESS)

    def test_set_onu_query_status_updates_text_and_color(self):
        context = SimpleNamespace(onu_query_status_var=Mock(), onu_query_status_label=Mock())

        LineCheckAssistant._set_onu_query_status(context, "查询未注册的 ONU 功能待接入", COLOR_MUTED)

        context.onu_query_status_var.set.assert_called_once_with("查询未注册的 ONU 功能待接入")
        context.onu_query_status_label.configure.assert_called_once_with(foreground=COLOR_MUTED)

    def test_onu_password_eye_toggles_plain_text_display(self):
        context = SimpleNamespace(
            onu_password_visible=False,
            onu_password_entry=Mock(),
            onu_password_toggle=Mock(),
        )

        LineCheckAssistant._toggle_onu_password_visibility(context)

        self.assertTrue(context.onu_password_visible)
        context.onu_password_entry.configure.assert_called_once_with(show="")
        context.onu_password_toggle.configure.assert_called_once_with(relief="sunken")

    def test_current_onu_registration_config_reads_all_input_fields(self):
        context = SimpleNamespace(
            onu_registration_config=OnuRegistrationConfig(),
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C600)),
            onu_olt_ip_var=Mock(get=Mock(return_value="172.18.18.200")),
            onu_source_ip_var=Mock(get=Mock(return_value="172.33.5.35")),
            onu_username_var=Mock(get=Mock(return_value="admin")),
            onu_password_var=Mock(get=Mock(return_value="secret")),
            onu_c600_shelf_var=Mock(get=Mock(return_value="1")),
            onu_c600_slot_var=Mock(get=Mock(return_value="2")),
            onu_c600_pon_var=Mock(get=Mock(return_value="3")),
            onu_c600_onu_id_var=Mock(get=Mock(return_value="55")),
            onu_c600_onu_type_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_real_speed_var=Mock(get=Mock(return_value="xgspon")),
            onu_c600_tcont_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_tcont_profile_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_gemport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_vport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_sn_bind_both_var=Mock(get=Mock(return_value=True)),
            onu_c300_allow_offline_cleanup_var=Mock(get=Mock(return_value=False)),
        )

        config = LineCheckAssistant._current_onu_registration_config(context)

        self.assertEqual(
            config,
            OnuRegistrationConfig(
                olt_ip="172.18.18.200",
                username="admin",
                password="secret",
                olt_family=OLT_FAMILY_C600,
                source_ip="172.33.5.35",
                c600_olt_ip="172.18.18.200",
                c600_source_ip="172.33.5.35",
                c600_username="admin",
                c600_password="secret",
                c600_real_speed="xgspon",
                c600_tcont_profile="CXP-55",
                c600_shelf=1,
                c600_slot=2,
                c600_pon=3,
                c600_onu_id=55,
            ),
        )

    def test_current_onu_registration_config_ignores_destroyed_services_text(self):
        destroyed_text = Mock()
        destroyed_text.winfo_exists.return_value = False
        context = SimpleNamespace(
            onu_registration_config=OnuRegistrationConfig(c600_services="6,600"),
            onu_c600_services_text=destroyed_text,
            onu_family_var=Mock(get=Mock(return_value=OLT_FAMILY_C600)),
            onu_olt_ip_var=Mock(get=Mock(return_value="172.18.18.152")),
            onu_source_ip_var=Mock(get=Mock(return_value="172.33.5.35")),
            onu_username_var=Mock(get=Mock(return_value="admin")),
            onu_password_var=Mock(get=Mock(return_value="secret")),
            onu_c600_shelf_var=Mock(get=Mock(return_value="1")),
            onu_c600_slot_var=Mock(get=Mock(return_value="1")),
            onu_c600_pon_var=Mock(get=Mock(return_value="5")),
            onu_c600_onu_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_onu_type_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_real_speed_var=Mock(get=Mock(return_value="xgspon")),
            onu_c600_tcont_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_tcont_profile_var=Mock(get=Mock(return_value="CXP-55")),
            onu_c600_gemport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_vport_id_var=Mock(get=Mock(return_value="1")),
            onu_c600_sn_bind_both_var=Mock(get=Mock(return_value=True)),
        )

        config = LineCheckAssistant._current_onu_registration_config(context)

        self.assertEqual(config.c600_services, "6,600")
        destroyed_text.get.assert_not_called()

    def test_save_onu_registration_config_writes_current_inputs(self):
        config = OnuRegistrationConfig(olt_ip="172.18.18.200", username="admin", password="secret")
        context = SimpleNamespace(
            onu_save_after_id="after-id",
            onu_registration_store=Mock(),
            _current_onu_registration_config=Mock(return_value=config),
        )

        LineCheckAssistant._save_onu_registration_config(context)

        self.assertIsNone(context.onu_save_after_id)
        context.onu_registration_store.save.assert_called_once_with(config)
        self.assertIs(context.onu_registration_config, config)

    def test_app_close_saves_onu_registration_inputs(self):
        context = SimpleNamespace(
            onu_save_after_id="after-id",
            sample_upgrade_save_after_id=None,
            after_cancel=Mock(),
            _save_onu_registration_config=Mock(),
            _save_sample_upgrade_settings=Mock(),
            destroy=Mock(),
        )

        LineCheckAssistant._on_app_close(context)

        context.after_cancel.assert_called_once_with("after-id")
        self.assertIsNone(context.onu_save_after_id)
        context._save_onu_registration_config.assert_called_once_with()
        context._save_sample_upgrade_settings.assert_called_once_with()
        context.destroy.assert_called_once_with()

    def test_app_close_still_destroys_when_save_fails(self):
        context = SimpleNamespace(
            onu_save_after_id=None,
            sample_upgrade_save_after_id=None,
            _save_onu_registration_config=Mock(side_effect=ValueError("save failed")),
            _save_sample_upgrade_settings=Mock(),
            destroy=Mock(),
        )

        LineCheckAssistant._on_app_close(context)

        context.destroy.assert_called_once_with()

    def test_current_sample_upgrade_settings_reads_all_inputs(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp指令")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=4)),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=True)),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            parameter_initial_username_var=Mock(get=Mock(return_value="param-root")),
            parameter_initial_password_var=Mock(get=Mock(return_value="param-secret")),
            parameter_parallel_count_var=Mock(get=Mock(return_value=6)),
            parameter_clear_parameters_var=Mock(get=Mock(return_value=True)),
            parameter_exit_aging_var=Mock(get=Mock(return_value=False)),
            # 2026-07-20:全流程执行管道用的两个新字段
            power_operation_var=Mock(get=Mock(return_value="down")),
            parameter_table_path_var=Mock(get=Mock(return_value=r"F:\data\params.xlsx")),
        )

        settings = LineCheckAssistant._current_sample_upgrade_settings(context)

        self.assertEqual(
            settings,
            SampleUpgradeSettings(
                upgrade_mode="全包升级",
                transfer_method="Tftp指令",
                parallel_count=4,
                restore_factory=True,
                username="root",
                password="secret",
                firmware_path=r"F:\firmware\tclinux_allinone",
                parameter_initial_username="param-root",
                parameter_initial_password="param-secret",
                parameter_parallel_count=6,
                parameter_clear_parameters=True,
                parameter_exit_aging=False,
                power_operation="down",
                parameter_table_path=r"F:\data\params.xlsx",
            ),
        )

    def test_current_sample_upgrade_settings_normalizes_legacy_tftp_copy_label(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp拷贝命令")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=2)),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            parameter_initial_username_var=Mock(get=Mock(return_value="")),
            parameter_initial_password_var=Mock(get=Mock(return_value="")),
            parameter_parallel_count_var=Mock(get=Mock(return_value="invalid")),
            parameter_clear_parameters_var=Mock(get=Mock(return_value=False)),
            parameter_exit_aging_var=Mock(get=Mock(return_value=False)),
            # 2026-07-20:全流程执行管道默认字段
            power_operation_var=Mock(get=Mock(return_value="up")),
            parameter_table_path_var=Mock(get=Mock(return_value="")),
        )

        settings = LineCheckAssistant._current_sample_upgrade_settings(context)

        self.assertEqual(settings.transfer_method, "Tftp指令")
        self.assertEqual(settings.power_operation, "up")
        self.assertEqual(settings.parameter_table_path, "")
        self.assertEqual(settings.parameter_parallel_count, DEFAULT_PARAMETER_PARALLEL_COUNT)

    def test_loading_parameter_table_updates_persisted_pipeline_path(self):
        """写参窗口选表后，全流程子任务 4 必须立刻读到同一条路径。"""
        table_path = r"F:\fixture\batch_parameters.xlsx"
        context = SimpleNamespace(
            parameter_records=[],
            parameter_loaded_table_path="",
            parameter_table_path_var=Mock(),
            _log=Mock(),
            _refresh_parameter_preflight=Mock(),
        )

        with patch("line_check_assistant.app.load_parameter_records", return_value=["record"]):
            loaded = LineCheckAssistant._load_parameter_table(context, Path(table_path))

        self.assertTrue(loaded)
        self.assertEqual(context.parameter_records, ["record"])
        self.assertEqual(context.parameter_loaded_table_path, table_path)
        context.parameter_table_path_var.set.assert_called_once_with(table_path)
        context._refresh_parameter_preflight.assert_called_once_with()

    def test_parameter_writer_reuses_persisted_path_and_restores_saved_table(self):
        """重开写参窗口必须显示并恢复上次已保存的参数表。"""
        import inspect
        import line_check_assistant.app as app_module

        source = inspect.getsource(app_module.LineCheckAssistant._open_sample_parameter_writer)
        self.assertIn("self.parameter_table_var = self.parameter_table_path_var", source)
        self.assertIn("self._load_parameter_table(Path(saved_table_path), report_error=False)", source)

    def test_parameter_option_checkbuttons_use_native_checkmark_indicator(self):
        """写参可选项必须使用 Windows 原生勾选框，不显示 ttk clam 的叉号。"""
        import inspect
        import line_check_assistant.app as app_module

        source = inspect.getsource(app_module.LineCheckAssistant._open_sample_parameter_writer)
        self.assertEqual(source.count("Checkbutton("), 2)
        self.assertNotIn("ttk.Checkbutton(option_row", source)
        self.assertIn('selectcolor="#ffffff"', source)

    def test_onu_options_and_active_ui_use_native_checkmark_indicator(self):
        """ONU及今后新增的布尔选项都不得使用会显示叉号的ttk控件。"""
        import line_check_assistant.app as app_module

        source = inspect.getsource(app_module.LineCheckAssistant._open_onu_registration_module)
        self.assertNotIn("ttk.Checkbutton(", source)
        self.assertEqual(source.count("Checkbutton("), 3)
        self.assertEqual(source.count('selectcolor="#ffffff"'), 3)
        for label in (
            "C300 配置失败时，允许删除明确选择的一台同 PON 离线 ONU 后重试（危险）",
            "启用 SN 双重绑定",
            "完整验证成功后执行 write（危险，仅本次有效）",
        ):
            self.assertIn(label, source)

        project_root = Path(__file__).resolve().parents[1]
        offenders = []
        for source_dir in ("line_check_assistant", "src"):
            for source_path in (project_root / source_dir).rglob("*.py"):
                if "ttk.Checkbutton(" in source_path.read_text(encoding="utf-8"):
                    offenders.append(str(source_path.relative_to(project_root)))
        self.assertEqual(offenders, [], f"应改用原生 Checkbutton 的文件：{offenders}")

    def test_pipeline_subtask_wait_returns_only_after_completion_result(self):
        """异步升级/写参只有完成回调通知后，管道才能执行下一项。"""
        context = SimpleNamespace(
            _pipeline_subtask_events={},
            _pipeline_subtask_results={},
        )

        LineCheckAssistant._begin_pipeline_subtask(context, "sample_upgrade")
        LineCheckAssistant._finish_pipeline_subtask(context, "sample_upgrade", True, "升级完成")
        LineCheckAssistant._wait_pipeline_subtask(context, "sample_upgrade")

        self.assertEqual(context._pipeline_subtask_events, {})
        self.assertEqual(context._pipeline_subtask_results, {})

    def test_save_sample_upgrade_settings_writes_current_inputs(self):
        settings = SampleUpgradeSettings(upgrade_mode="页面升级", transfer_method="Tftp Put")
        context = SimpleNamespace(
            sample_upgrade_save_after_id="after-id",
            sample_upgrade_settings_store=Mock(),
            _current_sample_upgrade_settings=Mock(return_value=settings),
        )

        LineCheckAssistant._save_sample_upgrade_settings(context)

        self.assertIsNone(context.sample_upgrade_save_after_id)
        context.sample_upgrade_settings_store.save.assert_called_once_with(settings)

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
            _refresh_upgrade_parallel_count_visibility=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_transfer_visibility(context)

        context.upgrade_transfer_label.grid.assert_called_once_with()
        context.upgrade_transfer_combo.grid.assert_called_once_with()
        context.upgrade_transfer_label.grid_remove.assert_not_called()
        context.upgrade_transfer_combo.grid_remove.assert_not_called()

    def test_full_package_tftp_put_refreshes_parallel_count_visibility(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put"), set=Mock()),
            upgrade_transfer_label=Mock(),
            upgrade_transfer_combo=Mock(),
            _refresh_upgrade_parallel_count_visibility=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_transfer_visibility(context)

        context._refresh_upgrade_parallel_count_visibility.assert_called_once_with()

    def test_upgrade_window_only_exposes_parallel_count_for_full_package(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._open_upgrade_module)

        self.assertIn('text=f"并行数 (1-{MAX_PARALLEL_UPGRADES})"', source)
        self.assertNotIn("升级执行方式", source)
        self.assertNotIn("upgrade_execution", source)

    def test_page_upgrade_hides_transfer_method(self):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put"), set=Mock()),
            upgrade_transfer_label=Mock(),
            upgrade_transfer_combo=Mock(),
            _refresh_upgrade_parallel_count_visibility=Mock(),
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

    def test_restore_factory_text_uses_empty_box_when_disabled(self):
        context = SimpleNamespace(
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_restore_factory_text_var=Mock(),
        )

        LineCheckAssistant._refresh_upgrade_restore_factory_text(context)

        context.upgrade_restore_factory_text_var.set.assert_called_once_with("☐ 恢复出厂")
        self.assertEqual(LineCheckAssistant._restore_factory_text(True), "☑ 恢复出厂")
        self.assertEqual(LineCheckAssistant._restore_factory_text(False), "☐ 恢复出厂")

    @patch("line_check_assistant.app.threading.Thread")
    def test_page_upgrade_start_routes_to_page_upgrade_flow(self, thread_class):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_username_var=Mock(get=Mock(return_value="admin")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            upgrade_window=Mock(),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            _start_page_upgrade=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        context._start_page_upgrade.assert_called_once_with()
        thread_class.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    def test_full_package_tftp_command_starts_parallel_upgrade_flow(self, thread_class):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp指令")),
            upgrade_username_var=Mock(get=Mock(return_value="admin")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            _start_full_package_upgrade=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        context._start_full_package_upgrade.assert_called_once_with()
        thread_class.assert_not_called()

    @patch("line_check_assistant.app.threading.Thread")
    def test_full_package_tftp_put_starts_parallel_upgrade_flow(self, thread_class):
        context = SimpleNamespace(
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_username_var=Mock(get=Mock(return_value="admin")),
            upgrade_password_var=Mock(get=Mock(return_value="password")),
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux")),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            _start_full_package_upgrade=Mock(),
        )

        LineCheckAssistant._on_upgrade_start_clicked(context)

        context._start_full_package_upgrade.assert_called_once_with()
        thread_class.assert_not_called()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_page_upgrade_requests_use_enabled_channel_ips(self, thread_class, _is_file, _askyesno):
        channels = [
            ChannelConfig(section="channel_1", vlan_name="VLAN102", adapter_alias="VLAN102", network_card_ip="172.18.18.3", device_manage_ip="192.168.29.1", enabled=True),
            ChannelConfig(section="channel_2", vlan_name="VLAN101", network_card_ip="", device_manage_ip="192.168.30.1", enabled=True),
        ]
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\sdmc.bin")),
            upgrade_username_var=Mock(get=Mock(return_value="sdmc")),
            upgrade_password_var=Mock(get=Mock(return_value="1234")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=True)),
            upgrade_window=Mock(),
            device_ip_var=Mock(get=Mock(return_value="192.168.1.1")),
            _selected_page_upgrade_channels=Mock(return_value=channels),
            _tftp_server_ip_for_channel=Mock(return_value="172.18.18.4"),
            _set_upgrade_status=Mock(),
            _page_upgrade_worker=Mock(),
        )

        LineCheckAssistant._start_page_upgrade(context)

        requests = thread_class.call_args.kwargs["args"][0]
        self.assertEqual([request.vlan for request in requests], ["vlan102", "vlan101"])
        self.assertEqual([request.adapter_alias for request in requests], ["VLAN102", "VLAN101"])
        self.assertEqual([request.bind_ip for request in requests], ["172.18.18.3", "172.18.18.4"])
        self.assertEqual([request.device_ip for request in requests], ["192.168.29.1", "192.168.30.1"])
        self.assertTrue(all(request.username == "sdmc" for request in requests))
        self.assertTrue(all(request.password == "1234" for request in requests))
        self.assertTrue(all(request.restore_factory for request in requests))
        # 所有 PageUpgradeRequest 都带上默认 /24 子网掩码,准备网络时据此设置 PC 静态 IP
        self.assertTrue(all(request.subnet_mask == "255.255.255.0" for request in requests))
        self.assertIn("恢复出厂：开启，升级成功、设备重启并重新登录成功后将通过 UBUS 执行恢复出厂", _askyesno.call_args.args[1])
        thread_class.return_value.start.assert_called_once_with()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_page_upgrade_requests_propagate_custom_subnet_mask(self, thread_class, _is_file, _askyesno):
        channels = [
            ChannelConfig(
                section="channel_1",
                vlan_name="VLAN139",
                adapter_alias="VLAN139",
                network_card_ip="192.168.29.139",
                device_manage_ip="192.168.29.1",
                subnet_mask="255.255.255.128",
                enabled=True,
            ),
        ]
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\sdmc.bin")),
            upgrade_username_var=Mock(get=Mock(return_value="sdmc")),
            upgrade_password_var=Mock(get=Mock(return_value="1234")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_window=Mock(),
            device_ip_var=Mock(get=Mock(return_value="")),
            _selected_page_upgrade_channels=Mock(return_value=channels),
            _tftp_server_ip_for_channel=Mock(return_value=""),
            _set_upgrade_status=Mock(),
            _page_upgrade_worker=Mock(),
        )

        LineCheckAssistant._start_page_upgrade(context)

        requests = thread_class.call_args.kwargs["args"][0]
        self.assertEqual(requests[0].subnet_mask, "255.255.255.128")

    def test_page_upgrade_channels_follow_main_channel_order_and_deduplicate(self):
        context = SimpleNamespace(
            channels=[
                ChannelConfig(section="channel_1", vlan_name="VLAN108", enabled=True),
                ChannelConfig(section="channel_2", vlan_name="VLAN101", enabled=True),
                ChannelConfig(section="channel_3", vlan_name="vlan108", enabled=True),
                ChannelConfig(section="channel_4", vlan_name="VLAN102", enabled=False),
            ],
            upgrade_window=Mock(),
        )

        channels = LineCheckAssistant._selected_page_upgrade_channels(context)

        self.assertEqual([channel.section for channel in channels], ["channel_1", "channel_2"])

    @patch("line_check_assistant.app.run_page_upgrade_batch")
    def test_page_upgrade_worker_reports_completion(self, run_batch):
        request = PageUpgradeRequest(
            vlan="vlan101",
            bind_ip="172.18.18.3",
            device_ip="192.168.29.1",
            username="sdmc",
            password="1234",
            firmware_path=Mock(),
        )
        item_result = PageUpgradeItemResult(request=request, result=CommandResult(True, "vlan101 ok"))

        def fake_batch(requests, on_output=None, on_item_complete=None):
            on_output("log line")
            on_item_complete(item_result)
            return [item_result]

        run_batch.side_effect = fake_batch
        context = SimpleNamespace(
            log_queue=Mock(),
            after=Mock(side_effect=lambda _delay, callback: callback()),
            _set_upgrade_status=Mock(),
            _complete_page_upgrade=Mock(),
        )

        LineCheckAssistant._page_upgrade_worker(context, [request])

        context.log_queue.put.assert_any_call("开始 UBUS 页面升级，共 1 台样机。")
        context.log_queue.put.assert_any_call("log line")
        context.log_queue.put.assert_any_call("vlan101 ok")
        context._set_upgrade_status.assert_called_once_with("vlan101", "页面升级完成", 100)
        context._complete_page_upgrade.assert_called_once_with([item_result])

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_full_package_requests_use_page_credentials(self, thread_class, _is_file, askyesno):
        channels = [
            ChannelConfig(section="channel_1", vlan_name="VLAN102", serial_port="COM8", enabled=True),
            ChannelConfig(section="channel_2", vlan_name="VLAN101", serial_port="COM7", enabled=True),
        ]
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_execution_var=Mock(get=Mock(return_value="串行")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=2)),
            upgrade_window=Mock(),
            _selected_tftp_copy_upgrade_channels=Mock(return_value=channels),
            _full_package_tftp_server_ip_for_channel=Mock(side_effect=["192.168.1.102", "192.168.1.101"]),
            _selected_power_serial_port=Mock(return_value="COM106"),
            _set_upgrade_status=Mock(),
            _serial_tftp_copy_upgrade_worker=Mock(),
            _parallel_tftp_command_upgrade_worker=Mock(),
            _parallel_tftp_put_upgrade_worker=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._start_full_package_upgrade(context)

        upgrade_items = thread_class.call_args.kwargs["args"][0]
        requests = [request for _channel, request in upgrade_items]
        self.assertEqual([channel.section for channel, _request in upgrade_items], ["channel_1", "channel_2"])
        self.assertEqual([request.vlan for request in requests], ["vlan102", "vlan101"])
        self.assertEqual([request.tftp_server_ip for request in requests], ["192.168.1.102", "192.168.1.101"])
        self.assertEqual([request.serial_port for request in requests], ["COM8", "COM7"])
        self.assertEqual([request.power_channel for request in requests], [1, 2])
        self.assertTrue(all(request.final_username == "root" for request in requests))
        self.assertTrue(all(request.final_password == "secret" for request in requests))
        self.assertTrue(all(request.transfer_method == "Tftp Put" for request in requests))
        self.assertIn("PC 192.168.1.102 → 样机 192.168.1.1", askyesno.call_args.args[1])
        self.assertIn("恢复出厂：关闭，不会执行恢复出厂", askyesno.call_args.args[1])
        self.assertIn("不会改写 network_card_ip.ini", askyesno.call_args.args[1])

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_full_package_requires_manual_reboot_confirmation_when_power_port_empty(self, thread_class, _is_file, askyesno):
        channel = ChannelConfig(section="channel_1", vlan_name="VLAN101", enabled=True)
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp指令")),
            upgrade_execution_var=Mock(get=Mock(return_value="串行")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=1)),
            upgrade_window=Mock(),
            _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
            _full_package_tftp_server_ip_for_channel=Mock(return_value="192.168.1.101"),
            _selected_power_serial_port=Mock(return_value=""),
            _set_upgrade_status=Mock(),
            _serial_tftp_copy_upgrade_worker=Mock(),
            _parallel_tftp_command_upgrade_worker=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._start_full_package_upgrade(context)

        self.assertIn("请先手动重启样机", askyesno.call_args.args[1])
        self.assertIn("确认样机已重启后", askyesno.call_args.args[1])
        thread_class.return_value.start.assert_called_once_with()

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_tftp_command_parallel_mode_uses_parallel_worker(self, thread_class, _is_file, _askyesno):
        channel = ChannelConfig(section="channel_1", vlan_name="VLAN101", enabled=True)
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp指令")),
            upgrade_execution_var=Mock(get=Mock(return_value="并行（最多 8 台）")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=4)),
            upgrade_window=Mock(),
            _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
            _full_package_tftp_server_ip_for_channel=Mock(return_value="192.168.1.101"),
            _selected_power_serial_port=Mock(return_value="COM106"),
            _set_upgrade_status=Mock(),
            _serial_tftp_copy_upgrade_worker=Mock(),
            _parallel_tftp_command_upgrade_worker=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._start_full_package_upgrade(context)

        thread_class.assert_called_once_with(
            target=context._parallel_tftp_command_upgrade_worker,
            args=(thread_class.call_args.kwargs["args"][0], 4),
            daemon=True,
        )
        context._set_upgrade_status.assert_called_once_with("", "准备并行升级 1 台样机（最多 4 台）", 0)

    @patch("line_check_assistant.app.messagebox.askyesno", return_value=True)
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_tftp_put_parallel_mode_uses_parallel_worker(self, thread_class, _is_file, _askyesno):
        channel = ChannelConfig(section="channel_1", vlan_name="VLAN101", enabled=True)
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\\firmware\\tclinux_allinone")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_execution_var=Mock(get=Mock(return_value="并行（最多 8 台）")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=4)),
            upgrade_window=Mock(),
            _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
            _full_package_tftp_server_ip_for_channel=Mock(return_value="192.168.1.101"),
            _selected_power_serial_port=Mock(return_value="COM106"),
            _set_upgrade_status=Mock(),
            _serial_tftp_copy_upgrade_worker=Mock(),
            _parallel_tftp_command_upgrade_worker=Mock(),
            _parallel_tftp_put_upgrade_worker=Mock(),
            _log=Mock(),
        )

        LineCheckAssistant._start_full_package_upgrade(context)

        thread_class.assert_called_once_with(
            target=context._parallel_tftp_put_upgrade_worker,
            args=(thread_class.call_args.kwargs["args"][0], 4),
            daemon=True,
        )
        context._set_upgrade_status.assert_called_once_with("", "准备并行升级 1 台样机（最多 4 台）", 0)

    def test_tftp_copy_channels_follow_main_channel_order_and_deduplicate(self):
        context = SimpleNamespace(
            channels=[
                ChannelConfig(section="channel_1", vlan_name="VLAN108", enabled=True),
                ChannelConfig(section="channel_2", vlan_name="VLAN101", enabled=True),
                ChannelConfig(section="channel_3", vlan_name="vlan108", enabled=True),
                ChannelConfig(section="channel_4", vlan_name="VLAN102", enabled=False),
            ],
            upgrade_window=Mock(),
            _vlan_sort_key=lambda value: (int("".join(char for char in value if char.isdigit())), value),
        )

        channels = LineCheckAssistant._selected_tftp_copy_upgrade_channels(context)

        self.assertEqual([channel.section for channel in channels], ["channel_1", "channel_2"])

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

    def test_full_package_tftp_server_ip_ignores_channel_and_management_networks(self):
        channel = ChannelConfig(
            section="channel_1",
            vlan_name="VLAN148",
            network_card_ip="192.168.29.148",
            device_manage_ip="192.168.29.1",
        )

        self.assertEqual(
            LineCheckAssistant._full_package_tftp_server_ip_for_channel(channel),
            "192.168.1.148",
        )

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

    def test_launch_power_on_passes_selected_channels_and_wait_seconds(self):
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
            _select_power_com_port=Mock(return_value=("COM106", "上电")),
            power_serial_var=Mock(),
            _power_on_worker=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.askyesno", return_value=True) as askyesno, patch("line_check_assistant.app.threading.Thread") as thread:
            LineCheckAssistant._launch_power_on(context)

        context._power_on_wait_seconds.assert_called_once_with(channels)
        context._select_power_com_port.assert_called_once_with()
        context.power_serial_var.set.assert_called_once_with("COM106")
        askyesno.assert_called_once()
        confirmation = askyesno.call_args.args[1]
        self.assertIn("相邻开启指令间隔 1 秒", confirmation)
        self.assertIn("不会关闭任何程控电源通道", confirmation)
        self.assertNotIn("先关闭全部", confirmation)
        thread.assert_called_once_with(target=context._power_on_worker, args=("COM106", [1, 2, 3], "上电", 15), daemon=True)
        thread.return_value.start.assert_called_once_with()
        self.assertTrue(context.power_on_running)

    def test_open_power_control_saves_pipeline_settings_without_power_execution(self):
        """全流程「去配置」只保存 COM/操作类型，绝不能下发电源指令。"""
        context = SimpleNamespace(
            power_operation_var=Mock(get=Mock(return_value="down")),
            _select_power_com_port=Mock(return_value=("COM102", "下电")),
            power_serial_var=Mock(),
            _persist_config=Mock(),
            _save_sample_upgrade_settings=Mock(),
            _log=Mock(),
            pipeline_window=None,
        )

        LineCheckAssistant._open_power_control(context)

        context._select_power_com_port.assert_called_once_with(initial_action="下电")
        context.power_serial_var.set.assert_called_once_with("COM102")
        context.power_operation_var.set.assert_called_once_with("down")
        context._persist_config.assert_called_once_with()
        context._save_sample_upgrade_settings.assert_called_once_with()
        self.assertIn("未下发任何程控电源指令", context._log.call_args.args[0])

    def test_power_selector_does_not_use_negative_padding(self):
        """COM 选择弹窗在当前 Tk 环境中不能传负的 pack pady。"""
        import inspect

        source = inspect.getsource(LineCheckAssistant._select_power_com_port)
        self.assertNotIn("pady=(-7, 12)", source)
        self.assertIn("pady=(0, 12)", source)

    def test_launch_power_on_allows_empty_power_serial_port_after_manual_reboot_confirmation(self):
        channels = [ChannelConfig(section="channel_1", enabled=True)]
        context = SimpleNamespace(
            power_on_running=False,
            _capture_current_channel=Mock(),
            _selected_channels=Mock(return_value=channels),
            _power_on_wait_seconds=Mock(return_value=0),
            _select_power_com_port=Mock(return_value=("", "上电")),
            power_serial_var=Mock(),
            _power_on_worker=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.askyesno", return_value=True) as askyesno, patch("line_check_assistant.app.threading.Thread") as thread:
            LineCheckAssistant._launch_power_on(context)

        self.assertIn("请先手动重启样机", askyesno.call_args.args[1])
        context.power_serial_var.set.assert_called_once_with("")
        thread.assert_called_once_with(target=context._power_on_worker, args=("", [1], "上电", 0), daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_launch_power_on_routes_selected_channels_to_power_off(self):
        channels = [ChannelConfig(section="channel_2", enabled=True), ChannelConfig(section="channel_5", enabled=True)]
        context = SimpleNamespace(
            power_on_running=False,
            _capture_current_channel=Mock(),
            _selected_channels=Mock(return_value=channels),
            _power_on_wait_seconds=Mock(return_value=0),
            _select_power_com_port=Mock(return_value=("COM106", "下电")),
            power_serial_var=Mock(),
            _power_on_worker=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.askyesno", return_value=True) as askyesno, patch("line_check_assistant.app.threading.Thread") as thread:
            LineCheckAssistant._launch_power_on(context)

        confirmation = askyesno.call_args.args[1]
        self.assertIn("关闭全部勾选通道", confirmation)
        self.assertIn("不会执行全部断电", confirmation)
        thread.assert_called_once_with(target=context._power_on_worker, args=("COM106", [2, 5], "下电", 0), daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_launch_power_on_warns_when_no_channel_enabled(self):
        context = SimpleNamespace(
            power_on_running=False,
            _capture_current_channel=Mock(),
            _selected_channels=Mock(return_value=[]),
            _select_power_com_port=Mock(),
        )

        with patch("line_check_assistant.app.messagebox.showwarning") as showwarning:
            LineCheckAssistant._launch_power_on(context)

        showwarning.assert_called_once()
        context._select_power_com_port.assert_not_called()
        self.assertFalse(context.power_on_running)

    def test_power_on_wait_seconds_does_not_add_startup_wait(self):
        channels = [
            ChannelConfig(section="channel_1", enabled=True),
            ChannelConfig(section="channel_2", enabled=True),
        ]

        self.assertEqual(LineCheckAssistant._power_on_wait_seconds(None, channels), 0)

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

    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_serial_full_package_skips_confirmation_when_pipeline_authorized(
        self, thread_class, _is_file, askyesno
    ):
        channel = ChannelConfig(
            section="channel_1", vlan_name="VLAN101", serial_port="COM1", enabled=True
        )
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\tclinux_allinone")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_execution_var=Mock(get=Mock(return_value="串行")),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=1)),
            upgrade_window=Mock(),
            _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
            _full_package_tftp_server_ip_for_channel=Mock(return_value="192.168.1.101"),
            _selected_power_serial_port=Mock(return_value="COM106"),
            _set_upgrade_status=Mock(),
            _serial_tftp_copy_upgrade_worker=Mock(),
            _parallel_tftp_put_upgrade_worker=Mock(),
            _log=Mock(),
        )

        started = LineCheckAssistant._start_full_package_upgrade(
            context, skip_confirmation=True
        )

        self.assertTrue(started)
        askyesno.assert_not_called()
        self.assertEqual(context._log.call_count, 2)
        thread_class.return_value.start.assert_called_once_with()

    @patch("line_check_assistant.app.messagebox.askyesno")
    @patch("line_check_assistant.app.Path.is_file", return_value=True)
    @patch("line_check_assistant.app.threading.Thread")
    def test_page_upgrade_skips_confirmation_when_pipeline_authorized(
        self, thread_class, _is_file, askyesno
    ):
        channel = ChannelConfig(
            section="channel_1",
            vlan_name="VLAN101",
            network_card_ip="192.168.1.101",
            device_manage_ip="192.168.1.1",
            enabled=True,
        )
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value=r"F:\firmware\sdmc.bin")),
            upgrade_username_var=Mock(get=Mock(return_value="sdmc")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_window=Mock(),
            device_ip_var=Mock(get=Mock(return_value="192.168.1.1")),
            _selected_page_upgrade_channels=Mock(return_value=[channel]),
            _tftp_server_ip_for_channel=Mock(return_value="192.168.1.101"),
            _set_upgrade_status=Mock(),
            _page_upgrade_worker=Mock(),
            _log=Mock(),
        )

        started = LineCheckAssistant._start_page_upgrade(
            context, skip_confirmation=True
        )

        self.assertTrue(started)
        askyesno.assert_not_called()
        context._log.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()

    def test_pipeline_upgrade_bridge_forwards_unattended_authorization(self):
        page_context = SimpleNamespace(
            _open_upgrade_module=Mock(),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_mode_var=Mock(get=Mock(return_value="页面升级")),
            _start_page_upgrade=Mock(return_value=True),
        )
        serial_context = SimpleNamespace(
            _open_upgrade_module=Mock(),
            _capture_current_channel=Mock(),
            _validate_upgrade_required_fields=Mock(return_value=True),
            upgrade_transfer_var=Mock(get=Mock(return_value="Tftp Put")),
            upgrade_mode_var=Mock(get=Mock(return_value="全包升级")),
            _start_full_package_upgrade=Mock(return_value=True),
        )

        self.assertTrue(
            LineCheckAssistant._start_pipeline_sample_upgrade_on_ui(
                page_context, skip_confirmation=True
            )
        )
        self.assertTrue(
            LineCheckAssistant._start_pipeline_sample_upgrade_on_ui(
                serial_context, skip_confirmation=True
            )
        )

        page_context._start_page_upgrade.assert_called_once_with(skip_confirmation=True)
        serial_context._start_full_package_upgrade.assert_called_once_with(
            skip_confirmation=True
        )

    @patch("line_check_assistant.app.messagebox.showinfo")
    @patch("line_check_assistant.app.messagebox.showwarning")
    @patch("line_check_assistant.app.messagebox.showerror")
    def test_unattended_pipeline_tftp_completion_is_logged_without_a_dialog(
        self, showerror, showwarning, showinfo
    ):
        item = SimpleNamespace(
            request=SimpleNamespace(vlan="vlan139"),
            result=CommandResult(True, "vlan139 全包升级流程完成。"),
        )
        context = SimpleNamespace(
            _pipeline_sample_upgrade_completion_dialog_suppressed=True,
            _set_upgrade_status=Mock(),
            _log=Mock(),
            upgrade_window=Mock(),
            _finish_pipeline_subtask=Mock(),
        )

        LineCheckAssistant._complete_parallel_tftp_command_upgrade(context, 1, [item])

        showinfo.assert_not_called()
        showwarning.assert_not_called()
        showerror.assert_not_called()
        context._log.assert_called_once()
        self.assertIn("不显示完成提示框", context._log.call_args.args[0])
        self.assertFalse(context._pipeline_sample_upgrade_completion_dialog_suppressed)
        context._finish_pipeline_subtask.assert_called_once_with(
            "sample_upgrade", True, "并行 Tftp指令 升级完成：成功 1/1 台。"
        )

    def test_pipeline_parameter_bridge_forwards_unattended_authorization(self):
        context = SimpleNamespace(
            _open_sample_parameter_writer=Mock(),
            _start_sample_parameter_write=Mock(return_value=True),
        )

        self.assertTrue(
            LineCheckAssistant._start_pipeline_sample_parameter_write_on_ui(
                context, skip_confirmation=True
            )
        )

        context._start_sample_parameter_write.assert_called_once_with(skip_confirmation=True)
        self.assertTrue(context._pipeline_sample_parameter_completion_dialog_suppressed)

    @patch("line_check_assistant.app.messagebox.showinfo")
    @patch("line_check_assistant.app.messagebox.showwarning")
    @patch("line_check_assistant.app.messagebox.showerror")
    def test_unattended_pipeline_parameter_completion_is_logged_without_a_dialog(
        self, showerror, showwarning, showinfo
    ):
        result = SimpleNamespace(
            ok=True,
            request=SimpleNamespace(vlan="vlan139"),
            message="vlan139 写参并读回校验成功。",
        )
        context = SimpleNamespace(
            parameter_write_running=True,
            parameter_cancel_event=Mock(),
            parameter_writer_window=Mock(),
            parameter_write_button=Mock(),
            parameter_cancel_button=Mock(),
            serial_terminal=Mock(),
            parameter_status_var=Mock(),
            _pipeline_sample_parameter_completion_dialog_suppressed=True,
            _log=Mock(),
            _finish_pipeline_subtask=Mock(),
        )
        context.parameter_writer_window.winfo_exists.return_value = True

        LineCheckAssistant._complete_sample_parameter_write(context, [result])

        showinfo.assert_not_called()
        showwarning.assert_not_called()
        showerror.assert_not_called()
        self.assertFalse(context._pipeline_sample_parameter_completion_dialog_suppressed)
        self.assertTrue(
            any(
                "不显示完成提示框" in call.args[0]
                for call in context._log.call_args_list
            )
        )
        context._finish_pipeline_subtask.assert_called_once_with(
            "sample_parameter_write", True, "写样机参数完成：1/1 台成功。"
        )

    @patch("line_check_assistant.app.query_device_project_info")
    @patch("line_check_assistant.app.threading.Thread")
    def test_project_info_query_uses_current_channel_and_returns_to_ui_thread(
        self, thread_class, query_project_info
    ):
        result = SimpleNamespace(
            software_version="S13.58.01.001",
            internal_software_version="T13.58.01.003",
            onu_compile_time="Mon Jun 8 10:16:25 UTC 2026",
        )
        query_project_info.return_value = result
        context = SimpleNamespace(
            _capture_current_channel=Mock(),
            current_index=0,
            channels=[
                ChannelConfig(
                    section="channel_1",
                    vlan_name="VLAN139",
                    network_card_ip="192.168.1.139",
                    device_manage_ip="192.168.1.1",
                )
            ],
            _log=Mock(),
            log_queue=Mock(),
            after=Mock(side_effect=lambda _delay, callback: callback()),
            test_item_config_window=Mock(),
        )
        applied: list[object] = []

        LineCheckAssistant._start_project_info_query(
            context, TelnetSettings(user="root", password="secret"), applied.append
        )
        worker = thread_class.call_args.kwargs["target"]
        worker()

        request = query_project_info.call_args.args[0]
        self.assertEqual(request.bind_ip, "192.168.1.139")
        self.assertEqual(request.device_host, "192.168.1.1")
        self.assertEqual(request.telnet.user, "root")
        self.assertEqual(applied, [result])

    def test_project_info_tab_keeps_manual_versions_separate_from_read_only_query_results(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._build_test_item_project_info_tab)

        self.assertIn("查询当前样机版本", source)
        self.assertIn("当前样机查询结果（只读）", source)
        self.assertIn("queried_software_version_var", source)
        self.assertIn("结果仅供查看，不会覆盖手动输入或写入 INI", source)
        self.assertIn('state="readonly"', source)
        self.assertIn('"<Button-3>"', source)
        self.assertIn('label="复制全部"', source)
        self.assertNotIn("\n    software_version_var.set(result.software_version)", source)
        self.assertNotIn(
            "\n    internal_software_version_var.set(result.internal_software_version)", source
        )
        self.assertNotIn("\n    onu_compile_time_var.set(result.onu_compile_time)", source)
        self.assertIn("cat /etc/config/deviceinfo", source)
        self.assertIn("cat /proc/version", source)

    def test_power_test_channel_states_stay_in_overview_and_summarize_final_results(self):
        channels = [
            ChannelConfig(section="channel_2", enabled=True),
            ChannelConfig(section="channel_7", enabled=True),
            ChannelConfig(section="channel_8", enabled=True),
        ]
        context = SimpleNamespace(
            channels=channels,
            power_test_channel_states={},
            power_test_channel_progresses={},
            channel_list=Mock(),
        )
        context._apply_power_test_channel_color = (
            LineCheckAssistant._apply_power_test_channel_color.__get__(context)
        )

        LineCheckAssistant._set_power_test_channel_state(context, 7, "retry", "retry")
        context.channel_list.itemconfig.assert_not_called()
        LineCheckAssistant._set_power_test_channel_state(context, 7, "success", "retry success")
        context.channel_list.itemconfig.assert_not_called()
        LineCheckAssistant._set_power_test_channel_state(context, 7, "failed", "ponmgr failed")
        LineCheckAssistant._set_power_test_channel_state(context, 2, "success", "all passed")
        LineCheckAssistant._set_power_test_channel_state(context, 8, "success", "all passed")

        self.assertEqual(
            LineCheckAssistant._power_test_channel_result_summary(context),
            "\u901a\u90532\u6240\u6709\u6d4b\u8bd5\u9879\u9a8c\u8bc1\u6210\u529f\n"
            "\u901a\u90537ponmgr failed\n"
            "\u901a\u90538\u6240\u6709\u6d4b\u8bd5\u9879\u9a8c\u8bc1\u6210\u529f",
        )
        context.channel_list.itemconfig.assert_not_called()

    def test_power_test_channel_progress_keeps_left_list_plain_and_renders_card_overview(self):
        import inspect

        source = inspect.getsource(LineCheckAssistant._render_power_test_channel_overview)
        color_source = inspect.getsource(LineCheckAssistant._apply_power_test_channel_color)

        self.assertIn("第 {current_cycle} 轮：已完成", source)
        self.assertIn("关注：", source)
        self.assertIn("self.power_test_channel_attention_label.pack_forget()", source)
        self.assertIn("if attention_text:", source)
        self.assertIn("通道 {number}  {completed}/{total}", source)
        self.assertIn("self._show_power_test_channel_detail", source)
        self.assertIn("open_history=True", source)
        self.assertNotIn("power_test_channel_history_frame", source)
        self.assertIn("foreground=COLOR_TEXT", color_source)
        self.assertNotIn("COLOR_WARNING", color_source)
        self.assertNotIn("COLOR_DANGER", color_source)

    def test_power_test_channel_progress_updates_independent_round_before_rendering(self):
        render = Mock()
        context = SimpleNamespace(
            power_test_channel_progresses={},
            _render_power_test_channel_overview=render,
        )

        LineCheckAssistant._set_power_test_channel_progress(
            context,
            3,
            6,
            20,
            "第7轮执行中",
        )

        self.assertEqual(
            context.power_test_channel_progresses,
            {3: (6, 20, "第7轮执行中")},
        )
        render.assert_called_once_with()


    def test_power_test_channel_history_is_isolated_and_keeps_retry_success(self):
        render = Mock()
        context = SimpleNamespace(
            power_test_channel_histories={},
            _render_power_test_channel_overview=render,
        )

        LineCheckAssistant._record_power_test_channel_history(
            context, 2, 3, "retry", "\u51c6\u5907\u7b2c2/3\u6b21\u9a8c\u8bc1"
        )
        LineCheckAssistant._record_power_test_channel_history(
            context, 7, 1, "failed", "\u5df2\u9a8c\u8bc13\u6b21\u5931\u8d25"
        )
        LineCheckAssistant._record_power_test_channel_history(
            context, 2, 3, "success", "\u91cd\u8bd5 1 \u6b21\u540e\u9a8c\u8bc1\u6210\u529f"
        )
        LineCheckAssistant._record_power_test_channel_history(
            context, 2, 3, "success", "\u6240\u6709\u6d4b\u8bd5\u9879\u9a8c\u8bc1\u6210\u529f"
        )

        self.assertEqual(
            context.power_test_channel_histories,
            {
                2: [
                    (3, "retry", "\u51c6\u5907\u7b2c2/3\u6b21\u9a8c\u8bc1"),
                    (3, "success", "\u91cd\u8bd5 1 \u6b21\u540e\u9a8c\u8bc1\u6210\u529f"),
                ],
                7: [(1, "failed", "\u5df2\u9a8c\u8bc13\u6b21\u5931\u8d25")],
            },
        )
        self.assertEqual(render.call_count, 3)

    def test_power_test_channel_click_opens_separate_history_window(self):
        detail_var = Mock()
        open_history_window = Mock()
        refresh_history_window = Mock()
        context = SimpleNamespace(
            power_test_channel_progresses={2: (3, 5, "running")},
            power_test_channel_states={2: ("retry", "retry detail")},
            power_test_channel_detail_var=detail_var,
            _open_power_test_channel_history_window=open_history_window,
            _refresh_power_test_channel_history_window=refresh_history_window,
        )

        LineCheckAssistant._show_power_test_channel_detail(
            context, 2, open_history=True
        )

        self.assertEqual(context.power_test_channel_selected_number, 2)
        detail_var.set.assert_called_once()
        open_history_window.assert_called_once_with(2)
        refresh_history_window.assert_not_called()

    def test_power_test_channel_reset_clears_only_current_run_history(self):
        render = Mock()
        detail_var = Mock()
        context = SimpleNamespace(
            channels=[ChannelConfig(section="channel_2"), ChannelConfig(section="channel_7")],
            power_test_channel_states={2: ("retry", "retry"), 7: ("failed", "failed")},
            power_test_channel_progresses={2: (1, 3, "running"), 7: (1, 3, "running")},
            power_test_channel_histories={2: [(1, "retry", "retry")], 7: [(1, "failed", "failed")]},
            power_test_channel_detail_var=detail_var,
            power_test_channel_selected_number=2,
            _render_power_test_channel_overview=render,
            channel_list=Mock(),
        )
        context._apply_power_test_channel_color = (
            LineCheckAssistant._apply_power_test_channel_color.__get__(context)
        )

        LineCheckAssistant._reset_power_test_channel_states(context, [2])

        self.assertNotIn(2, context.power_test_channel_histories)
        self.assertEqual(context.power_test_channel_histories[7], [(1, "failed", "failed")])
        self.assertIsNone(context.power_test_channel_selected_number)
        detail_var.set.assert_called_once_with("")
        render.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

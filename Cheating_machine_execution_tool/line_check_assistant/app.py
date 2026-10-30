from __future__ import annotations

from src.models.upgrade_stop import UpgradeStopped, UpgradeStoppedResult
from src.services.upgrade_stop_service import UpgradeRun, result_state, summarize_results
from src.models.boot_entry import BOOT_ENTRY_LOGIN, BOOT_ENTRY_OPTIONS, normalize_boot_entry
from src.services.web_gateway_upgrade_service import (
    TRANSFER_WEB_GATEWAY, run_parallel_web_gateway_upgrades, validate_web_target,
)

import os
import queue
import re
import sys
import threading
from datetime import datetime
from src.services.test_item_pretest_service import prepare_pretest_request
from src.ui.test_item_pretest_controls import PretestControls
from src.ui.app_update_dialog import AppUpdateDialog, arrange_update_toolbar
from src.ui.project_name_badge import ProjectNameBadge
from src.ui.adapter_rename_dialog import offer_adapter_rename
from src.services.adapter_rename_service import (
    adapter_has_numeric_suffix, adapter_rename_is_busy, synchronize_channel_adapter_names,
)
from pathlib import Path
from tkinter import BooleanVar, Button, Canvas, Checkbutton, DoubleVar, END, Frame, IntVar, Label, Listbox, Menu, StringVar, TclError, Text, Tk, Toplevel, filedialog, messagebox, ttk

from .config_store import ChannelConfig, ChannelConfigStore, DEFAULT_POWER_SERIAL_PORT, DEFAULT_SUBNET_MASK
from .legacy_ui_defaults_store import LegacyUiDefaultsStore, TELNET_ENABLE_OPTION
from src.services.message_push_config_service import MessagePushConfigService
from src.ui.message_push_tab import MessagePushTab
from .network_ops import (
    CommandResult,
    adapter_alias_from_display,
    is_admin,
    list_adapter_display_names,
    run_line_check,
    static_ip_for_vlan,
    factory_bind_ip_for,
    factory_device_host_for,
)
from .onu_registration_store import (
    DEFAULT_C300_SERVICES,
    DEFAULT_C600_SERVICES,
    OnuRegistrationConfig,
    OnuRegistrationStore,
)
from .page_upgrade import PageUpgradeRequest, run_page_upgrade_batch
from .paths import resolve_config_dir, resolve_tool_root
from .sample_upgrade_settings_store import (
    DEFAULT_PARAMETER_PARALLEL_COUNT,
    DEFAULT_PARALLEL_COUNT,
    DEFAULT_UPGRADE_MODE,
    DEFAULT_UPGRADE_TRANSFER,
    MAX_PARALLEL_UPGRADES,
    SampleUpgradeSettings,
    SampleUpgradeSettingsStore,
    clamp_parameter_parallel_count,
    clamp_parallel_count,
)
from .serial_ports import list_prolific_ports, port_from_display
from .test_item_config_store import (
    DEFAULT_COMMAND_FAIL_RETRY_INTERVAL,
    ConnectWifiSettings,
    ExpectedSegment,
    OrderConfig,
    OrderItem,
    ProjectInfoSettings,
    TelnetSettings,
    TestItemConfigStore,
    TestProjectConfig,
    WIFI_AUTH_MODE_OPTIONS,
    WIFI_CIPHER_OPTIONS,
)
from src.core.wifi_interfaces import list_wifi_interface_names
from src.core.zte_c600_onu import parse_service_mappings, speed_mode_to_cli
from src.core import (
    SerialSessionManager,
    generate_parameter_records,
    load_parameter_records,
    save_parameter_records_xlsx,
    vlan_to_serial_port,
)
from src.config import DEFAULT_LOG_DIR
from src.models import (
    DutAdvancedConfigRequest,
    DutAdvancedConfigResult,
    DutAdvancedQueryResult,
    DutTelnetEnableRequest,
    DutTelnetEnableResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutWifiSettings,
    DutWanQueryResult,
    DutWanSettings,
    FullPackageUpgradeRequest,
    OLT_FAMILIES,
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OltConnection,
    OnuDiscoveryScope,
    OnuProvisionRequest,
    ParameterGenerationTemplate,
    RegisteredOnu,
    SampleParameterWriteRequest,
)
from src.services import (
    DEFAULT_DUT_PARALLEL_COUNT,
    PARAMETER_MAX_PARALLEL,
    PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS,
    TRANSFER_TFTP_COMMAND,
    TRANSFER_TFTP_PUT,
    build_dut_wifi_settings_sequence,
    clamp_dut_parallel_count,
    common_wan_connection_details,
    common_wan_connection_names,
    common_dut_status_settings,
    preflight_parameter_targets,
    run_dut_telnet_enable_batch,
    run_dut_advanced_config_batch,
    run_dut_status_query_batch,
    run_dut_wan_query_batch,
    run_parallel_tftp_command_upgrades,
    run_parallel_tftp_put_upgrades,
    run_parallel_sample_parameter_writes,
    run_single_sample_parameter_write,
    latest_power_test_result_log,
    turn_off_selected_channels,
    turn_on_selected_channels,
    validate_dut_telnet_request,
    validate_dut_advanced_request,
)
from src.services.onu_registration_service import OnuRegistrationService
from src.services.onu_batch_registration_service import build_batch_requests
from src.ui.onu_command_editor import OnuCommandEditor, command_plan_summary
from src.services.device_project_info_service import (
    DeviceProjectInfo,
    DeviceProjectInfoQueryRequest,
    query_device_project_info,
)
from src.services.telnet_post_login_service import describe_telnet_post_login
from src.ui import (
    MODULE_WINDOW_SIZE_STATE_PATH,
    DutConfigWindow,
    SerialTerminalWindow,
    load_module_window_size,
    save_module_window_size,
)
from src.ui.window_paint import (
    center_toplevel_on_parent,
    schedule_toplevel_client_refresh,
)


APP_DIR = resolve_tool_root()
CONFIG_DIR = resolve_config_dir(APP_DIR)
NETWORK_CONFIG_PATH = CONFIG_DIR / "network_card_ip.ini"
ONU_REGISTRATION_CONFIG_PATH = CONFIG_DIR / "onu_registration.ini"
SAMPLE_UPGRADE_SETTINGS_PATH = CONFIG_DIR / "sample_upgrade_settings.ini"
# 测试项配置 ini：窗口负责加载/保存，并提供独立的单次预备测试入口。
TEST_ITEM_CONFIG_PATH = CONFIG_DIR / "test_project_config.ini"
TEST_ITEM_DEFAULT_CONFIG_PATH = CONFIG_DIR / "test_project_config.default.ini"
LEGACY_UI_DEFAULTS_CONFIG_PATH = CONFIG_DIR / "config.ini"
LOG_DIR = APP_DIR / "assistant_logs"
POWER_SUPPLY_COUNT = 6
TOTAL_CHANNEL_COUNT = 16
VLAN_PER_POWER_SUPPLY = 8
FIRST_VLAN_ID = 101
POWER_ON_WAIT_SECONDS = 0
POWER_ACTION_ON = "上电"
POWER_ACTION_OFF = "下电"
POWER_ACTION_OPTIONS = (POWER_ACTION_ON, POWER_ACTION_OFF)
CHANNEL_LIST_FONT = ("Microsoft YaHei UI", 11)
CHANNEL_FIELD_WIDTH = 42
TEST_ITEM_COMMAND_GROUP_SPACING = 14
LEGACY_CHANNEL_TEST_START_PATTERN = re.compile(
    r"^\[旧工具Logs\]\[INFO\].*通道\s*【\d+】\s*开始第\s*\d+\s*次测试"
)
TEST_ITEM_HIDDEN_UI_DEFAULT_OPTIONS = frozenset(
    {
        TELNET_ENABLE_OPTION,
        "communication_method",
        "baud_rate",
        "selected_profile",
    }
)
MODULE_WINDOW_SIZE_SPECS = {
    "sample_parameter_writer": (980, 690, 860, 590),
    "onu_registration": (1000, 900, 1000, 900),
    "sample_upgrade": (820, 720, 820, 620),
    "test_item_config": (960, 940, 960, 940),
    "pipeline": (920, 800, 880, 780),
}


def _clear_test_item_rows(row_widgets: list[dict]) -> None:
    """销毁全部测试项命令行，避免遍历时删除原列表导致隔行残留。"""
    for row_dict in tuple(row_widgets):
        row_dict["remove"]()
    row_widgets.clear()


def power_channel_from_section(section: str) -> int:
    try:
        return int(section.lower().replace("channel_", ""))
    except ValueError:
        return 0


def _power_serial_group_index(serial_port: str) -> int:
    normalized_port = (port_from_display(serial_port) or serial_port or "").strip().upper()
    port_number = normalized_port[3:] if normalized_port.startswith("COM") else ""
    try:
        raw_index = int(port_number)
    except ValueError:
        return 0
    if 101 <= raw_index < 101 + POWER_SUPPLY_COUNT:
        return raw_index - 100
    if 1 <= raw_index <= POWER_SUPPLY_COUNT:
        # 兼容操作员口头所说的 COM1 / COM2；实际程控电源项仍为 COM101 / COM102。
        return raw_index
    return 0


def serial_options_for_power_serial_port(serial_port: str) -> list[str]:
    """按程控电源分组返回样机串口候选，每组连续8个COM口。"""
    power_index = _power_serial_group_index(serial_port)
    if not power_index:
        return [f"COM{index}" for index in range(1, POWER_SUPPLY_COUNT * VLAN_PER_POWER_SUPPLY + 1)]
    start_port = (power_index - 1) * VLAN_PER_POWER_SUPPLY + 1
    return [f"COM{index}" for index in range(start_port, start_port + VLAN_PER_POWER_SUPPLY)]


def vlan_options_for_power_serial_port(adapters: list[str], serial_port: str) -> list[str]:
    """返回指定程控电源 COM 口对应的 VLAN 网卡候选。

    每台程控电源管理连续 8 个 VLAN：COM101 对应 VLAN101–108、
    COM102 对应 VLAN109–116，依此类推。未选择 COM 时展示所有识别
    网卡；传入未知 COM 口时保留全部 VLAN 网卡，避免异常配置导致
    配置页没有可选项。
    """
    normalized_port = (port_from_display(serial_port) or serial_port or "").strip().upper()
    if not normalized_port:
        options_by_alias: dict[str, str] = {}
        for adapter in adapters:
            alias = adapter_alias_from_display(adapter)
            if alias:
                options_by_alias.setdefault(alias.lower(), adapter)
        return sorted(options_by_alias.values(), key=lambda value: adapter_alias_from_display(value).lower())

    power_index = _power_serial_group_index(normalized_port)

    start_vlan = FIRST_VLAN_ID + (power_index - 1) * VLAN_PER_POWER_SUPPLY
    end_vlan = start_vlan + VLAN_PER_POWER_SUPPLY - 1

    options_by_alias: dict[str, str] = {}
    for adapter in adapters:
        alias = adapter_alias_from_display(adapter)
        match = re.fullmatch(r"vlan(\d+)", alias, flags=re.IGNORECASE)
        if not match:
            continue
        vlan_id = int(match.group(1))
        if power_index and not start_vlan <= vlan_id <= end_vlan:
            continue
        options_by_alias.setdefault(alias.lower(), adapter)

    return sorted(
        options_by_alias.values(),
        key=lambda value: (
            int(re.search(r"\d+", adapter_alias_from_display(value)).group())
            if re.search(r"\d+", adapter_alias_from_display(value))
            else 999999,
            adapter_alias_from_display(value).lower(),
        ),
    )
CHANNEL_TABLE_COMBO_WIDTH = 32
CHANNEL_TABLE_SERIAL_COMBO_WIDTH = 12
CHANNEL_TABLE_GROUP_GAP = 24
CHANNEL_TABLE_ROWS_PER_GROUP = 4
UPGRADE_MODE_OPTIONS = ("页面升级", DEFAULT_UPGRADE_MODE)
TFTP_COMMAND_TRANSFER = TRANSFER_TFTP_COMMAND
TFTP_PUT_TRANSFER = TRANSFER_TFTP_PUT
FULL_PACKAGE_DEVICE_IP = "192.168.1.1"
LEGACY_TFTP_COPY_TRANSFER = "Tftp拷贝命令"
UPGRADE_TRANSFER_OPTIONS = (DEFAULT_UPGRADE_TRANSFER, TFTP_COMMAND_TRANSFER, "web打开网关")
SERIAL_FULL_PACKAGE_TRANSFERS = {TFTP_COMMAND_TRANSFER, TFTP_PUT_TRANSFER, TRANSFER_WEB_GATEWAY}
MAIN_LOG_EVENTS_PER_TICK = 120
MAIN_LOG_IDLE_DELAY_MS = 200
FONT_FAMILY = "Microsoft YaHei UI"
COLOR_BG = "#eef2f5"
COLOR_SURFACE = "#ffffff"
COLOR_SURFACE_SUBTLE = "#f7f9fb"
COLOR_BORDER = "#d5dce3"
COLOR_TEXT = "#17202a"
COLOR_MUTED = "#65717f"
COLOR_PRIMARY = "#0f766e"
COLOR_PRIMARY_DARK = "#115e59"
COLOR_PRIMARY_SOFT = "#d9f0ed"
COLOR_SECONDARY = "#e7ecef"
COLOR_SECONDARY_HOVER = "#dbe3e8"
COLOR_LOG_BG = "#f9fbfc"
COLOR_SUCCESS = "#047857"
COLOR_SUCCESS_BG = "#e8f5ef"
COLOR_WARNING = "#a16207"
COLOR_WARNING_BG = "#f8f0dd"
COLOR_DANGER = "#b42318"
COLOR_DANGER_DARK = "#8f1c13"
COLOR_DANGER_BG = "#fbe9e7"
APPLICATION_NAME = "openWRT老化测试环境搭建助手"
VERSION_INFO_FILENAME = "VERSION_INFO.txt"


def _load_release_version() -> str:
    """从随发布包提供的版本说明中读取当前发布版本。"""
    if getattr(sys, "frozen", False):
        version_info_paths = [Path(sys._MEIPASS) / VERSION_INFO_FILENAME]
    else:
        version_info_paths = [
            Path(__file__).resolve().parent / "packaging_assets" / VERSION_INFO_FILENAME
        ]

    for version_info_path in version_info_paths:
        try:
            match = re.search(
                r"^版本：\s*(\S+)",
                version_info_path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
        except OSError:
            continue
        if match:
            return match.group(1)
    return "未标注版本"


RELEASE_VERSION = _load_release_version()
MAIN_WINDOW_TITLE = f"{APPLICATION_NAME} {RELEASE_VERSION}"


def _finish_pipeline_subtask_if_waiting(app, code: str, ok: bool, detail: str) -> None:
    """仅在全流程等待该异步任务时回传完成结果；单功能入口保持原行为。"""
    finish = getattr(app, "_finish_pipeline_subtask", None)
    if callable(finish):
        finish(code, ok, detail)


class LineCheckAssistant(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(MAIN_WINDOW_TITLE)
        self.geometry("1200x780")
        self.minsize(1040, 700)
        self.configure(background=COLOR_BG)
        self._configure_theme()

        self.store = ChannelConfigStore(NETWORK_CONFIG_PATH)
        self.onu_registration_store = OnuRegistrationStore(ONU_REGISTRATION_CONFIG_PATH)
        self.onu_registration_config = self.onu_registration_store.load()
        self.sample_upgrade_settings_store = SampleUpgradeSettingsStore(SAMPLE_UPGRADE_SETTINGS_PATH)
        self.sample_upgrade_settings = self.sample_upgrade_settings_store.load()
        self._module_window_size_state_path = MODULE_WINDOW_SIZE_STATE_PATH
        self.channels = self.store.load()
        self.power_serial_port = self.store.load_power_serial_port()
        self.adapters = list_adapter_display_names()
        self.power_serial_options = self._build_power_serial_options()
        if self.power_serial_port not in self.power_serial_options:
            self.power_serial_port = DEFAULT_POWER_SERIAL_PORT
        self._ensure_channel_slots()
        self.current_index = 0 if self.channels else -1
        self._last_selected_index = self.current_index
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        # 全流程编排器在后台线程运行；涉及 Tk 窗口/确认框的子任务必须投回主线程，
        # 不能由编排线程直接操作 Toplevel。
        self.pipeline_ui_task_queue: "queue.Queue[tuple]" = queue.Queue()
        self.dut_config_ui_queue: "queue.Queue[tuple]" = queue.Queue()
        self._pipeline_subtask_events: dict[str, threading.Event] = {}
        self._pipeline_subtask_results: dict[str, tuple[bool, str]] = {}
        self.running = False
        self.power_on_running = False
        self.power_test_channel_states: dict[int, tuple[str, str]] = {}
        self.power_test_channel_progresses: dict[int, tuple[int, int, str]] = {}
        self.power_test_channel_histories: dict[int, list[tuple[int, str, str]]] = {}
        self.power_test_channel_selected_number: int | None = None
        self.power_test_channel_history_window = None
        self.power_test_channel_history_text = None
        self.power_test_channel_history_title_var = StringVar(value="")
        self.power_test_channel_overview_expanded = True
        self.power_test_channel_overview_shown = False
        self.power_test_channel_summary_var = StringVar(value="")
        self.power_test_channel_attention_var = StringVar(value="")
        self.power_test_channel_detail_var = StringVar(value="")
        self.upgrade_window = None
        self.parameter_writer_window = None
        self.parameter_write_running = False
        self.parameter_records = []
        # 当前内存中已成功加载的参数表。窗口重新打开时用它判断是否需要从持久化路径恢复记录。
        self.parameter_loaded_table_path = ""
        self.parameter_preflight = None
        self.parameter_cancel_event = None
        self.serial_session_manager = SerialSessionManager()
        self.serial_terminal = SerialTerminalWindow(self, self.serial_session_manager, self._serial_log_directory())
        self.dut_config_window = None
        self.dut_config_running = False
        self.dut_config_cancel_event = None
        self.dut_config_active_feature = None
        self.dut_config_requests: list[DutTelnetEnableRequest] = []
        self.dut_config_validation_errors: dict[str, str] = {}
        self.test_item_config_window = None
        self.pipeline_window = None
        self.power_test_running = False
        self.power_test_status_var = StringVar(value="开关机测试状态：未运行")
        self.power_test_progress_text_var = StringVar(value="开关机测试进度：等待开始")
        self.onu_registration_window = None
        self.onu_telnet_test_running = False
        self.onu_query_running = False
        self.onu_template_query_running = False
        self.onu_register_running = False
        self.onu_save_olt_running = False
        self.onu_save_after_id = None
        saved_onu_family = self.onu_registration_config.olt_family
        if saved_onu_family not in OLT_FAMILIES:
            saved_onu_family = OLT_FAMILY_C300
        self.onu_family_var = StringVar(value=saved_onu_family)
        self.onu_active_family = saved_onu_family
        self.onu_connection_profiles = {
            OLT_FAMILY_C300: {
                "olt_ip": self.onu_registration_config.c300_olt_ip,
                "source_ip": self.onu_registration_config.c300_source_ip,
                "username": self.onu_registration_config.c300_username,
                "password": self.onu_registration_config.c300_password,
            },
            OLT_FAMILY_C600: {
                "olt_ip": self.onu_registration_config.c600_olt_ip,
                "source_ip": self.onu_registration_config.c600_source_ip,
                "username": self.onu_registration_config.c600_username,
                "password": self.onu_registration_config.c600_password,
            },
        }
        self.onu_olt_ip_var = StringVar(value=self.onu_registration_config.olt_ip)
        self.onu_source_ip_var = StringVar(value=self.onu_registration_config.source_ip)
        self.onu_username_var = StringVar(value=self.onu_registration_config.username)
        self.onu_password_var = StringVar(value=self.onu_registration_config.password)
        self.onu_c600_shelf_var = StringVar(value=str(self.onu_registration_config.c600_shelf))
        self.onu_c600_slot_var = StringVar(value=str(self.onu_registration_config.c600_slot))
        self.onu_c600_pon_var = StringVar(value=str(self.onu_registration_config.c600_pon))
        self.onu_c600_onu_id_var = StringVar(value=str(self.onu_registration_config.c600_onu_id))
        self.onu_c600_onu_type_var = StringVar(value=self.onu_registration_config.c600_onu_type)
        self.onu_c600_real_speed_var = StringVar(value=self.onu_registration_config.c600_real_speed)
        self.onu_c600_tcont_id_var = StringVar(value=str(self.onu_registration_config.c600_tcont_id))
        self.onu_c600_tcont_profile_var = StringVar(value=self.onu_registration_config.c600_tcont_profile)
        self.onu_c600_gemport_id_var = StringVar(value=str(self.onu_registration_config.c600_gemport_id))
        self.onu_c600_vport_id_var = StringVar(value=str(self.onu_registration_config.c600_vport_id))
        self.onu_c600_sn_bind_both_var = BooleanVar(value=self.onu_registration_config.c600_sn_bind_both)
        self.onu_c300_shelf_var = StringVar(value=str(self.onu_registration_config.c300_shelf))
        self.onu_c300_slot_var = StringVar(value=str(self.onu_registration_config.c300_slot))
        self.onu_c300_pon_var = StringVar(value=str(self.onu_registration_config.c300_pon))
        self.onu_c300_onu_id_var = StringVar(value=str(self.onu_registration_config.c300_onu_id))
        self.onu_c300_onu_type_var = StringVar(value=self.onu_registration_config.c300_onu_type)
        self.onu_c300_tcont_id_var = StringVar(value=str(self.onu_registration_config.c300_tcont_id))
        self.onu_c300_tcont_profile_var = StringVar(value=self.onu_registration_config.c300_tcont_profile)
        self.onu_c600_write_after_success_var = BooleanVar(value=False)
        self.onu_c300_allow_offline_cleanup_var = BooleanVar(
            value=self.onu_registration_config.c300_allow_offline_cleanup
        )
        self.onu_password_visible = False
        self.onu_telnet_status_var = StringVar(value="")
        self.onu_query_status_var = StringVar(value="")
        self.onu_c600_selection_var = StringVar(value="")
        self.onu_unregistered_selection_vars = []
        self.onu_target_id_inputs = {}
        self.onu_active_id_target = None
        self.onu_c300_cleanup_candidates = ()
        self.onu_c300_cleanup_candidate_var = StringVar(value="")
        self.onu_cleanup_query_running = False
        self.onu_manage_shelf_var = StringVar(value="1")
        self.onu_manage_slot_var = StringVar(value="1")
        self.onu_manage_pon_var = StringVar(value="1")
        self.onu_registered_candidates = ()
        self.onu_registered_candidate_var = StringVar(value="")
        self.onu_manage_query_running = False
        self.onu_manage_delete_running = False
        self.onu_preview_ready = False
        self.onu_cancel_event = threading.Event()
        self._bind_onu_registration_autosave()
        upgrade_mode = self.sample_upgrade_settings.upgrade_mode if self.sample_upgrade_settings.upgrade_mode in UPGRADE_MODE_OPTIONS else DEFAULT_UPGRADE_MODE
        saved_transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.sample_upgrade_settings.transfer_method)
        transfer_method = saved_transfer_method if saved_transfer_method in UPGRADE_TRANSFER_OPTIONS else DEFAULT_UPGRADE_TRANSFER
        self.sample_upgrade_save_after_id = None
        self.upgrade_mode_var = StringVar(value=upgrade_mode)
        self.upgrade_transfer_var = StringVar(value=transfer_method)
        self.upgrade_boot_entry_var = StringVar(value=normalize_boot_entry(self.sample_upgrade_settings.boot_entry_method))
        self.upgrade_parallel_count_var = IntVar(
            value=clamp_parallel_count(self.sample_upgrade_settings.parallel_count)
        )
        restore_factory_enabled = bool(self.sample_upgrade_settings.restore_factory)
        self.upgrade_restore_factory_var = BooleanVar(value=restore_factory_enabled)
        self.upgrade_restore_factory_text_var = StringVar(value=LineCheckAssistant._restore_factory_text(restore_factory_enabled))
        self.upgrade_username_var = StringVar(value=self.sample_upgrade_settings.username)
        self.upgrade_password_var = StringVar(value=self.sample_upgrade_settings.password)
        self.upgrade_password_visible = False
        self.upgrade_firmware_var = StringVar(value=self.sample_upgrade_settings.firmware_path)
        self.upgrade_targets_var = StringVar(value="未勾选目标样机")
        self.sample_upgrade_running = False
        self._sample_upgrade_run = None
        self.upgrade_status_var = StringVar(value="尚未开始升级")
        self.upgrade_progress_var = DoubleVar(value=0)
        # 写样机参数窗口的「首次登录账号 / 密码」也走同一份 sample_upgrade_settings.ini,
        # 与升级超级凭据分两个独立 key;作为主程序实例变量持久存在,值变更通过 trace_add 自动写盘。
        self.parameter_initial_username_var = StringVar(value=self.sample_upgrade_settings.parameter_initial_username)
        self.parameter_initial_password_var = StringVar(value=self.sample_upgrade_settings.parameter_initial_password)
        self.parameter_parallel_count_var = IntVar(
            value=clamp_parameter_parallel_count(
                self.sample_upgrade_settings.parameter_parallel_count
            )
        )
        # 写样机参数流水线两个可选行为(2026-07-19):清空参数 / 退出老化,
        # 默认关闭,操作员勾选后下次写参时下发对应命令。
        self.parameter_clear_parameters_var = BooleanVar(value=self.sample_upgrade_settings.parameter_clear_parameters)
        self.parameter_exit_aging_var = BooleanVar(value=self.sample_upgrade_settings.parameter_exit_aging)
        # 2026-07-20:全流程执行管道(主界面「检查并执行测试」)需要两个 Tk 变量:
        # - ``power_operation_var``:「自动上/下电」子任务的上/下电选项("up" / "down")
        # - ``parameter_table_path_var``:「写样机参数」子任务的参数表文件路径
        self.power_operation_var = StringVar(value=self.sample_upgrade_settings.power_operation or "up")
        self.parameter_table_path_var = StringVar(value=self.sample_upgrade_settings.parameter_table_path or "")
        self._bind_sample_upgrade_autosave()
        LOG_DIR.mkdir(exist_ok=True)
        self.log_path = LOG_DIR / f"line_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        self._build_ui()
        self._refresh_saved_project_name()
        self.bind(
            "<ButtonPress-1>", self._bring_main_window_to_front, add="+"
        )
        self._load_current_channel()
        self._show_startup_warnings()
        self.after_idle(self._maximize_window)
        self.after(200, self._drain_log_queue)
        self.after(50, self._drain_pipeline_ui_tasks)
        self.after(50, self._drain_dut_config_ui_tasks)
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except Exception:
            return

    def _bring_main_window_to_front(self, _event=None) -> None:
        """主界面任意位置被点击时升层，不强制改写当前控件焦点。"""
        try:
            self.lift()
        except Exception:
            # 应用退出过程中Tk窗口可能已销毁，点击升层无需阻断关闭流程。
            return

    def _on_app_close(self) -> None:
        rename_dialog = getattr(self, "adapter_rename_dialog", None)
        if rename_dialog is not None and not rename_dialog.can_close():
            return
        pretest = getattr(self, "test_item_pretest_controls", None)
        if pretest is not None and not pretest.can_close():
            return
        session = getattr(self, "power_test_resume_session", None)
        if session is not None:
            session.stop()
        dut_cancel_event = getattr(self, "dut_config_cancel_event", None)
        if dut_cancel_event is not None:
            dut_cancel_event.set()
        updates = getattr(self, "app_update_dialog", None)
        if updates is not None and not updates.prepare_app_close(self._on_app_close):
            return
        if updates is not None and updates.jobs:
            # 更新线程已退出；销毁日志控件前落盘本次收尾日志，按当前队列快照限量排空。
            pending_logs = self.log_queue.qsize()
            for _ in range((pending_logs + MAIN_LOG_EVENTS_PER_TICK - 1) // MAIN_LOG_EVENTS_PER_TICK):
                self._drain_log_queue()
        try:
            if self.onu_save_after_id is not None:
                try:
                    self.after_cancel(self.onu_save_after_id)
                except Exception:
                    pass
                self.onu_save_after_id = None
            self._save_onu_registration_config()
            if self.sample_upgrade_save_after_id is not None:
                try:
                    self.after_cancel(self.sample_upgrade_save_after_id)
                except Exception:
                    pass
                self.sample_upgrade_save_after_id = None
            self._save_sample_upgrade_settings()
        except Exception:
            pass
        finally:
            manager = getattr(self, "serial_session_manager", None)
            if manager is not None:
                manager.shutdown_all()
            self.destroy()

    def _cancel_pending_onu_registration_save(self) -> None:
        if self.onu_save_after_id is not None:
            try:
                self.after_cancel(self.onu_save_after_id)
            except Exception:
                pass
            self.onu_save_after_id = None

    def _cancel_pending_sample_upgrade_save(self) -> None:
        if self.sample_upgrade_save_after_id is not None:
            try:
                self.after_cancel(self.sample_upgrade_save_after_id)
            except Exception:
                pass
            self.sample_upgrade_save_after_id = None

    # -- 全流程异步子任务桥接 ------------------------------------------

    def _drain_pipeline_ui_tasks(self) -> None:
        """在 Tk 主线程执行全流程子任务提交动作（确认框 / 窗口 / 线程启动）。"""
        for _index in range(8):
            try:
                action, completed, outcome = self.pipeline_ui_task_queue.get_nowait()
            except queue.Empty:
                break
            try:
                outcome["result"] = action()
            except Exception as exc:  # noqa: BLE001 - 必须把主线程提交错误回传给编排器
                outcome["error"] = exc
            finally:
                completed.set()
        try:
            self.after(50, self._drain_pipeline_ui_tasks)
        except Exception:
            # 主窗口销毁时不再继续调度。
            return

    def _invoke_pipeline_ui_action(self, action) -> bool:
        """后台编排线程同步提交一个主线程 UI 动作，并取得“是否真正启动”。"""
        completed = threading.Event()
        outcome: dict[str, object] = {}
        self.pipeline_ui_task_queue.put((action, completed, outcome))
        completed.wait()
        error = outcome.get("error")
        if error is not None:
            raise error  # type: ignore[misc]
        return bool(outcome.get("result"))

    def _drain_dut_config_ui_tasks(self) -> None:
        """在 Tk 主线程更新 DUT 表格和批次结束状态。"""
        for _index in range(16):
            try:
                event = self.dut_config_ui_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "item":
                feature = event[1] if len(event) >= 3 else "telnet"
                result = event[2] if len(event) >= 3 else event[1]
                window = self.dut_config_window
                if window is not None and window.exists():
                    window.update_result(result, feature)
            elif kind == "finished":
                feature = event[1] if len(event) >= 3 else "telnet"
                results = event[2] if len(event) >= 3 else event[1]
                if feature == "telnet":
                    self._finish_dut_telnet_enable(results)
                elif feature == "wan_query":
                    self._finish_dut_wan_query(results)
                elif feature in {
                    "telnet_query", "voice_query", "tr069_query",
                    "wifi_2g_query", "wifi_5g_query",
                }:
                    self._finish_dut_current_status_query(
                        feature.removesuffix("_query"), results
                    )
                else:
                    self._finish_dut_advanced_config(feature, results)
        try:
            self.after(50, self._drain_dut_config_ui_tasks)
        except Exception:
            return

    def _begin_pipeline_subtask(self, code: str) -> None:
        self._pipeline_subtask_results.pop(code, None)
        self._pipeline_subtask_events[code] = threading.Event()

    def _finish_pipeline_subtask(self, code: str, ok: bool, detail: str) -> None:
        event = self._pipeline_subtask_events.get(code)
        if event is None:
            return
        self._pipeline_subtask_results[code] = (ok, detail)
        event.set()

    def _wait_pipeline_subtask(self, code: str) -> None:
        event = self._pipeline_subtask_events.get(code)
        if event is None:
            raise RuntimeError(f"全流程子任务 {code} 未建立完成事件")
        event.wait()
        ok, detail = self._pipeline_subtask_results.pop(code, (False, "未收到完成结果"))
        self._pipeline_subtask_events.pop(code, None)
        if not ok:
            run = getattr(self, "_sample_upgrade_run", None)
            if code == "sample_upgrade" and run and run.pipeline_owned and run.control.is_set():
                raise UpgradeStopped(detail)
            raise RuntimeError(detail)

    def _run_pipeline_sample_upgrade(self, skip_confirmation: bool = False) -> None:
        """供后台编排器调用：主线程启动升级，完成后才允许下一子任务。"""
        self._begin_pipeline_subtask("sample_upgrade")
        started = self._invoke_pipeline_ui_action(
            lambda: self._start_pipeline_sample_upgrade_on_ui(skip_confirmation)
        )
        if not started:
            self._finish_pipeline_subtask("sample_upgrade", False, "样机升级未启动：操作员取消或配置未通过")
        self._wait_pipeline_subtask("sample_upgrade")

    def _start_pipeline_sample_upgrade_on_ui(self, skip_confirmation: bool = False) -> bool:
        # 去配置窗口可能已被操作员关闭；管道重新创建/拉起有效窗口，
        # 使确认框不再引用已销毁的 Toplevel。
        # 此标记只由全流程的一次性无人值守授权设置；升级 worker 完成后会
        # 清除。普通“样机升级”窗口仍保留原来的完成/失败提示框。
        self._pipeline_sample_upgrade_completion_dialog_suppressed = skip_confirmation
        self._open_upgrade_module()
        self._capture_current_channel()
        if not self._validate_upgrade_required_fields():
            self._pipeline_sample_upgrade_completion_dialog_suppressed = False
            return False
        transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())
        if self.upgrade_mode_var.get() == "页面升级":
            started = self._start_page_upgrade(skip_confirmation=skip_confirmation)
        elif self.upgrade_mode_var.get() == "全包升级" and transfer_method in SERIAL_FULL_PACKAGE_TRANSFERS:
            started = self._start_full_package_upgrade(skip_confirmation=skip_confirmation)
        else:
            messagebox.showwarning("升级方式不支持", "请在样机升级窗口选择页面升级、Tftp指令或 Tftp Put。", parent=self.upgrade_window)
            started = False
        if not started:
            self._pipeline_sample_upgrade_completion_dialog_suppressed = False
        return started

    def _run_pipeline_sample_parameter_write(self, skip_confirmation: bool = False) -> None:
        """供后台编排器调用：重新打开写参窗口，完成后才允许下一子任务。"""
        self._begin_pipeline_subtask("sample_parameter_write")
        started = self._invoke_pipeline_ui_action(
            lambda: self._start_pipeline_sample_parameter_write_on_ui(skip_confirmation)
        )
        if not started:
            self._finish_pipeline_subtask("sample_parameter_write", False, "写样机参数未启动：操作员取消或预检未通过")
        self._wait_pipeline_subtask("sample_parameter_write")

    def _start_pipeline_sample_parameter_write_on_ui(self, skip_confirmation: bool = False) -> bool:
        # 此标记只由全流程的一次性无人值守授权设置；写参 worker 完成后会
        # 清除。普通“写样机参数”窗口仍保留原来的完成/失败提示框。
        self._pipeline_sample_parameter_completion_dialog_suppressed = skip_confirmation
        self._open_sample_parameter_writer()
        started = self._start_sample_parameter_write(skip_confirmation=skip_confirmation)
        if not started:
            self._pipeline_sample_parameter_completion_dialog_suppressed = False
        return started

    def _run_pipeline_onu_registration(self) -> None:
        """Submit the pre-reviewed ONU batch on Tk, then wait for its final result."""
        self._begin_pipeline_subtask("onu_registration")
        started = self._invoke_pipeline_ui_action(
            self._start_pipeline_onu_registration_on_ui
        )
        if not started:
            self._finish_pipeline_subtask(
                "onu_registration", False, "ONU 注册未启动：请先查询、勾选目标并生成预览"
            )
        self._wait_pipeline_subtask("onu_registration")

    def _start_pipeline_onu_registration_on_ui(self) -> bool:
        """ONU remains explicitly confirmed; pipeline only owns completion waiting."""
        if not self._selected_unregistered_onus() or not self.onu_preview_ready:
            self._open_onu_registration_module()
            messagebox.showwarning(
                "ONU 批量注册未就绪",
                "请先查询未注册 ONU，勾选本批目标并生成命令预览；全流程不会按查询顺序猜测目标。",
                parent=self.onu_registration_window,
            )
            return False
        return bool(self._on_onu_register_selected_clicked())

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.option_add("*Font", f"{{{FONT_FAMILY}}} 10")
        self.option_add("*TCombobox*Listbox.font", f"{{{FONT_FAMILY}}} 10")

        style.configure("App.TFrame", background=COLOR_BG)
        style.configure("Surface.TFrame", background=COLOR_SURFACE)
        style.configure("Header.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=(FONT_FAMILY, 20, "bold"))
        style.configure("Subtitle.TLabel", background=COLOR_BG, foreground=COLOR_MUTED, font=(FONT_FAMILY, 10))
        style.configure("CardTitle.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=(FONT_FAMILY, 12, "bold"))
        style.configure("CardHint.TLabel", background=COLOR_SURFACE, foreground=COLOR_MUTED, font=(FONT_FAMILY, 9))
        style.configure("Surface.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT)
        style.configure("Muted.TLabel", background=COLOR_SURFACE, foreground=COLOR_MUTED)
        style.configure("Success.TLabel", background=COLOR_SUCCESS_BG, foreground=COLOR_SUCCESS, padding=(10, 6), font=(FONT_FAMILY, 9, "bold"))
        style.configure("Danger.TLabel", background=COLOR_DANGER_BG, foreground=COLOR_DANGER, padding=(10, 6), font=(FONT_FAMILY, 9, "bold"))
        power_status_style = {"padding": (14, 8), "font": (FONT_FAMILY, 11, "bold")}
        style.configure("PowerStatusIdle.TLabel", background=COLOR_SECONDARY, foreground=COLOR_MUTED, **power_status_style)
        style.configure("PowerStatusRunning.TLabel", background=COLOR_PRIMARY, foreground="#ffffff", **power_status_style)
        style.configure("PowerStatusStopping.TLabel", background=COLOR_WARNING_BG, foreground=COLOR_WARNING, **power_status_style)
        style.configure("PowerStatusCompleted.TLabel", background=COLOR_SUCCESS_BG, foreground=COLOR_SUCCESS, **power_status_style)
        style.configure("PowerStatusStopped.TLabel", background=COLOR_SECONDARY, foreground=COLOR_TEXT, **power_status_style)
        style.configure("PowerStatusFailed.TLabel", background=COLOR_DANGER_BG, foreground=COLOR_DANGER, **power_status_style)
        power_channel_style = {"padding": (8, 5), "font": (FONT_FAMILY, 9, "bold")}
        style.configure("PowerChannelRunning.TLabel", background=COLOR_PRIMARY_SOFT, foreground=COLOR_PRIMARY_DARK, **power_channel_style)
        style.configure("PowerChannelWaiting.TLabel", background=COLOR_SECONDARY, foreground=COLOR_MUTED, **power_channel_style)
        style.configure("PowerChannelRetry.TLabel", background=COLOR_WARNING_BG, foreground=COLOR_WARNING, **power_channel_style)
        style.configure("PowerChannelFailed.TLabel", background=COLOR_DANGER_BG, foreground=COLOR_DANGER, **power_channel_style)
        style.configure("PowerChannelCompleted.TLabel", background=COLOR_SUCCESS_BG, foreground=COLOR_SUCCESS, **power_channel_style)
        style.configure(
            "OverviewToggle.TButton",
            background=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            borderwidth=0,
            padding=(0, 2),
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("OverviewToggle.TButton", foreground=[("active", COLOR_PRIMARY_DARK)])
        style.configure("TButton", padding=(12, 7), font=(FONT_FAMILY, 9))
        style.configure("Primary.TButton", background=COLOR_PRIMARY, foreground="#ffffff", padding=(16, 9), font=(FONT_FAMILY, 10, "bold"))
        style.map("Primary.TButton", background=[("active", COLOR_PRIMARY_DARK), ("pressed", COLOR_PRIMARY_DARK)])
        style.configure("Secondary.TButton", background=COLOR_SECONDARY, foreground=COLOR_TEXT)
        style.map("Secondary.TButton", background=[("active", COLOR_SECONDARY_HOVER)])
        style.configure("Danger.TButton", background=COLOR_DANGER, foreground="#ffffff", padding=(16, 9), font=(FONT_FAMILY, 10, "bold"))
        style.map("Danger.TButton", background=[("active", COLOR_DANGER_DARK), ("pressed", COLOR_DANGER_DARK)])
        style.configure("Tool.TButton", background=COLOR_SURFACE, foreground=COLOR_TEXT, padding=(12, 8))
        style.map("Tool.TButton", background=[("active", COLOR_PRIMARY_SOFT)], foreground=[("active", COLOR_PRIMARY_DARK)])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=COLOR_BORDER, padding=6)
        style.configure("TCombobox", fieldbackground="#ffffff", background="#ffffff", bordercolor=COLOR_BORDER, padding=5)
        style.configure("Horizontal.TProgressbar", background=COLOR_PRIMARY, troughcolor=COLOR_SECONDARY, bordercolor=COLOR_SECONDARY)
        style.configure("TLabelframe", background=COLOR_SURFACE, bordercolor=COLOR_BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10, "bold"))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=(20, 16, 20, 18))
        root.pack(fill="both", expand=True)

        admin_ok = is_admin()
        admin_text = "管理员权限已就绪" if admin_ok else "缺少管理员权限，请右键以管理员身份运行"

        toolbar = ttk.Frame(root, style="Surface.TFrame", padding=(12, 10))
        toolbar.pack(fill="x", pady=(0, 14))
        toolbar_commands = ttk.Frame(toolbar, style="Surface.TFrame")
        toolbar_actions = ttk.Frame(toolbar, style="Surface.TFrame")
        self.project_name_badge = ProjectNameBadge(
            toolbar_actions, font_family=FONT_FAMILY,
            background=COLOR_PRIMARY_SOFT, foreground=COLOR_PRIMARY_DARK,
        )
        self.project_name_badge.pack(side="left", padx=(0, 16))
        ttk.Label(toolbar_commands, text="常用工具", style="CardTitle.TLabel").pack(side="left", padx=(2, 16))
        ttk.Button(toolbar_commands, text="自动上/下电", command=self._launch_power_on, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar_commands, text="样机升级", command=self._open_upgrade_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar_commands, text="写样机参数", command=self._open_sample_parameter_writer, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar_commands, text="ONU注册", command=self._open_onu_registration_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar_commands, text="串口日志", command=self._open_serial_log_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar_commands, text="DUT配置", command=self._open_dut_config_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        self.app_update_dialog = AppUpdateDialog(self, RELEASE_VERSION, log=self.log_queue.put)
        self.check_updates_button = ttk.Button(
            toolbar_actions, text="检查更新", command=self.app_update_dialog.open, style="Secondary.TButton",
        )
        self.check_updates_button.pack(side="right")
        self.app_update_dialog.bind_button(self.check_updates_button)
        ttk.Button(toolbar_actions, text="刷新网卡", command=self._refresh_adapters, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(toolbar_actions, text="刷新串口", command=self._refresh_power_serial_ports, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Label(
            toolbar_actions,
            text=admin_text,
            style="Success.TLabel" if admin_ok else "Danger.TLabel",
        ).pack(side="right", padx=(0, 16))
        arrange_update_toolbar(toolbar, toolbar_commands, toolbar_actions)

        body = ttk.Frame(root, style="App.TFrame")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, style="Surface.TFrame", padding=14)
        left.pack(side="left", fill="y", padx=(0, 14))
        ttk.Label(left, text="1  选择测试通道", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(left, text="点击方框或双击可切换启用状态", style="CardHint.TLabel").pack(anchor="w", pady=(3, 10))
        self.channel_list = Listbox(
            left,
            width=34,
            height=16,
            exportselection=False,
            font=CHANNEL_LIST_FONT,
            background=COLOR_SURFACE_SUBTLE,
            foreground=COLOR_TEXT,
            selectbackground=COLOR_PRIMARY_SOFT,
            selectforeground=COLOR_PRIMARY_DARK,
            activestyle="none",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
        )
        self.channel_list.pack(fill="both", expand=True, pady=(0, 10))
        self.channel_list.bind("<<ListboxSelect>>", self._on_channel_selected)
        self.channel_list.bind("<Button-1>", self._on_channel_list_press)
        self.channel_list.bind("<ButtonRelease-1>", self._on_channel_list_click)
        self.channel_list.bind("<Button-3>", self._on_channel_list_context_menu)
        self.channel_list.bind("<space>", self._toggle_selected_channel_enabled)
        self.channel_list.bind("<Double-Button-1>", self._on_channel_list_double_click)
        self.channel_context_menu = Menu(self, tearoff=0)
        self.channel_context_menu.add_command(
            label="打开本次开关机运行日志",
            command=self._open_selected_power_test_log,
        )
        for channel in self.channels:
            self.channel_list.insert(END, self._channel_list_label(channel))
        if self.current_index >= 0:
            self.channel_list.selection_set(self.current_index)

        selection_actions = ttk.Frame(left, style="Surface.TFrame")
        selection_actions.pack(fill="x")
        ttk.Button(selection_actions, text="全选", command=lambda: self._set_all_channels_enabled(True), style="Secondary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(selection_actions, text="清除", command=lambda: self._set_all_channels_enabled(False), style="Secondary.TButton").pack(side="left", fill="x", expand=True, padx=(8, 0))

        right = ttk.Frame(body, style="App.TFrame")
        right.pack(side="left", fill="both", expand=True)

        config_card = ttk.Frame(right, style="Surface.TFrame", padding=14)
        config_card.pack(fill="x", pady=(0, 12))
        config_header = ttk.Frame(config_card, style="Surface.TFrame")
        config_header.pack(fill="x")
        ttk.Label(config_header, text="2  配置测试参数", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(config_header, text="测试项配置", command=self._open_test_item_config, style="Tool.TButton").pack(side="right")
        ttk.Label(config_card, text="通道勾选、VLAN和COM口选择会实时保存", style="CardHint.TLabel").pack(anchor="w", pady=(3, 10))

        self.enabled_var = BooleanVar(value=True)
        self.vlan_var = StringVar()
        self.adapter_var = StringVar()
        self.pc_ip_var = StringVar()
        self.device_ip_var = StringVar(value=self._shared_device_manage_ip())
        self.mask_var = StringVar(value=DEFAULT_SUBNET_MASK)
        self.channel_row_vars = {}

        power_form = ttk.Frame(config_card, style="Surface.TFrame")
        power_form.pack(fill="x", pady=(0, 10))
        self.power_serial_var = StringVar(value=self.power_serial_port)
        ttk.Label(power_form, text="程控电源串口", style="Surface.TLabel").grid(row=0, column=0, sticky="w")
        self.power_serial_combo = ttk.Combobox(
            power_form,
            textvariable=self.power_serial_var,
            values=self.power_serial_options,
            width=28,
            state="readonly",
        )
        self.power_serial_combo.grid(row=0, column=1, sticky="w", padx=(12, 24))
        self.power_serial_combo.bind("<<ComboboxSelected>>", self._on_power_serial_changed)
        self.power_serial_combo.bind("<FocusOut>", self._on_power_serial_changed)
        ttk.Label(power_form, text="样机管理 IP", style="Surface.TLabel").grid(row=0, column=2, sticky="w")
        device_ip_entry = ttk.Entry(power_form, textvariable=self.device_ip_var, width=22)
        device_ip_entry.grid(row=0, column=3, sticky="w", padx=(12, 0))
        device_ip_entry.bind("<FocusOut>", self._on_device_ip_changed)
        device_ip_entry.bind("<Return>", self._on_device_ip_changed)
        power_form.columnconfigure(4, weight=1)

        form = ttk.Frame(config_card, style="Surface.TFrame")
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.channel_table = Frame(form, background=COLOR_SURFACE)
        self.channel_table.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._rebuild_channel_config_rows()

        run_card = ttk.Frame(right, style="Surface.TFrame", padding=(14, 12))
        run_card.pack(fill="x", pady=(0, 12))
        run_copy = ttk.Frame(run_card, style="Surface.TFrame")
        run_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(run_copy, text="3  环境检查与开关机测试", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            run_copy,
            text="检查全部启用通道。环境检查通过后，系统将自动开始执行开关机测试。",
            style="CardHint.TLabel",
        ).pack(anchor="w", pady=(3, 4))
        power_test_status_row = ttk.Frame(run_copy, style="Surface.TFrame")
        power_test_status_row.pack(fill="x", pady=(3, 8))
        self.power_test_status_label = ttk.Label(
            power_test_status_row,
            textvariable=self.power_test_status_var,
            style="PowerStatusIdle.TLabel",
        )
        self.power_test_status_label.pack(side="left")
        ttk.Label(
            power_test_status_row,
            textvariable=self.power_test_progress_text_var,
            style="CardHint.TLabel",
        ).pack(side="right", padx=(12, 0))
        self.progress = ttk.Progressbar(run_copy, mode="determinate", maximum=1, value=0)
        self.progress.pack(fill="x")
        self.power_test_channel_overview = ttk.Frame(run_copy, style="Surface.TFrame")
        self.power_test_channel_overview_toggle = ttk.Button(
            self.power_test_channel_overview,
            text="通道概览（收起）",
            command=self._toggle_power_test_channel_overview,
            style="OverviewToggle.TButton",
        )
        self.power_test_channel_overview_toggle.pack(anchor="w", pady=(8, 2))
        ttk.Label(
            self.power_test_channel_overview,
            textvariable=self.power_test_channel_summary_var,
            style="Surface.TLabel",
        ).pack(anchor="w", pady=(0, 2))
        self.power_test_channel_attention_label = ttk.Label(
            self.power_test_channel_overview,
            textvariable=self.power_test_channel_attention_var,
            style="CardHint.TLabel",
        )
        self.power_test_channel_attention_label.pack(anchor="w", pady=(0, 4))
        self.power_test_channel_grid = ttk.Frame(
            self.power_test_channel_overview,
            style="Surface.TFrame",
        )
        self.power_test_channel_grid.pack(fill="x")
        self.power_test_channel_detail_label = ttk.Label(
            self.power_test_channel_overview,
            textvariable=self.power_test_channel_detail_var,
            style="CardHint.TLabel",
        )
        self.power_test_channel_detail_label.pack(anchor="w", pady=(4, 0))
        run_actions = ttk.Frame(run_card, style="Surface.TFrame")
        run_actions.pack(side="right", padx=(20, 0))
        ttk.Button(
            run_actions,
            text="检查并执行测试",
            command=self._start_all_checks,
            style="Primary.TButton",
        ).pack(side="right")
        self.stop_power_test_button = ttk.Button(
            run_actions,
            text="停止测试",
            command=self._stop_power_test,
            style="Secondary.TButton",
            state="disabled",
        )
        self.stop_power_test_button.pack(side="right", padx=(0, 8))

        log_card = ttk.Frame(right, style="Surface.TFrame", padding=14)
        log_card.pack(fill="both", expand=True)
        log_header = ttk.Frame(log_card, style="Surface.TFrame")
        log_header.pack(fill="x")
        ttk.Label(log_header, text="执行日志", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(log_header, text="清空日志", command=self._clear_log, style="Secondary.TButton").pack(side="right")
        self.log_text = Text(
            log_card,
            height=18,
            wrap="word",
            font=("Consolas", 10),
            background=COLOR_LOG_BG,
            foreground=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=10,
            pady=8,
        )
        self.log_text.pack(fill="both", expand=True)
        self._configure_log_tags()
        self._log_section("操作步骤")
        self._log("1. 人工接好所有样机线路")
        self._log("2. 选择本次测试使用的程控电源串口，并确认通道对应的 VLAN 和 COM口")
        self._log("3. 点击“直接控制程控电源上电”")
        self._log("4. 主程序通过程控电源串口按选中通道执行断电、上电")
        self._log("5. 回到本软件检查线路")
        self._log_blank()
        self._log_section("运行信息")
        self._log(f"本次日志文件：{self.log_path}")
        if not self.channels:
            self._log("未读取到任何 channel 配置，请检查配置文件。")
        if not self.adapters:
            self._log("未识别到网卡，请确认 ipconfig 可正常运行。")

    def _add_field(self, parent: Frame, label: str, row: int, variable: StringVar, combo_values=None) -> None:
        Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        if combo_values is not None:
            widget = ttk.Combobox(parent, textvariable=variable, values=combo_values, width=CHANNEL_FIELD_WIDTH)
        else:
            widget = ttk.Entry(parent, textvariable=variable, width=CHANNEL_FIELD_WIDTH)
        widget.grid(row=row, column=1, sticky="w", pady=5, padx=(8, 0))
        if label == "通道对应 VLAN":
            self.vlan_combo = widget
            widget.bind("<<ComboboxSelected>>", self._on_vlan_changed)
            widget.bind("<FocusOut>", self._on_vlan_changed)

    def _open_network_config(self) -> None:
        """「全流程执行」窗口中「环境线路检查」行的「去配置」按钮入口(2026-07-20 新增)。

        网络配置目前内嵌在主界面顶部 VLAN / IP 区,没有独立子窗口。
        这里:隐藏全流程执行窗口 + 把主界面拉到前台 + emit 一行提示,
        操作员在主界面顶部左侧「网络配置」卡片编辑 VLAN / 网卡 / PC IP / 样机 IP,
        完成后再次点击「检查并执行测试」即可重开全流程执行窗口(原窗口已隐藏)。

        注意:``self.pipeline_window`` 是 ``PipelineWindow`` 包装器(持有 ``self.window`` 这个 Toplevel),
        ``winfo_exists()`` / ``withdraw()`` 必须走 ``.window``,不能直接调包装器。
        """
        pipeline_window = self.pipeline_window
        if pipeline_window is not None and pipeline_window.window.winfo_exists():
            pipeline_window.window.withdraw()
        self.deiconify()
        self.lift()
        self.focus_force()
        self._log(
            "请在主界面顶部「网络配置」卡片编辑 VLAN / 网卡 / PC 静态 IP / 样机管理 IP;"
            "完成后再次点击「检查并执行测试」重开全流程执行窗口。"
        )

    def _restore_module_window_size(self, window, module_key: str) -> tuple[int, int]:
        """恢复功能模块窗口宽高；首次打开保持既有默认值。"""
        default_width, default_height, min_width, min_height = MODULE_WINDOW_SIZE_SPECS[module_key]
        width, height = load_module_window_size(
            self._module_window_size_state_path,
            module_key,
            default_width=default_width,
            default_height=default_height,
            min_width=min_width,
            min_height=min_height,
            screen_width=window.winfo_screenwidth(),
            screen_height=window.winfo_screenheight(),
        )
        window.geometry(f"{width}x{height}")
        return width, height

    def _remember_module_window_size(self, window, module_key: str) -> bool:
        """在窗口确认关闭后记录当前宽高；失败不阻止正常关闭。"""
        default_width, default_height, min_width, min_height = MODULE_WINDOW_SIZE_SPECS[module_key]
        try:
            window.update_idletasks()
            width = window.winfo_width()
            height = window.winfo_height()
        except (AttributeError, TclError):
            return False
        return save_module_window_size(
            self._module_window_size_state_path,
            module_key,
            width,
            height,
            default_width=default_width,
            default_height=default_height,
            min_width=min_width,
            min_height=min_height,
        )

    def _open_sample_parameter_writer(self) -> None:
        if self.parameter_writer_window is not None and self.parameter_writer_window.winfo_exists():
            self.parameter_writer_window.deiconify()
            self.parameter_writer_window.lift()
            self.parameter_writer_window.focus_force()
            self._refresh_parameter_preflight()
            return

        dialog = Toplevel(self)
        self.parameter_writer_window = dialog
        dialog.title("写样机参数")
        window_width, window_height = self._restore_module_window_size(
            dialog, "sample_parameter_writer"
        )
        dialog.minsize(860, 590)

        # 参数表路径是全流程子任务 4 的必填项，必须直接复用实例级持久变量；
        # 不能每次开写参窗口再新建临时 StringVar，否则选表后全流程仍会读到空路径。
        self.parameter_table_var = self.parameter_table_path_var
        # 写样机参数窗口的「首次登录账号 / 密码」直接复用主程序实例级 StringVar,
        # 由 ``__init__`` 阶段从 sample_upgrade_settings.ini 加载,值变更经 trace_add 自动写盘。
        # 写样机参数默认并行 1(2026-07-19 用户要求):多台并发容易撞 UBUS HTTP / telnet login / NIC,
        # 默认串行更稳;Spinbox 仍允许 1–8 现场上调。该实例级变量会恢复上次保存值,
        # 升级窗口的 parallel_count 仍走 DEFAULT_PARALLEL_COUNT=2。
        self.parameter_status_var = StringVar(value="请选择或生成参数表。")

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill="both", expand=True)
        source_row = ttk.Frame(container)
        source_row.pack(fill="x", pady=(0, 8))
        ttk.Label(source_row, text="参数表：").pack(side="left")
        ttk.Entry(source_row, textvariable=self.parameter_table_var, width=70, state="readonly").pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Button(source_row, text="选择参数表...", command=self._browse_parameter_table, style="Secondary.TButton").pack(side="left")
        ttk.Button(source_row, text="生成批量参数表...", command=self._open_parameter_generator, style="Tool.TButton").pack(side="left", padx=(8, 0))

        credential_row = ttk.Frame(container)
        credential_row.pack(fill="x", pady=(0, 8))
        ttk.Label(credential_row, text="首次登录账号：").pack(side="left")
        ttk.Entry(credential_row, textvariable=self.parameter_initial_username_var, width=20).pack(side="left", padx=(6, 14))
        ttk.Label(credential_row, text="密码：").pack(side="left")
        ttk.Entry(credential_row, textvariable=self.parameter_initial_password_var, width=24).pack(side="left", padx=(6, 14))
        ttk.Label(credential_row, text="并行数：").pack(side="left")
        parallel_spinbox = ttk.Spinbox(credential_row, from_=1, to=PARAMETER_MAX_PARALLEL, textvariable=self.parameter_parallel_count_var, width=5)
        parallel_spinbox.pack(side="left", padx=(6, 0))
        ttk.Label(credential_row, text=f"（1–{PARAMETER_MAX_PARALLEL} 台，默认 {DEFAULT_PARAMETER_PARALLEL_COUNT}）", style="CardHint.TLabel").pack(side="left", padx=(6, 0))

        # 写样机参数流水线两个可选行为(2026-07-19):勾选后才下发,默认关闭。
        option_row = ttk.Frame(container)
        option_row.pack(fill="x", pady=(0, 8))
        # ttk 的 clam 主题会把选中态绘制为叉号；这里使用 Windows 原生 Checkbutton，
        # 让两个危险可选项在选中时明确显示标准勾选标记。
        Checkbutton(
            option_row,
            text="清空参数",
            variable=self.parameter_clear_parameters_var,
            selectcolor="#ffffff",
            background=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
        ).pack(side="left")
        Checkbutton(
            option_row,
            text="退出老化",
            variable=self.parameter_exit_aging_var,
            selectcolor="#ffffff",
            background=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
        ).pack(side="left", padx=(16, 0))
        ttk.Label(option_row, text="（勾选后,工厂模式二次登录成功时下发对应命令；不勾选则下发跳过日志）", style="CardHint.TLabel").pack(side="left", padx=(12, 0))

        ttk.Label(container, text="本次目标与预检结果", style="CardTitle.TLabel").pack(anchor="w", pady=(4, 4))
        self.parameter_preview_text = Text(container, height=17, wrap="word", state="disabled", background=COLOR_LOG_BG)
        self.parameter_preview_text.pack(fill="both", expand=True)
        ttk.Label(container, textvariable=self.parameter_status_var, style="CardHint.TLabel").pack(anchor="w", pady=(7, 6))

        actions = ttk.Frame(container)
        actions.pack(fill="x")
        ttk.Button(actions, text="重新预检", command=self._refresh_parameter_preflight, style="Secondary.TButton").pack(side="left")
        self.parameter_write_button = ttk.Button(actions, text="写入参数", command=self._start_sample_parameter_write, style="Primary.TButton")
        self.parameter_write_button.pack(side="right")
        self.parameter_cancel_button = ttk.Button(actions, text="停止批次", command=self._cancel_sample_parameter_write, state="disabled", style="Secondary.TButton")
        self.parameter_cancel_button.pack(side="right", padx=(0, 8))

        def close_dialog() -> None:
            if self.parameter_write_running:
                messagebox.showwarning("写参进行中", "请先停止写参批次并等待串口清理完成。", parent=dialog)
                return
            self._remember_module_window_size(dialog, "sample_parameter_writer")
            self._save_sample_upgrade_settings()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        center_toplevel_on_parent(
            dialog, self, window_width=window_width, window_height=window_height
        )
        # 程序重开后内存记录为空，但路径已由 sample_upgrade_settings.ini 恢复；
        # 自动重新加载，使窗口预检和全流程状态都基于同一份已选参数表。
        saved_table_path = self.parameter_table_path_var.get().strip()
        if saved_table_path and self.parameter_loaded_table_path != saved_table_path:
            self._load_parameter_table(Path(saved_table_path), report_error=False)
        else:
            self._refresh_parameter_preflight()

    def _parameter_channel_ports(self, *, capture_current: bool = True) -> list[tuple[str, str]]:
        if capture_current:
            self._capture_current_channel()
        items: list[tuple[str, str]] = []
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if not vlan:
                items.append(("", ""))
                continue
            items.append((vlan, LineCheckAssistant._serial_port_for_channel(channel)))
        return items

    def _channel_for_vlan(self, vlan_name: str) -> ChannelConfig | None:
        target = adapter_alias_from_display(vlan_name).strip().casefold()
        if not target:
            return None
        for channel in self.channels:
            if not channel.enabled:
                continue
            alias = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip().casefold()
            if alias == target:
                return channel
        return None

    def _bind_ip_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        return channel.network_card_ip.strip() if channel is not None and channel.network_card_ip else ""

    def _device_host_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        if channel is not None and channel.device_manage_ip:
            return channel.device_manage_ip.strip()
        shared = self.device_ip_var.get().strip() if hasattr(self, "device_ip_var") else ""
        return shared

    def _factory_bind_ip_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        if channel is not None and channel.factory_bind_ip and channel.factory_bind_ip.strip():
            return channel.factory_bind_ip.strip()
        # 未配置时按用户模式 network_card_ip 自动派生:第 3 段 → 29,主机位不变
        if channel is not None and channel.network_card_ip:
            return factory_bind_ip_for(channel.network_card_ip)
        return ""

    def _factory_device_host_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        if channel is not None and channel.factory_device_host and channel.factory_device_host.strip():
            return channel.factory_device_host.strip()
        # 未配置时按用户模式 device_manage_ip 自动派生:第 3 段 → 29,主机位不变
        if channel is not None and channel.device_manage_ip:
            return factory_device_host_for(channel.device_manage_ip)
        return ""

    def _adapter_alias_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        return channel.adapter_alias.strip() if channel is not None and channel.adapter_alias else ""

    def _subnet_mask_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        return (channel.subnet_mask or "").strip() if channel is not None else ""

    def _browse_parameter_table(self) -> None:
        path = filedialog.askopenfilename(
            title="选择批量样机参数表",
            filetypes=[
                ("参数表", "*.xlsx *.xlsm *.xls *.csv"),
                ("Excel", "*.xlsx *.xlsm *.xls"),
                ("CSV", "*.csv"),
            ],
            parent=self.parameter_writer_window,
        )
        if path:
            self._load_parameter_table(Path(path))

    def _load_parameter_table(self, path: Path, *, report_error: bool = True) -> bool:
        try:
            self.parameter_records = load_parameter_records(path)
        except Exception as exc:
            self.parameter_loaded_table_path = ""
            if report_error:
                messagebox.showerror("读取参数表失败", str(exc), parent=self.parameter_writer_window)
            else:
                self._log(f"写样机参数：未能恢复已保存参数表 {path}：{exc}")
            self._refresh_parameter_preflight()
            return False
        saved_path = str(path)
        # 选表后立即同步全流程读取的路径变量；其 trace 会将值写入
        # sample_upgrade_settings.ini，关闭/重开窗口也不会丢失。
        self.parameter_table_path_var.set(saved_path)
        self.parameter_loaded_table_path = saved_path
        self._log(f"写样机参数：已加载参数表 {path}，共 {len(self.parameter_records)} 条记录。")
        self._refresh_parameter_preflight()
        return True

    def _refresh_parameter_preflight(self, *, capture_current: bool = True) -> None:
        if self.parameter_writer_window is None or not self.parameter_writer_window.winfo_exists():
            return
        channel_ports = self._parameter_channel_ports() if capture_current else self._parameter_channel_ports(capture_current=False)
        if not self.parameter_records:
            targets = [f"- {vlan or '未配置 VLAN'} / {port or '未映射串口'}" for vlan, port in channel_ports]
            self._render_parameter_preview(["尚未加载参数表。", "当前已勾选通道：", *(targets or ["- 无"])] )
            self.parameter_status_var.set("请先选择参数表，或使用“生成批量参数表”。")
            self.parameter_preflight = None
            return
        self.parameter_preflight = preflight_parameter_targets(self.parameter_records, channel_ports)
        lines = ["目标 VLAN / COM / MAC："]
        for target in self.parameter_preflight.targets:
            lines.append(f"- {target.vlan} / {target.serial_port} / {target.record.values.get('MAC', '')}")
        if self.parameter_preflight.errors:
            lines.extend(("", "预检错误：", *(f"- {item}" for item in self.parameter_preflight.errors)))
        if self.parameter_preflight.warnings:
            lines.extend(("", "预检提示：", *(f"- {item}" for item in self.parameter_preflight.warnings)))
        self._render_parameter_preview(lines)
        self.parameter_status_var.set(
            f"预检通过：{len(self.parameter_preflight.targets)} 台可写入。"
            if self.parameter_preflight.ok
            else f"预检未通过：{len(self.parameter_preflight.errors)} 项错误。"
        )

    def _render_parameter_preview(self, lines: list[str]) -> None:
        self.parameter_preview_text.configure(state="normal")
        self.parameter_preview_text.delete("1.0", END)
        self.parameter_preview_text.insert(END, "\n".join(lines))
        self.parameter_preview_text.configure(state="disabled")

    def _start_sample_parameter_write(self, skip_confirmation: bool = False) -> bool:
        if self.parameter_write_running:
            return False
        self._refresh_parameter_preflight()
        preflight = self.parameter_preflight
        if preflight is None or not preflight.ok:
            messagebox.showwarning("参数表未通过预检", "请先处理预检错误后再写入参数。", parent=self.parameter_writer_window)
            return False
        username = self.parameter_initial_username_var.get().strip()
        password = self.parameter_initial_password_var.get()
        if not username or not password:
            messagebox.showwarning("登录信息不完整", "请填写首次登录账号和密码。", parent=self.parameter_writer_window)
            return False
        try:
            parallel_count = max(1, min(int(self.parameter_parallel_count_var.get()), PARAMETER_MAX_PARALLEL))
        except (TypeError, ValueError):
            parallel_count = DEFAULT_PARAMETER_PARALLEL_COUNT
        target_text = "\n".join(f"- {target.vlan} / {target.serial_port} / MAC:{target.record.values.get('MAC', '')}" for target in preflight.targets)
        # 配置冲突预检(2026-07-18):bind_ip 与 device_host 相同 → PC 把自己作为目标连接,
        # TCP 必然 timed out(典型表现 VLAN110/111 报「Telnet 连接失败 192.168.1.110:23 源 IP 192.168.1.110:timed out」)。
        # `vlan{N} -> 192.168.1.{N}` 约定只适用于 PC 静态 IP(network_card_ip),
        # 样机管理 IP 是设备自身 IP,跟 VLAN 编号无关,典型值 192.168.1.1。
        for target in preflight.targets:
            bind_ip = self._bind_ip_for_vlan(target.vlan)
            device_host = self._device_host_for_vlan(target.vlan)
            if not bind_ip or not device_host:
                continue
            if bind_ip == device_host:
                messagebox.showerror(
                    "样机 IP 配置冲突",
                    f"通道 {target.vlan} 的 PC 静态 IP({bind_ip})与样机管理 IP({device_host})相同,"
                    "PC 无法把自己作为目标连接,写参必然超时失败。\n\n"
                    "样机管理 IP 应为设备自身的管理 IP（典型 192.168.1.1）,不是按 VLAN 编号派生的 PC 静态 IP。\n"
                    "请在主界面表格中修改该通道的「样机管理 IP」字段,"
                    "或在 Auto_power_on_off_tool/config/network_card_ip.ini 中"
                    f"将该通道的 device_manage_ip 改为样机实际管理 IP（典型 192.168.1.1）后重试。",
                    parent=self.parameter_writer_window,
                )
                return False
        # 验证走 telnet 路径的目标必须有 factory_bind_ip / factory_device_host:
        # 工厂模式 reboot 后,样机管理 IP 切到另一网段(如 192.168.29.1),PC 端 VLAN 网卡也
        # 必须切到该网段才能继续工厂模式二次登录。
        # 两个字段若未手动填写,会按"第 3 段 → 29,主机位不变"从用户模式
        # network_card_ip / device_manage_ip 自动派生;派生失败(用户模式字段也未填)
        # 才拒绝本次写入。
        for target in preflight.targets:
            if not self._bind_ip_for_vlan(target.vlan) or not self._device_host_for_vlan(target.vlan):
                continue
            missing = []
            factory_bind = self._factory_bind_ip_for_vlan(target.vlan)
            factory_device = self._factory_device_host_for_vlan(target.vlan)
            if not factory_bind:
                missing.append("factory_bind_ip (需补齐 network_card_ip 或手动填写)")
            if not factory_device:
                missing.append("factory_device_host (需补齐 device_manage_ip 或手动填写)")
            if missing:
                messagebox.showerror(
                    "缺少工厂模式配置",
                    f"通道 {target.vlan} 走 telnet 路径,但自动派生工厂模式配置失败:{', '.join(missing)}。\n"
                    "工厂模式重启后样机管理 IP 会切换到 29 网段(如 192.168.29.1),PC 端 VLAN 网卡也需切换。\n"
                    "请在主界面表格中补齐 network_card_ip / device_manage_ip 或手动填写 factory_bind_ip / factory_device_host 后重试。",
                    parent=self.parameter_writer_window,
                )
                return False
        # 写样机参数可选行为(2026-07-19):确认框描述按 9 步自然顺序生成,
        # 严格匹配 sample_parameter_service.run_parameter_write_pipeline 实际下发顺序,
        # 避免描述与现场实际下发的命令列表不符。勾选的可选项打勾并显示命令,
        # 未勾选的可选项明确标注"[跳过]"便于操作员一眼分辨。
        clear_enabled = bool(self.parameter_clear_parameters_var.get())
        aging_enabled = bool(self.parameter_exit_aging_var.get())
        action_lines = [
            "1. 进入工厂模式（ppctl set FACTORY_MODE=1）",
            "2. firstboot -yr",
            "3. 等待 100 秒",
            "4. 工厂模式二次登录（root / 工厂密码）",
        ]
        if aging_enabled:
            action_lines.append("5. 下发退出老化命令（ppctl set AGING_STATE=1）")
        else:
            action_lines.append("5. [跳过] 退出老化命令")
        if clear_enabled:
            action_lines.append("6. 下发 ppctl clear")
        else:
            action_lines.append("6. [跳过] ppctl clear")
        action_lines.extend([
            "7. 写入并读回校验全部 15 项参数",
            "8. 退出工厂模式（ppctl set FACTORY_MODE=0）",
            "9. firstboot -yr",
        ])
        action_summary = "\n".join(action_lines)
        if not skip_confirmation:
            if not messagebox.askyesno(
                "确认批量写样机参数",
                f"将并行写入 {len(preflight.targets)} 台样机（最多 {parallel_count} 台）：\n{target_text}\n\n"
                f"每台会依次：\n{action_summary}\n\n是否继续？",
                parent=self.parameter_writer_window,
            ):
                return False
        else:
            self._log("[全流程][无人值守] 已使用总确认授权，跳过写样机参数子任务确认。")
        requests = [
            SampleParameterWriteRequest(
                vlan=target.vlan,
                serial_port=target.serial_port,
                initial_username=username,
                initial_password=password,
                values=target.record.values,
                bind_ip=self._bind_ip_for_vlan(target.vlan),
                device_host=self._device_host_for_vlan(target.vlan),
                ubus_port=80,
                factory_bind_ip=self._factory_bind_ip_for_vlan(target.vlan),
                factory_device_host=self._factory_device_host_for_vlan(target.vlan),
                clear_parameters=clear_enabled,
                exit_aging=aging_enabled,
            )
            for target in preflight.targets
        ]
        self.parameter_write_running = True
        self.parameter_cancel_event = threading.Event()
        self.parameter_write_button.configure(state="disabled")
        self.parameter_cancel_button.configure(state="normal")
        self.parameter_status_var.set(f"正在并行写入 {len(requests)} 台样机（最多 {parallel_count} 台）。")
        self.serial_terminal.begin_upgrade_logs([request.vlan for request in requests])
        thread = threading.Thread(
            target=self._sample_parameter_write_worker,
            args=(requests, parallel_count, self.parameter_cancel_event),
            daemon=True,
        )
        thread.start()
        return True

    def _sample_parameter_write_worker(self, requests: list[SampleParameterWriteRequest], parallel_count: int, cancel_event: threading.Event) -> None:
        # 端到端 telnet 写参:UBUS 启用 telnet → TelnetSession(未登录)→ run_parameter_write_pipeline 内部 _login。
        # 工厂模式 100 秒等待后可切换 PC 网卡到工厂模式对应网段后重建 TelnetSession
        # （session_swap），其它情况由串口路径走 transport 回退入口。
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from src.config import DEFAULT_LOG_DIR
        from src.core.bind_socket import wait_for_bindable_ip as _wait_for_bindable_ip
        from src.core.telnet_transport import TelnetSession
        from src.core.ubus_enable_telnet import enable_telnet_via_ubus
        from src.core.ubus_http_client import UbusHttpClient
        from src.models import SampleParameterItemResult
        from src.services.sample_parameter_service import run_single_sample_parameter_write
        from line_check_assistant.network_ops import prepare_network_for_sample

        self.log_queue.put(f"开始批量写样机参数：{len(requests)} 台，并行上限 {parallel_count}。")

        def emit_to_main(line: str) -> None:
            self.log_queue.put(line)

        # UBUS 启用 telnet 失败(典型:HTTP timed out / TCP refused)允许重试 3 次。
        # 与 sample_parameter_service.PARAMETER_WRITE_RETRIES=3 / 串行升级
        # TFTP_COMMAND_MAX_RETRIES=3 的同款约定。
        UBUS_ENABLE_TELNET_MAX_RETRIES = 3
        UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS = 2.0

        telnet_indices = [index for index, req in enumerate(requests) if req.bind_ip and req.device_host]
        serial_indices = [index for index, req in enumerate(requests) if index not in telnet_indices]

        def make_telnet_factory(request):
            def factory(r):
                if not r.bind_ip or not r.device_host:
                    raise RuntimeError(f"{r.vlan} 切 telnet 路径但 bind_ip / device_host 为空")

                # 写参前置:启用对应通道网卡 + 按 channel.network_card_ip 设置静态 IP + 等可绑。
                # 100 秒工厂模式网段切换由 make_factory_session_swap 处理,本步骤只覆盖用户模式初始网段。
                adapter_alias = self._adapter_alias_for_vlan(r.vlan)
                subnet_mask = self._subnet_mask_for_vlan(r.vlan)
                if adapter_alias and r.bind_ip:
                    emit_to_main(
                        f"{r.vlan} 写参前置:准备网络 {adapter_alias}({r.bind_ip} / {subnet_mask or '255.255.255.0'})。"
                    )
                    network_result = prepare_network_for_sample(
                        adapter_alias,
                        r.bind_ip,
                        subnet_mask,
                        on_output=emit_to_main,
                        sleep_fn=time.sleep,
                        reuse_if_ready=True,
                    )
                    if not network_result.ok:
                        emit_to_main(f"{r.vlan} 写参前置:网络准备失败:{network_result.message}")
                        raise RuntimeError(f"{r.vlan} 网络准备失败:{network_result.message}")
                    if not _wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0):
                        emit_to_main(
                            f"{r.vlan} 写参前置:{r.bind_ip} 仍未成为可绑地址,放弃本台。"
                        )
                        raise RuntimeError(f"{r.vlan} 网络准备后 {r.bind_ip} 仍不可绑")

                log_path = DEFAULT_LOG_DIR / f"sample_parameter_{r.vlan}_{r.bind_ip}.log"
                # 端到端 telnet 写参:UBUS 启用 telnet → TelnetSession(未登录)→ run_parameter_write_pipeline 内部 _login。
                # 必须先由 UBUS 打开样机的 telnet 监听（默认防火墙禁用），再同步建立 TCP 连接，否则 192.168.1.1:23 会 timed out。
                # 启用失败(典型:UBUS HTTP 请求失败 ... timed out)允许重试 3 次,
                # 每次重试前 sleep 2 秒,给样机防火墙 reload / telnetd 启动留缓冲。
                emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 中 ({r.device_host})。")
                enable_result = None
                for _attempt in range(1, UBUS_ENABLE_TELNET_MAX_RETRIES + 2):
                    if _attempt > 1:
                        emit_to_main(
                            f"{r.vlan} UBUS 启用 telnet 第 {_attempt - 1}/{UBUS_ENABLE_TELNET_MAX_RETRIES} 次重试,"
                            f"等待 {UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS} 秒..."
                        )
                        time.sleep(UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS)
                    ubus_client = UbusHttpClient(r.bind_ip, r.device_host, ubus_port=r.ubus_port)
                    try:
                        try:
                            enable_result = enable_telnet_via_ubus(
                                ubus_client,
                                r.initial_username,
                                r.initial_password,
                                on_log=lambda ev: emit_to_main(f"{r.vlan} UBUS: {ev.message}"),
                                sleep_fn=lambda _seconds: None,
                                sleep_after_seconds=0.0,
                            )
                        finally:
                            ubus_client.close()
                        break  # 成功,跳出重试循环
                    except Exception as exc:
                        emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 失败：{exc}")
                        if _attempt > UBUS_ENABLE_TELNET_MAX_RETRIES:
                            raise  # 已用完全部 3 次重试
                emit_to_main(f"{r.vlan} UBUS 启用 telnet {enable_result.action}: {enable_result.message}")
                return TelnetSession(
                    r.bind_ip,
                    r.device_host,
                    log_path=log_path,
                    known_secrets=(r.initial_password,),
                )
            return factory

        def make_factory_session_swap(request):
            """工厂模式 100 秒等待后的会话切换回调。

            流程:
              1. 关闭旧 TelnetSession(样机管理 IP 已切到工厂模式网段,旧 socket 已无意义);
              2. 调用 ``prepare_network_for_sample`` 把 PC VLAN 网卡切到
                 ``request.factory_bind_ip / factory_device_host`` 同一网段;
              3. 调用 ``wait_for_bindable_ip`` 等 Windows 把新 IP 注册为可绑定地址;
              4. 创建新 TelnetSession 指向工厂模式管理 IP 后返回。
            失败时 (缺字段 / 切网段失败 / 新建会话失败) 返回 None,pipeline 视作放弃本台。
            """
            if not request.factory_bind_ip or not request.factory_device_host:
                emit_to_main(f"{request.vlan} 工厂模式网段切换：缺少 factory_bind_ip / factory_device_host,放弃本台。")
                return None

            def swap(old_session):
                # 关闭旧会话;失败也继续(本来就可能已断)。
                try:
                    old_session.close()
                except Exception as exc:
                    emit_to_main(f"{request.vlan} 工厂模式网段切换：关闭旧 TelnetSession 异常(忽略):{exc}")

                adapter_alias = self._adapter_alias_for_vlan(request.vlan)
                subnet_mask = self._subnet_mask_for_vlan(request.vlan)
                if not adapter_alias:
                    emit_to_main(f"{request.vlan} 工厂模式网段切换：未找到 VLAN {request.vlan} 的 adapter_alias,放弃本台。")
                    return None
                emit_to_main(
                    f"{request.vlan} 工厂模式网段切换：准备把 {adapter_alias} 设为 {request.factory_bind_ip}（{subnet_mask or '255.255.255.0'}）,"
                    f"样机目标 {request.factory_device_host}。"
                )
                result = prepare_network_for_sample(
                    adapter_alias,
                    request.factory_bind_ip,
                    subnet_mask,
                    on_output=emit_to_main,
                    sleep_fn=time.sleep,
                    reuse_if_ready=True,
                )
                if not result.ok:
                    emit_to_main(f"{request.vlan} 工厂模式网段切换失败：{result.message}")
                    return None
                if not _wait_for_bindable_ip(request.factory_bind_ip, timeout_seconds=15.0):
                    emit_to_main(
                        f"{request.vlan} 工厂模式网段切换：{request.factory_bind_ip} 仍未成为可绑地址,放弃本台。"
                    )
                    return None
                new_log_path = DEFAULT_LOG_DIR / f"sample_parameter_{request.vlan}_{request.factory_bind_ip}.log"
                try:
                    new_session = TelnetSession(
                        request.factory_bind_ip,
                        request.factory_device_host,
                        log_path=new_log_path,
                        known_secrets=(request.initial_password,),
                    )
                except Exception as exc:
                    emit_to_main(f"{request.vlan} 工厂模式重建 TelnetSession 失败：{exc}")
                    return None
                emit_to_main(
                    f"{request.vlan} 工厂模式重建 TelnetSession 成功（{request.factory_bind_ip} → {request.factory_device_host}）。"
                )
                return new_session
            return swap

        results: list[SampleParameterItemResult | None] = [None] * len(requests)

        if serial_indices:
            serial_requests = [requests[i] for i in serial_indices]
            serial_results = run_parallel_sample_parameter_writes(
                serial_requests,
                self.serial_session_manager,
                parallel_count=parallel_count,
                on_output=emit_to_main,
                on_session_ready=lambda vlan, session, log_path: self.after(
                    0, lambda vlan=vlan, session=session, log_path=log_path: self._attach_serial_upgrade(vlan, session, log_path)
                ),
                cancel_event=cancel_event,
            )
            for offset, serial_index in enumerate(serial_indices):
                results[serial_index] = serial_results[offset]

        if telnet_indices:
            telnet_requests = [requests[i] for i in telnet_indices]
            with ThreadPoolExecutor(max_workers=min(parallel_count, len(telnet_requests)), thread_name_prefix="sample-parameter-telnet") as executor:
                # 错峰启动(2026-07-18 P2 缓解): 第 1 个 worker 立即 submit,后续每个 worker
                # 在 submit 前 sleep PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS,避免 8 台同 t=0
                # 触发网络准备 + UBUS 4 段 HTTP + telnet login 把网卡/防火墙挤爆。
                telnet_futures: dict = {}
                for offset, req in enumerate(telnet_requests):
                    if offset > 0:
                        time.sleep(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)
                    future = executor.submit(
                        run_single_sample_parameter_write,
                        req,
                        self.serial_session_manager,
                        emit_to_main,
                        None,
                        cancel_event,
                        time.sleep,
                        make_telnet_factory(req),
                        make_factory_session_swap(req),
                    )
                    telnet_futures[future] = telnet_indices[offset]
                for future in as_completed(telnet_futures):
                    telnet_results_index = telnet_futures[future]
                    try:
                        results[telnet_results_index] = future.result()
                    except Exception as exc:
                        req = requests[telnet_results_index]
                        results[telnet_results_index] = SampleParameterItemResult(
                            req, False, f"{req.vlan} telnet 写参启动失败：{exc}",
                            cancelled=cancel_event.is_set(),
                        )

        final = [r if isinstance(r, SampleParameterItemResult) else SampleParameterItemResult(requests[idx], False, "未运行") for idx, r in enumerate(results)]
        self.after(0, lambda: self._complete_sample_parameter_write(final))


    def _cancel_sample_parameter_write(self) -> None:
        if self.parameter_cancel_event is not None:
            self.parameter_cancel_event.set()
            self.parameter_cancel_button.configure(state="disabled")
            self.parameter_status_var.set("已请求停止：正在完成已进入工厂模式样机的清理。")
            self._log("写样机参数：用户请求停止批次，后续命令将停止并尝试清理工厂模式。")

    def _complete_sample_parameter_write(self, results) -> None:
        self.parameter_write_running = False
        self.parameter_cancel_event = None
        if self.parameter_writer_window is not None and self.parameter_writer_window.winfo_exists():
            self.parameter_write_button.configure(state="normal")
            self.parameter_cancel_button.configure(state="disabled")
        self.serial_terminal.finish_upgrade_logs()
        success_count = sum(1 for item in results if item.ok)
        summary = "\n".join(f"- {item.request.vlan}: {item.message}" for item in results)
        self._log(f"批量写样机参数结束：{success_count}/{len(results)} 台成功。")
        if self.parameter_writer_window is not None and self.parameter_writer_window.winfo_exists():
            self.parameter_status_var.set(f"批量写参完成：{success_count}/{len(results)} 台成功。")
        suppress_dialog = bool(
            getattr(self, "_pipeline_sample_parameter_completion_dialog_suppressed", False)
        )
        self._pipeline_sample_parameter_completion_dialog_suppressed = False
        if suppress_dialog:
            self._log(
                "[全流程][无人值守] 批量写参完成："
                f"成功 {success_count}/{len(results)} 台；已写入执行日志，不显示完成提示框。"
            )
        elif success_count == len(results):
            messagebox.showinfo("批量写参完成", f"全部 {success_count} 台样机写参并读回校验成功。", parent=self.parameter_writer_window)
        else:
            messagebox.showerror("批量写参存在失败", f"成功 {success_count}/{len(results)} 台。\n\n{summary}", parent=self.parameter_writer_window)
        _finish_pipeline_subtask_if_waiting(
            self,
            "sample_parameter_write",
            success_count == len(results),
            f"写样机参数完成：{success_count}/{len(results)} 台成功。",
        )

    def _open_parameter_generator(self) -> None:
        channel_ports = self._parameter_channel_ports()
        vlans = [vlan for vlan, _port in channel_ports if vlan]
        if not vlans:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选通道并配置 VLAN。", parent=self.parameter_writer_window)
            return
        dialog = Toplevel(self.parameter_writer_window)
        dialog.title("生成批量样机参数表")
        dialog.geometry("680x800")
        dialog.minsize(680, 800)
        dialog.transient(self.parameter_writer_window)
        dialog.grab_set()
        container = ttk.Frame(dialog, padding=14)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text=f"将为 {len(vlans)} 个已勾选 VLAN 生成一行参数。", style="CardHint.TLabel").pack(anchor="w", pady=(0, 10))

        fields = {
            "SN 前缀（纯数字）": StringVar(value="12345678"),
            "XPON SN 前缀（固定 4 位）": StringVar(value="XPON"),
            "MAC 前6位（十六进制）": StringVar(value="020000"),
            "2.4G SSID 前缀": StringVar(value="Test24G"),
            "5G SSID 前缀": StringVar(value="Test5G"),
            "SN 随机后缀长度（总长≤16）": StringVar(value="8"),
            "2.4G WiFi Password": StringVar(),
            "5G WiFi Password": StringVar(),
            "2.4G Country Code": StringVar(value="CN"),
            "5G Country Code": StringVar(value="CN"),
            "Product Class": StringVar(),
            "Superuser Name": StringVar(),
            "Superuser Password": StringVar(),
            "User Name": StringVar(),
            "User Password": StringVar(),
            "IP": StringVar(value="192.168.1.1"),
        }
        grid = ttk.Frame(container)
        grid.pack(fill="both", expand=True)
        for row, (label, variable) in enumerate(fields.items()):
            ttk.Label(grid, text=f"{label}：").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=3)
            ttk.Entry(grid, textvariable=variable, width=48).grid(row=row, column=1, sticky="ew", pady=3)
        grid.columnconfigure(1, weight=1)

        def generate_and_save() -> None:
            try:
                suffix_length = int(fields["SN 随机后缀长度（总长≤16）"].get().strip())
                fixed_values = {
                    column: fields[column].get()
                    for column in (
                        "2.4G WiFi Password", "5G WiFi Password", "2.4G Country Code", "5G Country Code",
                        "Product Class", "Superuser Name", "Superuser Password", "User Name", "User Password", "IP",
                    )
                }
                records = generate_parameter_records(
                    vlans,
                    ParameterGenerationTemplate(
                        sn_prefix=fields["SN 前缀（纯数字）"].get(),
                        xpon_prefix=fields["XPON SN 前缀（固定 4 位）"].get(),
                        mac_prefix=fields["MAC 前6位（十六进制）"].get(),
                        ssid_24_prefix=fields["2.4G SSID 前缀"].get(),
                        ssid_5_prefix=fields["5G SSID 前缀"].get(),
                        suffix_length=suffix_length,
                        fixed_values=fixed_values,
                    ),
                )
            except Exception as exc:
                messagebox.showwarning("生成参数表失败", str(exc), parent=dialog)
                self._log(f"[写样机参数][生成批量参数表] 参数生成失败：{exc}")
                return
            path = filedialog.asksaveasfilename(
                title="保存批量样机参数表",
                parent=dialog,
                defaultextension=".xlsx",
                filetypes=[("Excel 参数表", "*.xlsx")],
                initialfile="batch_sample_parameters.xlsx",
            )
            if not path:
                return
            try:
                save_parameter_records_xlsx(Path(path), records)
            except Exception as exc:
                messagebox.showerror("保存参数表失败", str(exc), parent=dialog)
                self._log(f"[写样机参数][生成批量参数表] 保存失败：{exc}")
                return
            self._log(
                f"[写样机参数][生成批量参数表] 成功：已生成 {len(records)} 条记录；"
                f"SN为纯数字且前缀+随机后缀不超过16位；"
                f"XPON SN固定12位（前缀4位 + 后8位大写十六进制）；"
                f"MAC前6位由用户指定、后6位为唯一随机十六进制；文件={path}"
            )
            dialog.grab_release()
            dialog.destroy()
            self._load_parameter_table(Path(path))
            messagebox.showinfo("参数表已生成", f"已生成 {len(records)} 条记录并完成预检。\n生成不会自动写入设备。", parent=self.parameter_writer_window)

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="生成并保存...", command=generate_and_save, style="Primary.TButton").pack(side="right")
        ttk.Button(buttons, text="取消", command=lambda: (dialog.grab_release(), dialog.destroy()), style="Secondary.TButton").pack(side="right", padx=(0, 8))
        center_toplevel_on_parent(
            dialog,
            self.parameter_writer_window,
            window_width=680,
            window_height=750,
        )
        schedule_toplevel_client_refresh(
            dialog,
            on_first_refresh=lambda: self._log(
                "[写样机参数][生成批量参数表] 已触发客户区首帧尺寸刷新"
            ),
        )

    def _bind_onu_registration_autosave(self) -> None:
        for variable in (
            self.onu_family_var,
            self.onu_olt_ip_var,
            self.onu_source_ip_var,
            self.onu_username_var,
            self.onu_password_var,
            self.onu_c600_shelf_var,
            self.onu_c600_slot_var,
            self.onu_c600_pon_var,
            self.onu_c600_onu_id_var,
            self.onu_c600_onu_type_var,
            self.onu_c600_real_speed_var,
            self.onu_c600_tcont_id_var,
            self.onu_c600_tcont_profile_var,
            self.onu_c600_gemport_id_var,
            self.onu_c600_vport_id_var,
            self.onu_c600_sn_bind_both_var,
            self.onu_c300_shelf_var,
            self.onu_c300_slot_var,
            self.onu_c300_pon_var,
            self.onu_c300_onu_id_var,
            self.onu_c300_onu_type_var,
            self.onu_c300_tcont_id_var,
            self.onu_c300_tcont_profile_var,
            self.onu_c300_allow_offline_cleanup_var,
        ):
            variable.trace_add("write", lambda *_args: self._on_onu_registration_input_changed())

    def _on_onu_registration_input_changed(self) -> None:
        self._schedule_onu_registration_save()
        if getattr(self, "onu_c300_cleanup_candidates", ()):
            self._clear_c300_cleanup_candidates()
        self._invalidate_onu_preview()

    def _on_onu_services_text_modified(self, event=None) -> None:
        widget = event.widget if event is not None else self.onu_c600_services_text
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._schedule_onu_registration_save()
        self._invalidate_onu_preview()

    def _invalidate_onu_preview(self) -> None:
        self.onu_preview_ready = False
        if hasattr(self, "onu_confirmation_summary_var"):
            self.onu_confirmation_summary_var.set("参数或目标已变化，请重新生成命令预览。")
        editor = getattr(self, "onu_command_editor", None)
        if editor is not None:
            editor.clear()
        elif getattr(self, "onu_command_preview_text", None) is not None:
            self.onu_command_preview_text.configure(state="normal")
            self.onu_command_preview_text.delete("1.0", "end")
            self.onu_command_preview_text.configure(state="disabled")
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(state="disabled")

    def _on_onu_command_editor_ready_changed(self, ready: bool) -> None:
        self.onu_preview_ready = ready
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(
                state="normal" if ready and not LineCheckAssistant._onu_operation_is_running(self) else "disabled"
            )

    def _onu_operation_is_running(self) -> bool:
        return any(getattr(self, name, False) for name in (
            "onu_telnet_test_running", "onu_query_running", "onu_cleanup_query_running",
            "onu_register_running", "onu_save_olt_running", "onu_manage_query_running",
            "onu_manage_delete_running", "onu_template_query_running",
        ))

    def _current_onu_registration_config(self) -> OnuRegistrationConfig:
        services = self.onu_registration_config.c600_services or DEFAULT_C600_SERVICES
        c300_services = self.onu_registration_config.c300_services or DEFAULT_C300_SERVICES
        services_widget = getattr(self, "onu_c600_services_text", None)
        if services_widget is not None:
            try:
                if services_widget.winfo_exists():
                    services = services_widget.get("1.0", "end").strip()
            except TclError:
                # Toplevel 已销毁时 Python 属性仍可能存在；全流程状态刷新应读取最近保存的缓存。
                pass
        c300_services_widget = getattr(self, "onu_c300_services_text", None)
        if c300_services_widget is not None:
            try:
                if c300_services_widget.winfo_exists():
                    c300_services = c300_services_widget.get("1.0", "end").strip()
            except TclError:
                pass

        def integer_value(variable, fallback: int) -> int:
            try:
                if variable is None:
                    return fallback
                return int(variable.get().strip())
            except (TypeError, ValueError):
                return fallback

        family = self.onu_family_var.get()
        if hasattr(self, "onu_connection_profiles"):
            self._remember_onu_connection_profile(family)
            profiles = self.onu_connection_profiles
        else:
            profiles = {
                OLT_FAMILY_C300: {
                    "olt_ip": self.onu_registration_config.c300_olt_ip,
                    "source_ip": self.onu_registration_config.c300_source_ip,
                    "username": self.onu_registration_config.c300_username,
                    "password": self.onu_registration_config.c300_password,
                },
                OLT_FAMILY_C600: {
                    "olt_ip": self.onu_registration_config.c600_olt_ip,
                    "source_ip": self.onu_registration_config.c600_source_ip,
                    "username": self.onu_registration_config.c600_username,
                    "password": self.onu_registration_config.c600_password,
                },
            }
            profiles[family] = {
                "olt_ip": self.onu_olt_ip_var.get(),
                "source_ip": self.onu_source_ip_var.get(),
                "username": self.onu_username_var.get(),
                "password": self.onu_password_var.get(),
            }

        return OnuRegistrationConfig(
            olt_ip=self.onu_olt_ip_var.get(),
            username=self.onu_username_var.get(),
            password=self.onu_password_var.get(),
            olt_family=self.onu_family_var.get(),
            source_ip=self.onu_source_ip_var.get(),
            c300_olt_ip=profiles[OLT_FAMILY_C300]["olt_ip"],
            c300_source_ip=profiles[OLT_FAMILY_C300]["source_ip"],
            c300_username=profiles[OLT_FAMILY_C300]["username"],
            c300_password=profiles[OLT_FAMILY_C300]["password"],
            c600_olt_ip=profiles[OLT_FAMILY_C600]["olt_ip"],
            c600_source_ip=profiles[OLT_FAMILY_C600]["source_ip"],
            c600_username=profiles[OLT_FAMILY_C600]["username"],
            c600_password=profiles[OLT_FAMILY_C600]["password"],
            c600_shelf=integer_value(self.onu_c600_shelf_var, 1),
            c600_slot=integer_value(self.onu_c600_slot_var, 1),
            c600_pon=integer_value(self.onu_c600_pon_var, 5),
            c600_onu_id=integer_value(self.onu_c600_onu_id_var, 1),
            c600_onu_type=LineCheckAssistant._template_name_from_input(self.onu_c600_onu_type_var.get()),
            c600_real_speed=self.onu_c600_real_speed_var.get(),
            c600_tcont_id=integer_value(self.onu_c600_tcont_id_var, 1),
            c600_tcont_profile=LineCheckAssistant._template_name_from_input(self.onu_c600_tcont_profile_var.get()),
            c600_gemport_id=integer_value(self.onu_c600_gemport_id_var, 1),
            c600_vport_id=integer_value(self.onu_c600_vport_id_var, 1),
            c600_sn_bind_both=bool(self.onu_c600_sn_bind_both_var.get()),
            c600_services=services,
            c300_shelf=integer_value(getattr(self, "onu_c300_shelf_var", None), 1),
            c300_slot=integer_value(getattr(self, "onu_c300_slot_var", None), 2),
            c300_pon=integer_value(getattr(self, "onu_c300_pon_var", None), 1),
            c300_onu_id=integer_value(getattr(self, "onu_c300_onu_id_var", None), 1),
            c300_onu_type=(
                LineCheckAssistant._template_name_from_input(self.onu_c300_onu_type_var.get())
                if hasattr(self, "onu_c300_onu_type_var") else "SD-41"
            ),
            c300_tcont_id=integer_value(getattr(self, "onu_c300_tcont_id_var", None), 1),
            c300_tcont_profile=(
                LineCheckAssistant._template_name_from_input(self.onu_c300_tcont_profile_var.get())
                if hasattr(self, "onu_c300_tcont_profile_var") else "1G"
            ),
            c300_services=c300_services,
            c300_allow_offline_cleanup=False,
        )

    def _remember_onu_connection_profile(self, family: str) -> None:
        if family not in OLT_FAMILIES or not hasattr(self, "onu_connection_profiles"):
            return
        self.onu_connection_profiles[family] = {
            "olt_ip": self.onu_olt_ip_var.get().strip(),
            "source_ip": self.onu_source_ip_var.get().strip(),
            "username": self.onu_username_var.get().strip(),
            "password": self.onu_password_var.get(),
        }

    def _load_onu_connection_profile(self, family: str) -> None:
        profile = self.onu_connection_profiles[family]
        self.onu_olt_ip_var.set(profile["olt_ip"])
        self.onu_source_ip_var.set(profile["source_ip"])
        self.onu_username_var.set(profile["username"])
        self.onu_password_var.set(profile["password"])

    def _schedule_onu_registration_save(self) -> None:
        if self.onu_save_after_id is not None:
            try:
                self.after_cancel(self.onu_save_after_id)
            except Exception:
                pass
        self.onu_save_after_id = self.after(400, self._save_onu_registration_config)

    def _save_onu_registration_config(self) -> None:
        self.onu_save_after_id = None
        config = self._current_onu_registration_config()
        self.onu_registration_store.save(config)
        self.onu_registration_config = config

    def _bind_sample_upgrade_autosave(self) -> None:
        for variable in (
            self.upgrade_mode_var,
            self.upgrade_transfer_var,
            self.upgrade_boot_entry_var,
            self.upgrade_restore_factory_var,
            self.upgrade_username_var,
            self.upgrade_password_var,
            self.upgrade_firmware_var,
            self.parameter_initial_username_var,
            self.parameter_initial_password_var,
            self.parameter_parallel_count_var,
            self.parameter_clear_parameters_var,
            self.parameter_exit_aging_var,
            # 2026-07-20:全流程执行管道用的两个新字段,加入 autosave 链。
            self.power_operation_var,
            self.parameter_table_path_var,
        ):
            variable.trace_add("write", lambda *_args: self._schedule_sample_upgrade_save())

    @staticmethod
    def _normalize_upgrade_transfer_method(transfer_method: str) -> str:
        if transfer_method == LEGACY_TFTP_COPY_TRANSFER:
            return TFTP_COMMAND_TRANSFER
        return transfer_method

    def _current_sample_upgrade_settings(self) -> SampleUpgradeSettings:
        return SampleUpgradeSettings(
            boot_entry_method=LineCheckAssistant._selected_boot_entry_method(self),
            upgrade_mode=self.upgrade_mode_var.get(),
            transfer_method=LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get()),
            parallel_count=clamp_parallel_count(self.upgrade_parallel_count_var.get()),
            restore_factory=bool(self.upgrade_restore_factory_var.get()),
            username=self.upgrade_username_var.get(),
            password=self.upgrade_password_var.get(),
            firmware_path=self.upgrade_firmware_var.get(),
            parameter_initial_username=self.parameter_initial_username_var.get(),
            parameter_initial_password=self.parameter_initial_password_var.get(),
            parameter_parallel_count=clamp_parameter_parallel_count(
                self.parameter_parallel_count_var.get()
            ),
            parameter_clear_parameters=bool(self.parameter_clear_parameters_var.get()),
            parameter_exit_aging=bool(self.parameter_exit_aging_var.get()),
            # 2026-07-20:全流程执行管道用的两个新字段,透传到 ``SampleUpgradeSettings``。
            power_operation=(self.power_operation_var.get() or "up").strip().lower()
            if (self.power_operation_var.get() or "up").strip().lower() in {"up", "down"}
            else "up",
            parameter_table_path=(self.parameter_table_path_var.get() or "").strip(),
        )

    def _schedule_sample_upgrade_save(self) -> None:
        if self.sample_upgrade_save_after_id is not None:
            try:
                self.after_cancel(self.sample_upgrade_save_after_id)
            except Exception:
                pass
        self.sample_upgrade_save_after_id = self.after(400, self._save_sample_upgrade_settings)

    def _save_sample_upgrade_settings(self) -> None:
        self.sample_upgrade_save_after_id = None
        self.sample_upgrade_settings_store.save(self._current_sample_upgrade_settings())

    def _open_onu_registration_module(self) -> None:
        if self.onu_registration_window is not None and self.onu_registration_window.winfo_exists():
            self.onu_registration_window.deiconify()
            self.onu_registration_window.lift()
            self.onu_registration_window.focus_force()
            return

        # write 是整台 OLT 的持久化操作，只允许本次窗口明确授权，关闭后不保留。
        self.onu_c600_write_after_success_var.set(False)
        dialog = Toplevel(self)
        self.onu_registration_window = dialog
        dialog.title("ONU注册")
        window_width, window_height = self._restore_module_window_size(
            dialog, "onu_registration"
        )
        dialog.minsize(1000, 900)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)
        title_label = Label(
            content,
            text="ONU注册",
            font=(FONT_FAMILY, 18, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        )
        title_label.grid(row=0, column=0, sticky="w")
        subtitle_label = Label(
            content,
            text="统一支持中兴 C300 与 C600；业务流程一致，实际 CLI 按型号严格隔离。",
            foreground=COLOR_MUTED,
            background=COLOR_BG,
        )
        subtitle_label.grid(row=1, column=0, sticky="w", pady=(4, 8))

        connection_frame = ttk.LabelFrame(content, text="OLT 连接")
        connection_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5):
            connection_frame.columnconfigure(column, weight=1)

        Label(connection_frame, text="OLT 型号", anchor="w").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=4)
        self.onu_family_combo = ttk.Combobox(
            connection_frame,
            textvariable=self.onu_family_var,
            values=OLT_FAMILIES,
            state="readonly",
            width=14,
        )
        self.onu_family_combo.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=4)
        self.onu_family_combo.bind("<<ComboboxSelected>>", self._on_onu_family_changed)
        Label(connection_frame, text="OLT IP", anchor="w").grid(row=0, column=2, sticky="w", padx=(4, 4), pady=4)
        ttk.Entry(connection_frame, textvariable=self.onu_olt_ip_var, width=18).grid(
            row=0, column=3, sticky="ew", padx=(0, 10), pady=4
        )
        Label(connection_frame, text="源 IP", anchor="w").grid(row=0, column=4, sticky="w", padx=(4, 4), pady=4)
        ttk.Entry(connection_frame, textvariable=self.onu_source_ip_var, width=18).grid(
            row=0, column=5, sticky="ew", padx=(0, 10), pady=4
        )

        Label(connection_frame, text="用户名", anchor="w").grid(row=1, column=0, sticky="w", padx=(10, 4), pady=4)
        ttk.Entry(connection_frame, textvariable=self.onu_username_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=4
        )
        Label(connection_frame, text="密码", anchor="w").grid(row=1, column=2, sticky="w", padx=(4, 4), pady=4)
        onu_password_container = Frame(connection_frame, background=COLOR_SURFACE)
        onu_password_container.grid(row=1, column=3, sticky="ew", padx=(0, 10), pady=4)
        self.onu_password_entry = ttk.Entry(onu_password_container, textvariable=self.onu_password_var, width=18, show="*")
        self.onu_password_entry.pack(side="left", fill="x", expand=True)
        self.onu_password_toggle = Button(
            onu_password_container,
            text="👁",
            width=3,
            command=self._toggle_onu_password_visibility,
        )
        self.onu_password_toggle.pack(side="right", padx=(6, 0))
        self.onu_status_label = Label(
            connection_frame,
            textvariable=self.onu_telnet_status_var,
            anchor="w",
            background=COLOR_SURFACE_SUBTLE,
            foreground=COLOR_TEXT,
            relief="solid",
            borderwidth=1,
            padx=8,
        )
        self.onu_status_label.grid(row=2, column=0, columnspan=5, sticky="ew", padx=(10, 6), pady=(0, 4))
        self.onu_telnet_test_button = ttk.Button(
            connection_frame,
            text="登录测试",
            command=self._on_onu_telnet_test_clicked,
            style="Secondary.TButton",
        )
        self.onu_telnet_test_button.grid(row=2, column=5, sticky="e", padx=(0, 10), pady=(0, 4))

        self.onu_notebook = ttk.Notebook(content)
        self.onu_notebook.grid(row=3, column=0, sticky="nsew")
        discovery_tab = Frame(self.onu_notebook, padx=8, pady=8, background=COLOR_BG)
        config_tab = Frame(self.onu_notebook, padx=8, pady=8, background=COLOR_BG)
        preview_tab = Frame(self.onu_notebook, padx=8, pady=8, background=COLOR_BG)
        self.onu_discovery_tab = discovery_tab
        self.onu_config_tab = config_tab
        self.onu_c600_tab = config_tab
        self.onu_preview_tab = preview_tab
        self.onu_notebook.add(discovery_tab, text="1. 查询 ONU")
        self.onu_notebook.add(config_tab, text="2. 配置业务")
        self.onu_notebook.add(preview_tab, text="3. 确认执行")

        manage_tab = Frame(self.onu_notebook, padx=8, pady=8, background=COLOR_BG)
        self.onu_manage_tab = manage_tab
        self.onu_notebook.add(manage_tab, text="4. 已注册管理")
        manage_tab.columnconfigure(0, weight=1)
        manage_tab.rowconfigure(3, weight=1)

        manage_scope_frame = ttk.LabelFrame(manage_tab, text="目标 PON 口（机框/槽位/PON）")
        manage_scope_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column in (1, 3, 5):
            manage_scope_frame.columnconfigure(column, weight=1)

        def manage_scope_field(column, label, variable):
            Label(manage_scope_frame, text=label, anchor="w").grid(
                row=0, column=column, sticky="w", padx=(10, 4), pady=4
            )
            ttk.Entry(manage_scope_frame, textvariable=variable, width=10).grid(
                row=0, column=column + 1, sticky="ew", padx=(0, 10), pady=4
            )

        manage_scope_field(0, "机框", self.onu_manage_shelf_var)
        manage_scope_field(2, "槽位", self.onu_manage_slot_var)
        manage_scope_field(4, "PON", self.onu_manage_pon_var)

        manage_actions = Frame(manage_tab, background=COLOR_BG)
        manage_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.onu_manage_query_button = ttk.Button(
            manage_actions,
            text="查询已注册 ONU",
            command=self._on_onu_manage_query_clicked,
            style="Secondary.TButton",
        )
        self.onu_manage_query_button.pack(side="left")

        manage_candidate_row = Frame(manage_tab, background=COLOR_BG)
        manage_candidate_row.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        Label(
            manage_candidate_row,
            text="选择要删除的已注册 ONU",
            anchor="w",
            background=COLOR_BG,
        ).pack(side="left")
        self.onu_registered_combo = ttk.Combobox(
            manage_candidate_row,
            textvariable=self.onu_registered_candidate_var,
            values=(),
            state="disabled",
            width=62,
        )
        self.onu_registered_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.onu_registered_combo.bind(
            "<<ComboboxSelected>>",
            self._on_registered_candidate_selected,
        )

        Label(
            manage_tab,
            text=(
                "列出目标 PON 口下所有已注册 ONU（含在线 working）；删除在线 ONU 会立即中断其业务。"
                "删除前会二次确认并重新核对接口与 SN，只删除明确选择的这一台，"
                "删除后回读确认其回到未注册状态，且不执行 write。"
            ),
            justify="left",
            anchor="nw",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).grid(row=3, column=0, sticky="nsew", pady=(4, 6))

        self.onu_manage_delete_button = ttk.Button(
            manage_tab,
            text="删除选中 ONU（危险）",
            command=self._on_onu_manage_delete_clicked,
            style="Danger.TButton",
            state="disabled",
        )
        self.onu_manage_delete_button.grid(row=4, column=0, sticky="ew", pady=(0, 6))

        discovery_tab.columnconfigure(0, weight=1)
        discovery_tab.rowconfigure(2, weight=1)
        self.onu_c300_scope_frame = ttk.LabelFrame(discovery_tab, text="C300 查询范围")
        self.onu_c300_scope_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column in (1, 3, 5):
            self.onu_c300_scope_frame.columnconfigure(column, weight=1)

        def c300_scope_field(column, label, variable):
            Label(self.onu_c300_scope_frame, text=label, anchor="w").grid(
                row=0, column=column, sticky="w", padx=(10, 4), pady=4
            )
            ttk.Entry(self.onu_c300_scope_frame, textvariable=variable, width=10).grid(
                row=0, column=column + 1, sticky="ew", padx=(0, 10), pady=4
            )

        c300_scope_field(0, "机框", self.onu_c300_shelf_var)
        c300_scope_field(2, "槽位", self.onu_c300_slot_var)
        c300_scope_field(4, "PON", self.onu_c300_pon_var)

        self.onu_c600_scope_frame = ttk.LabelFrame(discovery_tab, text="C600 查询范围")
        self.onu_c600_scope_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column in (1, 3, 5):
            self.onu_c600_scope_frame.columnconfigure(column, weight=1)

        def c600_scope_field(column, label, variable):
            Label(self.onu_c600_scope_frame, text=label, anchor="w").grid(
                row=0, column=column, sticky="w", padx=(10, 4), pady=4
            )
            ttk.Entry(self.onu_c600_scope_frame, textvariable=variable, width=10).grid(
                row=0, column=column + 1, sticky="ew", padx=(0, 10), pady=4
            )

        c600_scope_field(0, "机框", self.onu_c600_shelf_var)
        c600_scope_field(2, "槽位", self.onu_c600_slot_var)
        c600_scope_field(4, "PON", self.onu_c600_pon_var)

        query_actions = Frame(discovery_tab, background=COLOR_BG)
        query_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.onu_query_button = ttk.Button(
            query_actions,
            text="查询未注册 ONU（全0=整机）",
            command=self._on_onu_query_unregistered_clicked,
            style="Secondary.TButton",
        )
        self.onu_query_button.pack(side="left")
        self.onu_clear_selection_button = ttk.Button(
            query_actions,
            text="清除选择",
            command=self._clear_unregistered_onu_selection,
            style="Secondary.TButton",
            state="disabled",
        )
        self.onu_clear_selection_button.pack(side="left", padx=(8, 0))
        self.onu_next_config_button = ttk.Button(
            query_actions,
            text="下一步：配置业务",
            command=self._go_to_onu_config_step,
            style="Primary.TButton",
            state="disabled",
        )
        self.onu_next_config_button.pack(side="right")

        self.onu_unregistered_list_frame = Frame(
            discovery_tab,
            background=COLOR_SURFACE_SUBTLE,
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
        )
        self.onu_unregistered_list_frame.grid(row=2, column=0, sticky="nsew")

        config_tab.columnconfigure(0, weight=1)
        config_tab.rowconfigure(0, weight=1)
        self.onu_c300_config_frame = Frame(config_tab, background=COLOR_BG)
        self.onu_c300_config_frame.grid(row=0, column=0, sticky="nsew")
        c300_form = ttk.LabelFrame(self.onu_c300_config_frame, text="C300 注册参数")
        c300_form.pack(fill="x")
        for column in (1, 3, 5, 7):
            c300_form.columnconfigure(column, weight=1)

        def c300_field(row, column, label, variable, width=10):
            Label(c300_form, text=label, anchor="w").grid(row=row, column=column, sticky="w", padx=(10, 4), pady=5)
            ttk.Entry(c300_form, textvariable=variable, width=width).grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=5)

        def c300_template_field(row, column, label, variable, kind, width=12):
            Label(c300_form, text=label, anchor="w").grid(row=row, column=column, sticky="w", padx=(10, 4), pady=5)
            container = Frame(c300_form, background=COLOR_SURFACE)
            container.grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=5)
            combo = ttk.Combobox(container, textvariable=variable, values=(), state="normal", width=width)
            combo.pack(side="left", fill="x", expand=True)
            combo.bind("<<ComboboxSelected>>", lambda _event: self._invalidate_onu_preview())
            button = ttk.Button(
                container,
                text="查询",
                command=lambda: self._on_onu_template_query_clicked(kind),
                style="Secondary.TButton",
                width=5,
            )
            button.pack(side="left", padx=(4, 0))
            setattr(self, f"onu_c300_{kind}_combo", combo)
            setattr(self, f"onu_c300_{kind}_query_button", button)

        c300_field(0, 0, "ONU ID", self.onu_c300_onu_id_var, 8)
        c300_template_field(0, 2, "ONU 类型模板", self.onu_c300_onu_type_var, "onu_type", 14)
        c300_field(0, 4, "T-CONT", self.onu_c300_tcont_id_var, 8)
        c300_template_field(0, 6, "DBA模板", self.onu_c300_tcont_profile_var, "dba", 12)
        ttk.Label(
            c300_form,
            text=(
                "业务表固定保留六项标准业务；每行 Service ID 同时作为 GEM Port 与 VPort，必须保留组播 VLAN 600。"
            ),
            justify="left",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=8, sticky="w", padx=10, pady=(2, 6))
        c300_mapping_frame = ttk.LabelFrame(self.onu_c300_config_frame, text="业务分类映射（每行 ServiceID,VLAN）")
        c300_mapping_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.onu_c300_services_text = Text(c300_mapping_frame, height=6, font=("Consolas", 10), wrap="none")
        self.onu_c300_services_text.insert("1.0", self.onu_registration_config.c300_services or DEFAULT_C300_SERVICES)
        self.onu_c300_services_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.onu_c300_services_text.edit_modified(False)
        self.onu_c300_services_text.bind("<<Modified>>", self._on_onu_services_text_modified)
        ttk.Label(
            c300_mapping_frame,
            text="上网：第1/5/6行（Internet/Internet2/Internet3）；TR069：第2行；语音：第3行；IPTV：第4行。C300仍为每项独立 GEM/VPort。",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(0, 8))
        # ttk 的 clam 主题会把选中态绘制为叉号；布尔选项统一使用原生
        # Checkbutton，让选中态显示标准勾号，同时保留原有变量与命令语义。
        self.onu_c300_cleanup_check = Checkbutton(
            self.onu_c300_config_frame,
            text="C300 配置失败时，允许删除明确选择的一台同 PON 离线 ONU 后重试（危险）",
            variable=self.onu_c300_allow_offline_cleanup_var,
            command=self._on_c300_cleanup_toggle,
            selectcolor="#ffffff",
            background=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.onu_c300_cleanup_check.pack(anchor="w", padx=10, pady=(0, 6))
        cleanup_row = Frame(self.onu_c300_config_frame, background=COLOR_BG)
        cleanup_row.pack(fill="x", padx=10, pady=(0, 8))
        self.onu_c300_cleanup_query_button = ttk.Button(
            cleanup_row,
            text="查询同 PON 离线候选",
            command=self._on_c300_cleanup_candidates_clicked,
            style="Secondary.TButton",
            state="disabled",
        )
        self.onu_c300_cleanup_query_button.pack(side="left")
        self.onu_c300_cleanup_combo = ttk.Combobox(
            cleanup_row,
            textvariable=self.onu_c300_cleanup_candidate_var,
            values=(),
            state="disabled",
            width=62,
        )
        self.onu_c300_cleanup_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.onu_c300_cleanup_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._invalidate_onu_preview(),
        )

        self.onu_c600_config_frame = Frame(config_tab, background=COLOR_BG)
        self.onu_c600_config_frame.grid(row=0, column=0, sticky="nsew")
        c600_form = ttk.LabelFrame(self.onu_c600_config_frame, text="C600 注册参数")
        c600_form.pack(fill="x")
        for column in (1, 3, 5, 7):
            c600_form.columnconfigure(column, weight=1)

        def c600_field(row, column, label, variable, width=10):
            Label(c600_form, text=label, anchor="w").grid(
                row=row, column=column, sticky="w", padx=(10, 4), pady=5
            )
            entry = ttk.Entry(c600_form, textvariable=variable, width=width)
            entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=5)
            return entry

        def c600_template_field(row, column, label, variable, kind, width=12):
            Label(c600_form, text=label, anchor="w").grid(
                row=row, column=column, sticky="w", padx=(10, 4), pady=5
            )
            container = Frame(c600_form, background=COLOR_SURFACE)
            container.grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=5)
            combo = ttk.Combobox(container, textvariable=variable, values=(), state="normal", width=width)
            combo.pack(side="left", fill="x", expand=True)
            combo.bind("<<ComboboxSelected>>", lambda _event: self._invalidate_onu_preview())
            button = ttk.Button(
                container,
                text="查询",
                command=lambda: self._on_onu_template_query_clicked(kind),
                style="Secondary.TButton",
                width=5,
            )
            button.pack(side="left", padx=(4, 0))
            setattr(self, f"onu_c600_{kind}_combo", combo)
            setattr(self, f"onu_c600_{kind}_query_button", button)

        c600_field(0, 0, "ONU ID", self.onu_c600_onu_id_var, 8)
        c600_template_field(0, 2, "ONU 类型模板", self.onu_c600_onu_type_var, "onu_type", 14)
        Label(c600_form, text="速率设置", anchor="w").grid(row=0, column=4, sticky="w", padx=(10, 4), pady=5)
        ttk.Combobox(
            c600_form,
            textvariable=self.onu_c600_real_speed_var,
            values=("auto", "xgspon", "xgpon", "gpon"),
            state="readonly",
            width=10,
        ).grid(row=0, column=5, sticky="ew", padx=(0, 8), pady=5)
        c600_field(0, 6, "上网T-CONT", self.onu_c600_tcont_id_var, 8)
        c600_template_field(1, 0, "上网DBA模板", self.onu_c600_tcont_profile_var, "dba", 12)
        c600_field(1, 2, "上网GEM Port", self.onu_c600_gemport_id_var, 8)
        c600_field(1, 4, "上网VPort", self.onu_c600_vport_id_var, 8)
        Checkbutton(
            c600_form,
            text="启用 SN 双重绑定",
            variable=self.onu_c600_sn_bind_both_var,
            selectcolor="#ffffff",
            background=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            highlightthickness=0,
            borderwidth=0,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=10, pady=5)
        ttk.Label(
            c600_form,
            text="ONU 类型模板是 OLT 中的 onu-type 模板名称；默认带入查询到的 ONU 型号，可按实际兼容模板修改。",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=8, sticky="w", padx=10, pady=(2, 0))
        Checkbutton(
            c600_form,
            text="完整验证成功后执行 write（危险，仅本次有效）",
            variable=self.onu_c600_write_after_success_var,
            command=self._invalidate_onu_preview,
            selectcolor="#ffffff",
            background=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            highlightthickness=0,
            borderwidth=0,
        ).grid(row=3, column=0, columnspan=8, sticky="w", padx=10, pady=(2, 6))

        mapping_frame = ttk.LabelFrame(self.onu_c600_config_frame, text="业务映射（每行 ServiceID,ONU侧VLAN[,网络侧VLAN]）")
        mapping_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.onu_c600_services_text = Text(mapping_frame, height=6, font=("Consolas", 10), wrap="none")
        self.onu_c600_services_text.insert("1.0", self.onu_registration_config.c600_services or DEFAULT_C600_SERVICES)
        self.onu_c600_services_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.onu_c600_services_text.edit_modified(False)
        self.onu_c600_services_text.bind("<<Modified>>", self._on_onu_services_text_modified)
        ttk.Label(
            mapping_frame,
            text="例如 2,111,171 表示 ONU VLAN111 ↔ 网络 VLAN171；两列表示两侧相同。语音/组播/TR069按网络侧335/600/50分层。",
            wraplength=880,
        ).pack(anchor="w", padx=8, pady=(0, 6))
        ttk.Label(
            mapping_frame,
            text=(
                "业务分层：上网→GEM/VPort 1；语音335→2；组播600→3（含IGMP）；"
                "TR069 50→4。GEM与VPort必须1:1对应。"
            ),
        ).pack(anchor="w", padx=8, pady=(0, 8))

        config_actions = Frame(config_tab, background=COLOR_BG)
        config_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            config_actions,
            text="返回查询",
            command=lambda: self.onu_notebook.select(self.onu_discovery_tab),
            style="Secondary.TButton",
        ).pack(side="left")
        self.onu_preview_button = ttk.Button(
            config_actions,
            text="生成预览并进入下一步",
            command=self._on_onu_preview_clicked,
            style="Primary.TButton",
            state="disabled",
        )
        self.onu_preview_button.pack(side="right")

        preview_tab.columnconfigure(0, weight=1)
        preview_tab.rowconfigure(1, weight=1)
        self.onu_confirmation_summary_var = StringVar(value="请先完成 ONU 查询与业务配置。")
        summary_frame = ttk.LabelFrame(preview_tab, text="执行摘要")
        summary_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(
            summary_frame,
            textvariable=self.onu_confirmation_summary_var,
            justify="left",
        ).pack(fill="x", padx=8, pady=6)
        self.onu_command_editor = OnuCommandEditor(
            preview_tab, height=8,
            on_ready_changed=self._on_onu_command_editor_ready_changed,
            log=lambda text: self._log(f"[ONU注册][{self.onu_family_var.get()}] {text}"),
        )
        self.onu_command_editor.frame.grid(row=1, column=0, sticky="nsew")
        self.onu_command_preview_text = self.onu_command_editor.text
        preview_actions = Frame(preview_tab, background=COLOR_BG)
        preview_actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            preview_actions,
            text="返回修改",
            command=lambda: self.onu_notebook.select(self.onu_config_tab),
            style="Secondary.TButton",
        ).pack(side="left")
        self.onu_register_button = ttk.Button(
            preview_actions,
            text="开始注册",
            command=self._on_onu_register_selected_clicked,
            style="Primary.TButton",
            state="disabled",
        )
        self.onu_register_button.pack(side="right")

        warning_label = Label(
            content,
            text="注册会修改 OLT 当前配置；命令预览只读，业务参数请返回第二步修改；write 按本次授权独立保存。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        )
        warning_label.grid(row=4, column=0, sticky="w", pady=(6, 0))

        self.onu_query_status_label = Label(
            content,
            textvariable=self.onu_query_status_var,
            anchor="w",
            justify="left",
            background=COLOR_SURFACE_SUBTLE,
            foreground=COLOR_TEXT,
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=4,
            wraplength=760,
        )
        self.onu_query_status_label.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.onu_query_status_label.bind(
            "<Configure>",
            lambda event: self.onu_query_status_label.configure(wraplength=max(280, event.width - 18)),
        )

        def close_dialog() -> None:
            if (
                self.onu_telnet_test_running
                or self.onu_query_running
                or self.onu_cleanup_query_running
                or self.onu_register_running
                or self.onu_save_olt_running
                or self.onu_manage_query_running
                or self.onu_manage_delete_running
            ):
                messagebox.showwarning(
                    "ONU 操作正在执行",
                    "请先点击“停止”并等待当前操作安全结束，再关闭窗口。",
                    parent=dialog,
                )
                return
            try:
                self._cancel_pending_onu_registration_save()
                self._save_onu_registration_config()
            except Exception:
                pass
            finally:
                self._remember_module_window_size(dialog, "onu_registration")
                dialog.destroy()
                self.onu_registration_window = None
                self.onu_command_editor = None
                self.onu_command_preview_text = None
                self.onu_preview_ready = False

        bottom_actions = Frame(content, background=COLOR_BG)
        bottom_actions.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        self.onu_stop_button = ttk.Button(
            bottom_actions,
            text="停止",
            width=12,
            command=self._on_onu_stop_clicked,
            style="Secondary.TButton",
            state="disabled",
        )
        self.onu_stop_button.pack(side="right", padx=(8, 0))
        ttk.Button(bottom_actions, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        self.onu_preview_ready = False
        self._on_onu_family_changed()
        center_toplevel_on_parent(
            dialog, self, window_width=window_width, window_height=window_height
        )

    def _on_onu_family_changed(self, _event=None) -> None:
        family = self.onu_family_var.get()
        if family not in OLT_FAMILIES:
            family = OLT_FAMILY_C300
            self.onu_family_var.set(family)
        previous_family = getattr(self, "onu_active_family", family)
        if hasattr(self, "onu_connection_profiles") and previous_family != family:
            self._remember_onu_connection_profile(previous_family)
            self._load_onu_connection_profile(family)
            self.onu_active_family = family
        if hasattr(self, "onu_c600_scope_frame"):
            if family == OLT_FAMILY_C600:
                self.onu_c600_scope_frame.grid()
            else:
                self.onu_c600_scope_frame.grid_remove()
        if hasattr(self, "onu_c300_scope_frame"):
            if family == OLT_FAMILY_C300:
                self.onu_c300_scope_frame.grid()
            else:
                self.onu_c300_scope_frame.grid_remove()
        if hasattr(self, "onu_c300_config_frame") and hasattr(self, "onu_c600_config_frame"):
            if family == OLT_FAMILY_C600:
                self.onu_c300_config_frame.grid_remove()
                self.onu_c600_config_frame.grid()
            else:
                self.onu_c600_config_frame.grid_remove()
                self.onu_c300_config_frame.grid()
        if hasattr(self, "onu_c300_cleanup_check"):
            self.onu_c300_cleanup_check.configure(state="normal" if family == OLT_FAMILY_C300 else "disabled")
        if hasattr(self, "onu_c300_cleanup_query_button"):
            self._on_c300_cleanup_toggle()
        if hasattr(self, "onu_notebook"):
            self.onu_notebook.select(self.onu_discovery_tab)
        self._render_unregistered_onu_selection([])
        if hasattr(self, "onu_c300_cleanup_candidate_var"):
            self._clear_c300_cleanup_candidates()
        if hasattr(self, "onu_registered_candidates"):
            self._clear_registered_candidates()
            if family == OLT_FAMILY_C600:
                self.onu_manage_shelf_var.set(self.onu_c600_shelf_var.get())
                self.onu_manage_slot_var.set(self.onu_c600_slot_var.get())
                self.onu_manage_pon_var.set(self.onu_c600_pon_var.get())
        self._invalidate_onu_preview()
        self._set_onu_telnet_status("")
        query_hint = (
            "C300 将执行全局未注册查询，并按上方机框、槽位、PON 筛选结果"
            if family == OLT_FAMILY_C300
            else "请填写上方机框、槽位和 PON，再查询 C600 未注册 ONU"
        )
        self._set_onu_query_status(query_hint, COLOR_MUTED)

    def _clear_c300_cleanup_candidates(self) -> None:
        self.onu_c300_cleanup_candidates = ()
        self.onu_c300_cleanup_candidate_var.set("")
        if hasattr(self, "onu_c300_cleanup_combo"):
            self.onu_c300_cleanup_combo.configure(values=())

    def _clear_registered_candidates(self) -> None:
        self.onu_registered_candidates = ()
        self.onu_registered_candidate_var.set("")
        if hasattr(self, "onu_registered_combo"):
            self.onu_registered_combo.configure(values=(), state="disabled")
        if hasattr(self, "onu_manage_delete_button"):
            self.onu_manage_delete_button.configure(state="disabled")

    def _current_onu_manage_pon_interface(self) -> str:
        try:
            shelf = int(self.onu_manage_shelf_var.get().strip())
            slot = int(self.onu_manage_slot_var.get().strip())
            pon = int(self.onu_manage_pon_var.get().strip())
        except ValueError as exc:
            raise ValueError("已注册管理：机框、槽位和 PON 必须是整数") from exc
        if not (1 <= shelf <= 64 and 1 <= slot <= 64 and 1 <= pon <= 64):
            raise ValueError("已注册管理：机框、槽位和 PON 必须在 1-64 之间")
        family = self.onu_family_var.get()
        if family == OLT_FAMILY_C600:
            return f"gpon_olt-{shelf}/{slot}/{pon}"
        return f"gpon-olt_{shelf}/{slot}/{pon}"

    def _selected_registered_onu(self):
        selected = self.onu_registered_candidate_var.get()
        return next(
            (
                candidate
                for candidate in self.onu_registered_candidates
                if candidate.display_text == selected
            ),
            None,
        )

    def _on_c300_cleanup_toggle(self) -> None:
        enabled = (
            self.onu_family_var.get() == OLT_FAMILY_C300
            and bool(self.onu_c300_allow_offline_cleanup_var.get())
        )
        if not enabled:
            self._clear_c300_cleanup_candidates()
        if hasattr(self, "onu_c300_cleanup_query_button"):
            self.onu_c300_cleanup_query_button.configure(state="normal" if enabled else "disabled")
        if hasattr(self, "onu_c300_cleanup_combo"):
            self.onu_c300_cleanup_combo.configure(
                state="readonly" if enabled and self.onu_c300_cleanup_candidates else "disabled"
            )
        self._invalidate_onu_preview()

    def _selected_c300_cleanup_candidate(self):
        selected = self.onu_c300_cleanup_candidate_var.get()
        return next(
            (
                candidate
                for candidate in self.onu_c300_cleanup_candidates
                if candidate.display_text == selected
            ),
            None,
        )

    def _on_c300_cleanup_candidates_clicked(self) -> None:
        if self.onu_cleanup_query_running:
            return
        try:
            connection = self._current_onu_connection()
            requests = self._build_onu_provision_requests()
        except Exception as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("无法查询离线候选", str(exc), parent=self.onu_registration_window)
            return
        if self.onu_family_var.get() != OLT_FAMILY_C300:
            return
        self.onu_cleanup_query_running = True
        self.onu_cancel_event = threading.Event()
        self._clear_c300_cleanup_candidates()
        self._set_onu_query_status("正在只读查询目标 PON 的离线 ONU...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_cleanup_candidates_worker,
            args=(connection, requests[0]),
            daemon=True,
        )
        thread.start()

    def _onu_cleanup_candidates_worker(self, connection: OltConnection, request) -> None:
        result = OnuRegistrationService(logger=self._log).query_c300_cleanup_candidates(
            connection,
            request,
            self.onu_cancel_event,
        )
        self.after(0, lambda: self._complete_onu_cleanup_candidates(result))

    def _complete_onu_cleanup_candidates(self, result) -> None:
        self.onu_cleanup_query_running = False
        self._set_onu_registration_action_buttons_state("normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        if not result.ok:
            self._set_onu_query_status(result.message, COLOR_DANGER)
            self._clear_c300_cleanup_candidates()
            return
        self.onu_c300_cleanup_candidates = tuple(result.cleanup_candidates)
        values = tuple(candidate.display_text for candidate in self.onu_c300_cleanup_candidates)
        self.onu_c300_cleanup_combo.configure(
            values=values,
            state="readonly" if values else "disabled",
        )
        self.onu_c300_cleanup_candidate_var.set("")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if values else COLOR_WARNING)
        self._invalidate_onu_preview()

    def _on_registered_candidate_selected(self, _event=None) -> None:
        has_selection = self._selected_registered_onu() is not None
        if hasattr(self, "onu_manage_delete_button"):
            self.onu_manage_delete_button.configure(
                state="normal" if has_selection else "disabled"
            )

    def _on_onu_manage_query_clicked(self) -> None:
        if self.onu_manage_query_running or self.onu_manage_delete_running:
            return
        try:
            connection = self._current_onu_connection()
            pon_interface = self._current_onu_manage_pon_interface()
        except ValueError as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("已注册管理参数错误", str(exc), parent=self.onu_registration_window)
            return
        family = self.onu_family_var.get()
        command_text = (
            "show gpon onu state（全局查询，按目标 PON 过滤）"
            if family == OLT_FAMILY_C300
            else f"show gpon onu state {pon_interface}"
        )
        confirmed = messagebox.askyesno(
            "确认查询已注册 ONU",
            f"将登录 {family} OLT 并执行只读命令：\n{command_text}\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return
        self.onu_manage_query_running = True
        self.onu_cancel_event = threading.Event()
        self._clear_registered_candidates()
        self._set_onu_query_status(f"正在只读查询 {pon_interface} 的已注册 ONU...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_manage_query_worker,
            args=(family, connection, pon_interface),
            daemon=True,
        )
        thread.start()

    def _onu_manage_query_worker(self, family, connection, pon_interface) -> None:
        result = OnuRegistrationService(logger=self._log).query_registered_candidates(
            family, connection, pon_interface, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_manage_query(family, connection.host, result))

    def _complete_onu_manage_query(self, family, host, result) -> None:
        self.onu_manage_query_running = False
        self._set_onu_registration_action_buttons_state("normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        if not result.ok:
            self._set_onu_query_status(result.message, COLOR_DANGER)
            self._clear_registered_candidates()
            return
        self.onu_registered_candidates = tuple(result.registered_onus)
        values = tuple(candidate.display_text for candidate in self.onu_registered_candidates)
        self.onu_registered_combo.configure(
            values=values,
            state="readonly" if values else "disabled",
        )
        self.onu_registered_candidate_var.set("")
        if hasattr(self, "onu_manage_delete_button"):
            self.onu_manage_delete_button.configure(state="disabled")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if values else COLOR_WARNING)
        self._log(f"[ONU注册][{family}] 查询已注册 ONU：{host} - {result.message}")

    def _on_onu_manage_delete_clicked(self) -> None:
        if self.onu_manage_delete_running or self.onu_manage_query_running:
            return
        candidate = self._selected_registered_onu()
        if candidate is None:
            self._set_onu_query_status("请先查询并明确选择一台要删除的已注册 ONU", COLOR_DANGER)
            messagebox.showwarning(
                "未选择删除目标",
                "请先在候选列表中选择一台已注册 ONU。",
                parent=self.onu_registration_window,
            )
            return
        try:
            connection = self._current_onu_connection()
        except ValueError as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("连接参数错误", str(exc), parent=self.onu_registration_window)
            return
        family = self.onu_family_var.get()
        confirmed = messagebox.askyesno(
            "确认删除 ONU（危险）",
            f"将删除 {candidate.onu_interface}（SN {candidate.serial_number or '未确认'}，状态 {candidate.state}）。\n"
            "若为在线 working ONU，删除将立即中断其业务。\n"
            "删除前会再次核对接口与 SN，且只删除这一台，删除后回读确认。\n"
            "该操作不会执行 write。是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return
        self.onu_manage_delete_running = True
        self.onu_cancel_event = threading.Event()
        self._set_onu_query_status(f"正在删除 {candidate.onu_interface}...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_manage_delete_worker,
            args=(family, connection, candidate),
            daemon=True,
        )
        thread.start()

    def _onu_manage_delete_worker(self, family, connection, candidate) -> None:
        result = OnuRegistrationService(logger=self._log).delete_registered_onu(
            family, connection, candidate, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_manage_delete(family, connection.host, result))

    def _complete_onu_manage_delete(self, family, host, result) -> None:
        self.onu_manage_delete_running = False
        self._set_onu_registration_action_buttons_state("normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"[ONU注册][{family}] 删除已注册 ONU：{host} - {result.message}")
        if result.ok:
            self._clear_registered_candidates()

    def _go_to_onu_config_step(self) -> None:
        if not self._selected_unregistered_onus():
            message = "请先在查询结果中选择要注册的 ONU"
            self._set_onu_query_status(message, COLOR_DANGER)
            messagebox.showwarning("尚未选择 ONU", message, parent=self.onu_registration_window)
            return
        self.onu_notebook.select(self.onu_config_tab)

    def _current_onu_connection(self) -> OltConnection:
        connection = OltConnection(
            host=self.onu_olt_ip_var.get().strip(),
            source_ip=self.onu_source_ip_var.get().strip(),
            username=self.onu_username_var.get().strip(),
            password=self.onu_password_var.get(),
        )
        errors = connection.validate()
        if errors:
            raise ValueError("\n".join(f"• {error}" for error in errors))
        return connection

    def _current_onu_discovery_scope(self) -> OnuDiscoveryScope:
        family = self.onu_family_var.get()
        shelf_var = self.onu_c300_shelf_var if family == OLT_FAMILY_C300 else self.onu_c600_shelf_var
        slot_var = self.onu_c300_slot_var if family == OLT_FAMILY_C300 else self.onu_c600_slot_var
        pon_var = self.onu_c300_pon_var if family == OLT_FAMILY_C300 else self.onu_c600_pon_var
        try:
            scope = OnuDiscoveryScope(
                int(shelf_var.get().strip()),
                int(slot_var.get().strip()),
                int(pon_var.get().strip()),
            )
        except ValueError as exc:
            raise ValueError(f"{family} 机框、槽位和 PON 必须是整数") from exc
        errors = scope.validate()
        if errors:
            raise ValueError("；".join(errors))
        return scope

    @staticmethod
    def _template_name_from_input(value: str) -> str:
        """Strip the read-only dropdown annotation while preserving manual input."""
        return (value or "").split("（", 1)[0].strip()

    def _build_onu_provision_requests(self):
        LineCheckAssistant._capture_onu_target_id(self)
        target_ids = getattr(self, "onu_target_id_inputs", {})
        selected_onus = self._selected_unregistered_onus()
        if not selected_onus:
            raise ValueError("请先选择要注册的 ONU")
        family = self.onu_family_var.get()
        if family == OLT_FAMILY_C300:
            if not hasattr(self, "onu_c300_services_text"):
                return build_batch_requests(
                    selected_onus,
                    OnuProvisionRequest(family=family, onu=selected_onus[0], onu_type="SD-41"),
                    target_ids=target_ids,
                )
            try:
                services = parse_service_mappings(self.onu_c300_services_text.get("1.0", "end"))
                base_request = OnuProvisionRequest(
                    family=family,
                    onu=selected_onus[0],
                    onu_id=int(self.onu_c300_onu_id_var.get().strip()),
                    onu_type=LineCheckAssistant._template_name_from_input(self.onu_c300_onu_type_var.get()),
                    tcont_id=int(self.onu_c300_tcont_id_var.get().strip()),
                    tcont_profile=LineCheckAssistant._template_name_from_input(self.onu_c300_tcont_profile_var.get()),
                    services=tuple(services),
                )
                return build_batch_requests(selected_onus, base_request, target_ids=target_ids)
            except ValueError as exc:
                raise ValueError(f"C300 参数错误：{exc}") from exc
        try:
            base_request = OnuProvisionRequest(
                family=family,
                onu=selected_onus[0],
                onu_id=int(self.onu_c600_onu_id_var.get().strip()),
                onu_type=LineCheckAssistant._template_name_from_input(self.onu_c600_onu_type_var.get()),
                real_speed=self.onu_c600_real_speed_var.get().strip(),
                tcont_id=int(self.onu_c600_tcont_id_var.get().strip()),
                tcont_profile=LineCheckAssistant._template_name_from_input(self.onu_c600_tcont_profile_var.get()),
                gemport_id=int(self.onu_c600_gemport_id_var.get().strip()),
                vport_id=int(self.onu_c600_vport_id_var.get().strip()),
                sn_bind_both=bool(self.onu_c600_sn_bind_both_var.get()),
                services=tuple(parse_service_mappings(self.onu_c600_services_text.get("1.0", "end"), allow_translation=True)),
            )
        except ValueError as exc:
            raise ValueError(f"C600 参数错误：{exc}") from exc
        return build_batch_requests(selected_onus, base_request, target_ids=target_ids)

    def _on_onu_preview_clicked(self) -> None:
        if LineCheckAssistant._onu_operation_is_running(self):
            self._set_onu_query_status("ONU 操作正在执行，请等待安全结束后再生成预览", COLOR_WARNING)
            return
        try:
            requests = self._build_onu_provision_requests()
            commands = OnuRegistrationService().build_preview(requests)
        except Exception as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("无法生成命令预览", str(exc), parent=self.onu_registration_window)
            return
        family = self.onu_family_var.get()
        target_lines = "；".join(
            f"{request.onu.display_text} → ONU ID {request.onu_id}"
            for request in requests
        )
        if family == OLT_FAMILY_C300:
            cleanup_candidate = None
            if self.onu_c300_allow_offline_cleanup_var.get():
                cleanup_candidate = self._selected_c300_cleanup_candidate()
                if cleanup_candidate is None:
                    message = "已启用危险清理，请先查询并明确选择一台同 PON 离线 ONU"
                    self._set_onu_query_status(message, COLOR_DANGER)
                    messagebox.showwarning(
                        "未选择清理目标",
                        message,
                        parent=self.onu_registration_window,
                    )
                    return
            safety_text = (
                f"仅允许失败后删除 {cleanup_candidate.onu_interface} 并重试；成功后单独询问 write"
                if cleanup_candidate
                else "首条 CLI 错误停止且不删除 ONU；成功后单独询问 write"
            )
        else:
            write_after_success = bool(self.onu_c600_write_after_success_var.get())
            safety_text = (
                "首条 CLI 错误停止；不自动删除 ONU；完整验证成功后执行 write"
                if write_after_success
                else "首条 CLI 错误停止；不自动删除 ONU；本次不执行 write"
            )
        self.onu_confirmation_summary_var.set(
            f"OLT：{family} {self.onu_olt_ip_var.get().strip() or '未填写'}　"
            f"源 IP：{self.onu_source_ip_var.get().strip() or '未填写'}\n"
            f"目标：{target_lines}\n安全策略：{safety_text}"
        )
        if family == OLT_FAMILY_C300:
            write_note = "保存策略：注册命令不含 write；成功后另行确认是否保存。"
        elif self.onu_c600_write_after_success_var.get():
            write_note = "保存策略：完整上线与只读验证成功后，在独立会话执行 write。"
        else:
            write_note = "保存策略：本次不执行 write。"
        try:
            self.onu_command_editor.load_requests(requests, write_note=write_note)
        except ValueError as exc:
            self._invalidate_onu_preview()
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("无法生成命令预览", str(exc), parent=self.onu_registration_window)
            return
        self.onu_preview_ready = True
        self.onu_register_button.configure(state="normal")
        self.onu_notebook.select(self.onu_preview_tab)
        batch_note = "；批量将先完成全体预检再逐台下发" if len(requests) > 1 else ""
        self._set_onu_query_status(f"已生成 {len(commands)} 条命令；尚未连接 OLT{batch_note}", COLOR_SUCCESS)

    def _on_onu_stop_clicked(self) -> None:
        self.onu_cancel_event.set()
        self._set_onu_query_status("正在停止 ONU 操作，等待当前安全点...", COLOR_WARNING)
        self._log(f"[ONU注册][{self.onu_family_var.get()}] 操作员请求停止")

    def _on_onu_telnet_test_clicked(self) -> None:
        if self.onu_telnet_test_running:
            return
        try:
            connection = self._current_onu_connection()
        except ValueError as exc:
            self._set_onu_telnet_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("连接参数错误", str(exc), parent=self.onu_registration_window)
            return
        family = self.onu_family_var.get()
        confirmed = messagebox.askyesno(
            "确认登录 OLT",
            f"将使用源 IP {connection.source_ip} 登录 {family} OLT。登录测试不下发配置命令。\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return

        self.onu_telnet_test_running = True
        self.onu_cancel_event = threading.Event()
        self._set_onu_telnet_status(f"正在登录 {family}：{connection.host}:23", COLOR_WARNING)
        if hasattr(self, "onu_telnet_test_button"):
            self.onu_telnet_test_button.configure(state="disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(target=self._onu_telnet_test_worker, args=(family, connection), daemon=True)
        thread.start()

    def _onu_telnet_test_worker(self, family: str, connection: OltConnection) -> None:
        result = OnuRegistrationService(logger=self._log).test_connection(
            family, connection, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_telnet_test(family, connection.host, result))

    def _complete_onu_telnet_test(self, family: str, host: str, result) -> None:
        self.onu_telnet_test_running = False
        if hasattr(self, "onu_telnet_test_button"):
            self.onu_telnet_test_button.configure(state="normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        self._set_onu_telnet_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"[ONU注册][{family}] OLT 登录测试：{host} - {result.message}")

    def _on_onu_template_query_clicked(self, kind: str) -> None:
        if self.onu_template_query_running:
            return
        family = self.onu_family_var.get()
        try:
            connection = self._current_onu_connection()
        except ValueError as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("查询参数错误", str(exc), parent=self.onu_registration_window)
            return
        kind_name = "ONU 类型模板" if kind == "onu_type" else "DBA 带宽模板"
        command = "show onu-type" if kind == "onu_type" else "show gpon profile tcont"
        confirmed = messagebox.askyesno(
            f"确认查询{kind_name}",
            f"将登录 {family} OLT 并执行只读命令：\n{command}\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return
        self.onu_template_query_running = True
        self.onu_cancel_event = threading.Event()
        self._set_onu_query_status(f"正在查询 {family} {kind_name}...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_template_query_worker,
            args=(family, connection, kind),
            daemon=True,
        )
        thread.start()

    def _onu_template_query_worker(self, family: str, connection: OltConnection, kind: str) -> None:
        result = OnuRegistrationService(logger=self._log).query_templates(
            family, connection, kind, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_template_query(family, connection.host, kind, result))

    def _complete_onu_template_query(self, family: str, host: str, kind: str, result) -> None:
        self.onu_template_query_running = False
        self._set_onu_registration_action_buttons_state("normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        kind_name = "ONU 类型模板" if kind == "onu_type" else "DBA 带宽模板"
        if result.ok:
            combo = getattr(self, f"onu_{family.lower()}_{kind}_combo", None)
            if combo is not None:
                combo.configure(values=tuple(template.display_text for template in result.templates))
            self._set_onu_query_status(result.message, COLOR_SUCCESS if result.templates else COLOR_WARNING)
        else:
            self._set_onu_query_status(result.message, COLOR_DANGER)
        self._log(f"[ONU注册][{family}] 查询{kind_name}：{host} - {result.message}")

    def _on_onu_query_unregistered_clicked(self) -> None:
        if self.onu_query_running:
            return
        family = self.onu_family_var.get()
        try:
            connection = self._current_onu_connection()
            scope = self._current_onu_discovery_scope()
        except ValueError as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("查询参数错误", str(exc), parent=self.onu_registration_window)
            return
        if family == OLT_FAMILY_C300:
            command_text = "show gpon onu uncfg"
        elif scope.is_all_olt:
            command_text = "show pon onu uncfg sn model speed-mode"
        else:
            command_text = f"show pon onu uncfg gpon_olt-{scope.shelf}/{scope.slot}/{scope.pon} sn model speed-mode"
        scope_text = "整台 OLT" if scope.is_all_olt else f"机框 {scope.shelf} / 槽位 {scope.slot} / PON {scope.pon}"
        confirmed = messagebox.askyesno(
            "确认查询未注册 ONU",
            f"范围：{scope_text}\n将登录 {family} OLT 并执行只读命令：\n{command_text}\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return

        self.onu_query_running = True
        self.onu_cancel_event = threading.Event()
        self._set_onu_query_status(f"正在查询 {family} 未注册 ONU...", COLOR_WARNING)
        self._render_unregistered_onu_selection([])
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_query_unregistered_worker,
            args=(family, connection, scope),
            daemon=True,
        )
        thread.start()

    def _onu_query_unregistered_worker(self, family: str, connection: OltConnection, scope: OnuDiscoveryScope) -> None:
        result = OnuRegistrationService(logger=self._log).query_unregistered(
            family, connection, scope, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_query_unregistered(family, connection.host, result))

    def _complete_onu_query_unregistered(self, family: str, host: str, result) -> None:
        self.onu_query_running = False
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        if result.ok:
            message = f"查询到 {len(result.onus)} 个未注册 ONU，请选择要注册的 ONU" if result.onus else result.message
            self._set_onu_query_status(message, COLOR_SUCCESS)
            self._render_unregistered_onu_selection(result.onus)
        else:
            self._set_onu_query_status(result.message, COLOR_DANGER)
            self._render_unregistered_onu_selection([])
        self._log(f"[ONU注册][{family}] 查询未注册 ONU：{host} - {result.message}")

    def _on_onu_register_selected_clicked(self) -> bool:
        if LineCheckAssistant._onu_operation_is_running(self):
            return False
        if hasattr(self, "onu_preview_ready") and not self.onu_preview_ready:
            message = "命令预览已失效，请返回配置业务并重新生成命令预览后再开始注册"
            self._set_onu_query_status(message, COLOR_DANGER)
            messagebox.showwarning("预览已失效", message, parent=self.onu_registration_window)
            return False
        try:
            connection = self._current_onu_connection()
            requests = self._build_onu_provision_requests()
            if tuple(requests) != self.onu_command_editor.requests:
                self._invalidate_onu_preview()
                raise ValueError("参数或目标已变化，请重新生成命令预览后再开始注册")
            command_plans = self.onu_command_editor.capture_plans()
            commands = tuple(command for plan in command_plans for command in plan.commands)
        except Exception as exc:
            self._set_onu_query_status(str(exc), COLOR_DANGER)
            messagebox.showwarning("注册参数错误", str(exc), parent=self.onu_registration_window)
            return False
        family = self.onu_family_var.get()
        write_var = getattr(self, "onu_c600_write_after_success_var", None)
        write_after_success = (
            family == OLT_FAMILY_C600
            and write_var is not None
            and bool(write_var.get())
        )
        onu_lines = "\n".join(
            f"- {request.onu.display_text} → ONU ID {request.onu_id}"
            for request in requests
        )
        cleanup_candidate = (
            self._selected_c300_cleanup_candidate()
            if family == OLT_FAMILY_C300 and bool(self.onu_c300_allow_offline_cleanup_var.get())
            else None
        )
        if family == OLT_FAMILY_C300 and self.onu_c300_allow_offline_cleanup_var.get() and cleanup_candidate is None:
            message = "危险清理已启用，但未明确选择同 PON 离线 ONU"
            self._set_onu_query_status(message, COLOR_DANGER)
            messagebox.showwarning("未选择清理目标", message, parent=self.onu_registration_window)
            return False
        if family == OLT_FAMILY_C300 and len(requests) > 1 and cleanup_candidate is not None:
            message = "批量注册不允许离线 ONU 清理重试；请关闭危险清理或改为单台注册"
            self._set_onu_query_status(message, COLOR_DANGER)
            messagebox.showwarning("批量注册安全限制", message, parent=self.onu_registration_window)
            return False
        cleanup_text = (
            "\nC300 危险策略：仅当配置失败且状态复核仍为离线时，删除 "
            f"{cleanup_candidate.display_text} 后重试。"
            if cleanup_candidate
            else "\n失败处理：遇到第一条 CLI 错误立即停止，不删除 ONU。"
        )
        confirmed = messagebox.askyesno(
            "确认注册 ONU",
            f"OLT 型号：{family}\n源 IP：{connection.source_ip}\n目标：\n{onu_lines}\n"
            f"共 {len(commands)} 条注册配置命令，按本次已校验快照执行。\n"
            + "\n".join(command_plan_summary(plan) for plan in command_plans)
            + f"{cleanup_text}\n"
            + (
                "完整上线与只读验证成功后还会执行 write，保存整台 OLT 当前运行配置。是否继续？"
                if write_after_success
                else "该操作会修改 OLT 当前运行配置，本次不会执行 write。是否继续？"
            ),
            parent=self.onu_registration_window,
        )
        if not confirmed:
            self._log(f"[ONU注册][{family}] 操作员取消命令快照确认，跳过注册")
            return False

        self._log(f"[ONU注册][{family}] 已确认 {len(command_plans)} 个目标、{len(commands)} 条命令快照，按本次业务参数回读验证")
        self.onu_register_running = True
        self.onu_cancel_event = threading.Event()
        self._set_onu_query_status(f"正在注册 {len(requests)} 个 {family} ONU...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(
            target=self._onu_register_selected_worker,
            args=(
                family,
                connection,
                requests,
                cleanup_candidate,
                write_after_success,
                command_plans,
            ),
            daemon=True,
        )
        thread.start()
        return True

    def _onu_register_selected_worker(
        self,
        family: str,
        connection: OltConnection,
        requests,
        cleanup_candidate,
        write_after_success: bool,
        command_plans=None,
    ) -> None:
        result = OnuRegistrationService(logger=self._log).register(
            connection,
            requests,
            c300_cleanup_candidate=cleanup_candidate,
            cancel_event=self.onu_cancel_event,
            command_plans=command_plans,
        )
        self.after(
            0,
            lambda: self._complete_onu_register_selected(
                family, connection, result, write_after_success
            ),
        )

    def _complete_onu_register_selected(
        self,
        family: str,
        connection: OltConnection,
        result,
        write_after_success: bool = False,
    ) -> None:
        self.onu_register_running = False
        self._set_onu_registration_action_buttons_state("normal" if self.onu_unregistered_selection_vars else "disabled")
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"[ONU注册][{family}] 注册结果：{connection.host} - {result.message}")
        if not result.ok:
            _finish_pipeline_subtask_if_waiting(self, "onu_registration", False, result.message)
            return
        if family == OLT_FAMILY_C600:
            if not write_after_success:
                messagebox.showinfo(
                    "C600 注册与验证完成",
                    "C600 ONU 注册、业务配置及只读验证已经执行。\n本次未选择 write，当前运行配置尚未写入启动配置。",
                    parent=self.onu_registration_window,
                )
                _finish_pipeline_subtask_if_waiting(self, "onu_registration", True, result.message)
                return
            confirmed = True
        else:
            confirmed = messagebox.askyesno(
                "保存 OLT 最新配置",
                "ONU 注册配置已下发到 OLT 当前运行配置。\n是否执行 write，将最新配置写入启动配置？",
                parent=self.onu_registration_window,
            )
        if not confirmed:
            self._log(f"[ONU注册][{family}] 保存 OLT 配置：{connection.host} - 用户选择暂不保存")
            _finish_pipeline_subtask_if_waiting(self, "onu_registration", True, result.message)
            return

        self.onu_save_olt_running = True
        self._set_onu_query_status("正在执行 write 保存 OLT 最新配置...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        self.onu_cancel_event = threading.Event()
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="normal")
        thread = threading.Thread(target=self._onu_save_olt_configuration_worker, args=(family, connection), daemon=True)
        thread.start()

    def _onu_save_olt_configuration_worker(self, family: str, connection: OltConnection) -> None:
        result = OnuRegistrationService(logger=self._log).save_configuration(
            family, connection, self.onu_cancel_event
        )
        self.after(0, lambda: self._complete_onu_save_olt_configuration(family, connection.host, result))

    def _complete_onu_save_olt_configuration(self, family: str, host: str, result) -> None:
        self.onu_save_olt_running = False
        self._set_onu_registration_action_buttons_state("normal" if self.onu_unregistered_selection_vars else "disabled")
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        if hasattr(self, "onu_stop_button"):
            self.onu_stop_button.configure(state="disabled")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"[ONU注册][{family}] 保存 OLT 配置：{host} - {result.message}")
        _finish_pipeline_subtask_if_waiting(self, "onu_registration", result.ok, result.message)

    def _set_onu_telnet_status(self, message: str, foreground: str = COLOR_TEXT) -> None:
        self.onu_telnet_status_var.set(message)
        if hasattr(self, "onu_status_label"):
            self.onu_status_label.configure(foreground=foreground)

    def _set_onu_query_status(self, message: str, foreground: str = COLOR_TEXT) -> None:
        self.onu_query_status_var.set(message)
        if hasattr(self, "onu_query_status_label"):
            self.onu_query_status_label.configure(foreground=foreground)

    def _render_unregistered_onu_selection(self, onus) -> None:
        self.onu_target_id_inputs = {}
        self.onu_active_id_target = None
        if not hasattr(self, "onu_unregistered_list_frame"):
            self.onu_unregistered_selection_vars = []
            return
        for child in self.onu_unregistered_list_frame.winfo_children():
            child.destroy()
        self.onu_unregistered_selection_vars = []
        self.onu_c600_selection_var.set("")
        self._invalidate_onu_preview()
        if not onus:
            Label(
                self.onu_unregistered_list_frame,
                text="未查询到可选择的未注册 ONU",
                anchor="w",
                background=COLOR_SURFACE_SUBTLE,
                foreground=COLOR_MUTED,
            ).pack(fill="x", anchor="w")
            self._set_unregistered_onu_selection_buttons_state("disabled")
            return

        family = self.onu_family_var.get()
        for index, onu in enumerate(onus):
            variable = BooleanVar(value=False)
            text = getattr(onu, "display_text", "") or (
                f"{onu.onu_index}  SN:{onu.serial_number}  状态:{onu.state}"
            )
            if family == OLT_FAMILY_C600:
                command = lambda current_onu=onu, current_var=variable: self._on_c600_onu_selected(
                    current_onu, current_var
                )
            else:
                command = lambda current_onu=onu, current_var=variable: self._on_onu_selection_toggled(
                    current_onu, current_var
                )
            Checkbutton(
                self.onu_unregistered_list_frame,
                text=text,
                variable=variable,
                command=command,
                background=COLOR_SURFACE_SUBTLE,
                activebackground=COLOR_SURFACE_SUBTLE,
                selectcolor="#ffffff",
                anchor="w",
            ).pack(fill="x", anchor="w")
            self.onu_unregistered_selection_vars.append((onu, variable))
        self._set_unregistered_onu_selection_buttons_state("normal")

    def _set_unregistered_onu_selection_buttons_state(self, state: str) -> None:
        if hasattr(self, "onu_select_all_button"):
            self.onu_select_all_button.configure(state=state)
        if hasattr(self, "onu_clear_selection_button"):
            self.onu_clear_selection_button.configure(state=state)
        if hasattr(self, "onu_next_config_button"):
            self.onu_next_config_button.configure(state="disabled")
        if hasattr(self, "onu_preview_button"):
            self.onu_preview_button.configure(state="disabled")
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(state="disabled")

    def _set_onu_registration_action_buttons_state(self, state: str) -> None:
        editor = getattr(self, "onu_command_editor", None)
        if editor is not None:
            editor.set_busy(state != "normal")
        if hasattr(self, "onu_select_all_button"):
            self.onu_select_all_button.configure(state=state)
        if hasattr(self, "onu_clear_selection_button"):
            self.onu_clear_selection_button.configure(state=state)
        if hasattr(self, "onu_next_config_button"):
            self.onu_next_config_button.configure(state=state)
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(
                state=state if getattr(self, "onu_preview_ready", False) else "disabled"
            )
        if hasattr(self, "onu_preview_button"):
            self.onu_preview_button.configure(state=state)
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state=state)
        if hasattr(self, "onu_telnet_test_button"):
            self.onu_telnet_test_button.configure(state=state)
        for family in ("c300", "c600"):
            for kind in ("onu_type", "dba"):
                button = getattr(self, f"onu_{family}_{kind}_query_button", None)
                if button is not None:
                    button.configure(state=state)
        if hasattr(self, "onu_family_combo"):
            self.onu_family_combo.configure(state="readonly" if state == "normal" else "disabled")
        if hasattr(self, "onu_c300_cleanup_query_button"):
            cleanup_enabled = (
                state == "normal"
                and self.onu_family_var.get() == OLT_FAMILY_C300
                and bool(self.onu_c300_allow_offline_cleanup_var.get())
            )
            self.onu_c300_cleanup_query_button.configure(
                state="normal" if cleanup_enabled else "disabled"
            )
        if hasattr(self, "onu_c300_cleanup_combo"):
            cleanup_selectable = (
                state == "normal"
                and bool(self.onu_c300_allow_offline_cleanup_var.get())
                and bool(self.onu_c300_cleanup_candidates)
            )
            self.onu_c300_cleanup_combo.configure(
                state="readonly" if cleanup_selectable else "disabled"
            )
        if hasattr(self, "onu_manage_query_button"):
            self.onu_manage_query_button.configure(state=state)
        if hasattr(self, "onu_registered_combo"):
            self.onu_registered_combo.configure(
                state="readonly"
                if state == "normal" and self.onu_registered_candidates
                else "disabled"
            )
        if hasattr(self, "onu_manage_delete_button"):
            delete_enabled = state == "normal" and self._selected_registered_onu() is not None
            self.onu_manage_delete_button.configure(
                state="normal" if delete_enabled else "disabled"
            )

    def _selected_unregistered_onus(self):
        return [onu for onu, variable in self.onu_unregistered_selection_vars if variable.get()]

    def _select_all_unregistered_onus(self) -> None:
        LineCheckAssistant._capture_onu_target_id(self)
        self.onu_active_id_target = None
        for index, (onu, variable) in enumerate(self.onu_unregistered_selection_vars):
            variable.set(True)
            if index == 0 and self.onu_family_var.get() == OLT_FAMILY_C600:
                self._fill_c600_from_discovered_onu(onu)
        self._invalidate_onu_preview()
        self._refresh_onu_selection_action_state()

    def _clear_unregistered_onu_selection(self) -> None:
        LineCheckAssistant._capture_onu_target_id(self)
        self.onu_active_id_target = None
        for _onu, variable in self.onu_unregistered_selection_vars:
            variable.set(False)
        self.onu_c600_selection_var.set("")
        self._invalidate_onu_preview()
        self._refresh_onu_selection_action_state()

    def _on_c600_onu_selected(self, onu, variable) -> None:
        self._on_onu_selection_toggled(onu, variable)
        self.onu_notebook.select(self.onu_config_tab)

    def _on_onu_selection_toggled(self, onu, variable) -> None:
        # 原生 Checkbutton 支持一批目标；配置页仍使用同一业务模板。
        LineCheckAssistant._capture_onu_target_id(self)
        self.onu_active_id_target = None
        if variable.get():
            id_var = getattr(self, f"onu_{self.onu_family_var.get().lower()}_onu_id_var", None)
            if id_var is not None:
                saved_id = getattr(self, "onu_target_id_inputs", {}).get(onu)
                if saved_id is not None:
                    id_var.set(saved_id)
                elif getattr(onu, "suggested_onu_id", None):
                    id_var.set(str(onu.suggested_onu_id))
                self.onu_active_id_initial_value = id_var.get().strip()
                self.onu_active_id_target = onu
            if self.onu_family_var.get() == OLT_FAMILY_C600:
                self._fill_c600_from_discovered_onu(onu)
            else:
                self._clear_c300_cleanup_candidates()
        self._invalidate_onu_preview()
        self._refresh_onu_selection_action_state()

    def _capture_onu_target_id(self) -> None:
        """Collect the shared entry for its current ONU before changing targets."""
        target = getattr(self, "onu_active_id_target", None)
        if target is None or target.family != self.onu_family_var.get():
            return
        variable = getattr(self, f"onu_{target.family.lower()}_onu_id_var", None)
        if variable is not None:
            if not hasattr(self, "onu_target_id_inputs"):
                self.onu_target_id_inputs = {}
            value = variable.get().strip()
            if target in self.onu_target_id_inputs or value != getattr(self, "onu_active_id_initial_value", None):
                self.onu_target_id_inputs[target] = value

    def _refresh_onu_selection_action_state(self) -> None:
        has_selection = bool(self._selected_unregistered_onus()) and not LineCheckAssistant._onu_operation_is_running(self)
        state = "normal" if has_selection else "disabled"
        if hasattr(self, "onu_next_config_button"):
            self.onu_next_config_button.configure(state=state)
        if hasattr(self, "onu_preview_button"):
            self.onu_preview_button.configure(state=state)
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(
                state="normal" if has_selection and self.onu_preview_ready else "disabled"
            )

    def _fill_c600_from_discovered_onu(self, onu) -> None:
        if getattr(onu, "model", ""):
            self.onu_c600_onu_type_var.set(onu.model)
        if getattr(onu, "speed_mode", ""):
            self.onu_c600_real_speed_var.set(speed_mode_to_cli(onu.speed_mode))
        self._set_onu_query_status(
            f"已选择 {onu.display_text}；请进入“2. 配置业务”核对 ONU ID、模板和业务映射",
            COLOR_SUCCESS,
        )

    def _toggle_onu_password_visibility(self) -> None:
        self.onu_password_visible = not self.onu_password_visible
        self.onu_password_entry.configure(show="" if self.onu_password_visible else "*")
        self.onu_password_toggle.configure(relief="sunken" if self.onu_password_visible else "raised")

    def _open_upgrade_module(self) -> None:
        if self.upgrade_window is not None and self.upgrade_window.winfo_exists():
            self._refresh_upgrade_targets()
            self.upgrade_window.deiconify()
            self.upgrade_window.lift()
            self.upgrade_window.focus_force()
            return

        dialog = Toplevel(self)
        self.upgrade_window = dialog
        dialog.title("样机升级")
        window_width, window_height = self._restore_module_window_size(
            dialog, "sample_upgrade"
        )
        dialog.minsize(820, 620)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        Label(content, text="样机升级", font=(FONT_FAMILY, 18, "bold"), background=COLOR_BG, foreground=COLOR_TEXT).pack(anchor="w")
        Label(
            content,
            text="选择升级方式、升级固件和目标样机。页面升级会通过 UBUS 批量执行。",
            foreground=COLOR_MUTED,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(6, 16))

        overview = ttk.LabelFrame(content, text="升级配置")
        overview.pack(fill="x")

        Label(overview, text="升级方式", anchor="w").grid(row=0, column=0, sticky="w", padx=(12, 8), pady=8)
        mode_options = ttk.Frame(overview)
        mode_options.grid(row=0, column=1, sticky="w", padx=(0, 18), pady=8)
        for mode in UPGRADE_MODE_OPTIONS:
            ttk.Radiobutton(
                mode_options,
                text=mode,
                value=mode,
                variable=self.upgrade_mode_var,
                command=self._refresh_upgrade_transfer_visibility,
            ).pack(side="left", padx=(0, 18))

        self.upgrade_transfer_label = Label(overview, text="固件传输方式", anchor="w")
        self.upgrade_transfer_label.grid(row=1, column=0, sticky="w", padx=(12, 8), pady=8)
        self.upgrade_transfer_combo = ttk.Combobox(
            overview,
            textvariable=self.upgrade_transfer_var,
            values=UPGRADE_TRANSFER_OPTIONS,
            state="readonly",
            width=22,
        )
        self.upgrade_transfer_combo.grid(row=1, column=1, sticky="w", padx=(0, 18), pady=8)
        self.upgrade_transfer_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_upgrade_transfer_visibility())
        self.upgrade_parallel_count_label = Label(
            overview,
            text=f"并行数 (1-{MAX_PARALLEL_UPGRADES})",
            anchor="w",
        )
        self.upgrade_parallel_count_label.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=8)
        self.upgrade_parallel_count_spin = ttk.Spinbox(
            overview,
            from_=1,
            to=MAX_PARALLEL_UPGRADES,
            textvariable=self.upgrade_parallel_count_var,
            width=5,
        )
        self.upgrade_parallel_count_spin.grid(row=1, column=3, sticky="w", padx=(0, 12), pady=8)
        self.upgrade_restore_factory_label = Label(
            overview,
            textvariable=self.upgrade_restore_factory_text_var,
            anchor="w",
            cursor="hand2",
        )
        self.upgrade_restore_factory_label.grid(row=0, column=2, columnspan=2, sticky="w", padx=(0, 12), pady=8)
        self.upgrade_restore_factory_label.bind("<Button-1>", self._toggle_upgrade_restore_factory)

        Label(overview, text="超级用户名", anchor="w").grid(row=3, column=0, sticky="w", padx=(12, 8), pady=8)
        ttk.Entry(overview, textvariable=self.upgrade_username_var).grid(
            row=3, column=1, sticky="ew", padx=(0, 18), pady=8
        )
        Label(overview, text="密码", anchor="w").grid(row=3, column=2, sticky="w", padx=(0, 8), pady=8)
        password_container = Frame(overview, background=COLOR_SURFACE)
        password_container.grid(row=3, column=3, columnspan=2, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_password_entry = ttk.Entry(password_container, textvariable=self.upgrade_password_var, show="*")
        self.upgrade_password_entry.pack(side="left", fill="x", expand=True)
        self.upgrade_password_toggle = Button(
            password_container,
            text="👁",
            width=3,
            command=self._toggle_upgrade_password_visibility,
        )
        self.upgrade_password_toggle.pack(side="right", padx=(5, 0))

        Label(overview, text="升级固件", anchor="w").grid(row=4, column=0, sticky="w", padx=(12, 8), pady=8)
        ttk.Entry(overview, textvariable=self.upgrade_firmware_var, state="readonly").grid(
            row=4, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=8
        )
        Button(overview, text="选择固件...", command=self._select_upgrade_firmware).grid(
            row=4, column=4, sticky="e", padx=(0, 12), pady=8
        )

        Label(overview, text="目标样机", anchor="w").grid(row=5, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_targets_var,
            foreground=COLOR_TEXT,
            anchor="w",
            justify="left",
            wraplength=590,
        ).grid(row=5, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=8)

        Label(overview, text="执行状态", anchor="w").grid(row=6, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_status_var,
            foreground=COLOR_TEXT,
            anchor="w",
        ).grid(row=6, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_progress = ttk.Progressbar(
            overview,
            variable=self.upgrade_progress_var,
            maximum=100,
            mode="determinate",
        )
        self.upgrade_progress.grid(row=7, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=(0, 10))
        self.upgrade_boot_entry_label = Label(overview, text="进入 Boot 方式", anchor="w")
        self.upgrade_boot_entry_label.grid(row=2, column=0, sticky="w", padx=(12, 8), pady=8)
        self.upgrade_boot_entry_combo = ttk.Combobox(
            overview, textvariable=self.upgrade_boot_entry_var,
            values=BOOT_ENTRY_OPTIONS, state="readonly", width=22,
        )
        self.upgrade_boot_entry_combo.grid(row=2, column=1, sticky="w", padx=(0, 18), pady=8)
        overview.columnconfigure(1, weight=1)
        overview.columnconfigure(3, weight=1)
        self._refresh_upgrade_transfer_visibility()
        self._refresh_upgrade_targets()

        Label(
            content,
            text="页面升级会上传固件并触发设备升级；全包升级会使用内置 pySerial 串口状态机与 TFTPy 传输固件。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(16, 0))

        def close_dialog() -> None:
            try:
                self._cancel_pending_sample_upgrade_save()
                self._save_sample_upgrade_settings()
            except Exception:
                pass
            finally:
                self._remember_module_window_size(dialog, "sample_upgrade")
                dialog.destroy()
                self.upgrade_window = None

        buttons = Frame(content, background=COLOR_BG)
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        ttk.Button(buttons, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(side="right")
        self.upgrade_stop_button = ttk.Button(buttons, text="停止升级", width=12, command=self._stop_sample_upgrade, style="Secondary.TButton")
        self.upgrade_stop_button.pack(side="right", padx=(0, 8))
        self.upgrade_start_button = ttk.Button(buttons, text="开始升级", width=12, command=self._on_upgrade_start_clicked, style="Primary.TButton")
        self.upgrade_start_button.pack(side="right", padx=(0, 8))
        self._refresh_upgrade_buttons()
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        center_toplevel_on_parent(
            dialog, self, window_width=window_width, window_height=window_height
        )

    def _toggle_upgrade_restore_factory(self, _event=None) -> str:
        self.upgrade_restore_factory_var.set(not self.upgrade_restore_factory_var.get())
        self._refresh_upgrade_restore_factory_text()
        return "break"

    def _refresh_upgrade_restore_factory_text(self) -> None:
        if not hasattr(self, "upgrade_restore_factory_text_var"):
            return
        self.upgrade_restore_factory_text_var.set(LineCheckAssistant._restore_factory_text(bool(self.upgrade_restore_factory_var.get())))

    @staticmethod
    def _restore_factory_text(enabled: bool) -> str:
        marker = "☑" if enabled else "☐"
        return f"{marker} 恢复出厂"

    def _refresh_upgrade_transfer_visibility(self) -> None:
        if not hasattr(self, "upgrade_transfer_label") or not hasattr(self, "upgrade_transfer_combo"):
            return
        current_transfer = LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())
        if current_transfer != self.upgrade_transfer_var.get():
            self.upgrade_transfer_var.set(current_transfer)
        if current_transfer not in UPGRADE_TRANSFER_OPTIONS:
            self.upgrade_transfer_var.set(UPGRADE_TRANSFER_OPTIONS[0])
        if self.upgrade_mode_var.get() == "全包升级":
            self.upgrade_transfer_label.grid()
            self.upgrade_transfer_combo.grid()
        else:
            self.upgrade_transfer_label.grid_remove()
            self.upgrade_transfer_combo.grid_remove()

        for name in ("upgrade_boot_entry_label", "upgrade_boot_entry_combo"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.grid() if self.upgrade_mode_var.get() == "全包升级" else widget.grid_remove()
        self._refresh_upgrade_parallel_count_visibility()

    def _refresh_upgrade_parallel_count_visibility(self) -> None:
        """仅全包升级显示可编辑的并行数。"""
        if not hasattr(self, "upgrade_parallel_count_label") or not hasattr(self, "upgrade_parallel_count_spin"):
            return
        show = self.upgrade_mode_var.get() == "全包升级"
        if show:
            self.upgrade_parallel_count_label.grid()
            self.upgrade_parallel_count_spin.grid()
            self.upgrade_parallel_count_spin.state(["!disabled"])
        else:
            self.upgrade_parallel_count_label.grid_remove()
            self.upgrade_parallel_count_spin.grid_remove()
            self.upgrade_parallel_count_spin.state(["disabled"])

    def _refresh_upgrade_buttons(self) -> None:
        run = getattr(self, "_sample_upgrade_run", None)
        running = bool(getattr(self, "sample_upgrade_running", False))
        stopping = bool(run and run.control.is_set())
        for name, enabled in (("upgrade_start_button", not running), ("upgrade_stop_button", running and not stopping)):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state="normal" if enabled else "disabled")
                except TclError:
                    pass

    def _launch_upgrade_run(self, worker, args) -> bool:
        if getattr(self, "sample_upgrade_running", False):
            self._log("样机升级仍在运行或正在停止，未启动重复批次。")
            return False
        run = UpgradeRun(pipeline_owned="sample_upgrade" in getattr(self, "_pipeline_subtask_events", {}))
        self._sample_upgrade_run = run
        pipeline = getattr(self, "pipeline_window", None)
        if run.pipeline_owned and pipeline and getattr(pipeline, "_stop_requested", False):
            run.control.request_stop()
        self.sample_upgrade_running = True
        LineCheckAssistant._refresh_upgrade_buttons(self)

        run.thread = threading.Thread(target=worker, args=args, kwargs={"run": run}, daemon=True)
        try:
            run.thread.start()
        except Exception as exc:
            LineCheckAssistant._finish_upgrade_run(self, run, [], str(exc))
            raise
        if callable(getattr(self, "after", None)):
            self.after(50, lambda: LineCheckAssistant._drain_upgrade_ui(self, run))
        return True

    def _post_upgrade_ui(self, run, action) -> None:
        if run is None:
            self.after(0, action)
        else:
            run.ui_queue.put(action)

    def _drain_upgrade_ui(self, run) -> None:
        if getattr(self, "_sample_upgrade_run", None) is not run:
            return
        while not run.ui_queue.empty():
            run.ui_queue.get_nowait()()
        if not run.finished:
            self.after(50, lambda: LineCheckAssistant._drain_upgrade_ui(self, run))

    def _stop_sample_upgrade(self, from_pipeline=False) -> None:
        run = getattr(self, "_sample_upgrade_run", None)
        if run is None or run.finished or run.control.is_set():
            return
        if from_pipeline and not run.pipeline_owned:
            return
        run.control.request_stop()
        self._log("[样机升级] 已请求停止：排队任务跳过；已开始的传输/刷写等待安全边界，不再发起重试、重启或恢复出厂。")
        self.upgrade_status_var.set("正在停止，等待当前传输或设备操作安全收尾……")
        LineCheckAssistant._refresh_upgrade_buttons(self)
        if run.pipeline_owned and not from_pipeline:
            window = getattr(self, "pipeline_window", None)
            if window is not None:
                window.request_stop()

    def _finish_upgrade_run(self, run, results, error=None) -> bool:
        if getattr(self, "_sample_upgrade_run", None) is not run or run.finished:
            return True
        if run.thread is not None and run.thread.is_alive():
            # Queue completion only after the worker's finally blocks and COM cleanup.
            self.after(50, lambda: LineCheckAssistant._finish_upgrade_run(self, run, results, error))
            return True
        run.finished = True
        self.sample_upgrade_running = False
        terminal = getattr(self, "serial_terminal", None)
        if terminal is not None:
            try:
                terminal.finish_upgrade_logs()
            except Exception as exc:
                self._log(f"[样机升级] 串口日志界面收尾失败：{exc}")
        LineCheckAssistant._refresh_upgrade_buttons(self)
        stopped = run.control.is_set() or any(isinstance(item.result, UpgradeStoppedResult) for item in results)
        if stopped or error:
            summary = summarize_results(results)
            detail = summary + (f"；异常：{error}" if error else "")
            title = "样机升级已停止" if stopped else "样机升级失败"
            self._set_upgrade_status("", title + "：" + detail, self.upgrade_progress_var.get())
            self._log(title + "：" + detail)
            LineCheckAssistant._report_sample_upgrade_completion(self, title, detail, "warning" if stopped else "error")
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, title + "：" + detail)
            return True
        return False

    def _on_upgrade_start_clicked(self) -> None:
        if getattr(self, "sample_upgrade_running", False):
            self._log("样机升级仍在运行或正在停止，请等待当前批次释放资源。")
            return False
        self._capture_current_channel()
        if not self._validate_upgrade_required_fields():
            return
        transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())
        if self.upgrade_mode_var.get() == "全包升级" and transfer_method in SERIAL_FULL_PACKAGE_TRANSFERS:
            self._start_full_package_upgrade()
            return
        if self.upgrade_mode_var.get() == "页面升级":
            self._start_page_upgrade()
            return

        vlans = self._selected_upgrade_vlans()
        if not vlans:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选通道并配置对应 VLAN。", parent=self.upgrade_window)
            return
        self._open_serial_log_module(vlans)
        self._set_upgrade_status("", f"已打开 {len(vlans)} 个内置串口监控，未下发升级命令", 0)
        messagebox.showinfo("串口日志已启动", "已打开内置串口监控，当前未下发升级命令。", parent=self.upgrade_window)

    def _start_page_upgrade(self, skip_confirmation: bool = False) -> bool:
        if getattr(self, "sample_upgrade_running", False):
            self._log("样机升级仍在运行或正在停止，请等待当前批次释放资源。")
            return False
        channels = self._selected_page_upgrade_channels()
        if not channels:
            return False
        firmware_path = Path(self.upgrade_firmware_var.get().strip())
        if not firmware_path.is_file():
            messagebox.showwarning("未选择升级固件", "请先选择需要升级的固件文件。", parent=self.upgrade_window)
            return False

        requests: list[PageUpgradeRequest] = []
        for channel in channels:
            vlan_name = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            device_ip = (channel.device_manage_ip or self.device_ip_var.get().strip()).strip()
            bind_ip = channel.network_card_ip.strip()
            if not bind_ip:
                try:
                    bind_ip = self._tftp_server_ip_for_channel(channel)
                except ValueError as exc:
                    messagebox.showwarning("绑定 IP 不正确", str(exc), parent=self.upgrade_window)
                    return False
            if not device_ip:
                messagebox.showwarning("样机 IP 不完整", f"{channel.label} 未配置样机 IP。", parent=self.upgrade_window)
                return False
            requests.append(
                PageUpgradeRequest(
                    vlan=vlan_name.lower() if vlan_name.lower().startswith("vlan") else vlan_name,
                    adapter_alias=channel.adapter_alias or vlan_name,
                    bind_ip=bind_ip,
                    device_ip=device_ip,
                    username=self.upgrade_username_var.get().strip(),
                    password=self.upgrade_password_var.get().strip(),
                    firmware_path=firmware_path,
                    subnet_mask=channel.subnet_mask or DEFAULT_SUBNET_MASK,
                    restore_factory=bool(self.upgrade_restore_factory_var.get()),
                )
            )

        target_text = "、".join(request.vlan or request.device_ip for request in requests)
        restore_factory_text = (
            "开启，升级成功、设备重启并重新登录成功后将通过 UBUS 执行恢复出厂"
            if bool(self.upgrade_restore_factory_var.get())
            else "关闭，不会执行恢复出厂"
        )
        if not skip_confirmation:
            if not messagebox.askyesno(
                "确认页面升级",
                f"将通过 UBUS 页面升级并行升级 {len(requests)} 台样机：{target_text}\n\n"
                f"该操作会上传固件、触发升级并等待设备重启上线。\n恢复出厂：{restore_factory_text}\n\n是否继续？",
                parent=self.upgrade_window,
            ):
                return False
        else:
            self._log("[全流程][无人值守] 已使用总确认授权，跳过页面升级子任务确认。")

        self._set_upgrade_status("", f"准备页面升级 {len(requests)} 台样机", 0)
        return LineCheckAssistant._launch_upgrade_run(self, self._page_upgrade_worker, (requests,))

    def _selected_page_upgrade_channels(self) -> list[ChannelConfig]:
        channels_by_vlan: dict[str, ChannelConfig] = {}
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if vlan and vlan.lower() not in channels_by_vlan:
                channels_by_vlan[vlan.lower()] = channel
        channels = list(channels_by_vlan.values())
        if not channels:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选至少 1 个通道并配置对应 VLAN。", parent=self.upgrade_window)
            return []
        return channels

    def _page_upgrade_worker(self, requests: list[PageUpgradeRequest], run=None) -> None:
        total = len(requests)
        completed = 0

        def on_item_complete(item_result) -> None:
            nonlocal completed
            completed += 1
            progress = (completed / total) * 100 if total else 100
            stage = ("页面升级" + result_state(item_result.result)) if isinstance(item_result.result, UpgradeStoppedResult) else ("页面升级完成" if item_result.result.ok else "页面升级失败")
            LineCheckAssistant._post_upgrade_ui(self, run, lambda request=item_result.request, stage=stage, progress=progress: self._set_upgrade_status(request.vlan, stage, progress))
            self.log_queue.put(item_result.result.message)

        self.log_queue.put(f"开始 UBUS 页面升级，共 {total} 台样机。")
        try:
            results = run_page_upgrade_batch(
                requests,
                on_output=lambda line: self.log_queue.put(line),
                on_item_complete=on_item_complete,
                **({"stop_control": run.control} if run else {}),
            )
            LineCheckAssistant._post_upgrade_ui(self, run, lambda: self._complete_page_upgrade(results, **({"run": run} if run else {})))
        except Exception as exc:
            if run:
                LineCheckAssistant._post_upgrade_ui(self, run, lambda error=str(exc): LineCheckAssistant._finish_upgrade_run(self, run, [], error))
            else:
                raise

    def _complete_page_upgrade(self, results, run=None) -> None:
        if run and run.thread is not None and run.thread.is_alive():
            self.after(50, lambda: LineCheckAssistant._complete_page_upgrade(self, results, run=run))
            return
        if run and LineCheckAssistant._finish_upgrade_run(self, run, results):
            return
        total = len(results)
        success_count = sum(1 for item in results if item.result.ok)
        if success_count == total:
            self._set_upgrade_status("", f"页面升级完成：{success_count}/{total} 台", 100)
            LineCheckAssistant._report_sample_upgrade_completion(
                self,
                "样机升级完成",
                f"页面升级完成：{success_count}/{total} 台样机已升级。",
                "info",
            )
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", True, f"页面升级完成：{success_count}/{total} 台成功。")
            return
        failed_messages = [item.result.message for item in results if not item.result.ok]
        progress = (success_count / total) * 100 if total else 0
        self._set_upgrade_status("", f"页面升级完成：{success_count}/{total} 台成功", progress)
        LineCheckAssistant._report_sample_upgrade_completion(
            self, "样机升级失败", "\n".join(failed_messages), "error"
        )
        _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, f"页面升级完成：{success_count}/{total} 台成功。")

    def _report_sample_upgrade_completion(self, title: str, detail: str, dialog_kind: str) -> None:
        """报告升级结果；本次全流程无人值守时不以中间弹窗阻塞编排器。"""
        suppress_dialog = bool(
            getattr(self, "_pipeline_sample_upgrade_completion_dialog_suppressed", False)
        )
        self._pipeline_sample_upgrade_completion_dialog_suppressed = False
        if suppress_dialog:
            self._log(
                f"[全流程][无人值守] {title}：{detail}；已写入执行日志，不显示完成提示框。"
            )
            return
        if dialog_kind == "info":
            messagebox.showinfo(title, detail, parent=self.upgrade_window)
        elif dialog_kind == "warning":
            messagebox.showwarning(title, detail, parent=self.upgrade_window)
        else:
            messagebox.showerror(title, detail, parent=self.upgrade_window)

    def _validate_upgrade_required_fields(self) -> bool:
        required_fields = [
            ("超级用户名", self.upgrade_username_var.get().strip()),
            ("密码", self.upgrade_password_var.get().strip()),
            ("升级固件", self.upgrade_firmware_var.get().strip()),
        ]
        missing = [label for label, value in required_fields if not value]
        if missing:
            messagebox.showwarning("升级信息不完整", f"请填入：{'、'.join(missing)}", parent=self.upgrade_window)
            return False
        return True

    def _start_full_package_upgrade(self, skip_confirmation: bool = False) -> bool:
        if getattr(self, "sample_upgrade_running", False):
            self._log("样机升级仍在运行或正在停止，请等待当前批次释放资源。")
            return False
        channels = self._selected_tftp_copy_upgrade_channels()
        if not channels:
            return False
        firmware_path = Path(self.upgrade_firmware_var.get().strip())
        if not firmware_path.is_file():
            messagebox.showwarning("未选择升级固件", "请先选择需要升级的固件文件。", parent=self.upgrade_window)
            return False

        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]] = []
        power_serial_port = self._selected_power_serial_port()
        transfer_method = LineCheckAssistant._selected_upgrade_transfer_method(self)
        is_web = transfer_method == TRANSFER_WEB_GATEWAY
        web_device_ip = self.device_ip_var.get().strip() if is_web else ""
        for channel in channels:
            try:
                if is_web:
                    validate_web_target(channel.network_card_ip.strip(), web_device_ip, channel.subnet_mask)
                    tftp_server_ip = ""
                else:
                    tftp_server_ip = self._full_package_tftp_server_ip_for_channel(channel)
            except ValueError as exc:
                messagebox.showwarning("VLAN IP 不正确", str(exc), parent=self.upgrade_window)
                return False

            vlan_name = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            power_channel = power_channel_from_section(channel.section)
            if not 1 <= power_channel <= TOTAL_CHANNEL_COUNT:
                messagebox.showwarning("程控电源通道不正确", f"无法从 {channel.section} 确定程控电源通道。", parent=self.upgrade_window)
                return False
            request = FullPackageUpgradeRequest(
                vlan=vlan_name.lower(),
                server_interface=vlan_name,
                tftp_server_ip=tftp_server_ip,
                firmware_path=firmware_path,
                power_serial_port=power_serial_port,
                final_username=self.upgrade_username_var.get().strip(),
                final_password=self.upgrade_password_var.get().strip(),
                restore_factory=bool(self.upgrade_restore_factory_var.get()),
                transfer_method=transfer_method,
                boot_entry_method=LineCheckAssistant._selected_boot_entry_method(self),
                power_channel=power_channel,
                serial_port=LineCheckAssistant._serial_port_for_channel(channel),
                web_device_ip=web_device_ip,
                web_source_ip=channel.network_card_ip.strip() if is_web else "",
                web_subnet_mask=channel.subnet_mask if is_web else "255.255.255.0",
            )
            upgrade_items.append((channel, request))

        target_text = "、".join(
            f"{request.vlan}/{request.serial_port or '(未配置COM)'}"
            f"（PC {request.web_source_ip if is_web else request.tftp_server_ip} → 样机 {web_device_ip if is_web else FULL_PACKAGE_DEVICE_IP}）"
            for _channel, request in upgrade_items
        )
        transfer_action = "执行 Tftp Put" if transfer_method == TFTP_PUT_TRANSFER else "下发 Tftp指令"
        if is_web:
            transfer_action = "打开网关网页、自动选择当前固件并点击 Update software，固定等待30秒后进入90秒Boot/Bood观察"
        network_instruction = (
            "Web升级使用对应通道PC静态IP/掩码，浏览器出口锁定对应VLAN网卡，访问主界面样机管理IP。\n"
            if is_web else
            f"全包升级固定将目标 VLAN 网卡准备为 192.168.1.<VLAN尾号>，样机固定为 {FULL_PACKAGE_DEVICE_IP}。\n"
        )
        parallel_count = clamp_parallel_count(self.upgrade_parallel_count_var.get())
        parallel_text = f"最多 {parallel_count} 台，完成即补位"
        restore_factory_text = "开启，会在最终系统登录后执行恢复出厂" if bool(self.upgrade_restore_factory_var.get()) else "关闭，不会执行恢复出厂"
        power_instruction = (
            "每台样机会自动上电、进入 boot、"
            if power_serial_port
            else "未选择程控电源 COM 口。请先手动重启样机，确认样机已重启后再点击“是”继续；随后将进入 boot、"
        )
        post_transfer_instruction = "并复位/重新上电。" if power_serial_port else "及后续升级流程。"
        if not skip_confirmation:
            if not messagebox.askyesno(
                "确认样机升级",
                f"将升级 {len(upgrade_items)} 台样机：{target_text}\n并行数：{parallel_text}\n\n"
                f"升级固件：{firmware_path}\n"
                f"{network_instruction}"
                f"升级过程不会改写 network_card_ip.ini；{power_instruction}{transfer_action}{post_transfer_instruction}\n"
                f"进入 Boot 方式：{upgrade_items[0][1].boot_entry_method}\n"
                f"恢复出厂：{restore_factory_text}\n\n是否继续？",
                parent=self.upgrade_window,
            ):
                return False
        else:
            self._log("[全流程][无人值守] 已使用总确认授权，跳过全包升级子任务确认。")

        self._log(
            ("[全包升级] Web指定网络：" if is_web else "[全包升级] 固定网络：")
            + "，".join(
                f"{request.vlan} PC {request.web_source_ip if is_web else request.tftp_server_ip} → 样机 {web_device_ip if is_web else FULL_PACKAGE_DEVICE_IP}"
                for _channel, request in upgrade_items
            )
        )

        terminal = getattr(self, "serial_terminal", None)
        if terminal is not None:
            terminal.begin_upgrade_logs([request.vlan for _channel, request in upgrade_items])
        self._set_upgrade_status("", f"准备并行升级 {len(upgrade_items)} 台样机（最多 {parallel_count} 台）", 0)
        parallel_worker = (
            self._parallel_web_gateway_upgrade_worker if is_web else
            self._parallel_tftp_command_upgrade_worker
            if transfer_method == TFTP_COMMAND_TRANSFER
            else self._parallel_tftp_put_upgrade_worker
        )
        return LineCheckAssistant._launch_upgrade_run(self, parallel_worker, (upgrade_items, parallel_count))

    def _selected_boot_entry_method(self) -> str:
        variable = getattr(self, "upgrade_boot_entry_var", None)
        return normalize_boot_entry(variable.get() if variable is not None else BOOT_ENTRY_LOGIN)

    def _selected_upgrade_transfer_method(self) -> str:
        return LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())

    def _selected_tftp_copy_upgrade_channels(self) -> list[ChannelConfig]:
        channels_by_vlan: dict[str, ChannelConfig] = {}
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if vlan and vlan.lower() not in channels_by_vlan:
                channels_by_vlan[vlan.lower()] = channel
        channels = list(channels_by_vlan.values())
        if not channels:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选至少 1 个通道并配置对应 VLAN。", parent=self.upgrade_window)
            return []
        return channels

    def _tftp_server_ip_for_channel(self, channel: ChannelConfig) -> str:
        if channel.network_card_ip:
            return channel.network_card_ip.strip()
        vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias)
        device_manage_ip = channel.device_manage_ip or self.device_ip_var.get().strip()
        if device_manage_ip:
            return static_ip_for_vlan(vlan, device_manage_ip)
        digits = "".join(char for char in vlan if char.isdigit())
        if not digits:
            raise ValueError(f"无法从 VLAN 名称确定 IP：{vlan or '未选择'}")
        host_number = int(digits)
        if not 1 <= host_number <= 254:
            raise ValueError(f"VLAN 主机号必须在 1-254 之间：{host_number}")
        return f"192.168.1.{host_number}"

    @staticmethod
    def _full_package_tftp_server_ip_for_channel(channel: ChannelConfig) -> str:
        """全包升级固定走 192.168.1.0/24，不读取主界面样机管理 IP。"""
        vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias)
        digits = "".join(char for char in vlan if char.isdigit())
        if not digits:
            raise ValueError(f"无法从 VLAN 名称确定全包升级 IP：{vlan or '未选择'}")
        host_number = int(digits)
        if not 1 <= host_number <= 254:
            raise ValueError(f"VLAN 主机号必须在 1-254 之间：{host_number}")
        return f"192.168.1.{host_number}"

    def _parallel_tftp_command_upgrade_worker(
        self,
        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]],
        parallel_count: int = DEFAULT_PARALLEL_COUNT,
        run=None,
    ) -> None:
        requests = [request for _channel, request in upgrade_items]
        total = len(requests)
        max_workers = max(1, min(clamp_parallel_count(parallel_count), total))
        started = succeeded = failed = stopped = skipped = 0

        def refresh_status() -> None:
            running = started - succeeded - failed - stopped
            queued = total - started - skipped
            progress = ((succeeded + failed + stopped + skipped) / total) * 100 if total else 100
            LineCheckAssistant._post_upgrade_ui(
                self, run,
                lambda: self._set_upgrade_status(
                    "",
                    f"并行升级：运行中 {running} 台，已成功 {succeeded} 台，已失败 {failed} 台，排队 {queued} 台"
                    + (f"，已停止 {stopped} 台，跳过 {skipped} 台" if stopped or skipped else ""),
                    progress,
                ),
            )

        def on_item_started(request: FullPackageUpgradeRequest) -> None:
            nonlocal started
            started += 1
            self.log_queue.put(f"开始并行升级：{request.vlan}")
            refresh_status()

        def on_item_complete(item) -> None:
            nonlocal succeeded, failed, stopped, skipped
            if isinstance(item.result, UpgradeStoppedResult):
                skipped += int(item.result.skipped)
                stopped += int(not item.result.skipped)
            elif item.result.ok:
                succeeded += 1
            else:
                failed += 1
            self.log_queue.put(item.result.message)
            refresh_status()

        try:
            results = run_parallel_tftp_command_upgrades(
                requests,
                self.serial_session_manager,
                max_workers=max_workers,
                on_output=lambda vlan, line: self.log_queue.put(f"[{vlan}] {line}"),
                on_session_ready=lambda vlan, session, log_path: LineCheckAssistant._post_upgrade_ui(
                    self, run, lambda vlan=vlan, session=session, log_path=log_path: self._attach_serial_upgrade(vlan, session, log_path)
                ),
                on_item_started=on_item_started,
                on_item_complete=on_item_complete,
                **({"stop_control": run.control} if run else {}),
            )
            LineCheckAssistant._post_upgrade_ui(self, run, lambda: self._complete_parallel_tftp_command_upgrade(total, results, **({"run": run} if run else {})))
        except Exception as exc:
            LineCheckAssistant._post_upgrade_ui(self, run, lambda error=str(exc): self._complete_parallel_tftp_command_upgrade(total, [], error, **({"run": run} if run else {})))
        finally:
            terminal = getattr(self, "serial_terminal", None)
            if terminal is not None:
                if run is None:
                    self.after(100, terminal.finish_upgrade_logs)

    def _parallel_web_gateway_upgrade_worker(self, upgrade_items, parallel_count=DEFAULT_PARALLEL_COUNT, run=None):
        # Reuse only UI progress/completion plumbing; transport dispatch stays independent.
        LineCheckAssistant._parallel_tftp_put_upgrade_worker(
            self, upgrade_items, parallel_count, runner=run_parallel_web_gateway_upgrades,
            **({"run": run} if run else {}),
        )

    def _parallel_tftp_put_upgrade_worker(
        self,
        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]],
        parallel_count: int = DEFAULT_PARALLEL_COUNT,
        run=None,
        *,
        runner=None,
    ) -> None:
        requests = [request for _channel, request in upgrade_items]
        total = len(requests)
        max_workers = max(1, min(clamp_parallel_count(parallel_count), total))
        started = succeeded = failed = stopped = skipped = 0

        def refresh_status() -> None:
            running = started - succeeded - failed - stopped
            queued = total - started - skipped
            progress = ((succeeded + failed + stopped + skipped) / total) * 100 if total else 100
            LineCheckAssistant._post_upgrade_ui(
                self, run,
                lambda: self._set_upgrade_status(
                    "",
                    f"并行升级：运行中 {running} 台，已成功 {succeeded} 台，已失败 {failed} 台，排队 {queued} 台"
                    + (f"，已停止 {stopped} 台，跳过 {skipped} 台" if stopped or skipped else ""),
                    progress,
                ),
            )

        def on_item_started(request: FullPackageUpgradeRequest) -> None:
            nonlocal started
            started += 1
            self.log_queue.put(f"开始并行升级：{request.vlan}")
            refresh_status()

        def on_item_complete(item) -> None:
            nonlocal succeeded, failed, stopped, skipped
            if isinstance(item.result, UpgradeStoppedResult):
                skipped += int(item.result.skipped)
                stopped += int(not item.result.skipped)
            elif item.result.ok:
                succeeded += 1
            else:
                failed += 1
            self.log_queue.put(item.result.message)
            refresh_status()

        try:
            results = (runner or run_parallel_tftp_put_upgrades)(
                requests,
                self.serial_session_manager,
                max_workers=max_workers,
                on_output=lambda vlan, line: self.log_queue.put(f"[{vlan}] {line}"),
                on_session_ready=lambda vlan, session, log_path: LineCheckAssistant._post_upgrade_ui(
                    self, run, lambda vlan=vlan, session=session, log_path=log_path: self._attach_serial_upgrade(vlan, session, log_path)
                ),
                on_item_started=on_item_started,
                on_item_complete=on_item_complete,
                **({"stop_control": run.control} if run else {}),
            )
            LineCheckAssistant._post_upgrade_ui(self, run, lambda: self._complete_parallel_tftp_put_upgrade(total, results, **({"run": run} if run else {})))
        except Exception as exc:
            LineCheckAssistant._post_upgrade_ui(self, run, lambda error=str(exc): self._complete_parallel_tftp_put_upgrade(total, [], error, **({"run": run} if run else {})))
        finally:
            terminal = getattr(self, "serial_terminal", None)
            if terminal is not None:
                if run is None:
                    self.after(100, terminal.finish_upgrade_logs)

    def _complete_parallel_tftp_command_upgrade(self, total: int, results, orchestration_error: str | None = None, run=None) -> None:
        if run and run.thread is not None and run.thread.is_alive():
            self.after(50, lambda: LineCheckAssistant._complete_parallel_tftp_command_upgrade(self, total, results, orchestration_error, run=run))
            return
        if run and LineCheckAssistant._finish_upgrade_run(self, run, results, orchestration_error):
            return
        if orchestration_error:
            self._set_upgrade_status("", "并行升级启动失败", 0)
            self._log(orchestration_error)
            LineCheckAssistant._report_sample_upgrade_completion(
                self, "并行升级失败", orchestration_error, "error"
            )
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, orchestration_error)
            return
        succeeded = [item for item in results if item.result.ok]
        failed = [item for item in results if not item.result.ok]
        self._set_upgrade_status("", f"并行升级完成：成功 {len(succeeded)}/{total} 台，失败 {len(failed)} 台", 100)
        detail = "\n".join(
            f"{'成功' if item.result.ok else '失败'} {item.request.vlan}：{item.result.message}"
            for item in results
        )
        LineCheckAssistant._report_sample_upgrade_completion(
            self, "样机升级完成", detail, "warning" if failed else "info"
        )
        _finish_pipeline_subtask_if_waiting(
            self, "sample_upgrade", not failed, f"并行 Tftp指令 升级完成：成功 {len(succeeded)}/{total} 台。"
        )

    def _complete_parallel_tftp_put_upgrade(self, total: int, results, orchestration_error: str | None = None, run=None) -> None:
        if run and run.thread is not None and run.thread.is_alive():
            self.after(50, lambda: LineCheckAssistant._complete_parallel_tftp_put_upgrade(self, total, results, orchestration_error, run=run))
            return
        if run and LineCheckAssistant._finish_upgrade_run(self, run, results, orchestration_error):
            return
        if orchestration_error:
            self._set_upgrade_status("", "并行升级启动失败", 0)
            self._log(orchestration_error)
            LineCheckAssistant._report_sample_upgrade_completion(
                self, "并行升级失败", orchestration_error, "error"
            )
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, orchestration_error)
            return
        succeeded = [item for item in results if item.result.ok]
        failed = [item for item in results if not item.result.ok]
        self._set_upgrade_status("", f"并行升级完成：成功 {len(succeeded)}/{total} 台，失败 {len(failed)} 台", 100)
        detail = "\n".join(
            f"{'成功' if item.result.ok else '失败'} {item.request.vlan}：{item.result.message}"
            for item in results
        )
        LineCheckAssistant._report_sample_upgrade_completion(
            self, "样机升级完成", detail, "warning" if failed else "info"
        )
        _finish_pipeline_subtask_if_waiting(
            self, "sample_upgrade", not failed,
            f"并行 {results[0].request.transfer_method if results else TFTP_PUT_TRANSFER} 升级完成：成功 {len(succeeded)}/{total} 台。"
        )

    def _toggle_upgrade_password_visibility(self) -> None:
        self.upgrade_password_visible = not self.upgrade_password_visible
        self.upgrade_password_entry.configure(show="" if self.upgrade_password_visible else "*")
        self.upgrade_password_toggle.configure(relief="sunken" if self.upgrade_password_visible else "raised")

    def _select_upgrade_firmware(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.upgrade_window,
            title="选择升级固件",
            filetypes=[
                ("所有文件", "*.*"),
                ("升级固件", "*.bin *.img *.trx *.tar *.gz *.zip"),
            ],
        )
        if path:
            self.upgrade_firmware_var.set(path)

    def _selected_upgrade_vlans(self) -> list[str]:
        vlans = []
        seen = set()
        for channel in self.channels:
            if not channel.enabled:
                continue
            value = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            vlans.append(value.lower() if value.lower().startswith("vlan") else value)
        return sorted(vlans, key=self._vlan_sort_key)

    def _selected_serial_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        seen = set()
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if not vlan or vlan.casefold() in seen:
                continue
            seen.add(vlan.casefold())
            normalized_vlan = vlan.lower() if vlan.lower().startswith("vlan") else vlan
            targets.append(
                (normalized_vlan, LineCheckAssistant._serial_port_for_channel(channel))
            )
        return sorted(targets, key=lambda item: self._vlan_sort_key(item[0]))

    def _serial_targets_for_vlans(self, vlans: list[str]) -> list[tuple[str, str]]:
        return [(vlan, self._serial_port_for_vlan(vlan)) for vlan in vlans]

    def _refresh_upgrade_targets(self) -> None:
        vlans = self._selected_upgrade_vlans()
        if vlans:
            self.upgrade_targets_var.set("、".join(vlans))
        elif any(channel.enabled for channel in self.channels):
            self.upgrade_targets_var.set("已勾选通道尚未配置 VLAN")
        else:
            self.upgrade_targets_var.set("未勾选目标样机")

    def _set_upgrade_status(self, vlan: str, stage: str, progress: float) -> None:
        run = getattr(self, "_sample_upgrade_run", None)
        if run and not run.finished and run.control.is_set():
            stage = "正在停止，等待安全收尾；" + stage
        normalized_progress = max(0.0, min(float(progress), 100.0))
        self.upgrade_progress_var.set(normalized_progress)
        if vlan:
            self.upgrade_status_var.set(f"正在升级 {vlan}：{stage}（{normalized_progress:g}%）")
        else:
            self.upgrade_status_var.set(stage or "尚未开始升级")

    def _refresh_saved_project_name(self) -> None:
        """只展示磁盘配置；失败不影响主窗口或测试项配置的既有流程。"""
        try:
            name = TestItemConfigStore(TEST_ITEM_CONFIG_PATH).load(required=True).project_info.project_name
        except FileNotFoundError:
            self.project_name_badge.set_name("")
            self.log_queue.put("[项目名称] 配置文件不存在，显示未设置。")
        except Exception:
            self.project_name_badge.set_name("", failed=True)
            self.log_queue.put("[项目名称] 读取失败，请检查配置格式和访问权限。")
        else:
            self.project_name_badge.set_name(name)
            self.log_queue.put("[项目名称] 已刷新已保存的项目名称。" if name.strip()
                               else "[项目名称] 已保存名称为空，显示未设置。")

    def _open_test_item_config(self) -> None:
        """打开配置窗口：编辑、单次预备测试及只读项目信息查询。"""
        self._refresh_saved_project_name()
        if self.test_item_config_window is not None and self.test_item_config_window.winfo_exists():
            self.test_item_config_window.deiconify()
            self.test_item_config_window.lift()
            self.test_item_config_window.focus_force()
            schedule_toplevel_client_refresh(self.test_item_config_window)
            return

        dialog = Toplevel(self)
        self.test_item_config_window = dialog
        dialog.title("测试项配置")
        window_width, window_height = self._restore_module_window_size(
            dialog, "test_item_config"
        )
        dialog.minsize(960, 940)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        Label(
            content,
            text="测试项配置",
            font=(FONT_FAMILY, 18, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(anchor="w")
        Label(
            content,
            text=(
                "编辑测试项 ini（Telnet / 测试项命令 / WiFi / 项目信息）、运行参数及消息推送。"
                "测试项页可单次执行预备测试；项目信息页可对当前通道样机执行只读版本查询。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=920,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        store = TestItemConfigStore(TEST_ITEM_CONFIG_PATH)
        if not TEST_ITEM_CONFIG_PATH.exists():
            messagebox.showwarning(
                "未找到测试项 ini",
                (
                    f"未找到 {TEST_ITEM_CONFIG_PATH}。\n\n"
                    "将以空白表单打开，保存后自动创建。"
                    "默认值与老工具原 ini 保持一致。"
                ),
                parent=dialog,
            )
        legacy_defaults_store = LegacyUiDefaultsStore(LEGACY_UI_DEFAULTS_CONFIG_PATH)
        message_push_service = MessagePushConfigService(LEGACY_UI_DEFAULTS_CONFIG_PATH)
        try:
            message_push_values = message_push_service.load()
            config = store.load()
            legacy_defaults = legacy_defaults_store.load()
        except Exception:  # 配置解析异常可能包含原始凭据，使用固定提示。
            error = "配置加载失败，请检查 ini 格式和访问权限。"
            self._log(f"[测试项配置 / 消息推送] {error}")
            messagebox.showerror("加载失败", error, parent=dialog)
            dialog.destroy()
            self.test_item_config_window = None
            return
        self._log("[消息推送] 已加载 config.ini [dingtalk_config]")

        notebook = ttk.Notebook(content)
        notebook.pack(fill="both", expand=True, pady=(0, 12))

        dirty = [False]

        def mark_dirty(*_args) -> None:
            dirty[0] = True

        telnet_vars = self._build_test_item_telnet_tab(notebook, config.telnet, mark_dirty)
        order_control = self._build_test_item_order_tab(
            notebook,
            config.order,
            mark_dirty,
            TEST_ITEM_DEFAULT_CONFIG_PATH,
            telnet_supplier=telnet_vars["capture"],
        )
        wifi_vars = self._build_test_item_wifi_tab(notebook, config.connect_wifi, mark_dirty)
        project_info_vars = self._build_test_item_project_info_tab(
            notebook,
            config.project_info,
            mark_dirty,
            telnet_supplier=telnet_vars["capture"],
        )
        legacy_defaults_control = self._build_test_item_ui_defaults_tab(
            notebook,
            legacy_defaults,
            mark_dirty,
        )
        message_push_control = MessagePushTab(
            notebook, message_push_values, mark_dirty,
            background=COLOR_BG, foreground=COLOR_TEXT, log=self._log,
            project_config_path=TEST_ITEM_CONFIG_PATH,
        )

        button_bar = Frame(content, background=COLOR_BG)
        button_bar.pack(fill="x", side="bottom", anchor="e")

        def reset_dirty() -> None:
            dirty[0] = False

        def reload() -> None:
            if dirty[0]:
                if not messagebox.askyesno(
                    "放弃修改",
                    "当前有未保存的修改，重新加载将丢弃这些改动。是否继续？",
                    parent=dialog,
                ):
                    return
            try:
                reloaded = store.load()
                reloaded_legacy_defaults = legacy_defaults_store.load()
                reloaded_message_push = message_push_service.load()
            except Exception as exc:  # noqa: BLE001 - ini 损坏需明确提示
                self._log("[测试项配置 / 消息推送] 重新加载失败，请检查配置格式和访问权限。")
                messagebox.showerror("加载失败", "读取 ini 失败，请检查配置格式和访问权限。", parent=dialog)
                return
            finally:
                self._refresh_saved_project_name()
            legacy_defaults_control["load"](reloaded_legacy_defaults)
            telnet_vars["load"](reloaded.telnet)
            order_control["load"](reloaded.order)
            wifi_vars["load"](reloaded.connect_wifi)
            project_info_vars["load"](reloaded.project_info)
            message_push_control.load(reloaded_message_push)
            reset_dirty()
            self._log("[测试项配置] 已从磁盘重新加载（未保存改动已丢弃）")
            self._log("[消息推送] 已重新加载 config.ini [dingtalk_config]")

        def save() -> None:
            try:
                captured_message_push = message_push_service.validate(message_push_control.capture())
                captured = TestProjectConfig(
                    telnet=telnet_vars["capture"](),
                    order=order_control["capture"](),
                    connect_wifi=wifi_vars["capture"](),
                    project_info=project_info_vars["capture"](),
                )
                captured_legacy_defaults = legacy_defaults_control["capture"]()
                captured_legacy_defaults[TELNET_ENABLE_OPTION] = (
                    "0" if bool(captured.telnet.telnet_default_on) else "1"
                )
                captured_legacy_defaults = legacy_defaults_store.validate(
                    captured_legacy_defaults
                )
            except ValueError as exc:
                self._log("[测试项配置 / 消息推送] 保存跳过：输入校验失败。")
                messagebox.showerror("数据不合法", str(exc), parent=dialog)
                return
            if not messagebox.askyesno(
                "保存测试项 ini",
                (
                    f"将更新 {TEST_ITEM_CONFIG_PATH} 和 {LEGACY_UI_DEFAULTS_CONFIG_PATH}。\n\n"
                    f"- Telnet 字段：{len(captured.telnet.__dict__)} 项\n"
                    f"- 测试项命令：{len(captured.order.items)} 条\n"
                    f"- 指令重试间隔：{captured.order.command_fail_retry_interval_time} 秒"
                    "（仅写入 config.ini [other_config]）\n"
                    f"- WiFi 连接：{'启用' if captured.connect_wifi.enable else '关闭'}；"
                    f"2.4G={'启用' if captured.connect_wifi.test_2g_enable else '关闭'}；"
                    f"5G={'启用' if captured.connect_wifi.test_5g_enable else '关闭'}；"
                    f"认证={captured.connect_wifi.auth_mode}；加密={captured.connect_wifi.cipher}；"
                    f"网卡={captured.connect_wifi.wireless_card_name if captured.connect_wifi.choose_wireless_card else '自动选择'}\n"
                    f"- 项目信息：项目={captured.project_info.project_name or '(空)'}，"
                    f"软件版本={captured.project_info.software_version or '(空)'}，"
                    f"内部软件版本={captured.project_info.internal_software_version or '(空)'}，"
                    f"编译时间={captured.project_info.onu_compile_time or '(空)'}\n"
                    f"- 旧工具参数：[ui_defaults] {len(captured_legacy_defaults)} 项\n"
                    f"- 消息推送：{'启用' if captured_message_push['dingtalk_flag'] == '1' else '关闭'}；"
                    f"@所有人：{'启用' if captured_message_push['at_all'] == '1' else '关闭'}\n\n"
                    "测试项 ini 中的原注释会在保存后丢失；config.ini 的其它段和注释会保留。是否继续？"
                ),
                parent=dialog,
            ):
                self._log("[消息推送] 操作员取消保存，跳过写入。")
                return
            try:
                self._log("[消息推送] 开始保存 config.ini [dingtalk_config]")
                store.save(captured)
                legacy_defaults_store.save(captured_legacy_defaults)
                message_push_service.save(captured_message_push)
            except OSError as exc:
                messagebox.showerror("保存失败", f"写入 ini 失败：{exc}", parent=dialog)
                self._log(f"[测试项配置 / 消息推送] 保存失败：{exc}")
                return
            finally:
                self._refresh_saved_project_name()
            reset_dirty()
            self._log("[消息推送] 已保存 config.ini [dingtalk_config]，未发送消息。")
            self._log(
                f"[测试项配置] 已保存 {len(captured.order.items)} 条测试项命令，"
                f"已将指令重试间隔 {captured.order.command_fail_retry_interval_time} 秒"
                "保存到 config.ini [other_config]，"
                f"并更新 {len(captured_legacy_defaults)} 项旧工具参数"
            )
            messagebox.showinfo(
                "保存成功",
                f"已保存到 {TEST_ITEM_CONFIG_PATH} 和 {LEGACY_UI_DEFAULTS_CONFIG_PATH}。",
                parent=dialog,
            )

        def close_dialog() -> None:
            if not message_push_control.can_close():
                return
            pretest = getattr(self, "test_item_pretest_controls", None)
            if pretest is not None and not pretest.can_close():
                return
            if dirty[0]:
                if not messagebox.askyesno(
                    "放弃修改",
                    "当前有未保存的修改，关闭窗口将丢弃这些改动。是否继续？",
                    parent=dialog,
                ):
                    return
            self._remember_module_window_size(dialog, "test_item_config")
            dialog.destroy()
            self.test_item_config_window = None
            self.test_item_pretest_controls = None

        ttk.Button(button_bar, text="重新加载", command=reload, style="Secondary.TButton").pack(side="left")
        ttk.Button(button_bar, text="关闭", command=close_dialog, style="Secondary.TButton").pack(side="right")
        ttk.Button(button_bar, text="保存", command=save, style="Primary.TButton").pack(side="right", padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        center_toplevel_on_parent(
            dialog,
            self,
            window_width=window_width,
            window_height=window_height,
        )
        schedule_toplevel_client_refresh(
            dialog,
            on_first_refresh=lambda: self._log(
                "[测试项配置] 已触发客户区首帧尺寸刷新"
            ),
        )

    # -- 测试项配置：各 Tab 的具体构建 ------------------------------------

    def _build_test_item_telnet_tab(
        self,
        notebook: ttk.Notebook,
        telnet: TelnetSettings,
        mark_dirty,
    ) -> dict:
        """构建 [telnet] 段 Tab。返回 ``{"capture": Callable, "load": Callable}``。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="Telnet")

        request_url_var = StringVar(value=telnet.request_url)
        port_var = IntVar(value=telnet.port)
        user_var = StringVar(value=telnet.user)
        password_var = StringVar(value=telnet.password)
        timeout_var = IntVar(value=telnet.timeout)
        input_user_flag_var = StringVar(value=telnet.input_user_flag)
        input_password_flag_var = StringVar(value=telnet.input_password_flag)
        login_success_flag_var = StringVar(value=telnet.login_success_flag)
        login_after_input_str_var = StringVar(value=telnet.login_after_input_str)
        need_pwd_flag_var = IntVar(value=telnet.telnet_need_enter_password_flag)
        no_user_pwd_flag_var = IntVar(value=telnet.telnet_no_user_password_flag)
        only_power_var = IntVar(value=telnet.only_power_off_on)
        # Telnet 默认已开启(默认 1 = 勾选,可在 UI 中由用户切换;Q1=A 仅编辑器)。
        telnet_default_on_var = IntVar(value=telnet.telnet_default_on)

        password_visible = [False]

        for var in (
            request_url_var,
            user_var,
            password_var,
            input_user_flag_var,
            input_password_flag_var,
            login_success_flag_var,
            login_after_input_str_var,
        ):
            var.trace_add("write", lambda *_a: mark_dirty())
        for var in (
            port_var,
            timeout_var,
            need_pwd_flag_var,
            no_user_pwd_flag_var,
            only_power_var,
            telnet_default_on_var,
        ):
            var.trace_add("write", lambda *_a: mark_dirty())

        def int_field(parent: ttk.Frame, row: int, label: str, var: IntVar, from_: int = 0, to: int = 65535) -> None:
            Label(parent, text=label, width=32, anchor="w", background=COLOR_BG).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            ttk.Spinbox(parent, from_=from_, to=to, textvariable=var, width=10).grid(
                row=row, column=1, sticky="w", pady=6
            )

        Label(
            frame,
            text="Telnet 连接参数",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # 新增的 Checkbutton 放在标题下方(原 request_url 行的位置),其他字段全部下移 1 行。
        Checkbutton(
            frame,
            text="设备默认已开启 Telnet",
            variable=telnet_default_on_var,
            onvalue=1,
            offvalue=0,
            background=COLOR_BG,
            activebackground=COLOR_BG,
            highlightthickness=0,
            borderwidth=0,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))

        Label(frame, text="Telnet 开启地址", width=32, anchor="w", background=COLOR_BG).grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=request_url_var, width=36).grid(row=2, column=1, sticky="ew", pady=6)

        Label(frame, text="登录用户名", width=32, anchor="w", background=COLOR_BG).grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=user_var, width=24).grid(row=3, column=1, sticky="ew", pady=6)

        Label(frame, text="登录密码（明文）", width=32, anchor="w", background=COLOR_BG).grid(
            row=4, column=0, sticky="w", padx=(0, 12), pady=6
        )
        pwd_container = Frame(frame, background=COLOR_BG)
        pwd_container.grid(row=4, column=1, sticky="ew", pady=6)
        pwd_entry = ttk.Entry(pwd_container, textvariable=password_var, width=24)
        pwd_entry.pack(side="left", fill="x", expand=True)

        def toggle_password_visibility() -> None:
            password_visible[0] = not password_visible[0]
            pwd_entry.configure(show="" if password_visible[0] else "*")
            toggle_btn.configure(text="🙈" if password_visible[0] else "👁")

        toggle_btn = Button(pwd_container, text="👁", width=3, command=toggle_password_visibility)
        toggle_btn.pack(side="left", padx=(8, 0))

        int_field(frame, 5, "Telnet 端口", port_var, from_=1, to=65535)
        int_field(frame, 6, "连接超时时间（秒）", timeout_var, from_=1, to=600)

        Label(frame, text="用户名提示符", width=32, anchor="w", background=COLOR_BG).grid(
            row=7, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=input_user_flag_var, width=18).grid(row=7, column=1, sticky="w", pady=6)
        Label(frame, text="密码提示符", width=32, anchor="w", background=COLOR_BG).grid(
            row=8, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=input_password_flag_var, width=18).grid(row=8, column=1, sticky="w", pady=6)
        Label(frame, text="登录成功提示符", width=32, anchor="w", background=COLOR_BG).grid(
            row=9, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=login_success_flag_var, width=18).grid(row=9, column=1, sticky="w", pady=6)

        Label(frame, text="登录后命令", width=32, anchor="w", background=COLOR_BG).grid(
            row=10, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=login_after_input_str_var, width=18).grid(
            row=10, column=1, sticky="w", pady=6
        )

        int_field(frame, 11, "是否需要输入密码（0/1）", need_pwd_flag_var, from_=0, to=1)
        int_field(frame, 12, "免用户名密码登录（0/1）", no_user_pwd_flag_var, from_=0, to=1)
        int_field(frame, 13, "仅执行上下电（0/1）", only_power_var, from_=0, to=1)

        frame.columnconfigure(1, weight=1)

        def capture() -> TelnetSettings:
            return TelnetSettings(
                request_url=request_url_var.get().strip(),
                port=int(port_var.get()),
                user=user_var.get(),
                password=password_var.get(),
                timeout=int(timeout_var.get()),
                input_user_flag=input_user_flag_var.get(),
                input_password_flag=input_password_flag_var.get(),
                login_success_flag=login_success_flag_var.get(),
                login_after_input_str=login_after_input_str_var.get(),
                telnet_need_enter_password_flag=int(need_pwd_flag_var.get()),
                telnet_no_user_password_flag=int(no_user_pwd_flag_var.get()),
                only_power_off_on=int(only_power_var.get()),
                telnet_default_on=int(telnet_default_on_var.get()),
            )

        def load(new_telnet: TelnetSettings) -> None:
            request_url_var.set(new_telnet.request_url)
            port_var.set(new_telnet.port)
            user_var.set(new_telnet.user)
            password_var.set(new_telnet.password)
            timeout_var.set(new_telnet.timeout)
            input_user_flag_var.set(new_telnet.input_user_flag)
            input_password_flag_var.set(new_telnet.input_password_flag)
            login_success_flag_var.set(new_telnet.login_success_flag)
            login_after_input_str_var.set(new_telnet.login_after_input_str)
            need_pwd_flag_var.set(new_telnet.telnet_need_enter_password_flag)
            no_user_pwd_flag_var.set(new_telnet.telnet_no_user_password_flag)
            only_power_var.set(new_telnet.only_power_off_on)
            telnet_default_on_var.set(int(new_telnet.telnet_default_on))

        return {
            "capture": capture,
            "load": load,
            "telnet_default_on_var": telnet_default_on_var,
        }

    def _build_test_item_order_tab(
        self,
        notebook: ttk.Notebook,
        order: OrderConfig,
        mark_dirty,
        default_config_path: Path,
        telnet_supplier=None,
    ) -> dict:
        """构建 [order] 段 Tab。返回 ``{"capture": Callable, "load": Callable}``。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="测试项")

        # 顶部全局控件：指令重试间隔
        header = ttk.Frame(frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, 8))
        Label(
            header,
            text="测试项命令",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).pack(side="left")
        interval_container = ttk.Frame(header, style="App.TFrame")
        interval_container.pack(side="right")
        Label(
            interval_container,
            text="指令重试间隔（秒，全局）",
            background=COLOR_BG,
            foreground=COLOR_MUTED,
        ).pack(side="left", padx=(0, 6))
        interval_var = IntVar(value=order.command_fail_retry_interval_time or DEFAULT_COMMAND_FAIL_RETRY_INTERVAL)
        interval_var.trace_add("write", lambda *_a: mark_dirty())
        ttk.Spinbox(interval_container, from_=0, to=999, textvariable=interval_var, width=6).pack(side="left")

        Label(
            frame,
            text=(
                "每条命令可设置独立的重试次数；期望匹配默认正向，「否定」勾选后整段反向匹配；"
                "多段用 && 拼接表示全部命中。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        if telnet_supplier is not None:
            self.test_item_pretest_controls = PretestControls(
                frame,
                capture_request=lambda: self._capture_pretest_request(
                    capture(pretest=True), telnet_supplier()
                ),
                log=lambda text, tag: self._log(text, tag=tag),
                is_busy=lambda: any(bool(getattr(self, name, False)) for name in (
                    "running", "power_on_running", "power_test_running",
                    "parameter_write_running", "sample_upgrade_running", "dut_config_running",
                )),
            )

        # 中间滚动列表 + 底部新增按钮
        list_outer = ttk.Frame(frame, style="App.TFrame")
        list_outer.pack(fill="both", expand=True)
        canvas = Canvas(list_outer, highlightthickness=0, borderwidth=0, background=COLOR_BG)
        scrollbar = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        rows_frame = ttk.Frame(canvas, style="App.TFrame")
        rows_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")

        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(rows_window, width=e.width))
        rows_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Windows 鼠标滚轮支持
        def _on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        row_widgets: list[dict] = []

        def _add_segment_row(
            parent: ttk.Frame,
            segments_list: list[dict],
            text: str = "",
            negate: bool = False,
        ) -> dict:
            seg_frame = ttk.Frame(parent, style="App.TFrame")
            seg_frame.pack(fill="x", pady=2)

            negate_var = BooleanVar(value=negate)
            negate_var.trace_add("write", lambda *_a: mark_dirty())
            Checkbutton(
                seg_frame,
                text="否定",
                variable=negate_var,
                background=COLOR_SURFACE,
                activebackground=COLOR_SURFACE,
                highlightthickness=0,
                borderwidth=0,
            ).pack(side="left", padx=(0, 6))

            seg_var = StringVar(value=text)
            seg_var.trace_add("write", lambda *_a: mark_dirty())
            ttk.Entry(seg_frame, textvariable=seg_var).pack(side="left", fill="x", expand=True)

            def remove_segment() -> None:
                seg_frame.destroy()
                if seg_dict in segments_list:
                    segments_list.remove(seg_dict)

            ttk.Button(seg_frame, text="删除段", width=8, command=remove_segment, style="Secondary.TButton").pack(
                side="left", padx=(6, 0)
            )
            seg_dict = {
                "frame": seg_frame,
                "var": seg_var,
                "negate_var": negate_var,
                "remove": remove_segment,
            }
            segments_list.append(seg_dict)
            return seg_dict

        def _build_row_widgets(item: OrderItem, row_index: int) -> dict:
            row_frame = ttk.Frame(rows_frame, style="Surface.TFrame", padding=(8, 6))
            # 命令组之间保留更明显的空白；段内期望条件仍使用紧凑间距。
            row_frame.pack(fill="x", pady=(0, TEST_ITEM_COMMAND_GROUP_SPACING))

            top = ttk.Frame(row_frame, style="Surface.TFrame")
            top.pack(fill="x")

            number_var = StringVar(value=f"{row_index + 1:02d}")
            Label(top, textvariable=number_var, width=4, anchor="w", background=COLOR_SURFACE).pack(
                side="left", padx=(0, 6)
            )

            command_var = StringVar(value=item.command)
            command_var.trace_add("write", lambda *_a: mark_dirty())
            ttk.Entry(top, textvariable=command_var, width=44).pack(side="left", fill="x", expand=True, padx=(0, 6))

            Label(top, text="重试次数", background=COLOR_SURFACE, foreground=COLOR_MUTED).pack(
                side="left", padx=(0, 4)
            )
            retry_var = IntVar(value=item.retry_times or 1)
            retry_var.trace_add("write", lambda *_a: mark_dirty())
            ttk.Spinbox(top, from_=1, to=99, textvariable=retry_var, width=5).pack(side="left", padx=(0, 6))

            def remove_row() -> None:
                row_frame.destroy()
                if row_dict in row_widgets:
                    row_widgets.remove(row_dict)
                _renumber_rows()

            ttk.Button(top, text="删除命令", width=10, command=remove_row, style="Secondary.TButton").pack(side="right")

            # 期望区域(per-segment 否定:每段独立 Checkbutton,见 _add_segment_row)
            expected_frame = ttk.Frame(row_frame, style="Surface.TFrame")
            expected_frame.pack(fill="x", pady=(6, 0))

            segments_list: list[dict] = []

            def add_segment() -> None:
                _add_segment_row(segments_holder, segments_list)

            segments_holder = ttk.Frame(expected_frame, style="Surface.TFrame")
            segments_holder.pack(fill="x", pady=(4, 0))
            for seg in item.expected_segments:
                _add_segment_row(segments_holder, segments_list, text=seg.text, negate=bool(seg.negate))

            seg_actions = ttk.Frame(expected_frame, style="Surface.TFrame")
            seg_actions.pack(fill="x", pady=(4, 0))
            ttk.Button(seg_actions, text="+ 增加段", width=10, command=add_segment, style="Secondary.TButton").pack(
                side="left"
            )

            row_dict = {
                "frame": row_frame,
                "number_var": number_var,
                "command_var": command_var,
                "retry_var": retry_var,
                "segments": segments_list,
                "remove": remove_row,
            }
            return row_dict

        def _renumber_rows() -> None:
            for index, row_dict in enumerate(row_widgets):
                row_dict["number_var"].set(f"{index + 1:02d}")

        def add_row(item: OrderItem | None = None) -> None:
            new_item = item or OrderItem()
            row_widgets.append(_build_row_widgets(new_item, len(row_widgets)))
            _renumber_rows()

        # 填充初始数据
        if order.items:
            for item in order.items:
                add_row(item)
        else:
            add_row(OrderItem())

        # 底部新增按钮
        bottom_bar = ttk.Frame(frame, style="App.TFrame")
        bottom_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom_bar, text="+ 新增测试项", width=14, command=lambda: add_row(), style="Secondary.TButton").pack(
            side="left"
        )

        def restore_default() -> None:
            self._log("[测试项配置] 恢复默认测试项：等待操作员确认")
            if not messagebox.askyesno(
                "恢复默认测试项",
                (
                    "将用默认模板恢复当前页面的全部测试项命令。\n\n"
                    "指令重试间隔继续使用 config.ini 中的当前值，不会恢复或覆盖。\n\n"
                    "Telnet、WiFi 和项目信息不会改变；恢复后仍需点击窗口底部“保存”才会写入正式配置。\n\n"
                    "是否继续？"
                ),
                parent=self.test_item_config_window,
            ):
                self._log("[测试项配置] 恢复默认测试项：操作员取消，跳过")
                return
            if not default_config_path.is_file():
                message = f"未找到默认测试项配置：{default_config_path}"
                messagebox.showerror("恢复默认失败", message, parent=self.test_item_config_window)
                self._log(f"[测试项配置] 恢复默认测试项失败：{message}")
                return
            try:
                default_order = TestItemConfigStore(default_config_path).load().order
            except Exception as exc:  # noqa: BLE001 - 默认模板损坏需明确提示
                messagebox.showerror(
                    "恢复默认失败",
                    f"读取默认测试项配置失败：{exc}",
                    parent=self.test_item_config_window,
                )
                self._log(f"[测试项配置] 恢复默认测试项失败：{exc}")
                return
            load(default_order)
            mark_dirty()
            self._log(
                f"[测试项配置] 已从 {default_config_path.name} 恢复 "
                f"{len(default_order.items)} 条默认测试项到界面，等待保存"
            )
            messagebox.showinfo(
                "已恢复默认",
                f"已恢复 {len(default_order.items)} 条默认测试项。\n请点击窗口底部“保存”写入正式配置。",
                parent=self.test_item_config_window,
            )

        ttk.Button(
            bottom_bar,
            text="恢复默认",
            width=12,
            command=restore_default,
            style="Secondary.TButton",
        ).pack(side="left", padx=(8, 0))

        def capture(pretest: bool = False) -> OrderConfig:
            items: list[OrderItem] = []
            for row_dict in row_widgets:
                segments = [
                    ExpectedSegment(
                        text=seg["var"].get(),
                        negate=bool(seg["negate_var"].get()),
                    )
                    for seg in row_dict["segments"]
                    if seg["var"].get().strip()
                ]
                command = row_dict["command_var"].get().strip()
                if not command and not segments:
                    # 完全空行跳过,不写入 ini。
                    continue
                items.append(
                    OrderItem(
                        command=command,
                        expected_segments=segments,
                        retry_times=1 if pretest else int(row_dict["retry_var"].get() or 1),
                    )
                )
            return OrderConfig(
                command_fail_retry_interval_time=0 if pretest else int(interval_var.get() or DEFAULT_COMMAND_FAIL_RETRY_INTERVAL),
                items=items,
            )

        def load(new_order: OrderConfig) -> None:
            interval_var.set(new_order.command_fail_retry_interval_time or DEFAULT_COMMAND_FAIL_RETRY_INTERVAL)
            _clear_test_item_rows(row_widgets)
            if new_order.items:
                for item in new_order.items:
                    add_row(item)
            else:
                add_row(OrderItem())

        return {"capture": capture, "load": load}

    def _capture_pretest_request(self, order: OrderConfig, telnet: TelnetSettings):
        self._capture_current_channel()
        return prepare_pretest_request(self._selected_channels(), order, telnet)

    def _build_test_item_ui_defaults_tab(
        self,
        notebook: ttk.Notebook,
        values: dict[str, str],
        mark_dirty,
    ) -> dict:
        """动态构建旧工具 ``config.ini [ui_defaults]`` 独立 Tab。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="开关机运行参数")

        Label(
            frame,
            text="旧工具界面与运行参数",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(0, 6))
        Label(
            frame,
            text=(
                "这里显示 config.ini [ui_defaults] 的开关机运行时间参数。"
                "通信方式、Telnet Enable、波特率和默认方案由其它配置维护，本页不重复显示；"
                "保存不会改动 config.ini 的其它配置段。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        rows_frame = ttk.Frame(frame, style="App.TFrame")
        rows_frame.pack(fill="both", expand=True)
        variables: dict[str, StringVar] = {}
        option_order: list[str] = []
        loaded_values: dict[str, str] = {}
        descriptions = {
            "communication_method": "ONU 通信方式（telnet / ssh）",
            "telnet_enable": "是否执行 Telnet 开启动作（由 Telnet 页反向同步）",
            "baud_rate": "程控电源串口波特率",
            "selected_profile": "旧工具默认测试方案",
            "startup_time": "设备启动等待时间（秒）",
            "interval_time": "每轮断电等待时间（秒）",
            "number_of_tests": "测试循环次数",
            "wait_command_done": "命令完成后等待时间（秒）",
        }

        def render(new_values: dict[str, str]) -> None:
            for child in rows_frame.winfo_children():
                child.destroy()
            variables.clear()
            option_order.clear()
            loaded_values.clear()
            loaded_values.update({key: str(value) for key, value in new_values.items()})
            row = 0
            for option, value in new_values.items():
                if option.lower() in TEST_ITEM_HIDDEN_UI_DEFAULT_OPTIONS:
                    continue
                option_order.append(option)
                Label(
                    rows_frame,
                    text=descriptions.get(option.lower(), option),
                    width=32,
                    anchor="w",
                    background=COLOR_BG,
                    foreground=COLOR_TEXT,
                ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=7)
                variable = StringVar(value=str(value))
                variable.trace_add("write", lambda *_args: mark_dirty())
                variables[option] = variable
                entry = ttk.Entry(rows_frame, textvariable=variable, width=28)
                entry.grid(row=row, column=1, sticky="ew", pady=7)
                row += 1
            rows_frame.columnconfigure(1, weight=1)

        def capture() -> dict[str, str]:
            captured = dict(loaded_values)
            captured.update(
                {option: variables[option].get().strip() for option in option_order}
            )
            return captured

        def load(new_values: dict[str, str]) -> None:
            render(new_values)

        render(values)
        return {"capture": capture, "load": load}

    def _build_test_item_wifi_tab(
        self,
        notebook: ttk.Notebook,
        wifi: ConnectWifiSettings,
        mark_dirty,
    ) -> dict:
        """构建 [connect_wifi] 段 Tab。返回 ``{"capture": Callable, "load": Callable}``。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="WiFi")

        enable_var = IntVar(value=wifi.enable)
        test_2g_var = IntVar(value=wifi.test_2g_enable)
        test_5g_var = IntVar(value=wifi.test_5g_enable)
        solution_var = StringVar(value=wifi.product_solution or "openwrt")
        auth_mode_var = StringVar(value=wifi.auth_mode or "WPA2-PSK")
        cipher_var = StringVar(value=wifi.cipher or "AES")
        choose_wireless_card_var = IntVar(value=wifi.choose_wireless_card)
        wireless_card_name_var = StringVar(value=wifi.wireless_card_name or "")
        for variable in (
            enable_var,
            test_2g_var,
            test_5g_var,
            solution_var,
            auth_mode_var,
            cipher_var,
            choose_wireless_card_var,
            wireless_card_name_var,
        ):
            variable.trace_add("write", lambda *_a: mark_dirty())

        Label(
            frame,
            text="WiFi 连接测试",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        connection_frame = Frame(frame, background=COLOR_BG)
        connection_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        for column, (text, variable) in enumerate(
            (
                ("连接 WiFi（主控）", enable_var),
                ("测试 2.4G WiFi", test_2g_var),
                ("测试 5G WiFi", test_5g_var),
            )
        ):
            Checkbutton(
                connection_frame,
                text=text,
                variable=variable,
                onvalue=1,
                offvalue=0,
                background=COLOR_BG,
                activebackground=COLOR_BG,
                highlightthickness=0,
                borderwidth=0,
            ).grid(row=0, column=column, sticky="w", padx=(0, 28))

        Label(frame, text="ONU 方案类型", width=18, anchor="w", background=COLOR_BG).grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        solution_combo = ttk.Combobox(
            frame,
            textvariable=solution_var,
            values=("openwrt", "bcm", "mtk"),
            state="readonly",
            width=18,
        )
        solution_combo.grid(row=2, column=1, sticky="w", pady=6)

        Label(frame, text="认证方式", width=14, anchor="w", background=COLOR_BG).grid(
            row=2, column=2, sticky="w", padx=(24, 12), pady=6
        )
        auth_values = tuple(dict.fromkeys((*WIFI_AUTH_MODE_OPTIONS, auth_mode_var.get())))
        ttk.Combobox(
            frame,
            textvariable=auth_mode_var,
            values=auth_values,
            state="readonly",
            width=24,
        ).grid(row=2, column=3, sticky="w", pady=6)

        Label(frame, text="加密算法", width=18, anchor="w", background=COLOR_BG).grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=6
        )
        cipher_values = tuple(dict.fromkeys((*WIFI_CIPHER_OPTIONS, cipher_var.get())))
        ttk.Combobox(
            frame,
            textvariable=cipher_var,
            values=cipher_values,
            state="readonly",
            width=18,
        ).grid(row=3, column=1, sticky="w", pady=6)

        Checkbutton(
            frame,
            text="指定无线网卡",
            variable=choose_wireless_card_var,
            onvalue=1,
            offvalue=0,
            background=COLOR_BG,
            activebackground=COLOR_BG,
            highlightthickness=0,
            borderwidth=0,
        ).grid(row=4, column=0, sticky="w", pady=(14, 6))
        initial_card_values = (
            (wireless_card_name_var.get(),) if wireless_card_name_var.get().strip() else ()
        )
        wireless_card_combo = ttk.Combobox(
            frame,
            textvariable=wireless_card_name_var,
            values=initial_card_values,
            state="readonly",
            width=34,
        )
        wireless_card_combo.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(14, 6))

        def refresh_wireless_cards() -> None:
            try:
                names = list_wifi_interface_names()
            except Exception as exc:  # noqa: BLE001 - pywifi/驱动异常需反馈操作员
                self._log(f"[测试项配置][WiFi] 刷新无线网卡失败：{exc}")
                messagebox.showerror("刷新无线网卡失败", str(exc), parent=frame.winfo_toplevel())
                return
            wireless_card_combo.configure(values=names)
            current_name = wireless_card_name_var.get().strip()
            if not names:
                self._log("[测试项配置][WiFi] 当前电脑没有检测到可用无线网卡。")
                messagebox.showwarning(
                    "未发现无线网卡",
                    "当前电脑没有检测到可用无线网卡，请确认网卡已启用及驱动正常。",
                    parent=frame.winfo_toplevel(),
                )
                return
            if not current_name:
                wireless_card_name_var.set(names[0])
            self._log(
                f"[测试项配置][WiFi] 已刷新无线网卡：{len(names)} 个，"
                f"当前选择={wireless_card_name_var.get().strip() or '(未选择)'}"
            )

        ttk.Button(
            frame,
            text="刷新无线网卡",
            command=refresh_wireless_cards,
            style="Tool.TButton",
        ).grid(row=4, column=3, sticky="w", padx=(12, 0), pady=(14, 6))

        Label(
            frame,
            text=(
                "主控关闭时不执行 WiFi 测试；2.4G / 5G 选择会保留。"
                "ONU 方案保存时统一小写；指定网卡后，运行电脑找不到该网卡会明确失败，不会改用其它网卡。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=560,
            justify="left",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        def capture() -> ConnectWifiSettings:
            return ConnectWifiSettings(
                enable=int(enable_var.get()),
                test_2g_enable=int(test_2g_var.get()),
                test_5g_enable=int(test_5g_var.get()),
                product_solution=(solution_var.get() or "openwrt").strip().lower(),
                auth_mode=(auth_mode_var.get() or "WPA2-PSK").strip(),
                cipher=(cipher_var.get() or "AES").strip(),
                choose_wireless_card=int(choose_wireless_card_var.get()),
                wireless_card_name=wireless_card_name_var.get().strip(),
            )

        def load(new_wifi: ConnectWifiSettings) -> None:
            enable_var.set(int(new_wifi.enable))
            test_2g_var.set(int(new_wifi.test_2g_enable))
            test_5g_var.set(int(new_wifi.test_5g_enable))
            solution_var.set((new_wifi.product_solution or "openwrt").strip().lower())
            auth_mode_var.set(new_wifi.auth_mode or "WPA2-PSK")
            cipher_var.set(new_wifi.cipher or "AES")
            choose_wireless_card_var.set(int(new_wifi.choose_wireless_card))
            wireless_card_name_var.set(new_wifi.wireless_card_name or "")

        return {"capture": capture, "load": load, "refresh_wireless_cards": refresh_wireless_cards}

    def _build_test_item_project_info_tab(
        self,
        notebook: ttk.Notebook,
        info: ProjectInfoSettings,
        mark_dirty,
        telnet_supplier,
    ) -> dict:
        """构建 [project_info] 段 Tab，并提供只读样机版本查询。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="项目信息")

        project_name_var = StringVar(value=info.project_name or "")
        software_version_var = StringVar(value=info.software_version or "")
        internal_software_version_var = StringVar(value=info.internal_software_version or "")
        onu_compile_time_var = StringVar(value=info.onu_compile_time or "")
        queried_software_version_var = StringVar(value="未查询")
        queried_internal_software_version_var = StringVar(value="未查询")
        queried_onu_compile_time_var = StringVar(value="未查询")

        for var in (
            project_name_var,
            software_version_var,
            internal_software_version_var,
            onu_compile_time_var,
        ):
            var.trace_add("write", lambda *_a: mark_dirty())

        Label(
            frame,
            text="项目信息",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        def text_field(row: int, label: str, var: StringVar, width: int = 40) -> None:
            Label(frame, text=label, width=20, anchor="w", background=COLOR_BG).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            ttk.Entry(frame, textvariable=var, width=width).grid(
                row=row, column=1, sticky="we", pady=6
            )

        text_field(1, "项目名称", project_name_var)
        text_field(2, "软件版本", software_version_var)
        text_field(3, "内部软件版本", internal_software_version_var)
        text_field(4, "ONU 软件编译时间", onu_compile_time_var)

        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="we", pady=(10, 8)
        )
        Label(
            frame,
            text="当前样机查询结果（只读）",
            font=(FONT_FAMILY, 10, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 2))

        copy_target = [queried_software_version_var]
        copy_menu = Menu(frame, tearoff=0)

        def copy_query_result() -> None:
            self.clipboard_clear()
            self.clipboard_append(copy_target[0].get())
            query_status_var.set("已复制查询结果到剪贴板。")

        copy_menu.add_command(label="复制全部", command=copy_query_result)

        def show_copy_menu(event, var: StringVar) -> str:
            copy_target[0] = var
            copy_menu.tk_popup(event.x_root, event.y_root)
            copy_menu.grab_release()
            return "break"

        def read_only_result_field(row: int, label: str, var: StringVar) -> None:
            Label(frame, text=label, width=20, anchor="w", background=COLOR_BG).grid(
                row=row, column=0, sticky="nw", padx=(0, 12), pady=4
            )
            field = ttk.Entry(
                frame,
                textvariable=var,
                width=50,
                state="readonly",
            )
            field.grid(row=row, column=1, sticky="we", pady=4)
            field.bind("<Button-3>", lambda event: show_copy_menu(event, var))

        read_only_result_field(7, "软件版本", queried_software_version_var)
        read_only_result_field(8, "内部软件版本", queried_internal_software_version_var)
        read_only_result_field(9, "ONU 软件编译时间", queried_onu_compile_time_var)

        query_status_var = StringVar(
            value="查询将使用主界面当前选中通道，以及 Telnet 页当前填写的连接参数。"
        )

        def apply_query_result(result: DeviceProjectInfo) -> None:
            queried_software_version_var.set(result.software_version)
            queried_internal_software_version_var.set(result.internal_software_version)
            queried_onu_compile_time_var.set(result.onu_compile_time)
            query_status_var.set("查询成功，结果仅供查看，不会覆盖手动输入或写入 INI。")

        ttk.Button(
            frame,
            text="查询当前样机版本",
            command=lambda: self._start_project_info_query(
                telnet_supplier(), apply_query_result
            ),
            style="Secondary.TButton",
        ).grid(row=10, column=1, sticky="w", pady=(10, 4))

        Label(
            frame,
            text=(
                "登录成功提示符为 > 时先发送 Telnet 页的登录后命令（默认 sh），等待 1 秒，"
                "再读取 cat /etc/config/deviceinfo 与 cat /proc/version。"
                "查询结果独立只读显示，不会覆写上方可手动编辑的版本输入框，也不会写入 INI；"
                "可拖拽选择后按 Ctrl+C，或右键选择“复制全部”。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=560,
            justify="left",
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 0))
        Label(
            frame,
            textvariable=query_status_var,
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=560,
            justify="left",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(4, 0))

        frame.columnconfigure(1, weight=1)

        def capture() -> ProjectInfoSettings:
            return ProjectInfoSettings(
                project_name=project_name_var.get().strip(),
                software_version=software_version_var.get().strip(),
                internal_software_version=internal_software_version_var.get().strip(),
                onu_compile_time=onu_compile_time_var.get().strip(),
            )

        def load(new_info: ProjectInfoSettings) -> None:
            project_name_var.set(new_info.project_name or "")
            software_version_var.set(new_info.software_version or "")
            internal_software_version_var.set(new_info.internal_software_version or "")
            onu_compile_time_var.set(new_info.onu_compile_time or "")

        return {"capture": capture, "load": load}

    def _start_project_info_query(self, telnet: TelnetSettings, on_success) -> None:
        """以当前通道及 Telnet 页参数登录、查询版本，并在主线程回填结果。"""
        self._capture_current_channel()
        if not 0 <= self.current_index < len(self.channels):
            messagebox.showwarning(
                "未选择通道", "请先在主界面选择要查询的样机通道。", parent=self.test_item_config_window
            )
            return
        channel = self.channels[self.current_index]
        bind_ip = (channel.network_card_ip or "").strip()
        device_host = (channel.device_manage_ip or "").strip()
        if not bind_ip or not device_host:
            messagebox.showwarning(
                "通道信息不完整",
                "当前通道缺少 PC 静态 IP 或样机管理 IP，请先在主界面完成通道配置。",
                parent=self.test_item_config_window,
            )
            return
        if telnet.login_success_flag == ">":
            if not messagebox.askyesno(
                "确认查询样机版本",
                f"当前通道 {channel.section}：PC {bind_ip} → 样机 {device_host}:{telnet.port}。\n\n"
                + describe_telnet_post_login(telnet)
                + "\n随后执行 cat /etc/config/deviceinfo 和 cat /proc/version 查询版本。\n是否继续？",
                parent=self.test_item_config_window,
            ):
                self._log("[项目信息] 操作员取消登录后命令确认，跳过查询。")
                return
        request = DeviceProjectInfoQueryRequest(
            bind_ip=bind_ip, device_host=device_host, telnet=telnet
        )
        self._log(
            f"[项目信息] 开始查询当前通道 {channel.section}（{channel.vlan_name or channel.adapter_alias}）："
            f"PC {bind_ip} → 样机 {device_host}。"
        )

        self._project_info_query_count = getattr(self, "_project_info_query_count", 0) + 1

        def query_finished() -> None:
            self._project_info_query_count = max(0, self._project_info_query_count - 1)

        def worker() -> None:
            try:
                result = query_device_project_info(
                    request, emit=lambda line: self.log_queue.put(line)
                )
            except Exception as exc:  # noqa: BLE001 - 网络/登录/解析错误均需反馈到主线程
                self.after(
                    0,
                    lambda error=str(exc): messagebox.showerror(
                        "查询样机版本失败", error, parent=self.test_item_config_window
                    ),
                )
                self.log_queue.put(f"[项目信息] 查询失败：{exc}")
                return
            finally:
                self.after(0, query_finished)
            self.after(0, lambda: on_success(result))

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            query_finished()
            raise

    def _serial_log_directory(self) -> Path:
        return DEFAULT_LOG_DIR

    def _attach_serial_upgrade(self, vlan: str, session, log_path: Path) -> None:
        self.serial_terminal.attach_upgrade(
            vlan,
            session,
            log_path,
            port=self._serial_port_for_vlan(vlan),
        )

    def _open_serial_log_module(self, vlans: list[str] | None = None) -> None:
        targets = (
            self._serial_targets_for_vlans(vlans)
            if vlans is not None
            else self._selected_serial_targets()
        )
        if not targets:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选至少一个通道。", parent=self)
            return
        self.serial_terminal.show(targets)

    def _open_pipeline_serial_logs(self, vlans: list[str] | None = None) -> None:
        """全流程专用：显示串口日志窗口，并打开窗口中的全部串口。"""
        targets = (
            self._serial_targets_for_vlans(vlans)
            if vlans is not None
            else self._selected_serial_targets()
        )
        if not targets:
            raise RuntimeError("没有已勾选通道，无法打开串口日志")
        self.serial_terminal.show(targets)
        failed = self.serial_terminal.open_all()
        ports = ", ".join(
            f"{vlan.lower()}/{port or '(未配置COM)'}"
            for vlan, port in targets
        )
        if failed:
            failed_text = ", ".join(failed)
            self._log(
                f"[全流程][串口日志] 已执行打开全部；失败通道：{failed_text}；"
                f"目标：{ports}"
            )
            raise RuntimeError(f"部分串口未能打开：{failed_text}")
        self._log(
            f"[全流程][串口日志] 已执行打开全部，共 {len(targets)} 个通道：{ports}"
        )

    def _open_dut_config_module(self) -> None:
        """打开可扩展 DUT 配置窗口；首个 Tab 提供批量开启 Telnet。"""
        if self.dut_config_window is not None and self.dut_config_window.exists():
            self.dut_config_window.show()
            if not getattr(self, "dut_config_running", False):
                self._refresh_dut_config_targets()
            return

        self.dut_config_window = DutConfigWindow(
            self,
            username_var=self.parameter_initial_username_var,
            password_var=self.parameter_initial_password_var,
            on_refresh=self._refresh_dut_config_targets,
            on_start=self._start_dut_telnet_enable,
            on_query_telnet=self._query_dut_telnet_status,
            on_start_wan=self._start_dut_wan_config,
            on_query_wan=self._query_dut_wan_connections,
            on_query_voice=self._query_dut_voice_status,
            on_query_tr069=self._query_dut_tr069_status,
            on_start_voice=self._start_dut_voice_config,
            on_start_tr069=self._start_dut_tr069_config,
            on_start_wifi_2g=self._start_dut_wifi_2g_config,
            on_query_wifi_2g=self._query_dut_wifi_2g_status,
            on_start_wifi_5g=self._start_dut_wifi_5g_config,
            on_query_wifi_5g=self._query_dut_wifi_5g_status,
            on_stop=self._stop_dut_telnet_enable,
            on_close=self._close_dut_config_module,
            on_first_paint_refresh=lambda: self._log(
                "[DUT配置] 已触发客户区首帧尺寸刷新"
            ),
        )
        self._refresh_dut_config_targets()
        self._log(
            "[DUT配置] 已打开 Telnet、WAN、2.4G WiFi、5G WiFi、语音和 TR069 配置页；"
            "候选目标来自主界面已勾选通道，实际配置和查询按DUT窗口内勾选目标执行。"
        )

    def _collect_dut_telnet_requests(self, *, capture_current: bool = True) -> list[DutTelnetEnableRequest]:
        """把主界面已勾选通道快照转换成 DUT service 请求。"""
        if capture_current:
            self._capture_current_channel()
        username = self.parameter_initial_username_var.get().strip()
        password = self.parameter_initial_password_var.get()
        requests: list[DutTelnetEnableRequest] = []
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(
                channel.vlan_name or channel.adapter_alias
            ).strip()
            adapter_alias = adapter_alias_from_display(
                channel.adapter_alias or channel.vlan_name
            ).strip()
            requests.append(
                DutTelnetEnableRequest(
                    channel=channel.label,
                    vlan=vlan.lower() if vlan.lower().startswith("vlan") else vlan,
                    adapter_alias=adapter_alias,
                    bind_ip=(channel.network_card_ip or "").strip(),
                    device_host=(channel.device_manage_ip or "").strip(),
                    subnet_mask=(channel.subnet_mask or DEFAULT_SUBNET_MASK).strip(),
                    username=username,
                    password=password,
                    ubus_port=80,
                )
            )
        return requests

    def _dut_request_validation_errors(
        self, requests: list[DutTelnetEnableRequest]
    ) -> dict[str, str]:
        errors_by_channel: dict[str, list[str]] = {}
        channels_by_vlan: dict[str, list[str]] = {}
        for request in requests:
            errors_by_channel[request.channel] = list(
                validate_dut_telnet_request(request)
            )
            normalized_vlan = request.vlan.strip().casefold()
            if normalized_vlan:
                channels_by_vlan.setdefault(normalized_vlan, []).append(request.channel)
        for vlan, channels in channels_by_vlan.items():
            if len(channels) <= 1:
                continue
            duplicate_message = (
                f"VLAN {vlan} 被多个通道重复选择：{'、'.join(channels)}"
            )
            for channel in channels:
                errors_by_channel[channel].append(duplicate_message)
        return {
            channel: "配置错误：" + "；".join(errors)
            for channel, errors in errors_by_channel.items()
            if errors
        }

    def _refresh_dut_config_targets(self, *, capture_current: bool = True) -> None:
        if self.dut_config_running:
            return
        requests = self._collect_dut_telnet_requests() if capture_current else self._collect_dut_telnet_requests(capture_current=False)
        errors = self._dut_request_validation_errors(requests)
        self.dut_config_requests = requests
        self.dut_config_validation_errors = errors
        window = self.dut_config_window
        if window is not None and window.exists():
            window.set_targets(requests, errors)
            selected_count = len(window.selected_target_channels())
        else:
            selected_count = len(requests)
        self._log(
            f"[DUT配置] 已刷新目标：{len(requests)} 台，"
            f"DUT窗口已选择 {selected_count} 台，配置错误 {len(errors)} 台。"
        )

    def _selected_dut_config_requests(
        self, window: DutConfigWindow | None = None
    ) -> list[DutTelnetEnableRequest]:
        selected_window = window or self.dut_config_window
        if selected_window is None or not selected_window.exists():
            return []
        selected_channels = set(selected_window.selected_target_channels())
        return [
            request for request in self.dut_config_requests
            if request.channel in selected_channels
        ]

    def _start_dut_telnet_enable(self) -> None:
        if self.dut_config_running:
            return
        self._refresh_dut_config_targets()
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        requests = LineCheckAssistant._selected_dut_config_requests(self, window)
        if not requests:
            messagebox.showwarning(
                "没有目标 DUT",
                (
                    "请先在主界面勾选至少一个通道并完成 VLAN 配置。"
                    if not self.dut_config_requests
                    else "请在DUT配置目标表中至少勾选一台目标样机。"
                ),
                parent=window.window,
            )
            return
        selected_errors = LineCheckAssistant._dut_request_validation_errors(
            self, requests
        )
        if selected_errors:
            details = "\n".join(
                f"- {channel}：{message.removeprefix('配置错误：')}"
                for channel, message in selected_errors.items()
            )
            messagebox.showerror(
                "DUT 配置不完整",
                f"请先修正以下配置：\n{details}",
                parent=window.window,
            )
            return
        parallel_count = clamp_dut_parallel_count(
            window.parallel_count() or DEFAULT_DUT_PARALLEL_COUNT
        )
        target_lines = "\n".join(
            f"- {request.channel} / {request.vlan} / "
            f"{request.bind_ip} → {request.device_host}:23"
            for request in requests
        )
        if not messagebox.askyesno(
            "确认批量开启 Telnet",
            f"将处理 {len(requests)} 台 DUT，并行数 {parallel_count}：\n"
            f"{target_lines}\n\n"
            "每台将依次启用 VLAN 网卡、设置 PC 静态 IP、通过 UBUS 修改 "
            "AccessCtrl Telnet 规则，并从对应源 IP 验证 TCP 23 端口。\n\n"
            "这会修改本机网卡配置和 DUT 防火墙规则，是否继续？",
            parent=window.window,
        ):
            self._log("[DUT配置] 操作员取消批量开启 Telnet，本次未下发命令。")
            return

        self.dut_config_running = True
        self.dut_config_active_feature = "telnet"
        self.dut_config_cancel_event = threading.Event()
        window.mark_all_pending()
        window.set_running(True)
        window.set_summary(
            f"正在执行：共 {len(requests)} 台，并行数 {parallel_count}"
        )
        self._log(
            f"[DUT配置] 开始批量开启 Telnet：{len(requests)} 台，"
            f"并行数 {parallel_count}。"
        )
        threading.Thread(
            target=self._dut_telnet_enable_worker,
            args=(requests, parallel_count, self.dut_config_cancel_event),
            name="dut-telnet-batch",
            daemon=True,
        ).start()

    def _dut_telnet_enable_worker(
        self,
        requests: list[DutTelnetEnableRequest],
        parallel_count: int,
        cancel_event: threading.Event,
    ) -> None:
        try:
            results = run_dut_telnet_enable_batch(
                requests,
                max_workers=parallel_count,
                stop_event=cancel_event,
                on_output=self.log_queue.put,
                on_item_complete=lambda result: self.dut_config_ui_queue.put(
                    ("item", "telnet", result)
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 批次边界必须回收 UI 状态
            self.log_queue.put(f"[DUT配置] 批次异常：{exc}")
            results = [
                DutTelnetEnableResult(
                    request,
                    False,
                    "exception",
                    f"DUT 配置批次异常：{exc}",
                )
                for request in requests
            ]
            for result in results:
                self.dut_config_ui_queue.put(("item", "telnet", result))
        self.dut_config_ui_queue.put(("finished", "telnet", results))

    def _finish_dut_telnet_enable(
        self, results: list[DutTelnetEnableResult]
    ) -> None:
        success_count = sum(1 for result in results if result.ok)
        stopped_count = sum(1 for result in results if result.stage == "stopped")
        failure_count = len(results) - success_count - stopped_count
        self.dut_config_running = False
        self.dut_config_active_feature = None
        self.dut_config_cancel_event = None
        summary = (
            f"DUT Telnet 配置结束：成功 {success_count}，失败 {failure_count}，"
            f"停止/跳过 {stopped_count}，共 {len(results)} 台"
        )
        self._log(f"[DUT配置] {summary}")
        window = self.dut_config_window
        if window is not None and window.exists():
            window.set_running(False)
            window.set_summary(summary)
            window.clear_current_status(
                "telnet", "Telnet配置已执行，请重新查询当前状态。"
            )
            if failure_count or stopped_count:
                messagebox.showwarning("DUT 配置结束", summary, parent=window.window)
            else:
                messagebox.showinfo("DUT 配置完成", summary, parent=window.window)

    def _collect_dut_advanced_requests(
        self,
        feature: str,
        settings: DutWanSettings | DutVoiceSettings | DutTr069Settings | DutWifiSettings,
        *,
        increment_wifi_ssid: bool = False,
    ) -> list[DutAdvancedConfigRequest]:
        """复用当前通道快照，为高级 DUT Tab 附加本批次功能参数。"""
        selected_requests = LineCheckAssistant._selected_dut_config_requests(self)
        if feature in {"wifi_2g", "wifi_5g"} and isinstance(
            settings, DutWifiSettings
        ):
            settings_sequence = build_dut_wifi_settings_sequence(
                settings,
                len(selected_requests),
                increment_enabled=increment_wifi_ssid,
            )
        else:
            settings_sequence = tuple(settings for _request in selected_requests)
        return [
            DutAdvancedConfigRequest(
                channel=request.channel,
                vlan=request.vlan,
                adapter_alias=request.adapter_alias,
                bind_ip=request.bind_ip,
                device_host=request.device_host,
                subnet_mask=request.subnet_mask,
                username=request.username,
                password=request.password,
                ubus_port=request.ubus_port,
                feature=feature,
                settings=target_settings,
            )
            for request, target_settings in zip(
                selected_requests, settings_sequence
            )
        ]

    def _start_dut_wan_config(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._start_dut_advanced_config("wan", window.wan_settings())

    def _query_dut_wan_connections(self) -> None:
        """启动只读 WAN 查询；业务流程由 service 执行。"""
        if self.dut_config_running:
            return
        self._refresh_dut_config_targets()
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        requests = LineCheckAssistant._selected_dut_config_requests(self, window)
        if not requests:
            messagebox.showwarning(
                "没有目标 DUT",
                (
                    "请先在主界面勾选至少一个通道并完成 VLAN 配置。"
                    if not self.dut_config_requests
                    else "请在DUT配置目标表中至少勾选一台目标样机。"
                ),
                parent=window.window,
            )
            return
        selected_errors = LineCheckAssistant._dut_request_validation_errors(
            self, requests
        )
        if selected_errors:
            details = "\n".join(
                f"- {channel}：{message.removeprefix('配置错误：')}"
                for channel, message in selected_errors.items()
            )
            messagebox.showerror(
                "WAN 查询条件不完整",
                f"请先修正以下配置：\n{details}",
                parent=window.window,
            )
            return

        parallel_count = clamp_dut_parallel_count(
            window.parallel_count() or DEFAULT_DUT_PARALLEL_COUNT
        )
        self.dut_config_running = True
        self.dut_config_active_feature = "wan_query"
        self.dut_config_cancel_event = threading.Event()
        window.clear_wan_connections("正在查询当前目标 DUT 的现有 WAN……")
        window.clear_current_status("wan", "正在查询当前目标 DUT 的WAN状态……")
        window.mark_all_pending("wan")
        window.set_running(True)
        window.set_summary(
            f"正在查询现有 WAN：共 {len(requests)} 台，并行数 {parallel_count}",
            "wan",
        )
        self._log(
            f"[DUT配置][WAN查询] 开始只读查询：{len(requests)} 台，"
            f"并行数 {parallel_count}；仅共同存在的连接会进入下拉列表。"
        )
        threading.Thread(
            target=self._dut_wan_query_worker,
            args=(requests, parallel_count, self.dut_config_cancel_event),
            name="dut-wan-query-batch",
            daemon=True,
        ).start()

    def _dut_wan_query_worker(
        self,
        requests: list[DutTelnetEnableRequest],
        parallel_count: int,
        cancel_event: threading.Event,
    ) -> None:
        try:
            results = run_dut_wan_query_batch(
                requests,
                max_workers=parallel_count,
                stop_event=cancel_event,
                on_output=self.log_queue.put,
                on_item_complete=lambda result: self.dut_config_ui_queue.put(
                    ("item", "wan_query", result)
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 批次边界必须回收 UI 状态
            self.log_queue.put(f"[DUT配置][WAN查询] 批次异常：{exc}")
            results = [
                DutWanQueryResult(
                    request, False, "exception", f"WAN 查询批次异常：{exc}"
                )
                for request in requests
            ]
            for result in results:
                self.dut_config_ui_queue.put(("item", "wan_query", result))
        self.dut_config_ui_queue.put(("finished", "wan_query", results))

    def _finish_dut_wan_query(self, results: list[DutWanQueryResult]) -> None:
        success_count = sum(1 for result in results if result.ok)
        stopped_count = sum(1 for result in results if result.stage == "stopped")
        failure_count = len(results) - success_count - stopped_count
        common_names = common_wan_connection_names(results)
        common_details = common_wan_connection_details(results)
        self.dut_config_running = False
        self.dut_config_active_feature = None
        self.dut_config_cancel_event = None
        summary = (
            f"WAN 查询结束：成功 {success_count}，失败 {failure_count}，"
            f"停止/跳过 {stopped_count}，共同 WAN {len(common_names)} 个"
        )
        self._log(f"[DUT配置][WAN查询] {summary}：{list(common_names)}")
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        window.set_running(False)
        window.set_summary(summary, "wan")
        window.set_wan_current_status_results(results)
        if failure_count or stopped_count:
            window.clear_wan_connections(
                "部分 DUT 查询失败或停止，未生成批量修改/删除下拉列表。"
            )
            messagebox.showwarning("WAN 查询未完成", summary, parent=window.window)
        else:
            window.set_wan_connections(
                common_names,
                target_count=len(results),
                connection_details=common_details,
            )
            messagebox.showinfo("WAN 查询完成", summary, parent=window.window)

    def _start_dut_voice_config(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._start_dut_advanced_config("voice", window.voice_settings())

    def _query_dut_telnet_status(self) -> None:
        self._query_dut_current_status("telnet")

    def _query_dut_voice_status(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._query_dut_current_status("voice", line_index=window.voice_line_index())

    def _query_dut_tr069_status(self) -> None:
        self._query_dut_current_status("tr069")

    def _start_dut_wifi_2g_config(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._start_dut_advanced_config("wifi_2g", window.wifi_settings("wifi_2g"))

    def _start_dut_wifi_5g_config(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._start_dut_advanced_config("wifi_5g", window.wifi_settings("wifi_5g"))

    def _query_dut_wifi_2g_status(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._query_dut_current_status(
            "wifi_2g", ssid_index=window.wifi_ssid_index("wifi_2g")
        )

    def _query_dut_wifi_5g_status(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._query_dut_current_status(
            "wifi_5g", ssid_index=window.wifi_ssid_index("wifi_5g")
        )

    def _query_dut_current_status(
        self,
        feature: str,
        *,
        line_index: str = "1",
        ssid_index: str = "1",
    ) -> None:
        """启动DUT只读状态查询，查询参数不依赖当前配置表单完整性。"""
        if self.dut_config_running:
            return
        self._refresh_dut_config_targets()
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        requests = LineCheckAssistant._selected_dut_config_requests(self, window)
        feature_label = {
            "telnet": "Telnet", "voice": "语音", "tr069": "TR069",
            "wifi_2g": "2.4G WiFi", "wifi_5g": "5G WiFi",
        }[feature]
        if not requests:
            messagebox.showwarning(
                "没有目标 DUT",
                (
                    "请先在主界面勾选至少一个通道并完成 VLAN 配置。"
                    if not self.dut_config_requests
                    else "请在DUT配置目标表中至少勾选一台目标样机。"
                ),
                parent=window.window,
            )
            return
        selected_errors = LineCheckAssistant._dut_request_validation_errors(
            self, requests
        )
        if selected_errors:
            details = "\n".join(
                f"- {channel}：{message.removeprefix('配置错误：')}"
                for channel, message in selected_errors.items()
            )
            messagebox.showerror(
                f"{feature_label}查询条件不完整",
                f"请先修正以下配置：\n{details}",
                parent=window.window,
            )
            return
        if feature == "voice":
            try:
                if not 1 <= int(line_index) <= 8:
                    raise ValueError
            except (TypeError, ValueError):
                messagebox.showerror(
                    "语音查询条件不完整",
                    f"语音线路索引必须为 1–8：{line_index}",
                    parent=window.window,
                )
                return
        if feature in {"wifi_2g", "wifi_5g"}:
            try:
                if not 1 <= int(ssid_index) <= 8:
                    raise ValueError
            except (TypeError, ValueError):
                messagebox.showerror(
                    f"{feature_label}查询条件不完整",
                    f"SSID 索引必须为 1–8：{ssid_index}",
                    parent=window.window,
                )
                return

        parallel_count = clamp_dut_parallel_count(
            window.parallel_count() or DEFAULT_DUT_PARALLEL_COUNT
        )
        query_feature = f"{feature}_query"
        self.dut_config_running = True
        self.dut_config_active_feature = query_feature
        self.dut_config_cancel_event = threading.Event()
        window.clear_current_status(feature, f"正在查询当前{feature_label}状态……")
        window.mark_all_pending(feature)
        window.set_running(True)
        window.set_summary(
            f"正在查询当前{feature_label}状态：共 {len(requests)} 台，并行数 {parallel_count}",
            feature,
        )
        line_text = f"，线路 {line_index}" if feature == "voice" else ""
        if feature in {"wifi_2g", "wifi_5g"}:
            line_text = f"，SSID索引 {ssid_index}"
        self._log(
            f"[DUT配置][{feature_label}查询] 开始只读查询：{len(requests)} 台，"
            f"并行数 {parallel_count}{line_text}；不会下发配置命令。"
        )
        threading.Thread(
            target=self._dut_current_status_query_worker,
            args=(
                feature, requests, line_index, ssid_index,
                parallel_count, self.dut_config_cancel_event,
            ),
            name=f"dut-{feature}-status-query-batch",
            daemon=True,
        ).start()

    def _dut_current_status_query_worker(
        self,
        feature: str,
        requests: list[DutTelnetEnableRequest],
        line_index: str,
        ssid_index: str,
        parallel_count: int,
        cancel_event: threading.Event,
    ) -> None:
        query_feature = f"{feature}_query"
        feature_label = {
            "telnet": "Telnet", "voice": "语音", "tr069": "TR069",
            "wifi_2g": "2.4G WiFi", "wifi_5g": "5G WiFi",
        }[feature]
        try:
            results = run_dut_status_query_batch(
                requests,
                feature,
                line_index=line_index,
                ssid_index=ssid_index,
                max_workers=parallel_count,
                stop_event=cancel_event,
                on_output=self.log_queue.put,
                on_item_complete=lambda result: self.dut_config_ui_queue.put(
                    ("item", query_feature, result)
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 批次边界必须回收UI状态
            self.log_queue.put(f"[DUT配置][{feature_label}查询] 批次异常：{exc}")
            results = [
                DutAdvancedQueryResult(
                    request,
                    feature,
                    False,
                    "exception",
                    f"{feature_label}查询批次异常：{exc}",
                )
                for request in requests
            ]
            for result in results:
                self.dut_config_ui_queue.put(("item", query_feature, result))
        self.dut_config_ui_queue.put(("finished", query_feature, results))

    def _finish_dut_current_status_query(
        self,
        feature: str,
        results: list[DutAdvancedQueryResult],
    ) -> None:
        feature_label = {
            "telnet": "Telnet", "voice": "语音", "tr069": "TR069",
            "wifi_2g": "2.4G WiFi", "wifi_5g": "5G WiFi",
        }[feature]
        success_count = sum(1 for result in results if result.ok)
        stopped_count = sum(1 for result in results if result.stage == "stopped")
        failure_count = len(results) - success_count - stopped_count
        common_settings = common_dut_status_settings(results)
        if feature == "telnet":
            consistency = "已展示当前状态"
        else:
            consistency = "参数一致，已同步表单" if common_settings is not None else "未自动覆盖表单"
        self.dut_config_running = False
        self.dut_config_active_feature = None
        self.dut_config_cancel_event = None
        summary = (
            f"{feature_label}查询结束：成功 {success_count}，失败 {failure_count}，"
            f"停止/跳过 {stopped_count}，共 {len(results)} 台；{consistency}"
        )
        self._log(f"[DUT配置][{feature_label}查询] {summary}")
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        window.set_running(False)
        window.set_summary(summary, feature)
        window.set_current_status_results(feature, results, common_settings)
        if failure_count or stopped_count:
            messagebox.showwarning(
                f"{feature_label}查询未完成", summary, parent=window.window
            )
        else:
            messagebox.showinfo(
                f"{feature_label}查询完成", summary, parent=window.window
            )

    def _start_dut_tr069_config(self) -> None:
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        self._start_dut_advanced_config("tr069", window.tr069_settings())

    def _start_dut_advanced_config(
        self,
        feature: str,
        settings: DutWanSettings | DutVoiceSettings | DutTr069Settings | DutWifiSettings,
    ) -> None:
        if self.dut_config_running:
            return
        self._refresh_dut_config_targets()
        window = self.dut_config_window
        if window is None or not window.exists():
            return
        feature_label = {
            "wan": "WAN", "voice": "语音", "tr069": "TR069",
            "wifi_2g": "2.4G WiFi", "wifi_5g": "5G WiFi",
        }[feature]
        increment_wifi_ssid = (
            feature in {"wifi_2g", "wifi_5g"}
            and window.wifi_ssid_increment_enabled(feature)
        )
        try:
            requests = self._collect_dut_advanced_requests(
                feature,
                settings,
                increment_wifi_ssid=increment_wifi_ssid,
            )
        except ValueError as exc:
            self._log(
                f"[DUT配置][{feature_label}配置] SSID递增预检失败：{exc}"
            )
            messagebox.showerror(
                "SSID递增条件不完整", str(exc), parent=window.window
            )
            return
        if not requests:
            messagebox.showwarning(
                "没有目标 DUT",
                (
                    "请先在主界面勾选至少一个通道并完成 VLAN 配置。"
                    if not self.dut_config_requests
                    else "请在DUT配置目标表中至少勾选一台目标样机。"
                ),
                parent=window.window,
            )
            return
        shared_wifi_settle = increment_wifi_ssid and len(requests) > 1
        errors_by_channel: dict[str, list[str]] = {}
        selected_common_errors = LineCheckAssistant._dut_request_validation_errors(
            self,
            [
                DutTelnetEnableRequest(
                    channel=request.channel,
                    vlan=request.vlan,
                    adapter_alias=request.adapter_alias,
                    bind_ip=request.bind_ip,
                    device_host=request.device_host,
                    subnet_mask=request.subnet_mask,
                    username=request.username,
                    password=request.password,
                    ubus_port=request.ubus_port,
                )
                for request in requests
            ]
        )
        for request in requests:
            errors_by_channel[request.channel] = list(validate_dut_advanced_request(request))
            common_error = selected_common_errors.get(request.channel, "")
            if common_error:
                errors_by_channel[request.channel].append(common_error.removeprefix("配置错误："))
        errors_by_channel = {
            channel: list(dict.fromkeys(errors))
            for channel, errors in errors_by_channel.items()
            if errors
        }
        if errors_by_channel:
            details = "\n".join(
                f"- {channel}：{'；'.join(errors)}"
                for channel, errors in errors_by_channel.items()
            )
            messagebox.showerror(
                f"{feature_label} 配置不完整",
                f"请先修正以下配置：\n{details}",
                parent=window.window,
            )
            return
        parallel_count = clamp_dut_parallel_count(
            window.parallel_count() or DEFAULT_DUT_PARALLEL_COUNT
        )
        target_lines_parts: list[str] = []
        for request in requests:
            line = (
                f"- {request.channel} / {request.vlan} / "
                f"{request.bind_ip} → {request.device_host}:{request.ubus_port}"
            )
            if feature in {"wifi_2g", "wifi_5g"} and isinstance(
                request.settings, DutWifiSettings
            ):
                line += f"；SSID={request.settings.ssid}"
            target_lines_parts.append(line)
        target_lines = "\n".join(target_lines_parts)
        operation_summary = ""
        warning = "这会修改 DUT 配置。"
        if feature == "wan" and isinstance(settings, DutWanSettings):
            operation_names = {"add": "新增", "modify": "修改", "delete": "删除"}
            operation_summary = (
                f"\nWAN 操作：{operation_names.get(settings.operation, settings.operation)}；"
                f"连接名/索引：{settings.connection_index or '无'}；"
                f"业务 VLAN：{settings.vlan_id or '无'}；"
                f"协议：{settings.ip_protocol}。"
            )
            if settings.operation == "delete":
                warning = (
                    "危险：将删除每台 DUT 上指定索引的现有 WAN；"
                    "不会自动恢复，请确认索引对应关系一致。"
                )
        elif feature == "voice" and isinstance(settings, DutVoiceSettings):
            operation_summary = (
                f"\nSIP 线路：{settings.line_index}；注册服务器："
                f"{settings.registrar_server}:{settings.registrar_server_port}。"
            )
        elif feature == "tr069" and isinstance(settings, DutTr069Settings):
            operation_summary = (
                f"\nACS：{settings.acs_url}；"
                f"手动 Inform：{'是' if settings.manual_inform else '否'}。"
            )
        elif feature in {"wifi_2g", "wifi_5g"} and isinstance(
            settings, DutWifiSettings
        ):
            operation_summary = (
                f"\n频段：{settings.band}；SSID索引：{settings.ssid_index}；"
                f"SSID递增：{'是' if increment_wifi_ssid else '否'}；"
                f"起始名称：{settings.ssid}；{settings.band}信道/带宽/协议："
                f"{settings.channel}/{settings.channel_bandwidth}/"
                f"{settings.operating_mode}；公共发射功率："
                f"{settings.transmit_power}%；"
                f"双频合一：{'是' if settings.dual_band_enabled else '否'}。"
            )
            if settings.dual_band_enabled and settings.peer_radio is not None:
                peer = settings.peer_radio
                operation_summary += (
                    f"\n{peer.band}信道/带宽/协议：{peer.channel}/"
                    f"{peer.channel_bandwidth}/{peer.operating_mode}。"
                )
            if shared_wifi_settle:
                operation_summary += (
                    "\n等待方式：全部目标下发完成后，仅最后一台统一等待60秒，"
                    "随后逐台回读校验。"
                )
            if settings.dual_band_enabled:
                warning = (
                    "这会把SSID、启用/隐藏、认证密码及AP参数同步到2.4G和5G，"
                    "分别修改两个频段的信道、带宽和协议，并把公共发射功率写入两个Radio。"
                )
        if not messagebox.askyesno(
            f"确认批量执行 {feature_label} 配置",
            f"将处理 {len(requests)} 台 DUT，并行数 {parallel_count}：\n"
            f"{target_lines}{operation_summary}\n\n"
            "每台将先启用 VLAN 网卡并设置 PC 静态 IP，再从对应源 IP 登录 UBUS。\n\n"
            f"{warning} 是否继续？",
            parent=window.window,
        ):
            self._log(f"[DUT配置][{feature_label}配置] 操作员取消，本次未下发命令。")
            return

        self.dut_config_running = True
        self.dut_config_active_feature = feature
        self.dut_config_cancel_event = threading.Event()
        window.mark_all_pending(feature)
        window.set_running(True)
        window.set_summary(
            f"正在执行：共 {len(requests)} 台，并行数 {parallel_count}", feature
        )
        self._log(
            f"[DUT配置][{feature_label}配置] 开始批量执行："
            f"{len(requests)} 台，并行数 {parallel_count}。"
        )
        if shared_wifi_settle:
            self._log(
                f"[DUT配置][{feature_label}配置] SSID递增批次等待策略："
                "全部目标先下发，仅最后一台统一等待60秒，再逐台回读校验。"
            )
        if feature in {"wifi_2g", "wifi_5g"}:
            for request in requests:
                if isinstance(request.settings, DutWifiSettings):
                    self._log(
                        f"[DUT配置][{feature_label}配置][SSID分配] "
                        f"{request.channel} / {request.vlan} → {request.settings.ssid}"
                    )
        threading.Thread(
            target=self._dut_advanced_config_worker,
            args=(
                feature,
                requests,
                parallel_count,
                self.dut_config_cancel_event,
                shared_wifi_settle,
            ),
            name=f"dut-{feature}-batch",
            daemon=True,
        ).start()

    def _dut_advanced_config_worker(
        self,
        feature: str,
        requests: list[DutAdvancedConfigRequest],
        parallel_count: int,
        cancel_event: threading.Event,
        shared_wifi_settle: bool = False,
    ) -> None:
        try:
            results = run_dut_advanced_config_batch(
                requests,
                max_workers=parallel_count,
                stop_event=cancel_event,
                on_output=self.log_queue.put,
                on_item_complete=lambda result: self.dut_config_ui_queue.put(
                    ("item", feature, result)
                ),
                shared_wifi_settle=shared_wifi_settle,
            )
        except Exception as exc:  # noqa: BLE001 - 批次边界必须回收 UI 状态
            self.log_queue.put(f"[DUT配置][{feature}] 批次异常：{exc}")
            results = [
                DutAdvancedConfigResult(
                    request, False, "exception", f"DUT 配置批次异常：{exc}"
                )
                for request in requests
            ]
            for result in results:
                self.dut_config_ui_queue.put(("item", feature, result))
        self.dut_config_ui_queue.put(("finished", feature, results))

    def _finish_dut_advanced_config(
        self,
        feature: str,
        results: list[DutAdvancedConfigResult],
    ) -> None:
        feature_label = {
            "wan": "WAN", "voice": "语音", "tr069": "TR069",
            "wifi_2g": "2.4G WiFi", "wifi_5g": "5G WiFi",
        }.get(feature, feature)
        success_count = sum(1 for result in results if result.ok)
        stopped_count = sum(1 for result in results if result.stage == "stopped")
        failure_count = len(results) - success_count - stopped_count
        self.dut_config_running = False
        self.dut_config_active_feature = None
        self.dut_config_cancel_event = None
        summary = (
            f"DUT {feature_label} 配置结束：成功 {success_count}，失败 {failure_count}，"
            f"停止/跳过 {stopped_count}，共 {len(results)} 台"
        )
        self._log(f"[DUT配置] {summary}")
        window = self.dut_config_window
        if window is not None and window.exists():
            if feature == "wan":
                window.clear_wan_connections("WAN 配置已执行，请重新查询最新连接列表。")
                window.clear_current_status("wan", "WAN配置已执行，请重新查询当前状态。")
            elif feature in {"voice", "tr069"}:
                feature_label = "语音" if feature == "voice" else "TR069"
                window.clear_current_status(
                    feature, f"{feature_label}配置已执行，请重新查询当前状态。"
                )
            elif feature in {"wifi_2g", "wifi_5g"}:
                band_label = "2.4G WiFi" if feature == "wifi_2g" else "5G WiFi"
                window.clear_current_status(
                    feature, f"{band_label}配置已执行，请重新查询当前状态。"
                )
                if any(
                    isinstance(result.request.settings, DutWifiSettings)
                    and result.request.settings.dual_band_enabled
                    for result in results
                ):
                    peer_feature = "wifi_5g" if feature == "wifi_2g" else "wifi_2g"
                    window.clear_current_status(
                        peer_feature, "双频合一配置已执行，请重新查询当前状态。"
                    )
            window.set_running(False)
            window.set_summary(summary, feature)
            if failure_count or stopped_count:
                messagebox.showwarning("DUT 配置结束", summary, parent=window.window)
            else:
                messagebox.showinfo("DUT 配置完成", summary, parent=window.window)

    def _stop_dut_telnet_enable(self) -> None:
        if not self.dut_config_running or self.dut_config_cancel_event is None:
            self._log("[DUT配置] 当前没有正在执行的配置批次。")
            return
        self.dut_config_cancel_event.set()
        window = self.dut_config_window
        if window is not None and window.exists():
            window.set_running(True, stopping=True)
        feature_label = {
            "telnet": "Telnet配置", "wan": "WAN配置", "wan_query": "WAN查询",
            "voice": "语音配置", "tr069": "TR069配置",
            "telnet_query": "Telnet查询", "voice_query": "语音查询",
            "tr069_query": "TR069查询",
            "wifi_2g": "2.4G WiFi配置", "wifi_5g": "5G WiFi配置",
            "wifi_2g_query": "2.4G WiFi查询", "wifi_5g_query": "5G WiFi查询",
        }.get(getattr(self, "dut_config_active_feature", None), "DUT配置")
        self._log(
            f"[DUT配置][{feature_label}] 操作员请求停止：尚未开始的 DUT 将跳过，"
            "正在执行的网络或 UBUS 调用将在安全点结束。"
        )

    def _close_dut_config_module(self) -> None:
        window = self.dut_config_window
        if window is None:
            return
        if self.dut_config_running:
            messagebox.showwarning(
                "DUT 配置进行中",
                "请先点击“停止”，等待当前批次安全结束后再关闭窗口。",
                parent=window.window,
            )
            return
        window.destroy()
        if self.dut_config_window is window:
            self.dut_config_window = None

    def _rebuild_channel_config_rows(self) -> None:
        for child in self.channel_table.winfo_children():
            child.destroy()
        self.channel_row_vars = {}

        selected_channels = [channel for channel in self.channels if channel.enabled]
        if not selected_channels:
            Label(self.channel_table, text="请在左侧勾选需要配置的通道。", foreground=COLOR_MUTED, background=COLOR_SURFACE).grid(row=0, column=0, sticky="w", pady=(0, 8))
            return

        group_count = 2 if len(selected_channels) > CHANNEL_TABLE_ROWS_PER_GROUP else 1
        rows_per_group = (len(selected_channels) + group_count - 1) // group_count
        headers = ["通道", "启用检查", "通道对应 VLAN", "通道对应 COM口"]
        for group in range(group_count):
            base_column = group * 5
            if group:
                self.channel_table.columnconfigure(base_column - 1, minsize=CHANNEL_TABLE_GROUP_GAP)
            self.channel_table.columnconfigure(base_column + 2, weight=1)
            for column, text in enumerate(headers):
                Label(self.channel_table, text=text, background=COLOR_SURFACE, foreground=COLOR_MUTED, font=(FONT_FAMILY, 9, "bold")).grid(
                    row=0,
                    column=base_column + column,
                    sticky="w",
                    padx=(0, 8),
                    pady=(0, 4),
                )

        vlan_options = self._current_vlan_options()
        serial_options = self._current_channel_serial_options()
        for index, channel in enumerate(selected_channels):
            group = index // rows_per_group
            row = index % rows_per_group + 1
            base_column = group * 5
            enabled_var = BooleanVar(value=channel.enabled)
            vlan_var = StringVar(value=channel.vlan_name or channel.adapter_alias)
            serial_var = StringVar(value=self._serial_port_for_channel(channel))
            self.channel_row_vars[channel.section] = {
                "enabled": enabled_var,
                "vlan": vlan_var,
                "serial_port": serial_var,
            }

            Label(self.channel_table, text=channel.section, width=12, anchor="w", background=COLOR_SURFACE, foreground=COLOR_TEXT).grid(row=row, column=base_column, sticky="w", padx=(0, 8), pady=4)
            Checkbutton(
                self.channel_table,
                variable=enabled_var,
                command=lambda section=channel.section: self._on_row_enabled_changed(section),
                background=COLOR_SURFACE,
                activebackground=COLOR_SURFACE,
                highlightthickness=0,
                borderwidth=0,
            ).grid(row=row, column=base_column + 1, sticky="w", padx=(0, 8), pady=4)
            vlan_combo = ttk.Combobox(
                self.channel_table,
                textvariable=vlan_var,
                values=vlan_options,
                width=CHANNEL_TABLE_COMBO_WIDTH,
                state="readonly",
            )
            vlan_combo.grid(row=row, column=base_column + 2, sticky="ew", padx=(0, 8), pady=3)
            vlan_combo.bind("<<ComboboxSelected>>", lambda _event, section=channel.section: self._on_row_vlan_changed(section))
            serial_combo = ttk.Combobox(
                self.channel_table,
                textvariable=serial_var,
                values=serial_options,
                width=CHANNEL_TABLE_SERIAL_COMBO_WIDTH,
                state="readonly",
            )
            serial_combo.grid(row=row, column=base_column + 3, sticky="w", padx=(0, 8), pady=3)
            serial_combo.bind(
                "<<ComboboxSelected>>",
                lambda _event, section=channel.section: self._on_row_serial_changed(section),
            )

    def _on_row_enabled_changed(self, section: str) -> None:
        channel = self._channel_by_section(section)
        if not channel:
            return
        self._capture_channel_row(channel)
        index = self.channels.index(channel)
        self._refresh_channel_list_item(index)
        self._select_channel_index(index)
        self._persist_config()

    def _on_row_vlan_changed(self, section: str) -> None:
        channel = self._channel_by_section(section)
        if not channel:
            return
        row_vars = self.channel_row_vars.get(section)
        selected_name = adapter_alias_from_display(row_vars["vlan"].get()) if row_vars else ""
        if selected_name and not adapter_has_numeric_suffix(selected_name):
            row_vars["vlan"].set(channel.vlan_name or channel.adapter_alias)
            self.adapter_rename_dialog = offer_adapter_rename(
                self, section=section, old_name=selected_name,
                is_busy=lambda: adapter_rename_is_busy(self),
                on_success=lambda new_name, result: self._on_adapter_renamed(section, selected_name, new_name, result),
                log=self._log,
            )
            return
        self._capture_channel_row(channel)
        index = self.channels.index(channel)
        self._refresh_channel_list_item(index)
        self._select_channel_index(index)
        self._persist_config()

    def _on_adapter_renamed(self, section, old_name, new_name, result):
        synchronize_channel_adapter_names(self.channels, section, old_name, new_name)
        self.adapters = [adapter.display_name for adapter in result.adapters]
        # 不调用采集所有行的 _persist_config，避免重命名时顺带修改其它配置字段。
        save_warning = None
        try:
            self.store.save(self._selected_channels(), self._selected_power_serial_port())
            self._log(f"[网卡重命名] 通道名称与 PC 静态 IP 已保存：{NETWORK_CONFIG_PATH}")
        except Exception as exc:
            save_warning = f"网卡已重命名，但配置保存失败：{exc}。内存已更新，请核对后重新保存配置。"
            self._log(f"[网卡重命名] {save_warning}")
        self._rebuild_channel_config_rows()
        for index in range(len(self.channels)):
            self._refresh_channel_list_item(index)
        channel = self._channel_by_section(section)
        if channel is not None:
            self._select_channel_index(self.channels.index(channel))
        self._refresh_upgrade_targets()
        self._refresh_dut_config_targets(capture_current=False)
        self._refresh_parameter_preflight(capture_current=False)
        self._invalidate_onu_preview()
        return save_warning

    def _on_row_serial_changed(self, section: str) -> None:
        channel = self._channel_by_section(section)
        if not channel:
            return
        self._capture_channel_row(channel)
        index = self.channels.index(channel)
        self._refresh_channel_list_item(index)
        self._select_channel_index(index)
        self._persist_config()
        self._log(
            f"{channel.section} 通道对应 COM口已更新为 "
            f"{channel.serial_port or '(空)'}。"
        )

    def _on_device_ip_changed(self, _event=None) -> None:
        self._persist_config()

    def _select_channel_index(self, index: int) -> None:
        if index < 0 or index >= len(self.channels):
            return
        self.current_index = index
        self._last_selected_index = index
        self.channel_list.selection_clear(0, END)
        self.channel_list.selection_set(index)
        self._load_current_channel()

    def _channel_by_section(self, section: str):
        for channel in self.channels:
            if channel.section == section:
                return channel
        return None

    def _capture_channel_rows(self) -> None:
        for section in list(self.channel_row_vars):
            channel = self._channel_by_section(section)
            if channel:
                self._capture_channel_row(channel)

    def _capture_channel_row(self, channel: ChannelConfig) -> None:
        row_vars = self.channel_row_vars.get(channel.section)
        if not row_vars:
            return
        channel.enabled = bool(row_vars["enabled"].get())
        selected_vlan = adapter_alias_from_display(row_vars["vlan"].get())
        matched_adapter = self._find_adapter_for_vlan(selected_vlan)
        channel.vlan_name = matched_adapter or selected_vlan
        channel.adapter_alias = matched_adapter or selected_vlan
        channel.serial_port = str(row_vars["serial_port"].get()).strip().upper()
        channel.device_manage_ip = self.device_ip_var.get().strip()
        channel.network_card_ip = self._network_card_ip_for_channel(channel)
        channel.subnet_mask = DEFAULT_SUBNET_MASK

    def _network_card_ip_for_channel(self, channel: ChannelConfig) -> str:
        if not channel.vlan_name or not channel.device_manage_ip:
            return ""
        try:
            return static_ip_for_vlan(channel.vlan_name, channel.device_manage_ip)
        except ValueError:
            return ""

    def _build_power_serial_options(self) -> list[str]:
        return ["", *[f"COM{101 + index}" for index in range(POWER_SUPPLY_COUNT)]]

    def _refresh_power_serial_ports(self) -> None:
        self.power_serial_options = self._build_power_serial_options()
        self.power_serial_combo.configure(values=self.power_serial_options)
        self._log_list("已刷新程控电源串口候选", self.power_serial_options)

    def _selected_power_serial_port(self) -> str:
        value = self.power_serial_var.get().strip()
        return (port_from_display(value) or value).upper()

    def _current_vlan_options(self) -> list[str]:
        return self._vlan_adapter_options()

    def _current_channel_serial_options(self) -> list[str]:
        return serial_options_for_power_serial_port(self._selected_power_serial_port())

    def _vlan_adapter_options(self) -> list[str]:
        return vlan_options_for_power_serial_port(self.adapters, self._selected_power_serial_port())

    @staticmethod
    def _serial_port_for_channel(channel: ChannelConfig) -> str:
        configured = (getattr(channel, "serial_port", "") or "").strip().upper()
        if configured:
            return configured
        vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
        if not vlan:
            return ""
        try:
            return vlan_to_serial_port(vlan)
        except ValueError:
            return ""

    def _serial_port_for_vlan(self, vlan_name: str) -> str:
        channel = self._channel_for_vlan(vlan_name)
        if channel is not None:
            return self._serial_port_for_channel(channel)
        try:
            return vlan_to_serial_port(vlan_name)
        except ValueError:
            return ""

    def _vlan_sort_key(self, value: str) -> tuple[int, str]:
        alias = adapter_alias_from_display(value).lower()
        digits = "".join(char for char in alias if char.isdigit())
        return (int(digits) if digits else 999999, alias)

    def _on_power_serial_changed(self, _event=None) -> None:
        selected = self._selected_power_serial_port()
        self._capture_channel_rows()
        self.power_serial_var.set(selected)
        self._rebuild_channel_config_rows()
        self._persist_config()
        options = self._current_vlan_options()
        serial_options = self._current_channel_serial_options()
        if not selected:
            self._log(
                "未选择程控电源串口；通道对应 VLAN 下拉框展示所有识别网卡，"
                f"通道对应 COM口展示 {serial_options[0]} 到 {serial_options[-1]}。"
                "请手动重启样机后，再进行后续步骤。"
            )
        elif options:
            self._log(
                f"程控电源串口已切换为 {selected}；VLAN 下拉框仅展示 "
                f"{adapter_alias_from_display(options[0])} 到 {adapter_alias_from_display(options[-1])}；"
                f"通道对应 COM口仅展示 {serial_options[0]} 到 {serial_options[-1]}。"
            )
        else:
            self._log(
                f"程控电源串口已切换为 {selected}；未找到该程控电源对应的 VLAN 网卡；"
                f"通道对应 COM口仅展示 {serial_options[0]} 到 {serial_options[-1]}。"
            )

    def _on_vlan_changed(self, _event=None) -> None:
        matched_adapter = self._find_adapter_for_vlan(self.vlan_var.get())
        if matched_adapter:
            self.adapter_var.set(matched_adapter)
            self.vlan_var.set(matched_adapter)

    def _find_adapter_for_vlan(self, vlan_name: str) -> str:
        target = adapter_alias_from_display(vlan_name).lower()
        if not target:
            return ""
        for adapter in self.adapters:
            alias = adapter_alias_from_display(adapter)
            if alias.lower() == target:
                return alias
        return ""

    def _channel_list_label(self, channel: ChannelConfig) -> str:
        checked = "☑" if channel.enabled else "☐"
        mappings = " / ".join(
            value for value in (channel.vlan_name, self._serial_port_for_channel(channel)) if value
        )
        suffix = f"  {mappings}" if mappings else ""
        return f"{checked} {channel.section}{suffix}"

    def _rebuild_channel_list(self) -> None:
        self.channel_list.delete(0, END)
        for channel in self.channels:
            self.channel_list.insert(END, self._channel_list_label(channel))

    def _refresh_channel_list_item(self, index: int) -> None:
        if index < 0 or index >= len(self.channels):
            return
        selected = index in self.channel_list.curselection()
        self.channel_list.delete(index)
        self.channel_list.insert(index, self._channel_list_label(self.channels[index]))
        self._apply_power_test_channel_color(index)
        if selected:
            self.channel_list.selection_set(index)

    def _apply_power_test_channel_color(self, index: int) -> None:
        """左侧通道列表仅用于配置，运行态统一显示在测试卡的通道概览。"""
        if index < 0 or index >= len(self.channels):
            return
        self.channel_list.itemconfig(index, foreground=COLOR_TEXT)

    def _reset_power_test_channel_states(self, channel_numbers: list[int]) -> None:
        """仅清空本次选中通道的旧结论和运行概览。"""
        for channel_number in channel_numbers:
            self.power_test_channel_states.pop(channel_number, None)
            self.power_test_channel_progresses.pop(channel_number, None)
            self.power_test_channel_histories.pop(channel_number, None)
        for index, channel in enumerate(self.channels):
            if power_channel_from_section(channel.section) in channel_numbers:
                self._apply_power_test_channel_color(index)
        detail_var = getattr(self, "power_test_channel_detail_var", None)
        if detail_var is not None:
            detail_var.set("")
        self.power_test_channel_selected_number = None
        close_history_window = getattr(self, "_close_power_test_channel_history_window", None)
        if callable(close_history_window):
            close_history_window()
        renderer = getattr(self, "_render_power_test_channel_overview", None)
        if callable(renderer):
            renderer()

    def _record_power_test_channel_history(
        self,
        channel_number: int,
        cycle: int,
        status: str,
        detail: str,
    ) -> None:
        """保留本次开关机测试中单通道的重试和失败事件。"""
        if status not in {"retry", "failed", "success", "resume"}:
            return
        if status == "success" and "重试" not in detail and "续跑" not in detail:
            return
        try:
            normalized_cycle = max(1, int(cycle))
        except (TypeError, ValueError):
            normalized_cycle = 1
        normalized_channel = int(channel_number)
        self.power_test_channel_histories.setdefault(normalized_channel, []).append(
            (normalized_cycle, status, str(detail).strip())
        )
        renderer = getattr(self, "_render_power_test_channel_overview", None)
        if callable(renderer):
            renderer()

    def _set_power_test_channel_state(
        self,
        channel_number: int,
        status: str,
        detail: str,
    ) -> None:
        """更新一条旧 Start All 通道的运行、重试、失败或正常结果。"""
        if status not in {"running", "retry", "failed", "success", "stopped"}:
            return
        self.power_test_channel_states[int(channel_number)] = (status, detail)
        renderer = getattr(self, "_render_power_test_channel_overview", None)
        if callable(renderer):
            renderer()

    def _set_power_test_channel_progress(
        self,
        channel_number: int,
        completed: int,
        total: int,
        stage: str,
    ) -> None:
        """更新一条通道的独立轮次与阶段；调用方必须位于 Tk 主线程。"""
        try:
            completed_cycles = int(completed)
            total_cycles = int(total)
        except (TypeError, ValueError):
            return
        if total_cycles <= 0:
            return
        channel_number = int(channel_number)
        self.power_test_channel_progresses[channel_number] = (
            max(0, min(completed_cycles, total_cycles)),
            total_cycles,
            str(stage).strip() or "等待状态更新",
        )
        self._render_power_test_channel_overview()

    def _toggle_power_test_channel_overview(self) -> None:
        """折叠或展开测试卡内的通道小卡，不影响后台测试。"""
        self.power_test_channel_overview_expanded = not self.power_test_channel_overview_expanded
        self._render_power_test_channel_overview()

    def _render_power_test_channel_overview(self) -> None:
        """根据独立轮次刷新测试卡，避免把运行态混入左侧配置列表。"""
        overview = getattr(self, "power_test_channel_overview", None)
        progresses = getattr(self, "power_test_channel_progresses", {})
        if overview is None:
            return
        if not progresses:
            overview.pack_forget()
            self.power_test_channel_overview_shown = False
            return
        if not getattr(self, "power_test_channel_overview_shown", False):
            overview.pack(fill="x", pady=(8, 0))
            self.power_test_channel_overview_shown = True

        channel_numbers = sorted(progresses)
        completed_values = [progresses[number][0] for number in channel_numbers]
        total_cycles = max(progresses[number][1] for number in channel_numbers)
        minimum_completed = min(completed_values)
        states = getattr(self, "power_test_channel_states", {})
        state_by_channel = {
            number: states.get(number, ("running", ""))[0]
            for number in channel_numbers
        }
        retries = sum(state == "retry" for state in state_by_channel.values())
        failures = sum(state == "failed" for state in state_by_channel.values())
        stopped = sum(state == "stopped" for state in state_by_channel.values())
        if minimum_completed >= total_cycles:
            summary = f"全部通道已完成：{len(channel_numbers)}/{len(channel_numbers)}"
        else:
            current_cycle = minimum_completed + 1
            current_finished = sum(value >= current_cycle for value in completed_values)
            running = sum(
                value < total and state not in {"retry", "failed", "stopped"}
                for value, total, state in (
                    (progresses[number][0], progresses[number][1], state_by_channel[number])
                    for number in channel_numbers
                )
            )
            summary = (
                f"第 {current_cycle} 轮：已完成 {current_finished}/{len(channel_numbers)}"
                f" ｜运行中 {running} ｜重试 {retries} ｜失败 {failures}"
            )
        if stopped:
            summary += f" ｜已停止 {stopped}"
        self.power_test_channel_summary_var.set(summary)

        maximum_completed = max(completed_values)
        attention: list[str] = []
        for number in channel_numbers:
            completed, total, stage = progresses[number]
            state, detail = states.get(number, ("running", ""))
            if state in {"retry", "failed"} or (
                completed == minimum_completed and completed < maximum_completed
            ):
                state_text = {"retry": "重试", "failed": "失败"}.get(state, "落后")
                attention.append(
                    f"通道 {number} {completed}/{total} {state_text}：{detail or stage}"
                )
        attention_text = f"关注：{'；'.join(attention[:2])}" if attention else ""
        self.power_test_channel_attention_var.set(attention_text)
        # 空文本 Label 仍会占据一行高度；没有异常/落后通道时不显示该行。
        self.power_test_channel_grid.pack_forget()
        self.power_test_channel_detail_label.pack_forget()
        self.power_test_channel_attention_label.pack_forget()
        if attention_text:
            self.power_test_channel_attention_label.pack(anchor="w", pady=(0, 4))

        expanded = getattr(self, "power_test_channel_overview_expanded", True)
        self.power_test_channel_overview_toggle.configure(
            text="通道概览（收起）" if expanded else "通道概览（展开）"
        )
        if not expanded:
            return
        self.power_test_channel_grid.pack(fill="x")
        self.power_test_channel_detail_label.pack(anchor="w", pady=(4, 0))
        for child in self.power_test_channel_grid.winfo_children():
            child.destroy()
        for column in range(4):
            self.power_test_channel_grid.columnconfigure(column, weight=1)
        from src.ui.power_test_resume_menu import bind_resume_menu
        for index, number in enumerate(channel_numbers):
            completed, total, stage = progresses[number]
            state, detail = states.get(number, ("running", ""))
            if state == "failed":
                state_text, style = "失败", "PowerChannelFailed.TLabel"
            elif state == "retry":
                state_text, style = "重试", "PowerChannelRetry.TLabel"
            elif state == "stopped":
                state_text, style = "已停止", "PowerChannelWaiting.TLabel"
            elif state == "success":
                state_text = "已完成" if completed >= total else "正常"
                style = "PowerChannelCompleted.TLabel"
            elif completed == 0:
                state_text, style = "等待", "PowerChannelWaiting.TLabel"
            else:
                state_text, style = "运行", "PowerChannelRunning.TLabel"
            tile = ttk.Label(
                self.power_test_channel_grid,
                text=f"通道 {number}  {completed}/{total}  {state_text}",
                style=style,
                anchor="w",
            )
            tile.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 5), pady=2)
            bind_resume_menu(self, tile, number)
            tile.bind(
                "<Button-1>",
                lambda _event, selected=number: self._show_power_test_channel_detail(
                    selected, open_history=True
                ),
            )
        selected_channel = getattr(self, "power_test_channel_selected_number", None)
        if selected_channel not in channel_numbers:
            selected_channel = channel_numbers[0]
        self._show_power_test_channel_detail(selected_channel, open_history=False)

    def _show_power_test_channel_detail(
        self,
        channel_number: int,
        *,
        open_history: bool = False,
    ) -> None:
        """显示当前摘要；用户点击时打开本次独立的重试/失败历史窗口。"""
        progress = self.power_test_channel_progresses.get(int(channel_number))
        if progress is None:
            return
        self.power_test_channel_selected_number = int(channel_number)
        completed, total, stage = progress
        status, detail = self.power_test_channel_states.get(int(channel_number), ("running", ""))
        status_text = {
            "stopped": "已停止",
            "retry": "重试中",
            "failed": "失败",
            "success": "已完成" if completed >= total else "验证正常",
        }.get(status, "运行中")
        self.power_test_channel_detail_var.set(
            f"通道 {channel_number}：{completed}/{total}，{status_text}，{detail or stage}"
        )
        if open_history:
            self._open_power_test_channel_history_window(int(channel_number))
        else:
            self._refresh_power_test_channel_history_window()

    def _open_power_test_channel_history_window(self, channel_number: int) -> None:
        """复用一个非模态窗口显示当前通道的本次重试/失败历史。"""
        self.power_test_channel_selected_number = int(channel_number)
        window = getattr(self, "power_test_channel_history_window", None)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_force()
            self._refresh_power_test_channel_history_window()
            return

        window = Toplevel(self)
        self.power_test_channel_history_window = window
        window.minsize(560, 300)
        window.geometry("760x440")
        window.protocol("WM_DELETE_WINDOW", self._close_power_test_channel_history_window)

        container = ttk.Frame(window, style="Surface.TFrame", padding=12)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            textvariable=self.power_test_channel_history_title_var,
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        history_body = ttk.Frame(container, style="Surface.TFrame")
        history_body.pack(fill="both", expand=True)
        history_text = Text(
            history_body,
            wrap="word",
            font=("Consolas", 10),
            background=COLOR_LOG_BG,
            foreground=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=10,
            pady=8,
            state="disabled",
        )
        self.power_test_channel_history_text = history_text
        history_scrollbar = ttk.Scrollbar(
            history_body,
            orient="vertical",
            command=history_text.yview,
        )
        history_text.configure(yscrollcommand=history_scrollbar.set)
        history_text.pack(side="left", fill="both", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        ttk.Button(
            container,
            text="关闭",
            command=self._close_power_test_channel_history_window,
            style="Secondary.TButton",
        ).pack(anchor="e", pady=(10, 0))
        center_toplevel_on_parent(window, self, window_width=760, window_height=440)
        schedule_toplevel_client_refresh(window)
        self._refresh_power_test_channel_history_window()

    def _close_power_test_channel_history_window(self) -> None:
        """销毁历史窗口并清理失效 Tk 控件引用。"""
        window = getattr(self, "power_test_channel_history_window", None)
        self.power_test_channel_history_window = None
        self.power_test_channel_history_text = None
        if window is not None and window.winfo_exists():
            window.destroy()

    def _refresh_power_test_channel_history_window(self) -> None:
        """在窗口打开期间随当前通道的新事件刷新滚动历史。"""
        window = getattr(self, "power_test_channel_history_window", None)
        history_text = getattr(self, "power_test_channel_history_text", None)
        history_title = getattr(self, "power_test_channel_history_title_var", None)
        channel_number = getattr(self, "power_test_channel_selected_number", None)
        if (
            window is None
            or history_text is None
            or history_title is None
            or channel_number is None
        ):
            return
        if not window.winfo_exists():
            self.power_test_channel_history_window = None
            self.power_test_channel_history_text = None
            return
        entries = self.power_test_channel_histories.get(int(channel_number), [])
        history_title.set(f"通道 {channel_number} 本次重试/失败历史（{len(entries)} 条）")
        window.title(f"通道 {channel_number} 重试/失败历史")
        lines = []
        status_labels = {
            "retry": "重试",
            "failed": "失败",
            "success": "重试后成功",
            "resume": "续跑",
        }
        for event_cycle, event_status, event_detail in entries:
            lines.append(
                f"第 {event_cycle} 轮｜{status_labels.get(event_status, event_status)}："
                f"{event_detail}"
            )
        if not lines:
            lines.append("本次未发生重试或失败。")
        history_text.configure(state="normal")
        history_text.delete("1.0", END)
        history_text.insert("1.0", "\n".join(lines))
        history_text.configure(state="disabled")
        history_text.yview_moveto(1.0)

    def _power_test_channel_result_summary(self) -> str:
        """返回本次开关机测试的最终逐通道结论，供结束弹窗直接展示。"""
        lines: list[str] = []
        for channel_number in sorted(self.power_test_channel_states):
            status, detail = self.power_test_channel_states[channel_number]
            if status == "success":
                lines.append(f"通道{channel_number}所有测试项验证成功")
            elif status == "failed":
                lines.append(f"通道{channel_number}{detail}")
        return "\n".join(lines)

    def _channel_list_row_at(self, event):
        index = self.channel_list.nearest(event.y)
        if index < 0 or index >= len(self.channels):
            return None
        row_box = self.channel_list.bbox(index)
        if row_box is None or not row_box[1] <= event.y < row_box[1] + row_box[3]:
            return None
        return index

    def _on_channel_list_press(self, event):
        if self._channel_list_row_at(event) is None:
            return "break"

    def _on_channel_list_double_click(self, event):
        if self._channel_list_row_at(event) is None:
            return "break"
        return self._toggle_selected_channel_enabled(event)

    def _on_channel_list_click(self, event) -> None:
        index = self._channel_list_row_at(event)
        if index is None:
            return
        # The checkbox marker is at the beginning of each row.
        if event.x <= 28:
            self._toggle_channel_enabled(index)

    def _on_channel_list_context_menu(self, event) -> str:
        """右键先选中鼠标所在通道，再显示与该通道相关的只读操作。"""
        index = self.channel_list.nearest(event.y)
        row_box = self.channel_list.bbox(index)
        if (
            index < 0
            or index >= len(self.channels)
            or row_box is None
            or not row_box[1] <= event.y < row_box[1] + row_box[3]
        ):
            return "break"
        self._select_channel_index(index)
        try:
            self.channel_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.channel_context_menu.grab_release()
        return "break"

    def _open_selected_power_test_log(self) -> None:
        """打开当前行对应的最新旧开关机结果日志，不读取或改写结果文件。"""
        if not 0 <= self.current_index < len(self.channels):
            messagebox.showwarning("未选择通道", "请先在左侧选择要查看日志的测试通道。", parent=self)
            self._log("[开关机运行日志] 未选择有效通道，未打开日志。")
            return

        channel = self.channels[self.current_index]
        channel_number = power_channel_from_section(channel.section)
        if not channel_number:
            messagebox.showwarning("通道不正确", f"无法识别通道：{channel.section}", parent=self)
            self._log(f"[开关机运行日志] 无法识别通道：{channel.section}。")
            return

        try:
            log_path = latest_power_test_result_log(
                APP_DIR / "Auto_power_on_off_tool", channel_number
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("查找开关机运行日志失败", str(exc), parent=self)
            self._log(f"[开关机运行日志] 通道 {channel_number} 查找失败：{exc}")
            return
        if log_path is None:
            result_dir = APP_DIR / "Auto_power_on_off_tool" / "test_results" / f"device_{channel_number}"
            messagebox.showinfo(
                "未找到开关机运行日志",
                f"通道 {channel_number} 暂无可打开的运行日志。\n\n结果目录：{result_dir}",
                parent=self,
            )
            self._log(
                f"[开关机运行日志] 通道 {channel_number} 未找到结果文件：{result_dir}"
            )
            return

        try:
            os.startfile(str(log_path))
        except OSError as exc:
            messagebox.showerror("打开开关机运行日志失败", f"{log_path}\n\n{exc}", parent=self)
            self._log(f"[开关机运行日志] 通道 {channel_number} 打开失败：{log_path}；{exc}")
            return
        self._log(f"[开关机运行日志] 已打开通道 {channel_number} 最新日志：{log_path}")

    def _toggle_selected_channel_enabled(self, _event=None) -> str:
        selection = self.channel_list.curselection()
        index = selection[0] if selection else self.current_index
        self._toggle_channel_enabled(index)
        return "break"

    def _toggle_channel_enabled(self, index: int) -> None:
        if index < 0 or index >= len(self.channels):
            return
        self._capture_current_channel()
        self.channels[index].enabled = not self.channels[index].enabled
        self.current_index = index
        self._last_selected_index = index
        self.channel_list.selection_clear(0, END)
        self.channel_list.selection_set(index)
        self._load_current_channel()
        self._refresh_channel_list_item(index)
        self._rebuild_channel_config_rows()
        self._persist_config()

    def _on_current_enabled_changed(self) -> None:
        self._capture_current_channel()
        self._refresh_channel_list_item(self.current_index)
        self._persist_config()

    def _set_all_channels_enabled(self, enabled: bool) -> None:
        self._capture_current_channel()
        for channel in self.channels:
            channel.enabled = enabled
        if 0 <= self.current_index < len(self.channels):
            self.enabled_var.set(enabled)
        self._rebuild_channel_list()
        if 0 <= self.current_index < len(self.channels):
            self.channel_list.selection_set(self.current_index)
        self._rebuild_channel_config_rows()
        self._persist_config()
        self._log("已全选通道。" if enabled else "已取消全选通道。")

    def _channel_sort_value(self, section: str) -> int:
        try:
            return int(section.lower().replace("channel_", ""))
        except ValueError:
            return 9999

    def _unique_options(self, values: list[str]) -> list[str]:
        seen = set()
        unique = []
        for value in values:
            normalized = (value or "").strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            unique.append(normalized)
        return unique

    def _ensure_channel_slots(self) -> None:
        channels_by_section = {channel.section: channel for channel in self.channels}
        for index in range(1, TOTAL_CHANNEL_COUNT + 1):
            section = f"channel_{index}"
            if section not in channels_by_section:
                self.channels.append(ChannelConfig(section=section, enabled=False))
        self.channels.sort(key=lambda channel: self._channel_sort_value(channel.section))

    def _shared_device_manage_ip(self) -> str:
        for channel in self.channels:
            if channel.device_manage_ip:
                return channel.device_manage_ip
        return ""

    def _show_startup_warnings(self) -> None:
        if not is_admin():
            messagebox.showwarning("需要管理员权限", "修改虚拟网卡静态 IP 需要管理员权限。请关闭后右键以管理员身份运行。")

    def _refresh_adapters(self) -> None:
        self.adapters = list_adapter_display_names()
        self._rebuild_channel_config_rows()
        if self.adapters:
            self._log_list("已刷新网卡", self.adapters)
        else:
            self._log("已刷新网卡：未识别到网卡")

    def _launch_power_on(self) -> None:
        if self.power_on_running:
            return
        self._capture_current_channel()
        enabled_channels = self._selected_channels()
        if not enabled_channels:
            messagebox.showwarning("没有启用通道", "请至少启用一个通道后再自动上/下电。", parent=self)
            return
        wait_seconds = self._power_on_wait_seconds(enabled_channels)
        selected_com, power_action = self._select_power_com_port()
        if selected_com is None:
            return
        if power_action not in POWER_ACTION_OPTIONS:
            messagebox.showwarning("操作类型不正确", "程控电源操作只能选择上电或下电。", parent=self)
            return
        power_channels = [power_channel_from_section(channel.section) for channel in enabled_channels]
        if any(not 1 <= channel <= TOTAL_CHANNEL_COUNT for channel in power_channels):
            messagebox.showwarning("程控电源通道不正确", "存在无法识别的 channel 编号，已取消自动上/下电。", parent=self)
            return
        channel_text = "、".join(str(channel) for channel in power_channels)
        if selected_com:
            action_description = (
                "确认后会按勾选顺序开启全部通道，相邻开启指令间隔 1 秒；执行前不会关闭任何程控电源通道。"
                if power_action == POWER_ACTION_ON
                else "确认后会按勾选顺序关闭全部勾选通道，相邻关闭指令间隔 1 秒；只关闭勾选通道，不会执行全部断电。"
            )
            confirm_text = (
                f"将直接通过程控电源串口 {selected_com} 操作通道 {channel_text}。\n\n"
                f"{action_description}\n\n不会启动旧的 Auto_Power_On_Off_Tool。\n\n是否继续？"
            )
        else:
            confirm_text = (
                "未选择程控电源串口。\n\n"
                "请先手动重启样机，确认样机已重启后再继续。\n"
                "不会向任何 COM 口下发指令。\n\n是否继续？"
            )
        if not messagebox.askyesno(
            f"确认自动{power_action}",
            confirm_text,
            parent=self,
        ):
            return
        self.power_serial_var.set(selected_com)
        self.power_on_running = True
        thread = threading.Thread(target=self._power_on_worker, args=(selected_com, power_channels, power_action, wait_seconds), daemon=True)
        thread.start()

    def _open_power_control(self) -> None:
        """供全流程窗口「自动上/下电 → 去配置」使用，只保存配置不执行电源操作。"""
        configured_operation = (self.power_operation_var.get() or "up").strip().lower()
        initial_action = POWER_ACTION_OFF if configured_operation == "down" else POWER_ACTION_ON
        selected_com, power_action = self._select_power_com_port(initial_action=initial_action)
        if selected_com is None:
            return

        operation = "down" if power_action == POWER_ACTION_OFF else "up"
        self.power_serial_var.set(selected_com)
        self.power_operation_var.set(operation)
        self._persist_config()
        self._save_sample_upgrade_settings()
        self._log(
            f"全流程自动上/下电配置已更新：COM={selected_com or '(未选，需手动重启)'} / 操作={operation}；"
            "仅保存配置，未下发任何程控电源指令。"
        )

        pipeline_window = self.pipeline_window
        refresh_statuses = getattr(pipeline_window, "_refresh_statuses", None)
        if callable(refresh_statuses):
            refresh_statuses()

    def _select_power_com_port(self, initial_action: str = POWER_ACTION_ON) -> tuple[str | None, str]:
        dialog = Toplevel(self)
        dialog.title("选择自动上/下电操作")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        options = self._build_power_serial_options()
        current = self._selected_power_serial_port()
        selected = StringVar(value=current if current in options else DEFAULT_POWER_SERIAL_PORT)
        action_default = initial_action if initial_action in POWER_ACTION_OPTIONS else POWER_ACTION_ON
        action = StringVar(value=action_default)
        result = {"port": None, "action": action_default}

        Frame(dialog, padx=16, pady=12).pack(fill="both", expand=True)
        container = dialog.winfo_children()[0]
        prompt = "请选择程控电源 COM 口："
        Label(container, text=prompt).pack(anchor="w", pady=(0, 8))
        combo = ttk.Combobox(container, textvariable=selected, values=options, width=58, state="readonly")
        combo.pack(fill="x", pady=(0, 12))
        Label(container, text="留空：请手动重启样机后，再进行后续流程。", foreground=COLOR_MUTED).pack(anchor="w", pady=(0, 12))

        Label(container, text="请选择操作类型：").pack(anchor="w", pady=(0, 8))
        action_combo = ttk.Combobox(container, textvariable=action, values=POWER_ACTION_OPTIONS, width=58, state="readonly")
        action_combo.pack(fill="x", pady=(0, 12))

        buttons = Frame(container)
        buttons.pack(fill="x")

        def confirm() -> None:
            try:
                value = selected.get().strip()
                selected_port = port_from_display(value) or value.upper()
                if selected_port not in options:
                    messagebox.showwarning("COM 口不正确", "程控电源串口只能选择 COM101 到 COM106。", parent=dialog)
                    return
                selected_action = action.get().strip()
                if selected_action not in POWER_ACTION_OPTIONS:
                    messagebox.showwarning("操作类型不正确", "请选择上电或下电。", parent=dialog)
                    return
                result["port"] = selected_port
                result["action"] = selected_action
                if selected_port:
                    self._log(f"已选择程控电源串口：{selected_port}，操作：{selected_action}")
                else:
                    self._log(f"未选择程控电源串口：请手动重启样机后，再进行本次{selected_action}后的步骤。")
                dialog.grab_release()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("选择 COM 口失败", str(exc), parent=dialog)
                self._log(f"选择 COM 口失败：{exc}")

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        Button(buttons, text="确定", command=confirm).pack(side="right")
        Button(buttons, text="取消", command=cancel).pack(side="right", padx=(0, 8))
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())

        center_toplevel_on_parent(dialog, self)
        combo.focus_set()
        self.wait_window(dialog)
        return result["port"], result["action"]

    def _power_on_wait_seconds(self, channels) -> int:
        return POWER_ON_WAIT_SECONDS

    def _power_on_worker(self, selected_com: str, power_channels: list[int], power_action: str, wait_seconds: int) -> None:
        try:
            action_text = "开启" if power_action == POWER_ACTION_ON else "关闭"
            self.log_queue.put(
                f"开始直接控制程控电源，串口 {selected_com}，通道 {'、'.join(str(channel) for channel in power_channels)}；"
                f"相邻{action_text}指令间隔 1 秒，全部{action_text}完成后不额外等待。"
            )
            if power_action == POWER_ACTION_ON:
                result = turn_on_selected_channels(
                    selected_com,
                    power_channels,
                    wait_seconds=wait_seconds,
                    on_output=lambda line: self.log_queue.put(line),
                )
            else:
                result = turn_off_selected_channels(
                    selected_com,
                    power_channels,
                    on_output=lambda line: self.log_queue.put(line),
                )
            self.log_queue.put(result.message)
        except Exception as exc:
            self.log_queue.put(f"自动上/下电后台流程异常：{exc}")
        finally:
            self.log_queue.put("__POWER_DONE__")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")
        self._log("执行日志已清空。")
        self._log(f"本次日志文件：{self.log_path}")

    def _on_channel_selected(self, _event=None) -> None:
        selection = self.channel_list.curselection()
        if not selection:
            return
        previous_index = self._last_selected_index
        self._capture_channel(previous_index)
        self._refresh_channel_list_item(previous_index)
        self.current_index = selection[0]
        self._last_selected_index = self.current_index
        self.channel_list.selection_set(self.current_index)
        self._load_current_channel()

    def _load_current_channel(self) -> None:
        if self.current_index < 0 or self.current_index >= len(self.channels):
            return
        channel = self.channels[self.current_index]
        self.enabled_var.set(channel.enabled)
        selected_vlan = channel.vlan_name or channel.adapter_alias
        self.vlan_var.set(selected_vlan)
        self.adapter_var.set(channel.adapter_alias or selected_vlan)
        self.pc_ip_var.set(channel.network_card_ip)
        if not self.device_ip_var.get().strip() and channel.device_manage_ip:
            self.device_ip_var.set(channel.device_manage_ip)
        self.mask_var.set(DEFAULT_SUBNET_MASK)

    def _capture_current_channel(self) -> None:
        self._capture_channel_rows()

    def _capture_channel(self, index: int) -> None:
        self._capture_channel_rows()

    def _persist_config(self) -> None:
        self._capture_current_channel()
        self.store.save(self._selected_channels(), self._selected_power_serial_port())
        self._refresh_upgrade_targets()
        self._log(f"已实时更新配置文件：{NETWORK_CONFIG_PATH}")

    def _start_all_checks(self) -> None:
        """2026-07-20: 主界面「检查并执行测试」按钮升级为「全流程执行」弹窗入口。

        旧实现:直接调 ``_run_checks``(仅做已勾选通道的 ping 通过性检查)。
        新实现:弹「全流程执行」窗口,操作员勾选 7 个子任务(自动上/下电 / 环境线路检查 /
        样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 测试项配置)后,按 1→7 顺序串行执行,
        任一失败(串口日志除外)→ 整个全流程停止。
        ``_run_checks`` / ``_check_worker`` 仍保留供单通道 ping 检查场景使用。

        注意:``self.pipeline_window`` 是 ``PipelineWindow`` 包装器(持有 ``self.window`` 这个 Toplevel),
        ``winfo_exists()`` / ``deiconify()`` / ``lift()`` / ``focus_force()`` 必须走 ``.window``,不能直接调包装器。
        """
        session = getattr(self, "power_test_resume_session", None)
        if session is not None and session.is_recovering:
            self._log("[通道续跑] 当前仍在恢复通道，请等待结束或停止后再启动全流程。")
            return
        # 旧逻辑保留作为兜底(直接跳弹窗失败时,仍可走 ping 检查)
        if self.running:
            return
        pipeline_window = self.pipeline_window
        if self.power_test_running:
            is_running = getattr(pipeline_window, "is_running", None)
            if callable(is_running) and is_running():
                self._log("开关机测试：当前全流程仍在执行或停止中，请在主界面查看状态。")
                return
            self._set_power_test_status("idle")
            self._log("开关机测试：检测到后台全流程已结束，已将残留状态恢复为未运行。")
        if pipeline_window is not None and pipeline_window.window.winfo_exists():
            pipeline_window.window.deiconify()
            pipeline_window.window.lift()
            pipeline_window.window.focus_force()
            return
        # 2026-07-20 引入:PipelineWindow 在 ``line_check_assistant.pipeline_window``;
        # 引用放在这里(而非 ``__init__``)以避免与 ``app.py`` 的 tkinter 启动顺序耦合。
        from .pipeline_window import PipelineWindow
        self.pipeline_window = PipelineWindow(self)

    def _set_power_test_status(self, status: str) -> None:
        """在 Tk 主线程同步主界面的全流程状态与停止按钮。"""
        labels = {
            "idle": "开关机测试状态：未运行",
            "running": "开关机测试状态：正在执行",
            "stopping": "开关机测试状态：正在停止（等待当前子任务安全退出）",
            "completed": "开关机测试状态：已完成",
            "stopped": "开关机测试状态：已停止",
            "failed": "开关机测试状态：执行失败",
        }
        styles = {
            "idle": "PowerStatusIdle.TLabel",
            "running": "PowerStatusRunning.TLabel",
            "stopping": "PowerStatusStopping.TLabel",
            "completed": "PowerStatusCompleted.TLabel",
            "stopped": "PowerStatusStopped.TLabel",
            "failed": "PowerStatusFailed.TLabel",
        }
        if status not in labels:
            raise ValueError(f"未知开关机测试状态：{status}")
        self.power_test_running = status in {"running", "stopping"}
        self.power_test_status_var.set(labels[status])
        self.power_test_status_label.configure(style=styles[status])
        self.stop_power_test_button.configure(
            state="normal" if status == "running" else "disabled"
        )

    def _set_power_test_progress(self, completed: int, total: int) -> None:
        """显示开关机测试已完成轮次；调用方必须位于 Tk 主线程。"""
        try:
            total_cycles = int(total)
            completed_cycles = int(completed)
        except (TypeError, ValueError):
            total_cycles = 0
            completed_cycles = 0
        if total_cycles <= 0:
            self.progress.configure(maximum=1, value=0)
            self.power_test_progress_text_var.set("开关机测试进度：等待开始")
            return
        completed_cycles = max(0, min(completed_cycles, total_cycles))
        self.progress.configure(maximum=total_cycles, value=completed_cycles)
        self.power_test_progress_text_var.set(
            f"开关机测试进度：{completed_cycles}/{total_cycles}"
        )

    def _stop_power_test(self) -> None:
        """主界面停止入口；委派给当前全流程编排器的既有停止事件。"""
        session = getattr(self, "power_test_resume_session", None)
        recovery_stopped = session is not None and session.is_recovering
        if recovery_stopped:
            session.stop()
            self.stop_power_test_button.configure(state="disabled")
        pipeline_window = self.pipeline_window
        if pipeline_window is not None and pipeline_window.request_stop():
            return
        if recovery_stopped:
            return
        if self.power_test_running:
            self._set_power_test_status("idle")
            self._log("开关机测试：后台全流程已结束，已将残留状态恢复为未运行。")
            return
        self._log("开关机测试：当前没有正在执行的全流程，无需停止。")

    def _selected_channels(self) -> list[ChannelConfig]:
        return [channel for channel in self.channels if channel.enabled]

    def _run_checks(self, channels) -> None:
        invalid_message = self._validate_channels(channels)
        if invalid_message:
            messagebox.showwarning("配置不完整", invalid_message)
            self._log(invalid_message)
            return
        self.running = True
        self.progress.configure(value=0, maximum=len(channels))
        thread = threading.Thread(target=self._check_worker, args=(channels,), daemon=True)
        thread.start()

    def _validate_channels(self, channels) -> str:
        available = {adapter_alias_from_display(adapter) for adapter in self.adapters}
        for channel in channels:
            if not channel.vlan_name:
                return f"{channel.section} 未选择通道对应 VLAN。"
            if not channel.adapter_alias:
                return f"{channel.section} 未选择 VLAN 对应网卡。"
            if available and channel.adapter_alias not in available:
                return f"{channel.section} 配置的 VLAN 网卡不存在：{channel.adapter_alias}。请刷新网卡后重新选择。"
            if not channel.device_manage_ip:
                return f"{channel.section} 未填写样机管理 IP。"
            try:
                channel.network_card_ip = static_ip_for_vlan(channel.vlan_name, channel.device_manage_ip)
            except ValueError as exc:
                return f"{channel.section} {exc}。"
        return ""

    def _check_worker(self, channels) -> None:
        passed = 0
        for index, channel in enumerate(channels, start=1):
            self.log_queue.put(f"开始检查 {channel.section}")
            self.log_queue.put(f"  VLAN：{channel.vlan_name or '未配置'}")
            self.log_queue.put(f"  PC 静态 IP：{channel.network_card_ip or '未配置'}")
            self.log_queue.put(f"  样机 IP：{channel.device_manage_ip or '未配置'}")
            result = run_line_check(
                channel.adapter_alias,
                channel.network_card_ip,
                channel.subnet_mask,
                channel.device_manage_ip,
            )
            if result.ok:
                passed += 1
                self.log_queue.put(f"[通过] {channel.section} {result.message}")
            else:
                self.log_queue.put(f"[失败] {channel.section} {result.message}")
                if result.output.strip():
                    self.log_queue.put("  诊断输出：")
                    for line in result.output.strip().splitlines():
                        self.log_queue.put(f"    {line}")
            self.log_queue.put(f"__PROGRESS__:{index}")
        self.log_queue.put(f"线路检查完成：通过 {passed}/{len(channels)}")
        self.log_queue.put("__DONE__")

    def _drain_log_queue(self) -> None:
        processed = 0
        while processed < MAIN_LOG_EVENTS_PER_TICK:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if item == "__DONE__":
                self.running = False
            elif item == "__POWER_DONE__":
                self.power_on_running = False
            elif item.startswith("__PROGRESS__:"):
                self.progress.configure(value=int(item.split(":", 1)[1]))
            else:
                self._log(item)
        delay = 0 if not self.log_queue.empty() else MAIN_LOG_IDLE_DELAY_MS
        self.after(delay, self._drain_log_queue)

    def _configure_log_tags(self) -> None:
        self.log_text.tag_configure("time", foreground=COLOR_MUTED)
        self.log_text.tag_configure("section", foreground=COLOR_TEXT, font=("Consolas", 10, "bold"))
        self.log_text.tag_configure("success", foreground=COLOR_SUCCESS)
        self.log_text.tag_configure("error", foreground=COLOR_DANGER)
        self.log_text.tag_configure("warning", foreground=COLOR_WARNING)
        self.log_text.tag_configure("muted", foreground=COLOR_MUTED)
        self.log_text.configure(state="disabled")

    def _log_tag_for(self, message: str) -> str:
        if LEGACY_CHANNEL_TEST_START_PATTERN.search(message):
            return "success"
        if "验证失败" in message or "失败" in message or "异常" in message:
            return "error"
        if "准备第" in message and "次验证" in message:
            return "warning"
        if message.startswith("[通过]") or "成功" in message or "完成" in message:
            return "success"
        if "未" in message or "请" in message:
            return "warning"
        if message.startswith("  "):
            return "muted"
        return ""

    def _log_section(self, title: str) -> None:
        self.log_text.configure(state="normal")
        if self.log_text.index("end-1c") != "1.0":
            self.log_text.insert(END, "\n")
        self.log_text.insert(END, f"==== {title} ====\n", "section")
        self.log_text.configure(state="disabled")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(f"{timestamp} ==== {title} ====\n")

    def _log_blank(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(END, "\n")
        self.log_text.configure(state="disabled")
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write("\n")

    def _log_list(self, title: str, items: list[str]) -> None:
        self._log(f"{title}（共 {len(items)} 项）：")
        for index, item in enumerate(items, start=1):
            self._log(f"  {index:02d}. {item}")

    def _log(self, message: str, tag: str | None = None) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = self._log_tag_for(message) if tag is None else tag
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"{timestamp}  ", "time")
        if tag:
            self.log_text.insert(END, message + "\n", tag)
        else:
            self.log_text.insert(END, message + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see(END)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(f"{timestamp} {message}\n")


def main() -> None:
    app = LineCheckAssistant()
    app.mainloop()


if __name__ == "__main__":
    main()

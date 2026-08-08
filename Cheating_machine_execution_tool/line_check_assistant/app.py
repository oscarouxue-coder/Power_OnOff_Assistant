from __future__ import annotations

import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, Button, Canvas, Checkbutton, DoubleVar, END, Frame, IntVar, Label, Listbox, Tk, StringVar, Text, Toplevel, filedialog, messagebox, ttk

from .config_store import ChannelConfig, ChannelConfigStore, DEFAULT_POWER_SERIAL_PORT, DEFAULT_SUBNET_MASK
from .legacy_ui_defaults_store import LegacyUiDefaultsStore, TELNET_ENABLE_OPTION
from .network_ops import (
    CommandResult,
    adapter_alias_from_display,
    check_telnet_connection,
    is_admin,
    list_adapter_display_names,
    login_olt_and_enter_global_mode,
    parse_unregistered_onus,
    query_unregistered_onus,
    register_unregistered_onus,
    run_line_check,
    save_olt_configuration,
    static_ip_for_vlan,
    factory_bind_ip_for,
    factory_device_host_for,
)
from .onu_registration_store import DEFAULT_OLT_IP, OnuRegistrationConfig, OnuRegistrationStore
from .page_upgrade import PageUpgradeRequest, run_page_upgrade_batch
from .paths import resolve_config_dir, resolve_tool_root
from .sample_upgrade_settings_store import (
    DEFAULT_PARAMETER_PARALLEL_COUNT,
    DEFAULT_PARALLEL_COUNT,
    DEFAULT_UPGRADE_EXECUTION_MODE,
    DEFAULT_UPGRADE_MODE,
    DEFAULT_UPGRADE_TRANSFER,
    MAX_PARALLEL_UPGRADES,
    SampleUpgradeSettings,
    SampleUpgradeSettingsStore,
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
)
from src.core import (
    SerialSessionManager,
    generate_parameter_records,
    load_parameter_records,
    save_parameter_records_xlsx,
    vlan_to_serial_port,
)
from src.config import DEFAULT_LOG_DIR
from src.models import FullPackageUpgradeRequest, ParameterGenerationTemplate, SampleParameterWriteRequest
from src.services import (
    PARAMETER_MAX_PARALLEL,
    PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS,
    TRANSFER_TFTP_COMMAND,
    TRANSFER_TFTP_PUT,
    preflight_parameter_targets,
    run_parallel_tftp_command_upgrades,
    run_parallel_tftp_put_upgrades,
    run_parallel_sample_parameter_writes,
    run_single_sample_parameter_write,
    run_single_full_package_upgrade,
    turn_off_selected_channels,
    turn_on_selected_channels,
)
from src.ui import SerialTerminalWindow


APP_DIR = resolve_tool_root()
CONFIG_DIR = resolve_config_dir(APP_DIR)
NETWORK_CONFIG_PATH = CONFIG_DIR / "network_card_ip.ini"
ONU_REGISTRATION_CONFIG_PATH = CONFIG_DIR / "onu_registration.ini"
SAMPLE_UPGRADE_SETTINGS_PATH = CONFIG_DIR / "sample_upgrade_settings.ini"
# 测试项配置 ini:由主界面「测试项配置」按钮打开的窗口加载/保存(Q1=A:仅编辑,不接执行)。
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


def _clear_test_item_rows(row_widgets: list[dict]) -> None:
    """销毁全部测试项命令行，避免遍历时删除原列表导致隔行残留。"""
    for row_dict in tuple(row_widgets):
        row_dict["remove"]()
    row_widgets.clear()


def _reveal_completed_dialog(dialog) -> None:
    """显示后处理完整绘制队列，避免 Windows 客户区等待鼠标消息才重绘。"""
    dialog.deiconify()
    dialog.lift()
    dialog.update_idletasks()
    dialog.update()
    dialog.focus_force()


def power_channel_from_section(section: str) -> int:
    try:
        return int(section.lower().replace("channel_", ""))
    except ValueError:
        return 0


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

    port_number = normalized_port[3:] if normalized_port.startswith("COM") else ""
    try:
        raw_index = int(port_number)
    except ValueError:
        raw_index = 0

    if 101 <= raw_index < 101 + POWER_SUPPLY_COUNT:
        power_index = raw_index - 100
    elif 1 <= raw_index <= POWER_SUPPLY_COUNT:
        # 兼容操作员口头所说的 COM1 / COM2；实际下拉项仍为 COM101 / COM102。
        power_index = raw_index
    else:
        power_index = 0

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
CHANNEL_TABLE_GROUP_GAP = 24
CHANNEL_TABLE_ROWS_PER_GROUP = 4
UPGRADE_MODE_OPTIONS = ("页面升级", DEFAULT_UPGRADE_MODE)
TFTP_COMMAND_TRANSFER = TRANSFER_TFTP_COMMAND
TFTP_PUT_TRANSFER = TRANSFER_TFTP_PUT
LEGACY_TFTP_COPY_TRANSFER = "Tftp拷贝命令"
UPGRADE_TRANSFER_OPTIONS = (DEFAULT_UPGRADE_TRANSFER, TFTP_COMMAND_TRANSFER, "web打开网关")
SERIAL_FULL_PACKAGE_TRANSFERS = {TFTP_COMMAND_TRANSFER, TFTP_PUT_TRANSFER}
UPGRADE_EXECUTION_SERIAL = DEFAULT_UPGRADE_EXECUTION_MODE
UPGRADE_EXECUTION_PARALLEL = f"并行（最多 {MAX_PARALLEL_UPGRADES} 台）"
UPGRADE_EXECUTION_OPTIONS = (UPGRADE_EXECUTION_SERIAL, UPGRADE_EXECUTION_PARALLEL)
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
COLOR_DANGER_BG = "#fbe9e7"


def _finish_pipeline_subtask_if_waiting(app, code: str, ok: bool, detail: str) -> None:
    """仅在全流程等待该异步任务时回传完成结果；单功能入口保持原行为。"""
    finish = getattr(app, "_finish_pipeline_subtask", None)
    if callable(finish):
        finish(code, ok, detail)


class LineCheckAssistant(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("开关机测试环境搭建助手")
        self.geometry("1200x780")
        self.minsize(1040, 700)
        self.configure(background=COLOR_BG)
        self._configure_theme()

        self.store = ChannelConfigStore(NETWORK_CONFIG_PATH)
        self.onu_registration_store = OnuRegistrationStore(ONU_REGISTRATION_CONFIG_PATH)
        self.onu_registration_config = self.onu_registration_store.load()
        self.sample_upgrade_settings_store = SampleUpgradeSettingsStore(SAMPLE_UPGRADE_SETTINGS_PATH)
        self.sample_upgrade_settings = self.sample_upgrade_settings_store.load()
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
        self._pipeline_subtask_events: dict[str, threading.Event] = {}
        self._pipeline_subtask_results: dict[str, tuple[bool, str]] = {}
        self.running = False
        self.power_on_running = False
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
        self.test_item_config_window = None
        self.pipeline_window = None
        self.power_test_running = False
        self.power_test_status_var = StringVar(value="开关机测试状态：未运行")
        self.onu_registration_window = None
        self.onu_telnet_test_running = False
        self.onu_query_running = False
        self.onu_register_running = False
        self.onu_save_olt_running = False
        self.onu_save_after_id = None
        self.onu_olt_ip_var = StringVar(value=self.onu_registration_config.olt_ip)
        self.onu_username_var = StringVar(value=self.onu_registration_config.username)
        self.onu_password_var = StringVar(value=self.onu_registration_config.password)
        self.onu_password_visible = False
        self.onu_telnet_status_var = StringVar(value="")
        self.onu_query_status_var = StringVar(value="")
        self.onu_unregistered_selection_vars = []
        self._bind_onu_registration_autosave()
        upgrade_mode = self.sample_upgrade_settings.upgrade_mode if self.sample_upgrade_settings.upgrade_mode in UPGRADE_MODE_OPTIONS else DEFAULT_UPGRADE_MODE
        saved_transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.sample_upgrade_settings.transfer_method)
        transfer_method = saved_transfer_method if saved_transfer_method in UPGRADE_TRANSFER_OPTIONS else DEFAULT_UPGRADE_TRANSFER
        execution_mode = self.sample_upgrade_settings.execution_mode
        if execution_mode not in UPGRADE_EXECUTION_OPTIONS:
            execution_mode = DEFAULT_UPGRADE_EXECUTION_MODE
        self.sample_upgrade_save_after_id = None
        self.upgrade_mode_var = StringVar(value=upgrade_mode)
        self.upgrade_transfer_var = StringVar(value=transfer_method)
        self.upgrade_execution_var = StringVar(value=execution_mode)
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
        self.upgrade_status_var = StringVar(value="尚未开始升级")
        self.upgrade_progress_var = DoubleVar(value=0)
        # 写样机参数窗口的「首次登录账号 / 密码」也走同一份 sample_upgrade_settings.ini,
        # 与升级超级凭据分两个独立 key;作为主程序实例变量持久存在,值变更通过 trace_add 自动写盘。
        self.parameter_initial_username_var = StringVar(value=self.sample_upgrade_settings.parameter_initial_username)
        self.parameter_initial_password_var = StringVar(value=self.sample_upgrade_settings.parameter_initial_password)
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
        self._load_current_channel()
        self._show_startup_warnings()
        self.after_idle(self._maximize_window)
        self.after(200, self._drain_log_queue)
        self.after(50, self._drain_pipeline_ui_tasks)
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except Exception:
            return

    def _on_app_close(self) -> None:
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
            raise RuntimeError(detail)

    def _run_pipeline_sample_upgrade(self) -> None:
        """供后台编排器调用：主线程确认并启动升级，完成后才允许下一子任务。"""
        self._begin_pipeline_subtask("sample_upgrade")
        started = self._invoke_pipeline_ui_action(self._start_pipeline_sample_upgrade_on_ui)
        if not started:
            self._finish_pipeline_subtask("sample_upgrade", False, "样机升级未启动：操作员取消或配置未通过")
        self._wait_pipeline_subtask("sample_upgrade")

    def _start_pipeline_sample_upgrade_on_ui(self) -> bool:
        # 去配置窗口可能已被操作员关闭；管道重新创建/拉起有效窗口，
        # 使确认框不再引用已销毁的 Toplevel。
        self._open_upgrade_module()
        self._capture_current_channel()
        if not self._validate_upgrade_required_fields():
            return False
        transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())
        if self.upgrade_mode_var.get() == "页面升级":
            return self._start_page_upgrade()
        if self.upgrade_mode_var.get() == "全包升级" and transfer_method in SERIAL_FULL_PACKAGE_TRANSFERS:
            return self._start_serial_tftp_copy_upgrade()
        messagebox.showwarning("升级方式不支持", "请在样机升级窗口选择页面升级、Tftp指令或 Tftp Put。", parent=self.upgrade_window)
        return False

    def _run_pipeline_sample_parameter_write(self) -> None:
        """供后台编排器调用：重新打开写参窗口，完成后才允许下一子任务。"""
        self._begin_pipeline_subtask("sample_parameter_write")
        started = self._invoke_pipeline_ui_action(self._start_pipeline_sample_parameter_write_on_ui)
        if not started:
            self._finish_pipeline_subtask("sample_parameter_write", False, "写样机参数未启动：操作员取消或预检未通过")
        self._wait_pipeline_subtask("sample_parameter_write")

    def _start_pipeline_sample_parameter_write_on_ui(self) -> bool:
        self._open_sample_parameter_writer()
        return self._start_sample_parameter_write()

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
        style.configure("TButton", padding=(12, 7), font=(FONT_FAMILY, 9))
        style.configure("Primary.TButton", background=COLOR_PRIMARY, foreground="#ffffff", padding=(16, 9), font=(FONT_FAMILY, 10, "bold"))
        style.map("Primary.TButton", background=[("active", COLOR_PRIMARY_DARK), ("pressed", COLOR_PRIMARY_DARK)])
        style.configure("Secondary.TButton", background=COLOR_SECONDARY, foreground=COLOR_TEXT)
        style.map("Secondary.TButton", background=[("active", COLOR_SECONDARY_HOVER)])
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
        ttk.Label(toolbar, text="常用工具", style="CardTitle.TLabel").pack(side="left", padx=(2, 16))
        ttk.Button(toolbar, text="自动上/下电", command=self._launch_power_on, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text="样机升级", command=self._open_upgrade_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="写样机参数", command=self._open_sample_parameter_writer, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="ONU注册", command=self._open_onu_registration_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="串口日志", command=self._open_serial_log_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="DUT配置", command=self._open_dut_config_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="刷新网卡", command=self._refresh_adapters, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(toolbar, text="刷新串口", command=self._refresh_power_serial_ports, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Label(
            toolbar,
            text=admin_text,
            style="Success.TLabel" if admin_ok else "Danger.TLabel",
        ).pack(side="right", padx=(0, 16))

        body = ttk.Frame(root, style="App.TFrame")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, style="Surface.TFrame", padding=14)
        left.pack(side="left", fill="y", padx=(0, 14))
        ttk.Label(left, text="1  选择测试通道", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(left, text="点击方框或双击可切换启用状态", style="CardHint.TLabel").pack(anchor="w", pady=(3, 10))
        self.channel_list = Listbox(
            left,
            width=26,
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
        self.channel_list.bind("<ButtonRelease-1>", self._on_channel_list_click)
        self.channel_list.bind("<space>", self._toggle_selected_channel_enabled)
        self.channel_list.bind("<Double-Button-1>", self._toggle_selected_channel_enabled)
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
        ttk.Label(config_card, text="通道勾选和 VLAN 选择会实时保存", style="CardHint.TLabel").pack(anchor="w", pady=(3, 10))

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
        self.power_test_status_label = ttk.Label(
            run_copy,
            textvariable=self.power_test_status_var,
            style="CardHint.TLabel",
        )
        self.power_test_status_label.pack(anchor="w", pady=(0, 4))
        self.progress = ttk.Progressbar(run_copy, mode="determinate")
        self.progress.pack(fill="x")
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
        self._log("2. 选择本次测试使用的程控电源串口，并确认通道对应的 VLAN")
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
        dialog.geometry("980x690")
        dialog.minsize(860, 590)
        dialog.transient(self)

        # 参数表路径是全流程子任务 4 的必填项，必须直接复用实例级持久变量；
        # 不能每次开写参窗口再新建临时 StringVar，否则选表后全流程仍会读到空路径。
        self.parameter_table_var = self.parameter_table_path_var
        # 写样机参数窗口的「首次登录账号 / 密码」直接复用主程序实例级 StringVar,
        # 由 ``__init__`` 阶段从 sample_upgrade_settings.ini 加载,值变更经 trace_add 自动写盘。
        # 写样机参数默认并行 1(2026-07-19 用户要求):多台并发容易撞 UBUS HTTP / telnet login / NIC,
        # 默认串行更稳;Spinbox 仍允许 1–8 现场上调。升级窗口的 parallel_count 仍走 DEFAULT_PARALLEL_COUNT=2。
        self.parameter_parallel_count_var = IntVar(value=DEFAULT_PARAMETER_PARALLEL_COUNT)
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
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        # 程序重开后内存记录为空，但路径已由 sample_upgrade_settings.ini 恢复；
        # 自动重新加载，使窗口预检和全流程状态都基于同一份已选参数表。
        saved_table_path = self.parameter_table_path_var.get().strip()
        if saved_table_path and self.parameter_loaded_table_path != saved_table_path:
            self._load_parameter_table(Path(saved_table_path), report_error=False)
        else:
            self._refresh_parameter_preflight()

    def _parameter_channel_ports(self) -> list[tuple[str, str]]:
        self._capture_current_channel()
        items: list[tuple[str, str]] = []
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if not vlan:
                items.append(("", ""))
                continue
            try:
                items.append((vlan, vlan_to_serial_port(vlan)))
            except ValueError:
                items.append((vlan, ""))
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

    def _refresh_parameter_preflight(self) -> None:
        if self.parameter_writer_window is None or not self.parameter_writer_window.winfo_exists():
            return
        channel_ports = self._parameter_channel_ports()
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

    def _start_sample_parameter_write(self) -> bool:
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
        if not messagebox.askyesno(
            "确认批量写样机参数",
            f"将并行写入 {len(preflight.targets)} 台样机（最多 {parallel_count} 台）：\n{target_text}\n\n"
            f"每台会依次：\n{action_summary}\n\n是否继续？",
            parent=self.parameter_writer_window,
        ):
            return False
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
                    0, lambda vlan=vlan, session=session, log_path=log_path: self.serial_terminal.attach_upgrade(vlan, session, log_path)
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
        if success_count == len(results):
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
        dialog.geometry("680x750")
        dialog.minsize(680, 750)
        dialog.transient(self.parameter_writer_window)
        dialog.grab_set()
        container = ttk.Frame(dialog, padding=14)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text=f"将为 {len(vlans)} 个已勾选 VLAN 生成一行参数。", style="CardHint.TLabel").pack(anchor="w", pady=(0, 10))

        fields = {
            "SN 前缀": StringVar(value="TESTSN"),
            "XPON SN 前缀": StringVar(value="XPON"),
            "2.4G SSID 前缀": StringVar(value="Test24G"),
            "5G SSID 前缀": StringVar(value="Test5G"),
            "SN/GPON SN 随机后缀长度": StringVar(value="8"),
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
                suffix_length = int(fields["SN/GPON SN 随机后缀长度"].get().strip())
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
                        sn_prefix=fields["SN 前缀"].get(),
                        xpon_prefix=fields["XPON SN 前缀"].get(),
                        ssid_24_prefix=fields["2.4G SSID 前缀"].get(),
                        ssid_5_prefix=fields["5G SSID 前缀"].get(),
                        suffix_length=suffix_length,
                        fixed_values=fixed_values,
                    ),
                )
            except Exception as exc:
                messagebox.showwarning("生成参数表失败", str(exc), parent=dialog)
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
                return
            dialog.grab_release()
            dialog.destroy()
            self._load_parameter_table(Path(path))
            messagebox.showinfo("参数表已生成", f"已生成 {len(records)} 条记录并完成预检。\n生成不会自动写入设备。", parent=self.parameter_writer_window)

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="生成并保存...", command=generate_and_save, style="Primary.TButton").pack(side="right")
        ttk.Button(buttons, text="取消", command=lambda: (dialog.grab_release(), dialog.destroy()), style="Secondary.TButton").pack(side="right", padx=(0, 8))

    def _bind_onu_registration_autosave(self) -> None:
        for variable in (self.onu_olt_ip_var, self.onu_username_var, self.onu_password_var):
            variable.trace_add("write", lambda *_args: self._schedule_onu_registration_save())

    def _current_onu_registration_config(self) -> OnuRegistrationConfig:
        return OnuRegistrationConfig(
            olt_ip=self.onu_olt_ip_var.get(),
            username=self.onu_username_var.get(),
            password=self.onu_password_var.get(),
        )

    def _schedule_onu_registration_save(self) -> None:
        if self.onu_save_after_id is not None:
            try:
                self.after_cancel(self.onu_save_after_id)
            except Exception:
                pass
        self.onu_save_after_id = self.after(400, self._save_onu_registration_config)

    def _save_onu_registration_config(self) -> None:
        self.onu_save_after_id = None
        self.onu_registration_store.save(self._current_onu_registration_config())

    def _bind_sample_upgrade_autosave(self) -> None:
        for variable in (
            self.upgrade_mode_var,
            self.upgrade_transfer_var,
            self.upgrade_execution_var,
            self.upgrade_restore_factory_var,
            self.upgrade_username_var,
            self.upgrade_password_var,
            self.upgrade_firmware_var,
            self.parameter_initial_username_var,
            self.parameter_initial_password_var,
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

    @staticmethod
    def _normalize_upgrade_execution_mode(execution_mode: str) -> str:
        if execution_mode in UPGRADE_EXECUTION_OPTIONS:
            return execution_mode
        return UPGRADE_EXECUTION_SERIAL

    def _current_sample_upgrade_settings(self) -> SampleUpgradeSettings:
        return SampleUpgradeSettings(
            upgrade_mode=self.upgrade_mode_var.get(),
            transfer_method=LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get()),
            execution_mode=LineCheckAssistant._normalize_upgrade_execution_mode(self.upgrade_execution_var.get()),
            parallel_count=clamp_parallel_count(self.upgrade_parallel_count_var.get()),
            restore_factory=bool(self.upgrade_restore_factory_var.get()),
            username=self.upgrade_username_var.get(),
            password=self.upgrade_password_var.get(),
            firmware_path=self.upgrade_firmware_var.get(),
            parameter_initial_username=self.parameter_initial_username_var.get(),
            parameter_initial_password=self.parameter_initial_password_var.get(),
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

        dialog = Toplevel(self)
        self.onu_registration_window = dialog
        dialog.title("ONU注册")
        dialog.geometry("896x580")
        dialog.minsize(836, 530)
        dialog.transient(self)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        Label(content, text="ONU注册", font=(FONT_FAMILY, 18, "bold"), background=COLOR_BG, foreground=COLOR_TEXT).pack(anchor="w")
        Label(
            content,
            text="输入 OLT IP 和登录凭据后，可先进行 Telnet 连通性测试，再查询未注册的 ONU。",
            foreground=COLOR_MUTED,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(6, 16))

        overview = ttk.LabelFrame(content, text="ONU注册配置")
        overview.pack(fill="x")
        for column, weight in ((1, 1), (3, 1), (4, 1), (5, 0)):
            overview.columnconfigure(column, weight=weight)

        Label(overview, text="OLT IP", width=16, anchor="w").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        ttk.Entry(overview, textvariable=self.onu_olt_ip_var, width=22).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=8)
        self.onu_status_label = Label(
            overview,
            textvariable=self.onu_telnet_status_var,
            width=28,
            anchor="w",
            background=COLOR_SURFACE_SUBTLE,
            foreground=COLOR_TEXT,
            relief="solid",
            borderwidth=1,
            padx=8,
        )
        self.onu_status_label.grid(row=0, column=2, columnspan=3, sticky="ew", padx=(0, 12), pady=8)
        self.onu_telnet_test_button = ttk.Button(
            overview,
            text="连通性测试",
            command=self._on_onu_telnet_test_clicked,
            style="Secondary.TButton",
        )
        self.onu_telnet_test_button.grid(row=0, column=5, sticky="e", padx=12, pady=8)

        Label(overview, text="用户名", width=16, anchor="w").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        ttk.Entry(overview, textvariable=self.onu_username_var, width=22).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=8)
        Label(overview, text="密码", width=8, anchor="w").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=8)
        onu_password_container = Frame(overview, background=COLOR_SURFACE)
        onu_password_container.grid(row=1, column=3, columnspan=2, sticky="ew", padx=(0, 0), pady=8)
        self.onu_password_entry = ttk.Entry(onu_password_container, textvariable=self.onu_password_var, width=22, show="*")
        self.onu_password_entry.pack(side="left", fill="x", expand=True)
        self.onu_password_toggle = Button(
            onu_password_container,
            text="👁",
            width=3,
            command=self._toggle_onu_password_visibility,
        )
        self.onu_password_toggle.pack(side="right", padx=(8, 0))

        Label(overview, text="查询未注册的ONU", width=16, anchor="w").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        self.onu_query_button = ttk.Button(
            overview,
            text="开始查询",
            command=self._on_onu_query_unregistered_clicked,
            style="Secondary.TButton",
        )
        self.onu_query_button.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=8)
        self.onu_select_all_button = ttk.Button(
            overview,
            text="全选",
            command=self._select_all_unregistered_onus,
            style="Secondary.TButton",
            state="disabled",
        )
        self.onu_select_all_button.grid(row=2, column=2, sticky="w", padx=(12, 6), pady=8)
        self.onu_clear_selection_button = ttk.Button(
            overview,
            text="取消全选",
            command=self._clear_unregistered_onu_selection,
            style="Secondary.TButton",
            state="disabled",
        )
        self.onu_clear_selection_button.grid(row=2, column=3, sticky="w", padx=(0, 4), pady=8)
        self.onu_register_button = ttk.Button(
            overview,
            text="开始注册",
            command=self._on_onu_register_selected_clicked,
            style="Primary.TButton",
            state="disabled",
        )
        self.onu_register_button.grid(row=2, column=4, sticky="w", padx=(0, 6), pady=8)
        self.onu_query_status_label = Label(
            overview,
            textvariable=self.onu_query_status_var,
            anchor="nw",
            justify="left",
            background=COLOR_SURFACE_SUBTLE,
            foreground=COLOR_TEXT,
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=4,
            wraplength=640,
        )
        self.onu_query_status_label.grid(row=3, column=1, columnspan=5, sticky="ew", padx=(0, 12), pady=(0, 8))
        self.onu_query_status_label.bind(
            "<Configure>",
            lambda event: self.onu_query_status_label.configure(wraplength=max(280, event.width - 18)),
        )
        self.onu_unregistered_list_frame = Frame(
            overview,
            background=COLOR_SURFACE_SUBTLE,
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
        )
        self.onu_unregistered_list_frame.grid(row=4, column=1, columnspan=5, sticky="ew", padx=(0, 12), pady=(0, 8))
        overview.columnconfigure(1, weight=1)

        Label(
            content,
            text="注册会修改 OLT 当前配置；执行前会再次确认，完成后请重新查询确认 ONU 上线。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(16, 0))

        def close_dialog() -> None:
            try:
                self._cancel_pending_onu_registration_save()
                self._save_onu_registration_config()
            except Exception:
                pass
            finally:
                dialog.destroy()
                self.onu_registration_window = None

        ttk.Button(content, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(
            side="bottom", anchor="e", pady=(18, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def _on_onu_telnet_test_clicked(self) -> None:
        if self.onu_telnet_test_running:
            return
        host = self.onu_olt_ip_var.get().strip()
        if not host:
            self._set_onu_telnet_status("请先输入 OLT IP", COLOR_DANGER)
            messagebox.showwarning("OLT IP 为空", "请先输入 OLT IP 后再进行连通性测试。", parent=self.onu_registration_window)
            return
        username = self.onu_username_var.get().strip()
        password = self.onu_password_var.get()
        if not username or not password:
            self._set_onu_query_status("请先输入 OLT 用户名和密码", COLOR_DANGER)
            messagebox.showwarning("登录信息不完整", "请先输入 OLT 用户名和密码。", parent=self.onu_registration_window)
            return
        confirmed = messagebox.askyesno(
            "确认登录 OLT",
            "连通性测试通过后将登录 OLT，并下发 configure terminal 进入全局模式。\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return

        self.onu_telnet_test_running = True
        self._set_onu_telnet_status(f"正在测试 Telnet 连接：{host}:23", COLOR_WARNING)
        self._set_onu_query_status("等待 Telnet 连通性测试通过后登录 OLT", COLOR_WARNING)
        if hasattr(self, "onu_telnet_test_button"):
            self.onu_telnet_test_button.configure(state="disabled")
        thread = threading.Thread(target=self._onu_telnet_test_worker, args=(host, username, password), daemon=True)
        thread.start()

    def _onu_telnet_test_worker(self, host: str, username: str, password: str) -> None:
        telnet_result = check_telnet_connection(host)
        login_result = None
        if telnet_result.ok:
            login_result = login_olt_and_enter_global_mode(host, username, password)
        self.after(0, lambda: self._complete_onu_telnet_test(host, telnet_result, login_result))

    def _complete_onu_telnet_test(self, host: str, telnet_result: CommandResult, login_result: CommandResult | None = None) -> None:
        self.onu_telnet_test_running = False
        if hasattr(self, "onu_telnet_test_button"):
            self.onu_telnet_test_button.configure(state="normal")
        self._set_onu_telnet_status(telnet_result.message, COLOR_SUCCESS if telnet_result.ok else COLOR_DANGER)
        self._log(f"ONU注册 OLT Telnet 测试：{host} - {telnet_result.message}")
        if not telnet_result.ok:
            self._set_onu_query_status("Telnet 未连通，未执行 OLT 登录", COLOR_DANGER)
            return
        if login_result is None:
            self._set_onu_query_status("Telnet 已连通，但未执行 OLT 登录", COLOR_WARNING)
            return
        self._set_onu_query_status(login_result.message, COLOR_SUCCESS if login_result.ok else COLOR_DANGER)
        self._log(f"ONU注册 OLT 登录：{host} - {login_result.message}")

    def _on_onu_query_unregistered_clicked(self) -> None:
        if self.onu_query_running:
            return
        host = self.onu_olt_ip_var.get().strip()
        username = self.onu_username_var.get().strip()
        password = self.onu_password_var.get()
        if not host:
            self._set_onu_query_status("请先输入 OLT IP", COLOR_DANGER)
            messagebox.showwarning("OLT IP 为空", "请先输入 OLT IP 后再查询未注册 ONU。", parent=self.onu_registration_window)
            return
        if not username or not password:
            self._set_onu_query_status("请先输入 OLT 用户名和密码", COLOR_DANGER)
            messagebox.showwarning("登录信息不完整", "请先输入 OLT 用户名和密码。", parent=self.onu_registration_window)
            return
        confirmed = messagebox.askyesno(
            "确认查询未注册 ONU",
            "将登录 OLT 并执行 show gpon onu uncfg 查询所有 PON 口下的未注册 ONU。\n是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return

        self.onu_query_running = True
        self._set_onu_query_status("正在查询所有 PON 口下的未注册 ONU...", COLOR_WARNING)
        self._render_unregistered_onu_selection([])
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="disabled")
        thread = threading.Thread(target=self._onu_query_unregistered_worker, args=(host, username, password), daemon=True)
        thread.start()

    def _onu_query_unregistered_worker(self, host: str, username: str, password: str) -> None:
        result = query_unregistered_onus(host, username, password)
        self.after(0, lambda: self._complete_onu_query_unregistered(host, result))

    def _complete_onu_query_unregistered(self, host: str, result: CommandResult) -> None:
        self.onu_query_running = False
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        if result.ok:
            onus = parse_unregistered_onus(result.output)
            message = f"查询到 {len(onus)} 个未注册 ONU，请选择要注册的 ONU" if onus else result.message
            self._set_onu_query_status(message, COLOR_SUCCESS)
            self._render_unregistered_onu_selection(onus)
        else:
            self._set_onu_query_status(result.message, COLOR_DANGER)
            self._render_unregistered_onu_selection([])
        self._log(f"ONU注册 查询未注册 ONU：{host} - {result.message}")

    def _on_onu_register_selected_clicked(self) -> None:
        if self.onu_register_running:
            return
        selected_onus = self._selected_unregistered_onus()
        if not selected_onus:
            self._set_onu_query_status("请先勾选要注册的 ONU", COLOR_DANGER)
            messagebox.showwarning("未选择 ONU", "请先在未注册 ONU 列表中勾选要注册的 ONU。", parent=self.onu_registration_window)
            return
        host = self.onu_olt_ip_var.get().strip()
        username = self.onu_username_var.get().strip()
        password = self.onu_password_var.get()
        if not host:
            self._set_onu_query_status("请先输入 OLT IP", COLOR_DANGER)
            messagebox.showwarning("OLT IP 为空", "请先输入 OLT IP 后再注册 ONU。", parent=self.onu_registration_window)
            return
        if not username or not password:
            self._set_onu_query_status("请先输入 OLT 用户名和密码", COLOR_DANGER)
            messagebox.showwarning("登录信息不完整", "请先输入 OLT 用户名和密码。", parent=self.onu_registration_window)
            return
        onu_lines = "\n".join(f"- {onu.onu_index}  SN:{onu.serial_number}" for onu in selected_onus)
        confirmed = messagebox.askyesno(
            "确认注册 ONU",
            f"将登录 OLT 并下发 {len(selected_onus)} 个 ONU 的注册配置，ONU 类型为 SD-41。\n"
            f"{onu_lines}\n\n如果新增 ONU 业务配置下发失败，软件会自动查找已注册但未在线的旧 ONU，"
            "优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，"
            "删除后重新注册新 ONU。\n"
            "该操作会修改 OLT 当前配置，但不会自动保存配置。是否继续？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            return

        self.onu_register_running = True
        self._set_onu_query_status(f"正在注册 {len(selected_onus)} 个 ONU...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        thread = threading.Thread(target=self._onu_register_selected_worker, args=(host, username, password, selected_onus), daemon=True)
        thread.start()

    def _onu_register_selected_worker(self, host: str, username: str, password: str, selected_onus) -> None:
        result = register_unregistered_onus(host, username, password, selected_onus)
        self.after(0, lambda: self._complete_onu_register_selected(host, username, password, result))

    def _complete_onu_register_selected(self, host: str, username: str, password: str, result: CommandResult) -> None:
        self.onu_register_running = False
        self._set_onu_registration_action_buttons_state("normal" if self.onu_unregistered_selection_vars else "disabled")
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"ONU注册 开始注册：{host} - {result.message}")
        if not result.ok:
            return
        confirmed = messagebox.askyesno(
            "保存 OLT 最新配置",
            "ONU 注册配置已下发到 OLT 当前运行配置。\n是否执行 write，将最新配置写入启动配置？",
            parent=self.onu_registration_window,
        )
        if not confirmed:
            self._log(f"ONU注册 保存 OLT 配置：{host} - 用户选择暂不保存")
            return

        self.onu_save_olt_running = True
        self._set_onu_query_status("正在执行 write 保存 OLT 最新配置...", COLOR_WARNING)
        self._set_onu_registration_action_buttons_state("disabled")
        thread = threading.Thread(target=self._onu_save_olt_configuration_worker, args=(host, username, password), daemon=True)
        thread.start()

    def _onu_save_olt_configuration_worker(self, host: str, username: str, password: str) -> None:
        result = save_olt_configuration(host, username, password)
        self.after(0, lambda: self._complete_onu_save_olt_configuration(host, result))

    def _complete_onu_save_olt_configuration(self, host: str, result: CommandResult) -> None:
        self.onu_save_olt_running = False
        self._set_onu_registration_action_buttons_state("normal" if self.onu_unregistered_selection_vars else "disabled")
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state="normal")
        self._set_onu_query_status(result.message, COLOR_SUCCESS if result.ok else COLOR_DANGER)
        self._log(f"ONU注册 保存 OLT 配置：{host} - {result.message}")

    def _set_onu_telnet_status(self, message: str, foreground: str = COLOR_TEXT) -> None:
        self.onu_telnet_status_var.set(message)
        if hasattr(self, "onu_status_label"):
            self.onu_status_label.configure(foreground=foreground)

    def _set_onu_query_status(self, message: str, foreground: str = COLOR_TEXT) -> None:
        self.onu_query_status_var.set(message)
        if hasattr(self, "onu_query_status_label"):
            self.onu_query_status_label.configure(foreground=foreground)

    def _render_unregistered_onu_selection(self, onus) -> None:
        if not hasattr(self, "onu_unregistered_list_frame"):
            self.onu_unregistered_selection_vars = []
            return
        for child in self.onu_unregistered_list_frame.winfo_children():
            child.destroy()
        self.onu_unregistered_selection_vars = []
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

        for onu in onus:
            variable = BooleanVar(value=False)
            text = f"{onu.onu_index}  SN:{onu.serial_number}  状态:{onu.state}"
            Checkbutton(
                self.onu_unregistered_list_frame,
                text=text,
                variable=variable,
                anchor="w",
                background=COLOR_SURFACE_SUBTLE,
                foreground=COLOR_TEXT,
                selectcolor=COLOR_SURFACE,
            ).pack(fill="x", anchor="w")
            self.onu_unregistered_selection_vars.append((onu, variable))
        self._set_unregistered_onu_selection_buttons_state("normal")

    def _set_unregistered_onu_selection_buttons_state(self, state: str) -> None:
        if hasattr(self, "onu_select_all_button"):
            self.onu_select_all_button.configure(state=state)
        if hasattr(self, "onu_clear_selection_button"):
            self.onu_clear_selection_button.configure(state=state)
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(state=state)

    def _set_onu_registration_action_buttons_state(self, state: str) -> None:
        if hasattr(self, "onu_select_all_button"):
            self.onu_select_all_button.configure(state=state)
        if hasattr(self, "onu_clear_selection_button"):
            self.onu_clear_selection_button.configure(state=state)
        if hasattr(self, "onu_register_button"):
            self.onu_register_button.configure(state=state)
        if hasattr(self, "onu_query_button"):
            self.onu_query_button.configure(state=state)

    def _selected_unregistered_onus(self):
        return [onu for onu, variable in self.onu_unregistered_selection_vars if variable.get()]

    def _select_all_unregistered_onus(self) -> None:
        for _onu, variable in self.onu_unregistered_selection_vars:
            variable.set(True)

    def _clear_unregistered_onu_selection(self) -> None:
        for _onu, variable in self.onu_unregistered_selection_vars:
            variable.set(False)

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
        dialog.geometry("820x580")
        dialog.minsize(760, 530)
        dialog.transient(self)
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
        self.upgrade_execution_label = Label(overview, text="执行方式", anchor="w")
        self.upgrade_execution_label.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=8)
        self.upgrade_execution_combo = ttk.Combobox(
            overview,
            textvariable=self.upgrade_execution_var,
            values=UPGRADE_EXECUTION_OPTIONS,
            state="readonly",
            width=18,
        )
        self.upgrade_execution_combo.grid(row=1, column=3, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_execution_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_upgrade_parallel_count_visibility())
        self.upgrade_parallel_count_label = Label(
            overview,
            text=f"并行数 (1-{MAX_PARALLEL_UPGRADES})",
            anchor="w",
        )
        self.upgrade_parallel_count_label.grid(row=1, column=4, sticky="w", padx=(0, 8), pady=8)
        self.upgrade_parallel_count_spin = ttk.Spinbox(
            overview,
            from_=1,
            to=MAX_PARALLEL_UPGRADES,
            textvariable=self.upgrade_parallel_count_var,
            width=5,
        )
        self.upgrade_parallel_count_spin.grid(row=1, column=5, sticky="w", padx=(0, 12), pady=8)
        self.upgrade_restore_factory_label = Label(
            overview,
            textvariable=self.upgrade_restore_factory_text_var,
            anchor="w",
            cursor="hand2",
        )
        self.upgrade_restore_factory_label.grid(row=0, column=2, columnspan=2, sticky="w", padx=(0, 12), pady=8)
        self.upgrade_restore_factory_label.bind("<Button-1>", self._toggle_upgrade_restore_factory)

        Label(overview, text="超级用户名", anchor="w").grid(row=2, column=0, sticky="w", padx=(12, 8), pady=8)
        ttk.Entry(overview, textvariable=self.upgrade_username_var).grid(
            row=2, column=1, sticky="ew", padx=(0, 18), pady=8
        )
        Label(overview, text="密码", anchor="w").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=8)
        password_container = Frame(overview, background=COLOR_SURFACE)
        password_container.grid(row=2, column=3, columnspan=2, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_password_entry = ttk.Entry(password_container, textvariable=self.upgrade_password_var, show="*")
        self.upgrade_password_entry.pack(side="left", fill="x", expand=True)
        self.upgrade_password_toggle = Button(
            password_container,
            text="👁",
            width=3,
            command=self._toggle_upgrade_password_visibility,
        )
        self.upgrade_password_toggle.pack(side="right", padx=(5, 0))

        Label(overview, text="升级固件", anchor="w").grid(row=3, column=0, sticky="w", padx=(12, 8), pady=8)
        ttk.Entry(overview, textvariable=self.upgrade_firmware_var, state="readonly").grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=8
        )
        Button(overview, text="选择固件...", command=self._select_upgrade_firmware).grid(
            row=3, column=4, sticky="e", padx=(0, 12), pady=8
        )

        Label(overview, text="目标样机", anchor="w").grid(row=4, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_targets_var,
            foreground=COLOR_TEXT,
            anchor="w",
            justify="left",
            wraplength=590,
        ).grid(row=4, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=8)

        Label(overview, text="执行状态", anchor="w").grid(row=5, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_status_var,
            foreground=COLOR_TEXT,
            anchor="w",
        ).grid(row=5, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_progress = ttk.Progressbar(
            overview,
            variable=self.upgrade_progress_var,
            maximum=100,
            mode="determinate",
        )
        self.upgrade_progress.grid(row=6, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=(0, 10))
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
                dialog.destroy()
                self.upgrade_window = None

        buttons = Frame(content, background=COLOR_BG)
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        ttk.Button(buttons, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(side="right")
        ttk.Button(buttons, text="开始升级", width=12, command=self._on_upgrade_start_clicked, style="Primary.TButton").pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

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

        if not hasattr(self, "upgrade_execution_label") or not hasattr(self, "upgrade_execution_combo"):
            return
        show_execution_mode = (
            self.upgrade_mode_var.get() == "全包升级"
            and current_transfer in SERIAL_FULL_PACKAGE_TRANSFERS
        )
        if show_execution_mode:
            self.upgrade_execution_label.grid()
            self.upgrade_execution_combo.grid()
        else:
            self.upgrade_execution_var.set(UPGRADE_EXECUTION_SERIAL)
            self.upgrade_execution_label.grid_remove()
            self.upgrade_execution_combo.grid_remove()
        self._refresh_upgrade_parallel_count_visibility()

    def _refresh_upgrade_parallel_count_visibility(self) -> None:
        """执行方式 = 串行 或 全包升级未启用时，并行数 Spinbox 灰显。"""
        if not hasattr(self, "upgrade_parallel_count_label") or not hasattr(self, "upgrade_parallel_count_spin"):
            return
        show = (
            self.upgrade_mode_var.get() == "全包升级"
            and LineCheckAssistant._normalize_upgrade_execution_mode(self.upgrade_execution_var.get())
            == UPGRADE_EXECUTION_PARALLEL
        )
        if show:
            self.upgrade_parallel_count_label.grid()
            self.upgrade_parallel_count_spin.grid()
            self.upgrade_parallel_count_spin.state(["!disabled"])
        else:
            self.upgrade_parallel_count_label.grid_remove()
            self.upgrade_parallel_count_spin.grid_remove()
            self.upgrade_parallel_count_spin.state(["disabled"])

    def _on_upgrade_start_clicked(self) -> None:
        self._capture_current_channel()
        if not self._validate_upgrade_required_fields():
            return
        transfer_method = LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get())
        if self.upgrade_mode_var.get() == "全包升级" and transfer_method in SERIAL_FULL_PACKAGE_TRANSFERS:
            self._start_serial_tftp_copy_upgrade()
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

    def _start_page_upgrade(self) -> bool:
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
        if not messagebox.askyesno(
            "确认页面升级",
            f"将通过 UBUS 页面升级并行升级 {len(requests)} 台样机：{target_text}\n\n"
            f"该操作会上传固件、触发升级并等待设备重启上线。\n恢复出厂：{restore_factory_text}\n\n是否继续？",
            parent=self.upgrade_window,
        ):
            return False

        self._set_upgrade_status("", f"准备页面升级 {len(requests)} 台样机", 0)
        thread = threading.Thread(target=self._page_upgrade_worker, args=(requests,), daemon=True)
        thread.start()
        return True

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

    def _page_upgrade_worker(self, requests: list[PageUpgradeRequest]) -> None:
        total = len(requests)
        completed = 0

        def on_item_complete(item_result) -> None:
            nonlocal completed
            completed += 1
            progress = (completed / total) * 100 if total else 100
            stage = "页面升级完成" if item_result.result.ok else "页面升级失败"
            self.after(0, lambda request=item_result.request, stage=stage, progress=progress: self._set_upgrade_status(request.vlan, stage, progress))
            self.log_queue.put(item_result.result.message)

        self.log_queue.put(f"开始 UBUS 页面升级，共 {total} 台样机。")
        results = run_page_upgrade_batch(
            requests,
            on_output=lambda line: self.log_queue.put(line),
            on_item_complete=on_item_complete,
        )
        self.after(0, lambda: self._complete_page_upgrade(results))

    def _complete_page_upgrade(self, results) -> None:
        total = len(results)
        success_count = sum(1 for item in results if item.result.ok)
        if success_count == total:
            self._set_upgrade_status("", f"页面升级完成：{success_count}/{total} 台", 100)
            messagebox.showinfo("样机升级完成", f"页面升级完成：{success_count}/{total} 台样机已升级。", parent=self.upgrade_window)
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", True, f"页面升级完成：{success_count}/{total} 台成功。")
            return
        failed_messages = [item.result.message for item in results if not item.result.ok]
        progress = (success_count / total) * 100 if total else 0
        self._set_upgrade_status("", f"页面升级完成：{success_count}/{total} 台成功", progress)
        messagebox.showerror("样机升级失败", "\n".join(failed_messages), parent=self.upgrade_window)
        _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, f"页面升级完成：{success_count}/{total} 台成功。")

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

    def _start_serial_tftp_copy_upgrade(self) -> bool:
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
        for channel in channels:
            try:
                tftp_server_ip = self._tftp_server_ip_for_channel(channel)
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
                power_channel=power_channel,
            )
            upgrade_items.append((channel, request))

        target_text = "、".join(request.vlan for _channel, request in upgrade_items)
        transfer_action = "执行 Tftp Put" if transfer_method == TFTP_PUT_TRANSFER else "下发 Tftp指令"
        execution_mode = LineCheckAssistant._normalize_upgrade_execution_mode(self.upgrade_execution_var.get())
        parallel_count = clamp_parallel_count(self.upgrade_parallel_count_var.get())
        parallel_serial_tftp = (
            transfer_method in SERIAL_FULL_PACKAGE_TRANSFERS
            and execution_mode == UPGRADE_EXECUTION_PARALLEL
        )
        execution_text = (
            f"并行（最多 {parallel_count} 台，完成即补位）" if parallel_serial_tftp else "串行"
        )
        restore_factory_text = "开启，会在最终系统登录后执行恢复出厂" if bool(self.upgrade_restore_factory_var.get()) else "关闭，不会执行恢复出厂"
        power_instruction = (
            "每台样机会自动上电、进入 boot、"
            if power_serial_port
            else "未选择程控电源 COM 口。请先手动重启样机，确认样机已重启后再点击“是”继续；随后将进入 boot、"
        )
        post_transfer_instruction = "并复位/重新上电。" if power_serial_port else "及后续升级流程。"
        if not messagebox.askyesno(
            "确认样机升级",
            f"将升级 {len(upgrade_items)} 台样机：{target_text}\n执行方式：{execution_text}\n\n"
            f"升级过程不会改写 network_card_ip.ini；{power_instruction}{transfer_action}{post_transfer_instruction}\n"
            f"恢复出厂：{restore_factory_text}\n\n是否继续？",
            parent=self.upgrade_window,
        ):
            return False

        terminal = getattr(self, "serial_terminal", None)
        if terminal is not None:
            terminal.begin_upgrade_logs([request.vlan for _channel, request in upgrade_items])
        if parallel_serial_tftp:
            self._set_upgrade_status("", f"准备并行升级 {len(upgrade_items)} 台样机（最多 {parallel_count} 台）", 0)
            parallel_worker = (
                self._parallel_tftp_command_upgrade_worker
                if transfer_method == TFTP_COMMAND_TRANSFER
                else self._parallel_tftp_put_upgrade_worker
            )
            thread = threading.Thread(target=parallel_worker, args=(upgrade_items, parallel_count), daemon=True)
        else:
            self._set_upgrade_status("", f"准备串行升级 {len(upgrade_items)} 台样机", 0)
            thread = threading.Thread(target=self._serial_tftp_copy_upgrade_worker, args=(upgrade_items,), daemon=True)
        thread.start()
        return True

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

    def _serial_tftp_copy_upgrade_worker(self, upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]]) -> None:
        total = len(upgrade_items)
        completed = 0
        failed_request = None
        failed_result = None
        for index, (_channel, request) in enumerate(upgrade_items, start=1):
            start_progress = ((index - 1) / total) * 100 if total else 0
            self.after(
                0,
                lambda request=request, index=index, total=total, progress=start_progress: self._set_upgrade_status(
                    request.vlan,
                    f"串行升级 {index}/{total}，准备上电",
                    progress,
                ),
            )
            self.log_queue.put(f"开始串行升级 {index}/{total}：{request.vlan}")
            try:
                result = run_single_full_package_upgrade(
                    request,
                    self.serial_session_manager,
                    on_output=lambda line: self.log_queue.put(line),
                    on_session_ready=lambda vlan, session, log_path: self.after(
                        0, lambda: self.serial_terminal.attach_upgrade(vlan, session, log_path)
                    ),
                )
            except Exception as exc:
                result = CommandResult(False, f"{request.vlan} 升级流程异常：{exc}")
            if not result.ok:
                failed_request = request
                failed_result = result
                break
            completed = index
            finish_progress = (completed / total) * 100 if total else 100
            self.log_queue.put(result.message)
            self.after(
                0,
                lambda request=request, index=index, total=total, progress=finish_progress: self._set_upgrade_status(
                    request.vlan,
                    f"串行升级 {index}/{total} 完成",
                    progress,
                ),
            )
        self.after(0, lambda: self._complete_serial_tftp_copy_upgrade(total, completed, failed_request, failed_result))
        terminal = getattr(self, "serial_terminal", None)
        if terminal is not None:
            self.after(100, terminal.finish_upgrade_logs)

    def _parallel_tftp_command_upgrade_worker(
        self,
        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]],
        parallel_count: int = DEFAULT_PARALLEL_COUNT,
    ) -> None:
        requests = [request for _channel, request in upgrade_items]
        total = len(requests)
        max_workers = max(1, min(clamp_parallel_count(parallel_count), total))
        started = succeeded = failed = 0

        def refresh_status() -> None:
            running = started - succeeded - failed
            queued = total - started
            progress = ((succeeded + failed) / total) * 100 if total else 100
            self.after(
                0,
                lambda: self._set_upgrade_status(
                    "",
                    f"并行升级：运行中 {running} 台，已成功 {succeeded} 台，已失败 {failed} 台，排队 {queued} 台",
                    progress,
                ),
            )

        def on_item_started(request: FullPackageUpgradeRequest) -> None:
            nonlocal started
            started += 1
            self.log_queue.put(f"开始并行升级：{request.vlan}")
            refresh_status()

        def on_item_complete(item) -> None:
            nonlocal succeeded, failed
            if item.result.ok:
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
                on_session_ready=lambda vlan, session, log_path: self.after(
                    0, lambda: self.serial_terminal.attach_upgrade(vlan, session, log_path)
                ),
                on_item_started=on_item_started,
                on_item_complete=on_item_complete,
            )
            self.after(0, lambda: self._complete_parallel_tftp_command_upgrade(total, results))
        except Exception as exc:
            self.after(0, lambda: self._complete_parallel_tftp_command_upgrade(total, [], str(exc)))
        finally:
            terminal = getattr(self, "serial_terminal", None)
            if terminal is not None:
                self.after(100, terminal.finish_upgrade_logs)

    def _parallel_tftp_put_upgrade_worker(
        self,
        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]],
        parallel_count: int = DEFAULT_PARALLEL_COUNT,
    ) -> None:
        requests = [request for _channel, request in upgrade_items]
        total = len(requests)
        max_workers = max(1, min(clamp_parallel_count(parallel_count), total))
        started = succeeded = failed = 0

        def refresh_status() -> None:
            running = started - succeeded - failed
            queued = total - started
            progress = ((succeeded + failed) / total) * 100 if total else 100
            self.after(
                0,
                lambda: self._set_upgrade_status(
                    "",
                    f"并行升级：运行中 {running} 台，已成功 {succeeded} 台，已失败 {failed} 台，排队 {queued} 台",
                    progress,
                ),
            )

        def on_item_started(request: FullPackageUpgradeRequest) -> None:
            nonlocal started
            started += 1
            self.log_queue.put(f"开始并行升级：{request.vlan}")
            refresh_status()

        def on_item_complete(item) -> None:
            nonlocal succeeded, failed
            if item.result.ok:
                succeeded += 1
            else:
                failed += 1
            self.log_queue.put(item.result.message)
            refresh_status()

        try:
            results = run_parallel_tftp_put_upgrades(
                requests,
                self.serial_session_manager,
                max_workers=max_workers,
                on_output=lambda vlan, line: self.log_queue.put(f"[{vlan}] {line}"),
                on_session_ready=lambda vlan, session, log_path: self.after(
                    0, lambda: self.serial_terminal.attach_upgrade(vlan, session, log_path)
                ),
                on_item_started=on_item_started,
                on_item_complete=on_item_complete,
            )
            self.after(0, lambda: self._complete_parallel_tftp_put_upgrade(total, results))
        except Exception as exc:
            self.after(0, lambda: self._complete_parallel_tftp_put_upgrade(total, [], str(exc)))
        finally:
            terminal = getattr(self, "serial_terminal", None)
            if terminal is not None:
                self.after(100, terminal.finish_upgrade_logs)

    def _complete_parallel_tftp_command_upgrade(self, total: int, results, orchestration_error: str | None = None) -> None:
        if orchestration_error:
            self._set_upgrade_status("", "并行升级启动失败", 0)
            self._log(orchestration_error)
            messagebox.showerror("并行升级失败", orchestration_error, parent=self.upgrade_window)
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, orchestration_error)
            return
        succeeded = [item for item in results if item.result.ok]
        failed = [item for item in results if not item.result.ok]
        self._set_upgrade_status("", f"并行升级完成：成功 {len(succeeded)}/{total} 台，失败 {len(failed)} 台", 100)
        detail = "\n".join(
            f"{'成功' if item.result.ok else '失败'} {item.request.vlan}：{item.result.message}"
            for item in results
        )
        if failed:
            messagebox.showwarning("样机升级完成", detail, parent=self.upgrade_window)
        else:
            messagebox.showinfo("样机升级完成", detail, parent=self.upgrade_window)
        _finish_pipeline_subtask_if_waiting(
            self, "sample_upgrade", not failed, f"并行 Tftp指令 升级完成：成功 {len(succeeded)}/{total} 台。"
        )

    def _complete_parallel_tftp_put_upgrade(self, total: int, results, orchestration_error: str | None = None) -> None:
        if orchestration_error:
            self._set_upgrade_status("", "并行升级启动失败", 0)
            self._log(orchestration_error)
            messagebox.showerror("并行升级失败", orchestration_error, parent=self.upgrade_window)
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, orchestration_error)
            return
        succeeded = [item for item in results if item.result.ok]
        failed = [item for item in results if not item.result.ok]
        self._set_upgrade_status("", f"并行升级完成：成功 {len(succeeded)}/{total} 台，失败 {len(failed)} 台", 100)
        detail = "\n".join(
            f"{'成功' if item.result.ok else '失败'} {item.request.vlan}：{item.result.message}"
            for item in results
        )
        if failed:
            messagebox.showwarning("样机升级完成", detail, parent=self.upgrade_window)
        else:
            messagebox.showinfo("样机升级完成", detail, parent=self.upgrade_window)
        _finish_pipeline_subtask_if_waiting(
            self, "sample_upgrade", not failed, f"并行 Tftp Put 升级完成：成功 {len(succeeded)}/{total} 台。"
        )

    def _complete_serial_tftp_copy_upgrade(self, total: int, completed: int, failed_request, failed_result) -> None:
        if failed_result is None:
            self._set_upgrade_status("", f"串行升级完成：{completed}/{total} 台", 100)
            messagebox.showinfo("样机升级完成", f"串行升级完成：{completed}/{total} 台样机已升级。", parent=self.upgrade_window)
            _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", True, f"串行升级完成：{completed}/{total} 台成功。")
            return
        progress = (completed / total) * 100 if total else 0
        vlan = failed_request.vlan if failed_request is not None else ""
        self._set_upgrade_status(vlan, f"升级失败，已停止后续样机（已完成 {completed}/{total} 台）", progress)
        self._log(failed_result.message)
        messagebox.showerror("样机升级失败", failed_result.message, parent=self.upgrade_window)
        _finish_pipeline_subtask_if_waiting(self, "sample_upgrade", False, failed_result.message)

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

    def _refresh_upgrade_targets(self) -> None:
        vlans = self._selected_upgrade_vlans()
        if vlans:
            self.upgrade_targets_var.set("、".join(vlans))
        elif any(channel.enabled for channel in self.channels):
            self.upgrade_targets_var.set("已勾选通道尚未配置 VLAN")
        else:
            self.upgrade_targets_var.set("未勾选目标样机")

    def _set_upgrade_status(self, vlan: str, stage: str, progress: float) -> None:
        normalized_progress = max(0.0, min(float(progress), 100.0))
        self.upgrade_progress_var.set(normalized_progress)
        if vlan:
            self.upgrade_status_var.set(f"正在升级 {vlan}：{stage}（{normalized_progress:g}%）")
        else:
            self.upgrade_status_var.set(stage or "尚未开始升级")

    def _open_test_item_config(self) -> None:
        """打开「测试项配置」窗口(Q1=A):加载并允许编辑 test_project_config.ini。

        仅做编辑器,不会驱动任何 telnet / 上下电 / 测试项执行流程。
        """
        if self.test_item_config_window is not None and self.test_item_config_window.winfo_exists():
            self.test_item_config_window.deiconify()
            self.test_item_config_window.lift()
            self.test_item_config_window.focus_force()
            return

        dialog = Toplevel(self)
        self.test_item_config_window = dialog
        # 测试项命令较多，构建过程中先隐藏，避免 Windows 提前显示未绘制完成的空窗口。
        dialog.withdraw()
        dialog.title("测试项配置")
        dialog.geometry("960x940")
        dialog.minsize(960, 940)
        dialog.transient(self)
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
                "编辑测试项 ini（Telnet / 测试项命令 / WiFi / 项目信息）及旧工具参数。当前仅提供编辑入口，"
                "不会改变主程序的执行流程。"
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
        config = store.load()
        legacy_defaults_store = LegacyUiDefaultsStore(LEGACY_UI_DEFAULTS_CONFIG_PATH)
        legacy_defaults = legacy_defaults_store.load()

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
        )
        wifi_vars = self._build_test_item_wifi_tab(notebook, config.connect_wifi, mark_dirty)
        project_info_vars = self._build_test_item_project_info_tab(notebook, config.project_info, mark_dirty)
        legacy_defaults_control = self._build_test_item_ui_defaults_tab(
            notebook,
            legacy_defaults,
            mark_dirty,
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
            except Exception as exc:  # noqa: BLE001 - ini 损坏需明确提示
                messagebox.showerror("加载失败", f"读取 ini 失败：{exc}", parent=dialog)
                return
            legacy_defaults_control["load"](reloaded_legacy_defaults)
            telnet_vars["load"](reloaded.telnet)
            order_control["load"](reloaded.order)
            wifi_vars["load"](reloaded.connect_wifi)
            project_info_vars["load"](reloaded.project_info)
            reset_dirty()
            self._log("[测试项配置] 已从磁盘重新加载（未保存改动已丢弃）")

        def save() -> None:
            try:
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
                    f"- WiFi 连接：{'启用' if captured.connect_wifi.enable else '关闭'}\n"
                    f"- 项目信息：项目={captured.project_info.project_name or '(空)'}，"
                    f"软件版本={captured.project_info.software_version or '(空)'}，"
                    f"内部软件版本={captured.project_info.internal_software_version or '(空)'}，"
                    f"编译时间={captured.project_info.onu_compile_time or '(空)'}\n"
                    f"- 旧工具参数：[ui_defaults] {len(captured_legacy_defaults)} 项\n\n"
                    "测试项 ini 中的原注释会在保存后丢失；config.ini 的其它段和注释会保留。是否继续？"
                ),
                parent=dialog,
            ):
                return
            try:
                store.save(captured)
                legacy_defaults_store.save(captured_legacy_defaults)
            except OSError as exc:
                messagebox.showerror("保存失败", f"写入 ini 失败：{exc}", parent=dialog)
                self._log(f"[测试项配置] 保存失败：{exc}")
                return
            reset_dirty()
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
            if dirty[0]:
                if not messagebox.askyesno(
                    "放弃修改",
                    "当前有未保存的修改，关闭窗口将丢弃这些改动。是否继续？",
                    parent=dialog,
                ):
                    return
            dialog.destroy()
            self.test_item_config_window = None

        ttk.Button(button_bar, text="重新加载", command=reload, style="Secondary.TButton").pack(side="left")
        ttk.Button(button_bar, text="关闭", command=close_dialog, style="Secondary.TButton").pack(side="right")
        ttk.Button(button_bar, text="保存", command=save, style="Primary.TButton").pack(side="right", padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        # 必须让当前按钮回调先结束，再显示并处理一次完整 WM_PAINT 队列。
        dialog.after(0, lambda: _reveal_completed_dialog(dialog))

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

        int_field(frame, 10, "是否需要输入密码（0/1）", need_pwd_flag_var, from_=0, to=1)
        int_field(frame, 11, "免用户名密码登录（0/1）", no_user_pwd_flag_var, from_=0, to=1)
        int_field(frame, 12, "仅执行上下电（0/1）", only_power_var, from_=0, to=1)

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

        def capture() -> OrderConfig:
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
                        retry_times=int(row_dict["retry_var"].get() or 1),
                    )
                )
            return OrderConfig(
                command_fail_retry_interval_time=int(interval_var.get() or DEFAULT_COMMAND_FAIL_RETRY_INTERVAL),
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
        enable_var.trace_add("write", lambda *_a: mark_dirty())
        solution_var = StringVar(value=wifi.product_solution or "openwrt")
        solution_var.trace_add("write", lambda *_a: mark_dirty())

        Label(
            frame,
            text="WiFi 连接测试",
            font=(FONT_FAMILY, 12, "bold"),
            foreground=COLOR_TEXT,
            background=COLOR_BG,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        Checkbutton(
            frame,
            text="启用 WiFi 连接测试",
            variable=enable_var,
            onvalue=1,
            offvalue=0,
            background=COLOR_BG,
            activebackground=COLOR_BG,
            highlightthickness=0,
            borderwidth=0,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=6)

        Label(frame, text="产品方案", width=24, anchor="w", background=COLOR_BG).grid(
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

        Label(
            frame,
            text=(
                "老工具当前仅支持 openwrt；bcm / mtk 已定义但执行时会提示未实现。"
                "保存时统一小写。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=560,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        frame.columnconfigure(1, weight=1)

        def capture() -> ConnectWifiSettings:
            return ConnectWifiSettings(
                enable=int(enable_var.get()),
                product_solution=(solution_var.get() or "openwrt").strip().lower(),
            )

        def load(new_wifi: ConnectWifiSettings) -> None:
            enable_var.set(int(new_wifi.enable))
            solution_var.set((new_wifi.product_solution or "openwrt").strip().lower())

        return {"capture": capture, "load": load}

    def _build_test_item_project_info_tab(
        self,
        notebook: ttk.Notebook,
        info: ProjectInfoSettings,
        mark_dirty,
    ) -> dict:
        """构建 [project_info] 段 Tab(Q1=A:仅做编辑器,不被主程序消费)。返回 ``{"capture": Callable, "load": Callable}``。"""
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
        notebook.add(frame, text="项目信息")

        project_name_var = StringVar(value=info.project_name or "")
        software_version_var = StringVar(value=info.software_version or "")
        internal_software_version_var = StringVar(value=info.internal_software_version or "")
        onu_compile_time_var = StringVar(value=info.onu_compile_time or "")

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

        Label(
            frame,
            text=(
                "本段仅做编辑器，不被主程序消费（Q1=A）。"
                "编译时间为自由文本，不强制 ISO 格式；"
                "操作员可在执行测试时肉眼对照样机输出的版本/编译时间。"
            ),
            foreground=COLOR_MUTED,
            background=COLOR_BG,
            wraplength=560,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

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

    def _serial_log_directory(self) -> Path:
        return DEFAULT_LOG_DIR

    def _open_serial_log_module(self, vlans: list[str] | None = None) -> None:
        targets = vlans or self._selected_upgrade_vlans()
        if not targets:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选至少一个通道。", parent=self)
            return
        self.serial_terminal.show(targets)

    def _open_pipeline_serial_logs(self, vlans: list[str] | None = None) -> None:
        """全流程专用：显示串口日志窗口，并打开窗口中的全部串口。"""
        targets = vlans or self._selected_upgrade_vlans()
        if not targets:
            raise RuntimeError("没有已勾选通道，无法打开串口日志")
        self.serial_terminal.show(targets)
        failed = self.serial_terminal.open_all()
        ports = ", ".join(
            f"{vlan.lower()}/{vlan_to_serial_port(vlan)}"
            for vlan in targets
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
        """打开 DUT 配置功能入口。

        当前只建立 UI 边界；后续再在 service / core 层接入 UBUS 配置逻辑。
        """
        if self.dut_config_window is not None and self.dut_config_window.winfo_exists():
            self.dut_config_window.deiconify()
            self.dut_config_window.lift()
            self.dut_config_window.focus_force()
            return

        dialog = Toplevel(self)
        self.dut_config_window = dialog
        dialog.title("DUT配置")
        dialog.geometry("620x300")
        dialog.minsize(620, 300)
        dialog.transient(self)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=24, pady=22, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        Label(
            content,
            text="DUT配置",
            font=(FONT_FAMILY, 18, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(anchor="w")
        Label(
            content,
            text="计划使用 UBUS 实现 DUT 配置，具体配置项和执行逻辑待后续完善。",
            background=COLOR_BG,
            foreground=COLOR_TEXT,
            anchor="w",
            justify="left",
        ).pack(fill="x", anchor="w", pady=(18, 8))
        Label(
            content,
            text="当前页面仅作为功能入口，不会连接 DUT，也不会下发任何 UBUS 命令。",
            background=COLOR_BG,
            foreground=COLOR_MUTED,
            anchor="w",
            justify="left",
        ).pack(fill="x", anchor="w")

        def close_dialog() -> None:
            dialog.destroy()
            if self.dut_config_window is dialog:
                self.dut_config_window = None

        ttk.Button(
            content,
            text="关闭",
            command=close_dialog,
            style="Secondary.TButton",
        ).pack(side="bottom", anchor="e")
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        self._log("[DUT配置] 已打开功能入口；UBUS 实现待完善，本次未下发任何设备命令。")

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
        headers = ["通道", "启用检查", "通道对应 VLAN"]
        for group in range(group_count):
            base_column = group * 4
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
        for index, channel in enumerate(selected_channels):
            group = index // rows_per_group
            row = index % rows_per_group + 1
            base_column = group * 4
            enabled_var = BooleanVar(value=channel.enabled)
            vlan_var = StringVar(value=channel.vlan_name or channel.adapter_alias)
            self.channel_row_vars[channel.section] = {
                "enabled": enabled_var,
                "vlan": vlan_var,
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
        self._capture_channel_row(channel)
        index = self.channels.index(channel)
        self._refresh_channel_list_item(index)
        self._select_channel_index(index)
        self._persist_config()

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

    def _vlan_adapter_options(self) -> list[str]:
        return vlan_options_for_power_serial_port(self.adapters, self._selected_power_serial_port())

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
        if not selected:
            self._log("未选择程控电源串口；通道对应 VLAN 下拉框展示所有识别网卡。请手动重启样机后，再进行后续步骤。")
        elif options:
            self._log(
                f"程控电源串口已切换为 {selected}；VLAN 下拉框仅展示 "
                f"{adapter_alias_from_display(options[0])} 到 {adapter_alias_from_display(options[-1])}。"
            )
        else:
            self._log(f"程控电源串口已切换为 {selected}；未找到该程控电源对应的 VLAN 网卡。")

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
        suffix = f"  {channel.vlan_name}" if channel.vlan_name else ""
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
        if selected:
            self.channel_list.selection_set(index)

    def _on_channel_list_click(self, event) -> None:
        index = self.channel_list.nearest(event.y)
        if index < 0 or index >= len(self.channels):
            return
        # The checkbox marker is at the beginning of each row.
        if event.x <= 28:
            self._toggle_channel_enabled(index)

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

        self.update_idletasks()
        x = self.winfo_x() + max((self.winfo_width() - 460) // 2, 0)
        y = self.winfo_y() + max((self.winfo_height() - 215) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
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
        # 旧逻辑保留作为兜底(直接跳弹窗失败时,仍可走 ping 检查)
        if self.running:
            return
        pipeline_window = self.pipeline_window
        if self.power_test_running:
            self._log("开关机测试：当前全流程仍在执行或停止中，请在主界面查看状态。")
            return
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
        if status not in labels:
            raise ValueError(f"未知开关机测试状态：{status}")
        self.power_test_running = status in {"running", "stopping"}
        self.power_test_status_var.set(labels[status])
        self.stop_power_test_button.configure(
            state="normal" if status == "running" else "disabled"
        )

    def _stop_power_test(self) -> None:
        """主界面停止入口；委派给当前全流程编排器的既有停止事件。"""
        pipeline_window = self.pipeline_window
        if pipeline_window is None or not pipeline_window.request_stop():
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
        if message.startswith("[通过]") or "成功" in message or "完成" in message:
            return "success"
        if message.startswith("[失败]") or "失败" in message or "异常" in message:
            return "error"
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

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = self._log_tag_for(message)
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

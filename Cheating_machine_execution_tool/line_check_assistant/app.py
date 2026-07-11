from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, Button, Checkbutton, DoubleVar, END, Frame, Label, Listbox, Tk, StringVar, Text, Toplevel, filedialog, messagebox, ttk

from .config_store import ChannelConfig, ChannelConfigStore, DEFAULT_POWER_SERIAL_PORT, DEFAULT_SUBNET_MASK
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
)
from .onu_registration_store import DEFAULT_OLT_IP, OnuRegistrationConfig, OnuRegistrationStore
from .page_upgrade import PageUpgradeRequest, run_page_upgrade_batch
from .paths import resolve_config_dir, resolve_tool_root
from .sample_upgrade_settings_store import DEFAULT_UPGRADE_MODE, DEFAULT_UPGRADE_TRANSFER, SampleUpgradeSettings, SampleUpgradeSettingsStore
from .serial_ports import list_prolific_ports, port_from_display
from src.core import SerialSessionManager
from src.config import DEFAULT_LOG_DIR
from src.models import FullPackageUpgradeRequest
from src.services import TRANSFER_TFTP_COMMAND, TRANSFER_TFTP_PUT, run_single_full_package_upgrade, turn_off_selected_channels, turn_on_selected_channels
from src.ui import SerialTerminalWindow


APP_DIR = resolve_tool_root()
CONFIG_DIR = resolve_config_dir(APP_DIR)
NETWORK_CONFIG_PATH = CONFIG_DIR / "network_card_ip.ini"
ONU_REGISTRATION_CONFIG_PATH = CONFIG_DIR / "onu_registration.ini"
SAMPLE_UPGRADE_SETTINGS_PATH = CONFIG_DIR / "sample_upgrade_settings.ini"
LOG_DIR = APP_DIR / "assistant_logs"
POWER_SUPPLY_COUNT = 6
TOTAL_CHANNEL_COUNT = 16
POWER_ON_WAIT_SECONDS = 0
POWER_ACTION_ON = "上电"
POWER_ACTION_OFF = "下电"
POWER_ACTION_OPTIONS = (POWER_ACTION_ON, POWER_ACTION_OFF)
CHANNEL_LIST_FONT = ("Microsoft YaHei UI", 11)
CHANNEL_FIELD_WIDTH = 42


def power_channel_from_section(section: str) -> int:
    try:
        return int(section.lower().replace("channel_", ""))
    except ValueError:
        return 0
CHANNEL_TABLE_COMBO_WIDTH = 32
CHANNEL_TABLE_GROUP_GAP = 24
CHANNEL_TABLE_ROWS_PER_GROUP = 4
UPGRADE_MODE_OPTIONS = ("页面升级", DEFAULT_UPGRADE_MODE)
TFTP_COMMAND_TRANSFER = TRANSFER_TFTP_COMMAND
TFTP_PUT_TRANSFER = TRANSFER_TFTP_PUT
LEGACY_TFTP_COPY_TRANSFER = "Tftp拷贝命令"
UPGRADE_TRANSFER_OPTIONS = (DEFAULT_UPGRADE_TRANSFER, TFTP_COMMAND_TRANSFER, "web打开网关")
SERIAL_FULL_PACKAGE_TRANSFERS = {TFTP_COMMAND_TRANSFER, TFTP_PUT_TRANSFER}
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
        self.running = False
        self.power_on_running = False
        self.upgrade_window = None
        self.serial_session_manager = SerialSessionManager()
        self.serial_terminal = SerialTerminalWindow(self, self.serial_session_manager, self._serial_log_directory())
        self.test_item_config_window = None
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
        self.sample_upgrade_save_after_id = None
        self.upgrade_mode_var = StringVar(value=upgrade_mode)
        self.upgrade_transfer_var = StringVar(value=transfer_method)
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
        self._bind_sample_upgrade_autosave()
        LOG_DIR.mkdir(exist_ok=True)
        self.log_path = LOG_DIR / f"line_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        self._build_ui()
        self._load_current_channel()
        self._show_startup_warnings()
        self.after_idle(self._maximize_window)
        self.after(200, self._drain_log_queue)
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

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill="x", pady=(0, 14))
        title_area = ttk.Frame(header, style="App.TFrame")
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, text="开关机测试环境搭建助手", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_area, text="配置测试通道、完成自动上/下电并检查全部线路", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        admin_ok = is_admin()
        admin_text = "管理员权限已就绪" if admin_ok else "缺少管理员权限，请右键以管理员身份运行"
        ttk.Label(header, text=admin_text, style="Success.TLabel" if admin_ok else "Danger.TLabel").pack(side="right", anchor="n", pady=3)

        toolbar = ttk.Frame(root, style="Surface.TFrame", padding=(12, 10))
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Label(toolbar, text="常用工具", style="CardTitle.TLabel").pack(side="left", padx=(2, 16))
        ttk.Button(toolbar, text="自动上/下电", command=self._launch_power_on, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text="样机升级", command=self._open_upgrade_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="写样机参数", command=self._open_sample_parameter_writer, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="ONU注册", command=self._open_onu_registration_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="串口日志", command=self._open_serial_log_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="刷新网卡", command=self._refresh_adapters, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(toolbar, text="刷新串口", command=self._refresh_power_serial_ports, style="Secondary.TButton").pack(side="right", padx=(0, 8))

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
        ttk.Button(
            config_header,
            text="测试项配置",
            command=self._open_test_item_config,
            style="Secondary.TButton",
        ).pack(side="right")
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
        ).pack(anchor="w", pady=(3, 8))
        self.progress = ttk.Progressbar(run_copy, mode="determinate")
        self.progress.pack(fill="x")
        ttk.Button(run_card, text="检查并执行测试", command=self._start_all_checks, style="Primary.TButton").pack(side="right", padx=(20, 0))

        log_card = ttk.Frame(right, style="Surface.TFrame", padding=14)
        log_card.pack(fill="both", expand=True)
        log_header = ttk.Frame(log_card, style="Surface.TFrame")
        log_header.pack(fill="x")
        ttk.Label(log_header, text="执行日志", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(log_header, text="清空日志", command=self._clear_log, style="Secondary.TButton").pack(side="right")
        ttk.Label(log_card, text="运行步骤、检查结果和异常信息", style="CardHint.TLabel").pack(anchor="w", pady=(3, 9))
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

    def _open_sample_parameter_writer(self) -> None:
        messagebox.showinfo("写样机参数", "写样机参数功能入口已预留，具体实现待完善。", parent=self)

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
            self.upgrade_restore_factory_var,
            self.upgrade_username_var,
            self.upgrade_password_var,
            self.upgrade_firmware_var,
        ):
            variable.trace_add("write", lambda *_args: self._schedule_sample_upgrade_save())

    @staticmethod
    def _normalize_upgrade_transfer_method(transfer_method: str) -> str:
        if transfer_method == LEGACY_TFTP_COPY_TRANSFER:
            return TFTP_COMMAND_TRANSFER
        return transfer_method

    def _current_sample_upgrade_settings(self) -> SampleUpgradeSettings:
        return SampleUpgradeSettings(
            upgrade_mode=self.upgrade_mode_var.get(),
            transfer_method=LineCheckAssistant._normalize_upgrade_transfer_method(self.upgrade_transfer_var.get()),
            restore_factory=bool(self.upgrade_restore_factory_var.get()),
            username=self.upgrade_username_var.get(),
            password=self.upgrade_password_var.get(),
            firmware_path=self.upgrade_firmware_var.get(),
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
        password_container.grid(row=2, column=3, sticky="ew", padx=(0, 12), pady=8)
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
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=8
        )
        Button(overview, text="选择固件...", command=self._select_upgrade_firmware).grid(
            row=3, column=3, sticky="e", padx=(0, 12), pady=8
        )

        Label(overview, text="目标样机", anchor="w").grid(row=4, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_targets_var,
            foreground=COLOR_TEXT,
            anchor="w",
            justify="left",
            wraplength=590,
        ).grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=8)

        Label(overview, text="执行状态", anchor="w").grid(row=5, column=0, sticky="nw", padx=(12, 8), pady=8)
        Label(
            overview,
            textvariable=self.upgrade_status_var,
            foreground=COLOR_TEXT,
            anchor="w",
        ).grid(row=5, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=8)
        self.upgrade_progress = ttk.Progressbar(
            overview,
            variable=self.upgrade_progress_var,
            maximum=100,
            mode="determinate",
        )
        self.upgrade_progress.grid(row=6, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=(0, 10))
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

    def _start_page_upgrade(self) -> None:
        channels = self._selected_page_upgrade_channels()
        if not channels:
            return
        firmware_path = Path(self.upgrade_firmware_var.get().strip())
        if not firmware_path.is_file():
            messagebox.showwarning("未选择升级固件", "请先选择需要升级的固件文件。", parent=self.upgrade_window)
            return

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
                    return
            if not device_ip:
                messagebox.showwarning("样机 IP 不完整", f"{channel.label} 未配置样机 IP。", parent=self.upgrade_window)
                return
            requests.append(
                PageUpgradeRequest(
                    vlan=vlan_name.lower() if vlan_name.lower().startswith("vlan") else vlan_name,
                    adapter_alias=channel.adapter_alias or vlan_name,
                    bind_ip=bind_ip,
                    device_ip=device_ip,
                    username=self.upgrade_username_var.get().strip(),
                    password=self.upgrade_password_var.get().strip(),
                    firmware_path=firmware_path,
                )
            )

        target_text = "、".join(request.vlan or request.device_ip for request in requests)
        if not messagebox.askyesno(
            "确认页面升级",
            f"将通过 UBUS 页面升级并行升级 {len(requests)} 台样机：{target_text}\n\n"
            "该操作会上传固件、触发升级并等待设备重启上线。是否继续？",
            parent=self.upgrade_window,
        ):
            return

        self._set_upgrade_status("", f"准备页面升级 {len(requests)} 台样机", 0)
        thread = threading.Thread(target=self._page_upgrade_worker, args=(requests,), daemon=True)
        thread.start()

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
            return
        failed_messages = [item.result.message for item in results if not item.result.ok]
        progress = (success_count / total) * 100 if total else 0
        self._set_upgrade_status("", f"页面升级完成：{success_count}/{total} 台成功", progress)
        messagebox.showerror("样机升级失败", "\n".join(failed_messages), parent=self.upgrade_window)

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

    def _start_serial_tftp_copy_upgrade(self) -> None:
        channels = self._selected_tftp_copy_upgrade_channels()
        if not channels:
            return
        firmware_path = Path(self.upgrade_firmware_var.get().strip())
        if not firmware_path.is_file():
            messagebox.showwarning("未选择升级固件", "请先选择需要升级的固件文件。", parent=self.upgrade_window)
            return

        upgrade_items: list[tuple[ChannelConfig, FullPackageUpgradeRequest]] = []
        power_serial_port = self._selected_power_serial_port()
        transfer_method = LineCheckAssistant._selected_upgrade_transfer_method(self)
        for channel in channels:
            try:
                tftp_server_ip = self._tftp_server_ip_for_channel(channel)
            except ValueError as exc:
                messagebox.showwarning("VLAN IP 不正确", str(exc), parent=self.upgrade_window)
                return

            vlan_name = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            power_channel = power_channel_from_section(channel.section)
            if not 1 <= power_channel <= TOTAL_CHANNEL_COUNT:
                messagebox.showwarning("程控电源通道不正确", f"无法从 {channel.section} 确定程控电源通道。", parent=self.upgrade_window)
                return
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
        restore_factory_text = "开启，会在最终系统登录后执行恢复出厂" if bool(self.upgrade_restore_factory_var.get()) else "关闭，不会执行恢复出厂"
        if not messagebox.askyesno(
            "确认串行升级",
            f"将按主界面通道顺序升级 {len(upgrade_items)} 台样机：{target_text}\n\n升级过程会自动改写 network_card_ip.ini，仅保留当前上电通道，然后自动上电、进入 boot、{transfer_action}并复位/重新上电。\n恢复出厂：{restore_factory_text}\n\n是否继续？",
            parent=self.upgrade_window,
        ):
            return

        self._set_upgrade_status("", f"准备串行升级 {len(upgrade_items)} 台样机", 0)
        thread = threading.Thread(target=self._serial_tftp_copy_upgrade_worker, args=(upgrade_items,), daemon=True)
        thread.start()

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
        restore_result = None
        selected_channels = [channel for channel, _request in upgrade_items]
        power_serial_port = upgrade_items[0][1].power_serial_port if upgrade_items else self._selected_power_serial_port()
        try:
            for index, (channel, request) in enumerate(upgrade_items, start=1):
                start_progress = ((index - 1) / total) * 100 if total else 0
                self.after(
                    0,
                    lambda request=request, index=index, total=total, progress=start_progress: self._set_upgrade_status(
                        request.vlan,
                        f"串行升级 {index}/{total}，更新通道配置并准备上电",
                        progress,
                    ),
                )
                self.log_queue.put(f"开始串行升级 {index}/{total}：{request.vlan}")
                try:
                    self.store.save([channel], request.power_serial_port)
                    self.log_queue.put(f"已更新 network_card_ip.ini，仅保留当前升级通道：{channel.section} / {request.vlan}")
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
        finally:
            if selected_channels:
                try:
                    self.store.save(selected_channels, power_serial_port)
                    self.log_queue.put("已恢复 network_card_ip.ini 中用户选择的完整通道配置。")
                except Exception as exc:
                    restore_result = CommandResult(False, f"恢复 network_card_ip.ini 完整通道配置失败：{exc}")
                    self.log_queue.put(restore_result.message)
        if failed_result is None and restore_result is not None:
            failed_result = restore_result
        self.after(0, lambda: self._complete_serial_tftp_copy_upgrade(total, completed, failed_request, failed_result))

    def _complete_serial_tftp_copy_upgrade(self, total: int, completed: int, failed_request, failed_result) -> None:
        if failed_result is None:
            self._set_upgrade_status("", f"串行升级完成：{completed}/{total} 台", 100)
            messagebox.showinfo("样机升级完成", f"串行升级完成：{completed}/{total} 台样机已升级。", parent=self.upgrade_window)
            return
        progress = (completed / total) * 100 if total else 0
        vlan = failed_request.vlan if failed_request is not None else ""
        self._set_upgrade_status(vlan, f"升级失败，已停止后续样机（已完成 {completed}/{total} 台）", progress)
        self._log(failed_result.message)
        messagebox.showerror("样机升级失败", failed_result.message, parent=self.upgrade_window)

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
        if self.test_item_config_window is not None and self.test_item_config_window.winfo_exists():
            self.test_item_config_window.deiconify()
            self.test_item_config_window.lift()
            self.test_item_config_window.focus_force()
            return

        dialog = Toplevel(self)
        self.test_item_config_window = dialog
        dialog.title("测试项配置")
        dialog.geometry("820x580")
        dialog.minsize(760, 530)
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
            text="查看线路检查当前执行的测试项目。",
            foreground=COLOR_MUTED,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(6, 16))

        overview = ttk.LabelFrame(content, text="当前测试项")
        overview.pack(fill="x")
        rows = [
            ("01", "启用 VLAN 网卡", "固定启用"),
            ("02", "配置 PC 静态 IP", "固定启用"),
            ("03", "Ping 样机管理 IP", "固定启用"),
        ]
        for row, (number, item, status) in enumerate(rows):
            Label(overview, text=number, width=6, anchor="w").grid(row=row, column=0, sticky="w", padx=(12, 0), pady=10)
            Label(overview, text=item, width=28, anchor="w").grid(row=row, column=1, sticky="w", padx=12, pady=10)
            Label(overview, text=status, foreground=COLOR_SUCCESS, anchor="w").grid(row=row, column=2, sticky="w", padx=12, pady=10)
        overview.columnconfigure(1, weight=1)

        Label(
            content,
            text="当前版本仅提供测试项入口与状态说明，不会改变既有线路检查流程。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(16, 0))

        def close_dialog() -> None:
            dialog.destroy()
            self.test_item_config_window = None

        ttk.Button(content, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(
            side="bottom", anchor="e", pady=(18, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def _serial_log_directory(self) -> Path:
        return DEFAULT_LOG_DIR

    def _open_serial_log_module(self, vlans: list[str] | None = None) -> None:
        targets = vlans or self._selected_upgrade_vlans()
        if not targets:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选至少一个通道。", parent=self)
            return
        self.serial_terminal.show(targets)

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
        return [f"COM{101 + index}" for index in range(POWER_SUPPLY_COUNT)]

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
        options = [
            adapter
            for adapter in self.adapters
            if adapter_alias_from_display(adapter).lower().startswith("vlan")
        ]
        return sorted(self._unique_options(options), key=self._vlan_sort_key)

    def _vlan_sort_key(self, value: str) -> tuple[int, str]:
        alias = adapter_alias_from_display(value).lower()
        digits = "".join(char for char in alias if char.isdigit())
        return (int(digits) if digits else 999999, alias)

    def _on_power_serial_changed(self, _event=None) -> None:
        selected = self._selected_power_serial_port()
        if selected:
            self.power_serial_var.set(selected)
            self._persist_config()

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
        if not selected_com:
            return
        if power_action not in POWER_ACTION_OPTIONS:
            messagebox.showwarning("操作类型不正确", "程控电源操作只能选择上电或下电。", parent=self)
            return
        power_channels = [power_channel_from_section(channel.section) for channel in enabled_channels]
        if any(not 1 <= channel <= TOTAL_CHANNEL_COUNT for channel in power_channels):
            messagebox.showwarning("程控电源通道不正确", "存在无法识别的 channel 编号，已取消自动上/下电。", parent=self)
            return
        channel_text = "、".join(str(channel) for channel in power_channels)
        action_description = (
            "确认后会按勾选顺序开启全部通道，相邻开启指令间隔 1 秒；执行前不会关闭任何程控电源通道。"
            if power_action == POWER_ACTION_ON
            else "确认后会按勾选顺序关闭全部勾选通道，相邻关闭指令间隔 1 秒；只关闭勾选通道，不会执行全部断电。"
        )
        if not messagebox.askyesno(
            f"确认自动{power_action}",
            f"将直接通过程控电源串口 {selected_com} 操作通道 {channel_text}。\n\n"
            f"{action_description}\n\n"
            "不会启动旧的 Auto_Power_On_Off_Tool。\n\n"
            "是否继续？",
            parent=self,
        ):
            return
        self.power_serial_var.set(selected_com)
        self.power_on_running = True
        thread = threading.Thread(target=self._power_on_worker, args=(selected_com, power_channels, power_action, wait_seconds), daemon=True)
        thread.start()

    def _select_power_com_port(self) -> tuple[str, str]:
        dialog = Toplevel(self)
        dialog.title("选择自动上/下电操作")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        options = self._build_power_serial_options()
        current = self._selected_power_serial_port()
        selected = StringVar(value=current if current in options else DEFAULT_POWER_SERIAL_PORT)
        action = StringVar(value=POWER_ACTION_ON)
        result = {"port": "", "action": POWER_ACTION_ON}

        Frame(dialog, padx=16, pady=12).pack(fill="both", expand=True)
        container = dialog.winfo_children()[0]
        prompt = "请选择程控电源 COM 口："
        Label(container, text=prompt).pack(anchor="w", pady=(0, 8))
        combo = ttk.Combobox(container, textvariable=selected, values=options, width=58, state="readonly")
        combo.pack(fill="x", pady=(0, 12))

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
                self._log(f"已选择程控电源串口：{selected_port}，操作：{selected_action}")
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
        if self.running:
            return
        self._capture_current_channel()
        enabled_channels = self._selected_channels()
        if not enabled_channels:
            messagebox.showwarning("没有启用通道", "请至少启用一个通道。")
            return
        self._persist_config()
        self._run_checks(enabled_channels)

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
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__DONE__":
                self.running = False
            elif item == "__POWER_DONE__":
                self.power_on_running = False
            elif item.startswith("__PROGRESS__:"):
                self.progress.configure(value=int(item.split(":", 1)[1]))
            else:
                self._log(item)
        self.after(200, self._drain_log_queue)

    def _configure_log_tags(self) -> None:
        self.log_text.tag_configure("time", foreground=COLOR_MUTED)
        self.log_text.tag_configure("section", foreground=COLOR_TEXT, font=("Consolas", 10, "bold"))
        self.log_text.tag_configure("success", foreground=COLOR_SUCCESS)
        self.log_text.tag_configure("error", foreground=COLOR_DANGER)
        self.log_text.tag_configure("warning", foreground=COLOR_WARNING)
        self.log_text.tag_configure("muted", foreground=COLOR_MUTED)
        self.log_text.configure(state="disabled")

    def _log_tag_for(self, message: str) -> str:
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

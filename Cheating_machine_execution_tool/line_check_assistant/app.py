from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, Button, Checkbutton, DoubleVar, END, Frame, Label, Listbox, Tk, StringVar, Text, Toplevel, filedialog, messagebox, ttk

from .config_store import ChannelConfig, ChannelConfigStore, DEFAULT_POWER_SERIAL_PORT, DEFAULT_SUBNET_MASK
from .network_ops import CommandResult, adapter_alias_from_display, is_admin, list_adapter_display_names, run_line_check, static_ip_for_vlan
from .old_tool_automation import automate_power_on
from .old_tool_config import prepare_power_on_default
from .paths import OLD_TOOL_NAME, resolve_tool_root
from .sample_upgrade import SingleTftpCopyUpgradeRequest, run_single_tftp_copy_upgrade
from .securecrt_automation import SecureCRTLaunchResult, launch_securecrt_serial_logs
from .serial_ports import list_prolific_ports, port_from_display


APP_DIR = resolve_tool_root()
CONFIG_DIR = APP_DIR / "config"
NETWORK_CONFIG_PATH = CONFIG_DIR / "network_card_ip.ini"
OLD_TOOL_PATH = APP_DIR / OLD_TOOL_NAME
LOG_DIR = APP_DIR / "assistant_logs"
POWER_SUPPLY_COUNT = 6
TOTAL_CHANNEL_COUNT = 16
POWER_ON_WAIT_SECONDS_PER_CHANNEL = 5
CHANNEL_LIST_FONT = ("Microsoft YaHei UI", 11)
CHANNEL_FIELD_WIDTH = 42
CHANNEL_TABLE_COMBO_WIDTH = 32
CHANNEL_TABLE_GROUP_GAP = 24
CHANNEL_TABLE_ROWS_PER_GROUP = 4
UPGRADE_MODE_OPTIONS = ("页面升级", "全包升级")
UPGRADE_TRANSFER_OPTIONS = ("Tftp Put", "Tftp拷贝命令", "web打开网关")
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
        self.serial_log_window = None
        self.test_item_config_window = None
        self.upgrade_mode_var = StringVar(value="全包升级")
        self.upgrade_transfer_var = StringVar(value=UPGRADE_TRANSFER_OPTIONS[0])
        self.upgrade_restore_factory_var = BooleanVar(value=False)
        self.upgrade_restore_factory_text_var = StringVar(value="☐ 恢复出厂")
        self.upgrade_username_var = StringVar()
        self.upgrade_password_var = StringVar()
        self.upgrade_password_visible = False
        self.upgrade_firmware_var = StringVar()
        self.upgrade_targets_var = StringVar(value="未勾选目标样机")
        self.upgrade_status_var = StringVar(value="尚未开始升级")
        self.upgrade_progress_var = DoubleVar(value=0)
        LOG_DIR.mkdir(exist_ok=True)
        self.log_path = LOG_DIR / f"line_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        self._build_ui()
        self._load_current_channel()
        self._show_startup_warnings()
        self.after_idle(self._maximize_window)
        self.after(200, self._drain_log_queue)

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except Exception:
            return

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
        ttk.Label(title_area, text="配置测试通道、完成自动上电并检查全部线路", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        admin_ok = is_admin()
        admin_text = "管理员权限已就绪" if admin_ok else "缺少管理员权限，请右键以管理员身份运行"
        ttk.Label(header, text=admin_text, style="Success.TLabel" if admin_ok else "Danger.TLabel").pack(side="right", anchor="n", pady=3)

        toolbar = ttk.Frame(root, style="Surface.TFrame", padding=(12, 10))
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Label(toolbar, text="常用工具", style="CardTitle.TLabel").pack(side="left", padx=(2, 16))
        ttk.Button(toolbar, text="自动上电", command=self._launch_old_tool, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text="样机升级", command=self._open_upgrade_module, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="写样机参数", command=self._open_sample_parameter_writer, style="Tool.TButton").pack(side="left", padx=(8, 0))
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
        self._log("3. 点击“自动启动旧软件上电”")
        self._log("4. 等待旧软件自动选择 Fully_powered_on、点击 Start ALL、上电并关闭")
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
            text="选择升级方式、升级固件和目标样机。具体升级命令与校验规则将在后续完善。",
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
            text="当前版本仅保存本次窗口中的配置，不会下发升级命令或修改设备。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(16, 0))

        def close_dialog() -> None:
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
        marker = "☑" if self.upgrade_restore_factory_var.get() else "☐"
        self.upgrade_restore_factory_text_var.set(f"{marker} 恢复出厂")

    def _refresh_upgrade_transfer_visibility(self) -> None:
        if not hasattr(self, "upgrade_transfer_label") or not hasattr(self, "upgrade_transfer_combo"):
            return
        if self.upgrade_transfer_var.get() not in UPGRADE_TRANSFER_OPTIONS:
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
        if self.upgrade_mode_var.get() == "全包升级" and self.upgrade_transfer_var.get() == "Tftp拷贝命令":
            self._start_single_tftp_copy_upgrade()
            return

        vlans = self._selected_upgrade_vlans()
        if not vlans:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选通道并配置对应 VLAN。", parent=self.upgrade_window)
            return
        self._set_upgrade_status("", "正在启动 SecureCRT 并建立串口连接...", 0)
        thread = threading.Thread(target=self._securecrt_launch_worker, args=(vlans,), daemon=True)
        thread.start()

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

    def _start_single_tftp_copy_upgrade(self) -> None:
        channel = self._selected_single_upgrade_channel()
        if channel is None:
            return
        firmware_path = Path(self.upgrade_firmware_var.get().strip())
        if not firmware_path.is_file():
            messagebox.showwarning("未选择升级固件", "请先选择需要升级的固件文件。", parent=self.upgrade_window)
            return
        try:
            tftp_server_ip = self._tftp_server_ip_for_channel(channel)
        except ValueError as exc:
            messagebox.showwarning("VLAN IP 不正确", str(exc), parent=self.upgrade_window)
            return

        vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip().lower()
        server_interface = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
        request = SingleTftpCopyUpgradeRequest(
            vlan=vlan,
            server_interface=server_interface,
            tftp_server_ip=tftp_server_ip,
            firmware_path=firmware_path,
            power_serial_port=self._selected_power_serial_port(),
            restore_factory=bool(self.upgrade_restore_factory_var.get()),
        )
        self._set_upgrade_status(vlan, "启动 SecureCRT、准备串口日志", 0)
        thread = threading.Thread(target=self._single_tftp_copy_upgrade_worker, args=(request,), daemon=True)
        thread.start()

    def _selected_single_upgrade_channel(self):
        channels = []
        for channel in self.channels:
            if not channel.enabled:
                continue
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
            if vlan:
                channels.append(channel)
        if not channels:
            messagebox.showwarning("没有目标样机", "请先在主界面勾选 1 个通道并配置对应 VLAN。", parent=self.upgrade_window)
            return None
        if len(channels) > 1:
            messagebox.showwarning("暂只支持单台升级", "当前先实现 1 台样机升级，请只勾选 1 个目标通道。", parent=self.upgrade_window)
            return None
        return channels[0]

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

    def _single_tftp_copy_upgrade_worker(self, request: SingleTftpCopyUpgradeRequest) -> None:
        try:
            result = run_single_tftp_copy_upgrade(
                APP_DIR,
                OLD_TOOL_PATH,
                request,
                on_output=lambda line: self.log_queue.put(line),
            )
        except Exception as exc:
            result = CommandResult(False, f"单台升级流程异常：{exc}")
        self.after(0, lambda: self._complete_single_tftp_copy_upgrade(request, result))

    def _complete_single_tftp_copy_upgrade(self, request: SingleTftpCopyUpgradeRequest, result) -> None:
        if result.ok:
            self._set_upgrade_status(request.vlan, "升级完成", 100)
            self._log(result.message)
            messagebox.showinfo("样机升级完成", result.message, parent=self.upgrade_window)
            return
        self._set_upgrade_status(request.vlan, "升级失败", 0)
        self._log(result.message)
        messagebox.showerror("样机升级失败", result.message, parent=self.upgrade_window)

    def _securecrt_launch_worker(self, vlans: list[str]) -> None:
        try:
            result = launch_securecrt_serial_logs(APP_DIR, vlans)
        except Exception as exc:
            result = SecureCRTLaunchResult(False, f"启动 SecureCRT 异常：{exc}")
        self.after(0, lambda: self._complete_securecrt_launch(result))

    def _complete_securecrt_launch(self, result: SecureCRTLaunchResult) -> None:
        if not result.success:
            messagebox.showerror("启动 SecureCRT 失败", result.message, parent=self.upgrade_window)
            self._set_upgrade_status("", "SecureCRT 启动失败", 0)
            return

        self._set_upgrade_status("", f"SecureCRT 已打开 {len(result.targets)} 个目标串口，日志记录中", 0)
        self._log(result.message)
        messagebox.showinfo(
            "串口日志已启动",
            f"已检测到 SecureCRT 可见窗口，并按目标 VLAN 启动 {len(result.targets)} 个串口连接。\n"
            f"日志目录：{result.log_directory}\n\n"
            "具体升级命令将在后续实现。",
            parent=self.upgrade_window,
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

    def _open_serial_log_module(self) -> None:
        if self.serial_log_window is not None and self.serial_log_window.winfo_exists():
            self.serial_log_window.deiconify()
            self.serial_log_window.lift()
            self.serial_log_window.focus_force()
            return

        dialog = Toplevel(self)
        self.serial_log_window = dialog
        dialog.title("串口日志记录")
        dialog.geometry("820x580")
        dialog.minsize(760, 530)
        dialog.transient(self)
        dialog.configure(background=COLOR_BG)

        content = Frame(dialog, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)
        Label(content, text="串口日志记录", font=(FONT_FAMILY, 18, "bold"), background=COLOR_BG, foreground=COLOR_TEXT).pack(anchor="w")
        Label(
            content,
            text="功能配置入口已建立。串口采集、文件轮转和通道关联规则将在后续逐步完善。",
            foreground=COLOR_MUTED,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(6, 16))

        overview = ttk.LabelFrame(content, text="日志记录配置")
        overview.pack(fill="x")
        rows = [
            ("日志串口", "待选择"),
            ("波特率", "待配置"),
            ("串口参数", "数据位 / 校验位 / 停止位待配置"),
            ("关联通道", "待配置"),
            ("日志目录", "待选择"),
            ("记录状态", "串口日志记录尚未启用"),
        ]
        for row, (label, value) in enumerate(rows):
            Label(overview, text=label, width=16, anchor="w").grid(row=row, column=0, sticky="w", padx=12, pady=7)
            Label(overview, text=value, foreground=COLOR_TEXT, anchor="w").grid(row=row, column=1, sticky="w", padx=12, pady=7)
        overview.columnconfigure(1, weight=1)

        Label(
            content,
            text="当前窗口仅作为配置入口，不会占用串口或生成日志文件。",
            foreground=COLOR_WARNING,
            background=COLOR_BG,
        ).pack(anchor="w", pady=(16, 0))

        def close_dialog() -> None:
            dialog.destroy()
            self.serial_log_window = None

        ttk.Button(content, text="关闭", width=12, command=close_dialog, style="Secondary.TButton").pack(side="bottom", anchor="e", pady=(18, 0))

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

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

    def _launch_old_tool(self) -> None:
        if self.power_on_running:
            return
        self._capture_current_channel()
        enabled_channels = self._selected_channels()
        if not enabled_channels:
            messagebox.showwarning("没有启用通道", "请至少启用一个通道后再自动上电。", parent=self)
            return
        wait_seconds = self._power_on_wait_seconds(enabled_channels)
        selected_com = self._select_power_com_port()
        if not selected_com:
            return
        self.power_serial_var.set(selected_com)
        self.power_on_running = True
        thread = threading.Thread(target=self._power_on_worker, args=(selected_com, wait_seconds), daemon=True)
        thread.start()

    def _select_power_com_port(self) -> str:
        dialog = Toplevel(self)
        dialog.title("选择程控电源 COM 口")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        options = self._build_power_serial_options()
        current = self._selected_power_serial_port()
        selected = StringVar(value=current if current in options else DEFAULT_POWER_SERIAL_PORT)
        result = {"port": ""}

        Frame(dialog, padx=16, pady=12).pack(fill="both", expand=True)
        container = dialog.winfo_children()[0]
        prompt = "请选择需要启动的程控电源 COM 口："
        Label(container, text=prompt).pack(anchor="w", pady=(0, 8))
        combo = ttk.Combobox(container, textvariable=selected, values=options, width=58, state="readonly")
        combo.pack(fill="x", pady=(0, 12))

        buttons = Frame(container)
        buttons.pack(fill="x")

        def confirm() -> None:
            try:
                value = selected.get().strip()
                selected_port = port_from_display(value) or value.upper()
                if selected_port not in options:
                    messagebox.showwarning("COM 口不正确", "程控电源串口只能选择 COM101 到 COM106。", parent=dialog)
                    return
                result["port"] = selected_port
                self._log(f"已选择程控电源串口：{selected_port}")
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
        y = self.winfo_y() + max((self.winfo_height() - 160) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
        combo.focus_set()
        self.wait_window(dialog)
        return result["port"]

    def _power_on_wait_seconds(self, channels) -> int:
        return len(channels) * POWER_ON_WAIT_SECONDS_PER_CHANNEL

    def _power_on_worker(self, selected_com: str, wait_seconds: int) -> None:
        try:
            try:
                message = prepare_power_on_default(CONFIG_DIR)
                self.log_queue.put(message)
            except OSError as exc:
                self.log_queue.put(f"准备 Fully_powered_on 默认配置失败：{exc}")
                return
            self.log_queue.put(
                f"开始自动打开旧软件、选择程控电源串口 {selected_com}、选择 Fully_powered_on、点击 Start ALL，"
                f"按启用通道数等待 {wait_seconds} 秒。"
            )
            result = automate_power_on(
                OLD_TOOL_PATH,
                serial_port=selected_com,
                wait_seconds=wait_seconds,
                on_output=lambda line: self.log_queue.put(line),
            )
            self.log_queue.put(result.message)
        except Exception as exc:
            self.log_queue.put(f"自动上电后台流程异常：{exc}")
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

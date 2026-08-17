import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .commands import (
    build_discovery_command,
    build_precheck_command,
    build_provision_commands,
    build_verify_commands,
    format_preview,
)
from .models import OltConnection, OnuProvisionConfig
from .parser import (
    parse_registered_onus,
    parse_service_mappings,
    parse_unconfigured_onus,
    speed_mode_to_cli,
)
from .telnet_client import OperationCancelled, TitanTelnetSession


DEFAULT_SERVICES = """1,170
2,171
3,172
4,173
5,335
6,600
7,50
8,151
9,150"""


class TitanProvisionerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("中兴 TITAN ONU 自动注册与业务配置")
        self.root.geometry("1180x780")
        self.root.minsize(980, 680)
        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self._build_style()
        self._build_variables()
        self._build_ui()
        self._set_busy(False)

    def _build_style(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Danger.TCheckbutton", foreground="#a32727")

    def _build_variables(self):
        self.host_var = tk.StringVar(value="172.18.18.152")
        self.port_var = tk.StringVar(value="23")
        self.source_ip_var = tk.StringVar(value="172.33.5.35")
        self.username_var = tk.StringVar(value="zte")
        self.password_var = tk.StringVar()
        self.timeout_var = tk.StringVar(value="10")

        self.shelf_var = tk.StringVar(value="1")
        self.slot_var = tk.StringVar(value="1")
        self.pon_var = tk.StringVar(value="5")
        self.onu_id_var = tk.StringVar(value="1")
        self.onu_type_var = tk.StringVar(value="CXP-55")
        self.sn_var = tk.StringVar()
        self.real_speed_var = tk.StringVar(value="xgspon")
        self.tcont_id_var = tk.StringVar(value="1")
        self.tcont_profile_var = tk.StringVar(value="CXP-55")
        self.gemport_id_var = tk.StringVar(value="1")
        self.vport_id_var = tk.StringVar(value="1")
        self.sn_bind_var = tk.BooleanVar(value=True)
        self.enable_apply_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪：默认仅生成预览，不执行 write 保存")

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="中兴 TITAN ONU 自动注册与业务配置", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            outer,
            text="适配本机验证过的 gpon_olt-/gpon_onu-/vport- 语法；密码不落盘，工具不执行 write。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.config_tab = ttk.Frame(self.notebook, padding=10)
        self.preview_tab = ttk.Frame(self.notebook, padding=10)
        self.log_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.config_tab, text="参数与发现")
        self.notebook.add(self.preview_tab, text="命令预览")
        self.notebook.add(self.log_tab, text="执行日志")

        self._build_config_tab()
        self._build_preview_tab()
        self._build_log_tab()

        action = ttk.Frame(outer)
        action.pack(fill="x", pady=(10, 0))
        ttk.Label(action, textvariable=self.status_var).pack(side="left")
        self.cancel_button = ttk.Button(action, text="停止", command=self._cancel)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(
            action, text="执行注册与配置", command=self._apply_clicked
        )
        self.apply_button.pack(side="right", padx=(0, 8))
        self.preview_button = ttk.Button(
            action, text="生成命令预览", command=self._preview_clicked
        )
        self.preview_button.pack(side="right", padx=(0, 8))

    def _entry_row(self, parent, row, label, variable, width=18, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=(0, 6), pady=3)
        entry = ttk.Entry(parent, textvariable=variable, width=width, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        return entry

    def _build_config_tab(self):
        top = ttk.Frame(self.config_tab)
        top.pack(fill="x")

        connection = ttk.LabelFrame(top, text="OLT 连接", padding=10)
        connection.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._entry_row(connection, 0, "OLT 地址", self.host_var)
        self._entry_row(connection, 1, "Telnet 端口", self.port_var)
        self._entry_row(connection, 2, "源 IP（可空）", self.source_ip_var)
        self._entry_row(connection, 3, "用户名", self.username_var)
        self._entry_row(connection, 4, "密码", self.password_var, show="●")
        self._entry_row(connection, 5, "超时（秒）", self.timeout_var)
        connection.columnconfigure(1, weight=1)

        onu = ttk.LabelFrame(top, text="ONU 与带宽参数", padding=10)
        onu.pack(side="left", fill="both", expand=True, padx=6)
        location = ttk.Frame(onu)
        location.grid(row=0, column=0, columnspan=2, sticky="ew", pady=3)
        for index, (label, variable) in enumerate(
            (("机框", self.shelf_var), ("槽位", self.slot_var), ("PON", self.pon_var), ("ONU ID", self.onu_id_var))
        ):
            ttk.Label(location, text=label).grid(row=0, column=index * 2, padx=(0, 3))
            ttk.Entry(location, textvariable=variable, width=5).grid(
                row=0, column=index * 2 + 1, padx=(0, 9)
            )
        self._entry_row(onu, 1, "ONU 型号", self.onu_type_var)
        self._entry_row(onu, 2, "SN", self.sn_var)
        ttk.Label(onu, text="实际速率").grid(row=3, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Combobox(
            onu,
            textvariable=self.real_speed_var,
            values=("xgspon", "xgpon", "gpon", "auto"),
            state="readonly",
            width=16,
        ).grid(row=3, column=1, sticky="ew", pady=3)
        self._entry_row(onu, 4, "T-CONT ID", self.tcont_id_var)
        self._entry_row(onu, 5, "T-CONT 模板", self.tcont_profile_var)
        self._entry_row(onu, 6, "GEM Port ID", self.gemport_id_var)
        self._entry_row(onu, 7, "VPort ID", self.vport_id_var)
        ttk.Checkbutton(onu, text="启用 SN 双重绑定", variable=self.sn_bind_var).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        onu.columnconfigure(1, weight=1)

        services = ttk.LabelFrame(top, text="业务映射（ServiceID,VLAN）", padding=10)
        services.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.services_text = tk.Text(services, width=24, height=14, font=("Consolas", 10))
        self.services_text.insert("1.0", DEFAULT_SERVICES)
        self.services_text.pack(fill="both", expand=True)
        ttk.Label(
            services,
            text="每行一条，例如 1,170。ONU service 与 vport service-port 同时生成。",
            style="Hint.TLabel",
            wraplength=260,
        ).pack(anchor="w", pady=(6, 0))

        discovery = ttk.LabelFrame(self.config_tab, text="未注册 ONU", padding=8)
        discovery.pack(fill="both", expand=True, pady=(10, 0))
        toolbar = ttk.Frame(discovery)
        toolbar.pack(fill="x", pady=(0, 6))
        self.discover_button = ttk.Button(
            toolbar, text="查询当前 PON 口", command=self._discover_clicked
        )
        self.discover_button.pack(side="left")
        ttk.Button(toolbar, text="填入选中 ONU", command=self._fill_selected_onu).pack(
            side="left", padx=6
        )
        ttk.Label(
            toolbar,
            text="查询命令：show pon onu uncfg gpon_olt-... sn model speed-mode",
            style="Hint.TLabel",
        ).pack(side="left", padx=8)

        columns = ("interface", "model", "sn", "speed")
        self.discovery_tree = ttk.Treeview(
            discovery, columns=columns, show="headings", height=8, selectmode="browse"
        )
        headings = {"interface": "PON 接口", "model": "型号", "sn": "SN", "speed": "速率"}
        widths = {"interface": 200, "model": 180, "sn": 200, "speed": 130}
        for column in columns:
            self.discovery_tree.heading(column, text=headings[column])
            self.discovery_tree.column(column, width=widths[column], anchor="w")
        self.discovery_tree.pack(fill="both", expand=True)
        self.discovery_tree.bind("<Double-1>", lambda _event: self._fill_selected_onu())

        confirm = ttk.Frame(self.config_tab)
        confirm.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            confirm,
            text="我已核对 PON、ONU ID、型号、SN、带宽模板和 VLAN，允许实际下发",
            variable=self.enable_apply_var,
            style="Danger.TCheckbutton",
        ).pack(anchor="w")

    def _build_preview_tab(self):
        ttk.Label(
            self.preview_tab,
            text="以下命令不会自动包含 write；实际执行前还会查询 PON 口并检查 ONU ID/SN 冲突。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        self.preview_text = tk.Text(
            self.preview_tab, wrap="none", font=("Consolas", 10), undo=False
        )
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.configure(state="disabled")

    def _build_log_tab(self):
        self.log_text = tk.Text(
            self.log_tab, wrap="word", font=("Consolas", 9), state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)

    def _connection(self) -> OltConnection:
        try:
            return OltConnection(
                host=self.host_var.get().strip(),
                port=int(self.port_var.get()),
                source_ip=self.source_ip_var.get().strip(),
                username=self.username_var.get().strip(),
                password=self.password_var.get(),
                timeout=float(self.timeout_var.get()),
            )
        except ValueError as exc:
            raise ValueError("端口和超时必须填写数字") from exc

    def _config(self) -> OnuProvisionConfig:
        try:
            return OnuProvisionConfig(
                shelf=int(self.shelf_var.get()),
                slot=int(self.slot_var.get()),
                pon=int(self.pon_var.get()),
                onu_id=int(self.onu_id_var.get()),
                onu_type=self.onu_type_var.get().strip(),
                serial_number=self.sn_var.get().strip().upper(),
                real_speed=self.real_speed_var.get(),
                tcont_id=int(self.tcont_id_var.get()),
                tcont_profile=self.tcont_profile_var.get().strip(),
                gemport_id=int(self.gemport_id_var.get()),
                vport_id=int(self.vport_id_var.get()),
                sn_bind_both=self.sn_bind_var.get(),
                services=parse_service_mappings(self.services_text.get("1.0", "end")),
            )
        except ValueError as exc:
            if "业务映射" in str(exc):
                raise
            raise ValueError(f"ONU 数字参数格式错误：{exc}") from exc

    def _validate(self, require_password=True):
        connection = self._connection()
        config = self._config()
        errors = connection.validate() + config.validate()
        if not require_password:
            errors = [error for error in errors if error != "密码不能为空"]
        if errors:
            raise ValueError("\n".join(f"• {error}" for error in errors))
        return connection, config

    def _show_error(self, title: str, exc: Exception):
        messagebox.showerror(title, str(exc), parent=self.root)

    def _preview_clicked(self):
        try:
            _connection, config = self._validate(require_password=False)
            commands = build_provision_commands(config)
        except Exception as exc:
            self._show_error("参数错误", exc)
            return
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", format_preview(commands))
        self.preview_text.configure(state="disabled")
        self.notebook.select(self.preview_tab)
        self.status_var.set(f"已生成 {len(commands)} 条配置命令；尚未连接 OLT")

    def _discover_clicked(self):
        try:
            connection = self._connection()
            errors = connection.validate()
            if errors:
                raise ValueError("\n".join(f"• {error}" for error in errors))
            shelf, slot, pon = (
                int(self.shelf_var.get()),
                int(self.slot_var.get()),
                int(self.pon_var.get()),
            )
        except Exception as exc:
            self._show_error("参数错误", exc)
            return

        def work():
            with TitanTelnetSession(
                connection, logger=self._append_log, cancel_event=self.cancel_event
            ) as session:
                output = session.execute(build_discovery_command(shelf, slot, pon))
            onus = parse_unconfigured_onus(output)
            self.root.after(0, lambda: self._show_discovery(onus))

        self._start_worker("查询未注册 ONU", work)

    def _show_discovery(self, onus):
        for item in self.discovery_tree.get_children():
            self.discovery_tree.delete(item)
        for onu in onus:
            self.discovery_tree.insert(
                "",
                "end",
                values=(onu.olt_interface, onu.model, onu.serial_number, onu.speed_mode),
            )
        self.status_var.set(f"查询完成：发现 {len(onus)} 台未注册 ONU")
        if not onus:
            messagebox.showinfo("查询结果", "当前 PON 口未发现可解析的未注册 ONU。", parent=self.root)

    def _fill_selected_onu(self):
        selected = self.discovery_tree.selection()
        if not selected:
            messagebox.showinfo("请选择 ONU", "请先在未注册 ONU 表格中选择一行。", parent=self.root)
            return
        interface, model, serial_number, speed_mode = self.discovery_tree.item(
            selected[0], "values"
        )
        location = interface.split("-", 1)[1].split("/")
        self.shelf_var.set(location[0])
        self.slot_var.set(location[1])
        self.pon_var.set(location[2])
        self.onu_type_var.set(model)
        self.sn_var.set(serial_number)
        self.real_speed_var.set(speed_mode_to_cli(speed_mode))
        self.status_var.set("已填入选中 ONU；请手工确认可用 ONU ID 和业务模板")

    def _apply_clicked(self):
        try:
            connection, config = self._validate(require_password=True)
            commands = build_provision_commands(config)
        except Exception as exc:
            self._show_error("参数错误", exc)
            return
        if not self.enable_apply_var.get():
            messagebox.showwarning(
                "尚未授权下发",
                "请先勾选“允许实际下发”，并核对命令预览。",
                parent=self.root,
            )
            return
        summary = (
            f"OLT：{connection.host}:{connection.port}\n"
            f"PON：{config.olt_interface}\n"
            f"ONU：{config.onu_interface}\n"
            f"型号/SN：{config.onu_type} / {config.serial_number}\n"
            f"业务 VLAN：{', '.join(str(item.vlan) for item in config.services)}\n\n"
            "工具会先检查 ONU ID 与 SN 冲突，遇到第一条 CLI 错误立即停止。\n"
            "不会执行 write，也不会在失败后自动删除 ONU。\n\n确定开始下发吗？"
        )
        if not messagebox.askyesno("确认实际下发", summary, icon="warning", parent=self.root):
            return

        def work():
            session = TitanTelnetSession(
                connection, logger=self._append_log, cancel_event=self.cancel_event
            )
            try:
                session.connect()
                self._append_log("=== 下发前冲突检查 ===")
                existing_output = session.execute(build_precheck_command(config))
                registered = parse_registered_onus(existing_output)
                for onu_id, onu_type, serial_number in registered:
                    if onu_id == config.onu_id:
                        raise RuntimeError(
                            f"ONU ID {onu_id} 已存在：type {onu_type} sn {serial_number}；已停止"
                        )
                    if serial_number.upper() == config.serial_number.upper():
                        raise RuntimeError(
                            f"SN {serial_number} 已注册在 ONU ID {onu_id}；已停止"
                        )
                uncfg_output = session.execute(
                    build_discovery_command(config.shelf, config.slot, config.pon)
                )
                discovered_sns = {
                    item.serial_number.upper() for item in parse_unconfigured_onus(uncfg_output)
                }
                if config.serial_number.upper() not in discovered_sns:
                    raise RuntimeError(
                        "目标 SN 当前不在未注册 ONU 列表中；可能已被其他会话注册或光路已变化"
                    )
                self._append_log("=== 开始注册与业务配置 ===")
                session.execute_many(commands, timeout=25)
                self._append_log("=== 下发后只读验证 ===")
                session.execute_many(build_verify_commands(config), timeout=35)
                self.root.after(0, self._apply_succeeded)
            except Exception:
                session.best_effort_end()
                raise
            finally:
                session.close()

        self._start_worker("注册与配置", work)

    def _apply_succeeded(self):
        self.status_var.set("注册与业务配置完成；只读验证已执行，未执行 write")
        self.notebook.select(self.log_tab)
        messagebox.showinfo(
            "执行完成",
            "ONU 注册和业务配置命令已完成，验证输出见日志。\n工具未执行 write。",
            parent=self.root,
        )

    def _append_log(self, message: str):
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        self.root.after(0, append)

    def _start_worker(self, label: str, work: Callable[[], None]):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("任务进行中", "请等待当前任务完成或先停止。", parent=self.root)
            return
        self.cancel_event = threading.Event()
        self._set_busy(True)
        self.status_var.set(f"正在{label}……")
        self.notebook.select(self.log_tab)
        self._append_log(f"\n===== {label} =====")

        def runner():
            error = None
            try:
                work()
            except OperationCancelled as exc:
                error = exc
            except Exception as exc:
                error = exc
                self._append_log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._worker_finished(label, error))

        self.worker = threading.Thread(target=runner, name="olt-worker", daemon=True)
        self.worker.start()

    def _worker_finished(self, label: str, error: Optional[Exception]):
        self._set_busy(False)
        if error:
            self.status_var.set(f"{label}失败：{error}")
            if isinstance(error, OperationCancelled):
                messagebox.showinfo("已停止", str(error), parent=self.root)
            else:
                messagebox.showerror(f"{label}失败", str(error), parent=self.root)
        elif not self.status_var.get().startswith("注册与业务配置完成"):
            self.status_var.set(f"{label}完成")

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        for button in (
            getattr(self, "discover_button", None),
            getattr(self, "preview_button", None),
            getattr(self, "apply_button", None),
        ):
            if button:
                button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _cancel(self):
        self.cancel_event.set()
        self.status_var.set("正在停止当前操作……")


def main():
    root = tk.Tk()
    TitanProvisionerApp(root)
    root.mainloop()

"""DUT 配置窗口；仅负责界面展示和回调，不承载 UBUS 业务逻辑。"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from tkinter import END, StringVar, Toplevel, messagebox, ttk

from src.models import DutTelnetEnableRequest, DutTelnetEnableResult
from src.services.dut_config_service import (
    DEFAULT_DUT_PARALLEL_COUNT,
    MAX_DUT_PARALLEL_COUNT,
)


class DutConfigWindow:
    """可扩展 DUT 配置容器；后续能力通过 ``notebook.add`` 增加独立 Tab。"""

    def __init__(
        self,
        master,
        *,
        username_var: StringVar,
        password_var: StringVar,
        on_refresh: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        self.window = Toplevel(master)
        self.window.withdraw()
        self.window.title("DUT配置")
        self.window.geometry("980x650")
        self.window.minsize(860, 560)
        self.window.transient(master)
        self.window.protocol("WM_DELETE_WINDOW", on_close)

        self.username_var = username_var
        self.password_var = password_var
        self.parallel_count_var = StringVar(value=str(DEFAULT_DUT_PARALLEL_COUNT))
        self.summary_var = StringVar(value="尚未加载目标 DUT")
        self._row_by_channel: dict[str, str] = {}

        outer = ttk.Frame(self.window, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="DUT配置", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="通过独立功能页配置已勾选 DUT；后续 UBUS 能力将在此窗口增加新的 Tab。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 12))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        telnet_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(telnet_tab, text="Telnet配置")

        credential_row = ttk.Frame(telnet_tab)
        credential_row.pack(fill="x", pady=(0, 10))
        ttk.Label(credential_row, text="UBUS 登录账号：").pack(side="left")
        self.username_entry = ttk.Entry(
            credential_row, textvariable=self.username_var, width=22
        )
        self.username_entry.pack(side="left", padx=(6, 16))
        ttk.Label(credential_row, text="密码：").pack(side="left")
        # 项目约定密码可明文显示，因此输入框不启用字符遮罩。
        self.password_entry = ttk.Entry(
            credential_row, textvariable=self.password_var, width=24
        )
        self.password_entry.pack(side="left", padx=(6, 16))
        ttk.Label(credential_row, text="并行数：").pack(side="left")
        self.parallel_spinbox = ttk.Spinbox(
            credential_row,
            from_=1,
            to=MAX_DUT_PARALLEL_COUNT,
            textvariable=self.parallel_count_var,
            width=5,
        )
        self.parallel_spinbox.pack(side="left", padx=(6, 0))
        ttk.Label(
            credential_row,
            text=f"（1–{MAX_DUT_PARALLEL_COUNT}，默认 {DEFAULT_DUT_PARALLEL_COUNT}）",
            style="Muted.TLabel",
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            telnet_tab,
            text=(
                "目标来自主界面已勾选通道。执行时会启用对应 VLAN 网卡、设置 PC 静态 IP，"
                "通过 UBUS 开启 Telnet，并从该 VLAN 源 IP 验证 TCP 23 端口。"
            ),
            style="Muted.TLabel",
            wraplength=850,
            justify="left",
        ).pack(fill="x", anchor="w", pady=(0, 10))

        table_frame = ttk.Frame(telnet_tab)
        table_frame.pack(fill="both", expand=True)
        columns = ("channel", "vlan", "adapter", "bind_ip", "device_host", "status")
        self.target_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=13
        )
        headings = {
            "channel": "通道",
            "vlan": "VLAN",
            "adapter": "网卡",
            "bind_ip": "PC 静态 IP",
            "device_host": "样机管理 IP",
            "status": "状态",
        }
        widths = {
            "channel": 80,
            "vlan": 85,
            "adapter": 135,
            "bind_ip": 120,
            "device_host": 120,
            "status": 300,
        }
        for column in columns:
            self.target_tree.heading(column, text=headings[column])
            self.target_tree.column(column, width=widths[column], anchor="w", stretch=column == "status")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.target_tree.yview)
        self.target_tree.configure(yscrollcommand=scrollbar.set)
        self.target_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(telnet_tab, textvariable=self.summary_var, style="Muted.TLabel").pack(
            fill="x", anchor="w", pady=(8, 8)
        )
        actions = ttk.Frame(telnet_tab)
        actions.pack(fill="x")
        self.refresh_button = ttk.Button(
            actions, text="刷新目标", command=on_refresh, style="Secondary.TButton"
        )
        self.refresh_button.pack(side="left")
        self.close_button = ttk.Button(
            actions, text="关闭", command=on_close, style="Secondary.TButton"
        )
        self.close_button.pack(side="right")
        self.start_button = ttk.Button(
            actions, text="开启 Telnet", command=on_start, style="Primary.TButton"
        )
        self.start_button.pack(side="right", padx=(0, 8))
        self.stop_button = ttk.Button(
            actions, text="停止", command=on_stop, state="disabled", style="Secondary.TButton"
        )
        self.stop_button.pack(side="right", padx=(0, 8))

        self.window.after(0, self._reveal)

    def _reveal(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.update_idletasks()
        self.window.update()
        self.window.focus_force()

    def exists(self) -> bool:
        return bool(self.window.winfo_exists())

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def destroy(self) -> None:
        self.window.destroy()

    def parallel_count(self) -> str:
        return self.parallel_count_var.get()

    def set_targets(
        self,
        requests: Iterable[DutTelnetEnableRequest],
        errors_by_channel: Mapping[str, str],
    ) -> None:
        for item in self.target_tree.get_children():
            self.target_tree.delete(item)
        self._row_by_channel.clear()
        request_list = list(requests)
        for index, request in enumerate(request_list):
            status = errors_by_channel.get(request.channel, "配置完整，等待执行")
            row_id = self.target_tree.insert(
                "",
                END,
                values=(
                    request.channel,
                    request.vlan or "未配置",
                    request.adapter_alias or "未配置",
                    request.bind_ip or "未配置",
                    request.device_host or "未配置",
                    status,
                ),
            )
            self._row_by_channel[request.channel or f"row-{index}"] = row_id
        self.summary_var.set(
            f"已加载 {len(request_list)} 台目标 DUT"
            if request_list
            else "主界面当前没有已勾选通道"
        )

    def mark_all_pending(self) -> None:
        for row_id in self._row_by_channel.values():
            values = list(self.target_tree.item(row_id, "values"))
            values[-1] = "等待执行"
            self.target_tree.item(row_id, values=values)

    def update_result(self, result: DutTelnetEnableResult) -> None:
        row_id = self._row_by_channel.get(result.request.channel)
        if row_id is None:
            return
        values = list(self.target_tree.item(row_id, "values"))
        if result.ok:
            values[-1] = "成功：Telnet 已开启并验证可用"
        elif result.stage == "stopped":
            values[-1] = f"已停止：{result.message}"
        else:
            values[-1] = f"失败：{result.message}"
        self.target_tree.item(row_id, values=values)

    def set_summary(self, text: str) -> None:
        self.summary_var.set(text)

    def set_running(self, running: bool, *, stopping: bool = False) -> None:
        input_state = "disabled" if running else "normal"
        self.username_entry.configure(state=input_state)
        self.password_entry.configure(state=input_state)
        self.parallel_spinbox.configure(state=input_state)
        self.refresh_button.configure(state="disabled" if running else "normal")
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="disabled" if not running or stopping else "normal")
        if stopping:
            self.summary_var.set("正在停止：已运行任务将在安全点结束，尚未开始的 DUT 将跳过")


__all__ = ["DutConfigWindow"]

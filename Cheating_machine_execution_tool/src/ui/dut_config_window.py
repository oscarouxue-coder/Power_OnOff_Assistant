"""DUT 配置窗口；仅负责界面展示和回调，不承载 UBUS 业务逻辑。"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from tkinter import BooleanVar, Checkbutton, END, StringVar, Toplevel, ttk

from src.models import (
    DutAdvancedConfigResult,
    DutTelnetEnableRequest,
    DutTelnetEnableResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutWanConnectionInfo,
    DutWanQueryResult,
    DutWanSettings,
)
from src.services.dut_config_service import (
    DEFAULT_DUT_PARALLEL_COUNT,
    MAX_DUT_PARALLEL_COUNT,
)
from src.services.dut_advanced_config_service import VOICE_CODEC_OPTIONS


DUT_CHECK_BACKGROUND = "#ffffff"
DUT_CHECK_FOREGROUND = "#17202a"
WAN_ROUTER_SERVICE_TYPES = (
    "INTERNET",
    "TR069",
    "VOICE",
    "TR069_VOICE",
    "TR069_INTERNET",
    "VOICE_INTERNET",
    "TR069_VOICE_INTERNET",
    "IPTV",
    "OTHER",
)
WAN_BRIDGE_SERVICE_TYPES = ("IPTV", "INTERNET", "OTHER")


@dataclass(frozen=True)
class WanFormRules:
    """WAN 当前选择对应的可见字段；不包含任何 UBUS 业务执行。"""

    show_index: bool
    show_config: bool
    show_router: bool
    show_pppoe_credentials: bool
    show_ipv4_selector: bool
    show_ipv4_static: bool
    show_ipv6_selector: bool
    show_ipv6_static: bool
    mtu_default: str


def normalize_wan_address_modes(
    access_type: str,
    ip_protocol: str,
    ipv4_type: str,
    ipv6_type: str,
    *,
    changed: str = "",
) -> tuple[str, str]:
    """把地址方式收敛到 WAN 协议封装实际支持的组合。"""
    if access_type == "PPPoE":
        return "DHCP", ipv6_type if ipv6_type in {"SLAAC", "DHCPv6"} else "SLAAC"
    if ip_protocol != "IPv4+IPv6（双栈）":
        return ipv4_type, ipv6_type
    if changed == "ipv4_type":
        return ("静态", "静态") if ipv4_type == "静态" else ("DHCP", "SLAAC" if ipv6_type == "静态" else ipv6_type)
    if changed == "ipv6_type":
        return ("静态", "静态") if ipv6_type == "静态" else ("DHCP" if ipv4_type == "静态" else ipv4_type, ipv6_type)
    if "静态" in {ipv4_type, ipv6_type}:
        return "静态", "静态"
    return "DHCP", ipv6_type


def resolve_wan_form_rules(
    operation: str,
    mode: str,
    access_type: str,
    ip_protocol: str,
    ipv4_type: str,
    ipv6_type: str,
) -> WanFormRules:
    """返回 WAN 表单显隐规则，供 Tk 界面和无界面测试共同使用。"""
    show_config = operation != "删除"
    show_router = show_config and mode == "路由"
    show_ipv4 = show_router and ip_protocol in {"IPv4", "IPv4+IPv6（双栈）"}
    show_ipv6 = show_router and ip_protocol in {"IPv6", "IPv4+IPv6（双栈）"}
    return WanFormRules(
        show_index=operation in {"修改", "删除"},
        show_config=show_config,
        show_router=show_router,
        show_pppoe_credentials=show_router and access_type == "PPPoE",
        show_ipv4_selector=show_ipv4,
        show_ipv4_static=show_ipv4 and ipv4_type == "静态",
        show_ipv6_selector=show_ipv6,
        show_ipv6_static=show_ipv6 and ipv6_type == "静态",
        mtu_default="1492" if access_type == "PPPoE" else "1500",
    )


def wan_connection_form_values(info: DutWanConnectionInfo) -> dict[str, str | bool | None]:
    """把业务模型值转换为 WAN 表单使用的中文枚举和值。"""
    protocol = {
        "IPv4AndIPv6": "IPv4+IPv6（双栈）",
        "IPv4/IPv6": "IPv4+IPv6（双栈）",
        "IPv4IPv6": "IPv4+IPv6（双栈）",
    }.get(info.ip_protocol, info.ip_protocol)
    return {
        "mode": "桥接" if info.mode.lower() == "bridge" else "路由" if info.mode else "",
        "service_type": info.service_type.replace("-", "_").upper(),
        "vlan_id": info.vlan_id,
        "vlan_priority": info.vlan_priority,
        "port_bind": info.port_bind,
        "mtu": info.mtu,
        "nat_enabled": info.nat_enabled,
        "access_type": info.access_type,
        "ip_protocol": protocol,
        "ipv4_type": "静态" if info.ipv4_type.lower() == "static" else "DHCP" if info.ipv4_type else "",
        "ipv4_address": info.ipv4_address,
        "ipv4_netmask": info.ipv4_netmask,
        "ipv4_gateway": info.ipv4_gateway,
        "ipv4_primary_dns": info.ipv4_primary_dns,
        "ipv4_secondary_dns": info.ipv4_secondary_dns,
        "ipv6_type": "静态" if info.ipv6_type.lower() == "static" else info.ipv6_type,
        "ipv6_address": info.ipv6_address,
        "ipv6_prefix": info.ipv6_prefix,
        "ipv6_gateway": info.ipv6_gateway,
        "ipv6_primary_dns": info.ipv6_primary_dns,
        "ipv6_secondary_dns": info.ipv6_secondary_dns,
        "pppoe_username": info.pppoe_username,
        "pppoe_password": info.pppoe_password,
    }


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
        on_start_wan: Callable[[], None],
        on_query_wan: Callable[[], None],
        on_start_voice: Callable[[], None],
        on_start_tr069: Callable[[], None],
        on_stop: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        self.window = Toplevel(master)
        self.window.withdraw()
        self.window.title("DUT配置")
        self.window.geometry("1180x780")
        self.window.minsize(980, 680)
        self.window.transient(master)
        self.window.protocol("WM_DELETE_WINDOW", on_close)

        self.username_var = username_var
        self.password_var = password_var
        self.parallel_count_var = StringVar(value=str(DEFAULT_DUT_PARALLEL_COUNT))
        self.summary_var = StringVar(value="尚未加载目标 DUT")
        self._row_by_channel: dict[str, str] = {}
        self._trees: dict[str, ttk.Treeview] = {}
        self._rows_by_feature: dict[str, dict[str, str]] = {}
        self._summary_vars: dict[str, StringVar] = {"telnet": self.summary_var}
        self._input_widgets: list = []
        self._field_groups: dict[str, tuple[object, object]] = {}
        self._start_buttons: dict[str, ttk.Button] = {}
        self._stop_buttons: list[ttk.Button] = []

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

        self._trees["telnet"] = self.target_tree
        self._rows_by_feature["telnet"] = self._row_by_channel
        self._input_widgets.extend(
            [self.username_entry, self.password_entry, self.parallel_spinbox, self.refresh_button]
        )
        self._start_buttons["telnet"] = self.start_button
        self._stop_buttons.append(self.stop_button)

        self._build_wan_tab(on_refresh, on_start_wan, on_query_wan, on_stop, on_close)
        self._build_voice_tab(on_refresh, on_start_voice, on_stop, on_close)
        self._build_tr069_tab(on_refresh, on_start_tr069, on_stop, on_close)

        self.window.after(0, self._reveal)

    def _field(
        self,
        parent,
        row: int,
        pair: int,
        label: str,
        variable,
        *,
        values: tuple[str, ...] | None = None,
        width: int = 16,
        field_key: str | None = None,
    ):
        column = pair * 2
        label_widget = ttk.Label(parent, text=label, anchor="w")
        label_widget.grid(row=row, column=column, sticky="w", padx=(4, 4), pady=3)
        if values is None:
            widget = ttk.Entry(parent, textvariable=variable, width=width)
        else:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        widget.grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=3)
        parent.columnconfigure(column + 1, weight=1)
        self._input_widgets.append(widget)
        if field_key is not None:
            self._field_groups[field_key] = (label_widget, widget)
        return widget

    def _native_checkbutton(self, parent, *, text: str, variable: BooleanVar) -> Checkbutton:
        """创建选中态为标准勾号的原生复选框，避开 Clam 主题叉号。"""
        widget = Checkbutton(
            parent,
            text=text,
            variable=variable,
            selectcolor=DUT_CHECK_BACKGROUND,
            background=DUT_CHECK_BACKGROUND,
            activebackground=DUT_CHECK_BACKGROUND,
            foreground=DUT_CHECK_FOREGROUND,
            activeforeground=DUT_CHECK_FOREGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self._input_widgets.append(widget)
        return widget

    def _advanced_target_area(
        self,
        tab,
        feature: str,
        *,
        start_text: str,
        on_refresh: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, pady=(8, 0))
        columns = ("channel", "vlan", "adapter", "bind_ip", "device_host", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=6)
        headings = {
            "channel": "通道", "vlan": "管理 VLAN", "adapter": "网卡",
            "bind_ip": "PC 静态 IP", "device_host": "样机管理 IP", "status": "状态",
        }
        widths = {
            "channel": 75, "vlan": 90, "adapter": 125, "bind_ip": 115,
            "device_host": 115, "status": 330,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w", stretch=column == "status")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        summary_var = StringVar(value="尚未加载目标 DUT")
        ttk.Label(tab, textvariable=summary_var, style="Muted.TLabel").pack(
            fill="x", anchor="w", pady=(6, 6)
        )
        actions = ttk.Frame(tab)
        actions.pack(fill="x")
        refresh = ttk.Button(actions, text="刷新目标", command=on_refresh, style="Secondary.TButton")
        refresh.pack(side="left")
        ttk.Button(actions, text="关闭", command=on_close, style="Secondary.TButton").pack(side="right")
        start = ttk.Button(actions, text=start_text, command=on_start, style="Primary.TButton")
        start.pack(side="right", padx=(0, 8))
        stop = ttk.Button(actions, text="停止", command=on_stop, state="disabled", style="Secondary.TButton")
        stop.pack(side="right", padx=(0, 8))
        self._trees[feature] = tree
        self._rows_by_feature[feature] = {}
        self._summary_vars[feature] = summary_var
        self._input_widgets.append(refresh)
        self._start_buttons[feature] = start
        self._stop_buttons.append(stop)

    def _build_wan_tab(self, on_refresh, on_start, on_query, on_stop, on_close) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="WAN配置")
        ttk.Label(
            tab,
            text=(
                "批量新增、修改或删除 WAN；支持 IPv4、IPv6 与 IPv4+IPv6 双栈。"
                "修改/删除请先查询并从共同存在的 WAN 下拉列表选择，"
                "删除不会自动匹配或删除其它 WAN。"
                "UBUS 凭据和并行数与 Telnet 配置页共享。"
            ),
            style="Muted.TLabel", wraplength=1080, justify="left",
        ).pack(fill="x", anchor="w", pady=(0, 6))
        form = ttk.LabelFrame(tab, text="WAN 参数", padding=8)
        form.pack(fill="x")
        self.wan_operation_var = StringVar(value="新增")
        self.wan_index_var = StringVar(value="")
        self.wan_mode_var = StringVar(value="路由")
        self.wan_service_type_var = StringVar(value="INTERNET")
        self.wan_vlan_id_var = StringVar(value="200")
        self.wan_vlan_priority_var = StringVar(value="0")
        self.wan_port_bind_var = StringVar(value="0")
        self.wan_mtu_var = StringVar(value="1500")
        self.wan_nat_var = BooleanVar(value=True)
        self.wan_access_type_var = StringVar(value="IPoE")
        self.wan_ip_protocol_var = StringVar(value="IPv4")
        self.wan_ipv4_type_var = StringVar(value="DHCP")
        self.wan_ipv4_address_var = StringVar(value="")
        self.wan_ipv4_netmask_var = StringVar(value="255.255.255.0")
        self.wan_ipv4_gateway_var = StringVar(value="")
        self.wan_ipv4_primary_dns_var = StringVar(value="")
        self.wan_ipv4_secondary_dns_var = StringVar(value="")
        self.wan_ipv6_type_var = StringVar(value="SLAAC")
        self.wan_ipv6_address_var = StringVar(value="")
        self.wan_ipv6_prefix_var = StringVar(value="")
        self.wan_ipv6_gateway_var = StringVar(value="")
        self.wan_ipv6_primary_dns_var = StringVar(value="")
        self.wan_ipv6_secondary_dns_var = StringVar(value="")
        self.wan_pppoe_username_var = StringVar(value="")
        self.wan_pppoe_password_var = StringVar(value="")
        self._field(form, 0, 0, "操作：", self.wan_operation_var, values=("新增", "修改", "删除"))
        index_label = ttk.Label(form, text="现有连接名/索引：", anchor="w")
        index_label.grid(row=0, column=2, sticky="w", padx=(4, 4), pady=3)
        index_holder = ttk.Frame(form)
        index_holder.grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=3)
        form.columnconfigure(3, weight=1)
        self.wan_index_combo = ttk.Combobox(
            index_holder,
            textvariable=self.wan_index_var,
            values=(),
            state="readonly",
            width=25,
        )
        self.wan_index_combo.pack(side="left", fill="x", expand=True)
        self.wan_index_combo.bind("<<ComboboxSelected>>", self._apply_selected_wan_connection)
        self.wan_query_button = ttk.Button(
            index_holder,
            text="查询现有 WAN",
            command=on_query,
            style="Secondary.TButton",
        )
        self.wan_query_button.pack(side="left", padx=(6, 0))
        self._field_groups["wan_index"] = (index_label, index_holder)
        self._input_widgets.extend((self.wan_index_combo, self.wan_query_button))
        self._field(form, 0, 2, "模式：", self.wan_mode_var, values=("路由", "桥接"), field_key="wan_mode")
        self._field(
            form, 0, 3, "业务类型：", self.wan_service_type_var,
            values=WAN_ROUTER_SERVICE_TYPES, width=22, field_key="wan_service_type",
        )
        self._field(form, 1, 0, "业务 VLAN ID：", self.wan_vlan_id_var, field_key="wan_vlan_id")
        self._field(form, 1, 1, "VLAN 优先级：", self.wan_vlan_priority_var, field_key="wan_vlan_priority")
        self._field(form, 1, 2, "端口绑定位掩码：", self.wan_port_bind_var, field_key="wan_port_bind")
        self._field(form, 1, 3, "MTU：", self.wan_mtu_var, field_key="wan_mtu")
        self._field(form, 2, 0, "接入方式：", self.wan_access_type_var, values=("IPoE", "PPPoE"), field_key="wan_access_type")
        self._field(form, 2, 1, "IP 协议：", self.wan_ip_protocol_var, values=("IPv4", "IPv6", "IPv4+IPv6（双栈）"), width=20, field_key="wan_ip_protocol")
        self.wan_ipv4_type_combo = self._field(
            form, 2, 2, "IPv4 地址方式：", self.wan_ipv4_type_var,
            values=("DHCP", "静态"), field_key="wan_ipv4_type",
        )
        self.wan_ipv6_type_combo = self._field(
            form, 2, 3, "IPv6 地址方式：", self.wan_ipv6_type_var,
            values=("SLAAC", "DHCPv6", "静态"), field_key="wan_ipv6_type",
        )
        self._field(form, 3, 0, "IPv4 地址：", self.wan_ipv4_address_var, field_key="wan_ipv4_address")
        self._field(form, 3, 1, "IPv4 掩码：", self.wan_ipv4_netmask_var, field_key="wan_ipv4_netmask")
        self._field(form, 3, 2, "IPv4 网关：", self.wan_ipv4_gateway_var, field_key="wan_ipv4_gateway")
        self._field(form, 3, 3, "IPv4 主 DNS：", self.wan_ipv4_primary_dns_var, field_key="wan_ipv4_primary_dns")
        self._field(form, 4, 0, "IPv4 备 DNS：", self.wan_ipv4_secondary_dns_var, field_key="wan_ipv4_secondary_dns")
        self._field(form, 4, 1, "PPPoE 账号：", self.wan_pppoe_username_var, field_key="wan_pppoe_username")
        self._field(form, 4, 2, "PPPoE 密码：", self.wan_pppoe_password_var, field_key="wan_pppoe_password")
        nat = self._native_checkbutton(form, text="启用 NAT", variable=self.wan_nat_var)
        nat.grid(row=4, column=6, columnspan=2, sticky="w", padx=4, pady=3)
        self._wan_nat_widget = nat
        self._field(form, 5, 0, "IPv6 地址：", self.wan_ipv6_address_var, field_key="wan_ipv6_address")
        self._field(form, 5, 1, "IPv6 前缀：", self.wan_ipv6_prefix_var, field_key="wan_ipv6_prefix")
        self._field(form, 5, 2, "IPv6 网关：", self.wan_ipv6_gateway_var, field_key="wan_ipv6_gateway")
        self._field(form, 5, 3, "IPv6 主 DNS：", self.wan_ipv6_primary_dns_var, field_key="wan_ipv6_primary_dns")
        self._field(form, 6, 0, "IPv6 备 DNS：", self.wan_ipv6_secondary_dns_var, field_key="wan_ipv6_secondary_dns")
        self.wan_rule_hint_var = StringVar(value="")
        ttk.Label(
            form, textvariable=self.wan_rule_hint_var, style="Muted.TLabel",
            justify="left", wraplength=1050,
        ).grid(row=7, column=0, columnspan=8, sticky="w", padx=4, pady=(5, 0))
        self.wan_query_status_var = StringVar(
            value="修改/删除时请先点击“查询现有 WAN”，再从下拉列表选择。"
        )
        ttk.Label(
            form,
            textvariable=self.wan_query_status_var,
            style="Muted.TLabel",
            justify="left",
            wraplength=1050,
        ).grid(row=8, column=0, columnspan=8, sticky="w", padx=4, pady=(2, 0))
        self._wan_target_signature: tuple[tuple[str, ...], ...] = ()
        self._wan_connection_details: dict[str, DutWanConnectionInfo] = {}
        self._updating_wan_form = False
        self._last_wan_access_type = ""
        for variable, changed in (
            (self.wan_operation_var, "operation"),
            (self.wan_mode_var, "mode"),
            (self.wan_access_type_var, "access_type"),
            (self.wan_ip_protocol_var, "ip_protocol"),
            (self.wan_ipv4_type_var, "ipv4_type"),
            (self.wan_ipv6_type_var, "ipv6_type"),
        ):
            variable.trace_add("write", lambda *_args, source=changed: self._update_wan_form_visibility(source))
        self._update_wan_form_visibility("initial")
        self._advanced_target_area(
            tab, "wan", start_text="执行 WAN 配置", on_refresh=on_refresh,
            on_start=on_start, on_stop=on_stop, on_close=on_close,
        )

    def clear_wan_connections(self, message: str | None = None) -> None:
        """清除可能已过期的 WAN 下拉缓存。"""
        self._wan_connection_details = {}
        self.wan_index_combo.configure(values=())
        self.wan_index_var.set("")
        self.wan_query_status_var.set(
            message or "修改/删除时请先点击“查询现有 WAN”，再从下拉列表选择。"
        )

    def set_wan_connections(
        self,
        connection_names: Iterable[str],
        *,
        target_count: int,
        connection_details: Mapping[str, DutWanConnectionInfo] | None = None,
    ) -> None:
        """显示共同 WAN；详情一致时默认选中并同步回填当前 WAN 信息。"""
        names = tuple(connection_names)
        self._wan_connection_details = dict(connection_details or {})
        self.wan_index_combo.configure(values=names)
        if self.wan_index_var.get() not in names:
            self.wan_index_var.set(names[0] if names else "")
        if names:
            detail_count = len(self._wan_connection_details)
            self.wan_query_status_var.set(
                f"已查询 {target_count} 台 DUT，共同存在 {len(names)} 个 WAN；"
                f"其中 {detail_count} 个完整配置在所有目标上一致。"
            )
            self._apply_selected_wan_connection()
        else:
            self.wan_query_status_var.set(
                f"已查询 {target_count} 台 DUT，未发现名称完全一致的共同 WAN。"
            )

    def _apply_selected_wan_connection(self, _event=None) -> None:
        """把下拉框当前 WAN 的只读快照同步到修改表单。"""
        name = self.wan_index_var.get().strip()
        info = self._wan_connection_details.get(name)
        if info is None:
            if name:
                self.wan_query_status_var.set(
                    "当前 WAN 在目标间的完整参数不一致或详情不可用；"
                    "下拉名称仍可用于删除，修改前请人工核对参数。"
                )
            return
        values = wan_connection_form_values(info)
        variables = {
            "mode": self.wan_mode_var,
            "service_type": self.wan_service_type_var,
            "vlan_id": self.wan_vlan_id_var,
            "vlan_priority": self.wan_vlan_priority_var,
            "port_bind": self.wan_port_bind_var,
            "mtu": self.wan_mtu_var,
            "access_type": self.wan_access_type_var,
            "ip_protocol": self.wan_ip_protocol_var,
            "ipv4_type": self.wan_ipv4_type_var,
            "ipv4_address": self.wan_ipv4_address_var,
            "ipv4_netmask": self.wan_ipv4_netmask_var,
            "ipv4_gateway": self.wan_ipv4_gateway_var,
            "ipv4_primary_dns": self.wan_ipv4_primary_dns_var,
            "ipv4_secondary_dns": self.wan_ipv4_secondary_dns_var,
            "ipv6_type": self.wan_ipv6_type_var,
            "ipv6_address": self.wan_ipv6_address_var,
            "ipv6_prefix": self.wan_ipv6_prefix_var,
            "ipv6_gateway": self.wan_ipv6_gateway_var,
            "ipv6_primary_dns": self.wan_ipv6_primary_dns_var,
            "ipv6_secondary_dns": self.wan_ipv6_secondary_dns_var,
            "pppoe_username": self.wan_pppoe_username_var,
            "pppoe_password": self.wan_pppoe_password_var,
        }
        self._updating_wan_form = True
        try:
            enum_fields = {
                "mode", "service_type", "access_type", "ip_protocol",
                "ipv4_type", "ipv6_type",
            }
            for key, variable in variables.items():
                value = values[key]
                if key not in enum_fields or value not in (None, ""):
                    variable.set(value)
            if values["nat_enabled"] is not None:
                self.wan_nat_var.set(bool(values["nat_enabled"]))
            self._last_wan_access_type = self.wan_access_type_var.get()
        finally:
            self._updating_wan_form = False
        self._update_wan_form_visibility("snapshot")
        self.wan_query_status_var.set(
            f"已同步当前 WAN 完整信息：{name}；修改前可直接核对并调整。"
        )

    def _set_wan_field_visible(self, field_key: str, visible: bool) -> None:
        for widget in self._field_groups[field_key]:
            widget.grid() if visible else widget.grid_remove()

    def _update_wan_form_visibility(self, changed: str = "") -> None:
        """按操作、模式、接入方式、协议和地址方式实时收敛 WAN 表单。"""
        if self._updating_wan_form:
            return
        self._updating_wan_form = True
        try:
            access_type = self.wan_access_type_var.get()
            if access_type != self._last_wan_access_type:
                self.wan_mtu_var.set("1492" if access_type == "PPPoE" else "1500")
                self._last_wan_access_type = access_type

            ipv4_type, ipv6_type = normalize_wan_address_modes(
                access_type,
                self.wan_ip_protocol_var.get(),
                self.wan_ipv4_type_var.get(),
                self.wan_ipv6_type_var.get(),
                changed=changed,
            )
            if self.wan_ipv4_type_var.get() != ipv4_type:
                self.wan_ipv4_type_var.set(ipv4_type)
            if self.wan_ipv6_type_var.get() != ipv6_type:
                self.wan_ipv6_type_var.set(ipv6_type)

            is_bridge = self.wan_mode_var.get() == "桥接"
            service_options = WAN_BRIDGE_SERVICE_TYPES if is_bridge else WAN_ROUTER_SERVICE_TYPES
            service_combo = self._field_groups["wan_service_type"][1]
            service_combo.configure(values=service_options)
            if self.wan_service_type_var.get() not in service_options:
                self.wan_service_type_var.set("IPTV" if is_bridge else "INTERNET")
            if is_bridge and self.wan_port_bind_var.get().strip() == "0":
                self.wan_port_bind_var.set("1")

            if access_type == "PPPoE":
                self.wan_ipv4_type_combo.configure(values=("DHCP",))
                self.wan_ipv6_type_combo.configure(values=("SLAAC", "DHCPv6"))
            else:
                self.wan_ipv4_type_combo.configure(values=("DHCP", "静态"))
                self.wan_ipv6_type_combo.configure(values=("SLAAC", "DHCPv6", "静态"))

            rules = resolve_wan_form_rules(
                self.wan_operation_var.get(), self.wan_mode_var.get(), access_type,
                self.wan_ip_protocol_var.get(), ipv4_type, ipv6_type,
            )
            visibility = {
                "wan_index": rules.show_index,
                "wan_mode": rules.show_config,
                "wan_service_type": rules.show_config,
                "wan_vlan_id": rules.show_config,
                "wan_vlan_priority": rules.show_config,
                "wan_port_bind": rules.show_config,
                "wan_mtu": rules.show_router,
                "wan_access_type": rules.show_router,
                "wan_ip_protocol": rules.show_router,
                "wan_ipv4_type": rules.show_ipv4_selector,
                "wan_ipv6_type": rules.show_ipv6_selector,
                "wan_pppoe_username": rules.show_pppoe_credentials,
                "wan_pppoe_password": rules.show_pppoe_credentials,
            }
            for key in (
                "wan_ipv4_address", "wan_ipv4_netmask", "wan_ipv4_gateway",
                "wan_ipv4_primary_dns", "wan_ipv4_secondary_dns",
            ):
                visibility[key] = rules.show_ipv4_static
            for key in (
                "wan_ipv6_address", "wan_ipv6_prefix", "wan_ipv6_gateway",
                "wan_ipv6_primary_dns", "wan_ipv6_secondary_dns",
            ):
                visibility[key] = rules.show_ipv6_static
            for field_key, visible in visibility.items():
                self._set_wan_field_visible(field_key, visible)
            self._wan_nat_widget.grid() if rules.show_router else self._wan_nat_widget.grid_remove()

            if not rules.show_config:
                hint = "删除仅按现有连接名/索引执行，不展示或使用其它 WAN 参数。"
            elif not rules.show_router:
                hint = "桥接 WAN 仅使用业务类型、VLAN、优先级和端口绑定；默认绑定 LAN1（位掩码 1）。"
            else:
                protocol = self.wan_ip_protocol_var.get()
                address_hint = []
                if rules.show_ipv4_selector:
                    address_hint.append(f"IPv4 {ipv4_type}")
                if rules.show_ipv6_selector:
                    address_hint.append(f"IPv6 {ipv6_type}")
                hint = (
                    f"当前为 {access_type} {protocol}（{' + '.join(address_hint)}），"
                    f"协议默认 MTU {rules.mtu_default}；动态地址不需要填写静态地址项。"
                )
                if access_type == "PPPoE":
                    hint += " PPPoE 仅支持动态地址组合，需填写账号和密码。"
                elif protocol == "IPv4+IPv6（双栈）":
                    hint += " IPoE 双栈静态时 IPv4 与 IPv6 必须同时静态。"
            self.wan_rule_hint_var.set(hint)
        finally:
            self._updating_wan_form = False

    def _build_voice_tab(self, on_refresh, on_start, on_stop, on_close) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="语音配置")
        ttk.Label(
            tab,
            text=(
                "批量配置 SIP 基础参数、服务器、账号、5 项编码优先级和 DigitMap；"
                "UBUS 凭据和并行数与 Telnet 配置页共享。"
            ),
            style="Muted.TLabel",
        ).pack(fill="x", anchor="w", pady=(0, 6))
        form = ttk.LabelFrame(tab, text="语音参数", padding=8)
        form.pack(fill="x")
        self.voice_line_index_var = StringVar(value="1")
        self.voice_account_enabled_var = BooleanVar(value=True)
        self.voice_display_name_var = StringVar(value="")
        self.voice_auth_username_var = StringVar(value="")
        self.voice_auth_password_var = StringVar(value="")
        self.voice_proxy_server_var = StringVar(value="")
        self.voice_proxy_port_var = StringVar(value="5060")
        self.voice_outbound_proxy_var = StringVar(value="")
        self.voice_outbound_proxy_port_var = StringVar(value="5060")
        self.voice_registrar_server_var = StringVar(value="")
        self.voice_registrar_server_port_var = StringVar(value="5060")
        self.voice_dtmf_method_var = StringVar(value="RFC2833")
        self.voice_register_expires_var = StringVar(value="3600")
        self.voice_sip_mode_var = StringVar(value="SIP")
        self.voice_digit_map_var = StringVar(value="x.")
        codec_defaults = ("G.711 U-law", "G.711 A-law", "G.729", "G.722", "G.723")
        self.voice_codec_vars = [StringVar(value=value) for value in codec_defaults]
        self._field(form, 0, 0, "线路索引：", self.voice_line_index_var)
        account_enable = self._native_checkbutton(
            form, text="启用 SIP 账号", variable=self.voice_account_enabled_var
        )
        account_enable.grid(row=0, column=2, columnspan=2, sticky="w", padx=4, pady=3)
        self._field(form, 0, 2, "显示名称：", self.voice_display_name_var)
        self._field(form, 0, 3, "认证账号：", self.voice_auth_username_var)
        self._field(form, 1, 0, "认证密码：", self.voice_auth_password_var)
        self._field(form, 1, 1, "代理服务器：", self.voice_proxy_server_var)
        self._field(form, 1, 2, "代理端口：", self.voice_proxy_port_var)
        self._field(form, 1, 3, "出站代理：", self.voice_outbound_proxy_var)
        self._field(form, 2, 0, "出站代理端口：", self.voice_outbound_proxy_port_var)
        self._field(form, 2, 1, "注册服务器：", self.voice_registrar_server_var)
        self._field(form, 2, 2, "注册服务器端口：", self.voice_registrar_server_port_var)
        self._field(form, 2, 3, "DTMF：", self.voice_dtmf_method_var, values=("RFC2833", "InBand", "SIPINFO"))
        self._field(form, 3, 0, "注册有效期：", self.voice_register_expires_var)
        self._field(form, 3, 1, "SIP 模式：", self.voice_sip_mode_var, values=("SIP", "UDP", "TCP", "TLS"))
        self._field(form, 3, 2, "DigitMap：", self.voice_digit_map_var, width=24)
        codec_values = tuple(sorted(VOICE_CODEC_OPTIONS))
        for index, variable in enumerate(self.voice_codec_vars):
            self._field(form, 4 + index // 4, index % 4, f"编码 {index + 1}：", variable, values=codec_values)
        self._advanced_target_area(
            tab, "voice", start_text="执行语音配置", on_refresh=on_refresh,
            on_start=on_start, on_stop=on_stop, on_close=on_close,
        )

    def _build_tr069_tab(self, on_refresh, on_start, on_stop, on_close) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="TR069配置")
        ttk.Label(
            tab,
            text=(
                "批量配置 ManagementServer 参数并回读；可选在配置成功后触发一次手动 Inform；"
                "UBUS 凭据和并行数与 Telnet 配置页共享。"
            ),
            style="Muted.TLabel",
        ).pack(fill="x", anchor="w", pady=(0, 6))
        form = ttk.LabelFrame(tab, text="TR069 参数", padding=8)
        form.pack(fill="x")
        self.tr069_acs_url_var = StringVar(value="http://172.18.18.101:7547/ACS-server/ACS")
        self.tr069_acs_username_var = StringVar(value="hgw")
        self.tr069_acs_password_var = StringVar(value="hgw")
        self.tr069_periodic_enabled_var = BooleanVar(value=True)
        self.tr069_interval_var = StringVar(value="86400")
        self.tr069_connection_request_enabled_var = BooleanVar(value=True)
        self.tr069_connection_username_var = StringVar(value="itms")
        self.tr069_connection_password_var = StringVar(value="itms")
        self.tr069_certificate_enabled_var = BooleanVar(value=False)
        self.tr069_manual_inform_var = BooleanVar(value=False)
        self._field(form, 0, 0, "ACS URL：", self.tr069_acs_url_var, width=35)
        self._field(form, 0, 1, "ACS 账号：", self.tr069_acs_username_var)
        self._field(form, 0, 2, "ACS 密码：", self.tr069_acs_password_var)
        periodic = self._native_checkbutton(
            form, text="启用周期 Inform", variable=self.tr069_periodic_enabled_var
        )
        periodic.grid(row=0, column=6, columnspan=2, sticky="w", padx=4, pady=3)
        self._field(form, 1, 0, "Inform 间隔(秒)：", self.tr069_interval_var)
        conn_enable = self._native_checkbutton(
            form,
            text="启用 HTTP 连接请求",
            variable=self.tr069_connection_request_enabled_var,
        )
        conn_enable.grid(row=1, column=2, columnspan=2, sticky="w", padx=4, pady=3)
        self._field(form, 1, 2, "连接请求账号：", self.tr069_connection_username_var)
        self._field(form, 1, 3, "连接请求密码：", self.tr069_connection_password_var)
        cert = self._native_checkbutton(
            form, text="启用证书", variable=self.tr069_certificate_enabled_var
        )
        cert.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        manual = self._native_checkbutton(
            form, text="配置后手动 Inform", variable=self.tr069_manual_inform_var
        )
        manual.grid(row=2, column=2, columnspan=2, sticky="w", padx=4, pady=3)
        self._advanced_target_area(
            tab, "tr069", start_text="执行 TR069 配置", on_refresh=on_refresh,
            on_start=on_start, on_stop=on_stop, on_close=on_close,
        )

    def wan_settings(self) -> DutWanSettings:
        return DutWanSettings(
            operation={"新增": "add", "修改": "modify", "删除": "delete"}.get(self.wan_operation_var.get(), ""),
            connection_index=self.wan_index_var.get().strip(),
            mode={"路由": "router", "桥接": "bridge"}.get(self.wan_mode_var.get(), ""),
            service_type=self.wan_service_type_var.get().strip(), vlan_id=self.wan_vlan_id_var.get().strip(),
            vlan_priority=self.wan_vlan_priority_var.get().strip(), port_bind=self.wan_port_bind_var.get().strip(),
            mtu=self.wan_mtu_var.get().strip(), nat_enabled=bool(self.wan_nat_var.get()),
            access_type=self.wan_access_type_var.get().strip(),
            ip_protocol={"IPv4+IPv6（双栈）": "IPv4IPv6"}.get(self.wan_ip_protocol_var.get(), self.wan_ip_protocol_var.get()),
            ipv4_type={"DHCP": "Dynamic", "静态": "Static"}.get(self.wan_ipv4_type_var.get(), ""),
            ipv4_address=self.wan_ipv4_address_var.get().strip(), ipv4_netmask=self.wan_ipv4_netmask_var.get().strip(),
            ipv4_gateway=self.wan_ipv4_gateway_var.get().strip(), ipv4_primary_dns=self.wan_ipv4_primary_dns_var.get().strip(),
            ipv4_secondary_dns=self.wan_ipv4_secondary_dns_var.get().strip(),
            ipv6_type={"静态": "Static"}.get(self.wan_ipv6_type_var.get(), self.wan_ipv6_type_var.get()),
            ipv6_address=self.wan_ipv6_address_var.get().strip(), ipv6_prefix=self.wan_ipv6_prefix_var.get().strip(),
            ipv6_gateway=self.wan_ipv6_gateway_var.get().strip(), ipv6_primary_dns=self.wan_ipv6_primary_dns_var.get().strip(),
            ipv6_secondary_dns=self.wan_ipv6_secondary_dns_var.get().strip(),
            pppoe_username=self.wan_pppoe_username_var.get(), pppoe_password=self.wan_pppoe_password_var.get(),
        )

    def voice_settings(self) -> DutVoiceSettings:
        return DutVoiceSettings(
            line_index=self.voice_line_index_var.get().strip(), account_enabled=bool(self.voice_account_enabled_var.get()),
            display_name=self.voice_display_name_var.get(), auth_username=self.voice_auth_username_var.get(),
            auth_password=self.voice_auth_password_var.get(), proxy_server=self.voice_proxy_server_var.get().strip(),
            proxy_port=self.voice_proxy_port_var.get().strip(), outbound_proxy=self.voice_outbound_proxy_var.get().strip(),
            outbound_proxy_port=self.voice_outbound_proxy_port_var.get().strip(),
            registrar_server=self.voice_registrar_server_var.get().strip(),
            registrar_server_port=self.voice_registrar_server_port_var.get().strip(),
            dtmf_method=self.voice_dtmf_method_var.get(), register_expires=self.voice_register_expires_var.get().strip(),
            sip_mode=self.voice_sip_mode_var.get(), digit_map=self.voice_digit_map_var.get(),
            codecs=tuple(variable.get() for variable in self.voice_codec_vars),
        )

    def tr069_settings(self) -> DutTr069Settings:
        return DutTr069Settings(
            acs_url=self.tr069_acs_url_var.get().strip(), acs_username=self.tr069_acs_username_var.get(),
            acs_password=self.tr069_acs_password_var.get(),
            periodic_inform_enabled=bool(self.tr069_periodic_enabled_var.get()),
            periodic_inform_interval=self.tr069_interval_var.get().strip(),
            connection_request_enabled=bool(self.tr069_connection_request_enabled_var.get()),
            connection_request_username=self.tr069_connection_username_var.get(),
            connection_request_password=self.tr069_connection_password_var.get(),
            certificate_enabled=bool(self.tr069_certificate_enabled_var.get()),
            manual_inform=bool(self.tr069_manual_inform_var.get()),
        )

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
        request_list = list(requests)
        target_signature = tuple(
            (request.channel, request.vlan, request.bind_ip, request.device_host)
            for request in request_list
        )
        if target_signature != self._wan_target_signature:
            self.clear_wan_connections("目标 DUT 已变化，请重新查询现有 WAN。")
            self._wan_target_signature = target_signature
        for feature, tree in self._trees.items():
            for item in tree.get_children():
                tree.delete(item)
            rows = self._rows_by_feature[feature]
            rows.clear()
            for index, request in enumerate(request_list):
                status = errors_by_channel.get(request.channel, "配置完整，等待执行")
                row_id = tree.insert(
                    "", END,
                    values=(
                        request.channel, request.vlan or "未配置", request.adapter_alias or "未配置",
                        request.bind_ip or "未配置", request.device_host or "未配置", status,
                    ),
                )
                rows[request.channel or f"row-{index}"] = row_id
            self._summary_vars[feature].set(
                f"已加载 {len(request_list)} 台目标 DUT" if request_list else "主界面当前没有已勾选通道"
            )

    def mark_all_pending(self, feature: str = "telnet") -> None:
        tree = self._trees.get(feature, self.target_tree)
        for row_id in self._rows_by_feature.get(feature, self._row_by_channel).values():
            values = list(tree.item(row_id, "values"))
            values[-1] = "等待执行"
            tree.item(row_id, values=values)

    def update_result(
        self,
        result: DutTelnetEnableResult | DutAdvancedConfigResult | DutWanQueryResult,
        feature: str | None = None,
    ) -> None:
        resolved_feature = feature or getattr(result.request, "feature", "telnet")
        tree_feature = "wan" if resolved_feature == "wan_query" else resolved_feature
        tree = getattr(self, "_trees", {}).get(tree_feature, self.target_tree)
        rows = getattr(self, "_rows_by_feature", {}).get(tree_feature, self._row_by_channel)
        row_id = rows.get(result.request.channel)
        if row_id is None:
            return
        values = list(tree.item(row_id, "values"))
        if result.ok:
            if resolved_feature == "wan_query":
                values[-1] = f"成功：发现 {len(result.connection_names)} 个现有 WAN"
                tree.item(row_id, values=values)
                return
            success_text = {
                "telnet": "成功：Telnet 已开启并验证可用",
                "wan": "成功：WAN 操作完成",
                "voice": "成功：语音配置完成",
                "tr069": "成功：TR069 配置完成",
            }.get(resolved_feature, f"成功：{result.message}")
            values[-1] = success_text
        elif result.stage == "stopped":
            values[-1] = f"已停止：{result.message}"
        else:
            values[-1] = f"失败：{result.message}"
        tree.item(row_id, values=values)

    def set_summary(self, text: str, feature: str = "telnet") -> None:
        self._summary_vars.get(feature, self.summary_var).set(text)

    def set_running(self, running: bool, *, stopping: bool = False) -> None:
        input_state = "disabled" if running else "normal"
        self.username_entry.configure(state=input_state)
        self.password_entry.configure(state=input_state)
        self.parallel_spinbox.configure(state=input_state)
        for widget in self._input_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="disabled" if running else "readonly")
                else:
                    widget.configure(state=input_state)
            except Exception:
                continue
        for button in self._start_buttons.values():
            button.configure(state="disabled" if running else "normal")
        for button in self._stop_buttons:
            button.configure(state="disabled" if not running or stopping else "normal")
        if not running and hasattr(self, "wan_operation_var"):
            self._update_wan_form_visibility()
        if stopping:
            for summary_var in self._summary_vars.values():
                summary_var.set("正在停止：已运行任务将在安全点结束，尚未开始的 DUT 将跳过")


__all__ = [
    "DutConfigWindow",
    "WanFormRules",
    "normalize_wan_address_modes",
    "resolve_wan_form_rules",
]

"""DUT 配置窗口；仅负责界面展示和回调，不承载 UBUS 业务逻辑。"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, Checkbutton, END, StringVar, TclError, Text, Toplevel, ttk

from src.models import (
    DutAdvancedConfigResult,
    DutAdvancedQueryResult,
    DutTelnetEnableRequest,
    DutTelnetEnableResult,
    DutTelnetStatus,
    DutTr069Settings,
    DutVoiceSettings,
    DutWifiSettings,
    DutWanConnectionInfo,
    DutWanQueryResult,
    DutWanSettings,
)
from src.services.dut_config_service import (
    DEFAULT_DUT_PARALLEL_COUNT,
    MAX_DUT_PARALLEL_COUNT,
)
from src.services.dut_advanced_config_service import (
    VOICE_CODEC_OPTIONS,
    VOICE_DTMF_OPTIONS,
    VOICE_SIP_MODE_OPTIONS,
    WIFI_BANDWIDTH_OPTIONS,
    WIFI_MODE_OPTIONS,
    WIFI_SECURITY_MODE_OPTIONS,
)
from src.ui.window_paint import (
    center_toplevel_on_parent,
    schedule_toplevel_client_refresh,
)


DUT_CHECK_BACKGROUND = "#ffffff"
DUT_CHECK_FOREGROUND = "#17202a"
DUT_TARGET_SELECTED_MARK = "☑"
DUT_TARGET_UNSELECTED_MARK = "☐"
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
WAN_LAN_PORTS = tuple(range(1, 9))
WAN_LAN_PORT_MASK = sum(1 << (port - 1) for port in WAN_LAN_PORTS)
WIFI_SSID_INDEX_OPTIONS = tuple(str(index) for index in range(1, 9))
WIFI_CHANNEL_OPTIONS = {
    "2.4G": ("auto", *(str(channel) for channel in range(1, 14))),
    "5G": (
        "auto", "36", "40", "44", "48", "52", "56", "60", "64",
        "100", "104", "108", "112", "116", "120", "124", "128",
        "132", "136", "140", "144", "149", "153", "157", "161", "165",
    ),
}
WIFI_TRANSMIT_POWER_OPTIONS = ("20", "40", "60", "80", "100")
DUT_CONFIG_UI_STATE_PATH = Path.home() / ".aouxue_dut_config.json"
DUT_CONFIG_DEFAULT_WIDTH = 1530
DUT_CONFIG_DEFAULT_HEIGHT = 880
DUT_CONFIG_MIN_WIDTH = 1530
DUT_CONFIG_MIN_HEIGHT = 880
DUT_CURRENT_STATUS_FEATURES = (
    "telnet", "wan", "wifi_2g", "wifi_5g", "voice", "tr069",
)
DUT_CURRENT_STATUS_DEFAULT_HEIGHT = 4
DUT_CURRENT_STATUS_MIN_HEIGHT = 2
DUT_CURRENT_STATUS_MAX_HEIGHT = 16
DUT_CURRENT_STATUS_DRAG_PIXELS_PER_ROW = 18
DUT_CURRENT_STATUS_BOTTOM_GUARD_PIXELS = 0


def reconcile_dut_target_selection(
    previous_selected: Iterable[str],
    previous_targets: Iterable[str],
    current_targets: Iterable[str],
) -> tuple[str, ...]:
    """保留仍存在目标的手动选择，并默认选中新加入的主界面目标。"""
    selected = set(previous_selected)
    known = set(previous_targets)
    current = tuple(dict.fromkeys(current_targets))
    return tuple(
        channel for channel in current if channel in selected or channel not in known
    )


def _load_dut_config_ui_state(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_dut_config_ui_state(path: Path, payload: Mapping[str, object]) -> bool:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def clamp_dut_current_status_height(value: object) -> int:
    """把持久化或拖动产生的高度收敛到可用文本行范围。"""
    try:
        height = int(value)
    except (TypeError, ValueError):
        return DUT_CURRENT_STATUS_DEFAULT_HEIGHT
    return max(DUT_CURRENT_STATUS_MIN_HEIGHT, min(DUT_CURRENT_STATUS_MAX_HEIGHT, height))


def load_dut_current_status_heights(path: Path) -> dict[str, int]:
    """读取每个 DUT Tab 的当前状态高度；损坏状态安全回退默认值。"""
    payload = _load_dut_config_ui_state(path)
    values = payload.get("current_status_heights") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return {}
    return {
        feature: clamp_dut_current_status_height(values[feature])
        for feature in DUT_CURRENT_STATUS_FEATURES
        if feature in values
    }


def save_dut_current_status_heights(
    path: Path, heights: Mapping[str, object]
) -> bool:
    """原子保存当前状态高度；UI 状态写失败不阻止窗口关闭。"""
    payload = _load_dut_config_ui_state(path)
    payload["current_status_heights"] = {
        feature: clamp_dut_current_status_height(heights[feature])
        for feature in DUT_CURRENT_STATUS_FEATURES
        if feature in heights
    }
    return _save_dut_config_ui_state(path, payload)


def clamp_dut_window_size(
    width: object,
    height: object,
    *,
    screen_width: object | None = None,
    screen_height: object | None = None,
) -> tuple[int, int]:
    """收敛DUT窗口宽高，避免损坏或跨屏幕状态造成不可用窗口。"""
    try:
        safe_width = int(width)
    except (TypeError, ValueError):
        safe_width = DUT_CONFIG_DEFAULT_WIDTH
    try:
        safe_height = int(height)
    except (TypeError, ValueError):
        safe_height = DUT_CONFIG_DEFAULT_HEIGHT
    safe_width = max(DUT_CONFIG_MIN_WIDTH, safe_width)
    safe_height = max(DUT_CONFIG_MIN_HEIGHT, safe_height)
    try:
        maximum_width = max(DUT_CONFIG_MIN_WIDTH, int(screen_width))
    except (TypeError, ValueError):
        maximum_width = safe_width
    try:
        maximum_height = max(DUT_CONFIG_MIN_HEIGHT, int(screen_height))
    except (TypeError, ValueError):
        maximum_height = safe_height
    return min(safe_width, maximum_width), min(safe_height, maximum_height)


def load_dut_window_size(
    path: Path, *, screen_width: object, screen_height: object
) -> tuple[int, int]:
    """读取上次关闭时的DUT窗口宽高，并适配当前屏幕。"""
    payload = _load_dut_config_ui_state(path)
    value = payload.get("window_size")
    if not isinstance(value, dict):
        value = {}
    return clamp_dut_window_size(
        value.get("width", DUT_CONFIG_DEFAULT_WIDTH),
        value.get("height", DUT_CONFIG_DEFAULT_HEIGHT),
        screen_width=screen_width,
        screen_height=screen_height,
    )


def save_dut_window_size(path: Path, width: object, height: object) -> bool:
    """保存DUT窗口宽高，同时保留同一文件中的状态区高度。"""
    safe_width, safe_height = clamp_dut_window_size(width, height)
    payload = _load_dut_config_ui_state(path)
    payload["window_size"] = {"width": safe_width, "height": safe_height}
    return _save_dut_config_ui_state(path, payload)


def _port_bind_mask_value(value: str) -> int:
    """把查询值或旧组合文本转换为非负位掩码；无效值按 0 处理。"""
    try:
        parts = [part.strip() for part in str(value).split("&&")]
        if not parts or any(not part for part in parts):
            return 0
        mask = sum(int(part) for part in parts)
        return mask if mask >= 0 else 0
    except (TypeError, ValueError):
        return 0


def wan_lan_ports_from_port_bind(value: str) -> tuple[int, ...]:
    """把 ``PortBind`` 位掩码转换为界面应勾选的 LAN1–LAN8。"""
    mask = _port_bind_mask_value(value)
    return tuple(port for port in WAN_LAN_PORTS if mask & (1 << (port - 1)))


def wan_port_bind_from_lan_ports(
    ports: Iterable[int], *, preserved_mask: int = 0
) -> str:
    """把已勾选 LAN 口转换为 UBUS 位掩码，并保留不在界面展示的旧绑定。"""
    mask = max(0, int(preserved_mask))
    for port in ports:
        if port in WAN_LAN_PORTS:
            mask |= 1 << (port - 1)
    return str(mask)


def voice_status_form_values(settings: DutVoiceSettings) -> dict[str, object]:
    """把只读语音状态映射为当前表单值。"""
    return {
        "line_index": settings.line_index,
        "account_enabled": settings.account_enabled,
        "display_name": settings.display_name,
        "auth_username": settings.auth_username,
        "auth_password": settings.auth_password,
        "proxy_server": settings.proxy_server,
        "proxy_port": settings.proxy_port,
        "outbound_proxy": settings.outbound_proxy,
        "outbound_proxy_port": settings.outbound_proxy_port,
        "registrar_server": settings.registrar_server,
        "registrar_server_port": settings.registrar_server_port,
        "dtmf_method": settings.dtmf_method,
        "register_expires": settings.register_expires,
        "sip_mode": settings.sip_mode,
        "digit_map": settings.digit_map,
        "codecs": settings.codecs,
    }


def tr069_status_form_values(settings: DutTr069Settings) -> dict[str, object]:
    """把只读TR069状态映射为当前表单值，不改动手动Inform动作选项。"""
    return {
        "acs_url": settings.acs_url,
        "acs_username": settings.acs_username,
        "acs_password": settings.acs_password,
        "periodic_inform_enabled": settings.periodic_inform_enabled,
        "periodic_inform_interval": settings.periodic_inform_interval,
        "connection_request_enabled": settings.connection_request_enabled,
        "connection_request_username": settings.connection_request_username,
        "connection_request_password": settings.connection_request_password,
        "certificate_enabled": settings.certificate_enabled,
    }


def wifi_status_form_values(settings: DutWifiSettings) -> dict[str, object]:
    """把只读 WiFi 状态映射为当前频段表单值。"""
    return {
        "ssid_index": settings.ssid_index,
        "ssid": settings.ssid,
        "password": settings.password,
        "channel": settings.channel,
        "channel_bandwidth": settings.channel_bandwidth,
        "dual_band_enabled": settings.dual_band_enabled,
        "enabled": settings.enabled,
        "hidden": settings.hidden,
        "security_mode": settings.security_mode,
        "operating_mode": settings.operating_mode,
        "transmit_power": settings.transmit_power,
        "max_associations": settings.max_associations,
        "wmm_enabled": settings.wmm_enabled,
    }


def voice_choice_options(settings: DutVoiceSettings) -> dict[str, tuple[str, ...]]:
    """按 DUT 查询能力生成语音只读下拉候选；缺能力字段时兼容兜底。"""

    current_by_key = {
        "dtmf_method": (settings.dtmf_method,),
        "sip_mode": (settings.sip_mode,),
        "codecs": settings.codecs,
    }
    supported_by_key = {
        "dtmf_method": settings.supported_dtmf_methods,
        "sip_mode": settings.supported_sip_modes,
        "codecs": settings.supported_codecs,
    }
    fallback_by_key = {
        "dtmf_method": VOICE_DTMF_OPTIONS,
        "sip_mode": VOICE_SIP_MODE_OPTIONS,
        "codecs": tuple(sorted(VOICE_CODEC_OPTIONS)),
    }
    options_by_key: dict[str, tuple[str, ...]] = {}
    for key in supported_by_key:
        options = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (supported_by_key[key] or fallback_by_key[key])
                if str(value).strip()
            )
        )
        current_values = tuple(
            str(value).strip() for value in current_by_key[key] if str(value).strip()
        )
        missing_current = tuple(value for value in current_values if value not in options)
        options_by_key[key] = tuple(dict.fromkeys((*missing_current, *options)))
    return options_by_key


def wifi_choice_options(settings: DutWifiSettings) -> dict[str, tuple[str, ...]]:
    """按 DUT 查询能力生成 WiFi 只读下拉候选；缺能力字段时使用兼容兜底。"""

    band = settings.band if settings.band in WIFI_CHANNEL_OPTIONS else "2.4G"
    supported_by_key = {
        "security_mode": settings.supported_security_modes,
        "channel": settings.supported_channels,
        "channel_bandwidth": settings.supported_bandwidths,
        "operating_mode": settings.supported_modes,
        "transmit_power": settings.supported_transmit_powers,
    }
    fallback_by_key = {
        "security_mode": WIFI_SECURITY_MODE_OPTIONS,
        "channel": WIFI_CHANNEL_OPTIONS[band],
        "channel_bandwidth": WIFI_BANDWIDTH_OPTIONS[band],
        "operating_mode": WIFI_MODE_OPTIONS[band],
        "transmit_power": WIFI_TRANSMIT_POWER_OPTIONS,
    }
    current_by_key = {
        "security_mode": settings.security_mode,
        "channel": settings.channel,
        "channel_bandwidth": settings.channel_bandwidth,
        "operating_mode": settings.operating_mode,
        "transmit_power": settings.transmit_power,
    }
    options_by_key: dict[str, tuple[str, ...]] = {}
    for key in supported_by_key:
        options = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (supported_by_key[key] or fallback_by_key[key])
                if str(value).strip()
            )
        )
        current = str(current_by_key[key]).strip()
        if current and current not in options:
            options = (current, *options)
        options_by_key[key] = options
    return options_by_key


@dataclass(frozen=True)
class WanFormRules:
    """WAN 当前选择对应的可见字段；不包含任何 UBUS 业务执行。"""

    show_index: bool
    show_config: bool
    show_router: bool
    show_pppoe_credentials: bool
    show_multicast_vlan: bool
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
    service_type: str = "",
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
        show_multicast_vlan=show_config and service_type.strip().upper() == "IPTV",
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
        "multicast_vlan_id": info.multicast_vlan_id,
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
        on_query_telnet: Callable[[], None],
        on_start_wan: Callable[[], None],
        on_query_wan: Callable[[], None],
        on_query_voice: Callable[[], None],
        on_query_tr069: Callable[[], None],
        on_start_voice: Callable[[], None],
        on_start_tr069: Callable[[], None],
        on_start_wifi_2g: Callable[[], None],
        on_query_wifi_2g: Callable[[], None],
        on_start_wifi_5g: Callable[[], None],
        on_query_wifi_5g: Callable[[], None],
        on_stop: Callable[[], None],
        on_close: Callable[[], None],
        on_first_paint_refresh: Callable[[], None] | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._state_path = state_path or DUT_CONFIG_UI_STATE_PATH
        self.window = Toplevel(master)
        self.window.title("DUT配置")
        window_width, window_height = load_dut_window_size(
            self._state_path,
            screen_width=self.window.winfo_screenwidth(),
            screen_height=self.window.winfo_screenheight(),
        )
        self.window.geometry(f"{window_width}x{window_height}")
        self.window.minsize(DUT_CONFIG_MIN_WIDTH, DUT_CONFIG_MIN_HEIGHT)
        self.window.protocol("WM_DELETE_WINDOW", on_close)

        self.username_var = username_var
        self.password_var = password_var
        self.parallel_count_var = StringVar(value=str(DEFAULT_DUT_PARALLEL_COUNT))
        self.summary_var = StringVar(value="尚未加载目标 DUT")
        self._row_by_channel: dict[str, str] = {}
        self._trees: dict[str, ttk.Treeview] = {}
        self._rows_by_feature: dict[str, dict[str, str]] = {}
        self._target_channels: tuple[str, ...] = ()
        self._selected_target_channels: set[str] = set()
        self._target_errors_by_channel: dict[str, str] = {}
        self._running = False
        self._summary_vars: dict[str, StringVar] = {"telnet": self.summary_var}
        self._input_widgets: list = []
        self._field_groups: dict[str, tuple[object, object]] = {}
        self._start_buttons: dict[str, ttk.Button] = {}
        self._stop_buttons: list[ttk.Button] = []
        self._current_status_texts: dict[str, Text] = {}
        self._current_status_resize_bars: dict[str, ttk.Label] = {}
        self._current_status_drag: dict[str, tuple[int, int]] = {}
        self._current_status_tabs: dict[str, object] = {}
        self._current_status_action_frames: dict[str, ttk.Frame] = {}
        self._current_status_bottom_areas: dict[str, ttk.Frame] = {}
        self._current_status_heights = load_dut_current_status_heights(
            self._state_path
        )
        self._wifi_vars: dict[str, dict[str, StringVar | BooleanVar]] = {}
        self._wifi_password_groups: dict[str, tuple[object, object]] = {}
        self._wifi_choice_widgets: dict[str, dict[str, ttk.Combobox]] = {}
        self._wifi_supported_options: dict[str, dict[str, tuple[str, ...]]] = {}
        self._voice_choice_widgets: dict[str, object] = {}
        self._voice_supported_options: dict[str, tuple[str, ...]] = {}
        self._tr069_capability_widgets: dict[str, object] = {}
        self._tr069_supported_fields: tuple[str, ...] = ()
        self._capability_disabled_widgets: set[object] = set()
        self.wifi_dual_band_var = BooleanVar(value=False)

        outer = ttk.Frame(self.window, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="DUT配置", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "主界面已勾选通道作为候选；在下方目标表再次勾选本次需要配置或查询的 DUT。"
            ),
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
                "目标表内可再次勾选本次范围；通过 UBUS 开启 Telnet，并从该 VLAN 源 IP 验证 TCP 23 端口。"
            ),
            style="Muted.TLabel",
            wraplength=850,
            justify="left",
        ).pack(fill="x", anchor="w", pady=(0, 10))

        self._build_current_status_area(
            telnet_tab, "telnet", "尚未查询当前Telnet状态。"
        )

        table_frame = ttk.Frame(telnet_tab)
        table_frame.pack(fill="both", expand=True)
        columns = (
            "selected", "channel", "vlan", "adapter", "bind_ip", "device_host", "status"
        )
        self.target_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=13
        )
        headings = {
            "selected": "选择",
            "channel": "通道",
            "vlan": "VLAN",
            "adapter": "网卡",
            "bind_ip": "PC 静态 IP",
            "device_host": "样机管理 IP",
            "status": "状态",
        }
        widths = {
            "selected": 55,
            "channel": 80,
            "vlan": 85,
            "adapter": 135,
            "bind_ip": 120,
            "device_host": 120,
            "status": 300,
        }
        for column in columns:
            self.target_tree.heading(column, text=headings[column])
            self.target_tree.column(
                column,
                width=widths[column],
                anchor="center" if column == "selected" else "w",
                stretch=column == "status",
            )
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.target_tree.yview)
        self.target_tree.configure(yscrollcommand=scrollbar.set)
        self.target_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_target_tree_selection(self.target_tree)

        footer = ttk.Frame(telnet_tab)
        self._pack_protected_bottom_area(telnet_tab, footer)
        self._current_status_bottom_areas["telnet"] = footer
        ttk.Label(footer, textvariable=self.summary_var, style="Muted.TLabel").pack(
            fill="x", anchor="w", pady=(8, 8)
        )
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self._current_status_action_frames["telnet"] = actions
        self.refresh_button = ttk.Button(
            actions, text="刷新目标", command=on_refresh, style="Secondary.TButton"
        )
        self.refresh_button.pack(side="left")
        self.select_all_button = ttk.Button(
            actions, text="全选", command=self.select_all_targets, style="Secondary.TButton"
        )
        self.select_all_button.pack(side="left", padx=(8, 0))
        self.clear_targets_button = ttk.Button(
            actions, text="清除", command=self.clear_all_targets, style="Secondary.TButton"
        )
        self.clear_targets_button.pack(side="left", padx=(8, 0))
        self.telnet_query_button = ttk.Button(
            actions,
            text="查询当前Telnet",
            command=on_query_telnet,
            style="Secondary.TButton",
        )
        self.telnet_query_button.pack(side="left", padx=(8, 0))
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
            [
                self.username_entry,
                self.password_entry,
                self.parallel_spinbox,
                self.refresh_button,
                self.select_all_button,
                self.clear_targets_button,
                self.telnet_query_button,
            ]
        )
        self._start_buttons["telnet"] = self.start_button
        self._stop_buttons.append(self.stop_button)

        self._build_wan_tab(on_refresh, on_start_wan, on_query_wan, on_stop, on_close)
        self._build_wifi_tab(
            "2.4G", "wifi_2g", on_refresh, on_start_wifi_2g,
            on_query_wifi_2g, on_stop, on_close,
        )
        self._build_wifi_tab(
            "5G", "wifi_5g", on_refresh, on_start_wifi_5g,
            on_query_wifi_5g, on_stop, on_close,
        )
        self._build_voice_tab(
            on_refresh, on_start_voice, on_query_voice, on_stop, on_close
        )
        self._build_tr069_tab(
            on_refresh, on_start_tr069, on_query_tr069, on_stop, on_close
        )

        self.notebook.bind(
            "<<NotebookTabChanged>>", self._on_dut_tab_changed, add="+"
        )
        center_toplevel_on_parent(
            self.window,
            master,
            window_width=window_width,
            window_height=window_height,
        )
        self.window.after_idle(self._constrain_selected_current_status_height)
        schedule_toplevel_client_refresh(
            self.window,
            on_first_refresh=on_first_paint_refresh,
        )

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

    def _native_checkbutton(
        self,
        parent,
        *,
        text: str,
        variable: BooleanVar,
        command: Callable[[], None] | None = None,
    ) -> Checkbutton:
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
            command=command,
        )
        self._input_widgets.append(widget)
        return widget

    @staticmethod
    def _pack_protected_bottom_area(tab, bottom_area) -> None:
        """优先为底部提示和按钮预留空间，避免可变高度组件将其裁切。"""
        existing_slaves = tab.pack_slaves()
        if existing_slaves:
            bottom_area.pack(
                side="bottom", fill="x", before=existing_slaves[0]
            )
            return
        bottom_area.pack(side="bottom", fill="x")

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
        query_text: str | None = None,
        on_query: Callable[[], None] | None = None,
    ) -> None:
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, pady=(8, 0))
        columns = (
            "selected", "channel", "vlan", "adapter", "bind_ip", "device_host", "status"
        )
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=6)
        headings = {
            "selected": "选择",
            "channel": "通道", "vlan": "管理 VLAN", "adapter": "网卡",
            "bind_ip": "PC 静态 IP", "device_host": "样机管理 IP", "status": "状态",
        }
        widths = {
            "selected": 55,
            "channel": 75, "vlan": 90, "adapter": 125, "bind_ip": 115,
            "device_host": 115, "status": 330,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(
                column,
                width=widths[column],
                anchor="center" if column == "selected" else "w",
                stretch=column == "status",
            )
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_target_tree_selection(tree)
        summary_var = StringVar(value="尚未加载目标 DUT")
        footer = ttk.Frame(tab)
        self._pack_protected_bottom_area(tab, footer)
        self._current_status_bottom_areas[feature] = footer
        ttk.Label(footer, textvariable=summary_var, style="Muted.TLabel").pack(
            fill="x", anchor="w", pady=(6, 6)
        )
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self._current_status_action_frames[feature] = actions
        refresh = ttk.Button(actions, text="刷新目标", command=on_refresh, style="Secondary.TButton")
        refresh.pack(side="left")
        select_all = ttk.Button(
            actions, text="全选", command=self.select_all_targets, style="Secondary.TButton"
        )
        select_all.pack(side="left", padx=(8, 0))
        clear_targets = ttk.Button(
            actions, text="清除", command=self.clear_all_targets, style="Secondary.TButton"
        )
        clear_targets.pack(side="left", padx=(8, 0))
        if query_text and on_query is not None:
            query = ttk.Button(
                actions, text=query_text, command=on_query, style="Secondary.TButton"
            )
            query.pack(side="left", padx=(8, 0))
            self._input_widgets.append(query)
        ttk.Button(actions, text="关闭", command=on_close, style="Secondary.TButton").pack(side="right")
        start = ttk.Button(actions, text=start_text, command=on_start, style="Primary.TButton")
        start.pack(side="right", padx=(0, 8))
        stop = ttk.Button(actions, text="停止", command=on_stop, state="disabled", style="Secondary.TButton")
        stop.pack(side="right", padx=(0, 8))
        self._trees[feature] = tree
        self._rows_by_feature[feature] = {}
        self._summary_vars[feature] = summary_var
        self._input_widgets.extend((refresh, select_all, clear_targets))
        self._start_buttons[feature] = start
        self._stop_buttons.append(stop)

    def _build_current_status_area(self, tab, feature: str, initial_text: str) -> None:
        self._current_status_tabs[feature] = tab
        frame = ttk.LabelFrame(tab, text="当前状态", padding=6)
        frame.pack(fill="x", pady=(8, 0))
        content = ttk.Frame(frame)
        content.pack(fill="x")
        height = self._current_status_heights.get(
            feature, DUT_CURRENT_STATUS_DEFAULT_HEIGHT
        )
        text = Text(
            content,
            height=height,
            wrap="word",
            relief="flat",
            borderwidth=0,
            background=DUT_CHECK_BACKGROUND,
            foreground=DUT_CHECK_FOREGROUND,
        )
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")
        resize_bar = ttk.Label(
            frame,
            text="↕ 拖动调整当前状态高度",
            anchor="center",
            cursor="sb_v_double_arrow",
            style="Muted.TLabel",
        )
        resize_bar.pack(fill="x", pady=(3, 0))
        resize_bar.bind(
            "<ButtonPress-1>",
            lambda event, selected=feature: self._begin_current_status_resize(
                selected, event.y_root
            ),
        )
        resize_bar.bind(
            "<B1-Motion>",
            lambda event, selected=feature: self._drag_current_status_resize(
                selected, event.y_root
            ),
        )
        resize_bar.bind(
            "<ButtonRelease-1>",
            lambda _event, selected=feature: self._finish_current_status_resize(
                selected
            ),
        )
        self._current_status_texts[feature] = text
        self._current_status_resize_bars[feature] = resize_bar
        self.clear_current_status(feature, initial_text)

    def _begin_current_status_resize(self, feature: str, y_root: int) -> str:
        text = self._current_status_texts.get(feature)
        if text is not None:
            height = clamp_dut_current_status_height(text.cget("height"))
            self._current_status_drag[feature] = (int(y_root), height)
        return "break"

    def _drag_current_status_resize(self, feature: str, y_root: int) -> str:
        text = self._current_status_texts.get(feature)
        origin = self._current_status_drag.get(feature)
        if text is None or origin is None:
            return "break"
        start_y, start_height = origin
        row_delta = round(
            (int(y_root) - start_y) / DUT_CURRENT_STATUS_DRAG_PIXELS_PER_ROW
        )
        height = clamp_dut_current_status_height(start_height + row_delta)
        effective_height = self._fit_current_status_height(feature, height)
        self._current_status_heights[feature] = effective_height
        return "break"

    def _fit_current_status_height(self, feature: str, requested_height: object) -> int:
        """限制状态区高度，确保当前 Tab 的底部操作按钮仍完整可见。"""
        requested = clamp_dut_current_status_height(requested_height)
        text = self._current_status_texts.get(feature)
        if text is None:
            return requested

        # 窗口尚未完成构建时没有可用的几何信息，先保留行数钳制。
        tabs = getattr(self, "_current_status_tabs", {})
        action_frames = getattr(self, "_current_status_action_frames", {})
        if feature not in tabs or feature not in action_frames:
            text.configure(height=requested)
            return requested

        for candidate in range(requested, DUT_CURRENT_STATUS_MIN_HEIGHT - 1, -1):
            text.configure(height=candidate)
            try:
                self.window.update_idletasks()
            except (AttributeError, TclError):
                return candidate
            visibility = self._bottom_actions_fully_visible(feature)
            if visibility is None or visibility:
                return candidate

        text.configure(height=DUT_CURRENT_STATUS_MIN_HEIGHT)
        return DUT_CURRENT_STATUS_MIN_HEIGHT

    def _bottom_actions_fully_visible(self, feature: str) -> bool | None:
        """返回按钮栏是否完整位于 Tab 和窗口内；几何信息无效时返回 None。"""
        tab = getattr(self, "_current_status_tabs", {}).get(feature)
        actions = getattr(self, "_current_status_action_frames", {}).get(feature)
        bottom_area = getattr(self, "_current_status_bottom_areas", {}).get(
            feature, actions
        )
        if tab is None or actions is None or bottom_area is None:
            return None
        try:
            if (
                not tab.winfo_ismapped()
                or not bottom_area.winfo_ismapped()
                or not actions.winfo_ismapped()
            ):
                return None
            tab_top = int(tab.winfo_rooty())
            tab_bottom = tab_top + int(tab.winfo_height())
            window_bottom = int(self.window.winfo_rooty()) + int(
                self.window.winfo_height()
            )
            actions_top = int(actions.winfo_rooty())
            actions_height = int(actions.winfo_height())
            actions_requested_height = int(actions.winfo_reqheight())
            actions_bottom = actions_top + actions_height
            bottom_area_top = int(bottom_area.winfo_rooty())
            bottom_area_height = int(bottom_area.winfo_height())
            bottom_area_requested_height = int(bottom_area.winfo_reqheight())
            bottom_area_bottom = bottom_area_top + bottom_area_height
        except (AttributeError, TclError, TypeError, ValueError):
            return None
        if tab_bottom <= tab_top or actions_bottom <= actions_top:
            return None
        if (
            actions_height < actions_requested_height
            or bottom_area_height < bottom_area_requested_height
        ):
            return False
        visible_bottom = min(tab_bottom, window_bottom)
        guard = DUT_CURRENT_STATUS_BOTTOM_GUARD_PIXELS
        return (
            bottom_area_top >= tab_top
            and bottom_area_bottom <= visible_bottom - guard
            and actions_top >= bottom_area_top
            and actions_bottom <= bottom_area_bottom
        )

    def _on_dut_tab_changed(self, _event=None) -> None:
        try:
            self.window.after_idle(self._constrain_selected_current_status_height)
        except TclError:
            return

    def _constrain_selected_current_status_height(self) -> None:
        try:
            selected_tab = str(self.notebook.select())
        except (AttributeError, TclError):
            return
        for feature, tab in self._current_status_tabs.items():
            if str(tab) != selected_tab:
                continue
            text = self._current_status_texts.get(feature)
            if text is None:
                return
            before = clamp_dut_current_status_height(text.cget("height"))
            effective = self._fit_current_status_height(feature, before)
            self._current_status_heights[feature] = effective
            if effective != before:
                save_dut_current_status_heights(
                    self._state_path, self._current_status_heights
                )
            return

    def _finish_current_status_resize(self, feature: str) -> str:
        self._current_status_drag.pop(feature, None)
        self._remember_current_status_heights()
        save_dut_current_status_heights(
            self._state_path, self._current_status_heights
        )
        return "break"

    def _remember_current_status_heights(self) -> None:
        for feature, text in self._current_status_texts.items():
            try:
                self._current_status_heights[feature] = (
                    clamp_dut_current_status_height(text.cget("height"))
                )
            except (TclError, TypeError, ValueError):
                continue

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
        self.wan_multicast_vlan_id_var = StringVar(value="")
        self.wan_vlan_priority_var = StringVar(value="0")
        self.wan_port_bind_var = StringVar(value="0")
        self.wan_lan_port_vars = tuple(BooleanVar(value=False) for _port in WAN_LAN_PORTS)
        self._wan_non_lan_port_bind_mask = 0
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
        port_bind_label = ttk.Label(form, text="端口绑定：", anchor="w")
        port_bind_label.grid(row=1, column=4, sticky="w", padx=(4, 4), pady=3)
        port_bind_holder = ttk.Frame(form)
        port_bind_holder.grid(row=1, column=5, sticky="ew", padx=(0, 8), pady=3)
        for index, (port, variable) in enumerate(zip(WAN_LAN_PORTS, self.wan_lan_port_vars)):
            option = self._native_checkbutton(
                port_bind_holder,
                text=f"LAN{port}",
                variable=variable,
                command=self._sync_wan_port_bind_from_checks,
            )
            option.grid(
                row=index // 4,
                column=index % 4,
                sticky="w",
                padx=(0, 5),
                pady=0,
            )
        form.columnconfigure(5, weight=1)
        self._field_groups["wan_port_bind"] = (port_bind_label, port_bind_holder)
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
        self._field(
            form, 7, 0, "组播 VLAN ID：", self.wan_multicast_vlan_id_var,
            field_key="wan_multicast_vlan_id",
        )
        self.wan_rule_hint_var = StringVar(value="")
        ttk.Label(
            form, textvariable=self.wan_rule_hint_var, style="Muted.TLabel",
            justify="left", wraplength=1050,
        ).grid(row=8, column=0, columnspan=8, sticky="w", padx=4, pady=(5, 0))
        self.wan_query_status_var = StringVar(
            value="修改/删除时请先点击“查询现有 WAN”，再从下拉列表选择。"
        )
        ttk.Label(
            form,
            textvariable=self.wan_query_status_var,
            style="Muted.TLabel",
            justify="left",
            wraplength=1050,
        ).grid(row=9, column=0, columnspan=8, sticky="w", padx=4, pady=(2, 0))
        self._wan_target_signature: tuple[tuple[str, ...], ...] = ()
        self._wan_connection_details: dict[str, DutWanConnectionInfo] = {}
        self._updating_wan_form = False
        self._last_wan_access_type = ""
        for variable, changed in (
            (self.wan_operation_var, "operation"),
            (self.wan_mode_var, "mode"),
            (self.wan_service_type_var, "service_type"),
            (self.wan_access_type_var, "access_type"),
            (self.wan_ip_protocol_var, "ip_protocol"),
            (self.wan_ipv4_type_var, "ipv4_type"),
            (self.wan_ipv6_type_var, "ipv6_type"),
        ):
            variable.trace_add("write", lambda *_args, source=changed: self._update_wan_form_visibility(source))
        self._update_wan_form_visibility("initial")
        self._build_current_status_area(
            tab, "wan", "尚未查询；点击“查询现有 WAN”获取每台当前连接状态。"
        )
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

    def set_wan_current_status_results(
        self, results: Iterable[DutWanQueryResult]
    ) -> None:
        """展示现有WAN查询已经返回的逐台连接摘要，不重复查询设备。"""
        lines: list[str] = []
        for result in results:
            label = result.request.channel or result.request.device_host or "DUT"
            if not result.ok:
                lines.append(f"{label}：查询失败/停止：{result.message}")
                continue
            details = []
            for info in result.connections:
                mode = "路由" if info.mode == "router" else "桥接" if info.mode == "bridge" else info.mode
                details.append(
                    f"{info.name}[{mode or '未知模式'}/{info.service_type or '未知业务'}/"
                    f"VLAN {info.vlan_id or '未知'}]"
                )
            if not details:
                details = list(result.connection_names)
            lines.append(
                f"{label}：发现 {len(result.connection_names)} 个WAN："
                + ("；".join(details) if details else "无")
            )
        self.clear_current_status("wan", "\n".join(lines) or "未返回WAN查询结果。")

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
            "multicast_vlan_id": self.wan_multicast_vlan_id_var,
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
            self._set_wan_port_bind_selection(str(values["port_bind"] or "0"))
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

    def _set_wan_port_bind_selection(self, value: str) -> None:
        """把查询到的位掩码同步成 LAN 勾选状态，并保留其它绑定类型。"""
        mask = _port_bind_mask_value(value)
        self._wan_non_lan_port_bind_mask = mask & ~WAN_LAN_PORT_MASK
        selected = set(wan_lan_ports_from_port_bind(str(mask)))
        for port, variable in zip(WAN_LAN_PORTS, self.wan_lan_port_vars):
            variable.set(port in selected)
        self.wan_port_bind_var.set(str(mask))

    def _sync_wan_port_bind_from_checks(self) -> None:
        """把 LAN 勾选状态实时转换为底层 ``PortBind`` 位掩码。"""
        selected = (
            port
            for port, variable in zip(WAN_LAN_PORTS, self.wan_lan_port_vars)
            if bool(variable.get())
        )
        self.wan_port_bind_var.set(
            wan_port_bind_from_lan_ports(
                selected,
                preserved_mask=self._wan_non_lan_port_bind_mask,
            )
        )

    def _update_wan_form_visibility(self, changed: str = "") -> None:
        """按操作、模式、接入方式、协议和地址方式实时收敛 WAN 表单。"""
        if self._updating_wan_form:
            return
        self._updating_wan_form = True
        try:
            if changed == "operation" and self.wan_operation_var.get() == "新增":
                self._wan_non_lan_port_bind_mask = 0
                self._sync_wan_port_bind_from_checks()
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
                self._set_wan_port_bind_selection("1")

            if access_type == "PPPoE":
                self.wan_ipv4_type_combo.configure(values=("DHCP",))
                self.wan_ipv6_type_combo.configure(values=("SLAAC", "DHCPv6"))
            else:
                self.wan_ipv4_type_combo.configure(values=("DHCP", "静态"))
                self.wan_ipv6_type_combo.configure(values=("SLAAC", "DHCPv6", "静态"))

            rules = resolve_wan_form_rules(
                self.wan_operation_var.get(), self.wan_mode_var.get(), access_type,
                self.wan_ip_protocol_var.get(), ipv4_type, ipv6_type,
                service_type=self.wan_service_type_var.get(),
            )
            visibility = {
                "wan_index": rules.show_index,
                "wan_mode": rules.show_config,
                "wan_service_type": rules.show_config,
                "wan_vlan_id": rules.show_config,
                "wan_multicast_vlan_id": rules.show_multicast_vlan,
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
                hint = (
                    "桥接 IPTV 使用业务类型、业务 VLAN、可选组播 VLAN、优先级和端口绑定；"
                    "默认绑定 LAN1（位掩码 1）。"
                    if rules.show_multicast_vlan
                    else "桥接 WAN 仅使用业务类型、VLAN、优先级和端口绑定；默认绑定 LAN1（位掩码 1）。"
                )
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
            if rules.show_multicast_vlan and rules.show_router:
                hint += " IPTV 可选填写组播 VLAN ID；留空表示不单独配置组播 VLAN。"
            self.wan_rule_hint_var.set(hint)
        finally:
            self._updating_wan_form = False

    def _build_wifi_tab(
        self,
        band: str,
        feature: str,
        on_refresh,
        on_start,
        on_query,
        on_stop,
        on_close,
    ) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text=f"{band} WiFi配置")
        ttk.Label(
            tab,
            text=(
                f"批量配置主 {band} SSID；查询会按厂商 Mapping 解析真实 Radio/AP/SSID 路径。"
                "查询成功后，认证、信道、带宽、协议和功率下拉会按DUT实际能力更新。"
                "开启双频合一时，当前名称、启用/隐藏、认证密码、最大接入数和WMM会同步到两个频段，"
                "信道、带宽、协议及功率仍只修改当前频段。UBUS凭据和并行数与Telnet页共享。"
            ),
            style="Muted.TLabel",
            wraplength=1180,
            justify="left",
        ).pack(fill="x", anchor="w", pady=(0, 6))
        form = ttk.LabelFrame(tab, text=f"{band} WiFi 参数", padding=8)
        form.pack(fill="x")
        defaults = {
            "ssid_index": "1",
            "ssid": "Test_2G_01" if band == "2.4G" else "Test_5G_01",
            "password": "Sdmc@1234_2G" if band == "2.4G" else "Sdmc@1234_5G",
            "channel": "auto",
            "channel_bandwidth": "20/40MHz" if band == "2.4G" else "160MHz",
            "security_mode": "WPA2-Personal",
            "operating_mode": "b,g,n,ax" if band == "2.4G" else "a,n,ac,ax",
            "transmit_power": "100",
            "max_associations": "32",
        }
        variables: dict[str, StringVar | BooleanVar] = {
            key: StringVar(value=value) for key, value in defaults.items()
        }
        variables.update(
            {
                "dual_band_enabled": self.wifi_dual_band_var,
                "enabled": BooleanVar(value=True),
                "hidden": BooleanVar(value=False),
                "wmm_enabled": BooleanVar(value=True),
                "ssid_increment": BooleanVar(value=False),
            }
        )
        self._wifi_vars[feature] = variables

        index_combo = self._field(
            form, 0, 0, "SSID 索引：", variables["ssid_index"],
            values=WIFI_SSID_INDEX_OPTIONS,
        )
        self._field(form, 0, 1, "WiFi 名称：", variables["ssid"], width=24)
        password_entry = self._field(
            form, 0, 2, "WiFi 密码：", variables["password"], width=24
        )
        password_label = form.grid_slaves(row=0, column=4)[0]
        security_combo = self._field(
            form, 0, 3, "认证/加密模式：", variables["security_mode"],
            values=WIFI_SECURITY_MODE_OPTIONS, width=24,
        )
        channel_combo = self._field(
            form, 1, 0, "信道：", variables["channel"],
            values=WIFI_CHANNEL_OPTIONS[band],
        )
        bandwidth_combo = self._field(
            form, 1, 1, "信道带宽：", variables["channel_bandwidth"],
            values=WIFI_BANDWIDTH_OPTIONS[band],
        )
        mode_combo = self._field(
            form, 1, 2, "WiFi 协议类型：", variables["operating_mode"],
            values=WIFI_MODE_OPTIONS[band], width=20,
        )
        power_combo = self._field(
            form, 1, 3, "发射功率(%)：", variables["transmit_power"],
            values=WIFI_TRANSMIT_POWER_OPTIONS,
        )
        self._field(form, 2, 0, "最大接入数：", variables["max_associations"])
        options = ttk.Frame(form)
        options.grid(row=2, column=2, columnspan=6, sticky="w", padx=(4, 0), pady=3)
        for column, (text, variable) in enumerate(
            (
                ("启用 WiFi", variables["enabled"]),
                ("隐藏 WiFi", variables["hidden"]),
                ("启用双频合一", variables["dual_band_enabled"]),
                ("启用 WMM", variables["wmm_enabled"]),
                ("SSID递增", variables["ssid_increment"]),
            )
        ):
            option = self._native_checkbutton(options, text=text, variable=variable)
            option.grid(row=0, column=column, sticky="w", padx=(0, 18))

        hint_var = StringVar(value="")
        variables["hint"] = hint_var
        ttk.Label(
            form,
            textvariable=hint_var,
            style="Muted.TLabel",
            justify="left",
            wraplength=1120,
        ).grid(row=3, column=0, columnspan=8, sticky="w", padx=4, pady=(5, 0))
        self._wifi_password_groups[feature] = (password_label, password_entry)
        self._wifi_choice_widgets[feature] = {
            "ssid_index": index_combo,
            "security_mode": security_combo,
            "channel": channel_combo,
            "channel_bandwidth": bandwidth_combo,
            "operating_mode": mode_combo,
            "transmit_power": power_combo,
        }
        variables["security_mode"].trace_add(
            "write", lambda *_args, selected=feature: self._update_wifi_form(selected)
        )
        variables["dual_band_enabled"].trace_add(
            "write", lambda *_args, selected=feature: self._update_wifi_form(selected)
        )
        variables["ssid_increment"].trace_add(
            "write", lambda *_args, selected=feature: self._update_wifi_form(selected)
        )
        self._update_wifi_form(feature)
        self._build_current_status_area(
            tab, feature, f"尚未查询当前 {band} WiFi 状态。"
        )
        self._advanced_target_area(
            tab,
            feature,
            start_text=f"执行 {band} WiFi 配置",
            on_refresh=on_refresh,
            on_start=on_start,
            on_stop=on_stop,
            on_close=on_close,
            query_text=f"查询当前{band} WiFi",
            on_query=on_query,
        )

    def _update_wifi_form(self, feature: str) -> None:
        variables = self._wifi_vars.get(feature)
        group = self._wifi_password_groups.get(feature)
        if not variables or group is None:
            return
        security_mode = str(variables["security_mode"].get())
        password_label, password_entry = group
        if security_mode == "None":
            password_label.grid_remove()
            password_entry.grid_remove()
            security_hint = "开放网络不下发 WiFi 密码。"
        else:
            password_label.grid()
            password_entry.grid()
            security_hint = "加密网络密码须为8–63个字符，或64位十六进制密钥。"
        dual_hint = (
            "已开启双频合一：名称和安全/AP参数会同步到2.4G与5G。"
            if bool(variables["dual_band_enabled"].get())
            else "双频独立：只修改当前频段。"
        )
        increment_hint = (
            "SSID递增已开启：名称须以数字结尾，并按已选DUT的目标表顺序逐台加1。"
            if bool(variables["ssid_increment"].get())
            else "SSID递增关闭：所有已选DUT使用同一名称。"
        )
        variables["hint"].set(f"{security_hint} {dual_hint} {increment_hint}")

    def _build_voice_tab(self, on_refresh, on_start, on_query, on_stop, on_close) -> None:
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
        self._voice_choice_widgets["dtmf_method"] = self._field(
            form, 2, 3, "DTMF：", self.voice_dtmf_method_var,
            values=VOICE_DTMF_OPTIONS,
        )
        self._field(form, 3, 0, "注册有效期：", self.voice_register_expires_var)
        self._voice_choice_widgets["sip_mode"] = self._field(
            form,
            3,
            1,
            "SIP 模式：",
            self.voice_sip_mode_var,
            values=VOICE_SIP_MODE_OPTIONS,
        )
        self._field(form, 3, 2, "DigitMap：", self.voice_digit_map_var, width=24)
        codec_values = tuple(sorted(VOICE_CODEC_OPTIONS))
        self._voice_choice_widgets["codecs"] = []
        for index, variable in enumerate(self.voice_codec_vars):
            self._voice_choice_widgets["codecs"].append(
                self._field(
                    form, 4 + index // 4, index % 4,
                    f"编码 {index + 1}：", variable, values=codec_values,
                )
            )
        self._build_current_status_area(
            tab, "voice", "尚未查询；查询时使用当前选择的语音线路索引。"
        )
        self._advanced_target_area(
            tab, "voice", start_text="执行语音配置", on_refresh=on_refresh,
            on_start=on_start, on_stop=on_stop, on_close=on_close,
            query_text="查询当前语音", on_query=on_query,
        )

    def _build_tr069_tab(self, on_refresh, on_start, on_query, on_stop, on_close) -> None:
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
        self._tr069_capability_widgets["acs_url"] = self._field(
            form, 0, 0, "ACS URL：", self.tr069_acs_url_var, width=35
        )
        self._tr069_capability_widgets["acs_username"] = self._field(
            form, 0, 1, "ACS 账号：", self.tr069_acs_username_var
        )
        self._tr069_capability_widgets["acs_password"] = self._field(
            form, 0, 2, "ACS 密码：", self.tr069_acs_password_var
        )
        periodic = self._native_checkbutton(
            form, text="启用周期 Inform", variable=self.tr069_periodic_enabled_var
        )
        periodic.grid(row=0, column=6, columnspan=2, sticky="w", padx=4, pady=3)
        self._tr069_capability_widgets["periodic_inform_enabled"] = periodic
        self._tr069_capability_widgets["periodic_inform_interval"] = self._field(
            form, 1, 0, "Inform 间隔(秒)：", self.tr069_interval_var
        )
        conn_enable = self._native_checkbutton(
            form,
            text="启用 HTTP 连接请求",
            variable=self.tr069_connection_request_enabled_var,
        )
        conn_enable.grid(row=1, column=2, columnspan=2, sticky="w", padx=4, pady=3)
        self._tr069_capability_widgets["connection_request_enabled"] = conn_enable
        self._tr069_capability_widgets["connection_request_username"] = self._field(
            form, 1, 2, "连接请求账号：", self.tr069_connection_username_var
        )
        self._tr069_capability_widgets["connection_request_password"] = self._field(
            form, 1, 3, "连接请求密码：", self.tr069_connection_password_var
        )
        cert = self._native_checkbutton(
            form, text="启用证书", variable=self.tr069_certificate_enabled_var
        )
        cert.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        self._tr069_capability_widgets["certificate_enabled"] = cert
        manual = self._native_checkbutton(
            form, text="配置后手动 Inform", variable=self.tr069_manual_inform_var
        )
        manual.grid(row=2, column=2, columnspan=2, sticky="w", padx=4, pady=3)
        self._tr069_capability_widgets["manual_inform"] = manual
        self._build_current_status_area(
            tab, "tr069", "尚未查询；“配置后手动 Inform”是动作选项，不属于设备持久状态。"
        )
        self._advanced_target_area(
            tab, "tr069", start_text="执行 TR069 配置", on_refresh=on_refresh,
            on_start=on_start, on_stop=on_stop, on_close=on_close,
            query_text="查询当前TR069", on_query=on_query,
        )

    def clear_current_status(self, feature: str, message: str) -> None:
        text = self._current_status_texts.get(feature)
        if text is None:
            return
        text.configure(state="normal")
        text.delete("1.0", END)
        text.insert("1.0", message)
        text.configure(state="disabled")

    @staticmethod
    def _voice_status_text(settings: DutVoiceSettings) -> str:
        return (
            f"线路={settings.line_index}，账号={'启用' if settings.account_enabled else '禁用'}，"
            f"显示名称={settings.display_name}，认证={settings.auth_username}/{settings.auth_password}，"
            f"代理={settings.proxy_server}:{settings.proxy_port}，"
            f"出站代理={settings.outbound_proxy}:{settings.outbound_proxy_port}，"
            f"注册服务器={settings.registrar_server}:{settings.registrar_server_port}，"
            f"DTMF={settings.dtmf_method}，有效期={settings.register_expires}，"
            f"SIP模式={settings.sip_mode}，DigitMap={settings.digit_map}，"
            f"编码={' / '.join(settings.codecs)}"
        )

    @staticmethod
    def _telnet_status_text(settings: DutTelnetStatus) -> str:
        rule_state = (
            "启用" if settings.rule_enabled else "禁用" if settings.rule_present else "不存在"
        )
        return (
            f"AccessCtrl总开关={'启用' if settings.access_control_enabled else '禁用'}，"
            f"LAN Telnet规则={rule_state}，"
            f"SourceInterface={list(settings.source_interfaces) or ['无']}，"
            f"TCP 23={'可连接' if settings.tcp_port_open else '不可连接'}，"
            f"探测结果={settings.probe_message}"
        )

    @staticmethod
    def _tr069_status_text(settings: DutTr069Settings) -> str:
        return (
            f"ACS={settings.acs_url}，账号={settings.acs_username}/{settings.acs_password}，"
            f"周期Inform={'启用' if settings.periodic_inform_enabled else '禁用'}"
            f"({settings.periodic_inform_interval}秒)，"
            f"HTTP连接请求={'启用' if settings.connection_request_enabled else '禁用'}，"
            f"连接请求账号={settings.connection_request_username}/"
            f"{settings.connection_request_password}，"
            f"证书={'启用' if settings.certificate_enabled else '禁用'}"
        )

    @staticmethod
    def _wifi_status_text(settings: DutWifiSettings) -> str:
        return (
            f"频段={settings.band}，SSID索引={settings.ssid_index}，"
            f"WiFi={'启用' if settings.enabled else '禁用'}，名称={settings.ssid}，"
            f"密码={settings.password if settings.security_mode != 'None' else '开放网络'}，"
            f"信道={settings.channel}，带宽={settings.channel_bandwidth}，"
            f"双频合一={'启用' if settings.dual_band_enabled else '禁用'}，"
            f"隐藏={'是' if settings.hidden else '否'}，认证/加密={settings.security_mode}，"
            f"协议={settings.operating_mode}，功率={settings.transmit_power}%，"
            f"最大接入={settings.max_associations}，WMM={'启用' if settings.wmm_enabled else '禁用'}"
        )

    def set_current_status_results(
        self,
        feature: str,
        results: Iterable[DutAdvancedQueryResult],
        common_settings: DutTelnetStatus | DutVoiceSettings | DutTr069Settings | DutWifiSettings | None,
    ) -> None:
        lines: list[str] = []
        for result in results:
            label = result.request.channel or result.request.device_host or "DUT"
            if result.ok and isinstance(result.settings, DutTelnetStatus):
                lines.append(f"{label}：{self._telnet_status_text(result.settings)}")
            elif result.ok and isinstance(result.settings, DutVoiceSettings):
                lines.append(f"{label}：{self._voice_status_text(result.settings)}")
            elif result.ok and isinstance(result.settings, DutTr069Settings):
                lines.append(f"{label}：{self._tr069_status_text(result.settings)}")
            elif result.ok and isinstance(result.settings, DutWifiSettings):
                lines.append(f"{label}：{self._wifi_status_text(result.settings)}")
            else:
                lines.append(f"{label}：查询失败/停止：{result.message}")
        sync_features = {"voice", "tr069", "wifi_2g", "wifi_5g"}
        if feature in sync_features and common_settings is not None:
            self.apply_current_status(feature, common_settings)
            lines.append("已确认全部成功目标参数一致，并同步到当前配置表单。")
        elif feature in sync_features and any(result.ok for result in results):
            if feature == "voice":
                self._reset_voice_choice_options()
            elif feature == "tr069":
                self._reset_tr069_capabilities()
            elif feature in {"wifi_2g", "wifi_5g"}:
                self._reset_wifi_choice_options(feature)
            lines.append("目标状态不完全一致或存在失败，未使用任意一台覆盖当前配置表单。")
        self.clear_current_status(feature, "\n".join(lines) or "未返回查询结果。")

    def apply_current_status(
        self,
        feature: str,
        settings: DutVoiceSettings | DutTr069Settings | DutWifiSettings,
    ) -> None:
        if feature == "voice" and isinstance(settings, DutVoiceSettings):
            values = voice_status_form_values(settings)
            options_by_key = voice_choice_options(settings)
            self._voice_supported_options = options_by_key
            dtmf_widget = self._voice_choice_widgets.get("dtmf_method")
            sip_widget = self._voice_choice_widgets.get("sip_mode")
            codec_widgets = self._voice_choice_widgets.get("codecs", ())
            if dtmf_widget is not None:
                dtmf_widget.configure(values=options_by_key["dtmf_method"])
            if sip_widget is not None:
                sip_widget.configure(values=options_by_key["sip_mode"])
            for widget in codec_widgets:
                widget.configure(values=options_by_key["codecs"])
            variables = {
                "line_index": self.voice_line_index_var,
                "display_name": self.voice_display_name_var,
                "auth_username": self.voice_auth_username_var,
                "auth_password": self.voice_auth_password_var,
                "proxy_server": self.voice_proxy_server_var,
                "proxy_port": self.voice_proxy_port_var,
                "outbound_proxy": self.voice_outbound_proxy_var,
                "outbound_proxy_port": self.voice_outbound_proxy_port_var,
                "registrar_server": self.voice_registrar_server_var,
                "registrar_server_port": self.voice_registrar_server_port_var,
                "dtmf_method": self.voice_dtmf_method_var,
                "register_expires": self.voice_register_expires_var,
                "sip_mode": self.voice_sip_mode_var,
                "digit_map": self.voice_digit_map_var,
            }
            for key, variable in variables.items():
                variable.set(values[key])
            self.voice_account_enabled_var.set(bool(values["account_enabled"]))
            for variable, value in zip(self.voice_codec_vars, values["codecs"]):
                variable.set(value)
        elif feature == "tr069" and isinstance(settings, DutTr069Settings):
            values = tr069_status_form_values(settings)
            variables = {
                "acs_url": self.tr069_acs_url_var,
                "acs_username": self.tr069_acs_username_var,
                "acs_password": self.tr069_acs_password_var,
                "periodic_inform_interval": self.tr069_interval_var,
                "connection_request_username": self.tr069_connection_username_var,
                "connection_request_password": self.tr069_connection_password_var,
            }
            for key, variable in variables.items():
                variable.set(values[key])
            self.tr069_periodic_enabled_var.set(
                bool(values["periodic_inform_enabled"])
            )
            self.tr069_connection_request_enabled_var.set(
                bool(values["connection_request_enabled"])
            )
            self.tr069_certificate_enabled_var.set(bool(values["certificate_enabled"]))
            self._apply_tr069_capabilities(settings.supported_fields)
        elif feature in {"wifi_2g", "wifi_5g"} and isinstance(
            settings, DutWifiSettings
        ):
            values = wifi_status_form_values(settings)
            variables = self._wifi_vars[feature]
            for key in (
                "ssid_index",
                "ssid",
                "password",
                "channel",
                "channel_bandwidth",
                "security_mode",
                "operating_mode",
                "transmit_power",
                "max_associations",
            ):
                variables[key].set(values[key])
            for key in ("dual_band_enabled", "enabled", "hidden", "wmm_enabled"):
                variables[key].set(bool(values[key]))
            widgets = self._wifi_choice_widgets.get(feature, {})
            options_by_key = wifi_choice_options(settings)
            self._wifi_supported_options[feature] = options_by_key
            for key, options in options_by_key.items():
                if key in widgets:
                    widgets[key].configure(values=options)
            self._update_wifi_form(feature)

    def _reset_voice_choice_options(self) -> None:
        if not hasattr(self, "_voice_choice_widgets"):
            return
        settings = DutVoiceSettings()
        options_by_key = voice_choice_options(settings)
        self._voice_supported_options = options_by_key
        dtmf_widget = self._voice_choice_widgets.get("dtmf_method")
        sip_widget = self._voice_choice_widgets.get("sip_mode")
        codec_widgets = self._voice_choice_widgets.get("codecs", ())
        if dtmf_widget is not None:
            dtmf_widget.configure(values=options_by_key["dtmf_method"])
        if sip_widget is not None:
            sip_widget.configure(values=options_by_key["sip_mode"])
        for widget in codec_widgets:
            widget.configure(values=options_by_key["codecs"])
        if self.voice_dtmf_method_var.get() not in options_by_key["dtmf_method"]:
            self.voice_dtmf_method_var.set(settings.dtmf_method)
        if self.voice_sip_mode_var.get() not in options_by_key["sip_mode"]:
            self.voice_sip_mode_var.set(settings.sip_mode)
        for variable, default in zip(self.voice_codec_vars, settings.codecs):
            if variable.get() not in options_by_key["codecs"]:
                variable.set(default)

    def _apply_tr069_capabilities(self, supported_fields: tuple[str, ...]) -> None:
        self._tr069_supported_fields = tuple(dict.fromkeys(supported_fields))
        supported = set(self._tr069_supported_fields)
        for field, widget in self._tr069_capability_widgets.items():
            disabled = bool(supported) and field not in supported
            if disabled:
                self._capability_disabled_widgets.add(widget)
                widget.configure(state="disabled")
            else:
                self._capability_disabled_widgets.discard(widget)
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly")
                else:
                    widget.configure(state="normal")
        if supported and "manual_inform" not in supported:
            self.tr069_manual_inform_var.set(False)

    def _reset_tr069_capabilities(self) -> None:
        if not hasattr(self, "_tr069_capability_widgets"):
            return
        self._tr069_supported_fields = ()
        for widget in self._tr069_capability_widgets.values():
            self._capability_disabled_widgets.discard(widget)
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly")
            else:
                widget.configure(state="normal")

    def _reset_wifi_choice_options(self, feature: str) -> None:
        variables = self._wifi_vars.get(feature)
        widgets = self._wifi_choice_widgets.get(feature, {})
        if variables is None:
            return
        band = "2.4G" if feature == "wifi_2g" else "5G"
        settings = DutWifiSettings(
            band=band,
            channel="auto",
            channel_bandwidth="20/40MHz" if band == "2.4G" else "160MHz",
            security_mode="WPA2-Personal",
            operating_mode="b,g,n,ax" if band == "2.4G" else "a,n,ac,ax",
            transmit_power="100",
        )
        options_by_key = wifi_choice_options(settings)
        self._wifi_supported_options[feature] = options_by_key
        for key, options in options_by_key.items():
            if key in widgets:
                widgets[key].configure(values=options)
            if str(variables[key].get()).strip() not in options:
                variables[key].set(getattr(settings, key))

    def wan_settings(self) -> DutWanSettings:
        self._sync_wan_port_bind_from_checks()
        return DutWanSettings(
            operation={"新增": "add", "修改": "modify", "删除": "delete"}.get(self.wan_operation_var.get(), ""),
            connection_index=self.wan_index_var.get().strip(),
            mode={"路由": "router", "桥接": "bridge"}.get(self.wan_mode_var.get(), ""),
            service_type=self.wan_service_type_var.get().strip(), vlan_id=self.wan_vlan_id_var.get().strip(),
            multicast_vlan_id=self.wan_multicast_vlan_id_var.get().strip(),
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
            supported_dtmf_methods=self._voice_supported_options.get("dtmf_method", ()),
            supported_sip_modes=self._voice_supported_options.get("sip_mode", ()),
            supported_codecs=self._voice_supported_options.get("codecs", ()),
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
            supported_fields=self._tr069_supported_fields,
        )

    def wifi_settings(self, feature: str) -> DutWifiSettings:
        variables = self._wifi_vars[feature]
        supported = self._wifi_supported_options.get(feature, {})
        return DutWifiSettings(
            band="2.4G" if feature == "wifi_2g" else "5G",
            ssid_index=str(variables["ssid_index"].get()).strip(),
            ssid=str(variables["ssid"].get()),
            password=str(variables["password"].get()),
            channel=str(variables["channel"].get()).strip(),
            channel_bandwidth=str(variables["channel_bandwidth"].get()).strip(),
            dual_band_enabled=bool(variables["dual_band_enabled"].get()),
            enabled=bool(variables["enabled"].get()),
            hidden=bool(variables["hidden"].get()),
            security_mode=str(variables["security_mode"].get()).strip(),
            operating_mode=str(variables["operating_mode"].get()).strip(),
            transmit_power=str(variables["transmit_power"].get()).strip(),
            max_associations=str(variables["max_associations"].get()).strip(),
            wmm_enabled=bool(variables["wmm_enabled"].get()),
            supported_channels=supported.get("channel", ()),
            supported_bandwidths=supported.get("channel_bandwidth", ()),
            supported_modes=supported.get("operating_mode", ()),
            supported_security_modes=supported.get("security_mode", ()),
            supported_transmit_powers=supported.get("transmit_power", ()),
        )

    def wifi_ssid_index(self, feature: str) -> str:
        return str(self._wifi_vars[feature]["ssid_index"].get()).strip()

    def wifi_ssid_increment_enabled(self, feature: str) -> bool:
        return bool(self._wifi_vars[feature]["ssid_increment"].get())

    def exists(self) -> bool:
        return bool(self.window.winfo_exists())

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.after_idle(self._constrain_selected_current_status_height)
        self.window.focus_force()
        schedule_toplevel_client_refresh(self.window)

    def destroy(self) -> None:
        self._remember_current_status_heights()
        save_dut_current_status_heights(
            self._state_path, self._current_status_heights
        )
        width, height = self._current_window_size()
        save_dut_window_size(self._state_path, width, height)
        self.window.destroy()

    def _current_window_size(self) -> tuple[int, int]:
        try:
            self.window.update_idletasks()
            return clamp_dut_window_size(
                self.window.winfo_width(),
                self.window.winfo_height(),
                screen_width=self.window.winfo_screenwidth(),
                screen_height=self.window.winfo_screenheight(),
            )
        except (AttributeError, TclError, TypeError, ValueError):
            return DUT_CONFIG_DEFAULT_WIDTH, DUT_CONFIG_DEFAULT_HEIGHT

    def parallel_count(self) -> str:
        return self.parallel_count_var.get()

    def _bind_target_tree_selection(self, tree: ttk.Treeview) -> None:
        tree.bind(
            "<ButtonRelease-1>",
            lambda event, selected_tree=tree: self._on_target_tree_click(
                selected_tree, event
            ),
            add="+",
        )

    def _on_target_tree_click(self, tree: ttk.Treeview, event) -> str | None:
        if self._running or tree.identify_region(event.x, event.y) != "cell":
            return None
        if tree.identify_column(event.x) != "#1":
            return None
        row_id = tree.identify_row(event.y)
        if not row_id:
            return None
        values = tuple(tree.item(row_id, "values"))
        if len(values) < 2:
            return None
        channel = str(values[1])
        if channel in self._selected_target_channels:
            self._selected_target_channels.discard(channel)
        else:
            self._selected_target_channels.add(channel)
        self._invalidate_status_after_target_selection_change()
        self._sync_target_selection_display()
        return "break"

    def _invalidate_status_after_target_selection_change(self) -> None:
        self.clear_wan_connections("DUT窗口目标选择已变化，请重新查询现有 WAN。")
        self.clear_current_status("telnet", "DUT窗口目标选择已变化，请重新查询当前Telnet状态。")
        self.clear_current_status("wan", "DUT窗口目标选择已变化，请重新查询当前WAN状态。")
        self.clear_current_status("voice", "DUT窗口目标选择已变化，请重新查询当前语音状态。")
        self.clear_current_status("tr069", "DUT窗口目标选择已变化，请重新查询当前TR069状态。")
        self.clear_current_status("wifi_2g", "DUT窗口目标选择已变化，请重新查询当前2.4G WiFi状态。")
        self.clear_current_status("wifi_5g", "DUT窗口目标选择已变化，请重新查询当前5G WiFi状态。")
        self._reset_wifi_choice_options("wifi_2g")
        self._reset_wifi_choice_options("wifi_5g")
        self._reset_voice_choice_options()
        self._reset_tr069_capabilities()

    def _sync_target_selection_display(self) -> None:
        for feature, tree in self._trees.items():
            rows = self._rows_by_feature[feature]
            for channel, row_id in rows.items():
                values = list(tree.item(row_id, "values"))
                if not values:
                    continue
                selected = channel in self._selected_target_channels
                values[0] = (
                    DUT_TARGET_SELECTED_MARK if selected else DUT_TARGET_UNSELECTED_MARK
                )
                values[-1] = (
                    self._target_errors_by_channel.get(
                        channel, "配置完整，等待执行"
                    )
                    if selected
                    else "未选择，本次跳过"
                )
                tree.item(row_id, values=values)
            selected_count = sum(
                1 for channel in self._target_channels
                if channel in self._selected_target_channels
            )
            self._summary_vars[feature].set(
                f"已加载 {len(self._target_channels)} 台目标 DUT，已选择 {selected_count} 台"
                if self._target_channels
                else "主界面当前没有已勾选通道"
            )

    def select_all_targets(self) -> None:
        if self._running:
            return
        if self._selected_target_channels == set(self._target_channels):
            return
        self._selected_target_channels = set(self._target_channels)
        self._invalidate_status_after_target_selection_change()
        self._sync_target_selection_display()

    def clear_all_targets(self) -> None:
        if self._running or not self._selected_target_channels:
            return
        self._selected_target_channels.clear()
        self._invalidate_status_after_target_selection_change()
        self._sync_target_selection_display()

    def selected_target_channels(self) -> tuple[str, ...]:
        return tuple(
            channel for channel in self._target_channels
            if channel in self._selected_target_channels
        )

    def voice_line_index(self) -> str:
        return self.voice_line_index_var.get().strip()

    def set_targets(
        self,
        requests: Iterable[DutTelnetEnableRequest],
        errors_by_channel: Mapping[str, str],
    ) -> None:
        request_list = list(requests)
        current_channels = tuple(request.channel for request in request_list)
        self._selected_target_channels = set(
            reconcile_dut_target_selection(
                self._selected_target_channels,
                self._target_channels,
                current_channels,
            )
        )
        self._target_channels = current_channels
        self._target_errors_by_channel = dict(errors_by_channel)
        target_signature = tuple(
            (request.channel, request.vlan, request.bind_ip, request.device_host)
            for request in request_list
        )
        if target_signature != self._wan_target_signature:
            self.clear_wan_connections("目标 DUT 已变化，请重新查询现有 WAN。")
            self.clear_current_status("telnet", "目标 DUT 已变化，请重新查询当前Telnet状态。")
            self.clear_current_status("wan", "目标 DUT 已变化，请重新查询当前WAN状态。")
            self.clear_current_status("voice", "目标 DUT 已变化，请重新查询当前语音状态。")
            self.clear_current_status("tr069", "目标 DUT 已变化，请重新查询当前TR069状态。")
            self.clear_current_status("wifi_2g", "目标 DUT 已变化，请重新查询当前2.4G WiFi状态。")
            self.clear_current_status("wifi_5g", "目标 DUT 已变化，请重新查询当前5G WiFi状态。")
            self._reset_wifi_choice_options("wifi_2g")
            self._reset_wifi_choice_options("wifi_5g")
            self._reset_voice_choice_options()
            self._reset_tr069_capabilities()
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
                        (
                            DUT_TARGET_SELECTED_MARK
                            if request.channel in self._selected_target_channels
                            else DUT_TARGET_UNSELECTED_MARK
                        ),
                        request.channel, request.vlan or "未配置", request.adapter_alias or "未配置",
                        request.bind_ip or "未配置", request.device_host or "未配置", status,
                    ),
                )
                rows[request.channel or f"row-{index}"] = row_id
        self._sync_target_selection_display()

    def mark_all_pending(self, feature: str = "telnet") -> None:
        tree = self._trees.get(feature, self.target_tree)
        for channel, row_id in self._rows_by_feature.get(
            feature, self._row_by_channel
        ).items():
            values = list(tree.item(row_id, "values"))
            values[-1] = (
                "等待执行"
                if channel in self._selected_target_channels
                else "未选择，本次跳过"
            )
            tree.item(row_id, values=values)

    def update_result(
        self,
        result: DutTelnetEnableResult | DutAdvancedConfigResult | DutAdvancedQueryResult | DutWanQueryResult,
        feature: str | None = None,
    ) -> None:
        resolved_feature = feature or getattr(result.request, "feature", "telnet")
        tree_feature = {
            "telnet_query": "telnet", "wan_query": "wan",
            "voice_query": "voice", "tr069_query": "tr069",
            "wifi_2g_query": "wifi_2g", "wifi_5g_query": "wifi_5g",
        }.get(resolved_feature, resolved_feature)
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
            if resolved_feature in {
                "telnet_query", "voice_query", "tr069_query",
                "wifi_2g_query", "wifi_5g_query",
            }:
                values[-1] = "成功：已查询当前状态"
                tree.item(row_id, values=values)
                return
            success_text = {
                "telnet": "成功：Telnet 已开启并验证可用",
                "wan": "成功：WAN 操作完成",
                "voice": "成功：语音配置完成",
                "tr069": "成功：TR069 配置完成",
                "wifi_2g": "成功：2.4G WiFi 配置完成",
                "wifi_5g": "成功：5G WiFi 配置完成",
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
        self._running = running
        input_state = "disabled" if running else "normal"
        self.username_entry.configure(state=input_state)
        self.password_entry.configure(state=input_state)
        self.parallel_spinbox.configure(state=input_state)
        for widget in self._input_widgets:
            try:
                if not running and widget in self._capability_disabled_widgets:
                    widget.configure(state="disabled")
                elif isinstance(widget, ttk.Combobox):
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
        if not running:
            for feature in self._wifi_vars:
                self._update_wifi_form(feature)
        if stopping:
            for summary_var in self._summary_vars.values():
                summary_var.set("正在停止：已运行任务将在安全点结束，尚未开始的 DUT 将跳过")


__all__ = [
    "DUT_CONFIG_DEFAULT_HEIGHT",
    "DUT_CONFIG_DEFAULT_WIDTH",
    "DUT_CONFIG_MIN_HEIGHT",
    "DUT_CONFIG_MIN_WIDTH",
    "DUT_CONFIG_UI_STATE_PATH",
    "DUT_CURRENT_STATUS_DEFAULT_HEIGHT",
    "DUT_CURRENT_STATUS_MAX_HEIGHT",
    "DUT_CURRENT_STATUS_MIN_HEIGHT",
    "DUT_TARGET_SELECTED_MARK",
    "DUT_TARGET_UNSELECTED_MARK",
    "DutConfigWindow",
    "WanFormRules",
    "clamp_dut_window_size",
    "normalize_wan_address_modes",
    "clamp_dut_current_status_height",
    "load_dut_current_status_heights",
    "load_dut_window_size",
    "resolve_wan_form_rules",
    "reconcile_dut_target_selection",
    "wan_lan_ports_from_port_bind",
    "wan_port_bind_from_lan_ports",
    "tr069_status_form_values",
    "voice_status_form_values",
    "wifi_status_form_values",
    "wifi_choice_options",
    "voice_choice_options",
    "save_dut_current_status_heights",
    "save_dut_window_size",
]

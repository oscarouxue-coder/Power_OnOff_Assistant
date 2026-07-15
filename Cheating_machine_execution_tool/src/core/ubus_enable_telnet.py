"""通过 UBUS 在样机上打开 telnet 服务（依 network_ops.firewall 访问控制规则）。

协议复刻自 SdmcUbusLibEnableTelnet.Enable_telnet（Cheating_machine_execution_tool/SdmcUbusLib/libs/Security_module_api/enable_telnet.py），
但由于 SdmcUbusLib 复用作工类、会话静态、不允许多并发，本地重写以适配本项目。

调用顺序：
1) `client.login(user, pass)` 拿到 ubus_rpc_session
2) bbfdm `get` Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable 总开关
3) 如 Enable != "1"：bbfdm `set` {"Enable": "1"}
4) bbfdm `get` Device.Firewall.<X_SDMC_>Security.AccessCtrl.Rule.{}. — 列出规则
5) 若存在 Application 含 "telnet" 且 SourceInterface in (lan / both / Device.IP.Interface.1)：
   - Enable != "True"：`set` 该 X_SDMC_Instance 的 {"Enable": "1"} → 返回 "already_present" 或 "reused"
   - 否则返回 "already_present"
6) 否则 `add` {SourceInterface: "Device.IP.Interface.1", IPVersion: 4, SourceIP: "0.0.0.0", Application: "telnet"}
7) 失败回退: `add` {SourceInterface: "lan", IPVersion: 4, SourceIP: "0.0.0.0", Application: "telnet"}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .ubus_http_client import UbusError, UbusHttpClient


VENDOR_PREFIX = "X_SDMC_"
ACCESS_CTRL_ENABLE_PATH = f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable"
ACCESS_CTRL_RULE_BASE_PATH = f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule."
LAN_SOURCE_INTERFACES = ("lan", "both", "Device.IP.Interface.1")


@dataclass(frozen=True)
class EnableTelnetResult:
    ok: bool
    action: str  # "already_present", "reused", "added_iface", "added_lan_fallback", "failed"
    message: str


EnableTelnetCallback = Callable[[EnableTelnetResult], None]


def enable_telnet_via_ubus(
    client: UbusHttpClient,
    username: str,
    password: str,
    *,
    on_log: EnableTelnetCallback | None = None,
    sleep_fn: Callable[[float], None] = __import__("time").sleep,
    sleep_after_seconds: float = 1.5,
) -> EnableTelnetResult:
    """对一台样机执行\"启用 telnet\"的 UBUS 流程。失败抛 UbusError 由调用方决定是否单台跳过。"""
    if on_log is not None:
        on_log(EnableTelnetResult(True, "started", "已发起 UBUS 启用 telnet 流程"))

    # 1) login
    session_id = client.login(username, password)

    # 2) 总开关
    try:
        result_enable = client.bbfdm_get(session_id, ACCESS_CTRL_ENABLE_PATH)
        enable_state = None
        if isinstance(result_enable, list) and len(result_enable) > 1:
            inner = result_enable[1]
            if isinstance(inner, dict):
                enable_state = inner.get("Enable")
        if enable_state != "1":
            client.bbfdm_set(session_id, ACCESS_CTRL_ENABLE_PATH, {"Enable": "1"})
            if on_log is not None:
                on_log(EnableTelnetResult(True, "set_total_enable", "AccessCtrl 总开关开启"))
    except UbusError as exc:
        if on_log is not None:
            on_log(EnableTelnetResult(False, "get_total_enable_failed", f"获取访问规则总开关失败：{exc}"))
        raise

    # 3) 检查已有 telnet 规则
    try:
        result_rule = client.bbfdm_get(session_id, ACCESS_CTRL_RULE_BASE_PATH)
    except UbusError as exc:
        if on_log is not None:
            on_log(EnableTelnetResult(False, "get_rule_failed", f"获取访问控制规则失败：{exc}"))
        raise

    rules_payload: list = []
    if isinstance(result_rule, list) and len(result_rule) > 1:
        candidate = result_rule[1]
        if isinstance(candidate, dict) and isinstance(candidate.get("Rule"), list):
            rules_payload = candidate["Rule"]

    for rule in rules_payload:
        if not isinstance(rule, dict):
            continue
        application = str(rule.get("Application", ""))
        if "telnet" not in application:
            continue
        source_interface = str(rule.get("SourceInterface", ""))
        if source_interface not in LAN_SOURCE_INTERFACES:
            continue
        enable_flag = rule.get("Enable", "True")
        x_sdmc_instance = rule.get("X_SDMC_Instance", "")
        if enable_flag != "True":
            client.bbfdm_set(
                session_id,
                f"{ACCESS_CTRL_RULE_BASE_PATH}{x_sdmc_instance}.",
                {"Enable": "1"},
            )
            if on_log is not None:
                on_log(EnableTelnetResult(True, "reused", f"已开启 LAN-telnet 规则 Enable (instance={x_sdmc_instance})"))
        else:
            if on_log is not None:
                on_log(EnableTelnetResult(True, "already_present", "LAN-telnet 规则已启用"))
        sleep_fn(sleep_after_seconds)
        return EnableTelnetResult(True, "already_present", "LAN-telnet 规则已就绪")

    # 4) 没有规则: add Device.IP.Interface.1（默认）
    try:
        client.bbfdm_add(
            session_id,
            ACCESS_CTRL_RULE_BASE_PATH,
            {
                "SourceInterface": "Device.IP.Interface.1",
                "IPVersion": 4,
                "SourceIP": "0.0.0.0",
                "Application": "telnet",
            },
        )
        sleep_fn(sleep_after_seconds)
        if on_log is not None:
            on_log(EnableTelnetResult(True, "added_iface", "已添加 Device.IP.Interface.1 telnet 规则"))
        return EnableTelnetResult(True, "added_iface", "已添加 telnet 规则")
    except UbusError:
        # 回退到 lan
        client.bbfdm_add(
            session_id,
            ACCESS_CTRL_RULE_BASE_PATH,
            {
                "SourceInterface": "lan",
                "IPVersion": 4,
                "SourceIP": "0.0.0.0",
                "Application": "telnet",
            },
        )
        sleep_fn(sleep_after_seconds)
        if on_log is not None:
            on_log(EnableTelnetResult(True, "added_lan_fallback", "Device.IP.Interface.1 失败,回退添加 lan telnet 规则"))
        return EnableTelnetResult(True, "added_lan_fallback", "已通过 lan 回退添加 telnet 规则")

"""通过 UBUS 在样机上打开 telnet 服务（依 network_ops.firewall 访问控制规则）。

协议复刻自 SdmcUbusLibEnableTelnet.Enable_telnet（Cheating_machine_execution_tool/SdmcUbusLib/libs/Security_module_api/enable_telnet.py），
但由于 SdmcUbusLib 复用作工类、会话静态、不允许多并发，本地重写以适配本项目。

调用顺序：
1) `client.login(user, pass)` 拿到 ubus_rpc_session
2) bbfdm `get` Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable 总开关
3) 如 Enable != "1"：bbfdm `set` {"Enable": "1"}（并校验 results[*].data == "1"）
4) bbfdm `get` Device.Firewall.<X_SDMC_>Security.AccessCtrl.Rule.{}. — 列出规则
5) 若存在 Application 含 "telnet" 且 SourceInterface in (lan / both / Device.IP.Interface.1):
   - Enable != "True"：`set` 该 X_SDMC_Instance 的 {"Enable": "1"}（并校验 results[*].data == "1"）→ 返回 "reused"
   - 否则返回 "already_present"
6) 否则 `add` {SourceInterface: "Device.IP.Interface.1", IPVersion: 4, SourceIP: "0.0.0.0", Application: "telnet"}（并校验 results[*].data == "1"）
7) 失败回退: `add` {SourceInterface: "lan", IPVersion: 4, SourceIP: "0.0.0.0", Application: "telnet"}（并校验 results[*].data == "1"）
8) 成功路径的最后额外 sleep 1.0 秒,模拟 SdmcUbusLib 现有流程节奏,给防火墙 reload 留时间。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.models.dut_config_models import DutTelnetStatus

from .telnet_transport import probe_telnet_port
from .ubus_http_client import UbusError, UbusHttpClient


VENDOR_PREFIX = "X_SDMC_"
# GET 参数路径:Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable
ACCESS_CTRL_ENABLE_PATH = f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable"
# SET/ADD 时使用的对象路径(末尾带点):与 SdmcUbusLibEnableTelnet._set_SecurityAccessCtrl_enable
# 一致。若使用 ACCESS_CTRL_ENABLE_PATH 加 obj_path={"Enable":"1"},bbfdm 会把路径拼成
# "...AccessCtrl.EnableEnable" 并以 fault 9005 "Invalid parameter name" 拒绝。
ACCESS_CTRL_ENABLE_OBJECT_PATH = f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl."
ACCESS_CTRL_RULE_BASE_PATH = f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule."
LAN_SOURCE_INTERFACES = ("lan", "both", "Device.IP.Interface.1")
ENABLE_TELNET_FINAL_SLEEP_SECONDS = 1.0


@dataclass(frozen=True)
class EnableTelnetResult:
    ok: bool
    action: str  # "already_present", "reused", "added_iface", "added_lan_fallback", "failed"
    message: str


EnableTelnetCallback = Callable[[EnableTelnetResult], None]
TelnetStatusLogCallback = Callable[[str], None]


def _bbfdm_all_results_one(response: Any) -> bool:
    """校验 bbfdm SET/ADD 响应中 ``results[*].data`` 全部等于 ``"1"``。

    复刻自 ``SdmcUbusLibEnableTelnet._set_SecurityAccessCtrl_enable`` 与
    ``_add_SecurityAccessCtrlRule`` 的断言:BBFDM 即使 JSON-RPC ``error_code=0``,
    也可能在 ``results[*].data='0'`` 中给出拒绝;不校验会误判为成功。
    """
    if not isinstance(response, list) or len(response) < 2:
        return False
    payload = response[1]
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return False
    return all(
        isinstance(item, dict) and item.get("data") == "1" for item in results
    )


def query_telnet_status(
    client: UbusHttpClient,
    session_id: str,
    bind_ip: str,
    device_host: str,
    *,
    on_log: TelnetStatusLogCallback | None = None,
    probe_fn: Callable[..., None] = probe_telnet_port,
    probe_timeout: float = 5.0,
) -> DutTelnetStatus:
    """只读查询AccessCtrl和TCP 23；不会开启或新增任何规则。"""
    if on_log is not None:
        on_log(f"TX UBUS bbfdm.get path={ACCESS_CTRL_ENABLE_PATH}")
    enable_response = client.bbfdm_get(session_id, ACCESS_CTRL_ENABLE_PATH)
    if not isinstance(enable_response, list) or not enable_response or enable_response[0] != 0:
        raise UbusError(f"查询AccessCtrl总开关失败：{enable_response}")
    enable_payload = (
        enable_response[1]
        if len(enable_response) > 1 and isinstance(enable_response[1], dict)
        else {}
    )
    access_control_enabled = str(enable_payload.get("Enable", "")).strip().casefold() in {
        "1", "true", "enable", "enabled",
    }

    if on_log is not None:
        on_log(f"TX UBUS bbfdm.get path={ACCESS_CTRL_RULE_BASE_PATH}")
    rules_response = client.bbfdm_get(session_id, ACCESS_CTRL_RULE_BASE_PATH)
    if not isinstance(rules_response, list) or not rules_response or rules_response[0] != 0:
        raise UbusError(f"查询AccessCtrl规则失败：{rules_response}")
    rules_payload = (
        rules_response[1]
        if len(rules_response) > 1 and isinstance(rules_response[1], dict)
        else {}
    )
    rules = rules_payload.get("Rule", [])
    matching_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict)
        and "telnet" in str(rule.get("Application", "")).casefold()
        and str(rule.get("SourceInterface", "")) in LAN_SOURCE_INTERFACES
    ] if isinstance(rules, list) else []
    source_interfaces = tuple(
        dict.fromkeys(str(rule.get("SourceInterface", "")) for rule in matching_rules)
    )
    rule_enabled = any(
        str(rule.get("Enable", "True")).strip().casefold()
        in {"1", "true", "enable", "enabled"}
        for rule in matching_rules
    )

    if on_log is not None:
        on_log(f"TX TCP Telnet状态探测：{bind_ip} -> {device_host}:23")
    try:
        probe_fn(bind_ip, device_host, device_port=23, timeout=probe_timeout)
        tcp_port_open = True
        probe_message = "TCP 23可连接"
    except Exception as exc:  # noqa: BLE001 - 端口关闭属于可展示状态
        tcp_port_open = False
        probe_message = str(exc)
    status = DutTelnetStatus(
        access_control_enabled=access_control_enabled,
        rule_present=bool(matching_rules),
        rule_enabled=rule_enabled,
        source_interfaces=source_interfaces,
        tcp_port_open=tcp_port_open,
        probe_message=probe_message,
    )
    if on_log is not None:
        on_log(
            "RX UBUS Telnet当前状态："
            f"AccessCtrl={'启用' if status.access_control_enabled else '禁用'}，"
            f"LAN规则={'启用' if status.rule_enabled else ('禁用' if status.rule_present else '不存在')}，"
            f"SourceInterface={list(status.source_interfaces)}，"
            f"TCP23={'可连接' if status.tcp_port_open else '不可连接'}，"
            f"探测结果={status.probe_message}"
        )
    return status


def enable_telnet_via_ubus(
    client: UbusHttpClient,
    username: str,
    password: str,
    *,
    on_log: EnableTelnetCallback | None = None,
    sleep_fn: Callable[[float], None] = __import__("time").sleep,
    sleep_after_seconds: float = 1.5,
) -> EnableTelnetResult:
    """对一台样机执行"启用 telnet"的 UBUS 流程。失败抛 UbusError 由调用方决定是否单台跳过。"""
    if on_log is not None:
        on_log(EnableTelnetResult(True, "started", "已发起 UBUS 启用 telnet 流程"))

    # 1) login
    if on_log is not None:
        on_log(EnableTelnetResult(True, "tx_login", f"TX UBUS session.login username={username}, password={password}"))
    session_id = client.login(username, password)
    if on_log is not None:
        on_log(EnableTelnetResult(True, "login_ok", "UBUS 登录成功"))

    # 2) 总开关
    try:
        if on_log is not None:
            on_log(EnableTelnetResult(True, "tx_get_total_enable", f"TX UBUS bbfdm.get path={ACCESS_CTRL_ENABLE_PATH}"))
        result_enable = client.bbfdm_get(session_id, ACCESS_CTRL_ENABLE_PATH)
        enable_state = None
        if isinstance(result_enable, list) and len(result_enable) > 1:
            inner = result_enable[1]
            if isinstance(inner, dict):
                enable_state = inner.get("Enable")
        if enable_state != "1":
            if on_log is not None:
                on_log(EnableTelnetResult(True, "tx_set_total_enable", f"TX UBUS bbfdm.set path={ACCESS_CTRL_ENABLE_OBJECT_PATH}, obj_path={{'Enable': '1'}}"))
            set_response = client.bbfdm_set(session_id, ACCESS_CTRL_ENABLE_OBJECT_PATH, {"Enable": "1"})
            if not _bbfdm_all_results_one(set_response):
                raise UbusError(f"UBUS 设置访问控制总开关失败,响应 {set_response}")
            if on_log is not None:
                on_log(EnableTelnetResult(True, "set_total_enable", "AccessCtrl 总开关开启"))
    except UbusError as exc:
        if on_log is not None:
            on_log(EnableTelnetResult(False, "get_total_enable_failed", f"获取访问规则总开关失败:{exc}"))
        raise

    # 3) 检查已有 telnet 规则
    try:
        if on_log is not None:
            on_log(EnableTelnetResult(True, "tx_get_rules", f"TX UBUS bbfdm.get path={ACCESS_CTRL_RULE_BASE_PATH}"))
        result_rule = client.bbfdm_get(session_id, ACCESS_CTRL_RULE_BASE_PATH)
    except UbusError as exc:
        if on_log is not None:
            on_log(EnableTelnetResult(False, "get_rule_failed", f"获取访问控制规则失败:{exc}"))
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
        result: EnableTelnetResult
        if enable_flag != "True":
            rule_path = f"{ACCESS_CTRL_RULE_BASE_PATH}{x_sdmc_instance}."
            if on_log is not None:
                on_log(EnableTelnetResult(True, "tx_set_rule", f"TX UBUS bbfdm.set path={rule_path}, obj_path={{'Enable': '1'}}"))
            set_response = client.bbfdm_set(
                session_id,
                rule_path,
                {"Enable": "1"},
            )
            if not _bbfdm_all_results_one(set_response):
                raise UbusError(f"UBUS 开启 LAN-telnet 规则失败,响应 {set_response}")
            if on_log is not None:
                on_log(EnableTelnetResult(True, "reused", f"已开启 LAN-telnet 规则 Enable (instance={x_sdmc_instance})"))
            result = EnableTelnetResult(True, "reused", "LAN-telnet 规则已开启")
        else:
            if on_log is not None:
                on_log(EnableTelnetResult(True, "already_present", "LAN-telnet 规则已启用"))
            result = EnableTelnetResult(True, "already_present", "LAN-telnet 规则已就绪")
        sleep_fn(sleep_after_seconds)
        sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS)
        return result

    # 4) 没有规则: add Device.IP.Interface.1（默认）
    try:
        iface_rule = {
            "SourceInterface": "Device.IP.Interface.1",
            "IPVersion": 4,
            "SourceIP": "0.0.0.0",
            "Application": "telnet",
        }
        if on_log is not None:
            on_log(EnableTelnetResult(True, "tx_add_iface", f"TX UBUS bbfdm.add path={ACCESS_CTRL_RULE_BASE_PATH}, obj_path={iface_rule}"))
        add_response = client.bbfdm_add(
            session_id,
            ACCESS_CTRL_RULE_BASE_PATH,
            iface_rule,
        )
        if not _bbfdm_all_results_one(add_response):
            raise UbusError(f"UBUS 添加 telnet 规则 (Device.IP.Interface.1) 失败,响应 {add_response}")
        sleep_fn(sleep_after_seconds)
        sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS)
        if on_log is not None:
            on_log(EnableTelnetResult(True, "added_iface", "已添加 Device.IP.Interface.1 telnet 规则"))
        return EnableTelnetResult(True, "added_iface", "已添加 telnet 规则")
    except UbusError:
        # 回退到 lan
        lan_rule = {
            "SourceInterface": "lan",
            "IPVersion": 4,
            "SourceIP": "0.0.0.0",
            "Application": "telnet",
        }
        if on_log is not None:
            on_log(EnableTelnetResult(True, "tx_add_lan", f"TX UBUS bbfdm.add path={ACCESS_CTRL_RULE_BASE_PATH}, obj_path={lan_rule}"))
        add_response = client.bbfdm_add(
            session_id,
            ACCESS_CTRL_RULE_BASE_PATH,
            lan_rule,
        )
        if not _bbfdm_all_results_one(add_response):
            raise UbusError(f"UBUS 添加 telnet 规则 (lan 回退) 失败,响应 {add_response}")
        sleep_fn(sleep_after_seconds)
        sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS)
        if on_log is not None:
            on_log(EnableTelnetResult(True, "added_lan_fallback", "Device.IP.Interface.1 失败,回退添加 lan telnet 规则"))
        return EnableTelnetResult(True, "added_lan_fallback", "已通过 lan 回退添加 telnet 规则")

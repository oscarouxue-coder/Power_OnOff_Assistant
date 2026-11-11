"""AI注册式PC检查：固定参数的只读命令及限定出口ICMP，不修改网络。"""
from dataclasses import asdict
import ipaddress
import subprocess
import time
from types import SimpleNamespace

from line_check_assistant.subprocess_window import hidden_window_kwargs
from src.core.wireless_ip import adapters_ipv4, validate_ping_target
from src.core.wireless_ping import run_wireless_ping
from src.utils.ai_output import decode_pc_output


NETWORK_COMMANDS = {
    "route": ["route", "print", "-4"],
    "addresses": ["ipconfig", "/all"],
    "arp": ["arp", "-a"],
    "wifi": ["netsh", "wlan", "show", "interfaces"],
}


def read_network_state(category, stop, emit):
    if category not in NETWORK_COMMANDS:
        raise ValueError("不支持的网络查询")
    args = NETWORK_COMMANDS[category]
    if stop.is_set():
        raise InterruptedError("检查已取消")
    emit("[AI网络检查] PC TX：" + " ".join(args))
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          **hidden_window_kwargs()) as process:
        deadline = time.monotonic() + 20
        try:
            while True:
                if stop.is_set():
                    raise InterruptedError("检查已取消")
                if time.monotonic() >= deadline:
                    raise TimeoutError("网络查询超过20秒")
                try:
                    output, _ = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        text, encoding = decode_pc_output(output)
        emit(f"[AI网络检查] PC RX：{category}；返回码={process.returncode}；编码={encoding}")
        return {"command": args, "returncode": process.returncode, "encoding": encoding,
                "text": text[-32768:], "scope": "PC全局只读快照；须按目标接口核对，不能据此认定DUT可达"}


def probe_connectivity(target, settings, path, stop, emit, busy, adapter_provider=adapters_ipv4,
                       ping=run_wireless_ping):
    """复用已验收的源IP+ifIndex双绑定ICMP，固定4包/2秒；不回退默认出口。"""
    if path not in ("wired", "wireless"):
        raise ValueError("不支持的出口")
    def guard():
        if stop.is_set():
            raise InterruptedError("Ping已取消")
        if busy(target):
            raise RuntimeError("设备或共享无线网卡正被测试占用，跳过Ping")
    guard()
    adapters = adapter_provider()
    if path == "wired":
        remote = target.host
        selected = [a for a in adapters if a["up"] and target.bind_ip in [v[0] for v in a["addresses"]]]
    else:
        remote = settings.get("wireless_ping_target", "")
        name = settings.get("wifi_wireless_card_name", "")
        if not name:
            raise ValueError("本次测试未明确无线接口身份，跳过；不自动选择其它网卡")
        selected = [a for a in adapters if a["up"] and a["name"] == name]
    if len(selected) != 1:
        raise ValueError("无法唯一确认目标出口接口，未发送Ping")
    validate_ping_target(remote)
    adapter = selected[0]
    if not any(not (ipaddress.IPv4Address(value[0]).is_link_local or
                    ipaddress.IPv4Address(value[0]).is_loopback or
                    ipaddress.IPv4Address(value[0]).is_unspecified) for value in adapter["addresses"]):
        raise ValueError("目标出口尚无可用IPv4地址，跳过Ping，不等待或切换网卡")
    # 有线限定已配置源IP；无线交给既有实现校验地址和接口持续一致。
    def scoped_adapters():
        values = adapter_provider()
        if path == "wired":
            values = [dict(a, addresses=tuple(v for v in a["addresses"] if v[0] == target.bind_ip))
                      if a["index"] == adapter["index"] else a for a in values]
        return values
    emit(f"[AI网络检查] 开始{path} Ping：接口={adapter['name']}；目标={remote}；固定4包/每包2秒")
    result = ping(SimpleNamespace(**{k: adapter[k] for k in ("name", "index", "guid")}),
                  remote, stop, emit, guard, adapter_provider=scoped_adapters)
    return {"path": path, "interface": adapter["name"], "if_index": adapter["index"],
            "result": asdict(result), "scope": "本次主动查询，不代表故障时状态"}

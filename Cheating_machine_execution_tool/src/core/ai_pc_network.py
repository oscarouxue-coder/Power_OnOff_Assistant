"""AI目标网卡只读取证；不启停网卡、不修改地址、不发送探测包。"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import time

from line_check_assistant.subprocess_window import hidden_window_kwargs
from src.utils.ai_output import decode_pc_output


# 固定脚本不插入配置值；使用数值状态，避免本地化显示文本影响判断。
ADAPTER_QUERY = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$addresses=@(Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore)
$adapters=@(Get-NetAdapter -IncludeHidden)
ConvertTo-Json -Depth 5 -Compress -InputObject @($adapters | ForEach-Object {
  $adapter=$_
  [PSCustomObject]@{
    name=[string]$adapter.Name; guid=[string]$adapter.InterfaceGuid
    index=$adapter.InterfaceIndex; status=[string]$adapter.Status
    admin_status=$adapter.InterfaceAdminStatus
    operational_status=$adapter.InterfaceOperationalStatus
    media_state=$adapter.MediaConnectState
    addresses=@($addresses | Where-Object {$_.InterfaceIndex -eq $adapter.InterfaceIndex} |
      ForEach-Object {[PSCustomObject]@{
        ip=[string]$_.IPAddress; prefix=$_.PrefixLength; state=[string]$_.AddressState
      }})
  }
})
"""
QUERY_TIMEOUT = 20
OUTPUT_LIMIT = 1024 * 1024


def _query(stop, emit):
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ADAPTER_QUERY]
    if stop.is_set():
        raise InterruptedError("网卡查询已取消")
    emit("[AI采集] PC TX：" + " ".join(args))
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          **hidden_window_kwargs()) as process:
        deadline = time.monotonic() + QUERY_TIMEOUT
        try:
            while True:
                if stop.is_set():
                    raise InterruptedError("网卡查询已取消")
                if time.monotonic() >= deadline:
                    raise TimeoutError("网卡只读查询超过20秒")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    if stop.is_set():
        raise InterruptedError("网卡查询已取消")
    if len(stdout) > OUTPUT_LIMIT or len(stderr) > OUTPUT_LIMIT:
        raise ValueError("网卡查询输出超过1MiB，未用不完整枚举判断接口状态")
    text, encoding = decode_pc_output(stdout)
    emit(f"[AI采集] PC RX：目标网卡查询；返回码={process.returncode}；编码={encoding}")
    if process.returncode:
        error, _ = decode_pc_output(stderr)
        raise RuntimeError("网卡查询失败：" + (error.strip()[:1500] or str(process.returncode)))
    # 不把损坏输出或空输出当作“没有网卡”。
    return json.loads(text.lstrip("\ufeff"))


def _normalize(items):
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError("网卡查询返回格式无效")
    result = []
    for item in items:
        if not isinstance(item, dict) or not all(key in item for key in (
                "name", "guid", "index", "admin_status", "operational_status", "media_state", "addresses")):
            raise ValueError("网卡查询缺少身份或状态字段")
        if (not isinstance(item["name"], str) or not item["name"].strip() or
                not isinstance(item["guid"], str) or not item["guid"].strip() or
                type(item["index"]) is not int or item["index"] <= 0):
            raise ValueError("网卡身份无效")
        for key in ("admin_status", "operational_status", "media_state"):
            if item[key] is not None and type(item[key]) is not int:
                raise ValueError("网卡状态不是数值")
        addresses = item["addresses"]
        if not isinstance(addresses, list):
            raise ValueError("网卡IPv4列表无效")
        for address in addresses:
            if (not isinstance(address, dict) or not isinstance(address.get("state"), str) or
                    type(address.get("prefix")) is not int or not 0 <= address["prefix"] <= 32):
                raise ValueError("网卡IPv4信息不完整")
            ipaddress.IPv4Address(address.get("ip"))
        result.append(dict(item, name=item["name"].strip(), addresses=addresses))
    return result


def assess_adapters(target, items):
    """只依据本次完整枚举分类；source_usable为None表示不能确认。"""
    adapters = _normalize(items)
    alias = target.vlan.strip().casefold()
    named = [a for a in adapters if a["name"].casefold() == alias] if alias else []
    holders = [a for a in adapters if any(v["ip"] == target.bind_ip for v in a["addresses"])]
    result = {"query_status": "ok", "configured_alias": target.vlan, "configured_source": target.bind_ip,
              "adapters_seen": len(adapters), "source_usable": None, "match_basis": "none"}
    # 无任何接口持有该源地址是完整枚举事实，不等同于网卡被禁用。
    if not holders:
        result["source_usable"] = False
    if len(named) > 1 or len(holders) > 1 or (named and holders and named[0] != holders[0]):
        result.update(status="identity_conflict", conclusion="配置别名与源IP归属冲突或候选不唯一，目标身份待核对",
                      source_usable=None, candidates=[_brief(a, target.bind_ip) for a in
                          (named + [a for a in holders if a not in named])[:8]],
                      candidate_count=len(named + [a for a in holders if a not in named]))
        return result
    if not named:
        if holders:
            result.update(status="identity_unconfirmed", match_basis="unique_source_ip_candidate",
                          conclusion="配置别名未命中，仅源IP命中候选，不能认定为原目标网卡",
                          candidates=[_brief(a, target.bind_ip) for a in holders])
        else:
            result.update(status="adapter_not_found", conclusion="本次枚举未找到配置目标接口，且没有接口持有配置源IP")
        return result
    adapter = named[0]
    result.update(match_basis="exact_alias", adapter=_brief(adapter, target.bind_ip))
    # MSFT_NetAdapter: InterfaceAdminStatus 2=Down；MediaConnectState 2=Disconnected。
    if adapter["admin_status"] == 2:
        result.update(status="disabled", conclusion="已确认目标网卡管理状态为禁用，配置源IP当前不可用于该接口",
                      source_usable=False)
    elif adapter["media_state"] == 2:
        result.update(status="link_disconnected", conclusion="目标网卡链路未接通；不能仅凭此认定网卡被禁用或网线损坏",
                      source_usable=False if not holders else None)
    elif not holders:
        result.update(status="source_ip_missing", conclusion="目标接口存在，但配置源IP当前未出现在任何接口上",
                      source_usable=False)
    elif not any(v["ip"] == target.bind_ip and v["state"].casefold() == "preferred"
                 for v in adapter["addresses"]):
        invalid = all(v["state"].casefold() in ("invalid", "tentative", "duplicate")
                      for v in adapter["addresses"] if v["ip"] == target.bind_ip)
        result.update(status="source_ip_unready", conclusion="配置源IP存在但地址状态不是Preferred，需要核对",
                      source_usable=False if invalid else None)
    elif adapter["admin_status"] == 1 and adapter["operational_status"] == 1 and adapter["media_state"] == 1:
        result.update(status="ready", conclusion="目标网卡及配置IPv4当前就绪；尚未验证DUT可达", source_usable=True)
    else:
        result.update(status="unknown", conclusion="目标网卡运行状态异常或信息不足，不能确定具体原因")
    return result


def _brief(adapter, source):
    # 先用完整枚举判断，再缩减展示；目标源地址始终保留，避免地址数量挤掉关键证据。
    addresses = sorted(adapter["addresses"], key=lambda a: a["ip"] != source)
    return dict({key: adapter[key] for key in ("name", "guid", "index", "admin_status",
                "operational_status", "media_state")}, status=adapter.get("status", ""),
                addresses=addresses[:32], address_count=len(addresses), addresses_truncated=len(addresses) > 32)


def read_target_network(target, stop, emit):
    result = {"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "scope": "当前只读快照，不代表故障时状态；不验证DUT可达性"}
    try:
        if stop.is_set():
            raise InterruptedError("网卡查询已取消")
        if os.name != "nt":
            raise RuntimeError("目标网卡查询仅支持Windows")
        result.update(assess_adapters(target, _query(stop, emit)))
        emit(f"[AI采集] 目标网卡：{target.vlan}；匹配={result['match_basis']}；{result['conclusion']}")
    except InterruptedError:
        emit("[AI采集] 目标网卡查询已取消")
        raise
    except Exception as exc:
        result.update(query_status="failed", status="query_failed", source_usable=None,
                      conclusion="网卡查询失败，不能据此认定接口不存在或DUT故障", error=str(exc)[:2000])
        emit("[AI采集] 目标网卡查询失败：" + result["error"])
    return result

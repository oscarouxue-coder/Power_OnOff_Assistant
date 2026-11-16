"""模型网关失败后的有界取证；沿用配置源地址，不修改路由/代理或重发HTTP。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from urllib.parse import urlsplit

import requests

from line_check_assistant.subprocess_window import hidden_window_kwargs


DIAGNOSTIC_TIMEOUT = 8
OUTPUT_LIMIT = 65536
# 固定脚本，目标只通过stdin JSON传递；不插值到PowerShell命令。
# 每完成一个阶段即输出JSON行；外层超时仍可保留前面的TCP证据。
NETWORK_QUERY = r"""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
function Write-Evidence($value) {
  [Console]::WriteLine('AIGW:' + (ConvertTo-Json -Compress -Depth 5 -InputObject $value))
}
$config=ConvertFrom-Json ([Console]::In.ReadToEnd())
$probes=@{}
foreach ($target in $config) {
  $result=@{kind='tcp'; label=[string]$target.label; host=[string]$target.host;
    port=[int]$target.port; ips=@(); source=''; peer=''; status='unknown'; code=''}
  $client=$null
  try {
    $lookup=[System.Net.Dns]::BeginGetHostAddresses([string]$target.host,$null,$null)
    if (-not $lookup.AsyncWaitHandle.WaitOne(1000)) {
      $result.status='dns_timeout'
    } else {
      $addresses=@([System.Net.Dns]::EndGetHostAddresses($lookup))
      $result.ips=@($addresses | Select-Object -First 8 | ForEach-Object {$_.ToString()})
      if ($addresses.Count -gt 0) {
        $until=[DateTime]::UtcNow.AddMilliseconds(2000)
        foreach ($address in ($addresses | Select-Object -First 2)) {
          $client=[System.Net.Sockets.TcpClient]::new($address.AddressFamily)
          try {
            if ($target.source_ip) {
              $source=[System.Net.IPAddress]::Parse([string]$target.source_ip)
              $client.Client.Bind([System.Net.IPEndPoint]::new($source,0))
            }
            $pending=$client.BeginConnect($address,[int]$target.port,$null,$null)
            $remaining=[Math]::Max(0, [int]($until-[DateTime]::UtcNow).TotalMilliseconds)
            if (-not $pending.AsyncWaitHandle.WaitOne($remaining)) {
              $result.status='tcp_timeout'
            } else {
              $client.EndConnect($pending)
              $result.status='connected'
              $result.source=$client.Client.LocalEndPoint.Address.ToString()
              $result.peer=$client.Client.RemoteEndPoint.Address.ToString()
              break
            }
          } catch {
            $result.status='tcp_failed'
            $errorValue=$_.Exception
            while ($errorValue.InnerException) {$errorValue=$errorValue.InnerException}
            if ($errorValue -is [System.Net.Sockets.SocketException]) {$result.code=[string]$errorValue.NativeErrorCode}
          } finally {$client.Close(); $client=$null}
          if ([DateTime]::UtcNow -ge $until) {break}
        }
      } else {$result.status='dns_empty'}
    }
  } catch {
    $result.status='dns_failed'
    $errorValue=$_.Exception
    while ($errorValue.InnerException) {$errorValue=$errorValue.InnerException}
    if ($errorValue -is [System.Net.Sockets.SocketException]) {$result.code=[string]$errorValue.NativeErrorCode}
  } finally {if ($null -ne $client) {$client.Close()}}
  Write-Evidence $result
  $probes[[string]$target.label]=$result
}
foreach ($target in $config) {
  $probe=$probes[[string]$target.label]
  if ($probe.source) {
    try {
      $interfaces=@(Get-NetIPAddress -IPAddress ([string]$probe.source) -ErrorAction Stop)
      Write-Evidence @{kind='interface'; label=[string]$target.label; source=[string]$probe.source;
        matches=@($interfaces | ForEach-Object {@{name=[string]$_.InterfaceAlias; index=[int]$_.InterfaceIndex}})}
    } catch {Write-Evidence @{kind='interface'; label=[string]$target.label; source=[string]$probe.source; matches=@()}}
  }
  try {
    $remote=if ($probe.peer) {$probe.peer} elseif ($probe.ips.Count -gt 0) {$probe.ips[0]} else {''}
    if (-not $remote) {throw 'unresolved'}
    $routes=@(Find-NetRoute -RemoteIPAddress ([string]$remote) -ErrorAction Stop)
    $source=@($routes | Where-Object {$_.PSObject.Properties['IPAddress']} | Select-Object -First 1)
    if ($source.Count -gt 0) {
      Write-Evidence @{kind='route'; label=[string]$target.label; status='ok';
        source=[string]$source[0].IPAddress; interface=[string]$source[0].InterfaceAlias;
        index=[int]$source[0].InterfaceIndex}
    } else {Write-Evidence @{kind='route'; label=[string]$target.label; status='unknown'}}
  } catch {Write-Evidence @{kind='route'; label=[string]$target.label; status='unavailable'}}
}
"""


def _endpoint(value, label):
    parts = urlsplit(value if "://" in value else "http://" + value)
    if not parts.hostname:
        raise ValueError("missing host")
    port = parts.port or (443 if parts.scheme == "https" else 1080 if parts.scheme.startswith("socks") else 80)
    return {"label": label, "host": parts.hostname, "port": port}


def proxy_snapshot(session, url):
    """按Requests相同的合并规则取快照，只留下不含认证信息的端点。"""
    if not isinstance(session, requests.Session):
        return {"status": "unknown"}
    try:
        settings = session.merge_environment_settings(url, {}, True, None, None)
        proxy = requests.utils.select_proxy(url, settings["proxies"])
        bypass = bool(session.trust_env and requests.utils.should_bypass_proxies(
            url, no_proxy=os.environ.get("no_proxy", os.environ.get("NO_PROXY"))))
        # 显式Session代理仍可能生效；命中绕过规则不等于最终请求绕过代理。
        return {"status": "proxy" if proxy else "direct", "no_proxy_bypass": bypass and not proxy,
                "endpoint": _endpoint(proxy, "代理") if proxy else None}
    except (ValueError, TypeError, KeyError, OSError):
        return {"status": "unknown"}


def transport_error(exc):
    """只读异常类型/数值错误码；不拼接可能含密钥的异常原文。"""
    nodes, seen, codes = [exc], set(), []
    dns = False
    for node in nodes:
        if id(node) in seen or len(seen) >= 24:
            continue
        seen.add(id(node))
        dns |= isinstance(node, socket.gaierror)
        for name in ("errno", "winerror"):
            code = getattr(node, name, None)
            if type(code) is int and code not in codes:
                codes.append(code)
        for child in (getattr(node, "reason", None), getattr(node, "__cause__", None),
                      getattr(node, "__context__", None), *getattr(node, "args", ())):
            if isinstance(child, BaseException) and id(child) not in seen:
                nodes.append(child)
    category = ("代理连接失败" if isinstance(exc, requests.exceptions.ProxyError) else
                "TLS证书或握手失败" if isinstance(exc, requests.exceptions.SSLError) else
                "连接超时" if isinstance(exc, requests.ConnectTimeout) else
                "读取超时" if isinstance(exc, requests.ReadTimeout) else
                "请求超时" if isinstance(exc, requests.Timeout) else
                "DNS解析失败" if dns else "连接失败")
    suffix = "；系统错误码=" + ",".join(map(str, codes)) if codes else ""
    return category + "（" + type(exc).__name__ + "）" + suffix


def _probe(targets, stop):
    if stop is not None and stop.is_set():
        raise InterruptedError("网络诊断已取消")
    if os.name != "nt":
        return [], "仅Windows支持接口查询"
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", NETWORK_QUERY]
    data = json.dumps(targets, ensure_ascii=True).encode("ascii")
    deadline = time.monotonic() + DIAGNOSTIC_TIMEOUT
    note = ""
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          **hidden_window_kwargs()) as process:
        try:
            while True:
                if stop is not None and stop.is_set():
                    raise InterruptedError("网络诊断已取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    stdout, _ = process.communicate()
                    note = "诊断达到8秒时限；保留已完成阶段"
                    break
                try:
                    stdout, _ = process.communicate(input=data, timeout=min(0.2, remaining))
                    if process.returncode:
                        note = "只读查询未完整完成"
                    break
                except subprocess.TimeoutExpired:
                    data = None  # communicate只允许首次发送stdin。
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    if stop is not None and stop.is_set():
        raise InterruptedError("网络诊断已取消")
    records = []
    for line in stdout[:OUTPUT_LIMIT].decode("utf-8-sig", errors="replace").splitlines():
        if line.startswith("AIGW:"):
            try:
                item = json.loads(line[5:])
                if isinstance(item, dict):
                    records.append(item)
            except ValueError:
                pass
    return records, note


def collect_gateway_network(url, proxy, stop=None, emit=lambda _line: None, *, source_ip=""):
    """取证失败不替代请求错误；取消仍传给上层，结果不得当作原HTTP出口。"""
    if stop is not None and stop.is_set():
        raise InterruptedError("网络诊断已取消")
    target = _endpoint(url, "网关")
    targets = [target]
    status = proxy.get("status", "unknown")
    proxy_note = {"proxy": "命中代理", "direct": "直连", "unknown": "未知"}.get(status, "未知")
    if proxy.get("endpoint"):
        targets.append(dict(proxy["endpoint"]))
        proxy_note += " " + proxy["endpoint"]["host"] + ":" + str(proxy["endpoint"]["port"])
    if source_ip:
        for endpoint in targets:
            endpoint["source_ip"] = source_ip
    lines = [f"目标={target['host']}:{target['port']}；当前有效代理={proxy_note}；"
             f"NO_PROXY绕过={'是' if proxy.get('no_proxy_bypass') else '否' if status != 'unknown' else '未知'}；"
             f"配置源IP={source_ip or '不指定（自动选择）'}",
             "原失败HTTP请求实际接口/源IP=未知；以下是失败后的当前探测，TCP成功仅表示端口可连接"]
    binding = "绑定配置源IP=" + source_ip if source_ip else "不绑定源IP"
    emit("[AI网络] PC TX：PowerShell Dns.BeginGetHostAddresses / TcpClient.BeginConnect（" + binding + "）/ "
         "Get-NetIPAddress -IPAddress <探测源IP> / Find-NetRoute -RemoteIPAddress <目标IP>；" + lines[0])
    try:
        records, note = _probe(targets, stop)
        for item in records:
            if item.get("kind") == "tcp":
                lines.append(f"{item.get('label')}解析IP={','.join(item.get('ips') or []) or '未知'}；"
                             f"TCP={item.get('status')}；对端IP={item.get('peer') or '未知'}；"
                             f"探测实际源IP={item.get('source') or '未知'}；错误码={item.get('code') or '无'}")
            elif item.get("kind") == "route":
                lines.append(f"{item.get('label')}当前路由选择={item.get('status')}；"
                             f"接口={item.get('interface') or '未知'}/{item.get('index') or '未知'}；"
                             f"路由源IP={item.get('source') or '未知'}（路由推断，不代表原HTTP请求出口）")
            elif item.get("kind") == "interface":
                matches = item.get("matches") or []
                identity = (str(matches[0].get("name")) + "/" + str(matches[0].get("index"))
                            if len(matches) == 1 else "未知（源IP对应接口不唯一或查询失败）")
                lines.append(f"{item.get('label')}TCP探测实际源IP={item.get('source')}；对应接口={identity}")
        for endpoint in targets:
            label = endpoint["label"]
            kinds = {item.get("kind") for item in records if item.get("label") == label}
            if "tcp" not in kinds:
                lines.append(label + "TCP/探测源IP=未知；未取得完整探测信息")
            if "interface" not in kinds:
                lines.append(label + "探测实际接口=未知")
            if "route" not in kinds:
                lines.append(label + "当前路由接口/源IP=未知")
        if note:
            lines.append(note)
    except InterruptedError:
        emit("[AI网络] 已取消")
        raise
    except Exception as exc:
        # 固定分类，不泄露子进程stderr或代理认证信息。
        lines.append("网络诊断失败：" + type(exc).__name__ + "；TCP/出站接口/源IP=未知")
    summary = "；".join(lines)
    emit("[AI网络] " + summary)
    return summary

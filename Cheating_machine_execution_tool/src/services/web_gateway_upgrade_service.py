"""Web gateway upload preparation and independent parallel dispatch."""
import ipaddress
import json
import os
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.gateway_browser import GatewayBrowser, find_gateway_browser

TRANSFER_WEB_GATEWAY = "web打开网关"
WEB_SUBMIT_WAIT_SECONDS = 30


def validate_web_target(source_ip, device_ip, subnet_mask):
    source = ipaddress.IPv4Address(source_ip)
    target = ipaddress.IPv4Address(device_ip)
    network = ipaddress.IPv4Network(f"{source}/{subnet_mask}", strict=False)
    if (source == target or source.is_unspecified or source.is_multicast
            or target.is_unspecified or target.is_multicast
            or source in (network.network_address, network.broadcast_address)
            or target in (network.network_address, network.broadcast_address)):
        raise ValueError("Web升级的PC地址和样机管理IP必须是不同的有效单播IPv4地址。")
    if target not in network:
        raise ValueError("Web升级的通道PC静态IP与主界面样机管理IP不在同一子网，请先核对通道配置。")


def selected_interface_index(alias, source_ip):
    """Read exact adapter ownership after network preparation; never guess by route."""
    env = dict(os.environ, LINE_CHECK_WEB_ALIAS=alias, LINE_CHECK_WEB_IP=source_ip)
    script = (
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$a=@(Get-NetAdapter -IncludeHidden | Where-Object {$_.Name -eq $env:LINE_CHECK_WEB_ALIAS}); "
        "if($a.Count -ne 1){throw 'VLAN adapter is not unique'}; "
        "$ips=@(Get-NetIPAddress -InterfaceIndex $a[0].ifIndex -AddressFamily IPv4 | "
        "Where-Object {$_.IPAddress -eq $env:LINE_CHECK_WEB_IP}); "
        "if($ips.Count -ne 1){throw 'Source IP is not on selected VLAN'}; "
        "[int]$a[0].ifIndex | ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"无法确认Web出口网卡 {alias} / {source_ip}：{result.stderr.strip()}")
    index = int(json.loads(result.stdout.strip().lstrip("\ufeff")))
    if index <= 0:
        raise RuntimeError("Web出口网卡索引无效。")
    return index


def start_gateway_upgrade(request, emit, sleep_fn=time.sleep):
    validate_web_target(request.web_source_ip, request.web_device_ip, request.web_subnet_mask)
    prepared = prepare_network_for_sample(request.server_interface, request.web_source_ip,
                                          request.web_subnet_mask, on_output=emit,
                                          sleep_fn=sleep_fn, settle_seconds=1.0, reuse_if_ready=True)
    if not prepared.ok:
        raise RuntimeError(prepared.message)
    if not wait_for_bindable_ip(request.web_source_ip, 15):
        raise RuntimeError(f"Web出口IP {request.web_source_ip} 在15秒内仍不可绑定。")
    index = selected_interface_index(request.server_interface, request.web_source_ip)
    browser = GatewayBrowser(request.web_source_ip, index, request.web_device_ip, emit)
    try:
        browser.start()
        browser.submit_firmware(request.firmware_path)
        emit("Web 提交动作完成，固定等待 30 秒；不等待网页变化、不重复点击。")
        sleep_fn(WEB_SUBMIT_WAIT_SECONDS)
        emit("Web 提交后 30 秒等待结束，开始原有 90 秒 Boot/Bood 观察流程。")
        return browser
    except Exception:
        browser.close()
        raise


def run_parallel_web_gateway_upgrades(requests, session_manager, *, max_workers=2,
                                      on_output=None, on_session_ready=None,
                                      on_item_started=None, on_item_complete=None):
    # Local import keeps the existing serial module independent at import time.
    from .serial_upgrade_service import (FullPackageUpgradeItemResult, UpgradePowerCycleCoordinator,
                                         run_single_full_package_upgrade)
    all_requests = list(requests)
    if not 1 <= max_workers <= 8:
        raise ValueError("Web升级并行数必须为1–8。")
    seen_vlans, seen_sources, seen_ports = set(), set(), set()
    for request in all_requests:
        if request.transfer_method != TRANSFER_WEB_GATEWAY:
            raise ValueError("Web升级批次仅支持 web打开网关。")
        validate_web_target(request.web_source_ip, request.web_device_ip, request.web_subnet_mask)
        if not request.firmware_path.is_file():
            raise ValueError(f"升级固件不存在：{request.firmware_path}")
        port = request.serial_port or request.vlan
        if request.server_interface.lower() in seen_vlans or request.web_source_ip in seen_sources or port.lower() in seen_ports:
            raise ValueError("Web升级批次存在重复VLAN、PC源IP或串口，未启动升级。")
        seen_vlans.add(request.server_interface.lower())
        seen_sources.add(request.web_source_ip)
        seen_ports.add(port.lower())
    find_gateway_browser()  # No power operations when the required browser is absent.
    pending, active, completed = list(all_requests), {}, {}

    def run_one(request, coordinator):
        return run_single_full_package_upgrade(
            request, session_manager,
            on_output=lambda line: on_output(request.vlan, line) if on_output else None,
            on_session_ready=on_session_ready, power_cycle_coordinator=coordinator,
        )

    with UpgradePowerCycleCoordinator() as coordinator, ThreadPoolExecutor(max_workers=max_workers) as executor:
        while pending or active:
            while pending and len(active) < max_workers:
                request = pending.pop(0)
                if on_item_started:
                    on_item_started(request)
                active[executor.submit(run_one, request, coordinator)] = request
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                request = active.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    from line_check_assistant.network_ops import CommandResult
                    result = CommandResult(False, f"{request.vlan} Web升级异常：{exc}")
                item = FullPackageUpgradeItemResult(request, result)
                completed[id(request)] = item
                if on_item_complete:
                    on_item_complete(item)
    return [completed[id(request)] for request in all_requests]

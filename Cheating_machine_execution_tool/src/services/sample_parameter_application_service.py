"""Shared parameter-write application service extracted without command/timing changes.

The GUI supplies immutable network data and UI-only event callbacks. Agent calls
this same service; no window, Tk variable or GUI lifecycle enters the pipeline.
"""
from __future__ import annotations

from src.services.sample_parameter_service import (run_parallel_sample_parameter_writes,
    PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)

def run_sample_parameter_batch(requests, parallel_count, cancel_event, session_manager, network, on_output, on_session_ready=None, serial_runner=None):
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.config import DEFAULT_LOG_DIR
    from src.core.bind_socket import wait_for_bindable_ip as _wait_for_bindable_ip
    from src.core.telnet_transport import TelnetSession
    from src.core.ubus_enable_telnet import enable_telnet_via_ubus
    from src.core.ubus_http_client import UbusHttpClient
    from src.models import SampleParameterItemResult
    from src.services.sample_parameter_service import run_single_sample_parameter_write
    from line_check_assistant.network_ops import prepare_network_for_sample
    on_output(f'开始批量写样机参数：{len(requests)} 台，并行上限 {parallel_count}。')

    def emit_to_main(line: str) -> None:
        on_output(line)
    UBUS_ENABLE_TELNET_MAX_RETRIES = 3
    UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS = 2.0
    telnet_indices = [index for (index, req) in enumerate(requests) if req.bind_ip and req.device_host]
    serial_indices = [index for (index, req) in enumerate(requests) if index not in telnet_indices]

    def make_telnet_factory(request):

        def factory(r):
            if not r.bind_ip or not r.device_host:
                raise RuntimeError(f'{r.vlan} 切 telnet 路径但 bind_ip / device_host 为空')
            adapter_alias = network[r.vlan.lower()][0]
            subnet_mask = network[r.vlan.lower()][1]
            if adapter_alias and r.bind_ip:
                emit_to_main(f"{r.vlan} 写参前置:准备网络 {adapter_alias}({r.bind_ip} / {subnet_mask or '255.255.255.0'})。")
                network_result = prepare_network_for_sample(adapter_alias, r.bind_ip, subnet_mask, on_output=emit_to_main, sleep_fn=time.sleep, reuse_if_ready=True)
                if not network_result.ok:
                    emit_to_main(f'{r.vlan} 写参前置:网络准备失败:{network_result.message}')
                    raise RuntimeError(f'{r.vlan} 网络准备失败:{network_result.message}')
                if not _wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0):
                    emit_to_main(f'{r.vlan} 写参前置:{r.bind_ip} 仍未成为可绑地址,放弃本台。')
                    raise RuntimeError(f'{r.vlan} 网络准备后 {r.bind_ip} 仍不可绑')
            log_path = DEFAULT_LOG_DIR / f'sample_parameter_{r.vlan}_{r.bind_ip}.log'
            emit_to_main(f'{r.vlan} 写参前置：UBUS 启用 telnet 中 ({r.device_host})。')
            enable_result = None
            for _attempt in range(1, UBUS_ENABLE_TELNET_MAX_RETRIES + 2):
                if _attempt > 1:
                    emit_to_main(f'{r.vlan} UBUS 启用 telnet 第 {_attempt - 1}/{UBUS_ENABLE_TELNET_MAX_RETRIES} 次重试,等待 {UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS} 秒...')
                    time.sleep(UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS)
                ubus_client = UbusHttpClient(r.bind_ip, r.device_host, ubus_port=r.ubus_port)
                try:
                    try:
                        enable_result = enable_telnet_via_ubus(ubus_client, r.initial_username, r.initial_password, on_log=lambda ev: emit_to_main(f'{r.vlan} UBUS: {ev.message}'), sleep_fn=lambda _seconds: None, sleep_after_seconds=0.0)
                    finally:
                        ubus_client.close()
                    break
                except Exception as exc:
                    emit_to_main(f'{r.vlan} 写参前置：UBUS 启用 telnet 失败：{exc}')
                    if _attempt > UBUS_ENABLE_TELNET_MAX_RETRIES:
                        raise
            emit_to_main(f'{r.vlan} UBUS 启用 telnet {enable_result.action}: {enable_result.message}')
            return TelnetSession(r.bind_ip, r.device_host, log_path=log_path, known_secrets=(r.initial_password,))
        return factory

    def make_factory_session_swap(request):
        """工厂模式 100 秒等待后的会话切换回调。

        流程:
          1. 关闭旧 TelnetSession(样机管理 IP 已切到工厂模式网段,旧 socket 已无意义);
          2. 调用 ``prepare_network_for_sample`` 把 PC VLAN 网卡切到
             ``request.factory_bind_ip / factory_device_host`` 同一网段;
          3. 调用 ``wait_for_bindable_ip`` 等 Windows 把新 IP 注册为可绑定地址;
          4. 创建新 TelnetSession 指向工厂模式管理 IP 后返回。
        失败时 (缺字段 / 切网段失败 / 新建会话失败) 返回 None,pipeline 视作放弃本台。
        """
        if not request.factory_bind_ip or not request.factory_device_host:
            emit_to_main(f'{request.vlan} 工厂模式网段切换：缺少 factory_bind_ip / factory_device_host,放弃本台。')
            return None

        def swap(old_session):
            try:
                old_session.close()
            except Exception as exc:
                emit_to_main(f'{request.vlan} 工厂模式网段切换：关闭旧 TelnetSession 异常(忽略):{exc}')
            adapter_alias = network[request.vlan.lower()][0]
            subnet_mask = network[request.vlan.lower()][1]
            if not adapter_alias:
                emit_to_main(f'{request.vlan} 工厂模式网段切换：未找到 VLAN {request.vlan} 的 adapter_alias,放弃本台。')
                return None
            emit_to_main(f"{request.vlan} 工厂模式网段切换：准备把 {adapter_alias} 设为 {request.factory_bind_ip}（{subnet_mask or '255.255.255.0'}）,样机目标 {request.factory_device_host}。")
            result = prepare_network_for_sample(adapter_alias, request.factory_bind_ip, subnet_mask, on_output=emit_to_main, sleep_fn=time.sleep, reuse_if_ready=True)
            if not result.ok:
                emit_to_main(f'{request.vlan} 工厂模式网段切换失败：{result.message}')
                return None
            if not _wait_for_bindable_ip(request.factory_bind_ip, timeout_seconds=15.0):
                emit_to_main(f'{request.vlan} 工厂模式网段切换：{request.factory_bind_ip} 仍未成为可绑地址,放弃本台。')
                return None
            new_log_path = DEFAULT_LOG_DIR / f'sample_parameter_{request.vlan}_{request.factory_bind_ip}.log'
            try:
                new_session = TelnetSession(request.factory_bind_ip, request.factory_device_host, log_path=new_log_path, known_secrets=(request.initial_password,))
            except Exception as exc:
                emit_to_main(f'{request.vlan} 工厂模式重建 TelnetSession 失败：{exc}')
                return None
            emit_to_main(f'{request.vlan} 工厂模式重建 TelnetSession 成功（{request.factory_bind_ip} → {request.factory_device_host}）。')
            return new_session
        return swap
    results: list[SampleParameterItemResult | None] = [None] * len(requests)
    if serial_indices:
        serial_requests = [requests[i] for i in serial_indices]
        serial_results = (serial_runner or run_parallel_sample_parameter_writes)(serial_requests, session_manager, parallel_count=parallel_count, on_output=emit_to_main, on_session_ready=on_session_ready, cancel_event=cancel_event)
        for (offset, serial_index) in enumerate(serial_indices):
            results[serial_index] = serial_results[offset]
    if telnet_indices:
        telnet_requests = [requests[i] for i in telnet_indices]
        with ThreadPoolExecutor(max_workers=min(parallel_count, len(telnet_requests)), thread_name_prefix='sample-parameter-telnet') as executor:
            telnet_futures: dict = {}
            for (offset, req) in enumerate(telnet_requests):
                if offset > 0:
                    time.sleep(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)
                future = executor.submit(run_single_sample_parameter_write, req, session_manager, emit_to_main, None, cancel_event, time.sleep, make_telnet_factory(req), make_factory_session_swap(req))
                telnet_futures[future] = telnet_indices[offset]
            for future in as_completed(telnet_futures):
                telnet_results_index = telnet_futures[future]
                try:
                    results[telnet_results_index] = future.result()
                except Exception as exc:
                    req = requests[telnet_results_index]
                    results[telnet_results_index] = SampleParameterItemResult(req, False, f'{req.vlan} telnet 写参启动失败：{exc}', cancelled=cancel_event.is_set())
    final = [r if isinstance(r, SampleParameterItemResult) else SampleParameterItemResult(requests[idx], False, '未运行') for (idx, r) in enumerate(results)]
    return final

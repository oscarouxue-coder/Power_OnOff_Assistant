"""Typed read-only replacements for observed local-command uses; never interprets shell text."""
from pathlib import Path
import socket
import threading
import uuid

from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema
from src.services.ai_pc_conversation import PcConversationExecutor
from src.core.ai_network_probe import read_network_state
from src.core.serial_inventory import list_serial_port_names
from line_check_assistant.network_ops import list_adapter_display_names


class ControlledHost:
    def __init__(self, service):
        self.service = service
        self.serial_provider, self.adapter_provider = list_serial_port_names, list_adapter_display_names
        add = service.registry.register
        add(CapabilitySpec('resources.refresh', '刷新串口和网卡资源清单',
            '调用GUI使用的现有只读枚举源，返回当前候选和授权通道的当前选择；内部串行查询，不打开COM、不自动改绑定。',
            object_schema(), self.refresh))
        add(CapabilitySpec("host.environment", "本机环境查询", "固定只读系统、路由、地址及无线状态查询，不执行任意PowerShell。",
            object_schema(), lambda a, auth: PcConversationExecutor(threading.Event(), service.emit).execute("read_pc_environment", {})))
        add(CapabilitySpec("host.network", "本机网络状态", "固定只读网络查询。", object_schema({
            "category": dict(type="string", enum=["route", "addresses", "arp", "wifi"])}, ("category",)),
            lambda a, auth: read_network_state(a["category"], threading.Event(), service.emit)))
        add(CapabilitySpec("host.serial_ports", "串口枚举", "枚举串口名称，不打开COM。", object_schema(),
            lambda a, auth: dict(ports=list_serial_port_names())))
        add(CapabilitySpec("host.processes", "进程只读快照", "读取进程编号、名称和状态，不终止进程或读取命令行凭据。",
            object_schema(), self.processes))
        add(CapabilitySpec("network.test_port", "锁源TCP连通性检查", "按明确通道源IP探测目标端口；不登录、不修改路由或IP。",
            object_schema({"channel_ids": dict(type="array", minItems=1, maxItems=1,
                items=dict(type="integer", minimum=1, maximum=16)), "port": dict(type="integer", minimum=1, maximum=65535)},
                ("channel_ids", "port")), self.test_port))

    def processes(self, arguments, authority):
        import psutil
        result = []
        for process in psutil.process_iter(("pid", "name", "status")):
            if len(result) >= 200:
                break
            try:
                result.append(process.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return dict(items=result, truncated=len(result) >= 200)

    def refresh(self, arguments, authority):
        with self.service.resources.lease('inventory:' + uuid.uuid4().hex, ('inventory-query',)):
            ports = self.serial_provider()
            adapters = self.adapter_provider()
            selected = self.service._channels({}, authority)['channels']
            self.service.emit('[资源刷新] 已读取当前串口/网卡清单；保留现有绑定，未打开COM或更改网卡')
            return dict(serial_ports=list(ports), adapters=list(adapters), current_channels=selected,
                        selection_changed=False)

    def test_port(self, arguments, authority):
        if self.service.devices is None:
            raise CapabilityError("target_unavailable", "当前未接入设备通道服务")
        snapshot, channels = self.service.devices.selected(arguments, authority)
        channel = channels[0]
        if not channel.network_card_ip or not channel.device_manage_ip:
            raise CapabilityError("invalid_target", "缺少通道源IP或样机管理IP")
        with self.service.resources.lease("probe:" + uuid.uuid4().hex, ("device-business",)):
            try:
                with socket.create_connection((channel.device_manage_ip, arguments["port"]), timeout=3,
                                              source_address=(channel.network_card_ip, 0)):
                    return dict(reachable=True, channel=channel.section, port=arguments["port"], notice="仅TCP端口可达，不代表业务通过")
            except OSError as exc:
                return dict(reachable=False, channel=channel.section, port=arguments["port"], error=str(exc),
                            notice="探测失败不是DUT根因结论，未修改网络或切换出口")

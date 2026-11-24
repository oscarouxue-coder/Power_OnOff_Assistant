"""Small guards around existing engines; no command, timing, or stop policy changes."""
from contextlib import ExitStack, closing, contextmanager
from functools import wraps
from ipaddress import IPv4Address
from typing import NamedTuple
from uuid import UUID, uuid4

from src.core.host_resource_lock import HostResourceLock
from src.core.wireless_ip import adapters_ipv4
from line_check_assistant.network_ops import adapter_alias_from_display
from src.services.workspace_resources import WorkspaceResources, host_resource_directory
from src.services.project_execution import pipeline_resource_owner
from src.services.host_resource_fence import HostResourceFence


class PowerAdmissionError(RuntimeError):
    """No pipeline subtask was dispatched."""


def channel_resources(channels):
    keys = []
    for channel in channels:
        alias = getattr(channel, "adapter_alias", "") or getattr(channel, "vlan_name", "")
        if alias:
            keys.append("adapter:" + alias.split(" [", 1)[0])
    return keys


class _PowerChannelBinding(NamedTuple):
    channel: int
    source: str
    alias: str
    guid: str
    index: int


def _power_bindings(channels):
    """Read the local Windows interface table once for the whole selection."""
    interfaces = adapters_ipv4()
    bindings = []
    seen_channels, seen_guids = set(), set()
    if not channels:
        raise ValueError("挂测缺少已选择的通道")
    for channel in channels:
        prefix, _, suffix = channel.section.casefold().rpartition('_')
        if prefix != 'channel' or not suffix.isdecimal() or not 1 <= int(suffix) <= 16:
            raise ValueError("挂测通道编号无效")
        number = int(suffix)
        try:
            source = IPv4Address(channel.network_card_ip.strip())
        except ValueError:
            raise ValueError(f"{channel.section} 缺少有效的本机源 IPv4") from None
        address = str(source)
        matches = [nic for nic in interfaces if any(ip == address for ip, _ in nic['addresses'])]
        if (source.is_unspecified or source.is_loopback or source.is_multicast or address == '255.255.255.255'
                or len(matches) != 1 or not matches[0]['up'] or matches[0]['index'] <= 0):
            raise ValueError(f"{channel.section} 源 IP 未唯一匹配到可用网卡")
        nic = matches[0]
        alias = nic['name'].strip().casefold()
        try:
            identifier = UUID(nic['guid'])
        except (ValueError, TypeError, AttributeError):
            raise ValueError(f"{channel.section} 缺少有效的网卡 GUID") from None
        guid = str(identifier)
        names = [adapter_alias_from_display(s).casefold() for s in (channel.adapter_alias, channel.vlan_name) if s.strip()]
        if (not alias or not identifier.int or any(name != alias for name in names)
                or sum(row['name'].strip().casefold() == alias for row in interfaces) != 1
                or sum(row['guid'].strip('{}').casefold() == guid for row in interfaces) != 1
                or sum(row['index'] == nic['index'] for row in interfaces) != 1):
            raise ValueError(f"{channel.section} 网卡别名、VLAN 或物理接口身份无法唯一核对")
        if number in seen_channels or guid in seen_guids:
            raise ValueError("所选挂测通道的网卡绑定重复，无法区分目标")
        seen_channels.add(number)
        seen_guids.add(guid)
        bindings.append(_PowerChannelBinding(number, address, alias, guid, nic['index']))
    return tuple(bindings)


@contextmanager
def _power_admission(context):
    binding = _power_bindings(context.enabled_channels)
    adapters = [(row.alias, row.guid) for row in binding]
    keys = {'adapter:' + value for pair in adapters for value in pair}
    standalone = context.standalone_power_run
    project_id = ''
    if standalone is not None:
        keys.update(standalone.resource_keys(context, binding))
        project_id = standalone.project.identity.project_id

    def verify():
        if _power_bindings(context.enabled_channels) != binding:
            raise ValueError("挂测通道的源 IP 或网卡身份已变化，已停止下发")
        if standalone is not None:
            standalone.verify(context, context.app.power_serial_port)

    parent = context.power_resource_owner or pipeline_resource_owner.get()
    if parent is not None:
        if standalone is not None:
            raise ValueError('独立挂测不能借用其它项目的资源所有者')
        protection, owner = parent
        if isinstance(protection, WorkspaceResources):
            # Extend the original ticket. Its issuer owns release after worker cleanup.
            protection.extend_adapter_owner(owner, adapters)
            verify()
            yield verify
        elif isinstance(protection, HostResourceFence):
            # The gateway job already owns its fence. Retain its original release boundary.
            with HostResourceLock(keys):
                protection.extend_active(owner, keys)
                verify()
                yield verify
        else:
            raise ValueError("挂测原资源所有者无法核实")
        return

    with closing(WorkspaceResources(host_resource_directory())) as resources:
        owner = 'gui:legacy-power:' + uuid4().hex
        resources.acquire(owner, project_id, '兼容单项目挂测', keys)
        try:
            verify()
            yield verify
        finally:
            resources.release(owner)


def guard_pipeline(function):
    @wraps(function)
    def run(self, selected):
        standalone = getattr(self.ctx, 'standalone_power_run', None)
        if standalone is not None:
            from src.services.standalone_power_project import OPEN_GUIDANCE
            try:
                standalone.verify(self.ctx, self.ctx.app.power_serial_port)
            except Exception as error:
                self.emit(f"[挂测准入] 未开始：{error}。{OPEN_GUIDANCE}")
                raise PowerAdmissionError(f'{error}。{OPEN_GUIDANCE}') from error
        if 'legacy_power_test' in selected:
            with ExitStack() as scope:
                try:
                    self._verify_power_resources = scope.enter_context(_power_admission(self.ctx))
                except Exception as error:
                    message = str(error)
                    if standalone is not None:
                        message += '。' + OPEN_GUIDANCE
                    self.emit(f"[挂测准入] 未开始：{message}")
                    raise PowerAdmissionError(message) from error
                try:
                    if standalone is not None:
                        self.emit(f'[挂测准入] 已取得所选 DUT 和网卡资源；项目={standalone.project.identity.project_id}；批次={standalone.root.name}')
                    return function(self, selected)
                finally:
                    self._verify_power_resources = None
        # Real PipelineContext exposes enabled_channels; callback-only compatibility
        # contexts used by existing non-device clients may have no channel list.
        keys = channel_resources(getattr(self.ctx, 'enabled_channels', ())) if selected else []
        with HostResourceLock(keys):
            return function(self, selected)
    return run


def guard_upgrade(function):
    @wraps(function)
    def run(requests, *args, **kwargs):
        requests = tuple(requests)
        keys = []
        for request in requests:
            for kind, field in (("adapter", "server_interface"), ("adapter", "adapter_alias"),
                                ("serial", "serial_port"), ("power", "power_serial_port")):
                value = getattr(request, field, "")
                if value:
                    keys.append(kind + ":" + value)
        with HostResourceLock(keys):
            return function(requests, *args, **kwargs)
    return run

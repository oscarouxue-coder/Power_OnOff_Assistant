"""Small guards around existing engines; no command, timing, or stop policy changes."""
from functools import wraps

from src.core.host_resource_lock import HostResourceLock


def channel_resources(channels):
    keys = []
    for channel in channels:
        alias = getattr(channel, "adapter_alias", "") or getattr(channel, "vlan_name", "")
        if alias:
            keys.append("adapter:" + alias.split(" [", 1)[0])
    return keys


def guard_pipeline(function):
    @wraps(function)
    def run(self, selected):
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

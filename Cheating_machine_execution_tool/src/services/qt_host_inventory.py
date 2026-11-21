"""Read Windows resources off the workspace command thread."""
from __future__ import annotations

from dataclasses import dataclass

from src.models.network_adapter import AdapterIdentity


@dataclass(frozen=True)
class HostInventoryReading:
    # None means failed; an empty tuple is a successful enumeration.
    ports: tuple[str, ...] | None
    adapters: tuple[AdapterIdentity, ...] | None


def read_host_inventory() -> HostInventoryReading:
    from src.core.network_adapter import read_adapter_identities
    from src.core.serial_inventory import list_serial_port_names

    try:
        ports = tuple(list_serial_port_names())
    except Exception:
        ports = None
    try:
        adapters = tuple(read_adapter_identities())
    except Exception:
        adapters = None
    return HostInventoryReading(ports, adapters)

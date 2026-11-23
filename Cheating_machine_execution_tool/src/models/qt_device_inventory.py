"""Readonly device inventory and leases published by the workspace worker."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from src.models.network_adapter import AdapterIdentity


@dataclass(frozen=True)
class DeviceInventoryView:
    ports: Tuple[str, ...] = ()
    adapters: Tuple[AdapterIdentity, ...] = ()
    ports_at: Optional[datetime] = None
    adapters_at: Optional[datetime] = None
    ports_failed: bool = False
    adapters_failed: bool = False


@dataclass(frozen=True)
class ResourceLeaseEntry:
    resource_key: str
    project_id: str
    project_name: str
    owner_id: str
    state: str


@dataclass(frozen=True)
class DeviceLeaseView:
    owners: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    sampled_at: Optional[datetime] = None
    protection_unavailable: bool = False
    entries: Tuple[ResourceLeaseEntry, ...] = ()

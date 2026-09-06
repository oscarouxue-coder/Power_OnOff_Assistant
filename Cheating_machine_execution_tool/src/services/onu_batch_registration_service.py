"""Batch request construction for the ONU registration UI.

The OLT-specific precheck remains in :mod:`onu_registration_service`; this
module only creates an immutable, deterministic target list before any device
command is sent.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from src.models.onu_registration_models import DiscoveredOnu, OnuProvisionRequest


def build_batch_requests(
    selected_onus: Iterable[DiscoveredOnu], base_request: OnuProvisionRequest
) -> tuple[OnuProvisionRequest, ...]:
    """Copy one business profile to selected ONUs with per-PON unique IDs.

    A single selection preserves the operator-entered ONU ID.  For a batch,
    the discovery-provided suggestion is used where available; other targets
    receive the first free number at or above the configured starting ID.
    Existing OLT occupation is deliberately not guessed here: the registration
    service validates every generated PON/ID against the live OLT before it
    sends any provisioning command.
    """
    targets = tuple(selected_onus)
    if not targets:
        raise ValueError("请先选择要注册的 ONU")
    if any(target.family != base_request.family for target in targets):
        raise ValueError("一次批量注册不能混合 C300 和 C600 ONU")

    serials: set[str] = set()
    for target in targets:
        serial = (target.serial_number or "").strip().upper()
        if not serial:
            raise ValueError("未注册 ONU 缺少 SN，拒绝加入批次")
        if serial in serials:
            raise ValueError(f"批量目标 SN 重复：{serial}")
        serials.add(serial)

    if len(targets) == 1:
        return (replace(base_request, onu=targets[0]),)

    starting_id = base_request.onu_id or 1
    if starting_id < 1:
        raise ValueError("批量注册的起始 ONU ID 必须是正整数")

    reserved: dict[str, set[int]] = {}
    for target in targets:
        suggested = target.suggested_onu_id
        if suggested is not None and suggested > 0:
            reserved.setdefault(target.pon_interface.lower(), set()).add(suggested)

    used: dict[str, set[int]] = {}
    requests: list[OnuProvisionRequest] = []
    for target in targets:
        pon_key = target.pon_interface.lower()
        assigned = target.suggested_onu_id
        occupied = used.setdefault(pon_key, set())
        if assigned is None or assigned < 1 or assigned in occupied:
            assigned = starting_id
            unavailable = occupied | reserved.get(pon_key, set())
            while assigned in unavailable:
                assigned += 1
        occupied.add(assigned)
        requests.append(replace(base_request, onu=target, onu_id=assigned))
    return tuple(requests)

"""Batch request construction for the ONU registration UI.

The OLT-specific precheck remains in :mod:`onu_registration_service`; this
module only creates an immutable, deterministic target list before any device
command is sent.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

from src.models.onu_registration_models import DiscoveredOnu, OnuProvisionRequest


def build_batch_requests(
    selected_onus: Iterable[DiscoveredOnu], base_request: OnuProvisionRequest,
    target_ids: Mapping[DiscoveredOnu, str] | None = None,
) -> tuple[OnuProvisionRequest, ...]:
    """Copy one business profile to selected ONUs with per-PON unique IDs.

    Explicit per-target inputs are preserved, including when switching targets.
    Conflicting explicit IDs are rejected rather than silently renumbered.
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

    explicit: dict[DiscoveredOnu, int] = {}
    reserved: dict[str, set[int]] = {}
    for target in targets:
        if target_ids is None or target not in target_ids:
            continue
        try:
            assigned = int(target_ids[target])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"ONU {target.serial_number} 的目标 ONU ID 必须是正整数") from exc
        if assigned < 1:
            raise ValueError(f"ONU {target.serial_number} 的目标 ONU ID 必须是正整数")
        occupied = reserved.setdefault(target.pon_interface.lower(), set())
        if assigned in occupied:
            raise ValueError(f"批量目标 ONU ID 重复：{target.pon_interface} / {assigned}；请修改手填 ID")
        occupied.add(assigned)
        explicit[target] = assigned

    if len(targets) == 1:
        return (replace(base_request, onu=targets[0], onu_id=explicit.get(targets[0], base_request.onu_id)),)

    starting_id = base_request.onu_id or 1
    if starting_id < 1:
        raise ValueError("批量注册的起始 ONU ID 必须是正整数")

    explicit_reserved = {pon: set(ids) for pon, ids in reserved.items()}
    for target in targets:
        if target in explicit:
            continue
        suggested = target.suggested_onu_id
        if suggested is not None and suggested > 0:
            reserved.setdefault(target.pon_interface.lower(), set()).add(suggested)

    used: dict[str, set[int]] = {}
    requests: list[OnuProvisionRequest] = []
    for target in targets:
        pon_key = target.pon_interface.lower()
        assigned = explicit.get(target, target.suggested_onu_id)
        occupied = used.setdefault(pon_key, set())
        if target not in explicit and (
            assigned is None or assigned < 1 or assigned in occupied
            or assigned in explicit_reserved.get(pon_key, set())
        ):
            assigned = starting_id
            unavailable = occupied | reserved.get(pon_key, set())
            while assigned in unavailable:
                assigned += 1
        occupied.add(assigned)
        requests.append(replace(base_request, onu=target, onu_id=assigned))
    return tuple(requests)

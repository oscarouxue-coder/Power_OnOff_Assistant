"""DUT 2.4G/5G WiFi 的只读查询、配置和回读校验协议切片。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from src.models.dut_config_models import DutWifiRadioSettings, DutWifiSettings

from .ubus_http_client import (
    UBUS_SERVICE_BBFDM,
    UbusError,
    UbusHttpClient,
    UbusTransportError,
)


VENDOR_PREFIX = "X_SDMC_"
WEB_OPTIONAL = {"proto": "web"}
WIFI_ROOT = "Device.WiFi."
WIFI_MAPPING_PATHS = {
    "2.4G": f"{WIFI_ROOT}{VENDOR_PREFIX}Mapping_2G",
    "5G": f"{WIFI_ROOT}{VENDOR_PREFIX}Mapping_5G",
}
WIFI_DUAL_BAND_PATH = f"{WIFI_ROOT}{VENDOR_PREFIX}DualBandEnable"
WIFI_APPLY_SETTLE_SECONDS = 60.0
WIFI_GET_RETRY_DELAY_SECONDS = 1.0
WIFI_GET_MAX_RETRIES = 1

LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], None]


def _emit(on_log: LogCallback | None, message: str) -> None:
    if on_log is not None:
        on_log(message)


def _require_rpc_ok(response: Any, action: str) -> Any:
    if not isinstance(response, list) or not response or response[0] != 0:
        raise UbusError(f"{action} 返回失败：{response}")
    return response


def _response_payload(response: Any, action: str) -> dict[str, Any]:
    _require_rpc_ok(response, action)
    if len(response) < 2 or not isinstance(response[1], dict):
        raise UbusError(f"{action} 返回格式异常：{response}")
    return response[1]


def _find_named_list(value: Any, name: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        candidate = value.get(name)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        for nested in value.values():
            found = _find_named_list(nested, name)
            if found:
                return found
    return []


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _split_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = _as_text(value)
        if not text:
            return ()
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, list):
            items = decoded
        else:
            items = text.replace(";", ",").split(",")
    return tuple(dict.fromkeys(_as_text(item) for item in items if _as_text(item)))


def _first_supported_values(
    values: Mapping[str, Any],
    *keys: str,
) -> tuple[str, ...]:
    """读取设备能力字段的首个有效兼容名称。"""

    for key in keys:
        supported = _split_values(values.get(key))
        if supported:
            return supported
    return ()


def _parse_mode_bw_map(value: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return (), ()
    entries = decoded.get("list", ()) if isinstance(decoded, dict) else ()
    modes: list[str] = []
    bandwidths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mode = _as_text(entry.get("standard"))
        if mode and mode not in modes:
            modes.append(mode)
        for bandwidth in _split_values(entry.get("bw")):
            if bandwidth not in bandwidths:
                bandwidths.append(bandwidth)
    return tuple(modes), tuple(bandwidths)


def _get(
    client: UbusHttpClient,
    session_id: str,
    path: str,
    *,
    on_log: LogCallback | None,
    sleep_fn: SleepCallback = time.sleep,
) -> dict[str, Any]:
    for attempt in range(1, WIFI_GET_MAX_RETRIES + 2):
        _emit(on_log, f"TX UBUS bbfdm.get path={path}")
        try:
            response = client.bbfdm_get(session_id, path, optional=WEB_OPTIONAL)
            break
        except UbusTransportError as exc:
            if attempt > WIFI_GET_MAX_RETRIES:
                raise
            _emit(
                on_log,
                "UBUS WiFi只读请求连接异常："
                f"{exc}；等待 {WIFI_GET_RETRY_DELAY_SECONDS:g} 秒后重建连接重试 "
                f"{attempt}/{WIFI_GET_MAX_RETRIES}",
            )
            sleep_fn(WIFI_GET_RETRY_DELAY_SECONDS)
    payload = _response_payload(response, f"WiFi get {path}")
    _emit(on_log, f"RX UBUS {path}：{payload}")
    return payload


def _mapping_value(payload: Mapping[str, Any], band: str) -> str:
    key = f"{VENDOR_PREFIX}Mapping_{'2G' if band == '2.4G' else '5G'}"
    value = payload.get(key)
    if not value:
        raise UbusError(f"未获取到 {key}：{payload}")
    return str(value)


def _instance_from_mapping_token(
    token: str,
    nodes: list[dict[str, Any]],
    node_name: str,
) -> str:
    try:
        position = int(token)
    except ValueError as exc:
        raise UbusError(f"WiFi {node_name} Mapping 索引无效：{token}") from exc
    if 1 <= position <= len(nodes):
        instance = nodes[position - 1].get(f"{VENDOR_PREFIX}Instance")
        if instance not in (None, ""):
            return str(instance)
    if any(_as_text(item.get(f"{VENDOR_PREFIX}Instance")) == token for item in nodes):
        return token
    raise UbusError(
        f"WiFi {node_name} Mapping 索引 {token} 超出节点范围 {len(nodes)}"
    )


def resolve_wifi_paths(
    client: UbusHttpClient,
    session_id: str,
    band: str,
    ssid_index: str,
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> dict[str, str]:
    """把厂商 Mapping 的第 N 组解析为真实 Radio/AP/SSID 实例路径。"""
    if band not in WIFI_MAPPING_PATHS:
        raise ValueError(f"WiFi 频段无效：{band}")
    try:
        position = int(ssid_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SSID 索引必须为正整数：{ssid_index}") from exc
    mapping_payload = _get(
        client,
        session_id,
        WIFI_MAPPING_PATHS[band],
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    groups = _mapping_value(mapping_payload, band).split("@")
    if not 1 <= position <= len(groups):
        raise UbusError(
            f"{band} SSID 索引 {position} 超出设备 Mapping 数量 {len(groups)}"
        )
    tokens = tuple(part.strip() for part in groups[position - 1].split(","))
    if len(tokens) != 3 or any(not token for token in tokens):
        raise UbusError(f"{band} WiFi Mapping 格式异常：{groups[position - 1]}")

    resolved: list[str] = []
    for token, node_name in zip(tokens, ("Radio", "AccessPoint", "SSID")):
        base_path = f"{WIFI_ROOT}{node_name}."
        payload = _get(
            client, session_id, base_path, on_log=on_log, sleep_fn=sleep_fn
        )
        nodes = _find_named_list(payload, node_name)
        if not nodes:
            raise UbusError(f"WiFi {node_name} 节点列表为空：{payload}")
        resolved.append(_instance_from_mapping_token(token, nodes, node_name))
    paths = {
        "radio": f"{WIFI_ROOT}Radio.{resolved[0]}.",
        "access_point": f"{WIFI_ROOT}AccessPoint.{resolved[1]}.",
        "ssid": f"{WIFI_ROOT}SSID.{resolved[2]}.",
    }
    _emit(
        on_log,
        f"WiFi Mapping 已解析：频段={band}，SSID索引={ssid_index}，路径={paths}",
    )
    return paths


def _dual_value_for_index(value: Any, ssid_index: str) -> bool:
    values = _as_text(value).split(",")
    position = int(ssid_index) - 1
    selected = values[position] if 0 <= position < len(values) else values[0]
    return _as_bool(selected)


def _updated_dual_value(value: Any, ssid_index: str, enabled: bool) -> str:
    values = _as_text(value).split(",")
    if not values or values == [""]:
        values = ["0"]
    position = int(ssid_index) - 1
    if position >= len(values):
        values.extend("0" for _ in range(position + 1 - len(values)))
    values[position] = "1" if enabled else "0"
    return ",".join(values)


def _query_wifi_status_single(
    client: UbusHttpClient,
    session_id: str,
    band: str,
    ssid_index: str = "1",
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> DutWifiSettings:
    """只读查询单个频段/SSID；不递归查询另一频段。"""
    paths = resolve_wifi_paths(
        client,
        session_id,
        band,
        ssid_index,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    dual_payload = _get(
        client,
        session_id,
        WIFI_DUAL_BAND_PATH,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    dual_raw = dual_payload.get(f"{VENDOR_PREFIX}DualBandEnable", "0")
    ssid_payload = _get(
        client, session_id, paths["ssid"], on_log=on_log, sleep_fn=sleep_fn
    )
    ap_payload = _get(
        client,
        session_id,
        paths["access_point"],
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    radio_payload = _get(
        client, session_id, paths["radio"], on_log=on_log, sleep_fn=sleep_fn
    )

    ssid_items = _find_named_list(ssid_payload, "SSID")
    ap_items = _find_named_list(ap_payload, "AccessPoint")
    radio_items = _find_named_list(radio_payload, "Radio")
    if not ssid_items or not ap_items or not radio_items:
        raise UbusError(
            "WiFi 状态返回缺少 SSID/AccessPoint/Radio 节点："
            f"SSID={ssid_payload}，AP={ap_payload}，Radio={radio_payload}"
        )
    ssid_data, ap_data, radio_data = ssid_items[0], ap_items[0], radio_items[0]
    security = ap_data.get("Security")
    if not isinstance(security, dict):
        security_payload = _get(
            client,
            session_id,
            f"{paths['access_point']}Security.",
            on_log=on_log,
            sleep_fn=sleep_fn,
        )
        security_items = _find_named_list(security_payload, "Security")
        security = security_items[0] if security_items else security_payload

    modes, bandwidths = _parse_mode_bw_map(
        radio_data.get(f"{VENDOR_PREFIX}ModeBWMap")
    )
    security_modes = _first_supported_values(
        security,
        "ModesSupported",
        f"{VENDOR_PREFIX}ModesSupported",
        "ModeSupported",
    )
    transmit_powers = _first_supported_values(
        radio_data,
        "TransmitPowerSupported",
        f"{VENDOR_PREFIX}TransmitPowerSupported",
        f"{VENDOR_PREFIX}TransmitPowersSupported",
        "TransmitPowerList",
        f"{VENDOR_PREFIX}TransmitPowerList",
    )
    settings = DutWifiSettings(
        band=band,
        ssid_index=str(ssid_index),
        ssid=_as_text(ssid_data.get("SSID")),
        password=_as_text(security.get(f"{VENDOR_PREFIX}Key")),
        channel=_as_text(
            radio_data.get(f"{VENDOR_PREFIX}ChannelEnabled")
            if radio_data.get(f"{VENDOR_PREFIX}ChannelEnabled") is not None
            else radio_data.get("Channel")
        ) or "auto",
        channel_bandwidth=_as_text(radio_data.get("OperatingChannelBandwidth")),
        dual_band_enabled=_dual_value_for_index(dual_raw, str(ssid_index)),
        enabled=_as_bool(ssid_data.get("Enable")),
        hidden=not _as_bool(ap_data.get("SSIDAdvertisementEnabled"), default=True),
        security_mode=_as_text(security.get("ModeEnabled")) or "None",
        operating_mode=_as_text(radio_data.get("OperatingStandards")),
        transmit_power=_as_text(radio_data.get("TransmitPower")),
        max_associations=_as_text(ap_data.get("MaxAllowedAssociations")),
        wmm_enabled=_as_bool(ap_data.get("WMMEnable"), default=True),
        supported_channels=_split_values(
            radio_data.get(f"{VENDOR_PREFIX}ChannelsSupported")
        ),
        supported_bandwidths=bandwidths,
        supported_modes=modes,
        supported_security_modes=security_modes,
        supported_transmit_powers=transmit_powers,
    )
    _emit(on_log, f"RX UBUS {band} WiFi当前状态：{settings}")
    return settings


def _radio_snapshot(settings: DutWifiSettings) -> DutWifiRadioSettings:
    return DutWifiRadioSettings(
        band=settings.band,
        channel=settings.channel,
        channel_bandwidth=settings.channel_bandwidth,
        operating_mode=settings.operating_mode,
        transmit_power=settings.transmit_power,
        supported_channels=settings.supported_channels,
        supported_bandwidths=settings.supported_bandwidths,
        supported_modes=settings.supported_modes,
        supported_transmit_powers=settings.supported_transmit_powers,
    )


def query_wifi_status(
    client: UbusHttpClient,
    session_id: str,
    band: str,
    ssid_index: str = "1",
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> DutWifiSettings:
    """只读查询指定频段，并预读另一频段Radio供双频配置使用。"""
    settings = _query_wifi_status_single(
        client,
        session_id,
        band,
        ssid_index,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    peer_band = "5G" if band == "2.4G" else "2.4G"
    peer = _query_wifi_status_single(
        client,
        session_id,
        peer_band,
        ssid_index,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    combined = replace(settings, peer_radio=_radio_snapshot(peer))
    _emit(
        on_log,
        f"RX UBUS 双频Radio当前状态：{band}={_radio_snapshot(settings)}，"
        f"{peer_band}={combined.peer_radio}",
    )
    return combined


def _wifi_set_paths(
    settings: DutWifiSettings,
    target_paths: Mapping[str, str],
    peer_paths: Mapping[str, str] | None,
    dual_value: str,
) -> list[dict[str, Any]]:
    ssid_targets = [target_paths]
    if settings.dual_band_enabled and peer_paths is not None:
        ssid_targets.append(peer_paths)
    paths: list[dict[str, Any]] = [
        {
            "addr": WIFI_ROOT,
            "obj_path": {f"{VENDOR_PREFIX}DualBandEnable": dual_value},
        }
    ]
    for mapped in ssid_targets:
        paths.extend(
            (
                {
                    "addr": mapped["ssid"],
                    "obj_path": {"Enable": settings.enabled, "SSID": settings.ssid},
                },
                {
                    "addr": mapped["access_point"],
                    "obj_path": {
                        "MaxAllowedAssociations": settings.max_associations,
                        "SSIDAdvertisementEnabled": "0" if settings.hidden else "1",
                        "WMMEnable": "1" if settings.wmm_enabled else "0",
                    },
                },
            )
        )
        security_obj: dict[str, Any] = {"ModeEnabled": settings.security_mode}
        if settings.security_mode != "None":
            security_obj[f"{VENDOR_PREFIX}Key"] = settings.password
        paths.append(
            {
                "addr": f"{mapped['access_point']}Security.",
                "obj_path": security_obj,
            }
        )
    paths.append(
        {
            "addr": target_paths["radio"],
            "obj_path": {
                f"{VENDOR_PREFIX}ChannelEnabled": settings.channel,
                f"{VENDOR_PREFIX}OperatingStandards": settings.operating_mode,
                "OperatingChannelBandwidth": settings.channel_bandwidth,
                "TransmitPower": settings.transmit_power,
            },
        }
    )
    if settings.dual_band_enabled:
        if peer_paths is None or settings.peer_radio is None:
            raise UbusError("双频合一缺少另一频段Radio参数，已拒绝下发")
        paths.append(
            {
                "addr": peer_paths["radio"],
                "obj_path": {
                    f"{VENDOR_PREFIX}ChannelEnabled": settings.peer_radio.channel,
                    f"{VENDOR_PREFIX}OperatingStandards": (
                        settings.peer_radio.operating_mode
                    ),
                    "OperatingChannelBandwidth": (
                        settings.peer_radio.channel_bandwidth
                    ),
                    "TransmitPower": settings.transmit_power,
                },
            }
        )
    return paths


def _assert_wifi_readback(expected: DutWifiSettings, actual: DutWifiSettings) -> None:
    fields = (
        "ssid",
        "channel",
        "channel_bandwidth",
        "dual_band_enabled",
        "enabled",
        "hidden",
        "security_mode",
        "operating_mode",
        "transmit_power",
        "max_associations",
        "wmm_enabled",
    )
    if expected.security_mode != "None":
        fields = (*fields, "password")
    mismatches = [
        f"{field}={getattr(actual, field)!r}（期望 {getattr(expected, field)!r}）"
        for field in fields
        if getattr(actual, field) != getattr(expected, field)
    ]
    if mismatches:
        raise UbusError(f"{expected.band} WiFi 回读不一致：{', '.join(mismatches)}")


def apply_wifi_config(
    client: UbusHttpClient,
    session_id: str,
    settings: DutWifiSettings,
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> None:
    """下发指定频段配置；不等待Radio稳定，也不执行回读。"""
    target_paths = resolve_wifi_paths(
        client,
        session_id,
        settings.band,
        settings.ssid_index,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    peer_band = "5G" if settings.band == "2.4G" else "2.4G"
    peer_paths = (
        resolve_wifi_paths(
            client,
            session_id,
            peer_band,
            settings.ssid_index,
            on_log=on_log,
            sleep_fn=sleep_fn,
        )
        if settings.dual_band_enabled
        else None
    )
    dual_payload = _get(
        client,
        session_id,
        WIFI_DUAL_BAND_PATH,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    current_dual = dual_payload.get(f"{VENDOR_PREFIX}DualBandEnable", "0")
    dual_value = _updated_dual_value(
        current_dual, settings.ssid_index, settings.dual_band_enabled
    )
    paths = _wifi_set_paths(settings, target_paths, peer_paths, dual_value)
    payload = {"paths": paths, "optional": WEB_OPTIONAL}
    _emit(on_log, f"TX UBUS bbfdm.set WiFi paths={paths}")
    response = client.call(session_id, UBUS_SERVICE_BBFDM, "set", payload)
    _require_rpc_ok(response, f"{settings.band} WiFi set")
    _emit(on_log, f"RX UBUS {settings.band} WiFi配置结果：{response}")


def verify_wifi_config(
    client: UbusHttpClient,
    session_id: str,
    settings: DutWifiSettings,
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> DutWifiSettings:
    """回读并校验指定频段；本函数不重复下发配置。"""
    peer_band = "5G" if settings.band == "2.4G" else "2.4G"
    actual = _query_wifi_status_single(
        client,
        session_id,
        settings.band,
        settings.ssid_index,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )
    _assert_wifi_readback(settings, actual)
    if settings.dual_band_enabled:
        if settings.peer_radio is None:
            raise UbusError("双频合一回读缺少另一频段Radio期望参数")
        peer = _query_wifi_status_single(
            client,
            session_id,
            peer_band,
            settings.ssid_index,
            on_log=on_log,
            sleep_fn=sleep_fn,
        )
        shared_fields = (
            "ssid",
            "password",
            "dual_band_enabled",
            "enabled",
            "hidden",
            "security_mode",
            "max_associations",
            "wmm_enabled",
        )
        mismatches = [
            field for field in shared_fields
            if getattr(peer, field) != getattr(settings, field)
            and not (field == "password" and settings.security_mode == "None")
        ]
        if mismatches:
            raise UbusError(f"双频合一回读不一致：{peer_band} 的 {', '.join(mismatches)} 未同步")
        peer_radio = _radio_snapshot(peer)
        peer_radio_mismatches = [
            f"{field}={getattr(peer_radio, field)!r}"
            f"（期望 {getattr(settings.peer_radio, field)!r}）"
            for field in ("channel", "channel_bandwidth", "operating_mode")
            if getattr(peer_radio, field) != getattr(settings.peer_radio, field)
        ]
        if peer_radio.transmit_power != settings.transmit_power:
            peer_radio_mismatches.append(
                f"transmit_power={peer_radio.transmit_power!r}"
                f"（期望公共值 {settings.transmit_power!r}）"
            )
        if peer_radio_mismatches:
            raise UbusError(
                f"双频合一回读不一致：{peer_band} Radio "
                f"{', '.join(peer_radio_mismatches)}"
            )
        actual = replace(actual, peer_radio=peer_radio)
    _emit(on_log, f"成功：{settings.band} WiFi 参数已下发并完成回读")
    return actual


def configure_wifi(
    client: UbusHttpClient,
    session_id: str,
    settings: DutWifiSettings,
    *,
    on_log: LogCallback | None = None,
    sleep_fn: SleepCallback = time.sleep,
) -> DutWifiSettings:
    """下发WiFi，等待Radio稳定后回读；保留单台既有完整时序。"""
    apply_wifi_config(
        client,
        session_id,
        settings,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )

    _emit(
        on_log,
        f"等待 WiFi 参数生效并稳定：{WIFI_APPLY_SETTLE_SECONDS:g} 秒",
    )
    sleep_fn(WIFI_APPLY_SETTLE_SECONDS)
    return verify_wifi_config(
        client,
        session_id,
        settings,
        on_log=on_log,
        sleep_fn=sleep_fn,
    )


__all__ = [
    "WIFI_DUAL_BAND_PATH",
    "WIFI_MAPPING_PATHS",
    "apply_wifi_config",
    "configure_wifi",
    "query_wifi_status",
    "resolve_wifi_paths",
    "verify_wifi_config",
]

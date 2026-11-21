"""Original WiFi presentation mappings shared by Tk/Qt; no GUI imports."""
from __future__ import annotations
from dataclasses import replace
from src.models.dut_config_models import DutWifiSettings, DutWifiRadioSettings
from src.services.dut_advanced_config_service import WIFI_BANDWIDTH_OPTIONS, WIFI_MODE_OPTIONS, WIFI_SECURITY_MODE_OPTIONS


def wifi_editor_defaults(feature):
    """Original Tk field defaults, including a peer snapshot for choice lists."""
    band = '2.4G' if feature == 'wifi_2g' else '5G'
    peer_band = '5G' if band == '2.4G' else '2.4G'
    return DutWifiSettings(band=band, ssid='Test_2G_01' if band == '2.4G' else 'Test_5G_01',
        password='Sdmc@1234_2G' if band == '2.4G' else 'Sdmc@1234_5G',
        channel_bandwidth='20/40MHz' if band == '2.4G' else '160MHz',
        operating_mode='b,g,n,ax' if band == '2.4G' else 'a,n,ac,ax',
        peer_radio=DutWifiRadioSettings(band=peer_band,
            channel_bandwidth='20/40MHz' if peer_band == '2.4G' else '160MHz',
            operating_mode='b,g,n,ax' if peer_band == '2.4G' else 'a,n,ac,ax'))

WIFI_SSID_INDEX_OPTIONS = tuple(str(index) for index in range(1, 9))

WIFI_CHANNEL_OPTIONS = {
    "2.4G": ("auto", *(str(channel) for channel in range(1, 14))),
    "5G": (
        "auto", "36", "40", "44", "48", "52", "56", "60", "64",
        "100", "104", "108", "112", "116", "120", "124", "128",
        "132", "136", "140", "144", "149", "153", "157", "161", "165",
    ),
}

WIFI_TRANSMIT_POWER_OPTIONS = ("20", "40", "60", "80", "100")

def wifi_status_form_values(settings: DutWifiSettings) -> dict[str, object]:
    """把只读WiFi状态映射为公共参数和两套Radio表单值。"""
    values: dict[str, object] = {
        "ssid_index": settings.ssid_index,
        "ssid": settings.ssid,
        "password": settings.password,
        "channel": settings.channel,
        "channel_bandwidth": settings.channel_bandwidth,
        "dual_band_enabled": settings.dual_band_enabled,
        "enabled": settings.enabled,
        "hidden": settings.hidden,
        "security_mode": settings.security_mode,
        "operating_mode": settings.operating_mode,
        "transmit_power": settings.transmit_power,
        "max_associations": settings.max_associations,
        "wmm_enabled": settings.wmm_enabled,
    }
    peer_band = "5G" if settings.band == "2.4G" else "2.4G"
    peer = settings.peer_radio or DutWifiRadioSettings(
        band=peer_band,
        channel_bandwidth="20/40MHz" if peer_band == "2.4G" else "160MHz",
        operating_mode="b,g,n,ax" if peer_band == "2.4G" else "a,n,ac,ax",
    )
    values.update(
        {
            "peer_channel": peer.channel,
            "peer_channel_bandwidth": peer.channel_bandwidth,
            "peer_operating_mode": peer.operating_mode,
        }
    )
    return values

def wifi_choice_options(settings: DutWifiSettings) -> dict[str, tuple[str, ...]]:
    """按 DUT 查询能力生成 WiFi 只读下拉候选；缺能力字段时使用兼容兜底。"""

    band = settings.band if settings.band in WIFI_CHANNEL_OPTIONS else "2.4G"
    supported_by_key = {
        "security_mode": settings.supported_security_modes,
        "channel": settings.supported_channels,
        "channel_bandwidth": settings.supported_bandwidths,
        "operating_mode": settings.supported_modes,
        "transmit_power": settings.supported_transmit_powers,
    }
    fallback_by_key = {
        "security_mode": WIFI_SECURITY_MODE_OPTIONS,
        "channel": WIFI_CHANNEL_OPTIONS[band],
        "channel_bandwidth": WIFI_BANDWIDTH_OPTIONS[band],
        "operating_mode": WIFI_MODE_OPTIONS[band],
        "transmit_power": WIFI_TRANSMIT_POWER_OPTIONS,
    }
    current_by_key = {
        "security_mode": settings.security_mode,
        "channel": settings.channel,
        "channel_bandwidth": settings.channel_bandwidth,
        "operating_mode": settings.operating_mode,
        "transmit_power": settings.transmit_power,
    }
    options_by_key: dict[str, tuple[str, ...]] = {}
    for key in supported_by_key:
        options = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (supported_by_key[key] or fallback_by_key[key])
                if str(value).strip()
            )
        )
        current = str(current_by_key[key]).strip()
        if current and current not in options:
            options = (current, *options)
        options_by_key[key] = options
    peer_band = "5G" if band == "2.4G" else "2.4G"
    peer = settings.peer_radio or DutWifiRadioSettings(
        band=peer_band,
        channel_bandwidth="20/40MHz" if peer_band == "2.4G" else "160MHz",
        operating_mode="b,g,n,ax" if peer_band == "2.4G" else "a,n,ac,ax",
    )
    if peer is not None:
        peer_supported = {
            "peer_channel": peer.supported_channels,
            "peer_channel_bandwidth": peer.supported_bandwidths,
            "peer_operating_mode": peer.supported_modes,
        }
        peer_fallback = {
            "peer_channel": WIFI_CHANNEL_OPTIONS[peer.band],
            "peer_channel_bandwidth": WIFI_BANDWIDTH_OPTIONS[peer.band],
            "peer_operating_mode": WIFI_MODE_OPTIONS[peer.band],
        }
        peer_current = {
            "peer_channel": peer.channel,
            "peer_channel_bandwidth": peer.channel_bandwidth,
            "peer_operating_mode": peer.operating_mode,
        }
        for key in peer_supported:
            options = tuple(
                dict.fromkeys(
                    str(value).strip()
                    for value in (peer_supported[key] or peer_fallback[key])
                    if str(value).strip()
                )
            )
            current = str(peer_current[key]).strip()
            if current and current not in options:
                options = (current, *options)
            options_by_key[key] = options

        if settings.dual_band_enabled:
            primary_powers = tuple(
                settings.supported_transmit_powers or WIFI_TRANSMIT_POWER_OPTIONS
            )
            peer_powers = set(
                peer.supported_transmit_powers or WIFI_TRANSMIT_POWER_OPTIONS
            )
            shared_powers = tuple(
                value for value in primary_powers if value in peer_powers
            )
            if settings.transmit_power and settings.transmit_power not in shared_powers:
                shared_powers = (settings.transmit_power, *shared_powers)
            options_by_key["transmit_power"] = shared_powers
    return options_by_key

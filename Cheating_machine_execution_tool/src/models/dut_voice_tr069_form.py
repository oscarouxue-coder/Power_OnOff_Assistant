"""Shared original Voice and TR069 form projections."""
from src.models.dut_config_models import DutVoiceSettings, DutTr069Settings
from src.services.dut_advanced_config_service import (
    VOICE_CODEC_OPTIONS,
    VOICE_DTMF_OPTIONS,
    VOICE_SIP_MODE_OPTIONS,
)


def voice_status_form_values(settings: DutVoiceSettings) -> dict[str, object]:
    """把只读语音状态映射为当前表单值。"""
    return {
        "line_index": settings.line_index,
        "account_enabled": settings.account_enabled,
        "display_name": settings.display_name,
        "auth_username": settings.auth_username,
        "auth_password": settings.auth_password,
        "proxy_server": settings.proxy_server,
        "proxy_port": settings.proxy_port,
        "outbound_proxy": settings.outbound_proxy,
        "outbound_proxy_port": settings.outbound_proxy_port,
        "registrar_server": settings.registrar_server,
        "registrar_server_port": settings.registrar_server_port,
        "dtmf_method": settings.dtmf_method,
        "register_expires": settings.register_expires,
        "sip_mode": settings.sip_mode,
        "digit_map": settings.digit_map,
        "codecs": settings.codecs,
    }


def tr069_status_form_values(settings: DutTr069Settings) -> dict[str, object]:
    """把只读TR069状态映射为当前表单值，不改动手动Inform动作选项。"""
    return {
        "acs_url": settings.acs_url,
        "acs_username": settings.acs_username,
        "acs_password": settings.acs_password,
        "periodic_inform_enabled": settings.periodic_inform_enabled,
        "periodic_inform_interval": settings.periodic_inform_interval,
        "connection_request_enabled": settings.connection_request_enabled,
        "connection_request_username": settings.connection_request_username,
        "connection_request_password": settings.connection_request_password,
        "certificate_enabled": settings.certificate_enabled,
    }


def voice_choice_options(settings: DutVoiceSettings) -> dict[str, tuple[str, ...]]:
    """按 DUT 查询能力生成语音只读下拉候选；缺能力字段时兼容兜底。"""

    current_by_key = {
        "dtmf_method": (settings.dtmf_method,),
        "sip_mode": (settings.sip_mode,),
        "codecs": settings.codecs,
    }
    supported_by_key = {
        "dtmf_method": settings.supported_dtmf_methods,
        "sip_mode": settings.supported_sip_modes,
        "codecs": settings.supported_codecs,
    }
    fallback_by_key = {
        "dtmf_method": VOICE_DTMF_OPTIONS,
        "sip_mode": VOICE_SIP_MODE_OPTIONS,
        "codecs": tuple(sorted(VOICE_CODEC_OPTIONS)),
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
        current_values = tuple(
            str(value).strip() for value in current_by_key[key] if str(value).strip()
        )
        missing_current = tuple(value for value in current_values if value not in options)
        options_by_key[key] = tuple(dict.fromkeys((*missing_current, *options)))
    return options_by_key


def tr069_editor_defaults():
    """Match the original Tk form rather than the partial query defaults."""
    return DutTr069Settings(
        acs_url='http://172.18.18.101:7547/ACS-server/ACS',
        acs_username='hgw',
        acs_password='hgw',
        periodic_inform_enabled=True,
        periodic_inform_interval='86400',
        connection_request_enabled=True,
        connection_request_username='itms',
        connection_request_password='itms',
        certificate_enabled=False,
        manual_inform=False,
    )

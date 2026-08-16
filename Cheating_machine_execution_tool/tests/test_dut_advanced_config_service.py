from __future__ import annotations

import threading
import unittest

from line_check_assistant.network_ops import CommandResult
from src.models import (
    DutAdvancedConfigRequest,
    DutAdvancedConfigResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutWanSettings,
    DutWifiSettings,
)
from src.services.dut_advanced_config_service import (
    VOICE_SIP_MODE_OPTIONS,
    run_dut_advanced_config_batch,
    run_single_dut_advanced_config,
    validate_tr069_settings,
    validate_voice_settings,
    validate_wan_settings,
    validate_wifi_settings,
)


def _request(feature: str, settings) -> DutAdvancedConfigRequest:
    return DutAdvancedConfigRequest(
        channel="通道 12",
        vlan="vlan112",
        adapter_alias="VLAN112",
        bind_ip="192.168.1.112",
        device_host="192.168.1.1",
        subnet_mask="255.255.255.0",
        username="telecomadmin",
        password="plain-password",
        feature=feature,
        settings=settings,
    )


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def login(self, username, password):
        if username != "telecomadmin" or password != "plain-password":
            raise RuntimeError("bad credentials")
        return "session-id"

    def close(self):
        self.closed = True


class DutAdvancedConfigServiceTests(unittest.TestCase):
    def test_wifi_validation_covers_band_rules_security_and_extra_fields(self) -> None:
        valid = DutWifiSettings(
            band="2.4G",
            ssid="Lab_WiFi",
            password="password123",
            channel="13",
            channel_bandwidth="20/40MHz",
            security_mode="WPA3-Personal-Transition",
            operating_mode="b,g,n,ax",
            transmit_power="80",
            max_associations="32",
        )
        self.assertEqual(validate_wifi_settings(valid), ())
        self.assertEqual(
            validate_wifi_settings(
                DutWifiSettings(
                    band="5G",
                    ssid="Open_WiFi",
                    password="",
                    channel="36",
                    channel_bandwidth="80MHz",
                    security_mode="None",
                    operating_mode="a,n,ac,ax",
                )
            ),
            (),
        )

        errors = validate_wifi_settings(
            DutWifiSettings(
                band="5G",
                ssid="X" * 33,
                password="short",
                channel="6",
                channel_bandwidth="20/40MHz",
                operating_mode="b,g,n,ax",
                transmit_power="101",
                max_associations="65",
            )
        )
        self.assertTrue(any("32 字节" in error for error in errors))
        self.assertTrue(any("密码" in error for error in errors))
        self.assertTrue(any("5G WiFi 信道" in error for error in errors))
        self.assertTrue(any("信道带宽" in error for error in errors))
        self.assertTrue(any("协议类型" in error for error in errors))
        self.assertTrue(any("发射功率" in error for error in errors))
        self.assertTrue(any("最大接入数" in error for error in errors))

    def test_wifi_validation_uses_dut_reported_capabilities_when_available(self) -> None:
        supported = DutWifiSettings(
            band="2.4G",
            ssid="Capability_WiFi",
            password="password123",
            channel="11",
            channel_bandwidth="20/40MHz",
            security_mode="WPA2-WPA3-Personal",
            operating_mode="g,n,ax",
            transmit_power="75",
            max_associations="32",
            supported_channels=("auto", "1", "6", "11"),
            supported_bandwidths=("20MHz", "20/40MHz"),
            supported_modes=("g,n", "g,n,ax"),
            supported_security_modes=("None", "WPA2-WPA3-Personal"),
            supported_transmit_powers=("25", "50", "75", "100"),
        )
        self.assertEqual(validate_wifi_settings(supported), ())

        errors = validate_wifi_settings(
            DutWifiSettings(
                **{
                    **supported.__dict__,
                    "security_mode": "WPA3-Personal",
                    "channel": "13",
                    "channel_bandwidth": "40MHz",
                    "operating_mode": "b,g,n,ax",
                    "transmit_power": "80",
                }
            )
        )
        self.assertTrue(any("认证/加密模式" in error for error in errors))
        self.assertTrue(any("信道不在DUT支持列表" in error for error in errors))
        self.assertTrue(any("信道带宽" in error for error in errors))
        self.assertTrue(any("协议类型" in error for error in errors))
        self.assertTrue(any("发射功率不在DUT支持列表" in error for error in errors))

    def test_dual_stack_static_validation_accepts_complete_ipoe_settings(self) -> None:
        settings = DutWanSettings(
            vlan_id="200",
            ip_protocol="IPv4IPv6",
            ipv4_type="Static",
            ipv4_address="172.18.18.43",
            ipv4_netmask="255.255.255.0",
            ipv4_gateway="172.18.18.1",
            ipv4_primary_dns="8.8.8.8",
            ipv6_type="Static",
            ipv6_address="2001:db8::2",
            ipv6_prefix="2001:db8::/64",
            ipv6_gateway="2001:db8::1",
            ipv6_primary_dns="2001:4860:4860::8888",
        )

        self.assertEqual(validate_wan_settings(settings), ())

    def test_wan_delete_requires_existing_connection_index(self) -> None:
        errors = validate_wan_settings(DutWanSettings(operation="delete"))
        self.assertTrue(any("连接名或索引" in error for error in errors))

    def test_pppoe_static_ipv4_is_rejected(self) -> None:
        errors = validate_wan_settings(
            DutWanSettings(
                vlan_id="200",
                access_type="PPPoE",
                pppoe_username="user",
                pppoe_password="pass",
                ipv4_type="Static",
                ipv4_address="172.18.18.2",
                ipv4_netmask="255.255.255.0",
                ipv4_gateway="172.18.18.1",
                ipv4_primary_dns="8.8.8.8",
            )
        )
        self.assertTrue(any("PPPoE 不支持静态 IPv4" in error for error in errors))

    def test_pppoe_static_ipv6_and_invalid_dual_stack_pair_are_rejected(self) -> None:
        errors = validate_wan_settings(
            DutWanSettings(
                vlan_id="200",
                access_type="PPPoE",
                pppoe_username="user",
                pppoe_password="pass",
                ip_protocol="IPv4IPv6",
                ipv4_type="Dynamic",
                ipv6_type="Static",
                ipv6_address="2001:db8::2",
                ipv6_prefix="2001:db8::/64",
                ipv6_gateway="2001:db8::1",
                ipv6_primary_dns="2001:4860:4860::8888",
            )
        )

        self.assertTrue(any("PPPoE 不支持静态 IPv6" in error for error in errors))
        self.assertTrue(any("PPPoE 双栈地址方式组合不受支持" in error for error in errors))

    def test_ipoe_dual_stack_rejects_mixed_static_and_dynamic_modes(self) -> None:
        errors = validate_wan_settings(
            DutWanSettings(
                vlan_id="200",
                ip_protocol="IPv4IPv6",
                ipv4_type="Static",
                ipv4_address="172.18.18.2",
                ipv4_netmask="255.255.255.0",
                ipv4_gateway="172.18.18.1",
                ipv4_primary_dns="8.8.8.8",
                ipv6_type="SLAAC",
            )
        )

        self.assertTrue(any("IPoE 双栈地址方式组合不受支持" in error for error in errors))

    def test_bridge_service_type_is_limited_to_reference_supported_values(self) -> None:
        errors = validate_wan_settings(
            DutWanSettings(mode="bridge", service_type="TR069", vlan_id="200")
        )

        self.assertTrue(any("桥接 WAN 的业务类型仅支持" in error for error in errors))

    def test_iptv_multicast_vlan_is_optional_but_validated_when_present(self) -> None:
        self.assertEqual(
            validate_wan_settings(
                DutWanSettings(service_type="IPTV", vlan_id="600", multicast_vlan_id="")
            ),
            (),
        )
        self.assertEqual(
            validate_wan_settings(
                DutWanSettings(service_type="IPTV", vlan_id="600", multicast_vlan_id="222")
            ),
            (),
        )
        for invalid_value in ("0", "4095", "not-a-vlan"):
            errors = validate_wan_settings(
                DutWanSettings(
                    service_type="IPTV",
                    vlan_id="600",
                    multicast_vlan_id=invalid_value,
                )
            )
            self.assertTrue(any("组播 VLAN ID 必须为 1–4094" in error for error in errors))

        non_iptv_errors = validate_wan_settings(
            DutWanSettings(
                service_type="INTERNET",
                vlan_id="172",
                multicast_vlan_id="stale-hidden-value",
            )
        )
        self.assertFalse(any("组播 VLAN" in error for error in non_iptv_errors))

    def test_voice_and_tr069_validation_report_missing_required_fields(self) -> None:
        voice_errors = validate_voice_settings(DutVoiceSettings())
        tr069_errors = validate_tr069_settings(DutTr069Settings())
        self.assertTrue(any("SIP 显示名称" in error for error in voice_errors))
        self.assertTrue(any("ACS URL" in error for error in tr069_errors))

    def test_voice_sip_mode_accepts_imssip_and_rejects_unknown_values(self) -> None:
        common = {
            "account_enabled": False,
            "proxy_server": "172.33.5.251",
            "registrar_server": "172.33.5.251",
        }

        self.assertEqual(
            VOICE_SIP_MODE_OPTIONS,
            ("SIP", "IMSSIP", "UDP", "TCP", "TLS"),
        )
        for sip_mode in VOICE_SIP_MODE_OPTIONS:
            self.assertEqual(
                validate_voice_settings(DutVoiceSettings(sip_mode=sip_mode, **common)),
                (),
            )
        errors = validate_voice_settings(
            DutVoiceSettings(sip_mode="UNKNOWN", **common)
        )
        self.assertTrue(any("SIP 模式无效" in error for error in errors))

    def test_voice_and_tr069_validation_follow_reported_dut_capabilities(self) -> None:
        voice = DutVoiceSettings(
            account_enabled=False,
            proxy_server="172.33.5.251",
            registrar_server="172.33.5.251",
            dtmf_method="InBand",
            sip_mode="TLS",
            codecs=("G.729",) * 5,
            supported_dtmf_methods=("RFC2833",),
            supported_sip_modes=("SIP", "IMSSIP"),
            supported_codecs=("G.711 U-law", "G.729"),
        )
        voice_errors = validate_voice_settings(voice)
        self.assertTrue(any("DTMF 模式无效" in error for error in voice_errors))
        self.assertTrue(any("SIP 模式无效" in error for error in voice_errors))

        tr069_errors = validate_tr069_settings(
            DutTr069Settings(
                acs_url="",
                periodic_inform_interval="",
                manual_inform=True,
                supported_fields=("acs_username",),
            )
        )
        self.assertEqual(tr069_errors, ("当前DUT不支持配置后手动 Inform",))

    def test_single_wan_success_prepares_network_logs_in_and_closes_client(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        calls: list[tuple] = []
        network_calls: list[tuple] = []
        request = _request("wan", DutWanSettings(vlan_id="200"))

        result = run_single_dut_advanced_config(
            request,
            on_output=logs.append,
            network_prepare_fn=lambda *args, **kwargs: network_calls.append((args, kwargs))
            or CommandResult(True, "ok"),
            bind_waiter=lambda ip, timeout: ip == "192.168.1.112" and timeout == 15,
            client_factory=lambda *_args, **_kwargs: client,
            wan_fn=lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.stage, "completed")
        self.assertTrue(client.closed)
        self.assertTrue(network_calls[0][1]["reuse_if_ready"])
        self.assertEqual(calls[0][0][1], "session-id")
        self.assertTrue(any("password=plain-password" in line for line in logs))
        self.assertTrue(any("成功：WAN 操作成功" in line for line in logs))

    def test_single_wifi_success_routes_to_wifi_protocol_and_logs_band(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        calls: list[tuple] = []
        settings = DutWifiSettings(
            band="5G",
            ssid="Lab_5G",
            password="password123",
            channel_bandwidth="160MHz",
            operating_mode="a,n,ac,ax",
        )

        result = run_single_dut_advanced_config(
            _request("wifi_5g", settings),
            on_output=logs.append,
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(True, "ok"),
            bind_waiter=lambda _ip, _timeout: True,
            client_factory=lambda *_args, **_kwargs: client,
            wifi_fn=lambda *args, **kwargs: calls.append((args, kwargs)) or settings,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls[0][0][2], settings)
        self.assertTrue(callable(calls[0][1]["sleep_fn"]))
        self.assertTrue(client.closed)
        self.assertTrue(any("[5G WiFi配置]" in line for line in logs))
        self.assertTrue(any("成功：5G WiFi 配置成功" in line for line in logs))

    def test_batch_stop_skips_not_started_devices(self) -> None:
        stop_event = threading.Event()
        requests = [
            _request("wan", DutWanSettings(vlan_id="200")),
            DutAdvancedConfigRequest(
                **{
                    **_request("wan", DutWanSettings(vlan_id="201")).__dict__,
                    "channel": "通道 13",
                }
            ),
        ]
        started: list[str] = []

        def runner(request, **_kwargs):
            started.append(request.channel)
            stop_event.set()
            return DutAdvancedConfigResult(request, True, "completed", "ok")

        results = run_dut_advanced_config_batch(
            requests, max_workers=1, stop_event=stop_event, single_runner=runner
        )

        self.assertEqual(started, ["通道 12"])
        self.assertEqual([result.stage for result in results], ["completed", "stopped"])


if __name__ == "__main__":
    unittest.main()

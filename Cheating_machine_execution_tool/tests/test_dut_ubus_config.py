from __future__ import annotations

import unittest

from src.core.dut_ubus_config import (
    MANAGEMENT_SERVER_PATH,
    WAN_COMMAND,
    WAN_INTERFACE_PATH,
    build_wan_input,
    configure_tr069,
    configure_voice,
    configure_wan,
    query_wan_connection_names,
)
from src.models import DutTr069Settings, DutVoiceSettings, DutWanSettings


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.management_values: dict = {}

    def bbfdm_operate(self, session, command, payload, optional=None):
        self.calls.append(("operate", session, command, payload, optional))
        return [0, {"results": [{"output": [{"Result": "OK"}]}]}]

    def bbfdm_set(self, session, path, values, optional=None):
        self.calls.append(("set", session, path, values, optional))
        if path == MANAGEMENT_SERVER_PATH:
            self.management_values = dict(values)
        return [0, {"results": [{"data": "1"}]}]

    def call(self, session, service, method, payload):
        self.calls.append(("call", session, service, method, payload))
        return [0, {"results": [{"data": "1"}]}]

    def bbfdm_get(self, session, path, optional=None):
        self.calls.append(("get", session, path, optional))
        if path == MANAGEMENT_SERVER_PATH:
            return [0, {"ManagementServer": dict(self.management_values)}]
        return [0, {}]


class DutUbusConfigTests(unittest.TestCase):
    def test_build_dual_stack_static_ipv4_and_dhcpv6_payload(self) -> None:
        settings = DutWanSettings(
            operation="add",
            mode="router",
            service_type="TR069_INTERNET",
            vlan_id="200",
            vlan_priority="3",
            port_bind="1&&8",
            access_type="IPoE",
            ip_protocol="IPv4IPv6",
            ipv4_type="Static",
            ipv4_address="172.18.18.43",
            ipv4_netmask="255.255.255.0",
            ipv4_gateway="172.18.18.1",
            ipv4_primary_dns="202.96.134.133",
            ipv6_type="DHCPv6",
        )

        payload = build_wan_input(settings)

        self.assertEqual(payload["IPProtocol"], "IPv4AndIPv6")
        self.assertEqual(payload["IPv4Type"], "Static")
        self.assertEqual(payload["IPv4Address"], "172.18.18.43")
        self.assertEqual(payload["IPv6Type"], "Dynamic")
        self.assertEqual(payload["DHCPv6AddressAssignment"], 1)
        self.assertEqual(payload["SLAAC"], 0)
        self.assertEqual(payload["PortBind"], 9)

    def test_build_modify_and_delete_use_existing_wan_index(self) -> None:
        modified = build_wan_input(
            DutWanSettings(
                operation="modify",
                connection_index="3_TR069_INTERNET_R_VID_200",
                vlan_id="201",
            )
        )
        deleted = build_wan_input(
            DutWanSettings(operation="delete", connection_index="5_IPTV_R_VID_123")
        )

        self.assertEqual(modified["Method"], "modify")
        self.assertEqual(modified["Index"], 3)
        self.assertEqual(deleted["Method"], "Delete")
        self.assertEqual(deleted["Index"], 5)

    def test_wan_operate_logs_actual_command_and_payload(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        configure_wan(
            client,
            "session",
            DutWanSettings(operation="add", vlan_id="200"),
            on_log=logs.append,
        )

        operate = client.calls[0]
        self.assertEqual(operate[0:3], ("operate", "session", WAN_COMMAND))
        self.assertTrue(any("bbfdm.operate" in item and '"VLAN": "200"' in item for item in logs))

    def test_query_wan_connection_names_filters_non_wan_and_sorts_by_index(self) -> None:
        client = _FakeClient()
        logs: list[str] = []

        def get_interfaces(session, path, optional=None):
            client.calls.append(("get", session, path, optional))
            return [
                0,
                {
                    "Interface": [
                        {"Name": "12_VOICE_R_VID_335"},
                        {"Name": "LAN"},
                        {"Name": "3_INTERNET_R_VID_200"},
                        {"Name": "2_OTHER_B_VID_TRANSP"},
                        {"Name": "not-a-wan"},
                        {"Name": "3_INTERNET_R_VID_200"},
                    ]
                },
            ]

        client.bbfdm_get = get_interfaces  # type: ignore[method-assign]

        names = query_wan_connection_names(client, "session", on_log=logs.append)

        self.assertEqual(
            names,
            ("3_INTERNET_R_VID_200", "12_VOICE_R_VID_335"),
        )
        self.assertEqual(client.calls[0][2], WAN_INTERFACE_PATH)
        self.assertTrue(any("bbfdm.get" in line and WAN_INTERFACE_PATH in line for line in logs))

    def test_voice_config_sets_server_account_codecs_and_reads_back(self) -> None:
        client = _FakeClient()
        settings = DutVoiceSettings(
            display_name="1001",
            auth_username="1001",
            auth_password="voice-pass",
            proxy_server="172.33.5.251",
            outbound_proxy="172.33.5.251",
            registrar_server="172.33.5.251",
        )

        configure_voice(client, "session", settings)

        paths = [call[2] for call in client.calls if call[0] == "set"]
        self.assertIn("Device.Services.VoiceService.1.SIP.Network.1.", paths)
        self.assertIn("Device.Services.VoiceService.1.SIP.Client.1.", paths)
        codec_call = next(call for call in client.calls if call[0] == "call")
        self.assertEqual(len(codec_call[4]["paths"]), 5)
        self.assertTrue(any(call[0] == "get" for call in client.calls))

    def test_tr069_config_sets_plaintext_credentials_and_verifies_readback(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        settings = DutTr069Settings(
            acs_url="http://acs.example.com:7547/acs",
            acs_username="hgw",
            acs_password="plain-acs-pass",
            connection_request_username="itms",
            connection_request_password="plain-request-pass",
        )

        configure_tr069(client, "session", settings, on_log=logs.append)

        set_call = next(call for call in client.calls if call[0] == "set")
        self.assertEqual(set_call[2], MANAGEMENT_SERVER_PATH)
        self.assertEqual(set_call[3]["Password"], "plain-acs-pass")
        self.assertEqual(set_call[3]["ConnectionRequestPassword"], "plain-request-pass")
        self.assertTrue(any("跳过：未勾选配置后手动 Inform" in item for item in logs))

    def test_tr069_manual_inform_waits_for_success_result(self) -> None:
        client = _FakeClient()
        original_get = client.bbfdm_get

        def get_with_inform(session, path, optional=None):
            if path.endswith("X_SDMC_ManualInformStage"):
                return [0, {"X_SDMC_ManualInformStage": "3_finish_inform"}]
            if path.endswith("X_SDMC_InformResult"):
                return [0, {"X_SDMC_InformResult": "10_success"}]
            return original_get(session, path, optional)

        client.bbfdm_get = get_with_inform  # type: ignore[method-assign]
        logs: list[str] = []
        configure_tr069(
            client,
            "session",
            DutTr069Settings(
                acs_url="http://acs.example.com:7547/acs",
                manual_inform=True,
            ),
            on_log=logs.append,
            sleep_fn=lambda _seconds: None,
        )

        trigger = next(call for call in client.calls if call[0] == "call")
        self.assertEqual(trigger[3], "set")
        self.assertEqual(trigger[4]["value"], "1_wait_inform")
        self.assertTrue(any("手动 Inform 已完成" in item for item in logs))


if __name__ == "__main__":
    unittest.main()

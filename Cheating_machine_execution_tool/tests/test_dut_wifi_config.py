from __future__ import annotations

import unittest

from src.core.dut_wifi_config import (
    WIFI_APPLY_SETTLE_SECONDS,
    WIFI_GET_RETRY_DELAY_SECONDS,
    apply_wifi_config,
    configure_wifi,
    query_wifi_status,
    resolve_wifi_paths,
    verify_wifi_config,
)
from src.core.ubus_http_client import UbusTransportError
from src.models import DutWifiSettings


class _FakeWifiClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.dual = "0,0"
        self.ssids = {
            "Device.WiFi.SSID.11.": {"X_SDMC_Instance": 11, "Enable": True, "SSID": "Old_2G"},
            "Device.WiFi.SSID.12.": {"X_SDMC_Instance": 12, "Enable": True, "SSID": "Old_5G"},
        }
        self.aps = {
            "Device.WiFi.AccessPoint.21.": {
                "X_SDMC_Instance": 21,
                "MaxAllowedAssociations": "32",
                "SSIDAdvertisementEnabled": "1",
                "WMMEnable": "1",
                "Security": {
                    "ModeEnabled": "WPA2-Personal",
                    "ModesSupported": "None,WPA2-Personal,WPA3-Personal-Transition",
                    "X_SDMC_Key": "password2g",
                },
            },
            "Device.WiFi.AccessPoint.22.": {
                "X_SDMC_Instance": 22,
                "MaxAllowedAssociations": "32",
                "SSIDAdvertisementEnabled": "1",
                "WMMEnable": "1",
                "Security": {
                    "ModeEnabled": "WPA2-Personal",
                    "ModesSupported": "None,WPA2-Personal,WPA3-Personal-Transition",
                    "X_SDMC_Key": "password5g",
                },
            },
        }
        mode_map_2g = '{"list":[{"standard":"b,g,n,ax","bw":"20MHz,40MHz,20/40MHz"}]}'
        mode_map_5g = '{"list":[{"standard":"a,n,ac,ax","bw":"20MHz,40MHz,80MHz,160MHz"}]}'
        self.radios = {
            "Device.WiFi.Radio.31.": {
                "X_SDMC_Instance": 31,
                "X_SDMC_ChannelEnabled": "auto",
                "Channel": "1",
                "OperatingChannelBandwidth": "20/40MHz",
                "OperatingStandards": "b,g,n,ax",
                "TransmitPower": "100",
                "TransmitPowerSupported": "20,40,60,80,100",
                "X_SDMC_ChannelsSupported": "1,6,11",
                "X_SDMC_ModeBWMap": mode_map_2g,
            },
            "Device.WiFi.Radio.32.": {
                "X_SDMC_Instance": 32,
                "X_SDMC_ChannelEnabled": "auto",
                "Channel": "36",
                "OperatingChannelBandwidth": "160MHz",
                "OperatingStandards": "a,n,ac,ax",
                "TransmitPower": "80",
                "X_SDMC_TransmitPowerSupported": "25,50,75,100",
                "X_SDMC_ChannelsSupported": "36,40,44,48",
                "X_SDMC_ModeBWMap": mode_map_5g,
            },
        }

    def bbfdm_get(self, session, path, optional=None):
        self.calls.append(("get", session, path, optional))
        if path == "Device.WiFi.X_SDMC_Mapping_2G":
            return [0, {"X_SDMC_Mapping_2G": "1,1,1"}]
        if path == "Device.WiFi.X_SDMC_Mapping_5G":
            return [0, {"X_SDMC_Mapping_5G": "2,2,2"}]
        if path == "Device.WiFi.X_SDMC_DualBandEnable":
            return [0, {"X_SDMC_DualBandEnable": self.dual}]
        if path == "Device.WiFi.Radio.":
            return [0, {"Radio": list(self.radios.values())}]
        if path == "Device.WiFi.AccessPoint.":
            return [0, {"AccessPoint": list(self.aps.values())}]
        if path == "Device.WiFi.SSID.":
            return [0, {"SSID": list(self.ssids.values())}]
        if path in self.radios:
            return [0, {"Radio": [dict(self.radios[path])]}]
        if path in self.aps:
            return [0, {"AccessPoint": [dict(self.aps[path])]}]
        if path in self.ssids:
            return [0, {"SSID": [dict(self.ssids[path])]}]
        raise AssertionError(f"unexpected get path: {path}")

    def call(self, session, service, method, payload):
        self.calls.append(("call", session, service, method, payload))
        if method != "set":
            raise AssertionError(f"unexpected method: {method}")
        for item in payload["paths"]:
            path = item["addr"]
            values = item["obj_path"]
            if path == "Device.WiFi.":
                self.dual = values["X_SDMC_DualBandEnable"]
            elif path in self.ssids:
                self.ssids[path].update(values)
            elif path in self.aps:
                self.aps[path].update(values)
            elif path.endswith("Security."):
                ap_path = path.removesuffix("Security.")
                self.aps[ap_path]["Security"].update(values)
            elif path in self.radios:
                self.radios[path].update(values)
            else:
                raise AssertionError(f"unexpected set path: {path}")
        return [0, {"results": [{"data": "1"}]}]


class _TransientRadioListClient(_FakeWifiClient):
    def __init__(self) -> None:
        super().__init__()
        self.radio_list_failures = 0

    def bbfdm_get(self, session, path, optional=None):
        if path == "Device.WiFi.Radio." and self.radio_list_failures == 0:
            self.calls.append(("get", session, path, optional))
            self.radio_list_failures += 1
            raise UbusTransportError(
                "UBUS HTTP 请求失败 192.168.1.1:80：timed out"
            )
        return super().bbfdm_get(session, path, optional)


class DutWifiConfigTests(unittest.TestCase):
    def test_query_resolves_vendor_mapping_and_never_sets(self) -> None:
        client = _FakeWifiClient()
        logs: list[str] = []

        settings = query_wifi_status(
            client, "session", "2.4G", "1", on_log=logs.append
        )

        self.assertEqual(settings.ssid, "Old_2G")
        self.assertEqual(settings.channel, "auto")
        self.assertFalse(settings.dual_band_enabled)
        self.assertEqual(settings.supported_channels, ("1", "6", "11"))
        self.assertEqual(
            settings.supported_security_modes,
            ("None", "WPA2-Personal", "WPA3-Personal-Transition"),
        )
        self.assertEqual(
            settings.supported_transmit_powers, ("20", "40", "60", "80", "100")
        )
        self.assertEqual(
            resolve_wifi_paths(client, "session", "5G", "1"),
            {
                "radio": "Device.WiFi.Radio.32.",
                "access_point": "Device.WiFi.AccessPoint.22.",
                "ssid": "Device.WiFi.SSID.12.",
            },
        )
        self.assertFalse(any(call[0] == "call" for call in client.calls))
        self.assertTrue(any("Device.WiFi.X_SDMC_Mapping_2G" in line for line in logs))

    def test_5g_query_uses_its_own_radio_and_capability_lists(self) -> None:
        client = _FakeWifiClient()

        settings = query_wifi_status(client, "session", "5G", "1")

        self.assertEqual(settings.band, "5G")
        self.assertEqual(settings.ssid, "Old_5G")
        self.assertEqual(settings.channel, "auto")
        self.assertEqual(settings.supported_channels, ("36", "40", "44", "48"))
        self.assertEqual(
            settings.supported_bandwidths,
            ("20MHz", "40MHz", "80MHz", "160MHz"),
        )
        self.assertEqual(settings.supported_modes, ("a,n,ac,ax",))
        self.assertEqual(
            settings.supported_transmit_powers, ("25", "50", "75", "100")
        )

    def test_query_retries_transient_radio_get_after_reconnect_delay(self) -> None:
        client = _TransientRadioListClient()
        logs: list[str] = []
        delays: list[float] = []

        settings = query_wifi_status(
            client,
            "session",
            "2.4G",
            "1",
            on_log=logs.append,
            sleep_fn=delays.append,
        )

        self.assertEqual(settings.ssid, "Old_2G")
        self.assertEqual(delays, [WIFI_GET_RETRY_DELAY_SECONDS])
        radio_list_gets = [
            call
            for call in client.calls
            if call[0] == "get" and call[2] == "Device.WiFi.Radio."
        ]
        self.assertEqual(len(radio_list_gets), 2)
        self.assertTrue(any("重建连接重试 1/1" in line for line in logs))

    def test_configure_dual_band_syncs_ssid_security_but_only_target_radio(self) -> None:
        client = _FakeWifiClient()
        settings = DutWifiSettings(
            band="2.4G",
            ssid_index="1",
            ssid="Merged_WiFi",
            password="merged-pass",
            channel="6",
            channel_bandwidth="40MHz",
            dual_band_enabled=True,
            enabled=True,
            hidden=True,
            security_mode="WPA2-Personal",
            operating_mode="b,g,n,ax",
            transmit_power="60",
            max_associations="20",
            wmm_enabled=False,
        )

        delays: list[float] = []
        actual = configure_wifi(
            client, "session", settings, sleep_fn=delays.append
        )

        self.assertEqual(actual.ssid, "Merged_WiFi")
        self.assertEqual(client.dual, "1,0")
        self.assertEqual(client.ssids["Device.WiFi.SSID.12."]["SSID"], "Merged_WiFi")
        self.assertEqual(
            client.aps["Device.WiFi.AccessPoint.22."]["Security"]["X_SDMC_Key"],
            "merged-pass",
        )
        self.assertEqual(client.radios["Device.WiFi.Radio.31."]["X_SDMC_ChannelEnabled"], "6")
        self.assertEqual(client.radios["Device.WiFi.Radio.32."]["X_SDMC_ChannelEnabled"], "auto")
        self.assertEqual(delays, [WIFI_APPLY_SETTLE_SECONDS])
        set_payload = next(call[4] for call in client.calls if call[0] == "call")
        self.assertIn(
            "Device.WiFi.AccessPoint.22.Security.",
            [item["addr"] for item in set_payload["paths"]],
        )

    def test_apply_and_verify_can_share_one_batch_settle_wait(self) -> None:
        client = _FakeWifiClient()
        settings = DutWifiSettings(
            band="2.4G",
            ssid="Batch_001",
            password="batch-pass",
            channel="6",
            channel_bandwidth="40MHz",
            security_mode="WPA2-Personal",
            operating_mode="b,g,n,ax",
        )
        delays: list[float] = []

        applied = apply_wifi_config(
            client,
            "session",
            settings,
            sleep_fn=delays.append,
        )

        self.assertIsNone(applied)
        self.assertEqual(delays, [])
        self.assertEqual(client.ssids["Device.WiFi.SSID.11."]["SSID"], "Batch_001")
        call_count_after_apply = sum(call[0] == "call" for call in client.calls)

        actual = verify_wifi_config(
            client,
            "session",
            settings,
            sleep_fn=delays.append,
        )

        self.assertEqual(actual.ssid, "Batch_001")
        self.assertEqual(delays, [])
        self.assertEqual(
            sum(call[0] == "call" for call in client.calls),
            call_count_after_apply,
        )

    def test_open_network_does_not_send_stale_password(self) -> None:
        client = _FakeWifiClient()
        settings = DutWifiSettings(
            band="5G",
            ssid="Open_WiFi",
            password="stale-password",
            channel_bandwidth="80MHz",
            security_mode="None",
            operating_mode="a,n,ac,ax",
        )

        configure_wifi(client, "session", settings, sleep_fn=lambda _seconds: None)

        set_payload = next(call[4] for call in client.calls if call[0] == "call")
        security_items = [
            item for item in set_payload["paths"] if item["addr"].endswith("Security.")
        ]
        self.assertEqual(security_items[0]["obj_path"], {"ModeEnabled": "None"})

    def test_consecutive_configurations_each_wait_for_wifi_to_stabilize(self) -> None:
        client = _FakeWifiClient()
        settings = DutWifiSettings(
            band="2.4G",
            ssid="Repeat_WiFi",
            password="repeat-pass",
            channel="6",
            channel_bandwidth="40MHz",
            security_mode="WPA2-Personal",
            operating_mode="b,g,n,ax",
        )
        delays: list[float] = []

        first = configure_wifi(
            client, "session", settings, sleep_fn=delays.append
        )
        second = configure_wifi(
            client, "session", settings, sleep_fn=delays.append
        )

        self.assertEqual(first.ssid, "Repeat_WiFi")
        self.assertEqual(second.ssid, "Repeat_WiFi")
        self.assertEqual(
            delays, [WIFI_APPLY_SETTLE_SECONDS, WIFI_APPLY_SETTLE_SECONDS]
        )


if __name__ == "__main__":
    unittest.main()

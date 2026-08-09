from __future__ import annotations

import threading
import unittest

from line_check_assistant.network_ops import CommandResult
from src.models import DutTelnetEnableRequest, DutWanConnectionInfo, DutWanQueryResult
from src.services.dut_wan_query_service import (
    common_wan_connection_details,
    common_wan_connection_names,
    run_dut_wan_query_batch,
    run_single_dut_wan_query,
)


def _request(channel: str = "通道 12") -> DutTelnetEnableRequest:
    return DutTelnetEnableRequest(
        channel=channel,
        vlan="vlan112",
        adapter_alias="VLAN112",
        bind_ip="192.168.1.112",
        device_host="192.168.1.1",
        subnet_mask="255.255.255.0",
        username="telecomadmin",
        password="plain-password",
    )


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False
        self.logged_out_sessions: list[str] = []

    def login(self, username, password):
        if (username, password) != ("telecomadmin", "plain-password"):
            raise RuntimeError("bad credentials")
        return "session-id"

    def logout(self, session_id):
        self.logged_out_sessions.append(session_id)

    def close(self):
        self.closed = True


class DutWanQueryServiceTests(unittest.TestCase):
    def test_single_query_prepares_network_logs_real_get_and_closes_client(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        network_calls: list[tuple] = []

        result = run_single_dut_wan_query(
            _request(),
            on_output=logs.append,
            network_prepare_fn=lambda *args, **kwargs: network_calls.append((args, kwargs))
            or CommandResult(True, "ok"),
            bind_waiter=lambda ip, timeout: ip == "192.168.1.112" and timeout == 15,
            client_factory=lambda *_args, **_kwargs: client,
            query_fn=lambda _client, session, on_log=None: (
                on_log("TX UBUS bbfdm.get path=Device.IP.Interface."),
                ("3_INTERNET_R_VID_200", "5_IPTV_B_VID_600"),
            )[1],
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertTrue(client.closed)
        self.assertEqual(client.logged_out_sessions, ["session-id"])
        self.assertTrue(network_calls[0][1]["reuse_if_ready"])
        self.assertEqual(
            result.connection_names,
            ("3_INTERNET_R_VID_200", "5_IPTV_B_VID_600"),
        )
        self.assertTrue(any("password=plain-password" in line for line in logs))
        self.assertTrue(any("Device.IP.Interface." in line for line in logs))
        self.assertTrue(any("Device.X_SDMC_Login.logout()" in line for line in logs))

    def test_consecutive_queries_release_previous_device_session(self) -> None:
        device_state = {"active_session": "", "counter": 0}

        class SessionLimitedClient:
            def __init__(self) -> None:
                self.closed = False

            def login(self, _username, _password):
                if device_state["active_session"]:
                    raise RuntimeError("Access denied: previous session is still active")
                device_state["counter"] += 1
                session_id = f"session-{device_state['counter']}"
                device_state["active_session"] = session_id
                return session_id

            def logout(self, session_id):
                if device_state["active_session"] == session_id:
                    device_state["active_session"] = ""

            def close(self):
                self.closed = True

        common_kwargs = {
            "network_prepare_fn": lambda *_args, **_kwargs: CommandResult(True, "ok"),
            "bind_waiter": lambda _ip, _timeout: True,
            "client_factory": lambda *_args, **_kwargs: SessionLimitedClient(),
            "query_fn": lambda _client, _session, on_log=None: ("3_INTERNET_R_VID_172",),
            "sleep_fn": lambda _seconds: None,
        }

        first = run_single_dut_wan_query(_request(), **common_kwargs)
        second = run_single_dut_wan_query(_request(), **common_kwargs)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(device_state["active_session"], "")
        self.assertEqual(device_state["counter"], 2)

    def test_common_names_requires_every_target_and_exact_name_match(self) -> None:
        first = DutWanQueryResult(
            _request("通道 12"),
            True,
            "completed",
            "ok",
            ("3_INTERNET_R_VID_200", "5_IPTV_B_VID_600"),
        )
        second = DutWanQueryResult(
            _request("通道 13"),
            True,
            "completed",
            "ok",
            ("3_VOICE_R_VID_335", "5_IPTV_B_VID_600"),
        )

        self.assertEqual(common_wan_connection_names((first, second)), ("5_IPTV_B_VID_600",))
        failed = DutWanQueryResult(_request("通道 13"), False, "query", "failed")
        self.assertEqual(common_wan_connection_names((first, failed)), ())

    def test_common_details_requires_identical_snapshot_on_every_target(self) -> None:
        info = DutWanConnectionInfo(
            name="3_INTERNET_R_VID_172",
            index="3",
            mode="router",
            service_type="INTERNET",
            vlan_id="172",
        )
        first = DutWanQueryResult(
            _request("通道 12"), True, "completed", "ok", (info.name,), (info,)
        )
        second = DutWanQueryResult(
            _request("通道 13"), True, "completed", "ok", (info.name,), (info,)
        )

        self.assertEqual(common_wan_connection_details((first, second)), {info.name: info})

        changed = DutWanConnectionInfo(
            name=info.name,
            index="3",
            mode="router",
            service_type="INTERNET",
            vlan_id="173",
        )
        second = DutWanQueryResult(
            _request("通道 13"), True, "completed", "ok", (info.name,), (changed,)
        )
        self.assertEqual(common_wan_connection_details((first, second)), {})

    def test_batch_stop_does_not_start_later_queries(self) -> None:
        stop_event = threading.Event()
        started: list[str] = []

        def runner(request, **_kwargs):
            started.append(request.channel)
            stop_event.set()
            return DutWanQueryResult(request, True, "completed", "ok", ())

        results = run_dut_wan_query_batch(
            (_request("通道 12"), _request("通道 13")),
            max_workers=1,
            stop_event=stop_event,
            single_runner=runner,
        )

        self.assertEqual(started, ["通道 12"])
        self.assertEqual([result.stage for result in results], ["completed", "stopped"])


if __name__ == "__main__":
    unittest.main()

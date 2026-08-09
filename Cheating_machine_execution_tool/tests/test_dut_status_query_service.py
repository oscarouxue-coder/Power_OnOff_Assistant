from __future__ import annotations

import threading
import unittest

from line_check_assistant.network_ops import CommandResult
from src.models import (
    DutAdvancedQueryResult,
    DutTelnetEnableRequest,
    DutTelnetStatus,
    DutTr069Settings,
    DutVoiceSettings,
)
from src.services.dut_status_query_service import (
    common_dut_status_settings,
    run_dut_status_query_batch,
    run_single_dut_status_query,
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


class DutStatusQueryServiceTests(unittest.TestCase):
    def test_single_telnet_query_uses_readonly_status_result_and_logs_out(self) -> None:
        client = _FakeClient()
        expected = DutTelnetStatus(
            access_control_enabled=True,
            rule_present=True,
            rule_enabled=True,
            source_interfaces=("lan",),
            tcp_port_open=True,
            probe_message="TCP 23可连接",
        )
        result = run_single_dut_status_query(
            _request(),
            "telnet",
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(True, "ok"),
            bind_waiter=lambda _ip, _timeout: True,
            client_factory=lambda *_args, **_kwargs: client,
            query_fn=lambda _client, _session, on_log=None: expected,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.settings, expected)
        self.assertEqual(client.logged_out_sessions, ["session-id"])
        self.assertTrue(client.closed)

    def test_single_voice_query_reuses_network_logs_out_and_returns_settings(self) -> None:
        client = _FakeClient()
        logs: list[str] = []
        network_calls: list[tuple] = []
        expected = DutVoiceSettings(line_index="2", sip_mode="IMSSIP")

        result = run_single_dut_status_query(
            _request(),
            "voice",
            line_index="2",
            on_output=logs.append,
            network_prepare_fn=lambda *args, **kwargs: network_calls.append((args, kwargs))
            or CommandResult(True, "ok"),
            bind_waiter=lambda ip, timeout: ip == "192.168.1.112" and timeout == 15,
            client_factory=lambda *_args, **_kwargs: client,
            query_fn=lambda _client, session, line_index, on_log=None: (
                on_log(f"TX UBUS bbfdm.get voice line={line_index} session={session}"),
                expected,
            )[1],
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.settings, expected)
        self.assertTrue(network_calls[0][1]["reuse_if_ready"])
        self.assertEqual(client.logged_out_sessions, ["session-id"])
        self.assertTrue(client.closed)
        self.assertTrue(any("password=plain-password" in item for item in logs))
        self.assertTrue(any("Device.X_SDMC_Login.logout()" in item for item in logs))

    def test_single_tr069_query_uses_same_readonly_flow(self) -> None:
        expected = DutTr069Settings(acs_url="http://acs.example.com/acs")
        result = run_single_dut_status_query(
            _request(),
            "tr069",
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(True, "ok"),
            bind_waiter=lambda _ip, _timeout: True,
            client_factory=lambda *_args, **_kwargs: _FakeClient(),
            query_fn=lambda _client, _session, on_log=None: expected,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.settings, expected)

    def test_consecutive_status_queries_release_previous_device_session(self) -> None:
        device_state = {"active_session": "", "counter": 0}

        class SessionLimitedClient(_FakeClient):
            def login(self, _username, _password):
                if device_state["active_session"]:
                    raise RuntimeError("Access denied: previous session is still active")
                device_state["counter"] += 1
                session_id = f"session-{device_state['counter']}"
                device_state["active_session"] = session_id
                return session_id

            def logout(self, session_id):
                super().logout(session_id)
                if device_state["active_session"] == session_id:
                    device_state["active_session"] = ""

        kwargs = {
            "network_prepare_fn": lambda *_args, **_kwargs: CommandResult(True, "ok"),
            "bind_waiter": lambda _ip, _timeout: True,
            "client_factory": lambda *_args, **_kwargs: SessionLimitedClient(),
            "query_fn": lambda _client, _session, on_log=None: DutTr069Settings(),
            "sleep_fn": lambda _seconds: None,
        }

        first = run_single_dut_status_query(_request(), "tr069", **kwargs)
        second = run_single_dut_status_query(_request(), "tr069", **kwargs)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(device_state["active_session"], "")
        self.assertEqual(device_state["counter"], 2)

    def test_common_settings_requires_every_target_success_and_exact_match(self) -> None:
        settings = DutVoiceSettings(line_index="1", sip_mode="IMSSIP")
        first = DutAdvancedQueryResult(
            _request("通道 12"), "voice", True, "completed", "ok", settings
        )
        second = DutAdvancedQueryResult(
            _request("通道 13"), "voice", True, "completed", "ok", settings
        )

        self.assertEqual(common_dut_status_settings((first, second)), settings)
        changed = DutAdvancedQueryResult(
            _request("通道 13"),
            "voice",
            True,
            "completed",
            "ok",
            DutVoiceSettings(line_index="1", sip_mode="SIP"),
        )
        self.assertIsNone(common_dut_status_settings((first, changed)))
        failed = DutAdvancedQueryResult(
            _request("通道 13"), "voice", False, "query", "failed"
        )
        self.assertIsNone(common_dut_status_settings((first, failed)))

    def test_batch_stop_does_not_start_later_status_queries(self) -> None:
        stop_event = threading.Event()
        started: list[str] = []

        def runner(request, feature, **_kwargs):
            started.append(request.channel)
            stop_event.set()
            return DutAdvancedQueryResult(
                request, feature, True, "completed", "ok", DutTr069Settings()
            )

        results = run_dut_status_query_batch(
            (_request("通道 12"), _request("通道 13")),
            "tr069",
            max_workers=1,
            stop_event=stop_event,
            single_runner=runner,
        )

        self.assertEqual(started, ["通道 12"])
        self.assertEqual([result.stage for result in results], ["completed", "stopped"])


if __name__ == "__main__":
    unittest.main()

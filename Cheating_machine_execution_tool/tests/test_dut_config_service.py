from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from line_check_assistant.network_ops import CommandResult
from src.core.ubus_enable_telnet import EnableTelnetResult
from src.models import DutTelnetEnableRequest, DutTelnetEnableResult
from src.services.dut_config_service import (
    MAX_DUT_PARALLEL_COUNT,
    clamp_dut_parallel_count,
    run_dut_telnet_enable_batch,
    run_single_dut_telnet_enable,
)


def _request(
    vlan: str = "vlan112", *, ubus_port: int | str = 80
) -> DutTelnetEnableRequest:
    return DutTelnetEnableRequest(
        channel=vlan.replace("vlan", "通道 "),
        vlan=vlan,
        adapter_alias=vlan,
        bind_ip="192.168.1.112",
        device_host="192.168.1.1",
        subnet_mask="255.255.255.0",
        username="telecomadmin",
        password="secret-password",
        ubus_port=ubus_port,  # type: ignore[arg-type]
    )


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class DutConfigServiceTests(unittest.TestCase):
    def test_request_repr_keeps_password_in_plaintext(self) -> None:
        rendered = repr(_request())
        self.assertIn("secret-password", rendered)
        self.assertIn("password=", rendered)

    def test_single_success_prepares_network_enables_ubus_and_probes_port(self) -> None:
        network_calls: list[tuple] = []
        clients: list[_FakeClient] = []
        probe_calls: list[tuple] = []
        logs: list[str] = []

        def prepare(*args, **kwargs):
            network_calls.append((args, kwargs))
            return CommandResult(True, "网络已准备")

        def client_factory(*_args, **_kwargs):
            client = _FakeClient()
            clients.append(client)
            return client

        def enable(_client, _username, _password, **kwargs):
            kwargs["on_log"](EnableTelnetResult(True, "tx_login", "TX UBUS session.login username=telecomadmin, password=secret-password"))
            kwargs["on_log"](EnableTelnetResult(True, "tx_get_rules", "TX UBUS bbfdm.get path=rules"))
            return EnableTelnetResult(True, "already_present", "LAN-telnet 规则已就绪")

        def probe(*args, **kwargs):
            probe_calls.append((args, kwargs))

        result = run_single_dut_telnet_enable(
            _request(),
            on_output=logs.append,
            network_prepare_fn=prepare,
            bind_waiter=lambda ip, timeout: ip == "192.168.1.112" and timeout == 15,
            client_factory=client_factory,
            enable_telnet_fn=enable,
            probe_fn=probe,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.action, "already_present")
        self.assertEqual(result.stage, "completed")
        self.assertEqual(len(network_calls), 1)
        self.assertTrue(network_calls[0][1]["reuse_if_ready"])
        self.assertEqual(probe_calls[0][0], ("192.168.1.112", "192.168.1.1"))
        self.assertEqual(probe_calls[0][1], {"device_port": 23, "timeout": 5.0})
        self.assertTrue(clients[0].closed)
        self.assertTrue(any("TX UBUS bbfdm.get" in line for line in logs))
        self.assertTrue(any("成功：Telnet 已开启并验证可用" in line for line in logs))
        self.assertTrue(any("password=secret-password" in line for line in logs))

    def test_network_failure_stops_before_ubus(self) -> None:
        client_factory = Mock()
        result = run_single_dut_telnet_enable(
            _request(),
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(False, "网卡启用失败"),
            client_factory=client_factory,
            sleep_fn=lambda _seconds: None,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.stage, "network")
        client_factory.assert_not_called()

    def test_ubus_retries_three_times_after_initial_failure_and_closes_every_client(self) -> None:
        clients: list[_FakeClient] = []
        attempts = 0
        sleeps: list[float] = []

        def client_factory(*_args, **_kwargs):
            client = _FakeClient()
            clients.append(client)
            return client

        def always_fail(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("Access denied")

        result = run_single_dut_telnet_enable(
            _request(),
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(True, "ok"),
            bind_waiter=lambda *_args: True,
            client_factory=client_factory,
            enable_telnet_fn=always_fail,
            sleep_fn=sleeps.append,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.stage, "ubus")
        self.assertEqual(attempts, 4)
        self.assertEqual(sleeps, [2.0, 2.0, 2.0])
        self.assertTrue(all(client.closed for client in clients))
        self.assertIn("退出样机 Web 管理页面", result.message)

    def test_ubus_success_but_telnet_probe_failure_is_not_reported_as_success(self) -> None:
        probe_attempts = 0

        def failed_probe(*_args, **_kwargs):
            nonlocal probe_attempts
            probe_attempts += 1
            raise RuntimeError("connection refused")

        result = run_single_dut_telnet_enable(
            _request(),
            network_prepare_fn=lambda *_args, **_kwargs: CommandResult(True, "ok"),
            bind_waiter=lambda *_args: True,
            client_factory=lambda *_args, **_kwargs: _FakeClient(),
            enable_telnet_fn=lambda *_args, **_kwargs: EnableTelnetResult(True, "added_iface", "已添加"),
            probe_fn=failed_probe,
            sleep_fn=lambda _seconds: None,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.stage, "telnet_probe")
        self.assertEqual(probe_attempts, 3)
        self.assertIn("UBUS 已成功", result.message)

    def test_invalid_same_source_and_device_ip_fails_preflight(self) -> None:
        request = DutTelnetEnableRequest(
            channel="通道 12",
            vlan="vlan112",
            adapter_alias="vlan112",
            bind_ip="192.168.1.1",
            device_host="192.168.1.1",
            subnet_mask="255.255.255.0",
            username="user",
            password="pass",
        )
        result = run_single_dut_telnet_enable(request)
        self.assertEqual(result.stage, "preflight")
        self.assertIn("相同", result.message)

    def test_invalid_ubus_port_is_reported_as_preflight_error(self) -> None:
        request = _request(ubus_port="not-a-port")

        result = run_single_dut_telnet_enable(request)

        self.assertEqual(result.stage, "preflight")
        self.assertIn("UBUS 端口格式无效", result.message)

    def test_parallel_count_clamps_to_one_through_eight(self) -> None:
        self.assertEqual(clamp_dut_parallel_count(0), 1)
        self.assertEqual(clamp_dut_parallel_count("bad"), 1)
        self.assertEqual(clamp_dut_parallel_count(4), 4)
        self.assertEqual(clamp_dut_parallel_count(99), MAX_DUT_PARALLEL_COUNT)

    def test_batch_keeps_order_and_isolates_single_failure(self) -> None:
        requests = [_request("vlan112"), _request("vlan113")]

        def runner(request, **_kwargs):
            return DutTelnetEnableResult(
                request,
                request.vlan != "vlan112",
                "completed" if request.vlan != "vlan112" else "ubus",
                "done",
            )

        results = run_dut_telnet_enable_batch(requests, max_workers=2, single_runner=runner)

        self.assertEqual([item.request.vlan for item in results], ["vlan112", "vlan113"])
        self.assertEqual([item.ok for item in results], [False, True])

    def test_batch_stop_does_not_start_later_requests(self) -> None:
        stop_event = threading.Event()
        requests = [_request("vlan112"), _request("vlan113"), _request("vlan114")]
        started: list[str] = []

        def runner(request, **_kwargs):
            started.append(request.vlan)
            stop_event.set()
            return DutTelnetEnableResult(request, True, "completed", "done")

        results = run_dut_telnet_enable_batch(
            requests,
            max_workers=1,
            stop_event=stop_event,
            single_runner=runner,
        )

        self.assertEqual(started, ["vlan112"])
        self.assertEqual([item.stage for item in results], ["completed", "stopped", "stopped"])


if __name__ == "__main__":
    unittest.main()

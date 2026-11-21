"""Original DUT batches/single services with only physical boundaries replaced."""
from types import SimpleNamespace
import threading

from line_check_assistant.network_ops import CommandResult
from src.core.ubus_enable_telnet import EnableTelnetResult
from src.models.dut_config_models import DutTelnetStatus, DutTelnetEnableResult
from src.services.dut_config_service import run_dut_telnet_enable_batch, run_single_dut_telnet_enable
from src.services.dut_status_query_service import run_dut_status_query_batch, run_single_dut_status_query


class DutHarness:
    def __init__(self):
        self.calls = []
        self.network_calls = []
        self.workers = []
        self.started = threading.Event()
        self.stop_seen = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.failure = False

    def _prepare(self, *args, **kwargs):
        self.network_calls.append((args, kwargs))
        return CommandResult(not self.failure, 'fake network failure' if self.failure else 'fake network ready')

    def _wait(self, request, stop):
        self.calls.append(request)
        self.started.set()
        while not self.release.wait(.01):
            if stop.is_set():
                self.stop_seen.set()

    def enable(self, request, *, stop_event, on_output):
        self._wait(request, stop_event)
        def enable(*args, **kwargs):
            kwargs['on_log'](EnableTelnetResult(True, 'tx_login', 'TX UBUS password=' + request.password))
            return EnableTelnetResult(True, 'already_present', 'fake rule ready')
        return run_single_dut_telnet_enable(request, stop_event=stop_event, on_output=on_output,
            network_prepare_fn=self._prepare, bind_waiter=lambda *a: True,
            client_factory=lambda *a, **kw: SimpleNamespace(close=lambda: None), enable_telnet_fn=enable,
            probe_fn=lambda *a, **kw: None, sleep_fn=lambda seconds: None)

    def query(self, request, feature, **kwargs):
        self._wait(request, kwargs['stop_event'])
        client = SimpleNamespace(close=lambda: None, login=lambda *a, **kw: 'fixture-session', logout=lambda *a: None)
        return run_single_dut_status_query(request, feature, **kwargs,
            network_prepare_fn=self._prepare, bind_waiter=lambda *a: True,
            client_factory=lambda *a, **kw: client,
            query_fn=lambda *a, **kw: DutTelnetStatus(True, True, True, ('LAN',), True, 'fake probe'),
            sleep_fn=lambda seconds: None)

    def enable_batch(self, requests, **kwargs):
        self.workers.append(kwargs['max_workers'])
        return run_dut_telnet_enable_batch(requests, single_runner=self.enable, **kwargs)

    def query_batch(self, requests, feature, **kwargs):
        self.workers.append(kwargs['max_workers'])
        return run_dut_status_query_batch(requests, feature, single_runner=self.query, **kwargs)


class WanHarness(DutHarness):
    def __init__(self):
        super().__init__()
        self.operations = []
        self.different = False
        self.clients = []

    def client(self, *args, **kwargs):
        def operate(session, command, payload, optional):
            self.operations.append((command, payload))
            return [0, {'results': [{'output': [{'Result': 'OK'}]}]}]
        client = SimpleNamespace(close=lambda: None, login=lambda *a: 'fixture-session',
            logout=lambda *a: None, bbfdm_operate=operate)
        self.clients.append(client)
        return client

    def wan_query(self, request, **kwargs):
        from src.models.dut_config_models import DutWanConnectionInfo
        from src.services.dut_wan_query_service import run_single_dut_wan_query
        self._wait(request, kwargs['stop_event'])
        def query(*args, **kw):
            return (DutWanConnectionInfo('1_INTERNET', '1', mode='router', service_type='INTERNET',
                vlan_id='201' if self.different and request.channel.endswith('7') else '200', vlan_priority='0',
                port_bind='265', mtu='1492', nat_enabled=True, access_type='PPPoE', ip_protocol='IPv4IPv6',
                ipv4_type='Dynamic', ipv6_type='DHCPv6', pppoe_username='fixture-ppp-user',
                pppoe_password='fixture-ppp-private'),)
        return run_single_dut_wan_query(request, **kwargs, network_prepare_fn=self._prepare,
            bind_waiter=lambda *a: True, client_factory=self.client, query_fn=query, sleep_fn=lambda t: None)

    def wan_query_batch(self, requests, **kwargs):
        from src.services.dut_wan_query_service import run_dut_wan_query_batch
        self.workers.append(kwargs['max_workers'])
        return run_dut_wan_query_batch(requests, single_runner=self.wan_query, **kwargs)

    def wan_configure(self, request, **kwargs):
        from src.services.dut_advanced_config_service import run_single_dut_advanced_config
        self._wait(request, kwargs['stop_event'])
        return run_single_dut_advanced_config(request, **kwargs, network_prepare_fn=self._prepare,
            bind_waiter=lambda *a: True, client_factory=self.client, sleep_fn=lambda t: None)

    def wan_configure_batch(self, requests, **kwargs):
        from src.services.dut_advanced_config_service import run_dut_advanced_config_batch
        self.workers.append(kwargs['max_workers'])
        return run_dut_advanced_config_batch(requests, single_runner=self.wan_configure, **kwargs)

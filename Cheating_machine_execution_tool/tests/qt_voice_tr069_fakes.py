"""Replace only physical network, UBUS and waiting in the original DUT services."""
import threading

from qt_dut_fakes import DutHarness
from test_dut_ubus_config import _FakeClient
from src.core.dut_ubus_config import INFORM_RESULT_PATH, MANAGEMENT_SERVER_PATH, MANUAL_INFORM_STAGE_PATH
from src.services.dut_advanced_config_service import run_dut_advanced_config_batch, run_single_dut_advanced_config
from src.services.dut_status_query_service import run_dut_status_query_batch, run_single_dut_status_query


class ManagementClient(_FakeClient):
    def __init__(self, harness):
        super().__init__()
        self.harness = harness
        self.management_values = dict(harness.reported_fields)
        self.closed = False

    def login(self, *_):
        return 'fixture-session'

    def logout(self, *_):
        pass

    def close(self):
        self.closed = True

    def bbfdm_get(self, session, path, optional=None):
        if path == MANAGEMENT_SERVER_PATH:
            return super().bbfdm_get(session, path, optional)
        self.calls.append(('get', session, path, optional))
        if path == MANUAL_INFORM_STAGE_PATH:
            stage = '1_wait_inform' if not self.harness.release_inform.is_set() else '3_finish_inform'
            return [0, {'X_SDMC_ManualInformStage': stage}]
        if path == INFORM_RESULT_PATH:
            return [0, {'X_SDMC_InformResult': self.harness.inform_result}]
        if path.endswith('VoIPProfile.1.'):
            return [0, {'DTMFMethod': 'SIPINFO', 'DTMFMethodSupported': 'SIPINFO'}]
        if path.endswith('SIP.Network.1.'):
            return [0, {'ProxyServer': '192.0.2.60', 'RegistrarServer': '192.0.2.61', 'ProxyServerPort': 5060,
                        'OutboundProxyPort': 5060, 'RegistrarServerPort': 5060, 'RegisterExpires': 3600}]
        if path.endswith('SIP.'):
            return [0, {'X_SDMC_SIPMode': 'IMSSIP', 'X_SDMC_SIPModeSupported': 'IMSSIP'}]
        if path.endswith('Capabilities.Codecs.'):
            return [0, {'Codecs': [{'Codec': 'G.729'}]}]
        if '.SIP.Client.' in path and '.X_SDMC_Codec.' not in path:
            return [0, {'Enable': '1', 'RegisterURI': '1002', 'AuthUserName': 'fixture-voice',
                        'X_SDMC_AuthPassword': 'fixture-quoted-voice"\\secret'}]
        if '.X_SDMC_Codec.' in path:
            return [0, {'Codec': 'G.729'}]
        return [0, {}]


class ManagementHarness(DutHarness):
    def __init__(self):
        super().__init__()
        self.clients = []
        self.reported_fields = {'URL': 'http://acs.example.test/acs', 'Password': 'fixture-acs-query-private',
                                'ConnectionRequestPassword': 'fixture-request-query-private'}
        self.release_inform = threading.Event()
        self.release_inform.set()
        self.inform_waiting = threading.Event()
        self.inform_result = '10_success'

    def client(self, *_args, **_kwargs):
        client = ManagementClient(self)
        self.clients.append(client)
        return client

    def pause(self, seconds, stop):
        if seconds == 1 and not self.release_inform.is_set():
            self.inform_waiting.set()
            while not self.release_inform.wait(.01):
                if stop.is_set():
                    self.stop_seen.set()

    def query(self, request, feature, **kwargs):
        self._wait(request, kwargs['stop_event'])
        return run_single_dut_status_query(request, feature, **kwargs, network_prepare_fn=self._prepare,
                                           bind_waiter=lambda *_: True, client_factory=self.client,
                                           sleep_fn=lambda _: None)

    def query_batch(self, requests, feature, **kwargs):
        return run_dut_status_query_batch(requests, feature, single_runner=self.query, **kwargs)

    def configure(self, request, **kwargs):
        self._wait(request, kwargs['stop_event'])
        return run_single_dut_advanced_config(request, **kwargs, network_prepare_fn=self._prepare,
                                             bind_waiter=lambda *_: True, client_factory=self.client,
                                             sleep_fn=lambda seconds: self.pause(seconds, kwargs['stop_event']))

    def configure_batch(self, requests, **kwargs):
        return run_dut_advanced_config_batch(requests, single_runner=self.configure, **kwargs)

"""正式无线路径使用模拟接口；覆盖身份、频段、取消、配置保护及FIFO接入。"""
from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.core.wifi_target_reader import read_wifi_snapshot
from src.core.windows_wifi import (security_pairs, choose_security, profile_xml, BssEntry,
                                   ConnectionAttributes, BssidList, NativeWifiBackend, ConnectionParameters)
from src.models.wifi_test_models import (
    WifiBandTarget, WifiSnapshot, WifiObservation, WifiConnection, WifiInterface,
    WifiTestOptions, WirelessPingResult, WifiEnvironmentError, WifiCancelled, WifiVerificationError,
)
from src.services.wifi_connection_service import WifiConnectionService, validate_wifi_options
from src.services.power_test_wifi_service import PowerTestWifiScheduler


TARGETS = (WifiBandTarget('2.4G', 'same-name', '02:00:00:00:00:01', 'private-key', 'WPA2-Personal'),
           WifiBandTarget('5G', 'same-name', '02:00:00:00:00:02', 'private-key', 'WPA2-Personal'))
OBS = tuple(WifiObservation(t.ssid, t.bssid, f, ((7, 4),)) for t, f in zip(TARGETS, (2412000, 5180000)))


class VirtualEvent:
    def __init__(self):
        self.now = 0.0
        self.stopped = False
        self.waits = []
        self.on_wait = None

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds
        if self.on_wait:
            self.on_wait()
        return self.stopped


class FakeBackend:
    def __init__(self):
        self.interface = WifiInterface('interface-guid', 'Wi-Fi', 7)
        self.connections = []
        self.disconnects = 0
        self.scans = 0
        self.target = None
        self.pair = (7, 4)
        self.override = None
        self.scan_callback = None
        self.obs = OBS

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def select_interface(self, card):
        if card and card != 'Wi-Fi':
            raise WifiEnvironmentError('指定无线网卡不存在')
        return self.interface

    def supported_pairs(self, _interface):
        return ((7, 4),)

    def start_scan(self, _interface):
        self.scans += 1
        if self.scan_callback:
            self.scan_callback()

    def scan_ready(self):
        return True

    def observations(self, _interface):
        return self.obs

    def current(self, _interface):
        if self.override:
            return self.override
        return None if self.target is None else WifiConnection(self.target.ssid, self.target.bssid, *self.pair)

    def connect(self, _interface, target, pair):
        self.target, self.pair = target, pair
        self.connections.append(target.band)

    def disconnect(self, _interface):
        self.disconnects += 1
        self.target = None


class ConnectionServiceTests(unittest.TestCase):
    def setUp(self):
        self.event = VirtualEvent()
        self.backend = FakeBackend()
        self.logs = []
        self.ping = Mock(return_value=WirelessPingResult('192.0.2.1', 4, (1.0,)))
        self.service = WifiConnectionService(lambda: self.backend, self.ping, lambda: self.event.now)

    def run_service(self, options=WifiTestOptions(), **changes):
        args = dict(snapshot=WifiSnapshot(TARGETS, True), options=options, card='Wi-Fi',
                    test_2g=True, test_5g=True, auth='WPA2-PSK', cipher='AES',
                    stop=self.event, emit=self.logs.append)
        args.update(changes)
        return self.service.run(**args)

    def test_same_ssid_requires_both_actual_bssids_and_pings_each_band(self):
        result = self.run_service(WifiTestOptions(wireless_ping_enable=True, wireless_ping_target='192.0.2.1'))
        self.assertEqual(result, ('success', ''))
        self.assertEqual(self.backend.connections, ['2.4G', '5G'])
        self.assertEqual(self.backend.disconnects, 2)
        self.assertEqual(self.ping.call_count, 2)
        self.assertGreaterEqual(self.event.now, 4)
        self.assertNotIn('private-key', '\n'.join(self.logs))

    def test_unified_mode_runs_once_even_when_saved_band_flags_off(self):
        self.assertEqual(self.run_service(WifiTestOptions('unified'), test_2g=False, test_5g=False), ('success', ''))
        self.assertEqual(len(self.backend.connections), 1)
        self.ping.assert_not_called()

    def test_per_band_skips_unselected_target(self):
        self.assertEqual(self.run_service(test_2g=False), ('success', ''))
        self.assertEqual(self.backend.connections, ['5G'])

    def test_other_dut_with_same_ssid_never_passes_and_keeps_retry_budget(self):
        self.backend.override = WifiConnection('same-name', '02:00:00:00:ff:01', 7, 4)
        self.assertEqual(self.run_service(test_5g=False)[0], 'failed')
        self.assertEqual(self.backend.connections, ['2.4G'] * 4)
        self.assertEqual(self.backend.disconnects, 4)
        self.assertGreaterEqual(self.event.now, 110)
        self.ping.assert_not_called()

    def test_wrong_band_during_ping_overrides_prior_reply_without_reconnection(self):
        def ping(*args):
            self.backend.override = WifiConnection(TARGETS[1].ssid, TARGETS[1].bssid, 7, 4)
            args[-1]()
        self.ping.side_effect = ping
        self.assertEqual(self.run_service(WifiTestOptions(wireless_ping_enable=True))[0], 'failed')
        self.assertEqual(self.backend.connections, ['2.4G'])
        self.assertEqual(self.backend.disconnects, 1)

    def test_ping_failure_does_not_reconnect_or_start_second_band(self):
        self.ping.return_value = WirelessPingResult('192.0.2.1', 4, ())
        result = self.run_service(WifiTestOptions(wireless_ping_enable=True))
        self.assertEqual(result[0], 'failed')
        self.assertIn('无线Ping', result[1])
        self.assertEqual(self.backend.connections, ['2.4G'])
        self.assertEqual(self.ping.call_count, 1)

    def test_cancel_during_stability_cleans_connection_and_skips_ping(self):
        self.event.on_wait = self.event.set
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.disconnects, 1)
        self.ping.assert_not_called()

    def test_cancel_during_scan_does_not_submit_connection(self):
        self.backend.scan_callback = self.event.set
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.connections, [])

    def test_actual_auth_mismatch_never_passes(self):
        self.backend.override = WifiConnection('same-name', TARGETS[0].bssid, 4, 2)
        self.assertEqual(self.run_service(test_5g=False)[0], 'failed')

    def test_manual_unsupported_mode_is_environment_error(self):
        self.assertEqual(self.run_service(WifiTestOptions(security_source='manual'), auth='WPA3-PSK')[0], 'error')
        self.assertEqual(self.backend.connections, [])

    def test_cleanup_failure_cannot_return_success(self):
        self.backend.disconnect = Mock(side_effect=RuntimeError('private-key'))
        self.assertEqual(self.run_service()[0], 'error')
        self.assertNotIn('private-key', '\n'.join(self.logs))

    def test_native_scheduler_keeps_reservation_across_ping(self):
        stop = threading.Event()
        scheduler = PowerTestWifiScheduler(options=WifiTestOptions('unified'), connection_service=self.service)
        def during_ping(*args):
            self.assertEqual(scheduler._owner, '通道2 第1轮')
            return WirelessPingResult('192.0.2.1', 4, (1,))
        self.service.ping = during_ping
        scheduler.options = WifiTestOptions('unified', wireless_ping_enable=True)
        result = scheduler.test_bands(channel=2, cycle=1, card='', stop_event=self.event, emit=self.logs.append,
                                      connector=None, wifi_info=WifiSnapshot(TARGETS), test_2g=False, test_5g=False,
                                      auth='WPA2-PSK', cipher='AES')
        self.assertEqual(result[0], 'success')
        self.assertIsNone(scheduler._owner)

    def test_invalid_options_and_disabled_ping_target(self):
        for options in (WifiTestOptions('invalid'), WifiTestOptions(security_source='invalid'),
                        WifiTestOptions(wireless_ping_enable=True)):
            with self.assertRaises(ValueError):
                validate_wifi_options(options)
        validate_wifi_options(WifiTestOptions(wireless_ping_target='http://unused'))
        validate_wifi_options(WifiTestOptions(wireless_ping_enable=True), enabled=False, solution='bcm')

    def test_master_off_ignores_all_wireless_only_validation(self):
        validate_wifi_options(WifiTestOptions('invalid', 'invalid', True, 'http://unused'),
                              enabled=False, solution='bcm')


class TargetReaderTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.logs = []
        self.values = {'X_SDMC_DualBandEnable': '1', 'X_SDMC_Mapping_2G': '1,1,1', 'X_SDMC_Mapping_5G': '2,2,2'}
        for node, ids in (('Radio', (31, 32)), ('AccessPoint', (21, 22)), ('SSID', (11, 12))):
            self.values[node + '.'] = '\n'.join(f'Device.WiFi.{node}.{i}.X_SDMC_Instance => {i}' for i in ids)
        for target, ssid_index, ap in zip(TARGETS, (11, 12), (21, 22)):
            self.values[f'SSID.{ssid_index}.SSID'] = target.ssid
            self.values[f'SSID.{ssid_index}.Enable'] = '1'
            self.values[f'SSID.{ssid_index}.BSSID'] = target.bssid
            self.values[f'AccessPoint.{ap}.Security.ModeEnabled'] = target.security
            self.values[f'AccessPoint.{ap}.Security.X_SDMC_Key'] = target.password
        self.client = Mock()
        self.client.execute_read_until.side_effect = self.reply

    def reply(self, command, **_kwargs):
        key = command.split('Device.WiFi.')[1]
        value = self.values.get(key)
        if value is None:
            return 'fault'
        return value if key.endswith('.') else 'Device.WiFi.' + key + ' => "' + value + '"'

    def read(self, **kwargs):
        return read_wifi_snapshot(self.client, self.stop, self.logs.append, **kwargs)

    def test_mapping_uses_real_instances_and_returns_bssids_without_password_logs(self):
        result = self.read()
        self.assertEqual(result.targets, TARGETS)
        self.assertTrue(result.dual_band_enabled)
        self.assertEqual(result[1], 'private-key')
        self.assertNotIn('private-key', repr(result))
        self.assertNotIn('private-key', '\n'.join(self.logs))
        for call in self.client.execute_read_until.call_args_list:
            self.assertIn('bbfdmd -c get ', call.args[0])
            self.assertTrue(call.kwargs['sensitive'])

    def test_single_band_does_not_read_unselected_band(self):
        self.read(bands=('5G',))
        self.assertFalse(any('Mapping_2G' in c.args[0] for c in self.client.execute_read_until.call_args_list))

    def test_missing_mapping_is_not_replaced_by_fixed_indices(self):
        del self.values['X_SDMC_Mapping_2G']
        with self.assertRaises(WifiEnvironmentError):
            self.read()

    def test_unified_can_use_one_confirmed_band_but_missing_both_is_error(self):
        del self.values['SSID.11.BSSID']
        self.assertEqual(self.read(allow_partial=True).targets, (TARGETS[1],))
        del self.values['SSID.12.BSSID']
        with self.assertRaises(WifiEnvironmentError):
            self.read(allow_partial=True)

    def test_same_ssid_does_not_infer_dual_band_flag(self):
        del self.values['X_SDMC_DualBandEnable']
        self.assertIsNone(self.read().dual_band_enabled)

    def test_stop_prevents_readonly_commands(self):
        self.stop.set()
        with self.assertRaises(WifiCancelled):
            self.read()
        self.client.execute_read_until.assert_not_called()


class SecurityTests(unittest.TestCase):
    def test_native_connection_is_temporary_bssid_scoped_and_never_saves_profiles(self):
        import ctypes as C
        from types import SimpleNamespace
        backend = NativeWifiBackend.__new__(NativeWifiBackend)
        backend.handle = 1
        captured = {}
        def connect(_handle, _guid, pointer, _reserved):
            params = C.cast(pointer, C.POINTER(ConnectionParameters)).contents
            captured['mode'] = params.mode
            captured['xml'] = params.profile
            captured['bssid'] = bytes(params.bssids.contents.addresses[0])
            return 0
        backend.api = SimpleNamespace(WlanConnect=connect, WlanDisconnect=Mock(return_value=0))
        interface = WifiInterface('00000000-0000-0000-0000-000000000007', 'Wi-Fi', 7)
        name = backend.connect(interface, TARGETS[0], (7, 4))
        self.assertEqual(captured['mode'], 1)
        self.assertTrue(name.startswith('LineCheck-WiFi-'))
        self.assertEqual(captured['bssid'], bytes.fromhex(TARGETS[0].bssid.replace(':', '')))
        backend.disconnect(interface)
        backend.api.WlanDisconnect.assert_called_once()

    def test_rsn_and_wpa_ie_parse_and_truncated_or_wep_not_guessed(self):
        rsn = bytes.fromhex('0100000fac040100000fac040200000fac02000fac08')
        self.assertEqual(security_pairs(bytes([48, len(rsn)]) + rsn, True), ((7, 4), (9, 4)))
        wpa = bytes.fromhex('0050f20101000050f20201000050f20201000050f202')
        self.assertEqual(security_pairs(bytes([221, len(wpa)]) + wpa, True), ((4, 2),))
        self.assertEqual(security_pairs(b'\x30\xffabc', True), ())
        self.assertEqual(security_pairs(b'', True), ())
        self.assertEqual(security_pairs(b'', False), ((1, 0),))

    def test_auto_prefers_supported_sae_and_manual_mixed_string_works(self):
        observation = replace(OBS[0], pairs=((7, 4), (9, 4)))
        self.assertEqual(choose_security(observation, observation.pairs), (9, 4))
        self.assertEqual(choose_security(observation, ((7, 4),)), (7, 4))
        self.assertEqual(choose_security(observation, observation.pairs, 'manual', 'WPA-PSK/WPA2-PSK'), (7, 4))
        with self.assertRaises(WifiEnvironmentError):
            choose_security(observation, ((7, 4),), 'manual', 'WPA3-PSK')

    def test_profile_escapes_credentials_and_keeps_manual_connection(self):
        target = replace(TARGETS[0], password='private<&key')
        xml = profile_xml('unique', target, (7, 4))
        self.assertIn('private&lt;&amp;key', xml)
        self.assertIn('<connectionMode>manual</connectionMode>', xml)
        self.assertIn(target.ssid.encode().hex(), xml)
        self.assertNotIn('sharedKey', profile_xml('open', replace(target, password=''), (1, 0)))

    def test_native_windows_structure_abi(self):
        import os
        import ctypes as C
        if os.name == 'nt':
            self.assertEqual(C.sizeof(BssEntry), 360)
            self.assertEqual(C.sizeof(ConnectionAttributes), 604)
            self.assertEqual(C.sizeof(BssidList), 20)


if __name__ == '__main__':
    unittest.main()

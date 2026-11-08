"""正式无线路径使用模拟接口；覆盖身份、频段、取消、配置保护及FIFO接入。"""
from dataclasses import replace
from pathlib import Path
import struct
import ctypes as C
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.core.wifi_target_reader import read_wifi_snapshot
from src.core.windows_wifi import (security_pairs, choose_security, profile_xml, BssEntry,
                                   ConnectionAttributes, BssidList, NativeWifiBackend, ConnectionParameters,
                                   Notification, Guid, U32)
from src.models.wifi_test_models import (
    WifiBandTarget, WifiSnapshot, WifiObservation, WifiConnection, WifiInterface,
    WifiTestOptions, WirelessPingResult, WifiEnvironmentError, WifiScanError, WifiCancelled, WifiVerificationError,
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

    def end_scan(self):
        pass

    def interface_state(self, _interface):
        return 4 if self.target is None else 1

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
        self.assertFalse(any('成功：本项无线测试通过' in text for text in self.logs))

    def test_second_band_scanning_waits_for_confirmed_stable_disconnect(self):
        disconnected_at = []
        def disconnect(_):
            self.backend.disconnects += 1
            self.backend.target = None
            disconnected_at.append(self.event.now)
        self.backend.disconnect = disconnect
        self.backend.interface_state = lambda _: 3 if self.event.now - disconnected_at[-1] < 1 else 4
        def scan():
            if disconnected_at:
                self.assertGreaterEqual(self.event.now - disconnected_at[-1], 1.5)
        self.backend.scan_callback = scan
        self.assertEqual(self.run_service(), ('success', ''))
        self.assertEqual(self.backend.scans, 2)
        clean = [i for i, text in enumerate(self.logs) if text.endswith('临时连接已清理')]
        success = [i for i, text in enumerate(self.logs) if text.endswith('成功：本项无线测试通过')]
        self.assertTrue(all(c < s for c, s in zip(clean, success)))

    def test_disconnect_state_must_remain_stable_and_not_just_be_empty_current(self):
        states = iter((4, 4, 3, 4, 4, 4, 4))
        self.backend.interface_state = lambda _: next(states, 4)
        self.service._wait_disconnected(self.backend, self.backend.interface, self.event)
        self.assertGreaterEqual(self.event.now, 1.0)

    def test_disconnect_timeout_stops_channel_without_more_scans_or_false_success(self):
        self.backend.interface_state = lambda _: 3
        result = self.run_service()
        self.assertEqual(result[0], 'error')
        self.assertIn('临时连接断开未确认', result[1])
        self.assertEqual(self.backend.disconnects, 1)
        self.assertEqual(self.backend.scans, 1)
        self.assertFalse(any('成功：本项无线测试通过' in text for text in self.logs))
        self.assertLessEqual(self.event.now, 7.3)  # 稳定核验约2秒，清理最多5秒。

    def test_interface_state_error_keeps_actual_reason_without_retrying_disconnect(self):
        self.backend.interface_state = Mock(side_effect=WifiEnvironmentError('读取状态失败（Windows错误码5）'))
        result = self.run_service()
        self.assertIn('Windows错误码5', result[1])
        self.assertIn('临时连接断开未确认', result[1])
        self.assertEqual(self.backend.disconnects, 1)

    def test_cancel_during_disconnect_wait_keeps_cleanup_but_starts_nothing_else(self):
        def state(_):
            self.event.set()
            return 3
        self.backend.interface_state = state
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.disconnects, 1)
        self.assertEqual(self.backend.scans, 1)
        self.assertFalse(any('成功：本项无线测试通过' in text for text in self.logs))

    def test_scan_failure_retries_in_existing_attempt_budget_then_recovers(self):
        def scan():
            if self.backend.scans == 1:
                raise WifiScanError('异步通知', 0x10009, retryable=True, reason='扫描调用失败')
        self.backend.scan_callback = scan
        self.assertEqual(self.run_service(test_2g=False), ('success', ''))
        self.assertEqual(self.backend.scans, 2)
        self.assertEqual(self.backend.connections, ['5G'])
        errors = [text for text in self.logs if '次扫描失败' in text]
        self.assertEqual(len(errors), 1)
        self.assertIn('第1/4次扫描失败', errors[0])
        self.assertIn('0x00010009', errors[0])
        self.assertIn('10秒后重试', errors[0])
        self.assertGreaterEqual(self.event.now, 12.5)

    def test_four_scan_failures_are_environment_error_and_never_connect(self):
        self.backend.scan_callback = Mock(side_effect=WifiScanError('异步通知', retryable=True))
        result = self.run_service()
        self.assertEqual(result[0], 'error')
        self.assertIn('第4/4次扫描失败', result[1])
        self.assertIn('次数已用尽', result[1])
        self.assertEqual(self.backend.scans, 4)
        self.assertEqual(self.backend.connections, [])
        self.assertEqual(self.backend.disconnects, 0)
        self.assertAlmostEqual(self.event.now, 30)

    def test_scan_timeout_uses_twenty_seconds_per_attempt_and_only_four_attempts(self):
        self.backend.scan_ready = lambda: False
        self.backend.end_scan = Mock()
        result = self.run_service(test_5g=False)
        self.assertEqual(result[0], 'error')
        self.assertIn('扫描超时', result[1])
        self.assertEqual(self.backend.scans, 4)
        self.assertEqual(self.backend.end_scan.call_count, 4)
        self.assertEqual(self.backend.connections, [])
        self.assertAlmostEqual(self.event.now, 110)

    def test_permanent_scan_error_exits_without_retry_or_connect(self):
        self.backend.scan_callback = Mock(side_effect=WifiScanError('API返回', 5, reason='拒绝访问'))
        result = self.run_service()
        self.assertEqual(result[0], 'error')
        self.assertIn('第1/4次扫描失败', result[1])
        self.assertIn('立即结束', result[1])
        self.assertEqual(self.backend.scans, 1)
        self.assertEqual(self.event.now, 0)

    def test_cancel_during_scan_wait_stops_notifications_without_connecting(self):
        self.backend.scan_ready = lambda: False
        self.backend.end_scan = Mock()
        self.event.on_wait = self.event.set
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.scans, 1)
        self.backend.end_scan.assert_called_once()
        self.assertEqual(self.backend.connections, [])

    def test_cancel_during_scan_retry_interval_does_not_start_next_attempt(self):
        self.backend.scan_callback = Mock(side_effect=WifiScanError('异步通知', retryable=True))
        self.event.on_wait = self.event.set
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.scans, 1)
        self.assertEqual(self.backend.connections, [])

    def test_stop_wins_over_scan_error_or_state_query_error(self):
        def scan():
            self.event.set()
            raise WifiScanError('API返回', 5)
        self.backend.scan_callback = scan
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertFalse(any('次扫描失败' in text for text in self.logs))
        self.event.stopped = False
        self.backend.scan_callback = None
        def state(_):
            self.event.set()
            raise WifiEnvironmentError('读取状态失败')
        self.backend.interface_state = state
        self.assertEqual(self.run_service()[0], 'cancelled')
        self.assertEqual(self.backend.connections, ['2.4G'])

    def test_resume_after_scan_error_starts_fresh_attempts(self):
        self.backend.scan_callback = Mock(side_effect=WifiScanError('异步通知', retryable=True))
        self.assertEqual(self.run_service()[0], 'error')
        self.backend.scan_callback = None
        self.logs.clear()
        self.assertEqual(self.run_service(test_2g=False), ('success', ''))
        self.assertIn('频段=5G 第 1/4 次连接', self.logs[1])

    def test_fifo_reservation_covers_disconnect_confirmation(self):
        scheduler = PowerTestWifiScheduler(options=WifiTestOptions('unified'), connection_service=self.service)
        def state(_):
            self.assertEqual(scheduler._owner, '通道2 第1轮')
            return 4
        self.backend.interface_state = state
        result = scheduler.test_bands(channel=2, cycle=1, card='', stop_event=self.event,
                                      emit=self.logs.append, connector=None, wifi_info=WifiSnapshot(TARGETS),
                                      test_2g=False, test_5g=False, auth='WPA2-PSK', cipher='AES')
        self.assertEqual(result[0], 'success')
        self.assertIsNone(scheduler._owner)

    def test_scan_near_deadline_cannot_submit_connection_after_budget(self):
        def observations(_):
            self.event.now += 21
            return OBS
        self.backend.observations = observations
        self.assertEqual(self.run_service()[0], 'failed')
        self.assertEqual(self.backend.scans, 4)
        self.assertEqual(self.backend.connections, [])

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


class NativeScanTests(unittest.TestCase):
    """直接驱动真实通知处理和ctypes解析，所有Windows API均为假对象。"""
    def setUp(self):
        from types import SimpleNamespace
        self.interface = WifiInterface('00000000-0000-0000-0000-000000000007', 'Wi-Fi', 7)
        self.backend = NativeWifiBackend.__new__(NativeWifiBackend)
        self.backend.handle = 1
        self.backend._scan_event = threading.Event()
        self.backend._scan_lock = threading.Lock()
        self.backend._scan_guid = None
        self.backend._scan_active = False
        self.backend._scan_failed = False
        self.backend._scan_reason = None
        self.backend.api = SimpleNamespace(WlanScan=Mock(return_value=0),
                                           WlanReasonCodeToString=Mock(return_value=87),
                                           WlanFreeMemory=Mock())

    def notify(self, code, reason=None, *, size=None, guid=None, source=8):
        value = U32(reason) if reason is not None else None
        note = Notification(source, code, Guid.parse(guid or self.interface.guid),
                            (C.sizeof(U32) if value is not None else 0) if size is None else size,
                            C.addressof(value) if value is not None else None)
        self.backend._on_notification(C.pointer(note), None)
        return value

    def test_failure_reason_is_copied_in_callback_and_decoded_only_in_worker(self):
        self.backend.start_scan(self.interface)
        value = self.notify(8, 0x10009)
        self.backend.api.WlanReasonCodeToString.assert_not_called()
        value.value = 123  # 原通知内存变化不能影响已经复制的原因码。
        def decode(code, size, buffer, reserved):
            self.assertEqual(code, 0x10009)
            buffer.value = '驱动扫描调用失败'
            return 0
        self.backend.api.WlanReasonCodeToString.side_effect = decode
        with self.assertRaises(WifiScanError) as caught:
            self.backend.scan_ready()
        error = caught.exception
        self.assertEqual((error.source, error.reason_code, error.retryable), ('异步通知', 0x10009, True))
        self.assertIn('驱动扫描调用失败', str(error))
        self.assertIn('0x00010009', str(error))

    def test_unknown_missing_and_short_reason_data_still_report_scan_failure(self):
        for reason, size in ((None, 0), (0x10009, 2)):
            with self.subTest(reason=reason, size=size):
                self.backend.start_scan(self.interface)
                self.notify(8, reason, size=size)
                with self.assertRaises(WifiScanError) as caught:
                    self.backend.scan_ready()
                self.assertIsNone(caught.exception.reason_code)
                self.assertTrue(caught.exception.retryable)
                self.assertIn('未提供', str(caught.exception))
        self.backend.api.WlanReasonCodeToString.assert_not_called()

    def test_reason_translation_error_retains_numeric_code(self):
        for failure in (87, OSError('RPC failure')):
            with self.subTest(failure=failure):
                self.backend.start_scan(self.interface)
                self.notify(8, 0x12345678)
                self.backend.api.WlanReasonCodeToString.side_effect = None
                if isinstance(failure, Exception):
                    self.backend.api.WlanReasonCodeToString.side_effect = failure
                else:
                    self.backend.api.WlanReasonCodeToString.return_value = failure
                with self.assertRaises(WifiScanError) as caught:
                    self.backend.scan_ready()
                self.assertEqual(caught.exception.reason_code, 0x12345678)
                self.assertIn('0x12345678', str(caught.exception))
                self.assertIn('转换失败', str(caught.exception))

    def test_ignores_non_target_source_guid_and_inactive_notifications(self):
        self.notify(8, 123)
        self.assertFalse(self.backend.scan_ready())
        self.backend.start_scan(self.interface)
        self.notify(8, 123, guid='00000000-0000-0000-0000-000000000008')
        self.notify(8, 123, source=16)
        self.notify(9, 123)
        self.assertFalse(self.backend.scan_ready())
        self.backend.end_scan()
        self.notify(8, 123)
        self.assertFalse(self.backend.scan_ready())

    def test_first_terminal_result_wins_and_next_scan_clears_old_failure(self):
        self.backend.start_scan(self.interface)
        self.notify(7)
        self.notify(8, 123)
        self.assertTrue(self.backend.scan_ready())
        self.backend.start_scan(self.interface)
        self.notify(8, 456)
        self.notify(7)
        with self.assertRaises(WifiScanError) as caught:
            self.backend.scan_ready()
        self.assertEqual(caught.exception.reason_code, 456)
        self.backend.start_scan(self.interface)
        self.assertFalse(self.backend.scan_ready())
        self.notify(7)
        self.assertTrue(self.backend.scan_ready())

    def test_api_return_classification_does_not_retry_permanent_or_unknown_errors(self):
        for code, retryable in ((21, True), (170, True), (995, True), (1237, True), (1460, True),
                                (5, False), (6, False), (87, False), (1062, False), (0x80342002, False),
                                (9999, False)):
            with self.subTest(code=code):
                self.backend.api.WlanScan.return_value = code
                with self.assertRaises(WifiScanError) as caught:
                    self.backend.start_scan(self.interface)
                self.assertEqual(caught.exception.reason_code, code)
                self.assertEqual(caught.exception.retryable, retryable)
                self.assertFalse(self.backend._scan_active)

    def test_api_error_translation_failure_does_not_hide_original_code(self):
        self.backend.api.WlanScan.return_value = 9999
        with patch('src.core.windows_wifi.C.FormatError', side_effect=ValueError()):
            with self.assertRaises(WifiScanError) as caught:
                self.backend.start_scan(self.interface)
        self.assertEqual(caught.exception.reason_code, 9999)

    def test_interface_state_queries_real_state_and_releases_buffer(self):
        value = U32(3)  # disconnecting不能作为disconnected。
        data = C.c_void_p(C.addressof(value))
        with patch.object(self.backend, '_query', return_value=(0, data, C.sizeof(value))) as query:
            self.assertEqual(self.backend.interface_state(self.interface), 3)
            query.assert_called_once_with(self.interface, 6)
        self.backend.api.WlanFreeMemory.assert_called_once_with(data)

    def test_invalid_interface_state_buffer_is_rejected_and_freed(self):
        value = U32(4)
        data = C.c_void_p(C.addressof(value))
        with patch.object(self.backend, '_query', return_value=(0, data, 2)):
            with self.assertRaises(WifiEnvironmentError):
                self.backend.interface_state(self.interface)
        self.backend.api.WlanFreeMemory.assert_called_once_with(data)


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

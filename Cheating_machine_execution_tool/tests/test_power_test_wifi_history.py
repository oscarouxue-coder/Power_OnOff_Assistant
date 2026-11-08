"""WiFi历史回归：真实service配假网卡/虚拟时钟，IPC及窗口使用模拟对象。"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock

import test_legacy_power_test_service as parent_tests
from test_wifi_connection_service import FakeBackend, VirtualEvent, TARGETS
from src.models.wifi_test_models import (
    WifiEnvironmentError, WifiScanError, WifiSnapshot, WifiTestOptions, WirelessPingResult,
)
from src.services import legacy_power_test_service as legacy
from src.services.power_test_resume_service import PowerTestResumeSession
from src.services.power_test_wifi_history_service import PowerTestWifiHistory
from src.services.power_test_wifi_service import PowerTestWifiScheduler
from src.services.wifi_connection_service import WifiConnectionService


def line(stage, band='5G', channel=2, cycle=3):
    context = f'[WiFi测试] 通道{channel} 第{cycle}轮'
    return context + (f' 网卡=Wi-Fi 2 频段={band} ' if band else ' ') + stage


def log(text, **metadata):
    return dict(type='log', source='logger', level='info', message=text, **metadata)


class WifiHistoryTests(unittest.TestCase):
    def replay(self, messages):
        return parent_tests.LegacyPowerTestServiceTests()._run_status_messages(messages)

    def service_messages(self, backend=None, options=WifiTestOptions(), ping=None,
                         event=None, test_2g=False):
        backend, event = backend or FakeBackend(), event or VirtualEvent()
        service = WifiConnectionService(lambda: backend, ping, lambda: event.now)
        scheduler = PowerTestWifiScheduler(options=options, connection_service=service)
        raw = []
        outcome, band = scheduler.test_bands(
            channel=2, cycle=3, card='Wi-Fi', stop_event=event, emit=raw.append,
            connector=None, wifi_info=WifiSnapshot(TARGETS, True), test_2g=test_2g,
            test_5g=True, auth='WPA2-PSK', cipher='AES')
        if outcome == 'failed':
            raw.append(line(f'无线测试{band}失败', band=''))
        elif outcome == 'error':
            raw.append(line(f'测试环境异常：{band}', band=''))
        return [log(text) for text in raw] + [dict(
            type='channel_result', channel=2, ok=outcome == 'success',
            cancelled=outcome == 'cancelled')]

    def test_four_connection_attempts_keep_three_retries_and_one_detailed_failure(self):
        backend = FakeBackend()
        backend.obs = ()
        _, states, history, progress, _ = self.replay(self.service_messages(backend))
        self.assertEqual([e[:3] for e in history],
                         [(2, 3, 'retry')] * 3 + [(2, 3, 'failed')])
        self.assertIn('第4/4次', history[-1][3])
        self.assertIn('扫描未发现目标BSSID', history[-1][3])
        self.assertIn('5G', history[-1][3])
        self.assertEqual(states[-1], (2, 'failed', history[-1][3]))
        self.assertTrue(all(e[1] == 0 for e in progress))

    def test_four_scan_errors_preserve_reason_code_and_deduplicate_retry_wait(self):
        backend = FakeBackend()
        backend.scan_callback = Mock(side_effect=WifiScanError(
            '异步通知', 1237, retryable=True, reason='驱动暂忙'))
        _, _, history, _, _ = self.replay(self.service_messages(backend))
        self.assertEqual([e[2] for e in history], ['retry'] * 3 + ['failed'])
        self.assertTrue(all('1237/0x000004D5' in e[3] for e in history))
        self.assertIn('第4/4次', history[-1][3])

    def test_permanent_scan_error_is_first_attempt_failure_without_retry(self):
        backend = FakeBackend()
        backend.scan_callback = Mock(side_effect=WifiScanError('API', 5, reason='拒绝访问'))
        _, states, history, _, _ = self.replay(self.service_messages(backend))
        self.assertEqual([e[:3] for e in history], [(2, 3, 'failed')])
        self.assertIn('第1/4次', history[0][3])
        self.assertIn('5/0x00000005', states[-1][2])

    def test_retry_success_waits_for_final_band_success(self):
        backend = FakeBackend()
        def scan():
            if backend.scans == 1:
                raise WifiScanError('API', 170, retryable=True)
        backend.scan_callback = scan
        messages = self.service_messages(backend)
        parser = PowerTestWifiHistory((2,), 5)
        events = []
        for message in messages:
            if message['type'] == 'log':
                new = parser.consume(message['message'])
                if new and new[0][2] == 'success':
                    self.assertTrue(message['message'].endswith('成功：本项无线测试通过'))
                    self.assertEqual(backend.disconnects, 1)
                events.extend(new)
        self.assertEqual([e[2] for e in events], ['retry', 'success'])
        self.assertIn('第2/4次', events[-1][3])
        self.assertIn('重试1次后', events[-1][3])
        _, _, history, _, _ = self.replay(messages)
        self.assertEqual(history, events)

    def test_dual_band_records_only_band_that_retries(self):
        backend = FakeBackend()
        def scan():
            if backend.scans == 2:
                raise WifiScanError('异步通知', 21, retryable=True)
        backend.scan_callback = scan
        _, _, history, _, _ = self.replay(self.service_messages(backend, test_2g=True))
        self.assertEqual([e[2] for e in history], ['retry', 'success'])
        self.assertTrue(all('WiFi 5G' in e[3] for e in history))

    def test_unified_network_retry_has_its_own_context(self):
        backend = FakeBackend()
        def scan():
            if backend.scans == 1:
                raise WifiScanError('扫描超时', retryable=True)
        backend.scan_callback = scan
        _, _, history, _, _ = self.replay(self.service_messages(backend, WifiTestOptions('unified')))
        self.assertEqual([e[2] for e in history], ['retry', 'success'])
        self.assertTrue(all('合一网络' in e[3] for e in history))

    def test_ping_failure_never_records_connection_verification_as_success(self):
        ping = Mock(return_value=WirelessPingResult('192.0.2.1', 4, ()))
        _, _, history, _, _ = self.replay(self.service_messages(
            options=WifiTestOptions(wireless_ping_enable=True), ping=ping))
        self.assertEqual([e[2] for e in history], ['failed'])
        self.assertIn('无线Ping全部无有效回复', history[0][3])
        self.assertEqual(ping.call_count, 1)

    def test_dns_environment_error_keeps_original_code(self):
        ping = Mock(side_effect=WifiEnvironmentError('无线DNS解析失败：9005 DNS_ERROR_RCODE_REFUSED'))
        _, _, history, _, _ = self.replay(self.service_messages(
            options=WifiTestOptions(wireless_ping_enable=True), ping=ping))
        self.assertEqual([e[2] for e in history], ['failed'])
        self.assertIn('9005 DNS_ERROR_RCODE_REFUSED', history[0][3])

    def test_cleanup_error_after_retry_does_not_record_recovery(self):
        backend = FakeBackend()
        def scan():
            if backend.scans == 1:
                raise WifiScanError('API', 170, retryable=True)
        backend.scan_callback = scan
        backend.disconnect = Mock(side_effect=RuntimeError('hidden-driver-data'))
        _, _, history, _, _ = self.replay(self.service_messages(backend))
        self.assertEqual([e[2] for e in history], ['retry', 'failed'])
        self.assertIn('临时无线连接清理失败', history[-1][3])
        self.assertNotIn('hidden-driver-data', history[-1][3])

    def test_info_read_failure_uses_actual_round_and_detailed_reason(self):
        _, states, history, _, _ = self.replay([
            log(line('测试环境异常：样机BSSID格式无效', band='')),
            log(line('获取WiFi信息失败（测试环境/样机信息异常，未执行连接）', band='')),
            dict(type='channel_result', channel=2, ok=False)])
        self.assertEqual([e[:3] for e in history], [(2, 3, 'failed')])
        self.assertIn('BSSID格式无效', history[0][3])
        self.assertEqual(states[-1][2], history[0][3])

    def test_cancel_after_error_does_not_append_failure_or_recovery(self):
        event, backend = VirtualEvent(), FakeBackend()
        backend.scan_callback = Mock(side_effect=WifiScanError('API', 170, retryable=True))
        event.on_wait = event.set
        _, states, history, progress, _ = self.replay(self.service_messages(backend, event=event))
        self.assertEqual([e[2] for e in history], ['retry'])
        self.assertEqual(states[-1][1], 'stopped')
        self.assertTrue(all(e[1] == 0 for e in progress))

    def test_channels_rounds_and_finished_duplicate_results_are_isolated(self):
        parser = PowerTestWifiHistory((2, 7), 5)
        events = []
        for channel in (2, 7):
            events += parser.consume(line('第 1/4 次未通过：目标未发现', channel=channel))
            events += parser.consume(line('等待10秒后重试', channel=channel))
        events += parser.consume(line('第 2/4 次连接，扫描/连接/核验共约20秒；认证来源=auto'))
        events += parser.consume(line('成功：本项无线测试通过'))
        events += parser.finish(2, ok=True)
        events += parser.finish(7, ok=False)
        events += parser.finish(7, ok=False)
        events += parser.consume(line('失败：迟到消息', channel=7))
        self.assertEqual([e[:3] for e in events], [
            (2, 3, 'retry'), (7, 3, 'retry'), (2, 3, 'success'), (7, 3, 'failed')])
        self.assertEqual(parser.consume(line('成功：本项无线测试通过', cycle=4)), [])
        parser.reset(2)
        self.assertEqual(parser.consume(line('成功：本项无线测试通过', cycle=4)), [])
        self.assertEqual(parser.consume(line('失败：过期消息', cycle=3)), [])

    def test_credentials_skip_queue_and_unselected_channels_are_not_failures(self):
        parser = PowerTestWifiHistory((2,), 5)
        for text in ('WiFi信息：2.4G SSID=失败；密码=等待10秒后重试',
                     '入队；当前占用=通道7', '等待网卡 10.0秒；当前占用=通道7',
                     '跳过：WiFi主控关闭', '取消：用户停止'):
            self.assertEqual(parser.consume(line(text, band='')), [])
        self.assertEqual(parser.consume(line('测试环境异常：错误', channel=7)), [])
        self.assertEqual(parser.consume(line('测试环境异常：错误', cycle=6)), [])
        self.assertEqual(parser.finish(2, ok=False), [])

    def test_resume_resets_parser_keeps_history_and_filters_old_attempt(self):
        messages = [log(line('测试环境异常：首次失败', band=''), channel=2, attempt=0),
                    dict(type='channel_result', channel=2, ok=False, attempt=0),
                    dict(type='channel_started', channel=2, completed=2, attempt=1),
                    log(line('测试环境异常：过期失败', band=''), channel=2, attempt=0),
                    log(line('第 1/4 次未通过：扫描未发现目标'), channel=2, attempt=1),
                    log(line('等待10秒后重试'), channel=2, attempt=1),
                    log(line('第 2/4 次连接，扫描/连接/核验共约20秒；认证来源=auto'),
                        channel=2, attempt=1),
                    log(line('成功：本项无线测试通过'), channel=2, attempt=1),
                    dict(type='channel_result', channel=2, ok=True, attempt=1)]
        class Process(parent_tests._HistoryCompletedProcess):
            def start(self):
                for message in messages:
                    self.args[1].put(message)
                self.args[1].put(dict(type='result', ok=False, detail='原业务失败结论保留'))
                self._alive = False
        class Context(parent_tests._FakeProcessContext):
            def Process(self, **kwargs):
                return Process(**kwargs)
        with tempfile.TemporaryDirectory() as temp:
            request = replace(legacy.prepare_legacy_power_test_request(
                parent_tests._write_config_tree(Path(temp)),
                (legacy.LegacyPowerChannel(2, '192.168.1.102'),)), number_of_tests=5)
            session = PowerTestResumeSession(request, [], threading.Event(), lambda _: None)
            observe = session.observe
            def observe_and_advance(message):
                observe(message)
                if message['type'] == 'channel_result' and not message.get('attempt'):
                    session.attempts[2] = 1
            session.observe = observe_and_advance
            history = []
            result = legacy.run_legacy_power_test(
                request, lambda _: None, session.stop_event, process_context=Context(),
                resume_session=session, on_channel_history=lambda *e: history.append(e))
        self.assertFalse(result.ok)
        self.assertEqual([e[2] for e in history], ['failed', 'resume', 'retry', 'success', 'success'])
        self.assertFalse(any('过期失败' in e[3] for e in history))
        self.assertTrue(all(e[1] == 3 for e in history[:4]))

    def test_resume_wifi_failure_adds_one_failure_not_a_second_generic_resume_failure(self):
        _, _, history, _, _ = self.replay([
            dict(type='channel_started', channel=2, completed=2, attempt=1),
            log(line('验证失败：无线Ping全部无有效回复', band='')),
            log(line('无线测试5G失败', band='')),
            dict(type='channel_result', channel=2, ok=False, attempt=1)])
        self.assertEqual([e[2] for e in history], ['resume', 'failed'])

    def test_open_history_window_refreshes_wifi_entries_and_count(self):
        from line_check_assistant.app import LineCheckAssistant
        context = SimpleNamespace(
            power_test_channel_histories={}, power_test_channel_selected_number=2,
            power_test_channel_history_window=Mock(), power_test_channel_history_text=Mock(),
            power_test_channel_history_title_var=Mock())
        context._render_power_test_channel_overview = lambda: (
            LineCheckAssistant._refresh_power_test_channel_history_window(context))
        _, _, events, _, _ = self.replay([
            log(line('第 1/4 次未通过：目标SSID/BSSID不匹配')),
            log(line('等待10秒后重试')),
            log(line('验证失败：无线Ping全部无有效回复', band='')),
            dict(type='channel_result', channel=2, ok=False)])
        for event in events:
            LineCheckAssistant._record_power_test_channel_history(context, *event)
        self.assertEqual(context.power_test_channel_history_text.insert.call_count, 2)
        context.power_test_channel_history_title_var.set.assert_called_with('通道 2 本次重试/失败历史（2 条）')
        body = context.power_test_channel_history_text.insert.call_args.args[1]
        self.assertIn('第 3 轮｜重试', body)
        self.assertIn('第 3 轮｜失败', body)
        self.assertIn('无线Ping全部无有效回复', body)


if __name__ == '__main__':
    unittest.main()

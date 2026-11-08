"""WiFi逐通道文件、IPC旁路和真实无GUI适配层；全部使用临时目录及假设备。"""
import queue
import sys
import tempfile
import threading
import types
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.services import legacy_power_test_service as legacy
from src.services.power_test_log_service import latest_power_test_wifi_log
from src.services.power_test_wifi_log_service import WifiResultLogQueue, WifiResultLogWriter
from test_legacy_power_test_service import _write_config_tree


def wifi(channel=2, cycle=1, body='新的驱动提示'):
    return f'[WiFi测试] 通道{channel} 第{cycle}轮 {body}'


class WifiResultLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.events = []
        self.writer = WifiResultLogWriter(self.root, self.events.append,
                                         now=lambda: datetime(2026, 11, 6, 0, 1, 2, 123456))
        self.writer.start_channel(2)
        self.addCleanup(self.writer.finish_channel)

    def test_lazy_creation_ignores_non_wifi_unbound_and_other_channel(self):
        for text in ('normal log', '[DUT配置] WiFi查询', wifi(3)):
            self.writer.write('info', text)
        self.writer.finish_channel()
        self.writer.write('info', wifi())
        self.assertFalse((self.root / 'test_results').exists())
        self.assertEqual(self.events, [])

    def test_all_cycles_plaintext_and_errors_are_flushed_but_details_are_hidden(self):
        stages = ['WiFi信息：2.4G SSID=my ssid，密码=p a ss!；5G SSID=test5，密码=key5',
                  '下发只读命令：bbfdmd -c get Device.WiFi.SSID.1.SSID',
                  '频段=2.4G 无线DNS结果：203.0.113.1；本项使用第一个IPv4',
                  '频段=2.4G 无线Ping第4/4包：超时',
                  '测试环境异常：无线DNS没有返回IPv4地址（错误码9005）', '临时连接已清理']
        for cycle, body in enumerate(stages, 1):
            self.writer.write('info', wifi(cycle=cycle, body=body))
            path = latest_power_test_wifi_log(self.root, 2)
            self.assertIsNotNone(path)
            if cycle in (1, 5):
                self.assertIn(body, path.read_text(encoding='utf-8'))
            else:
                self.assertNotIn(body, path.read_text(encoding='utf-8'))
        paths = list(self.root.rglob('*.log'))
        self.assertEqual(len(paths), 1)
        lines = paths[0].read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all('[INFO] [WiFi] 通道2 第' in line for line in lines))
        self.assertTrue(paths[0].name.endswith('20261106000102123456.log'))
        handle = self.writer.local.state.file
        self.writer.finish_channel()
        self.assertTrue(handle.closed)
        self.assertTrue(any('已创建' in event for event in self.events))
        self.assertTrue(any('已关闭' in event for event in self.events))

    def test_multiline_messages_keep_channel_cycle_on_each_physical_line(self):
        self.writer.write('warning', wifi(cycle=3, body='诊断第一行\n诊断第二行'))
        lines = latest_power_test_wifi_log(self.root, 2).read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all('[WARNING] [WiFi] 通道2 第3轮' in line for line in lines))
        # 空正文及前导零的旧消息仍安全保存，不能让日志适配层中断测试。
        self.writer.write('info', '[WiFi测试] 通道02 第03轮')
        self.assertIn('[WiFi] 通道2 第3轮 \n',
                      latest_power_test_wifi_log(self.root, 2).read_text(encoding='utf-8'))

    def test_same_timestamp_collision_and_resume_do_not_overwrite(self):
        self.writer.write('info', wifi(body='original'))
        first = latest_power_test_wifi_log(self.root, 2)
        original = first.read_bytes()
        self.writer.finish_channel()
        self.writer.start_channel(2)
        self.writer.write('info', wifi(body='new run'))
        second = latest_power_test_wifi_log(self.root, 2)
        self.writer.finish_channel()
        self.writer.start_channel(2, attempt=2)
        self.writer.write('info', wifi(cycle=4, body='resume'))
        self.assertEqual(first.read_bytes(), original)
        self.assertNotEqual(first, second)
        paths = list((self.root / 'test_results/device_2').glob('*.log'))
        self.assertEqual(len(paths), 3)
        resumed = next(p for p in paths if '_resume_2.log' in p.name)
        self.assertIn('第4轮 resume', resumed.read_text(encoding='utf-8'))

    def test_threads_do_not_mix_channels_or_leave_open_files(self):
        barrier = threading.Barrier(2)
        handles = []
        def record(channel):
            self.writer.start_channel(channel)
            barrier.wait(timeout=2)
            for cycle in (1, 2):
                self.writer.write('info', wifi(channel, cycle, f'only-{channel}'))
            handles.append(self.writer.local.state.file)
            self.writer.finish_channel()
        threads = [threading.Thread(target=record, args=(channel,)) for channel in (2, 7)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(handles), 2)
        self.assertTrue(all(handle.closed for handle in handles))
        for channel, other in ((2, 7), (7, 2)):
            content = latest_power_test_wifi_log(self.root, channel).read_text(encoding='utf-8')
            self.assertIn(f'only-{channel}', content)
            self.assertNotIn(f'only-{other}', content)

    def test_directory_and_create_failures_warn_once_and_next_attempt_recovers(self):
        for operation in ('mkdir', 'open'):
            with self.subTest(operation=operation):
                self.events.clear()
                self.writer.start_channel(2)
                with patch.object(Path, operation, side_effect=PermissionError('access denied')) as failing:
                    self.writer.write('info', wifi())
                    self.writer.write('error', wifi(body='验证失败'))
                self.assertEqual(failing.call_count, 1)
                self.assertEqual(len(self.events), 1)
                self.assertIn('device_2_wifi_', self.events[0])
                self.assertIn('设备测试继续', self.events[0])
                self.writer.finish_channel()
        self.writer.start_channel(2, 1)
        self.writer.write('info', wifi(body='recovered'))
        self.assertIn('recovered', latest_power_test_wifi_log(self.root, 2).read_text(encoding='utf-8'))

    def test_write_flush_and_close_failures_are_nonfatal_and_warn_once(self):
        for operation in ('write', 'flush', 'close'):
            with self.subTest(operation=operation):
                self.writer.start_channel(2)
                opened = Mock()
                getattr(opened, operation).side_effect = OSError('disk failure')
                self.writer.local.state.file = opened
                self.writer.local.state.path = self.root / 'test_results/device_2/device_2_wifi_test.log'
                self.events.clear()
                if operation != 'close':
                    self.writer.write('info', wifi())
                    self.writer.write('info', wifi())
                self.writer.finish_channel()
                self.assertEqual(len(self.events), 1)
                self.assertIn('失败', self.events[0])
                self.assertIn('设备测试继续', self.events[0])

    def test_queue_preserves_ipc_metadata_and_raw_messages_when_file_fails(self):
        target = queue.Queue()
        stamped = legacy._AttemptQueue(target, 'run-123')
        stamped.local.channel, stamped.local.attempt = 2, 3
        forwarding = WifiResultLogQueue(stamped, self.writer)
        self.assertIs(forwarding.local, stamped.local)
        message = dict(type='log', level='info', source='logger', message=wifi())
        with patch.object(Path, 'mkdir', side_effect=OSError('full')):
            forwarding.put(message)
            forwarding.put(message)
        self.assertEqual(len(self.events), 1)
        for _ in range(2):
            self.assertEqual(target.get_nowait(), dict(message, channel=2, attempt=3, run_id='run-123'))

    def test_logger_credentials_and_signal_errors_are_both_captured(self):
        target = queue.Queue()
        forwarding = WifiResultLogQueue(target, self.writer)
        logger = legacy._ForwardingLegacyLogger(forwarding, ('wifi-secret', 'login-secret'))
        logger.wifi_credentials(2, 1, ('ssid2', 'wifi-secret', 'ssid5', 'p a ss'))
        logger.info('other operation: login-secret')
        signal = Mock()
        signal.__getitem__ = Mock(return_value=signal)
        worker = SimpleNamespace(show_signal_error=signal)
        legacy._connect_legacy_log_signals(worker, forwarding)
        signal.connect.call_args.args[0](wifi(body='测试环境异常：DNS错误码9005'))
        content = latest_power_test_wifi_log(self.root, 2).read_text(encoding='utf-8')
        self.assertIn('密码=wifi-secret', content)
        self.assertIn('密码=p a ss', content)
        self.assertIn('[ERROR]', content)
        self.assertIn('9005', content)
        self.assertNotIn('other operation', content)
        messages = list(target.queue)
        self.assertIn('***', messages[1]['message'])
        self.assertEqual(len(messages), 3)

    def test_original_command_file_bytes_and_result_bridge_remain_unchanged(self):
        target = queue.Queue()
        forwarding = WifiResultLogQueue(target, self.writer)
        directory = self.root / 'test_results/device_2'
        directory.mkdir(parents=True)
        command = directory / 'device_2_command_results_20261106000102.log'
        expected = '2026-11-06 00:01:02: 通道2下挂的设备在第1次测试时正常\n'.encode('utf-8')
        restore = legacy._install_legacy_result_log_forwarder(forwarding)
        try:
            with open(command, 'wb', buffering=0) as result:
                result.write(expected[:20])
                legacy._ForwardingLegacyLogger(forwarding, ()).info(wifi(body='无线Ping第4/4包：超时'))
                result.write(expected[20:])
        finally:
            restore()
        self.assertEqual(command.read_bytes(), expected)
        self.assertIsNone(latest_power_test_wifi_log(self.root, 2))
        self.assertTrue(any('无线Ping第4/4包：超时' in m.get('message', '') for m in target.queue))
        self.assertEqual(sum(m.get('source')=='result_file' for m in target.queue), 1)

    def test_hidden_only_messages_do_not_create_empty_file_or_change_ipc(self):
        target = queue.Queue()
        forwarding = WifiResultLogQueue(target, self.writer)
        for body in ('开始获取WiFi信息', '下发无线扫描', '临时连接已清理'):
            message = dict(type='log', level='info', source='logger', message=wifi(body=body))
            forwarding.put(message)
            self.assertIs(target.get_nowait(), message)
        self.assertIsNone(latest_power_test_wifi_log(self.root, 2))
        self.assertEqual(self.events, [])


class _FastEvent(threading.Event):
    def wait(self, timeout=None):
        if timeout in (0.5, 1.0):
            return self.is_set()
        return super().wait(timeout)


class HeadlessWifiLogIntegrationTests(unittest.TestCase):
    def _run(self, *, mode='success', attempt=0, fail_log=False, enabled=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = _write_config_tree(Path(temporary.name))
        request = replace(legacy.prepare_legacy_power_test_request(
            root, (legacy.LegacyPowerChannel(2, '192.0.2.2'),)),
            connect_wifi_enable=enabled, wifi_choose_wireless_card=False,
            wireless_ping_enable=False)
        target, stop = queue.Queue(), _FastEvent()
        class Serial:
            def __init__(self, *args, **kwargs): pass
            def is_open(self): return True
            def serial_close(self): pass
            def write(self, data): return len(data)
        class Worker:
            def __init__(self, serial, logger, *args, **kwargs):
                self.logger = logger
                self.dingtalk = SimpleNamespace(log=None)
                self.power_control = SimpleNamespace(consumer=lambda: None, stopthreadevent=0)
            def run_case(self, ip, channel, event, **kwargs):
                if enabled:
                    cycle = kwargs.get('start_cycle', 1)
                    self.logger.wifi_credentials(channel, cycle, ('test2', 'secret2', 'test5', 'secret5'))
                    for number in (cycle, cycle+1):
                        self.logger.info(wifi(channel, number,
                                              '频段=2.4G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）'))
                if mode == 'exception': raise RuntimeError('fake device failure')
                if mode == 'cancelled':
                    event.set()
                    return None
                return True
        modules = {}
        for name, attr, value in (
            ('common.serilal_client', 'Serial', Serial),
            ('test_case.powe_on_off_telnet', 'PowerOnOffTelnet', Worker),
            ('pywifi', 'PyWiFi', lambda: SimpleNamespace(interfaces=lambda: [SimpleNamespace(name=lambda: 'test-card')]))):
            module = types.ModuleType(name)
            setattr(module, attr, value)
            modules[name] = module
        patchers = [patch.dict(sys.modules, modules), patch.object(sys, 'path', list(sys.path)),
                    patch.object(legacy.os, 'chdir'),
                    patch.object(legacy, '_install_headless_legacy_stubs', return_value=SimpleNamespace())]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            if fail_log:
                stack.enter_context(patch('src.services.power_test_wifi_log_service.Path.mkdir', side_effect=OSError('full')))
            legacy._legacy_start_all_worker(request, target, stop, control_queue=queue.Queue(),
                                           run_id='test-run', attempts={2: attempt},
                                           initial_completed={2: 2} if attempt else {}, initialize_power=False)
        return root, list(target.queue)

    def test_real_adapter_opens_records_and_closes_resumed_attempt(self):
        root, messages = self._run(attempt=2)
        path = latest_power_test_wifi_log(root, 2)
        self.assertIn('_resume_2.log', path.name)
        content = path.read_text(encoding='utf-8')
        self.assertIn('密码=secret2', content)
        self.assertIn('第3轮', content)
        self.assertIn('第4轮', content)
        self.assertTrue(any('已关闭' in m.get('message', '') for m in messages))
        self.assertTrue(next(m for m in messages if m['type']=='channel_result')['ok'])
        self.assertTrue(all(m['attempt']==2 for m in messages if m['type']=='log' and m.get('source')=='logger'))

    def test_real_adapter_preserves_success_despite_log_failure(self):
        root, messages = self._run(fail_log=True)
        self.assertIsNone(latest_power_test_wifi_log(root, 2))
        self.assertEqual(sum('记录已停用' in m.get('message', '') for m in messages), 1)
        self.assertTrue(next(m for m in messages if m['type']=='channel_result')['ok'])
        self.assertEqual(sum(m['type']=='log' and 'WiFi测试' in m.get('message', '') for m in messages), 3)

    def test_real_adapter_closes_after_cancellation_and_exception(self):
        for mode in ('cancelled', 'exception'):
            with self.subTest(mode=mode):
                root, messages = self._run(mode=mode)
                self.assertIsNotNone(latest_power_test_wifi_log(root, 2))
                self.assertTrue(any('已关闭' in m.get('message', '') for m in messages))
                result = next(m for m in messages if m['type']=='channel_result')
                self.assertFalse(result['ok'])
                if mode == 'cancelled': self.assertTrue(result['cancelled'])

    def test_disabled_wifi_does_not_create_logs(self):
        root, messages = self._run(enabled=False)
        self.assertIsNone(latest_power_test_wifi_log(root, 2))
        self.assertTrue(next(m for m in messages if m['type']=='channel_result')['ok'])


if __name__ == '__main__':
    unittest.main()

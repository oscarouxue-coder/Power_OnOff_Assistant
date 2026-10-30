"""WiFi 并发、取消和主程序接入回归；全部使用模拟网卡/设备。"""
import ast
import importlib.util
import io
import queue
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from src.services.power_test_wifi_service import PowerTestWifiScheduler
from src.services import legacy_power_test_service as legacy
import test_legacy_power_test_service as legacy_tests


ROOT = Path(__file__).resolve().parents[1]


def load_connector():
    const = types.SimpleNamespace(IFACE_CONNECTED=4, IFACE_DISCONNECTED=0, IFACE_INACTIVE=1,
                                  CIPHER_TYPE_CCMP=3, CIPHER_TYPE_TKIP=2,
                                  AKM_TYPE_WPA2PSK=2, AKM_TYPE_WPAPSK=1,
                                  AKM_TYPE_WPA3SAE=3, AUTH_ALG_OPEN=0)
    wifi = types.ModuleType('pywifi')
    wifi.const = const
    wifi.Profile = lambda: types.SimpleNamespace(akm=[])
    config = types.ModuleType('config.config_driver')
    config.OperationConfig = Mock()
    logging = types.ModuleType('common.my_logging')
    logging.creat_logger = Mock()
    spec = importlib.util.spec_from_file_location('_wifi_test_transport',
                                                ROOT / 'Auto_power_on_off_tool/common/wifi_connect.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'pywifi': wifi, 'config.config_driver': config,
                                 'common.my_logging': logging}):
        spec.loader.exec_module(module)
    return module


WIFI = load_connector()


class FastEvent(threading.Event):
    def __init__(self, cancel_on_wait=None):
        super().__init__()
        self.waits = []
        self.cancel_on_wait = cancel_on_wait

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.cancel_on_wait is not None and self.cancel_on_wait(timeout):
            self.set()
        return self.is_set()


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = PowerTestWifiScheduler()
        self.stop = threading.Event()
        self.logs = []
        self.calls = []

    def run_bands(self, channel=1, connector=None, **changes):
        connector = connector or types.SimpleNamespace(connect_wifi=lambda ssid, *a, **k:
                                                        self.calls.append(ssid) or True)
        args = dict(channel=channel, cycle=4, card='Wi-Fi', stop_event=self.stop,
                    emit=self.logs.append, connector=connector,
                    wifi_info=(f'{channel}-2g', 'private-key', f'{channel}-5g', 'private-key'),
                    test_2g=True, test_5g=True, auth='WPA2-PSK', cipher='AES')
        args.update(changes)
        return self.scheduler.test_bands(**args)

    def start_thread(self, target):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        return thread

    def test_fifo_keeps_both_bands_together(self):
        entered, release, queued = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        results = []
        def connect(ssid, *args, **kwargs):
            self.calls.append(ssid)
            if ssid == '1-2g':
                entered.set()
                self.assertTrue(release.wait(2))
            return True
        connector = types.SimpleNamespace(connect_wifi=connect)
        def log(message):
            self.logs.append(message)
            if '通道2' in message and '入队' in message:
                queued.set()
        first = self.start_thread(lambda: results.append(self.run_bands(1, connector)))
        self.assertTrue(entered.wait(2))
        second = self.start_thread(lambda: results.append(self.run_bands(2, connector, emit=log)))
        self.assertTrue(queued.wait(2))
        release.set()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(self.calls, ['1-2g', '1-5g', '2-2g', '2-5g'])
        self.assertEqual(results, [('success', ''), ('success', '')])

    def test_waiting_cancel_removes_ticket_without_connecting(self):
        queued = threading.Event()
        result = []
        def log(message):
            if '入队' in message:
                queued.set()
        with self.scheduler.reserve(1, 1, '', threading.Event(), self.logs.append):
            worker = self.start_thread(lambda: result.append(self.run_bands(2, emit=log)))
            self.assertTrue(queued.wait(2))
            self.stop.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
        self.assertEqual(result, [('cancelled', '')])
        self.assertEqual(self.calls, [])
        self.stop.clear()
        self.assertEqual(self.run_bands(3), ('success', ''))

    def test_stop_at_acquisition_does_not_connect(self):
        def log(message):
            self.logs.append(message)
            if '取得使用权' in message:
                self.stop.set()
        self.assertEqual(self.run_bands(emit=log)[0], 'cancelled')
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.scheduler._owner)

    def test_stop_after_first_success_prevents_second_band(self):
        def connect(ssid, *a, **kw):
            self.calls.append(ssid)
            self.stop.set()
            return True
        self.assertEqual(self.run_bands(connector=types.SimpleNamespace(connect_wifi=connect))[0], 'cancelled')
        self.assertEqual(self.calls, ['1-2g'])

    def test_failure_and_exception_release_for_next_channel_and_resume(self):
        for error in (False, RuntimeError('private-key')):
            with self.subTest(error=type(error).__name__):
                connector = Mock()
                if isinstance(error, Exception):
                    connector.connect_wifi.side_effect = error
                else:
                    connector.connect_wifi.return_value = error
                self.assertEqual(self.run_bands(connector=connector), ('failed', '2.4G'))
                self.assertEqual(connector.connect_wifi.call_count, 1)
                self.assertEqual(self.run_bands(2), ('success', ''))
                self.assertEqual(self.run_bands(1), ('success', ''))
        self.assertNotIn('private-key', '\n'.join(self.logs))

    def test_single_band_and_disabled_bands(self):
        self.assertEqual(self.run_bands(test_2g=False), ('success', ''))
        self.assertEqual(self.calls, ['1-5g'])
        self.calls.clear()
        self.assertEqual(self.run_bands(test_2g=False, test_5g=False), ('skipped', ''))
        self.assertEqual(self.calls, [])
        self.assertTrue(any('跳过' in line for line in self.logs))

    def test_wait_report_every_ten_seconds(self):
        report = threading.Event()
        result = []
        def log(message):
            self.logs.append(message)
            if '等待网卡 10.0秒' in message:
                report.set()
                self.stop.set()
        with self.scheduler.reserve(1, 1, '', threading.Event(), lambda _: None):
            self.scheduler._clock = Mock(side_effect=[0, 10])
            worker = self.start_thread(lambda: result.append(self.run_bands(2, emit=log)))
            self.assertTrue(report.wait(2))
            worker.join(1)
        self.assertEqual(result[0][0], 'cancelled')
        self.assertTrue(any('当前占用=通道1' in line for line in self.logs))


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.connector = WIFI.WifiConnect.__new__(WIFI.WifiConnect)
        self.connector.wifi_lock = threading.Lock()
        self.connector.logger = Mock()
        self.iface = Mock()
        self.iface.name.return_value = 'Wi-Fi'
        self.iface.status.return_value = WIFI.const.IFACE_CONNECTED
        self.connector.wifi = types.SimpleNamespace(interfaces=lambda: [self.iface])
        self.logs = []

    def connect(self, stop=None, **kwargs):
        return self.connector.connect_wifi('test-ssid', 'private-key', stop_event=stop or FastEvent(),
                                           on_log=self.logs.append, **kwargs)

    def assert_released(self):
        self.assertTrue(self.connector.wifi_lock.acquire(False))
        self.connector.wifi_lock.release()

    def test_four_attempts_and_original_wait_budget(self):
        self.iface.status.return_value = WIFI.const.IFACE_DISCONNECTED
        stop = FastEvent()
        self.assertFalse(self.connect(stop))
        self.assertEqual(self.iface.connect.call_count, 4)
        self.assertEqual(stop.waits.count(10), 3)
        self.assertEqual(stop.waits.count(0.2), 400)
        self.assertTrue(any('第 4/4 次' in line for line in self.logs))
        self.assertNotIn('private-key', '\n'.join(self.logs))
        self.assert_released()

    def test_connected_success_uses_existing_auth_mapping(self):
        self.assertTrue(self.connect())
        profile = self.iface.add_network_profile.call_args.args[0]
        self.assertEqual((profile.ssid, profile.key, profile.akm, profile.cipher),
                         ('test-ssid', 'private-key', [WIFI.const.AKM_TYPE_WPA2PSK], WIFI.const.CIPHER_TYPE_CCMP))

    def test_cancel_during_poll_and_retry(self):
        for wait in (0.2, 10):
            with self.subTest(wait=wait):
                self.iface.reset_mock()
                self.iface.status.return_value = WIFI.const.IFACE_DISCONNECTED
                with self.assertRaises(WIFI.WifiConnectionCancelled):
                    self.connect(FastEvent(lambda timeout: timeout == wait))
                self.assertEqual(self.iface.connect.call_count, 1)
                self.assert_released()

    def test_cancel_before_start_does_not_touch_card(self):
        stop = FastEvent()
        stop.set()
        with self.assertRaises(WIFI.WifiConnectionCancelled):
            self.connect(stop)
        self.iface.disconnect.assert_not_called()
        self.iface.connect.assert_not_called()

    def test_cancel_in_driver_call_stops_next_action(self):
        stop = FastEvent()
        self.iface.disconnect.side_effect = stop.set
        with self.assertRaises(WIFI.WifiConnectionCancelled):
            self.connect(stop)
        self.iface.add_network_profile.assert_not_called()
        self.assert_released()

    def test_driver_error_is_redacted_and_releases_lock(self):
        self.iface.connect.side_effect = RuntimeError('private-key')
        with self.assertRaisesRegex(RuntimeError, 'RuntimeError') as caught:
            self.connect()
        self.assertNotIn('private-key', str(caught.exception))
        self.assert_released()

    def test_cancel_while_waiting_for_low_level_lock(self):
        stop = threading.Event()
        errors = []
        self.connector.wifi_lock.acquire()
        def run():
            try:
                self.connect(stop)
            except WIFI.WifiConnectionCancelled:
                errors.append('cancelled')
        worker = threading.Thread(target=run, daemon=True)
        try:
            worker.start()
            stop.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, ['cancelled'])
            self.iface.connect.assert_not_called()
        finally:
            self.connector.wifi_lock.release()


class IntegrationTests(unittest.TestCase):
    def test_wifi_credentials_are_explicitly_plaintext_but_other_secrets_stay_filtered(self):
        messages = queue.Queue()
        logger = legacy._ForwardingLegacyLogger(messages, ('private-key', 'login-secret'))
        logger.wifi_credentials(2, 4, ('ssid2', 'private-key', 'ssid5', 'private-key'))
        logger.info('other operation: login-secret')
        output = list(messages.queue)
        self.assertIn('密码=private-key', output[0]['message'])
        self.assertNotIn('login-secret', output[1]['message'])
        helper = legacy_tests.LegacyPowerTestServiceTests()
        _, _, _, _, logs = helper._run_status_messages(output)
        self.assertTrue(any('密码=private-key' in line for line in logs))

    def test_cancelled_result_is_not_failure_history_or_progress(self):
        helper = legacy_tests.LegacyPowerTestServiceTests()
        result, states, history, progress, logs = helper._run_status_messages([
            dict(type='channel_result', channel=2, ok=False, cancelled=True, attempt=1)])
        self.assertEqual(states, [(2, 'stopped', '用户停止WiFi测试，保留已完成轮次')])
        self.assertEqual(history, [])
        self.assertTrue(all(event[1] == 0 for event in progress))

    def test_wifi_events_survive_main_log_filter_without_passwords(self):
        helper = legacy_tests.LegacyPowerTestServiceTests()
        messages = ['入队', '等待网卡 10.0秒', '取得使用权', '下发连接目标SSID',
                    '第 1/4 次未连接，等待10秒后重试', '成功', '跳过', '取消', '释放使用权']
        _, _, history, _, logs = helper._run_status_messages([
            dict(type='log', source='logger', level='info',
                 message=f'[WiFi测试] 通道2 第1轮 网卡=Wi-Fi 频段=5G SSID=test {line}')
            for line in messages])
        for message in messages:
            self.assertTrue(any(message in line for line in logs), message)
        self.assertEqual(history, [])

    def test_real_wifi_stage_cancel_skips_ping_notifications_and_completion(self):
        # 执行真实 run_case 的 WiFi 分支及其取消处理；只隔离此前设备命令。
        path = ROOT / 'Auto_power_on_off_tool/test_case/powe_on_off_telnet.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'run_case')
        stage = next(n for n in ast.walk(method) if isinstance(n, ast.If)
                     and ast.unparse(n.test) == 'wifi_scheduler is not None')
        handler = next(n for n in ast.walk(method) if isinstance(n, ast.ExceptHandler)
                       and isinstance(n.type, ast.Name) and n.type.id == 'WifiConnectionCancelled')
        tail = ast.parse('self.cmd_ping()\nreturn wifi_info').body
        body = [ast.Try(body=[stage] + tail, handlers=[handler], orelse=[], finalbody=[])]
        args = ast.parse('def stage(self, stop_event, wifi_scheduler, wifi_info, times, tel, f): pass').body[0].args
        fn = ast.FunctionDef(name='stage', args=args, body=body, decorator_list=[])
        config = types.SimpleNamespace(connect_wifi_enable_status=1, choose_test_2g_flag=1,
                                       choose_test_5g_flag=1, Onu_solution_type='openwrt',
                                       choose_wireless_card_name='', connect_wifi_auth_mode='WPA2-PSK',
                                       connect_wifi_ciper='AES')
        env = dict(OnuCongfig=config, check_wifi_stop=WIFI.check_wifi_stop,
                   WifiConnectionCancelled=WIFI.WifiConnectionCancelled, power_num=2, network_card_ip='192.0.2.2')
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), env)
        worker = Mock()
        worker.run_status_list = [1] * 16
        worker.wifi_status_list = [0] * 16
        stop = threading.Event()
        scheduler = Mock()
        scheduler.read_info.return_value = ('ssid2', 'private-key', 'ssid5', 'private-key')
        def cancelled(**kwargs):
            stop.set()
            return 'cancelled', '2.4G'
        scheduler.test_bands.side_effect = cancelled
        self.assertIsNone(env['stage'](worker, stop, scheduler, None, 4, object(), io.BytesIO()))
        scheduler.read_info.assert_called_once()
        worker.cmd_ping.assert_not_called()
        worker.dingtalk.webhook_send_message.assert_not_called()
        self.assertEqual(worker.wifi_status_list, [0] * 16)
        # 同一轮续跑重新读取；后续轮使用本次缓存。
        stop.clear()
        scheduler.test_bands.side_effect = None
        scheduler.test_bands.return_value = ('success', '')
        cached = env['stage'](worker, stop, scheduler, None, 4, object(), io.BytesIO())
        env['stage'](worker, stop, scheduler, cached, 5, object(), io.BytesIO())
        self.assertEqual(scheduler.read_info.call_count, 2)
        self.assertEqual(worker.logger.wifi_credentials.call_count, 2)
        self.assertEqual(worker.cmd_ping.call_count, 2)
        config.connect_wifi_enable_status = 0
        scheduler.reset_mock()
        env['stage'](worker, stop, scheduler, None, 4, object(), io.BytesIO())
        scheduler.read_info.assert_not_called()
        scheduler.test_bands.assert_not_called()

    def test_read_info_uses_existing_commands_with_sensitive_flag(self):
        client = Mock()
        client.execute_read_until.side_effect = ['=> a', '=> private-key', '=> b', '=> private-key']
        logs = []
        result = PowerTestWifiScheduler().read_info(client, threading.Event(), logs.append, 'openwrt')
        self.assertEqual(result, ('a', 'private-key', 'b', 'private-key'))
        self.assertEqual(len(client.execute_read_until.call_args_list), 4)
        self.assertTrue(all(call.kwargs['sensitive'] for call in client.execute_read_until.call_args_list))
        self.assertNotIn('private-key', '\n'.join(logs))

    def test_sensitive_telnet_read_never_logs_or_saves_response(self):
        path = ROOT / 'Auto_power_on_off_tool/clients/telnet_client.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'execute_read_until')
        fake_time = types.SimpleNamespace(time=Mock(side_effect=[0, 0, 0, 0, 3, 3]))
        env = dict(time=fake_time)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), 'exec'), env)
        client = Mock()
        client.tn.read_very_eager.side_effect = [b'', b'=> private-key', b'']
        logs = []
        with patch.dict(sys.modules, {'common.wifi_connect': WIFI}):
            response = env['execute_read_until'](client, 'read-key', sensitive=True,
                                                 stop_event=FastEvent(), on_log=logs.append)
        self.assertEqual(response, '=> private-key')
        client.file.write.assert_not_called()
        client.logger.info.assert_not_called()
        self.assertNotIn('private-key', '\n'.join(logs))

    def test_sensitive_telnet_stop_prevents_command_and_exception_disclosure(self):
        path = ROOT / 'Auto_power_on_off_tool/clients/telnet_client.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'execute_read_until')
        env = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), 'exec'), env)
        client = Mock()
        logs = []
        stop = FastEvent()
        stop.set()
        with patch.dict(sys.modules, {'common.wifi_connect': WIFI}):
            with self.assertRaises(WIFI.WifiConnectionCancelled):
                env['execute_read_until'](client, 'read-key', sensitive=True, stop_event=stop)
            client.tn.write.assert_not_called()
            stop.clear()
            client.tn.write.side_effect = RuntimeError('private-key')
            self.assertFalse(env['execute_read_until'](client, 'read-key', sensitive=True,
                                                     stop_event=stop, on_log=logs.append))
        client.file.write.assert_not_called()
        self.assertNotIn('private-key', '\n'.join(logs))


if __name__ == '__main__':
    unittest.main()

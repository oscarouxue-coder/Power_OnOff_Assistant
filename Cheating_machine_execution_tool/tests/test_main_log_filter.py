"""WiFi摘要、主日志/独立文件一致性；仅使用临时文件和模拟Text控件。"""
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from line_check_assistant.app import LineCheckAssistant
from src.services.legacy_power_test_service import _ForwardingLegacyLogger
from src.services.power_test_wifi_log_service import WifiResultLogWriter, WifiResultLogQueue
from src.ui.main_log_filter import format_main_log_message
from src.utils.wifi_log_summary import WifiLogSummary


def wifi_message(body, *, level='INFO', channel=2, cycle=4):
    return f'[旧工具Logs][{level}] [WiFi测试] 通道{channel} 第{cycle}轮 {body}'


def connected(band='2.4G', ssid='my network'):
    return (f'频段={band} 连接核验成功：SSID={ssid} BSSID=aa:bb:cc:dd:ee:ff '
            '实际频段=2.4G 认证=WPA2-PSK 加密=AES')


def ping_result(received=3):
    latency = ' 时延min/avg/max=10.00/20.00/30.00ms' if received else ''
    result = '通过' if received else '失败'
    return f'无线Ping汇总：发送4 接收{received} 丢包率={(4-received)*25}%{latency} {result}'


class MainLogFilterTests(unittest.TestCase):
    def setUp(self):
        self.summary = WifiLogSummary()

    def send(self, body, **kwargs):
        return format_main_log_message(wifi_message(body, **kwargs), self.summary)

    def test_other_logs_and_dut_queries_are_unchanged(self):
        for message in (
            '[DUT配置][2.4G WiFi查询] TX UBUS bbfdm.get path=Device.WiFi.Radio.',
            '[旧工具Logs][INFO] Ping 成功：源网卡 192.168.1.115 → 目标样机 192.168.1.1',
            '[旧工具Logs][ERROR] 通道 2 登录telnet失败',
            '[旧工具Logs][INFO] *******通道 【2】 开始第4次测试*******',
            '[WiFi连接日志] 打开失败',
        ):
            with self.subTest(message=message):
                self.assertEqual(format_main_log_message(message, self.summary), message)

    def test_known_normal_details_are_hidden(self):
        for stage in (
            '开始获取WiFi信息', '成功：WiFi信息读取完成',
            '下发只读命令：bbfdmd -c get Device.WiFi.SSID.1.SSID',
            '只读命令返回（WiFi回显隐藏）',
            '目标已读取：频段=2.4G Radio=1 SSID=test BSSID=aa:bb:cc:dd:ee:ff',
            '双频合一状态=关闭', '等待网卡 81.0秒；当前占用=通道1 第1轮',
            '实际无线网卡=aWLAN GUID=test-guid ifIndex=17',
            '下发无线扫描', '目标SSID=test BSSID=aa:bb:cc:dd:ee:ff 频段=2.4G 认证=WPA2-PSK 加密=AES',
            '等待10秒后重试', '无线Ping：等待无线IPv4地址（最长30秒）',
            '无线DNS查询：目标=example.com 接口索引=17',
            '无线DNS结果：203.0.113.1, 203.0.113.2；本项使用第一个IPv4',
            '无线Ping下发：第1/4包，192.168.1.240 → 203.0.113.1，超时2秒',
            '无线Ping第1/4包：回复 594.00ms', '无线Ping第4/4包：超时',
            '下发断开临时连接；不删除电脑原有无线配置', '临时连接已清理', '释放使用权',
        ):
            with self.subTest(stage=stage):
                self.assertIsNone(self.send(stage))
                self.assertIsNone(self.send('网卡=Intel(R) Wi-Fi 7 BE200 320MHz 频段=2.4G ' + stage))

    def test_connections_and_partial_ping_emit_only_after_final_success(self):
        self.assertIsNone(self.send('频段=2.4G 第 2/4 次连接，扫描/连接/核验共约20秒；认证来源=auto'))
        self.assertEqual(self.send('网卡=Wi-Fi 2 频段=2.4G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）'),
                         '[WiFi] 通道2 第4轮 2.4G 第2/4次下发连接')
        self.assertIsNone(self.send(connected()))
        self.assertIsNone(self.send('频段=2.4G 无线Ping开始：网卡=Wi-Fi 2 ifIndex=17 '
                                    '源IP=192.168.1.240 目标=example.com 实际IP=203.0.113.1'))
        self.assertIsNone(self.send('频段=2.4G ' + ping_result()))
        result = self.send('频段=2.4G 成功：本项无线测试通过')
        self.assertIn('2.4G 测试通过；SSID=my network；Ping发送4/接收3，丢包25%', result)
        self.assertIn('192.168.1.240→example.com(203.0.113.1)', result)
        self.assertNotIn('BSSID=', result)
        self.assertIsNone(self.send('频段=2.4G 成功：本项无线测试通过'))

    def test_unified_and_ping_disabled(self):
        self.send(connected('合一网络'))
        self.assertIsNone(self.send('频段=合一网络 跳过：无线Ping未启用'))
        self.assertEqual(self.send('频段=合一网络 成功：本项无线测试通过'),
                         '[WiFi] 通道2 第4轮 合一网络 测试通过；SSID=my network；实际频段=2.4G；Ping未启用')

    def test_retries_reset_pending_result_and_keep_actual_attempt(self):
        self.send(connected())
        failure = '频段=2.4G 第 1/4 次未通过：扫描未发现目标BSSID或频段不符'
        self.assertIn(failure, self.send(failure))
        self.send('频段=2.4G 第 2/4 次连接，扫描/连接/核验共约20秒；认证来源=auto')
        self.assertIn('第2/4次下发连接', self.send('频段=2.4G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）'))
        self.send(connected(ssid='second'))
        self.send('频段=2.4G 跳过：无线Ping未启用')
        self.assertIn('SSID=second；Ping未启用', self.send('频段=2.4G 成功：本项无线测试通过'))

    def test_queue_only_reports_contention_and_actual_wait(self):
        self.assertIsNone(self.send('网卡=Wi-Fi 2 入队；当前占用=无'))
        self.assertIsNone(self.send('网卡=Wi-Fi 2 取得使用权；等待 0.0秒'))
        self.assertIn('排队；当前占用=通道1 第1轮', self.send('网卡=Wi-Fi 2 入队；当前占用=通道1 第1轮'))
        self.assertIsNone(self.send('网卡=Wi-Fi 2 等待网卡 80.0秒；当前占用=通道1 第1轮'))
        self.assertEqual(self.send('网卡=Wi-Fi 2 取得使用权；等待 83.2秒'), '[WiFi] 通道2 第4轮 排队等待83.2秒')

    def test_errors_retries_cancel_skip_and_unknown_messages_survive(self):
        for stage in (
            '频段=2.4G 第 3/4 次未通过：扫描未发现目标BSSID或频段不符',
            '测试环境异常：2.4G：无线DNS没有返回IPv4地址（错误码9005）',
            '频段=5G ' + ping_result(0),
            '取消：用户停止WiFi测试', '取消等待/执行', '跳过：2.4G、5G均未启用',
            '频段=5G 跳过：未启用', '跳过：WiFi主控关闭',
            '临时连接已清理但驱动报告异常', '下发无线扫描失败',
            '无线DNS结果：读取失败', '双频合一状态未知；不会根据SSID同名推断', '新版本增加的阶段',
        ):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.send(stage))

    def test_no_success_after_zero_ping_guard_failure_or_cancellation(self):
        for ending in ('频段=2.4G ' + ping_result(0), '验证失败：连接核验不符',
                       '取消：用户停止WiFi测试', '测试环境异常：DNS9005'):
            with self.subTest(ending=ending):
                self.summary = WifiLogSummary()
                self.send(connected())
                if '汇总' not in ending:
                    self.send('频段=2.4G ' + ping_result())
                self.assertIn(ending, self.send(ending))
                self.assertIsNone(self.send('频段=2.4G 成功：本项无线测试通过'))

    def test_channels_bands_cycles_and_same_cycle_resume_do_not_mix(self):
        for channel, band, ssid in ((2, '2.4G', 'two'), (7, '5G', 'seven'), (2, '5G', 'five')):
            self.send(connected(band, ssid), channel=channel)
            self.send(f'频段={band} 跳过：无线Ping未启用', channel=channel)
        for channel, band, ssid in ((7, '5G', 'seven'), (2, '2.4G', 'two'), (2, '5G', 'five')):
            result = self.send(f'频段={band} 成功：本项无线测试通过', channel=channel)
            self.assertIn(f'通道{channel} 第4轮 {band} 测试通过；SSID={ssid}', result)
        self.send('开始获取WiFi信息')  # 续跑同一失败轮次，必须清除旧缓存。
        result = self.send('频段=2.4G 成功：本项无线测试通过')
        self.assertNotIn('SSID=', result)
        self.send(connected(), cycle=5)
        self.assertNotIn('SSID=', self.send('频段=5G 成功：本项无线测试通过', cycle=5))
        self.assertLessEqual(len(self.summary.channels[2].groups), 2)

    def test_credentials_are_opaque_plaintext_even_with_filter_keywords(self):
        body = ('WiFi信息：2.4G SSID=网卡=network，密码=异常 成功：本项无线测试通过；'
                '5G SSID=频段=5G，密码=pa ss网卡=word')
        self.assertEqual(self.send(body), '[WiFi] 通道2 第4轮 ' + body)
        self.send(connected(ssid='异常 测试通过 网卡=network'))
        self.assertIn('SSID=异常 测试通过 网卡=network', self.send('频段=2.4G 成功：本项无线测试通过'))

    def test_warning_error_and_multiline_unknown_are_not_hidden(self):
        for level in ('WARNING', 'ERROR'):
            self.assertEqual(self.send('下发无线扫描', level=level), f'[WiFi][{level}] 通道2 第4轮 下发无线扫描')
        self.assertIn('诊断第一行\n第二行', self.send('诊断第一行\n第二行'))


class MainLogPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.context = SimpleNamespace(log_path=self.root / 'main.log', log_text=Mock())
        self.context._log_tag_for = lambda text: LineCheckAssistant._log_tag_for(self.context, text)

    def test_hidden_messages_touch_neither_ui_nor_disk(self):
        LineCheckAssistant._log(self.context, wifi_message('频段=2.4G 无线Ping第4/4包：超时'))
        self.assertEqual(self.context.log_text.mock_calls, [])
        self.assertFalse(self.context.log_path.exists())

    def test_visible_message_uses_same_summary_on_disk_and_keeps_error_color(self):
        message = wifi_message('网卡=Intel(R) Wi-Fi 7 BE200 320MHz 测试环境异常：DNS错误码9005')
        LineCheckAssistant._log(self.context, message)
        expected = '[WiFi] 通道2 第4轮 测试环境异常：DNS错误码9005'
        self.context.log_text.insert.assert_any_call('end', expected + '\n', 'error')
        self.assertTrue(self.context.log_path.read_text(encoding='utf-8').endswith(expected + '\n'))
        self.assertNotIn('[旧工具Logs]', self.context.log_path.read_text(encoding='utf-8'))

    def test_explicit_tag_and_other_log_text_remain_intact(self):
        message = '[DUT配置] WiFi查询成功'
        LineCheckAssistant._log(self.context, message, tag='muted')
        self.context.log_text.insert.assert_any_call('end', message + '\n', 'muted')
        self.assertTrue(self.context.log_path.read_text(encoding='utf-8').endswith(message + '\n'))

    def test_three_sinks_match_and_raw_ipc_is_unchanged(self):
        writer = WifiResultLogWriter(self.root, lambda event: None)
        writer.start_channel(2)
        self.addCleanup(writer.finish_channel)
        target = queue.Queue()
        forwarding = WifiResultLogQueue(target, writer)
        stages = ['开始获取WiFi信息',
                  'WiFi信息：2.4G SSID=my network，密码=p a ss!；5G SSID=test5，密码=key5',
                  '网卡=Wi-Fi 2 入队；当前占用=无', '网卡=Wi-Fi 2 取得使用权；等待 0.0秒']
        for band in ('2.4G', '5G'):
            stages += [f'频段={band} 第 1/4 次连接，扫描/连接/核验共约20秒；认证来源=auto',
                       f'频段={band} 下发无线扫描',
                       f'频段={band} 下发目标BSSID临时连接配置（不保存或覆盖用户配置）',
                       connected(band), f'频段={band} 无线Ping第4/4包：超时',
                       f'频段={band} ' + ping_result(), f'频段={band} 成功：本项无线测试通过',
                       f'频段={band} 临时连接已清理']
        stages += ['释放使用权', '未知驱动提示']
        raw = []
        for stage in stages:
            entry = dict(type='log', source='logger', level='info', run_id='run', attempt=2,
                         message=f'[WiFi测试] 通道2 第4轮 {stage}')
            raw.append(entry.copy())
            forwarding.put(entry)
            message = target.get_nowait()
            self.assertEqual(message, raw[-1])
            LineCheckAssistant._log(self.context, f"[旧工具Logs][INFO] {message['message']}")
        rendered = [call.args[1].rstrip('\n') for call in self.context.log_text.insert.call_args_list
                    if call.args[0] == 'end' and not (len(call.args) == 3 and call.args[2] == 'time')]
        main = [line[20:] for line in self.context.log_path.read_text(encoding='utf-8').splitlines()]
        saved = list(self.root.glob('test_results/device_2/*.log'))[0]
        independent = [line.split('[INFO] ', 1)[1] for line in saved.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(main, rendered)
        self.assertEqual(main, independent)
        self.assertEqual(len(main), 6)  # 凭据+每频段两条+未知消息。
        self.assertEqual(sum('测试通过' in line for line in main), 2)
        self.context.log_text.insert.assert_any_call('end', main[2] + '\n', 'success')

    def test_real_service_scan_recovery_keeps_three_sinks_and_attempt_number_consistent(self):
        from test_wifi_connection_service import FakeBackend, VirtualEvent, TARGETS
        from src.services.wifi_connection_service import WifiConnectionService
        from src.services.power_test_wifi_service import PowerTestWifiScheduler
        from src.models.wifi_test_models import WifiScanError, WifiSnapshot, WifiTestOptions
        backend, stop = FakeBackend(), VirtualEvent()
        def scan():
            if backend.scans == 2:  # 2.4G通过后，5G第一次扫描失败。
                raise WifiScanError('异步通知', 0x10009, retryable=True, reason='扫描调用失败')
        backend.scan_callback = scan
        service = WifiConnectionService(lambda: backend, clock=lambda: stop.now)
        scheduler = PowerTestWifiScheduler(options=WifiTestOptions(), connection_service=service)
        writer = WifiResultLogWriter(self.root, lambda _: None)
        writer.start_channel(2, 1)
        self.addCleanup(writer.finish_channel)
        def emit(text):
            writer.write('info', text)
            LineCheckAssistant._log(self.context, '[旧工具Logs][INFO] ' + text)
        result = scheduler.test_bands(channel=2, cycle=4, card='Wi-Fi', stop_event=stop,
                                     emit=emit, connector=None, wifi_info=WifiSnapshot(TARGETS),
                                     test_2g=True, test_5g=True, auth='WPA2-PSK', cipher='AES')
        self.assertEqual(result, ('success', ''))
        main = [line[20:] for line in self.context.log_path.read_text(encoding='utf-8').splitlines()]
        independent = next(self.root.glob('test_results/device_2/*_resume_1.log'))
        saved = [line.split('[INFO] ', 1)[1] for line in independent.read_text(encoding='utf-8').splitlines()]
        rendered = [call.args[1].rstrip('\n') for call in self.context.log_text.insert.call_args_list
                    if call.args[0] == 'end' and not (len(call.args)==3 and call.args[2]=='time')]
        self.assertEqual(main, saved)
        self.assertEqual(main, rendered)
        self.assertEqual(sum('次扫描失败' in text for text in main), 1)
        self.assertTrue(any('5G 第2/4次下发连接' in text for text in main))
        self.assertTrue(any('0x00010009' in text and '10秒后重试' in text for text in main))
        self.assertEqual(sum('测试通过' in text for text in main), 2)

    def test_real_forwarded_credentials_are_plaintext_in_ui_and_file_on_resume(self):
        messages = queue.Queue()
        logger = _ForwardingLegacyLogger(messages, ('sample-password', 'other-secret'))
        for channel, cycle in ((1, 1), (2, 1), (7, 3)):
            logger.wifi_credentials(channel, cycle, ('my ssid', 'sample-password', 'ssid5', 'p a ss!'))
        while not messages.empty():
            entry = messages.get_nowait()
            LineCheckAssistant._log(self.context, f"[旧工具Logs][{entry['level'].upper()}] {entry['message']}")
        disk = self.context.log_path.read_text(encoding='utf-8')
        rendered = ''.join(call.args[1] for call in self.context.log_text.insert.call_args_list)
        for text in (disk, rendered):
            self.assertEqual(text.count('密码=sample-password'), 3)
            self.assertEqual(text.count('密码=p a ss!'), 3)
            for channel, cycle in ((1, 1), (2, 1), (7, 3)):
                self.assertEqual(text.count(f'通道{channel} 第{cycle}轮 WiFi信息：'), 1)


if __name__ == '__main__':
    unittest.main()

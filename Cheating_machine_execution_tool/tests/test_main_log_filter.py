"""AI/DUT显示与完整落盘、开关机WiFi三处摘要一致性；不连接设备或模型。"""
from dataclasses import asdict
import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from line_check_assistant.app import LineCheckAssistant
from src.services.legacy_power_test_service import _ForwardingLegacyLogger
from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.power_test_wifi_log_service import WifiResultLogWriter, WifiResultLogQueue
from src.ui.main_log_filter import ai_main_log_tag, format_main_log_message, is_ai_log_message, is_dut_log_message
from src.models.dut_config_models import DutTr069Settings, DutVoiceSettings, DutWifiRadioSettings, DutWifiSettings
from src.utils.ai_redaction import DiagnosticRedactor
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

    def test_real_service_ping_guard_retry_keeps_three_sinks_and_fresh_ping_result(self):
        from test_wifi_connection_service import FakeBackend, VirtualEvent, TARGETS, OBS
        from src.services.wifi_connection_service import WifiConnectionService
        from src.services.power_test_wifi_service import PowerTestWifiScheduler
        from src.models.wifi_test_models import WifiSnapshot, WifiTestOptions, WirelessPingResult
        backend, stop = FakeBackend(), VirtualEvent()
        backend.scan_callback = lambda: setattr(backend, 'obs', OBS)
        ping = Mock()
        def probe(interface, target, event, emit, guard):
            replies = (99.0,) if ping.call_count == 1 else (2.0, 4.0)
            emit(f'无线Ping汇总：发送4 接收{len(replies)} 丢包率={(4-len(replies))*25}% '
                 f'时延min/avg/max={min(replies):.2f}/{sum(replies)/len(replies):.2f}/{max(replies):.2f}ms 通过')
            if ping.call_count == 1:
                backend.obs = ()  # 汇总后service最后核验失败，不能提前显示通过。
            return WirelessPingResult('192.0.2.1', 4, replies)
        ping.side_effect = probe
        service = WifiConnectionService(lambda: backend, ping, lambda: stop.now)
        scheduler = PowerTestWifiScheduler(options=WifiTestOptions(wireless_ping_enable=True),
                                            connection_service=service)
        writer = WifiResultLogWriter(self.root, lambda _: None)
        writer.start_channel(2)
        self.addCleanup(writer.finish_channel)
        def emit(text):
            writer.write('info', text)
            LineCheckAssistant._log(self.context, '[旧工具Logs][INFO] ' + text)
        result = scheduler.test_bands(channel=2, cycle=4, card='Wi-Fi', stop_event=stop,
                                     emit=emit, connector=None, wifi_info=WifiSnapshot(TARGETS),
                                     test_2g=True, test_5g=False, auth='WPA2-PSK', cipher='AES')
        self.assertEqual(result, ('success', ''))
        main = [line[20:] for line in self.context.log_path.read_text(encoding='utf-8').splitlines()]
        saved = next(self.root.glob('test_results/device_2/*.log')).read_text(encoding='utf-8')
        independent = [line.split('[INFO] ', 1)[1] for line in saved.splitlines()]
        rendered = [call.args[1].rstrip('\n') for call in self.context.log_text.insert.call_args_list
                    if call.args[0] == 'end' and not (len(call.args) == 3 and call.args[2] == 'time')]
        self.assertEqual(main, independent)
        self.assertEqual(main, rendered)
        self.assertEqual(sum('Ping阶段连接核验失败：无法核验实际连接频率' in s for s in main), 1)
        self.assertTrue(any('2.4G 第2/4次下发连接' in s for s in main))
        successes = [s for s in main if '测试通过' in s]
        self.assertEqual(len(successes), 1)
        self.assertIn('Ping发送4/接收2', successes[0])
        self.assertNotIn('99.00', successes[0])

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


def dut_message(body, *, channel=1, feature='2.4G WiFi查询'):
    return f'[DUT配置][{feature}][通道 {channel}] {body}'


def dut_details():
    radio2 = DutWifiRadioSettings(band='2.4G')
    radio5 = DutWifiRadioSettings(band='5G')
    return [
        "RX UBUS Device.WiFi.X_SDMC_Mapping_2G：{'X_SDMC_Mapping_2G': '1,1,1'}",
        "RX UBUS Device.WiFi.X_SDMC_Mapping_5G：{'X_SDMC_Mapping_5G': '2,2,2'}",
        "RX UBUS Device.WiFi.X_SDMC_DualBandEnable：{'X_SDMC_DualBandEnable': '0,0'}",
        "RX UBUS Device.WiFi.Radio.：{'Radio': [{'Channel': 6}]}",
        "RX UBUS Device.WiFi.Radio.2.：{'Radio': [{'Channel': 36}]}",
        "RX UBUS Device.WiFi.SSID.：{'SSID': []}",
        "RX UBUS Device.WiFi.SSID.1.：{'SSID': [{'SSID': '异常 成功 SSID'}]}",
        "RX UBUS Device.WiFi.AccessPoint.：{'AccessPoint': []}",
        "RX UBUS Device.WiFi.AccessPoint.3.：{'AccessPoint': [{'Security': {}}]}",
        "RX UBUS Device.WiFi.AccessPoint.3.Security.：{'ModeEnabled': 'None'}",
        f'RX UBUS 2.4G WiFi当前状态：{DutWifiSettings(ssid="异常 成功 SSID", password="device-password")}',
        f'RX UBUS 5G WiFi当前状态：{DutWifiSettings(band="5G")}',
        f'RX UBUS 双频Radio当前状态：2.4G={radio2}，5G={radio5}',
        f'RX UBUS 双频Radio当前状态：5G={radio5}，2.4G={radio2}',
        "RX UBUS WAN 完整信息：['wan1(业务=INTERNET, VLAN=100, 组播VLAN=-, 模式=router, 接入=IPoE)']",
        'RX UBUS WAN 完整信息：[]',
        'RX UBUS 语音当前状态：' + json.dumps(asdict(DutVoiceSettings()), ensure_ascii=False, sort_keys=True),
        'RX UBUS TR069当前状态：' + json.dumps(asdict(DutTr069Settings()), ensure_ascii=False, sort_keys=True),
    ]


class DutMainLogFilterTests(unittest.TestCase):
    def test_known_details_are_hidden_for_each_channel(self):
        for channel in (1, 8):
            for body in dut_details():
                with self.subTest(channel=channel, body=body):
                    self.assertIsNone(format_main_log_message(dut_message(body, channel=channel)))

    def test_commands_results_and_all_failure_stages_remain_visible(self):
        for body in (
            '准备网络：192.168.1.101 -> 192.168.1.1',
            'TX UBUS session.login：192.168.1.101 -> 192.168.1.1:80，用户名=admin，密码=plain-password',
            'TX UBUS bbfdm.get path=Device.WiFi.Radio.2.',
            "TX UBUS bbfdm.set WiFi paths=[{'addr': 'Device.WiFi.SSID.1.', 'obj_path': {'SSID': '失败'}}]",
            'TX UBUS bbfdm.unauthenticated_operate command=Device.X_SDMC_Login.logout()',
            "RX UBUS 2.4G WiFi配置结果：[0, {'results': [{'data': '1'}]}]",
            'RX UBUS WAN Result=OK，Method=add，Index=1',
            "RX UBUS WAN 连接列表：['wan1']",
            'RX UBUS TR069 Inform 状态：10_success',
            'UBUS 登录成功', 'UBUS 会话已注销',
            '等待 WiFi 参数生效并稳定：60 秒',
            '成功：2.4G WiFi查询成功', '成功：2.4G WiFi 回读校验成功',
            '跳过：用户已停止，未继续执行本台后续步骤',
            'UBUS WiFi只读请求连接异常：timed out；等待 1 秒后重建连接重试 1/1',
            'UBUS 会话注销失败（已继续关闭连接）：Access denied',
            "失败：WiFi 状态返回缺少 SSID/AccessPoint/Radio 节点：SSID={}",
        ):
            message = dut_message(body)
            with self.subTest(body=body):
                self.assertEqual(format_main_log_message(message), message)

    def test_unknown_formats_multiline_and_nested_prefix_are_preserved(self):
        for message in (
            dut_message('RX UBUS Device.WiFi.Radio.2.：读取失败'),
            dut_message('RX UBUS Device.WiFi.NewNode.：{}'),
            dut_message('RX UBUS 2.4G WiFi当前状态：新格式'),
            dut_message('RX UBUS WAN 完整信息：读取异常'),
            dut_message(dut_details()[0] + '\n后续失败'),
            dut_message(dut_details()[0] + '；新版本说明'),
            dut_message('诊断第一行\n第二行'),
            '[DUT配置新功能] ' + dut_details()[0],
            '[旧工具Logs][INFO] ' + dut_message(dut_details()[0]),
            '[AI对话] ' + dut_message(dut_details()[0]),
            '[DUT配置][未完成前缀 ' + dut_details()[0],
        ):
            with self.subTest(message=message):
                self.assertEqual(format_main_log_message(message), message)
        self.assertFalse(is_dut_log_message('[DUT配置新功能] 测试'))
        self.assertFalse(is_dut_log_message('[旧工具Logs][INFO] [DUT配置] 测试'))
        self.assertTrue(is_dut_log_message('[DUT配置] 查询成功'))

    def test_real_core_query_logs_are_filtered_without_changing_query_results(self):
        from src.core.dut_wifi_config import query_wifi_status
        from test_dut_wifi_config import _FakeWifiClient
        for band in ('2.4G', '5G'):
            with self.subTest(band=band):
                client = _FakeWifiClient()
                logs = []
                result = query_wifi_status(client, 'session', band, on_log=logs.append)
                self.assertEqual(result.band, band)
                self.assertIsNotNone(result.peer_radio)
                self.assertTrue(all(call[0] == 'get' for call in client.calls))
                for body in logs:
                    shown = format_main_log_message(dut_message(body))
                    if body.startswith('RX UBUS '):
                        self.assertIsNone(shown, body)
                    else:
                        self.assertEqual(shown, dut_message(body))


class DutMainLogPersistenceTests(unittest.TestCase):
    setUp = MainLogPersistenceTests.setUp

    def test_hidden_details_are_saved_verbatim_without_touching_ui(self):
        messages = [dut_message(body) for body in dut_details()]
        for message in messages:
            LineCheckAssistant._log(self.context, message)
        self.assertEqual(self.context.log_text.mock_calls, [])
        lines = self.context.log_path.read_text(encoding='utf-8').splitlines()
        self.assertEqual([line[20:] for line in lines], messages)
        for line in lines:
            self.assertRegex(line[:20], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} $')

    def test_interleaved_channels_ai_and_wifi_keep_separate_file_rules(self):
        hidden1 = dut_message(dut_details()[0])
        hidden8 = dut_message(dut_details()[12], channel=8)
        command8 = dut_message('TX UBUS bbfdm.get path=Device.WiFi.Radio.2.', channel=8)
        error1 = dut_message('失败：连接超时')
        success8 = dut_message('成功：5G WiFi查询成功', channel=8)
        hidden_ai = '[AI对话] 会话12345678模型请求成功'
        wifi = wifi_message('频段=2.4G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）')
        messages = [hidden1, wifi_message('开始获取WiFi信息'), command8, hidden_ai, hidden8, error1, wifi, success8]
        for message in messages:
            LineCheckAssistant._log(self.context, message)
        expected = [hidden1, command8, hidden_ai, hidden8, error1, format_main_log_message(wifi), success8]
        self.assertEqual([line[20:] for line in self.context.log_path.read_text(encoding='utf-8').splitlines()], expected)
        shown = [call.args[1].rstrip('\n') for call in self.context.log_text.insert.call_args_list
                 if len(call.args) < 3 or call.args[2] != 'time']
        self.assertEqual(shown, [command8, error1, format_main_log_message(wifi), success8])
        self.context.log_text.insert.assert_any_call('end', error1 + '\n', 'error')
        self.context.log_text.insert.assert_any_call('end', success8 + '\n', 'success')

    def test_multiline_command_error_and_explicit_tag_are_preserved_in_both_sinks(self):
        command = dut_message("TX UBUS bbfdm.set paths=[\n{'SSID': 'network'}\n]")
        error = dut_message('失败：解析异常\n完整错误详情')
        for message in (command, error):
            LineCheckAssistant._log(self.context, message, tag='muted')
            self.context.log_text.insert.assert_any_call('end', message + '\n', 'muted')
        saved = self.context.log_path.read_text(encoding='utf-8')
        for message in (command, error):
            self.assertIn(message + '\n', saved)

    def test_real_tk_both_themes_keep_commands_colors_and_raw_file(self):
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        style = ttk.Style(root)
        original_theme = style.theme_use()
        self.addCleanup(root.update_idletasks)
        self.addCleanup(lambda: style.theme_use(original_theme))
        hidden = dut_message(dut_details()[10])
        visible = [(dut_message('TX UBUS bbfdm.get path=Device.WiFi.Radio.2.'), ''),
                   (dut_message('成功：2.4G WiFi查询成功'), 'success'),
                   (dut_message('失败：连接超时'), 'error'),
                   (dut_message('请稍后重试'), 'warning')]
        for theme in ('vista', 'clam'):
            with self.subTest(theme=theme):
                style.theme_use(theme)
                widget = tk.Text(root, state='disabled')
                self.addCleanup(widget.destroy)
                self.context.log_text = widget
                LineCheckAssistant._configure_log_tags(self.context)
                LineCheckAssistant._log(self.context, hidden)
                for message, _ in visible:
                    LineCheckAssistant._log(self.context, message)
                root.update_idletasks()
                self.assertNotIn(hidden, widget.get('1.0', 'end-1c'))
                self.assertNotIn('device-password', widget.get('1.0', 'end-1c'))
                for row, (message, tag) in enumerate(visible, start=1):
                    self.assertEqual(widget.get(f'{row}.10', f'{row}.end'), message)
                    self.assertIn('time', widget.tag_names(f'{row}.0'))
                    if tag:
                        self.assertIn(tag, widget.tag_names(f'{row}.10'))
                self.assertEqual(widget.cget('state'), 'disabled')
        saved = self.context.log_path.read_text(encoding='utf-8')
        for message in [hidden] + [item[0] for item in visible]:
            self.assertEqual(saved.count(message), 2)


def ai_json(event, value):
    return '[AI对话] ' + event + '：' + json.dumps(value, ensure_ascii=False)


def action_record(name='run_dut_command'):
    return dict(id='12345678' * 4, name=name,
                target=dict(channel=2, host='192.168.1.1', port='COM2', password='device-password'),
                params=dict(command='echo 请求模型；失败', cwd='C:/work', path='C:/work/sample.txt', content='file-body'),
                assessment=dict(risk='dangerous', reason='首次设备登录，请确认目标'),
                preview=dict(after='file-body'), fingerprint='internal-fingerprint')


class AiMainLogFilterTests(unittest.TestCase):
    def test_routine_messages_are_hidden(self):
        for body in (
            '会话12345678请求模型（第2次交互）；估算输入1234 Token',
            '会话12345678模型请求成功',
            '会话12345678最近请求用量：输入12，输出3，合计15 Token；接口返回',
            '会话12345678最近请求用量：输入12，输出3，合计15 Token；UTF-8字节估算',
            '会话12345678开始读取模型上下文容量：model-v1',
            '会话12345678上下文容量：100000 Token，来源=手动填写；输入按UTF-8字节保守估算，输出预留4096 Token及5%余量',
            '会话12345678上下文容量：100000 Token，来源=模型接口（缓存）；输入按UTF-8字节保守估算，输出预留4096 Token及5%余量',
            '会话12345678上下文容量：未知容量：最近50轮 / 100000字符',
            '会话12345678独立风险审查请求；模型=model-v1，估算输入240 Token',
            '操作12345678风险审查开始：run_dut_command',
        ):
            with self.subTest(body=body):
                self.assertIsNone(format_main_log_message('[AI对话] ' + body))

    def test_collection_summary_keeps_reason_permission_and_recipient(self):
        original = ('[AI对话] 会话12345678采集状态：目标已失效，只分析留存材料；权限=帮我批准；'
                    '真实诊断信息（含材料中的账号、密码）发送至自定义 / https://example.test/v1；请求工具：read_dut_state, run_local_command')
        self.assertEqual(format_main_log_message(original),
                         '[AI对话] 会话12345678采集状态：目标已失效，只分析留存材料；权限=帮我批准；发送至=自定义 / https://example.test/v1')

    def test_unknown_formats_and_errors_are_preserved(self):
        for body in (
            '模型容量读取失败（TimeoutError）；保留缓存并使用后备规则',
            '会话12345678上下文容量：读取异常，待核查',
            '会话12345678上下文裁剪：省略2轮完整历史',
            '会话12345678服务返回上下文超限；旧历史减半，第1/2次重试，不重复执行工具',
            '会话12345678请求模型失败：网络超时',
            '会话12345678请求模型（第1次交互）；估算输入123 Token；新格式',
            '会话12345678模型请求成功\n但后续解析失败',
            '会话12345678停止本轮；原挂测继续，等待必要清理',
            '会话12345678本轮结束；恢复状态：恢复待完成',
            '会话12345678工具跳过/失败：read_dut_state；目标正在占用',
            '会话12345678权限切换为完全访问；操作员已确认危险操作范围；跳过独立审查',
            '会话12345678完全访问授权失效：用户停止',
            '未来新增的阶段',
        ):
            message = '[AI对话] ' + body
            with self.subTest(body=body):
                self.assertEqual(format_main_log_message(message), message)

    def test_command_login_and_non_chat_ai_text_are_opaque(self):
        for message in (
            '[AI Debug][telnet] TX：echo 请求模型；模型请求成功',
            '[AI对话] [AI执行] PC TX（cwd=C:/work，超时=60秒）：echo 最近请求用量\nWrite-Output 失败',
            '[AI Debug] TX 登录用户名：会话12345678模型请求成功',
            '[AI对话] [AI Debug] TX 登录密码：请求工具：secret',
            '[AI网络检查] PC TX：ping -n 4 192.168.1.1',
            '[AI采集] 恢复待完成；下次连接核查，禁止通过重启恢复',
            '[AI诊断] 开始：通道2，厂商/模型，light',
            '[AI诊断] 完成，报告已保存；AI原因假设尚未人工确认',
            '[旧工具Logs][INFO] [AI对话] 会话12345678模型请求成功',
            '[AI新功能] 请求失败',
        ):
            with self.subTest(message=message):
                self.assertEqual(format_main_log_message(message), message)
        self.assertFalse(is_ai_log_message('[旧工具Logs][INFO] [AI对话] 测试'))
        self.assertTrue(is_ai_log_message('[AI对话] [AI Debug][telnet] TX：ls'))
        self.assertTrue(is_ai_log_message('[AI Debug][telnet] TX：ls'))

    def test_wait_approval_is_summarized_without_file_contents(self):
        result = format_main_log_message(ai_json('等待操作员批准', action_record()))
        self.assertEqual(result, '[AI对话] 等待操作员批准：run_dut_command；操作12345678；原因=首次设备登录，请确认目标')

    def test_execution_summary_identifies_target_or_local_path(self):
        for name in ('run_dut_command', 'run_local_command', 'write_local_file', 'read_serial_status'):
            with self.subTest(name=name):
                result = format_main_log_message(ai_json('实际执行操作', action_record(name)))
                self.assertIn(name + '；操作12345678', result)
                self.assertIn('通道2；目标=192.168.1.1' if name == 'run_dut_command' else '本机', result)
                if name == 'read_serial_status':
                    self.assertIn('串口=COM2', result)
                self.assertNotIn('file-body', result)
                self.assertNotIn('internal-fingerprint', result)
                self.assertNotIn('device-password', result)

    def test_review_keeps_risk_and_reason_without_json(self):
        for risk in ('ordinary', 'dangerous', 'unknown', 'blocked'):
            result = format_main_log_message(ai_json('操作12345678审查结果', dict(risk=risk, reason='清理尚未完成')))
            self.assertEqual(result, f'[AI对话] 操作12345678审查结果：{risk}；原因=清理尚未完成')
            self.assertEqual(ai_main_log_tag(result), '' if risk == 'ordinary' else 'warning')

    def test_result_preserves_status_exit_error_and_uncertainty(self):
        for state, label, color in (
            ('succeeded', '执行完成', 'success'), ('failed', '执行失败', 'error'),
            ('unknown', '结果待核实', 'warning'), ('cancelled', '已取消', 'warning'),
            ('blocked', '已拦截', 'warning'), ('rejected', '已拒绝', 'warning'),
        ):
            with self.subTest(state=state):
                message = ai_json('操作12345678结束', dict(action_state=state, exit_code=7, status='timed_out',
                    notice='完成收尾也不代表设备业务成功', stdout='full-output\nline2', dispatched=True))
                result = format_main_log_message(message)
                self.assertIn(label + '（' + state + '）', result)
                self.assertIn('进程状态=timed_out；返回码=7', result)
                self.assertIn('说明=完成收尾也不代表设备业务成功', result)
                self.assertNotIn('full-output', result)
                self.assertEqual(ai_main_log_tag(result), color)

    def test_dut_shell_return_does_not_claim_business_success(self):
        notice = '命令返回Shell提示符；业务是否成功须依据实际输出或后续查询核对'
        result = format_main_log_message(ai_json('操作12345678结束', dict(action_state='succeeded', notice=notice, output='raw-shell-output')))
        self.assertIn(notice, result)
        self.assertNotIn('执行成功', result)
        self.assertNotIn('业务成功', result)
        self.assertNotIn('raw-shell-output', result)

    def test_failure_summary_includes_errors_and_cleanup_warning(self):
        result = format_main_log_message(ai_json('操作12345678结束', dict(action_state='failed', error='未下发，连接失败',
            dispatched=False, stderr='first-error\n' + 'long-output' * 100, process_cleanup_confirmed=False, truncated=True)))
        for text in ('错误=未下发，连接失败', '未下发操作命令', '进程清理未确认', 'first-error', '完整输出见主日志文件', '原始输出已截断'):
            self.assertIn(text, result)
        self.assertNotIn('long-output', result)
        self.assertEqual(ai_main_log_tag(result), 'error')
        result = format_main_log_message(ai_json('操作12345678结束', dict(action_state='unknown', process_cleanup_confirmed=False)))
        self.assertEqual(ai_main_log_tag(result), 'warning')

    def test_long_single_line_stderr_has_explicit_detail_location(self):
        result = format_main_log_message(ai_json('操作12345678结束', dict(action_state='failed', stderr='x' * 400)))
        self.assertIn('x' * 240 + '…（完整输出见主日志文件）', result)
        self.assertNotIn('x' * 241, result)

    def test_malformed_json_missing_fields_and_new_states_fall_back(self):
        for event, value in (
            ('等待操作员批准', {}), ('实际执行操作', dict(name='test')),
            ('操作12345678结束', dict(action_state='new-state', error='新格式错误')),
            ('操作12345678结束', dict(action_state=['failed'])),
            ('操作12345678审查结果', dict(risk='new-risk', reason='说明')),
            ('实际执行操作', []), ('操作12345678结束', None),
        ):
            message = ai_json(event, value)
            with self.subTest(message=message):
                self.assertEqual(format_main_log_message(message), message)
        message = '[AI对话] 实际执行操作：{"name": "broken"'
        self.assertEqual(format_main_log_message(message), message)
        self.assertIsNone(ai_main_log_tag('[AI对话] 操作12345678结束：新格式（future）'))


class AiMainLogPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.context = SimpleNamespace(log_path=Path(temporary.name) / 'main.log', log_text=Mock())
        self.context._log_tag_for = lambda text: LineCheckAssistant._log_tag_for(self.context, text)

    def test_hidden_ai_message_is_saved_without_touching_ui(self):
        message = '[AI对话] 会话12345678模型请求成功'
        LineCheckAssistant._log(self.context, message)
        self.assertEqual(self.context.log_text.mock_calls, [])
        self.assertEqual(self.context.log_path.read_text(encoding='utf-8')[20:], message + '\n')

    def test_summary_and_full_json_are_written_to_separate_sinks(self):
        message = ai_json('实际执行操作', action_record('write_local_file'))
        LineCheckAssistant._log(self.context, message)
        expected = format_main_log_message(message)
        self.context.log_text.insert.assert_any_call('end', expected + '\n')
        self.assertEqual(self.context.log_path.read_text(encoding='utf-8')[20:], message + '\n')
        self.assertIn('file-body', self.context.log_path.read_text(encoding='utf-8'))

    def test_result_color_comes_from_state_and_explicit_tag_wins(self):
        message = ai_json('操作12345678结束', dict(action_state='unknown', stdout='成功：完成'))
        expected = format_main_log_message(message)
        LineCheckAssistant._log(self.context, message)
        self.context.log_text.insert.assert_any_call('end', expected + '\n', 'warning')
        LineCheckAssistant._log(self.context, message, tag='muted')
        self.context.log_text.insert.assert_any_call('end', expected + '\n', 'muted')
        self.assertEqual(self.context.log_path.read_text(encoding='utf-8').count(message), 2)

    def test_model_secret_stays_filtered_before_display_and_file(self):
        redactor = DiagnosticRedactor(['model-secret'])
        original = ai_json('实际执行操作', action_record('write_local_file'))
        message = redactor.text(original.replace('file-body', 'model-secret'))
        service = SimpleNamespace(redactor=redactor, emit_sink=lambda line: LineCheckAssistant._log(self.context, line))
        AiDiagnosticService.emit(service, original.replace('file-body', 'model-secret'))
        saved = self.context.log_path.read_text(encoding='utf-8')
        self.assertNotIn('model-secret', saved)
        self.assertTrue(saved.endswith(message + '\n'))
        self.assertNotIn('model-secret', str(self.context.log_text.insert.call_args_list))

    def test_mixed_sequence_keeps_hidden_ai_raw_and_wifi_summary(self):
        messages = [wifi_message('开始获取WiFi信息'), '[AI对话] 会话12345678模型请求成功',
                    '[AI对话] [AI Debug][telnet] TX：echo 请求模型',
                    ai_json('操作12345678结束', dict(action_state='failed', error='连接失败', output='raw-output')),
                    wifi_message('频段=2.4G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）')]
        for message in messages:
            LineCheckAssistant._log(self.context, message)
        saved = [line[20:] for line in self.context.log_path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(saved, messages[1:4] + [format_main_log_message(messages[4])])
        rendered = [call.args[1].rstrip('\n') for call in self.context.log_text.insert.call_args_list
                    if len(call.args) < 3 or call.args[2] != 'time']
        self.assertEqual(rendered, [format_main_log_message(message) for message in messages[2:]])

    def test_real_tk_both_themes_render_summary_and_preserve_full_file(self):
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        style = ttk.Style(root)
        original_theme = style.theme_use()
        self.addCleanup(root.update_idletasks)
        self.addCleanup(lambda: style.theme_use(original_theme))
        hidden = '[AI对话] 会话12345678最近请求用量：输入12，输出3，合计15 Token；接口返回'
        result = ai_json('操作12345678结束', dict(action_state='unknown', stdout='完整输出：成功', notice='结果待核实'))
        command = '[AI对话] [AI Debug][telnet] TX：echo 请求模型\nprintf 完成'
        for theme in ('vista', 'clam'):
            with self.subTest(theme=theme):
                style.theme_use(theme)
                widget = tk.Text(root, state='disabled')
                self.addCleanup(widget.destroy)
                widget.tag_configure('warning', foreground='#c07000')
                self.context.log_text = widget
                for message in (hidden, result, command):
                    LineCheckAssistant._log(self.context, message)
                root.update_idletasks()
                shown = widget.get('1.0', 'end-1c')
                self.assertNotIn('最近请求用量', shown)
                self.assertNotIn('完整输出：成功', shown)
                self.assertIn(format_main_log_message(result), shown)
                self.assertIn(command, shown)
                self.assertIn('warning', widget.tag_names('1.10'))
                self.assertEqual(widget.cget('state'), 'disabled')
        saved = self.context.log_path.read_text(encoding='utf-8')
        for message in (hidden, result, command):
            self.assertEqual(saved.count(message), 2)


if __name__ == '__main__':
    unittest.main()

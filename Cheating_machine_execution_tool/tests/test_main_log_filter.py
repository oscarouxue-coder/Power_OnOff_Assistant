"""WiFi 显示摘要与真实主日志落盘边界，无设备或网络操作。"""
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from line_check_assistant.app import LineCheckAssistant
from src.services.legacy_power_test_service import _ForwardingLegacyLogger
from src.ui.main_log_filter import format_main_log_message


def wifi_message(body, *, level='INFO', channel=2, cycle=4):
    return f'[旧工具Logs][{level}] [WiFi测试] 通道{channel} 第{cycle}轮 {body}'


class MainLogFilterTests(unittest.TestCase):
    def test_other_logs_and_dut_queries_are_unchanged(self):
        for message in (
            '[DUT配置][2.4G WiFi查询] TX UBUS bbfdm.get path=Device.WiFi.Radio.',
            '[旧工具Logs][INFO] Ping 成功：源网卡 192.168.1.115 → 目标样机 192.168.1.1',
            '[旧工具Logs][ERROR] 通道 2 登录telnet失败',
            '[WiFi测试] 未经过正式日志入口的消息',
            '[旧工具Logs][INFO] *******通道 【2】 开始第4次测试*******',
        ):
            with self.subTest(message=message):
                self.assertEqual(format_main_log_message(message), message)

    def test_known_normal_details_are_hidden(self):
        for stage in (
            '下发只读命令：bbfdmd -c get Device.WiFi.SSID.1.SSID',
            '只读命令返回（WiFi回显隐藏）',
            '目标已读取：频段=2.4G Radio=1 SSID=test BSSID=aa:bb:cc:dd:ee:ff',
            '双频合一状态=关闭',
            '等待网卡 81.0秒；当前占用=通道1 第1轮',
            '下发无线扫描',
            '目标SSID=test BSSID=aa:bb:cc:dd:ee:ff 频段=2.4G 认证=WPA2-PSK 加密=AES',
            '等待10秒后重试',
            '无线Ping：等待无线IPv4地址（最长30秒）',
            '无线DNS查询：目标=example.com 接口索引=17',
            '无线DNS结果：203.0.113.1, 203.0.113.2；本项使用第一个IPv4',
            '无线Ping下发：第1/4包，192.168.1.240 → 203.0.113.1，超时2秒',
            '无线Ping第1/4包：回复 594.00ms',
            '无线Ping第4/4包：超时',
            '成功：本项无线测试通过',
            '下发断开临时连接；不删除电脑原有无线配置',
            '临时连接已清理',
        ):
            with self.subTest(stage=stage):
                self.assertIsNone(format_main_log_message(wifi_message(stage)))
                self.assertIsNone(format_main_log_message(wifi_message(
                    '网卡=Intel(R) Wi-Fi 7 BE200 320MHz 频段=2.4G ' + stage)))

    def test_progress_actions_and_results_are_kept(self):
        for stage in (
            '开始获取WiFi信息',
            '入队；当前占用=通道1 第1轮',
            '取得使用权；等待 83.2秒',
            '实际无线网卡=aWLAN GUID=test-guid ifIndex=17',
            '频段=2.4G 第 4/4 次连接，扫描/连接/核验共约20秒；认证来源=auto',
            '频段=5G 下发目标BSSID临时连接配置（不保存或覆盖用户配置）',
            '频段=5G 连接核验成功：SSID=test BSSID=aa:bb:cc:dd:ee:ff 实际频段=5G 认证=WPA2-PSK 加密=AES',
            '频段=2.4G 无线Ping开始：网卡=aWLAN ifIndex=17 源IP=192.168.1.240 目标=example.com 实际IP=203.0.113.1',
            '频段=2.4G 无线Ping汇总：发送4 接收3 丢包率=25% 时延min/avg/max=594.00/849.00/1250.00ms 通过',
            '释放使用权',
        ):
            with self.subTest(stage=stage):
                output = format_main_log_message(wifi_message(stage))
                self.assertEqual(output, '[WiFi] 通道2 第4轮 ' + stage)

    def test_card_name_with_spaces_is_removed_only_from_recognized_stages(self):
        for stage in ('入队；当前占用=无', '取得使用权；等待 30.4秒',
                      '实际无线网卡=aWLAN GUID=test-guid ifIndex=17',
                      '释放使用权', '频段=5G 连接核验成功：SSID=my network'):
            with self.subTest(stage=stage):
                self.assertEqual(format_main_log_message(wifi_message(
                    '网卡=Intel(R) Wi-Fi 7 BE200 320MHz ' + stage)),
                    '[WiFi] 通道2 第4轮 ' + stage)
        unknown = '网卡=Intel(R) Wi-Fi 7 BE200 320MHz 新的驱动提示'
        self.assertEqual(format_main_log_message(wifi_message(unknown)),
                         '[WiFi] 通道2 第4轮 ' + unknown)

    def test_errors_retries_cancel_skip_and_unknown_messages_survive(self):
        for stage in (
            '频段=2.4G 第 3/4 次未通过：扫描未发现目标BSSID或频段不符',
            '测试环境异常：2.4G：无线DNS没有返回IPv4地址（错误码9005）',
            '频段=5G 无线Ping汇总：发送4 接收0 丢包率=100% 失败',
            '取消：用户停止WiFi测试', '取消等待/执行', '跳过：2.4G、5G均未启用',
            '频段=5G 跳过：无线Ping未启用',
            '临时连接已清理但驱动报告异常', '下发无线扫描失败',
            '无线DNS结果：读取失败', '新版本增加的阶段',
        ):
            with self.subTest(stage=stage):
                self.assertIn(stage, format_main_log_message(wifi_message(stage)))

    def test_warning_and_error_details_are_not_hidden(self):
        for level in ('WARNING', 'ERROR'):
            output = format_main_log_message(wifi_message('下发无线扫描', level=level))
            self.assertEqual(output, f'[WiFi][{level}] 通道2 第4轮 下发无线扫描')

    def test_credentials_are_opaque_plaintext_even_with_filter_keywords(self):
        body = ('WiFi信息：2.4G SSID=网卡=network，密码=异常 成功：本项无线测试通过；'
                '5G SSID=频段=5G，密码=pa ss网卡=word')
        self.assertEqual(format_main_log_message(wifi_message(body)),
                         '[WiFi] 通道2 第4轮 ' + body)

    def test_unified_band_and_resumed_cycle_are_preserved(self):
        self.assertEqual(format_main_log_message(wifi_message(
            '网卡=Wi-Fi 2 频段=合一网络 第 1/4 次连接，认证来源=auto',
            channel=7, cycle=3)),
            '[WiFi] 通道7 第3轮 频段=合一网络 第 1/4 次连接，认证来源=auto')


class MainLogPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.context = SimpleNamespace(log_path=Path(temporary.name) / 'main.log', log_text=Mock())
        self.context._log_tag_for = lambda text: LineCheckAssistant._log_tag_for(self.context, text)

    def test_hidden_messages_still_write_original_once_without_touching_text(self):
        message = wifi_message('频段=2.4G 无线Ping第4/4包：超时')
        LineCheckAssistant._log(self.context, message)
        self.assertEqual(self.context.log_text.mock_calls, [])
        lines = self.context.log_path.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(' ' + message))

    def test_visible_message_preserves_original_on_disk_and_error_color(self):
        message = wifi_message('网卡=Intel(R) Wi-Fi 7 BE200 320MHz 测试环境异常：DNS错误码9005')
        LineCheckAssistant._log(self.context, message)
        self.context.log_text.insert.assert_any_call(
            'end', '[WiFi] 通道2 第4轮 测试环境异常：DNS错误码9005\n', 'error')
        self.assertTrue(self.context.log_path.read_text(encoding='utf-8').endswith(message + '\n'))
        self.assertEqual(len(self.context.log_path.read_text(encoding='utf-8').splitlines()), 1)

    def test_explicit_tag_and_other_log_text_remain_intact(self):
        message = '[DUT配置] WiFi查询成功'
        LineCheckAssistant._log(self.context, message, tag='muted')
        self.context.log_text.insert.assert_any_call('end', message + '\n', 'muted')
        self.assertTrue(self.context.log_path.read_text(encoding='utf-8').endswith(message + '\n'))

    def test_success_color_comes_from_original_connection_result(self):
        message = wifi_message('频段=5G 连接核验成功：SSID=test')
        LineCheckAssistant._log(self.context, message)
        self.context.log_text.insert.assert_any_call(
            'end', '[WiFi] 通道2 第4轮 频段=5G 连接核验成功：SSID=test\n', 'success')

    def test_real_forwarded_credentials_are_plaintext_in_ui_and_file_on_resume(self):
        messages = queue.Queue()
        logger = _ForwardingLegacyLogger(messages, ('sample-password', 'other-secret'))
        # 现有执行/续跑入口各在首次读取后调用此适配器；显示层不缓存或吞掉续跑摘要。
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

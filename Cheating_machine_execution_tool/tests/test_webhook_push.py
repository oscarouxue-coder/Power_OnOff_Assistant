"""Webhook自动适配专项；只使用模拟HTTP与隔离临时配置。"""
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from src.core.feishu_robot import send_text
from src.core.webhook_target import detect_platform
from src.services.message_push_config_service import DEFAULTS, MessagePushConfigService, send_test_message
from src.ui.message_push_tab import MessagePushTab
from tk_test_windows import OffscreenTkWindows
from webhook_fakes import DINGTALK, FEISHU, response


class WebhookTargetTests(unittest.TestCase):
    def test_supported_urls(self):
        for url, name in ((FEISHU, 'feishu'), (DINGTALK, 'dingtalk'),
                          ('  ' + FEISHU + '  ', 'feishu'),
                          (FEISHU.replace('.cn/', '.cn:443/'), 'feishu'),
                          (DINGTALK + '&timestamp=old&sign=old', 'dingtalk')):
            self.assertEqual(detect_platform(url), name)

    def test_invalid_and_deceptive_urls_are_rejected_before_network(self):
        urls = ('', 'private-secret', FEISHU.replace('https:', 'http:'),
                FEISHU.replace('.cn/', '.cn.evil.invalid/'),
                FEISHU.replace('.cn/', '.cn:444/'), FEISHU.replace('.cn/', '.cn:bad/'),
                FEISHU.replace('open.feishu.cn', 'user:private-secret@open.feishu.cn'),
                FEISHU + '#private-secret', FEISHU + '?token=private-secret',
                FEISHU.rsplit('/', 1)[0] + '/', FEISHU + '/extra', FEISHU + '\nsecret',
                'https://open.feishu.cn/other/demo-token',
                DINGTALK.replace('access_token=demo-token', 'access_token='),
                DINGTALK.replace('oapi.dingtalk.com', 'oapi.dingtalk.com.evil.invalid'))
        with patch('src.core.feishu_robot.build_opener') as build:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                    send_text(url, '', 'text')
                self.assertNotIn('private-secret', str(caught.exception))
            build.assert_not_called()


class FeishuRobotTests(unittest.TestCase):
    def test_signed_message_matches_official_algorithm_and_mentions_all(self):
        opener = response({'code': 0})
        with patch('src.core.feishu_robot.build_opener', return_value=opener), \
             patch('src.core.feishu_robot.time.time', return_value=1700000000.9):
            send_text(FEISHU, ' demo-secret ', '中文测试', at_all=True)
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        expected = base64.b64encode(hmac.new(b'1700000000\ndemo-secret', b'', hashlib.sha256).digest()).decode()
        self.assertEqual(payload, {'msg_type': 'text',
                                  'content': {'text': '中文测试\n<at user_id="all">所有人</at>'},
                                  'timestamp': '1700000000', 'sign': expected})
        self.assertEqual(request.full_url, FEISHU)
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
        opener.open.assert_called_once()

    def test_unsigned_message_has_no_signature_or_mention(self):
        opener = response({'code': 0})
        with patch('src.core.feishu_robot.build_opener', return_value=opener):
            send_text(FEISHU, ' ', 'test')
        self.assertEqual(json.loads(opener.open.call_args.args[0].data),
                         {'msg_type': 'text', 'content': {'text': 'test'}})

    def test_errors_are_sanitized_and_never_retried(self):
        for body, status in (({'code': 19021, 'msg': 'private-secret'}, 200),
                             ({'code': False}, 200), ({}, 200), ([], 200),
                             (b'private-secret', 200), (b'\xff', 200),
                             (b'x' * 65537, 200), ({'code': 0}, 503)):
            with self.subTest(status=status, body_type=type(body)):
                opener = response(body, status)
                with patch('src.core.feishu_robot.build_opener', return_value=opener), \
                     self.assertRaises(RuntimeError) as caught:
                    send_text(FEISHU, '', 'test')
                self.assertNotIn('private-secret', str(caught.exception))
                self.assertNotIn('demo-token', str(caught.exception))
                opener.open.assert_called_once()

    def test_timeout_and_http_errors_are_sanitized(self):
        for error in (TimeoutError('private-secret'), HTTPError(FEISHU, 429, 'private-secret', {}, None)):
            opener = Mock()
            opener.open.side_effect = error
            with patch('src.core.feishu_robot.build_opener', return_value=opener), \
                 self.assertRaises(RuntimeError) as caught:
                send_text(FEISHU, 'secret', 'text')
            self.assertIn('飞书', str(caught.exception))
            self.assertNotIn('private-secret', str(caught.exception))
            self.assertNotIn('demo-token', str(caught.exception))
            opener.open.assert_called_once()

    def test_redirects_are_disabled(self):
        from src.core.feishu_robot import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))


class WebhookPushIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'project.ini'
        self.path.write_text('[project_info]\nproject_name = 已保存项目\n', encoding='utf-8')
        self.values = dict(DEFAULTS, webhook=FEISHU, secret='demo-secret', at_all='1')
        self.log = Mock()

    def legacy(self):
        path = Path(__file__).resolve().parents[1] / 'Auto_power_on_off_tool/common/dingtalk_send_message.py'
        spec = importlib.util.spec_from_file_location('_test_webhook_legacy', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'config.config_driver': Mock()}):
            spec.loader.exec_module(module)
        sender = module.DingTalk()
        sender.log = self.log
        sender.cf.read_ini.return_value = '1'
        sender.cf.read_config_file.return_value = self.values
        return module, sender

    def test_manual_feishu_uses_snapshot_saved_name_and_returns_platform_when_disabled(self):
        opener = response({'code': 0})
        with patch('src.core.feishu_robot.build_opener', return_value=opener), \
             patch('src.services.message_push_config_service.send_text') as ding:
            self.assertEqual(send_test_message(self.values, self.path, log=self.log), '飞书')
        payload = json.loads(opener.open.call_args.args[0].data)
        self.assertIn('项目：已保存项目', payload['content']['text'])
        self.assertIn('飞书机器人推送正常', payload['content']['text'])
        ding.assert_not_called()
        self.assertNotIn('demo-token', str(self.log.call_args_list))
        self.assertNotIn('demo-secret', str(self.log.call_args_list))
        self.assertIn('飞书', str(self.log.call_args_list))

    def test_each_send_reloads_project_name_and_rejects_empty_name(self):
        with patch('src.services.message_push_config_service.send_feishu_text') as send:
            for name in ('项目一', '项目二'):
                self.path.write_text(f'[project_info]\nproject_name = {name}\n', encoding='utf-8')
                send_test_message(self.values, self.path)
                self.assertIn(name, send.call_args.args[2])
            send.reset_mock()
            self.path.write_text('[project_info]\nproject_name = \n', encoding='utf-8')
            with self.assertRaises(ValueError):
                send_test_message(self.values, self.path)
            send.assert_not_called()

    def test_config_round_trip_without_new_keys_or_network(self):
        config = MessagePushConfigService(self.path.parent / 'config.ini')
        with patch('src.core.feishu_robot.build_opener') as build:
            for webhook in (FEISHU, DINGTALK, ''):
                values = dict(self.values, webhook=webhook)
                config.save(values)
                self.assertEqual(config.load(), values)
                self.assertEqual(set(config.load()), set(DEFAULTS))
            build.assert_not_called()

    def test_formal_completion_and_failure_use_feishu_and_never_read_remote_credentials(self):
        module, sender = self.legacy()
        for normal in (0, 1):
            opener = response({'code': 0})
            with patch.object(module, 'Path', return_value=self.path), \
                 patch.object(module.requests, 'post') as ding, \
                 patch('src.core.feishu_robot.build_opener', return_value=opener):
                self.assertIs(sender.webhook_send_message('旧项目', '测试详情', normal), True)
            text = json.loads(opener.open.call_args.args[0].data)['content']['text']
            self.assertIn('已保存项目', text)
            self.assertIn('完成' if normal else '异常', text)
            self.assertIn('测试详情', text)
            self.assertIn('<at user_id="all">', text)
            self.assertNotIn('远程客户端', text)
            ding.assert_not_called()
        self.assertTrue(all(call.args[0] != 'remote_config' for call in sender.cf.read_ini.call_args_list))
        self.assertNotIn('demo-secret', str(self.log.call_args_list))
        self.assertNotIn('demo-token', str(self.log.call_args_list))

    def test_formal_disabled_skips_http_and_project_read(self):
        module, sender = self.legacy()
        sender.cf.read_ini.return_value = '0'
        with patch.object(module, 'load_push_project_name') as load, \
             patch('src.core.feishu_robot.build_opener') as build:
            self.assertIs(sender.webhook_send_message('old', 'text'), True)
            load.assert_not_called()
            build.assert_not_called()

    def test_formal_feishu_rejection_returns_failure_and_logs_actual_platform(self):
        module, sender = self.legacy()
        with patch.object(module, 'Path', return_value=self.path), \
             patch('src.core.feishu_robot.build_opener', return_value=response({'code': 19021, 'msg': 'demo-secret'})):
            result = sender.webhook_send_message('old', 'text')
        self.assertIsInstance(result, RuntimeError)
        self.assertIn('19021', str(result))
        self.assertIn('正式发送失败', str(self.log.call_args_list))
        self.assertNotIn('demo-secret', str(self.log.call_args_list))

    def test_invalid_webhook_prevents_both_transports(self):
        self.values['webhook'] = 'https://open.feishu.cn.evil.invalid/private-secret'
        module, sender = self.legacy()
        with patch.object(module, 'Path', return_value=self.path), \
             patch('src.core.feishu_robot.build_opener') as feishu, \
             patch.object(module.requests, 'post') as ding:
            result = sender.webhook_send_message('old', 'text')
            self.assertIsInstance(result, ValueError)
            with self.assertRaises(ValueError):
                send_test_message(self.values, self.path)
            feishu.assert_not_called()
            ding.assert_not_called()
        self.assertNotIn('private-secret', str(self.log.call_args_list))

    def test_ui_success_uses_worker_snapshot_even_if_page_changes(self):
        with OffscreenTkWindows() as windows:
            root = tk.Tk()
            try:
                tab = MessagePushTab(ttk.Notebook(root), self.values, lambda *args: None,
                                     background='#eef2f5', foreground='black', project_config_path=self.path)
                snapshot = tab.capture()
                tab.variables['webhook'].set(DINGTALK)
                with patch('src.core.feishu_robot.build_opener', return_value=response({'code': 0})):
                    tab._send_worker(snapshot)
                while not tab.results.empty():
                    tab._poll_result()
                self.assertIn('飞书已接受', tab.status.get())
                self.assertEqual(tab.variables['webhook'].get(), DINGTALK)
                self.assertFalse(tab.running)
                self.assertEqual(str(tab.test_button.cget('state')), 'normal')
                windows.assert_offscreen()
            finally:
                root.destroy()

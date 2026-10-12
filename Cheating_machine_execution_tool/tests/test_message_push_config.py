import tempfile
import importlib.util
import sys
import json
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from src.services.message_push_config_service import DEFAULTS, MessagePushConfigService
from src.ui.message_push_tab import MessagePushTab
from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.test_item_config_store import TestProjectConfig
from src.core.dingtalk_robot import send_text
from src.services.message_push_config_service import send_test_message, load_push_project_name


class MessagePushSendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project_path = Path(self.tmp.name) / 'test_project_config.ini'
        self.project_path.write_text('[project_info]\nproject_name = 中文项目\n', encoding='utf-8-sig')

    def legacy_sender(self):
        path = Path(__file__).resolve().parents[1] / 'Auto_power_on_off_tool/common/dingtalk_send_message.py'
        spec = importlib.util.spec_from_file_location('_test_legacy_dingtalk', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'config.config_driver': Mock()}):
            spec.loader.exec_module(module)
        sender = module.DingTalk()
        sender.log = Mock()
        # 旧项目名与磁盘项目名不同，证明发送不再采用调用参数或旧配置。
        sender.cf.read_ini.side_effect = lambda section, key, **kwargs: {
            'dingtalk_flag': '1', 'test_project': '旧项目',
            'remote_tool_name': 'tool', 'remote_identification_code': 'id',
            'remote_verification_code': 'code',
        }[key]
        sender.cf.read_config_file.return_value = dict(
            webhook='https://oapi.dingtalk.com/robot/send?access_token=demo',
            secret='demo-secret', at_all='1')
        return module, sender

    def test_formal_completion_and_failure_use_saved_name_in_title_and_body(self):
        module, sender = self.legacy_sender()
        with patch.object(module, 'Path', return_value=self.project_path), \
             patch.object(module.requests, 'post') as post:
            post.return_value.json.return_value = {'errcode': 0}
            for normal in (0, 1):
                self.assertIs(sender.webhook_send_message('旧项目', '测试详情', normal), True)
                data = post.call_args.kwargs['json']
                for value in data['markdown'].values():
                    self.assertIn('中文项目', value)
                    self.assertNotIn('旧项目', value)
                    self.assertNotIn('NP2659GB', value)
                self.assertTrue(data['at']['isAtAll'])
            self.assertEqual(post.call_count, 2)
        self.assertNotIn('demo-secret', str(sender.log.call_args_list))
        self.assertNotIn('access_token=', str(sender.log.call_args_list))

    def test_formal_disabled_skips_name_read_and_http(self):
        module, sender = self.legacy_sender()
        sender.cf.read_ini.side_effect = None
        sender.cf.read_ini.return_value = '0'
        with patch.object(module, 'load_push_project_name') as load, \
             patch.object(module.requests, 'post') as post:
            self.assertIs(sender.webhook_send_message('旧项目', '详情'), True)
            load.assert_not_called()
            post.assert_not_called()

    def test_each_send_reloads_saved_name_and_ignores_unsaved_page_name(self):
        module, sender = self.legacy_sender()
        with patch.object(module, 'Path', return_value=self.project_path), \
             patch.object(module.requests, 'post') as post, \
             patch('src.services.message_push_config_service.send_text') as send:
            post.return_value.json.return_value = {'errcode': 0}
            for name in ('中文项目', '新的项目'):
                self.project_path.write_text(f'[project_info]\nproject_name = {name}\n', encoding='utf-8')
                send_test_message(dict(DEFAULTS, project_name='页面未保存值'), self.project_path)
                self.assertTrue(send.call_args.args[2].startswith(f'项目：{name}\n'))
                self.assertNotIn('页面未保存值', send.call_args.args[2])
                sender.webhook_send_message('旧项目', '详情')
                self.assertIn(name, post.call_args.kwargs['json']['markdown']['title'])

    def test_invalid_project_config_prevents_test_and_formal_http(self):
        module, sender = self.legacy_sender()
        for content in (None, '[other]\nproject_name = wrong\n', '[project_info]\n',
                        '[project_info]\nproject_name =   \n', 'private malformed', b'\xff'):
            with self.subTest(content=content):
                if content is None:
                    self.project_path.unlink(missing_ok=True)
                else:
                    self.project_path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
                with patch('src.services.message_push_config_service.send_text') as send, \
                     patch.object(module, 'Path', return_value=self.project_path), \
                     patch.object(module.requests, 'post') as post:
                    with self.assertRaisesRegex(ValueError, '已跳过发送') as caught:
                        send_test_message(DEFAULTS, self.project_path)
                    self.assertNotIn('private', str(caught.exception))
                    self.assertIsInstance(sender.webhook_send_message('旧项目', '详情'), ValueError)
                    send.assert_not_called()
                    post.assert_not_called()

    def test_project_read_permission_error_is_redacted(self):
        with patch.object(Path, 'open', side_effect=PermissionError('private-credential')):
            with self.assertRaisesRegex(ValueError, '项目名称读取失败') as caught:
                load_push_project_name(self.project_path)
        self.assertNotIn('private-credential', str(caught.exception))

    def response(self, payload):
        response = Mock(status=200)
        response.read.return_value = json.dumps(payload).encode()
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        return opener

    def test_signed_send_uses_current_values_and_at_all_even_when_disabled(self):
        opener = self.response({'errcode': 0})
        with patch('src.core.dingtalk_robot.build_opener', return_value=opener), \
             patch('src.core.dingtalk_robot.time.time', return_value=1700000000):
            send_test_message(dict(DEFAULTS, webhook='https://oapi.dingtalk.com/robot/send?access_token=demo',
                                   secret='demo-secret', at_all='1'), self.project_path)
        request = opener.open.call_args.args[0]
        query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query['access_token'], ['demo'])
        self.assertEqual(query['timestamp'], ['1700000000000'])
        self.assertTrue(query['sign'][0])
        self.assertTrue(json.loads(request.data)['at']['isAtAll'])
        self.assertEqual(json.loads(request.data)['text']['content'],
                         '项目：中文项目\nLineCheckAssistant 消息推送测试：收到此消息表示钉钉机器人推送正常。')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
        opener.open.assert_called_once()

    def test_unsigned_send_and_robot_failure_are_reported_without_remote_text(self):
        opener = self.response({'errcode': 310000, 'errmsg': 'private-secret'})
        with patch('src.core.dingtalk_robot.build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, '310000') as caught:
                send_text('https://oapi.dingtalk.com/robot/send?access_token=demo', '', 'test')
        self.assertNotIn('private-secret', str(caught.exception))
        self.assertNotIn('sign=', opener.open.call_args.args[0].full_url)

    def test_invalid_url_timeout_and_malformed_response(self):
        with patch('src.core.dingtalk_robot.build_opener') as build:
            with self.assertRaises(ValueError):
                send_text('https://example.invalid/?access_token=demo', '', 'test')
            build.assert_not_called()
        for payload in ({}, [], {'errcode': False}):
            with patch('src.core.dingtalk_robot.build_opener', return_value=self.response(payload)):
                with self.assertRaises(RuntimeError):
                    send_text('https://oapi.dingtalk.com/robot/send?access_token=demo', '', 'test')
        opener = Mock()
        opener.open.side_effect = TimeoutError('private-token')
        with patch('src.core.dingtalk_robot.build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, '结果未知') as caught:
                send_text('https://oapi.dingtalk.com/robot/send?access_token=demo', '', 'test')
        self.assertNotIn('private-token', str(caught.exception))
        opener.open.assert_called_once()


class MessagePushConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.ini"
        self.service = MessagePushConfigService(self.path)

    def test_missing_and_partial_config(self):
        self.assertEqual(self.service.load(), DEFAULTS)
        self.assertFalse(self.path.exists())
        self.path.write_text('[dingtalk_config]\nsecret = demo\n', encoding='utf-8')
        self.assertEqual(self.service.load(), dict(DEFAULTS, secret='demo'))
        self.service.save(DEFAULTS)
        self.assertEqual(self.service.load(), DEFAULTS)

    def test_round_trip_preserves_comments_unknown_keys_and_latest_other_sections(self):
        original = (b'\xef\xbb\xbf# header\r\n[other_config]\r\nretry = 42\r\n'
                    b'[dingtalk_config]\r\n# keep\r\ndingtalk_flag = 0\r\n'
                    b'webhook = old\r\nsecret = old\r\nat_all = 0\r\nfuture = keep\r\n'
                    b'[ui_defaults]\r\nstartup_time = 99\r\n')
        self.path.write_bytes(original)
        self.service.load()
        self.path.write_bytes(original.replace(b'retry = 42', b'retry = 12'))
        values = dict(dingtalk_flag='1', webhook='https://example.invalid/?token=a%20b&x=1',
                      secret='demo%#;=中文', at_all='1')
        self.service.save(values)
        self.assertEqual(self.service.load(), values)
        expected = original.replace(b'retry = 42', b'retry = 12')
        for key, value in values.items():
            old = '0' if key in ('dingtalk_flag', 'at_all') else 'old'
            expected = expected.replace(f'{key} = {old}'.encode(), f'{key} = {value}'.encode())
        self.assertEqual(self.path.read_bytes(), expected)

    def test_add_section_after_unterminated_line(self):
        self.path.write_bytes(b'[other]\nkey = keep')
        self.service.save(DEFAULTS)
        self.assertEqual(self.service.load(), DEFAULTS)
        self.assertTrue(self.path.read_bytes().startswith(b'[other]\nkey = keep\n'))

    def test_empty_fields_keep_line_endings_when_filled(self):
        self.path.write_bytes(b'[dingtalk_config]\r\nwebhook = \r\nsecret =\r\n')
        values = dict(DEFAULTS, webhook='demo-url', secret='demo-secret')
        self.service.save(values)
        self.assertEqual(self.service.load(), values)
        self.assertIn(b'webhook = demo-url\r\nsecret =demo-secret\r\n', self.path.read_bytes())

    def test_invalid_input_does_not_write_or_disclose_value(self):
        for values in (dict(DEFAULTS, secret='private\nvalue'), dict(DEFAULTS, at_all='private')):
            with self.assertRaises(ValueError) as caught:
                self.service.save(values)
            self.assertNotIn('private', str(caught.exception))
            self.assertFalse(self.path.exists())

    def test_parse_and_write_errors_do_not_disclose_credentials(self):
        self.path.write_text('[dingtalk_config]\nprivate malformed line\n', encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            self.service.load()
        self.assertNotIn('private', str(caught.exception))
        with patch.object(Path, 'write_bytes', side_effect=PermissionError('private')):
            with self.assertRaises(OSError) as caught:
                self.service.save(DEFAULTS)
        self.assertNotIn('private', str(caught.exception))


class MessagePushWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.root.test_item_config_window = None
        self.root.test_item_pretest_controls = None
        self.root._restore_module_window_size = Mock(return_value=(1000, 960))
        self.root._remember_module_window_size = Mock()
        self.root._log = Mock()
        self.config = TestProjectConfig()
        self.legacy = dict(communication_method='telnet', telnet_enable='0', baud_rate='19200',
                           selected_profile='test', startup_time='1', interval_time='1',
                           number_of_tests='1', wait_command_done='1')
        def builder(name, value):
            def build(notebook, *_args, **_kwargs):
                notebook.add(ttk.Frame(notebook), text=name)
                return {'capture': lambda: value, 'load': Mock()}
            return build
        for method, name, value in (
            ('telnet', 'Telnet', self.config.telnet), ('order', '测试项', self.config.order),
            ('wifi', 'WiFi', self.config.connect_wifi), ('project_info', '项目信息', self.config.project_info),
            ('ui_defaults', '开关机运行参数', self.legacy),
        ):
            setattr(self.root, f'_build_test_item_{method}_tab', builder(name, value))
        self.store = Mock()
        self.store.load.return_value = self.config
        self.legacy_store = Mock()
        self.legacy_store.load.return_value = self.legacy
        self.legacy_store.validate.side_effect = lambda values: values
        self.service = Mock(wraps=MessagePushConfigService(Path('unused')))
        self.service.load.return_value = dict(DEFAULTS, webhook='private-webhook', secret='private-secret')
        self.service.save = Mock()
        self.tab = None
        def build_tab(*args, **kwargs):
            self.tab = MessagePushTab(*args, **kwargs)
            return self.tab
        for name, value in (
            ('TestItemConfigStore', Mock(return_value=self.store)),
            ('LegacyUiDefaultsStore', Mock(return_value=self.legacy_store)),
            ('MessagePushConfigService', Mock(return_value=self.service)),
            ('MessagePushTab', build_tab), ('center_toplevel_on_parent', Mock()),
            ('schedule_toplevel_client_refresh', Mock()),
        ):
            patcher = patch('line_check_assistant.app.' + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        messages_patch = patch('line_check_assistant.app.messagebox')
        self.messages = messages_patch.start()
        self.addCleanup(messages_patch.stop)
        self.messages.askyesno.return_value = True
        LineCheckAssistant._open_test_item_config(self.root)
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)
        self.buttons = {w.cget('text'): w for w in walk(self.root.test_item_config_window)
                        if isinstance(w, ttk.Button)}

    def test_native_controls_and_save(self):
        notebook = self.tab.frame.master
        self.assertEqual([notebook.tab(tab, 'text') for tab in notebook.tabs()],
                         ['Telnet', '测试项', 'WiFi', '项目信息', '开关机运行参数', '消息推送'])
        checks = [w for w in self.tab.frame.winfo_children() if isinstance(w, tk.Checkbutton)]
        self.assertEqual(len(checks), 2)
        checks[0].invoke()
        self.tab.variables['secret'].set('new-secret')
        self.buttons['保存'].invoke()
        self.service.save.assert_called_once_with(dict(DEFAULTS, dingtalk_flag='1',
                                                      webhook='private-webhook', secret='new-secret'))
        self.assertNotIn('private-webhook', str(self.messages.askyesno.call_args))
        self.assertNotIn('new-secret', str(self.root._log.call_args_list))
        self.messages.askyesno.reset_mock()
        self.buttons['关闭'].invoke()
        self.messages.askyesno.assert_not_called()

    def test_cancel_save_and_reload(self):
        self.tab.variables['secret'].set('edited')
        self.messages.askyesno.return_value = False
        self.buttons['保存'].invoke()
        self.store.save.assert_not_called()
        self.service.save.assert_not_called()
        self.buttons['重新加载'].invoke()
        self.assertEqual(self.tab.capture()['secret'], 'edited')
        self.messages.askyesno.return_value = True
        self.buttons['重新加载'].invoke()
        self.assertEqual(self.tab.capture()['secret'], 'private-secret')

    def test_send_button_uses_snapshot_blocks_repeat_and_returns_to_idle(self):
        self.tab.variables['secret'].set('unsaved-secret')
        with patch('src.ui.message_push_tab.threading.Thread') as thread:
            self.buttons['发送测试消息'].invoke()
            self.tab.send_test()
            thread.assert_called_once()
            values = thread.call_args.kwargs['args'][0]
            self.assertEqual(values['secret'], 'unsaved-secret')
            self.assertTrue(self.tab.running)
            self.store.save.assert_not_called()
            self.service.save.assert_not_called()
        with patch('src.ui.message_push_tab.send_test_message') as send:
            self.tab._send_worker(values)
            self.assertEqual(send.call_args.args, (values, self.tab.project_config_path))
        self.tab._poll_result()
        self.assertFalse(self.tab.running)
        self.assertIn('发送成功', self.tab.status.get())
        self.assertNotIn('unsaved-secret', str(self.root._log.call_args_list))

    def test_send_failure_restores_button_and_blocks_close_while_running(self):
        with patch('src.ui.message_push_tab.threading.Thread'), \
             patch('src.ui.message_push_tab.messagebox.showinfo') as notice:
            self.tab.send_test()
            self.buttons['关闭'].invoke()
            notice.assert_called_once()
        with patch('src.ui.message_push_tab.send_test_message', side_effect=RuntimeError('network failed')):
            self.tab._send_worker(self.tab.capture())
        self.tab._poll_result()
        self.assertFalse(self.tab.running)
        self.assertEqual(str(self.tab.test_button['state']), 'normal')
        self.assertIn('network failed', self.tab.status.get())

    def test_failure_keeps_dirty_and_invalid_values_prevent_all_writes(self):
        self.tab.variables['secret'].set('bad\nsecret')
        self.buttons['保存'].invoke()
        self.store.save.assert_not_called()
        self.tab.variables['secret'].set('edited')
        self.service.save.side_effect = OSError('write failed')
        self.buttons['保存'].invoke()
        self.messages.showerror.assert_called()
        self.messages.askyesno.reset_mock()
        self.messages.askyesno.return_value = False
        self.buttons['关闭'].invoke()
        self.messages.askyesno.assert_called_once()
        self.assertTrue(self.root.test_item_config_window.winfo_exists())

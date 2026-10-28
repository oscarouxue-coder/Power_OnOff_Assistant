"""Recovery tests use fake transports/devices; never open a real COM port."""
import ast
import queue
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_legacy_power_test_service import _write_config_tree
from src.services import legacy_power_test_service as legacy
from src.services.power_test_resume_service import PowerTestResumeSession, ResumeRejected


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('background task did not reach expected state')
        threading.Event().wait(0.01)


class FastEvent(threading.Event):
    def wait(self, timeout=None):
        # Skip the old 1-second spacing between initial channel launches.
        if timeout in (0.5, 1.0):
            return self.is_set()
        return super().wait(timeout)


class ThreadProcess:
    def __init__(self, target, args, **kwargs):
        self.args = args
        self.thread = threading.Thread(target=target, args=args)
        self.exitcode = 0

    def start(self):
        self.thread.start()

    def is_alive(self):
        return self.thread.is_alive()

    def join(self, timeout=None):
        self.thread.join(timeout)

    def terminate(self):
        self.args[2].set()


class ThreadContext:
    Queue = queue.Queue
    Event = FastEvent
    Process = ThreadProcess


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = _write_config_tree(Path(self.temp.name))
        self.request = replace(legacy.prepare_legacy_power_test_request(
            root, (legacy.LegacyPowerChannel(5, '192.168.1.105'),
                   legacy.LegacyPowerChannel(6, '192.168.1.106'))),
            connect_wifi_enable=False, number_of_tests=5)
        self.channels = [SimpleNamespace(section=f'channel_{n}',
                         network_card_ip=f'192.168.1.10{n}', device_manage_ip='192.168.1.1')
                         for n in (5, 6)]
        self.logs = []
        self.session = PowerTestResumeSession(self.request, self.channels,
                                             threading.Event(), self.logs.append)

    def failed(self, channel=5):
        self.session.completed[channel] = 3
        self.session.failed.add(channel)
        self.session.ready.add(channel)

    def test_readiness_stop_success_and_duplicate_submission(self):
        self.failed()
        self.session.ready.clear()
        self.assertFalse(self.session.can_resume(5))
        self.session.ready.add(5)
        entered, release = threading.Event(), threading.Event()

        def validate(_channel):
            entered.set()
            release.wait(2)
            raise ResumeRejected('已停止')

        with patch.object(self.session, '_validate', side_effect=validate):
            self.assertTrue(self.session.submit(5))
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.session.submit(5))
            self.session.stop()
            release.set()
            wait_for(lambda: not self.session.busy)
        self.assertFalse(self.session.can_resume(5))
        self.session.stop_event.clear()
        self.session.completed[5] = 5
        self.assertFalse(self.session.can_resume(5))

    def test_config_change_or_missing_file_prevents_preflight(self):
        path = self.request.tool_root / 'config/config.ini'
        original = path.read_bytes()
        with patch('src.services.power_test_resume_service.query_device_project_info') as query:
            path.write_bytes(original + b'\n; changed\n')
            with self.assertRaisesRegex(ResumeRejected, '配置已变化'):
                self.session._validate(5)
            path.unlink()
            with self.assertRaisesRegex(ResumeRejected, '无法读取'):
                self.session._validate(5)
            query.assert_not_called()

    def test_version_precheck_uses_target_source_and_rejects_mismatch(self):
        info = SimpleNamespace(software_version='a', internal_software_version='b', onu_compile_time='c')
        config = SimpleNamespace(project_info=info, telnet=MagicMock())
        with patch('src.services.power_test_resume_service.TestItemConfigStore') as store, \
                patch('src.services.power_test_resume_service.query_device_project_info', return_value=info) as query:
            store.return_value.load.return_value = config
            self.session._validate(5)
            self.assertEqual(query.call_args.args[0].bind_ip, '192.168.1.105')
            self.assertEqual(query.call_args.args[0].device_host, '192.168.1.1')
            query.return_value = SimpleNamespace(software_version='wrong', internal_software_version='b', onu_compile_time='c')
            with self.assertRaisesRegex(ResumeRejected, '版本不一致'):
                self.session._validate(5)

    def test_empty_versions_skip_query_and_resume_only_failed_channel(self):
        for value in ('', ' \t '):
            with self.subTest(value=value), \
                    patch('src.services.power_test_resume_service.TestItemConfigStore') as store, \
                    patch('src.services.power_test_resume_service.query_device_project_info') as query, \
                    patch.object(legacy, 'run_legacy_power_test',
                                 return_value=legacy.LegacyPowerTestResult(True, 'ok')) as run:
                store.return_value.load.return_value.project_info = SimpleNamespace(
                    project_name='仍有项目名称', software_version=value,
                    internal_software_version=value, onu_compile_time=value)
                self.failed()
                self.session._resume(5)
                query.assert_not_called()
                self.assertTrue(all(call.kwargs == {'required': True}
                                    for call in store.return_value.load.call_args_list))
                run.assert_called_once()
                self.assertEqual([c.number for c in run.call_args.args[0].channels], [5])
                self.assertEqual(run.call_args.kwargs['initial_completed'], {5: 3})
                self.assertFalse(run.call_args.kwargs['initialize_power'])
                self.assertIn('三项版本基准均为空，跳过开始前版本校验', '\n'.join(self.logs))

    def test_partial_versions_and_query_failure_prevent_resume(self):
        with patch('src.services.power_test_resume_service.TestItemConfigStore') as store, \
                patch('src.services.power_test_resume_service.query_device_project_info') as query, \
                patch.object(legacy, 'run_legacy_power_test') as run:
            info = SimpleNamespace(software_version='a', internal_software_version='', onu_compile_time='')
            store.return_value.load.return_value.project_info = info
            with self.assertRaisesRegex(ResumeRejected, '内部软件版本、ONU 软件编译时间'):
                self.session._validate(5)
            query.assert_not_called()
            info.internal_software_version, info.onu_compile_time = 'b', 'c'
            query.side_effect = RuntimeError('查询失败')
            self.failed()
            self.session._resume(5)
            run.assert_not_called()

    def test_empty_versions_still_check_config_and_stop_after_load(self):
        for failure in ('changed', 'stopped'):
            with self.subTest(failure=failure), \
                    patch('src.services.power_test_resume_service.TestItemConfigStore') as store, \
                    patch('src.services.power_test_resume_service.query_device_project_info') as query:
                def load(**kwargs):
                    if failure == 'stopped':
                        self.session.stop_event.set()
                    else:
                        path = self.request.tool_root / 'config/config.ini'
                        path.write_bytes(path.read_bytes() + b'\n; changed\n')
                    return SimpleNamespace(project_info=SimpleNamespace(
                        software_version='', internal_software_version='', onu_compile_time=''))
                # Isolate each case's original fingerprint and stop state.
                self.session.fingerprint = self.session._fingerprint()
                self.session.stop_event.clear()
                store.return_value.load.side_effect = load
                with self.assertRaisesRegex(ResumeRejected, '配置变化或收到停止'):
                    self.session._validate(5)
                query.assert_not_called()

    def test_unreadable_profile_cannot_skip_resume_precheck(self):
        with patch('src.services.power_test_resume_service.TestItemConfigStore') as store, \
                patch('src.services.power_test_resume_service.query_device_project_info') as query, \
                patch.object(legacy, 'run_legacy_power_test') as run:
            store.return_value.load.side_effect = PermissionError('unreadable')
            self.failed()
            self.session._resume(5)
            query.assert_not_called()
            run.assert_not_called()

    def test_untrusted_preflight_exception_is_redacted(self):
        self.failed()
        with patch.object(self.session, '_validate', side_effect=ValueError('password=secret')):
            self.session._resume(5)
        self.assertNotIn('secret', '\n'.join(self.logs))

    def test_stale_messages_cannot_override_new_attempt(self):
        self.session.attempts[5] = 2
        self.assertFalse(self.session.accepts(dict(channel=5, attempt=1, run_id=self.session.run_id)))
        self.assertFalse(self.session.accepts(dict(channel=5, attempt=2, run_id='old-session')))
        self.assertTrue(self.session.accepts(dict(channel=5, attempt=2, run_id=self.session.run_id)))
        self.assertTrue(self.session.accepts(dict(channel=6, attempt=0, run_id=self.session.run_id)))

    def test_exit_race_falls_back_once_after_serial_owner_releases(self):
        self.failed()
        transport = queue.Queue()
        self.session.attach(transport)
        self.session.process_lock.acquire()
        with patch.object(self.session, '_validate'), \
                patch.object(legacy, 'run_legacy_power_test', return_value=legacy.LegacyPowerTestResult(True, 'ok')) as run:
            self.assertTrue(self.session.submit(5))
            command = transport.get(timeout=2)
            self.assertEqual(command['completed'], 3)
            self.session.detach()
            threading.Event().wait(0.1)
            run.assert_not_called()
            self.session.process_lock.release()
            wait_for(lambda: not self.session.busy)
            run.assert_called_once()
            self.assertEqual([c.number for c in run.call_args.args[0].channels], [5])
            self.assertEqual(run.call_args.kwargs['initial_completed'], {5: 3})
            self.assertFalse(run.call_args.kwargs['initialize_power'])

    def test_stop_while_waiting_for_process_exit_never_recovers(self):
        self.failed()
        transport = queue.Queue()
        self.session.attach(transport)
        with patch.object(self.session, '_validate'), patch.object(legacy, 'run_legacy_power_test') as run:
            self.session.submit(5)
            transport.get(timeout=2)
            self.session.stop()
            self.session.detach()
            wait_for(lambda: not self.session.busy)
            run.assert_not_called()

    def test_multiple_after_run_recoveries_share_serial_owner_lock(self):
        self.failed(5)
        self.failed(6)
        running = []
        calls = []

        def recover(request, *args, **kwargs):
            self.assertFalse(running)
            running.append(request.channels[0].number)
            calls.append(request.channels[0].number)
            threading.Event().wait(0.05)
            running.clear()
            return legacy.LegacyPowerTestResult(False, 'again')

        with patch.object(self.session, '_validate'), patch.object(legacy, 'run_legacy_power_test', side_effect=recover):
            self.session.submit(5)
            self.session.submit(6)
            wait_for(lambda: not self.session.busy)
        self.assertCountEqual(calls, [5, 6])

    def test_recovery_overall_progress_keeps_other_failed_channels(self):
        self.failed(5)
        self.failed(6)
        reported = []
        self.session.callbacks['on_progress'] = lambda n, total: reported.append((n, total))

        def recover(*args, **kwargs):
            self.session.completed[5] = 5
            kwargs['on_progress'](5, 5)
            return legacy.LegacyPowerTestResult(True, 'ok')

        with patch.object(self.session, '_validate'), patch.object(legacy, 'run_legacy_power_test', side_effect=recover):
            self.session._resume(5)
        self.assertEqual(reported, [(3, 5)])

    def worker_environment(self, *, fail_again=False):
        """Real adapter IPC/threads, with only legacy device dependencies stubbed."""
        released = threading.Event()
        calls, frames, initializations = [], [], []

        class Serial:
            def __init__(self, *args, **kwargs):
                pass
            def is_open(self):
                return True
            def write(self, frame):
                frames.append(bytes(frame))
            def serial_close(self):
                pass

        class Worker:
            def __init__(self, serial, logger, *args, initialize_power=True):
                self.serial, self.logger = serial, logger
                self.dingtalk = SimpleNamespace(log=None)
                self.power_control = SimpleNamespace(consumer=lambda: None, stopthreadevent=0)
                initializations.append(initialize_power)
                if initialize_power:
                    serial.write(bytes.fromhex('55 00 AD 00 00 AD'))

            def request_stop(self):
                released.set()

            def run_case(self, ip, channel, stop, **kwargs):
                start = kwargs.get('start_cycle', 1)
                calls.append((channel, start))
                self.serial.write(bytes([channel]))
                if channel == 6:
                    released.wait(3)
                if channel == 5 and start == 1:
                    self.logger.info('2026-10-12 10:00:00: 通道5下挂的设备在第3次测试时正常')
                    return False
                if channel == 5 and fail_again:
                    released.set()
                    return False
                for n in range(start, 6):
                    self.logger.info(f'2026-10-12 10:00:00: 通道{channel}下挂的设备在第{n}次测试时正常')
                released.set()
                return not fail_again

        modules = {}
        for name, attr, value in (
                ('common.serilal_client', 'Serial', Serial),
                ('test_case.powe_on_off_telnet', 'PowerOnOffTelnet', Worker),
                ('test_case.power_on_off_ssh', 'PowerOnOffSsh', Worker)):
            module = types.ModuleType(name)
            setattr(module, attr, value)
            modules[name] = module
        return modules, calls, frames, initializations

    def run_adapter(self, request, **kwargs):
        modules, calls, frames, initializations = self.worker_environment(fail_again=kwargs.pop('fail_again', False))
        with patch.dict(sys.modules, modules), patch.object(sys, 'path', list(sys.path)), \
                patch.object(legacy.os, 'chdir'), patch.object(legacy, '_install_headless_legacy_stubs'), \
                patch.object(legacy, '_connect_legacy_log_signals'), \
                patch.object(legacy, '_install_legacy_result_log_forwarder', return_value=lambda: None):
            result = legacy.run_legacy_power_test(
                request, self.logs.append, self.session.stop_event, process_context=ThreadContext(),
                resume_session=self.session, **kwargs)
        return result, calls, frames, initializations

    def test_live_resume_reuses_process_and_does_not_repeat_other_channel(self):
        errors = []

        def click_resume():
            try:
                wait_for(lambda: self.session.can_resume(5))
                self.assertEqual(self.session.completed[5], 3)
                self.assertTrue(self.session.submit(5))
            except Exception as exc:
                errors.append(exc)

        click = threading.Thread(target=click_resume)
        with patch.object(self.session, '_validate'):
            click.start()
            result, calls, frames, initializations = self.run_adapter(self.request)
            click.join(4)
            wait_for(lambda: not self.session.busy)
        self.assertFalse(errors, errors)
        self.assertTrue(result.ok, result.detail)
        self.assertCountEqual(calls, [(5, 1), (6, 1), (5, 4)])
        self.assertEqual(initializations, [False])
        self.assertNotIn(bytes.fromhex('55 00 AD 00 00 AD'), frames)
        self.assertEqual(frames[:2], [bytes.fromhex('55 01 A1 00 05 A5'),
                                     bytes.fromhex('55 01 A1 00 06 A6')])
        self.assertEqual(sum(len(frame) == 6 for frame in frames), 2)
        self.assertEqual(self.session.completed, {5: 5, 6: 5})

    def test_after_run_adapter_never_initializes_all_off_telnet_and_ssh(self):
        for communication in ('telnet', 'ssh'):
            with self.subTest(communication=communication):
                self.session.attempts[5] = 1
                self.session.completed[5] = 3
                request = replace(self.request, communication_method=communication,
                                  channels=(self.request.channels[0],))
                progresses = []
                result, calls, frames, initializations = self.run_adapter(
                    request, initial_completed={5: 3}, initialize_power=False,
                    on_channel_progress=lambda *args: progresses.append(args))
                self.assertTrue(result.ok)
                self.assertEqual(progresses[0], (5, 3, 5, '等待第4轮'))
                self.assertEqual(calls, [(5, 4)])
                self.assertEqual(initializations, [False])
                self.assertNotIn(bytes.fromhex('55 00 AD 00 00 AD'), frames)
                self.assertNotIn(bytes([6]), frames)

    def test_resumed_failure_keeps_progress_and_can_be_retried(self):
        self.session.attempts[5] = 1
        self.session.completed[5] = 3
        history = []
        result, calls, _, _ = self.run_adapter(
            replace(self.request, channels=(self.request.channels[0],)),
            initial_completed={5: 3}, initialize_power=False, fail_again=True,
            on_channel_history=lambda *args: history.append(args))
        self.assertFalse(result.ok)
        self.assertEqual(self.session.completed[5], 3)
        self.assertTrue(self.session.can_resume(5))
        self.assertEqual([item[2] for item in history], ['resume', 'failed'])
        self.assertEqual(calls, [(5, 4)])

    def test_real_legacy_entry_starts_at_requested_cycle_and_keeps_old_log(self):
        for filename in ('powe_on_off_telnet.py', 'power_on_off_ssh.py'):
            path = Path(__file__).resolve().parents[1] / 'Auto_power_on_off_tool/test_case' / filename
            tree = ast.parse(path.read_text(encoding='utf-8'))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
            initializer = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
            self.assertEqual(initializer.args.kwonlyargs[0].arg, 'initialize_power')
            self.assertIs(initializer.args.kw_defaults[0].value, True)
            power_guard = next(n for n in initializer.body if isinstance(n, ast.If)
                               and isinstance(n.test, ast.Name) and n.test.id == 'initialize_power')
            power_owner = SimpleNamespace(power_control=MagicMock(), ser=object())
            exec(compile(ast.fix_missing_locations(ast.Module(body=[power_guard], type_ignores=[])), str(path), 'exec'),
                 dict(self=power_owner, initialize_power=False))
            power_owner.power_control.power_all_off.assert_not_called()
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_case')
            # Execute the real prefix up to its test loop, then observe the loop
            # counter, without executing a single device command.
            loop = next(n for n in ast.walk(method) if isinstance(n, ast.While))
            loop.body = [ast.Return(value=ast.Name(id='times', ctx=ast.Load()))]
            module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
            env = dict(re=re, TelnetClient=SimpleNamespace())
            exec(compile(module, str(path), 'exec'), env)
            log = Path(self.temp.name) / (filename + '.log')
            log.write_bytes(b'original failure\n')
            worker = MagicMock()
            worker.test_number = 5
            worker.config_file_path = 'test_project_config.ini'
            worker.url = 'http://192.168.1.1'
            worker.is_stop_requested.return_value = False
            worker.selected_scheme_path.return_value = True
            worker.create_command_exec_result_file.return_value = str(log)
            worker.cf.read_config_file.return_value = {}
            with patch('builtins.print'):
                cycle = env['run_case'](worker, '192.168.1.105', 5, threading.Event(),
                                        start_cycle=4, result_suffix='unique')
            self.assertEqual(cycle, 4)
            self.assertEqual(log.read_bytes(), b'original failure\n')
            self.assertTrue(log.with_name(log.stem + '_resume_unique.log').exists())
            self.assertEqual(method.args.kw_defaults[0].value, 1)


class ResumeMenuTests(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.pipeline_window = None
        self.app._power_resume_context_menu = None
        self.session = self.app.power_test_resume_session
        self.session.completed = {5: 3}
        self.session.request.number_of_tests = 5
        self.session.can_resume.return_value = True
        self.session.submit.return_value = True
        self.session.is_recovering = False
        self.tile = MagicMock()

    def show_menu(self, menu):
        from src.ui.power_test_resume_menu import bind_resume_menu
        bind_resume_menu(self.app, self.tile, 5)
        self.tile.bind.call_args.args[1](SimpleNamespace(x_root=10, y_root=20))
        return menu.return_value.add_command.call_args.kwargs

    def test_menu_survives_popup_and_confirms_remaining_rounds(self):
        with patch('src.ui.power_test_resume_menu.tk.Menu') as menu, \
                patch('src.ui.power_test_resume_menu.messagebox.askyesno', return_value=True) as confirm:
            command = self.show_menu(menu)
            self.assertEqual(command['state'], 'normal')
            menu.return_value.destroy.assert_not_called()
            command['command']()
            self.session.submit.assert_called_once_with(5)
            self.assertIn('第 4/5', confirm.call_args.args[1])
            self.assertIn('三项版本基准均为空时跳过', confirm.call_args.args[1])
            self.assertIn('部分填写时阻止启动', confirm.call_args.args[1])
            self.assertIn('仅对通道 5 执行上下电', confirm.call_args.args[1])

    def test_running_or_stopping_channel_is_disabled(self):
        self.session.can_resume.return_value = False
        with patch('src.ui.power_test_resume_menu.tk.Menu') as menu:
            command = self.show_menu(menu)
            self.assertEqual(command['state'], 'disabled')

    def test_cancelled_confirmation_does_not_submit(self):
        with patch('src.ui.power_test_resume_menu.tk.Menu') as menu, \
                patch('src.ui.power_test_resume_menu.messagebox.askyesno', return_value=False):
            self.show_menu(menu)['command']()
        self.session.submit.assert_not_called()

    def test_state_changed_during_confirmation_does_not_submit(self):
        def change(*args, **kwargs):
            self.app.power_test_resume_session = None
            return True
        with patch('src.ui.power_test_resume_menu.tk.Menu') as menu, \
                patch('src.ui.power_test_resume_menu.messagebox.askyesno', side_effect=change):
            self.show_menu(menu)['command']()
        self.session.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()

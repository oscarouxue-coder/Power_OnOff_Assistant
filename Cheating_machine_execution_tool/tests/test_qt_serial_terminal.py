"""Qt serial adapter contracts; real shared manager with fake driver only."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from src.core.serial_transport import SerialSessionManager
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.serial_models import SerialEvent, SerialSettings
from src.services.ai_debug_service import DiagnosticToolExecutor
from src.services.ai_serial_client import AiSerialClient
from src.services.capability_registry import CapabilityRegistry
from src.services.qt_serial_terminal import QtSerialTerminal
from src.utils.ai_redaction import DiagnosticRedactor
from qt_serial_fakes import SerialHarness


class QtSerialTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qt-serial-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.harness = SerialHarness().start()
        self.addCleanup(self.harness.stop)
        self.manager = SerialSessionManager()
        self.addCleanup(self.manager.shutdown_all)
        self.channels = [dict(section='channel_1', enabled=True, vlan_name='VLAN116', serial_port='COM216'),
            dict(section='channel_7', enabled=True, vlan_name='VLAN122', serial_port='COM222'),
            dict(section='channel_2', enabled=False, vlan_name='VLAN117', serial_port='COM217')]
        self.logs = []
        self.service = SimpleNamespace(manager=self.manager, registry=CapabilityRegistry(),
            snapshot=lambda: dict(channels=self.channels), emit=self.logs.append)
        self.context = SimpleNamespace(root=self.root,
            identity=SimpleNamespace(project_id='fixture-project-id', name='串口测试项目'))
        self.terminal = QtSerialTerminal(self.service, self.context)
        self.authority = CapabilityAuthority('operator', 'session', 'request', (), source='gui', approved=True)
        self.snapshot = self.call('show', {})
        self.token = self.snapshot['token']

    def call(self, suffix, values=None):
        args = dict(values or {})
        if suffix != 'show':
            args.setdefault('token', self.token)
        spec = self.service.registry.validate('serial.terminal.' + suffix, args)
        self.authority.check((), spec.risk)
        self.assertIn(self.authority.source, spec.sources)
        return spec.handler(args, self.authority)

    def wait(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('serial fixture timeout')

    def poll(self, active='vlan116'):
        return self.call('poll', dict(active=active))

    def test_show_selected_targets_does_not_open_devices_and_uses_legacy_fallback(self):
        self.assertEqual([t['port'] for t in self.snapshot['tabs']], ['COM216', 'COM222'])
        self.assertFalse(self.harness.sessions)
        self.channels[0]['serial_port'] = ''
        self.assertEqual(self.call('show', {})['tabs'][0]['port'], 'COM16')
        self.assertFalse(self.harness.sessions)

    def test_diagnostic_snapshot_preserves_ownership_input_and_original_history(self):
        target = dict(target='vlan116', port='COM216')
        self.service.snapshot = lambda: dict(channels=self.channels, power_serial_port='com216')
        result = self.call('diagnostics', target)
        self.assertIn('未打开', result['text'])
        self.assertTrue(result['state']['power_port_conflict'])
        self.assertFalse(self.harness.sessions)
        for invalid in (dict(target, token='f' * 32), dict(target, port='COM222')):
            with self.assertRaises(CapabilityError):
                self.call('diagnostics', invalid)
        with patch.object(self.manager, 'acquire_monitor', side_effect=OSError('fixture driver unavailable')):
            self.call('open_all')
        self.assertEqual(self.call('diagnostics', target)['state']['last_open_error'], 'fixture driver unavailable')
        self.call('open_all')
        session = self.manager.acquire_existing_control('fixture job', SerialSettings('COM216'))
        legacy = AiSerialClient(self.manager)
        self.addCleanup(legacy.close)
        driver = self.harness.drivers['COM216']
        driver.input.put(b'x' * 70000 + b'fixture private data')
        self.wait(lambda: session.cursor() >= 70020)
        state = self.manager.diagnostic_state('COM216')
        for _ in range(2):
            result = self.call('diagnostics', target)
            self.assertEqual(result['text'], session.peek_since(session.cursor() - 65536))
            self.assertEqual(result['text'], legacy.read(SimpleNamespace(port='COM216')))
            self.assertTrue(result['text'].endswith('fixture private data'))
            self.assertEqual(result['state']['last_open_error'], '')
            self.assertEqual(result['state']['control_owner'], 'fixture job')
        self.assertEqual(self.manager.diagnostic_state('COM216'), state)
        self.wait(lambda: self.poll()['tabs'][0]['text'].endswith('fixture private data'))
        self.assertFalse(driver.writes)
        self.assertFalse(any('fixture private data' in line for line in self.logs))

    def test_passive_reader_limits_bytes_at_read_time_during_driver_burst(self):
        target = SimpleNamespace(channel=1, port='COM216')
        client = AiSerialClient(self.manager)
        self.addCleanup(client.close)
        session = self.manager.acquire_monitor('burst fixture', SerialSettings(target.port))
        driver = self.harness.drivers[target.port]
        first = b'A' * 65536
        last = b'B' * 65532 + b'TAIL'
        driver.input.put(first)
        self.wait(lambda: session.cursor() == len(first))
        read = session.peek_since

        def read_after_arrival(cursor):
            driver.input.put(last)
            self.wait(lambda: session.cursor() == len(first) + len(last))
            return read(cursor)

        with patch.object(session, 'peek_since', side_effect=read_after_arrival):
            result = client.read(target)
        self.assertEqual(len(result.encode('utf-8')), 65536)
        self.assertEqual(result, last.decode('ascii'))
        executor = DiagnosticToolExecutor(target, threading.Event(), self.logs.append, None,
                                          DiagnosticRedactor(), None, client.read)
        self.assertEqual(executor.execute('read_serial_log', {}, deep=False)['evidence'], last.decode('ascii'))
        self.assertEqual(read(0), (first + last).decode('ascii'))
        self.assertFalse(driver.writes)

    def test_passive_read_reports_incompatible_settings_without_changing_session(self):
        settings = SerialSettings('COM216', baudrate=9600)
        session = self.manager.acquire_monitor('fixture alternate rate', settings)
        result = self.call('diagnostics', dict(target='vlan116', port='COM216'))
        self.assertIn('参数与目标配置不一致', result['text'])
        self.assertEqual(result['state']['monitor_owners'], ['fixture alternate rate'])
        self.assertIs(self.manager.existing_session(settings), session)
        self.assertFalse(self.harness.drivers['COM216'].writes)

    def test_open_all_preserves_original_log_name_timestamps_and_tail_on_close(self):
        self.call('open_all')
        session = self.harness.sessions['COM216']
        expected = self.root / 'logs/serial' / f'vlan116_COM216_{date.today():%Y%m%d}.log'
        self.assertEqual(session.log_path, expected)
        self.harness.drivers['COM216'].input.put(b'line1\nline2\nlast-tail')
        self.wait(lambda: b'last-tail' in session._history)
        self.call('detach')
        self.wait(lambda: not self.poll()['token'])
        text = expected.read_text(encoding='utf-8')
        for line in text.splitlines():
            self.assertRegex(line, r'^\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2} (RX|TX|STATE) ')
        self.assertIn('RX last-tail', text)
        self.assertTrue(self.harness.drivers['COM216'].closed)

    def test_closing_one_monitor_keeps_other_owner_and_rejects_stale_delivery(self):
        self.call('open_all')
        item = self.terminal.tabs['vlan116']
        session, delivery = item['session'], item['delivery']
        self.manager.acquire_monitor('other-window', SerialSettings('COM216'))
        self.call('close_tab', dict(target='vlan116'))
        self.assertNotIn('vlan116', self.terminal.tabs)
        self.assertIs(self.manager.existing_session(SerialSettings('COM216')), session)
        delivery(SerialEvent('COM216', 'RX', b'late', 'late'))
        self.call('show', {})
        self.call('open_all')
        delivery(SerialEvent('COM216', 'RX', b'late-again', 'late-again'))
        self.assertIsNot(self.terminal.tabs['vlan116']['delivery'], delivery)
        visible = next(t for t in self.poll()['tabs'] if t['target'] == 'vlan116')
        self.assertNotIn('late', visible['text'])
        self.assertFalse(self.harness.drivers['COM216'].closed)

    def test_manual_text_empty_enter_and_control_lock_never_replay(self):
        preview = self.call('preview_send', dict(target='vlan116', text='echo fixture'))
        self.assertFalse(preview['dangerous'])
        self.call('send', dict(confirmation=preview['confirmation']))
        self.assertEqual(self.harness.drivers['COM216'].writes, [b'echo fixture\r'])
        with self.assertRaises(CapabilityError):
            self.call('send', dict(confirmation=preview['confirmation']))
        empty = self.call('preview_send', dict(target='vlan116', text=''))
        self.call('send', dict(confirmation=empty['confirmation']))
        self.assertEqual(self.harness.drivers['COM216'].writes[-1], b'\r')
        blocked = self.call('preview_send', dict(target='vlan116', text='must-not-send'))
        self.manager.acquire_control('upgrade-fixture', SerialSettings('COM216'))
        with self.assertRaises(CapabilityError):
            self.call('send', dict(confirmation=blocked['confirmation']))
        with self.assertRaises(CapabilityError):
            self.call('close_tab', dict(target='vlan116'))
        self.assertEqual(len(self.harness.drivers['COM216'].writes), 2)

    def test_dangerous_confirmation_cancel_expiry_and_binding_change(self):
        for text in ('reboot', 'firstboot -y', 'RESET', 'tftp fixture', 'upgrade'):
            preview = self.call('preview_send', dict(target='vlan116', text=text))
            self.assertTrue(preview['dangerous'])
            self.call('cancel')
            with self.assertRaises(CapabilityError):
                self.call('send', dict(confirmation=preview['confirmation']))
        preview = self.call('preview_send', dict(target='vlan116', text='echo old'))
        self.terminal.pending['created'] -= 121
        with self.assertRaises(CapabilityError):
            self.call('send', dict(confirmation=preview['confirmation']))
        preview = self.call('preview_send', dict(target='vlan116', text='echo changed'))
        self.channels[0]['serial_port'] = 'COM219'
        with self.assertRaises(CapabilityError):
            self.call('send', dict(confirmation=preview['confirmation']))
        self.assertFalse(self.harness.drivers['COM216'].writes)

    def test_bounded_inactive_buffer_and_old_subscription_isolation(self):
        self.call('open_all')
        delivery = self.terminal.tabs['vlan116']['delivery']
        for _ in range(2300):
            delivery(SerialEvent('COM216', 'RX', b'', 'x' * 20000))
        self.assertEqual(self.terminal.events.qsize(), 2000)
        self.assertGreater(self.terminal.events.dropped, 0)
        for _ in range(20):
            self.poll('vlan122')
        item = next(t for t in self.poll()['tabs'] if t['target'] == 'vlan116')
        self.assertLessEqual(len(item['text']), 65536)
        self.assertGreater(item['dropped'], 0)
        self.assertTrue(any('界面显示事件繁忙' in line for line in self.logs))

    def test_directory_restore_preserves_geometry_and_existing_session_file(self):
        state = self.root / 'ui/serial.json'
        state.parent.mkdir()
        state.write_text(json.dumps(dict(geometry='1000x650+50+50', log_dir=str(self.root))), encoding='utf-8')
        self.terminal._restored = False
        self.call('show', {})
        self.assertEqual(self.terminal.log_dir, self.root)
        self.call('open_all')
        actual = self.harness.sessions['COM216'].log_path
        target = self.root / 'new-parent'
        self.call('directory', dict(path=str(target)))
        self.assertEqual(self.terminal.log_dir, target / 'fixture-project-id')
        self.assertEqual(self.harness.sessions['COM216'].log_path, actual)
        self.assertEqual(json.loads(state.read_text())['geometry'], '1000x650+50+50')

    def test_directory_persistence_failure_does_not_change_current_path(self):
        previous = self.terminal.log_dir
        with patch.object(self.terminal, '_save_state', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                self.call('directory', dict(path=str(self.root / 'cannot-save')))
        self.assertEqual(self.terminal.log_dir, previous)

    def test_detach_releases_sessions_when_window_preferences_are_unwritable(self):
        self.call('open_all')
        with patch.object(self.terminal, '_save_state', side_effect=PermissionError('fixture')):
            self.call('detach')
        self.wait(lambda: not self.poll()['token'])
        self.assertTrue(all(driver.closed for driver in self.harness.drivers.values()))
        self.assertTrue(any('日志目录设置未保存' in message for message in self.logs))

    def test_partial_open_failure_keeps_other_monitor_and_reports_real_error(self):
        original = self.manager.acquire_monitor
        def acquire(owner, settings, path):
            if settings.port == 'COM222':
                raise OSError('fixture device unavailable')
            return original(owner, settings, path)
        with patch.object(self.manager, 'acquire_monitor', side_effect=acquire):
            result = self.call('open_all')
        self.assertEqual(result['failures'], ['vlan122'])
        self.assertTrue(result['tabs'][0]['monitoring'])
        self.assertIn('fixture device unavailable', result['tabs'][1]['state'])

    def test_reader_error_visible_without_log_event_delivery(self):
        self.call('open_all')
        self.harness.sessions['COM216'].error = OSError('fixture disconnected')
        result = self.poll()
        self.assertIn('fixture disconnected', result['tabs'][0]['state'])
        self.assertTrue(any('读取失败' in line for line in self.logs))

    def test_shutdown_waits_for_real_reader_callback_and_flushes_tail(self):
        self.call('open_all')
        session = self.harness.sessions['COM216']
        entered, release = threading.Event(), threading.Event()
        def block(event):
            if event.direction == 'RX':
                entered.set()
                release.wait(3)
        session.subscribe(block)
        self.harness.drivers['COM216'].input.put(b'final-tail')
        self.assertTrue(entered.wait(2))
        finished = threading.Event()
        worker = threading.Thread(target=lambda: (self.terminal.shutdown(), finished.set()))
        worker.start()
        try:
            self.assertFalse(finished.wait(.05))
        finally:
            release.set()
            worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertIn('RX final-tail', session.log_path.read_text(encoding='utf-8'))
        self.assertFalse(self.terminal.token)

    def test_only_gui_sources_registered_no_agent_raw_write_expansion(self):
        from src.services.capability_service import CapabilityService
        for suffix in ('show', 'poll', 'diagnostics', 'open_all', 'stop_all', 'detach', 'close_tab', 'preview_send', 'send', 'cancel', 'directory', 'folder'):
            spec = self.service.registry.get('serial.terminal.' + suffix)
            self.assertEqual(spec.sources, ('gui',))
        for source in ('local', 'dingtalk', 'feishu'):
            authority = CapabilityAuthority('principal', 'session', 'request', (), source=source, approved=True)
            with self.assertRaises(CapabilityError) as rejected:
                CapabilityService.validate(self.service, 'serial.terminal.show', {}, authority)
            self.assertEqual(rejected.exception.code, 'source_forbidden')
            with self.assertRaises(CapabilityError) as rejected_read:
                CapabilityService.validate(self.service, 'serial.terminal.diagnostics',
                    dict(token=self.token, target='vlan116', port='COM216'), authority)
            self.assertEqual(rejected_read.exception.code, 'source_forbidden')
        self.assertEqual(self.service.registry.get('serial.terminal.diagnostics').risk, 'read')
        self.assertEqual(self.service.registry.get('serial.terminal.preview_send').risk, 'modify')
        self.assertEqual(self.service.registry.get('serial.terminal.send').risk, 'dangerous')

    def test_driver_failure_reaches_terminal_without_discarding_other_channel(self):
        self.call('open_all')
        driver = self.harness.drivers['COM216']
        session = self.harness.sessions['COM216']
        self.addCleanup(session._host_resource_lock.close)
        self.addCleanup(driver.close)
        other = self.harness.sessions['COM222']
        with patch.object(driver, 'close', side_effect=OSError('fixture close refused')):
            self.call('close_tab', dict(target='vlan116'))
            ticket = self.terminal.tabs['vlan116']['ticket']
            self.assertTrue(ticket.done.wait(3))
        result = self.poll()
        tab = next(row for row in result['tabs'] if row['target'] == 'vlan116')
        self.assertIn('fixture close refused', tab['state'])
        with self.assertRaises(CapabilityError):
            self.call('detach')
        self.assertFalse(driver.closed)
        self.assertTrue(self.manager.diagnostic_state('COM216')['closing_in_program'])
        self.assertIs(self.manager.existing_session(SerialSettings('COM222')), other)
        self.assertNotIn('STATE 串口已关闭', session.log_path.read_text(encoding='utf-8'))
        self.assertFalse(driver.writes or self.harness.drivers['COM222'].writes)

    def test_close_failure_remains_visible_and_blocks_reopen_and_shutdown(self):
        self.call('open_all')
        session = self.harness.sessions['COM216']
        original = session.close
        def fail_after_driver_closed():
            original()
            raise OSError('fixture close not confirmed')
        with patch.object(session, 'close', side_effect=fail_after_driver_closed):
            self.call('close_tab', dict(target='vlan116'))
            self.wait(lambda: self.manager._closing['COM216'].done.is_set())
        result = self.poll()
        self.assertIn('关闭失败', result['tabs'][0]['state'])
        self.assertIn('vlan116', self.terminal.tabs)
        self.assertIn('vlan116', self.call('open_all')['failures'])
        with self.assertRaises(CapabilityError):
            self.call('detach')
        with self.assertRaises(CapabilityError):
            self.terminal.shutdown()

    def test_failed_release_restores_subscription_with_new_identity(self):
        self.call('open_all')
        previous = self.terminal.tabs['vlan116']['delivery']
        with patch.object(self.manager, 'release', side_effect=OSError('fixture owner not released')):
            with self.assertRaises(OSError):
                self.call('close_tab', dict(target='vlan116'))
        item = self.terminal.tabs['vlan116']
        self.assertIsNot(item['delivery'], previous)
        self.assertTrue(previous.invalid.is_set())
        item['delivery'](SerialEvent('COM216', 'RX', b'new', 'replacement-data'))
        self.assertIn('replacement-data', self.poll()['tabs'][0]['text'])

    def test_partial_detach_can_retry_without_releasing_another_monitor(self):
        self.call('open_all')
        settings = SerialSettings('COM216')
        shared = self.manager.acquire_monitor('other-monitor', settings)
        import threading
        start = threading.Thread.start
        def reject_second(worker):
            if worker.name == 'serial-close-COM222':
                raise RuntimeError('fixture release refused')
            start(worker)

        with patch.object(threading.Thread, 'start', reject_second):
            with self.assertRaisesRegex(CapabilityError, 'COM222 停止请求未受理，原监控继续') as refused:
                self.call('detach')
        self.assertEqual(refused.exception.code, 'serial_release_refused')
        self.assertIs(self.manager.existing_session(SerialSettings('COM222')), self.harness.sessions['COM222'])
        self.assertFalse(self.manager.diagnostic_state('COM222')['closing_in_program'])
        snapshot = self.poll()
        self.assertFalse(snapshot['closing'])
        self.assertEqual(snapshot['token'], self.token)
        self.assertEqual([tab['port'] for tab in snapshot['tabs']], ['COM222'])
        self.assertTrue(snapshot['tabs'][0]['monitoring'])
        self.call('detach')
        self.wait(lambda: not self.poll()['token'])
        self.assertTrue(self.harness.drivers['COM222'].closed)
        self.assertIs(self.manager.existing_session(settings), shared)
        self.assertFalse(self.harness.drivers['COM216'].closed)

    def test_existing_different_serial_settings_are_not_silently_reconfigured(self):
        session = self.manager.acquire_monitor('existing-fixture', SerialSettings('COM216', baudrate=9600))
        result = self.call('open_all')
        self.assertNotIn('vlan116', result['failures'])
        self.assertIs(self.manager.existing_session(SerialSettings('COM216', baudrate=9600)), session)
        self.assertEqual(session.settings.baudrate, 9600)
        self.assertEqual(result['tabs'][0]['path'], '')
        self.assertIn('未启用文件落盘', result['tabs'][0]['state'])
        preview = self.call('preview_send', dict(target='vlan116', text='fixture same settings'))
        self.call('send', dict(confirmation=preview['confirmation']))
        self.assertEqual(self.harness.drivers['COM216'].writes, [b'fixture same settings\r'])
        self.assertEqual(session.settings.baudrate, 9600)

    def test_stale_window_token_cannot_stop_or_send(self):
        self.call('open_all')
        for suffix, values in (('stop_all', {}), ('preview_send', dict(target='vlan116', text='reboot'))):
            with self.assertRaises(CapabilityError):
                self.call(suffix, dict(token='0' * 32, **values))
        self.assertFalse(self.harness.drivers['COM216'].writes)
        self.assertIsNotNone(self.manager.existing_session(SerialSettings('COM216')))

    def test_write_failure_releases_only_manual_control_and_never_retries(self):
        preview = self.call('preview_send', dict(target='vlan116', text='fixture command'))
        with patch.object(self.harness.drivers['COM216'], 'write', side_effect=OSError('fixture failed write')) as write:
            with self.assertRaises(RuntimeError):
                self.call('send', dict(confirmation=preview['confirmation']))
            with self.assertRaises(CapabilityError):
                self.call('send', dict(confirmation=preview['confirmation']))
        self.assertEqual(write.call_count, 1)
        self.assertTrue(self.manager.manual_writable('COM216'))
        self.assertTrue(self.manager.existing_session(SerialSettings('COM216')))
        self.assertTrue(any('发送失败' in line and '不自动重发' in line for line in self.logs))

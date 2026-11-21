"""Real upgrade admission and dispatch, with all device engines replaced by fakes."""
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from line_check_assistant.network_ops import CommandResult
from qt_execution_fakes import configure_project
import test_qt_dut_configuration as base
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.serial_models import SerialEvent
from src.models.upgrade_stop import UpgradeStoppedResult
from src.services.firmware_upgrade_service import dispatch_upgrade
from src.services.web_gateway_upgrade_service import TRANSFER_WEB_GATEWAY


class UpgradeSession:
    """An already-opened engine session. The observer may only subscribe."""

    def __init__(self, port):
        self.settings = SimpleNamespace(port=port)
        self.subscribers = set()

    def subscribe(self, subscriber):
        self.subscribers.add(subscriber)

    def unsubscribe(self, subscriber):
        self.subscribers.remove(subscriber)

    def emit(self, text, sensitive=False):
        for subscriber in tuple(self.subscribers):
            subscriber(SerialEvent(self.settings.port, 'RX', b'', text, sensitive))


class UpgradeHarness:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.finished.set()
        self.success = True
        self.sessions = {}
        self.callbacks = []

    def dispatch(self, requests, manager, **kwargs):
        def fake(method):
            def engine(batch, *_args, max_workers, on_output, stop_control, **callbacks):
                self.calls.append((method, tuple(batch), max_workers))
                on_output('原引擎阶段：模拟固件传输')
                if method != '页面升级' and callbacks.get('on_session_ready'):
                    ready = callbacks['on_session_ready']
                    self.callbacks.append(ready)
                    for request in batch:
                        callbacks['on_item_started'](request)
                        session = self.sessions[request.vlan] = UpgradeSession(request.serial_port)
                        ready(request.vlan, session, request.firmware_path.with_name(request.vlan + '.log'))
                        session.emit('原升级串口模拟输出\n')
                        session.emit('fixture-secret-hidden', sensitive=True)
                self.entered.set()
                if not self.finished.wait(8):
                    raise AssertionError('fake engine not released')
                result = (UpgradeStoppedResult('模拟安全停止') if stop_control.event.is_set()
                          else CommandResult(self.success, '模拟引擎结果'))
                items = [SimpleNamespace(request=request, result=result) for request in batch]
                if callbacks.get('on_item_complete'):
                    for item in items:
                        callbacks['on_item_complete'](item)
                return items
            return engine
        engines = {name: fake(name) for name in ('页面升级', 'Tftp指令', 'Tftp Put', TRANSFER_WEB_GATEWAY)}
        return dispatch_upgrade(requests, manager, engines=engines, **kwargs)


class QtFirmwareUpgradeTests(unittest.TestCase):
    cleanup_runtime = base.QtDutConfigurationTests.cleanup_runtime
    wait = base.QtDutConfigurationTests.wait

    def setUp(self):
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
        base.QtDutConfigurationTests.setUp(self)
        store = SampleUpgradeSettingsStore(self.context.config_dir / 'sample_upgrade_settings.ini')
        store.save(replace(store.load(), username='fake-initial-user', password='fake-initial-password'))
        self.workspace.projects.save(self.context)
        self.harness = UpgradeHarness()
        self.addCleanup(self.harness.finished.set)
        self.execution.capabilities.upgrade_dispatch = self.harness.dispatch
        network = patch('src.services.qt_firmware_upgrade.inspect_upgrade_network', return_value=[])
        self.network = network.start()
        self.addCleanup(network.stop)
        self.firmware = Path(self.temp.name) / 'fixture.bin'
        self.firmware.write_bytes(b'synthetic test firmware')
        self.open()

    def open(self):
        self.window = self.execution.upgrade_command('show', {})
        self.token = self.window['token']

    def command(self, suffix, **kwargs):
        return self.execution.upgrade_command(suffix, dict(token=self.token, **kwargs))

    def preview(self, method='页面升级', path=None, channels=(1, 7), **kwargs):
        args = dict(firmware_path=str(path or self.firmware), channel_ids=list(channels),
                    upgrade_type='页面升级' if method == '页面升级' else '全包升级')
        if method != '页面升级':
            args.update(transfer_method=method, parallel_count=1)
        args.update(kwargs)
        return self.command('preview', upgrade=args)

    def complete(self, pending):
        self.command('execute', confirmation=pending['confirmation'])
        self.wait(lambda: self.execution.idle)
        return self.command('poll')

    def test_four_modes_dispatch_original_requests_and_preserve_page_parallelism(self):
        self.assertEqual([row['number'] for row in self.window['targets']], [1, 7])
        self.network.assert_not_called()
        for method in ('页面升级', 'Tftp指令', 'Tftp Put', TRANSFER_WEB_GATEWAY):
            with self.subTest(method=method):
                pending = self.preview(method, restore_factory=True)
                self.assertIn('SHA256', pending['summary'])
                self.assertIn('恢复出厂：开启', pending['summary'])
                status = self.complete(pending)
                self.assertEqual(status['state'], 'succeeded')
                actual, requests, workers = self.harness.calls[-1]
                self.assertEqual(actual, method)
                self.assertEqual(workers, 2 if method == '页面升级' else 1)
                self.assertEqual([r.vlan for r in requests], ['vlan101', 'vlan107'])
                self.assertTrue(all(r.restore_factory for r in requests))
                self.assertTrue(all(r.firmware_path != self.firmware for r in requests))
                self.assertTrue(all(r.firmware_path.read_bytes() == self.firmware.read_bytes() for r in requests))

    def test_cancel_and_changed_firmware_do_not_admit_a_job(self):
        pending = self.preview()
        self.command('cancel')
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'])
        pending = self.preview()
        self.firmware.write_bytes(b'different synthetic firmware')
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'])
        self.assertEqual(self.harness.calls, [])
        self.assertFalse(self.execution.jobs)
        self.assertFalse(self.execution.capabilities.upgrades.pending)
        self.assertFalse(self.execution.capabilities.upgrades.confirmed)

    def test_revised_project_and_non_gui_authority_are_rejected(self):
        pending = self.preview()
        old = CapabilityAuthority('test-local', 'session', 'operation', (), source='local')
        with self.assertRaisesRegex(CapabilityError, '来源'):
            self.execution.capabilities.execute('firmware.editor.show', {}, old)
        profile = self.context.config_dir / 'test_project_config.ini'
        profile.write_bytes(profile.read_bytes() + b'\n# changed\n')
        self.workspace.projects.save(self.context)
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'])
        self.assertFalse(self.harness.calls)

    def test_stop_reopen_and_release_wait_for_original_worker(self):
        self.harness.finished.clear()
        pending = self.preview('Tftp Put', channels=(7,))
        self.command('execute', confirmation=pending['confirmation'])
        self.assertTrue(self.harness.entered.wait(3))
        old = self.token
        self.command('detach')
        self.open()
        self.assertNotEqual(old, self.token)
        self.assertTrue(self.window['stoppable'])
        self.assertFalse(self.execution.idle)
        self.command('stop')
        self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'stopped')

    def set_power_port(self, port):
        from line_check_assistant.config_store import ChannelConfigStore
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        store.save(store.load(), port)
        self.workspace.projects.save(self.context)

    def test_manual_restart_full_package_modes_keep_empty_power_port_and_original_targets(self):
        self.set_power_port('')
        self.open()
        for method in ('Tftp指令', 'Tftp Put', TRANSFER_WEB_GATEWAY):
            with self.subTest(method=method):
                pending = self.preview(method, channels=(7,))
                self.assertTrue(pending['manual_restart'])
                self.assertIn('CH07', pending['summary'])
                self.assertIn('已重启，继续升级', pending['summary'])
                self.assertIn('SHA256', pending['summary'])
                prior_calls = len(self.harness.calls)
                self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
                self.wait(lambda: self.execution.idle)
                status = self.command('poll')
                self.assertEqual(status['state'], 'succeeded')
                self.assertEqual(len(self.harness.calls), prior_calls + 1)
                actual, requests, workers = self.harness.calls[-1]
                self.assertEqual((actual, workers), (method, 1))
                request, = requests
                self.assertEqual((request.vlan, request.serial_port, request.power_serial_port), ('vlan107', 'COM7', ''))
                if method == TRANSFER_WEB_GATEWAY:
                    self.assertIn(request.web_source_ip, pending['summary'])
                    self.assertIn(request.web_device_ip, pending['summary'])
                else:
                    self.assertIn('192.168.1.107 ↔ 192.168.1.1', pending['summary'])
                job = self.execution.jobs[status['job']]['status']['request']
                self.assertTrue(job['arguments']['manual_restart_confirmed'])
                self.assertIn('serial:COM7', job['resources'])
                self.assertFalse(any(resource.startswith('power:') for resource in job['resources']))
        page = self.preview()
        self.assertFalse(page['manual_restart'])
        self.assertEqual(self.complete(page)['state'], 'succeeded')

    def test_manual_restart_requires_explicit_acknowledgement_and_stays_bound_to_power_and_firmware(self):
        self.set_power_port('')
        self.open()
        pending = self.preview('Tftp Put')
        with self.assertRaises(CapabilityError) as error:
            self.command('execute', confirmation=pending['confirmation'])
        self.assertEqual(error.exception.code, 'manual_restart_confirmation_required')
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
        pending = self.preview('Tftp Put')
        self.command('cancel')
        self.open()
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
        pending = self.preview('Tftp Put')
        self.firmware.write_bytes(b'changed fixture')
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
        pending = self.preview('Tftp Put')
        self.set_power_port('COM102')
        with self.assertRaises(CapabilityError):
            self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
        self.assertFalse(self.harness.calls)
        self.assertFalse(self.execution.jobs)

    def test_manual_restart_stays_local_and_standard_capability_rejects_absent_power(self):
        self.set_power_port('')
        self.open()
        pending = self.preview('Tftp Put', channels=(7,))
        request = dict(token=self.token, confirmation=pending['confirmation'], manual_restart_confirmed=True)
        upgrade = dict(upgrade_type='全包升级', firmware_path=str(self.firmware), channel_ids=[7])
        service = self.execution.capabilities
        for source in ('local', 'dingtalk', 'feishu', 'gui'):
            authority = CapabilityAuthority(source, 'session', 'operation', (7,), source=source, approved=True)
            if source != 'gui':
                with self.assertRaises(CapabilityError) as error:
                    service.execute('firmware.editor.execute', request, authority)
                self.assertEqual(error.exception.code, 'source_forbidden')
            with self.assertRaises(CapabilityError) as error:
                service.execute('firmware.upgrade', upgrade, authority)
            self.assertEqual(error.exception.code, 'manual_restart_required')
            with self.assertRaises(CapabilityError) as error:
                service.execute('firmware.upgrade', dict(upgrade, manual_restart_confirmed=True), authority)
            self.assertEqual(error.exception.code, 'invalid_parameters')
        self.assertFalse(self.harness.calls)

    def test_manual_restart_wait_preserves_confirmation_until_operator_finishes_and_stop_waits_for_engine(self):
        self.set_power_port('')
        self.open()
        self.harness.finished.clear()
        pending = self.preview('Tftp Put', channels=(7,))
        self.execution.upgrade.pending = replace(self.execution.upgrade.pending, created=-1000)
        self.command('execute', confirmation=pending['confirmation'], manual_restart_confirmed=True)
        self.assertTrue(self.harness.entered.wait(3))
        self.command('stop')
        self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'stopped')

    def test_manual_restart_confirmation_does_not_replace_network_preflight(self):
        self.set_power_port('')
        self.open()
        self.network.return_value = ['模拟源地址冲突']
        with self.assertRaises(CapabilityError) as error:
            self.preview('Tftp Put')
        self.assertEqual(error.exception.code, 'network_conflict')
        self.assertFalse(self.harness.calls)

    def _settings(self):
        return dict(self.window['defaults'], username='fake-upgrade-user', password='fake-private-password',
                    firmware_path=str(self.firmware), parallel_count=3, restore_factory=True)

    def test_blank_profile_blocks_preview_before_network_check(self):
        self.command('save', settings=dict(self._settings(), password=' '))
        with self.assertRaises(CapabilityError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'configuration_incomplete')
        self.network.assert_not_called()
        self.assertFalse(self.harness.calls)

    def test_save_uses_original_store_and_keeps_parameter_fields(self):
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
        store = SampleUpgradeSettingsStore(self.context.config_dir / 'sample_upgrade_settings.ini')
        original = replace(store.load(), parameter_initial_username='existing-parameter-user',
                           parameter_initial_password='existing-parameter-pass', parameter_parallel_count=7,
                           power_operation='down', parameter_table_path=str(self.firmware))
        store.save(original)
        self.workspace.projects.save(self.context)
        self.open()
        self.command('save', settings=self._settings())
        self.assertEqual(store.load(), replace(original, **self._settings()))
        self.assertFalse(self.workspace.projects.dirty(self.context))
        self.assertFalse(self.harness.calls)
        self.network.assert_not_called()
        self.assertNotIn('fake-private-password', '\n'.join(row.message for row in self.logs))
        self.open()
        self.assertEqual(self.window['password'], 'fake-private-password')
        self.assertEqual(self.complete(self.preview())['state'], 'succeeded')
        self.assertTrue(all(request.password == 'fake-private-password' for request in self.harness.calls[-1][1]))

    def test_save_commit_failure_restores_original_bytes(self):
        path = self.context.config_dir / 'sample_upgrade_settings.ini'
        original = path.read_bytes() if path.exists() else None
        with patch.object(self.workspace.projects, 'save', side_effect=OSError('fake write error')):
            with self.assertRaises(CapabilityError) as error:
                self.command('save', settings=self._settings())
        self.assertEqual(error.exception.code, 'configuration_save_failed')
        self.assertEqual(path.read_bytes() if path.exists() else None, original)
        self.assertFalse(self.workspace.projects.dirty(self.context))
        self.assertFalse(self.workspace.resources.owners)

    def test_full_upgrade_observes_original_session_without_owning_it(self):
        self.harness.finished.clear()
        pending = self.preview('Tftp Put', channels=(7,))
        self.command('execute', confirmation=pending['confirmation'])
        self.assertTrue(self.harness.entered.wait(3))
        batch = pending['confirmation']
        self.assertEqual(self.execution.upgrade.observation.serial.log_id, batch)
        self.assertEqual(self.command('poll')['items'][0]['state'], 'running')
        self.command('detach')
        active = self.execution.upgrade_command('logs', dict(batch=batch, active='vlan107'))
        self.assertFalse(active['closed'])
        tab, = active['tabs']
        self.assertEqual((tab['vlan'], tab['port']), ('vlan107', 'COM7'))
        self.assertTrue(tab['path'].endswith('vlan107.log'))
        self.assertIn('原升级串口模拟输出', tab['text'])
        self.assertNotIn('fixture-secret-hidden', tab['text'])
        session = self.harness.sessions['vlan107']
        self.assertEqual(len(session.subscribers), 1)
        old_delivery, = session.subscribers
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertFalse(session.subscribers)
        self.assertTrue(old_delivery.invalid.is_set())
        self.assertTrue(self.execution.upgrade_command('logs', dict(batch=batch, active='vlan107'))['closed'])
        late = self.harness.callbacks[-1]
        self.open()
        self.harness.entered.clear()
        self.harness.finished.clear()
        following = self.preview('Tftp Put', channels=(7,))
        self.command('execute', confirmation=following['confirmation'])
        self.assertTrue(self.harness.entered.wait(3))
        late('vlan107', session, Path('expired.log'))
        self.assertFalse(session.subscribers)
        current = self.execution.upgrade_command('logs', dict(batch=following['confirmation'], active='vlan107'))
        self.assertNotIn('expired.log', current['tabs'][0]['path'])
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)

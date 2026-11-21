"""Write through the real Job/admission boundary with a simulated equipment runner."""
from dataclasses import asdict, replace
from pathlib import Path
import threading
import unittest

from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
from src.core.sample_parameter_table import load_parameter_records, save_parameter_records_xlsx
from src.models.capabilities import CapabilityError
from src.models.sample_parameter_models import SampleParameterItemResult, SampleParameterRecord
from src.services.sample_parameter_application_service import run_sample_parameter_batch
import test_qt_dut_configuration as base
from test_qt_firmware_upgrade import UpgradeSession
from test_sample_parameter_service import values
from test_sample_parameter_table import template


def make_table(path):
    save_parameter_records_xlsx(path, [SampleParameterRecord(vlan, values(), 2) for vlan in ('vlan101', 'vlan107')])
    return path


def use_serial_fallback(workspace, context):
    store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
    channels = store.load()
    for channel in channels:
        channel.network_card_ip = ''
    store.save(channels, store.load_power_serial_port())
    workspace.projects.save(context)


class ParameterHarness:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = set()

    def run(self, requests, parallel, cancel, manager, network, emit, *, on_session_ready=None):
        self.calls.append((tuple(requests), parallel, dict(network)))
        emit('模拟写参服务已开始')
        self.entered.set()
        if not self.release.wait(12):
            raise AssertionError('测试未释放模拟写参服务')
        return [SampleParameterItemResult(request, request.vlan not in self.fail and not cancel.is_set(),
                    '模拟工厂模式清理完成' if cancel.is_set() else '模拟读回结果',
                    written_count=0 if cancel.is_set() else 15, cancelled=cancel.is_set()) for request in requests]


class ParameterSerialHarness(ParameterHarness):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.sessions = {}
        self.callbacks = []

    def run(self, requests, parallel, cancel, manager, network, emit, *, on_session_ready=None):
        if any(request.bind_ip and request.device_host for request in requests):
            raise AssertionError('fixture must use the serial fallback only')

        def serial_runner(batch, serial_manager, *, parallel_count, on_output, on_session_ready, cancel_event):
            self.callbacks.append(on_session_ready)
            for request in batch:
                session = UpgradeSession(request.serial_port)
                self.sessions[request.vlan] = session
                session.log_path = self.root / f'parameters-{request.vlan}.log'
                on_session_ready(request.vlan, session, Path('original-default-path.log'))
                session.emit(f'{request.vlan} 原写参串口模拟输出\n')
                session.emit('fixture-hidden-serial-write', sensitive=True)
            return super(ParameterSerialHarness, self).run(
                batch, parallel_count, cancel_event, serial_manager, network, on_output)

        return run_sample_parameter_batch(requests, parallel, cancel, manager, network, emit,
            on_session_ready=on_session_ready, serial_runner=serial_runner)


class QtParameterWriterTests(unittest.TestCase):
    cleanup_runtime = base.QtDutConfigurationTests.cleanup_runtime
    wait = base.QtDutConfigurationTests.wait

    def setUp(self):
        base.QtDutConfigurationTests.setUp(self)
        self.harness = ParameterHarness()
        self.addCleanup(self.harness.release.set)
        self.execution.capabilities.parameters.runner = self.harness.run
        self.store = SampleUpgradeSettingsStore(self.context.config_dir / 'sample_upgrade_settings.ini')
        self.store.save(replace(self.store.load(), username='upgrade-unchanged', password='upgrade-private',
            parameter_initial_username='parameter-user', parameter_initial_password='test-password'))
        self.workspace.projects.save(self.context)
        self.table = make_table(Path(self.temp.name) / 'parameters.xlsx')
        self.open()

    def open(self):
        self.window = self.execution.parameter_command('show', {})
        self.token = self.window['token']

    def command(self, suffix, **kwargs):
        return self.execution.parameter_command(suffix, dict(token=self.token, **kwargs))

    def selection(self, **other):
        options = dict(channel_ids=[7], table_path=str(self.table), parallel_count=2,
                       clear_parameters=False, exit_aging=False)
        options.update(other)
        return options

    def preview(self, **other):
        return self.command('preview', selection=self.selection(**other))

    def test_confirmation_cancel_stale_version_and_table_edit_never_dispatch(self):
        preview = self.preview(clear_parameters=True)
        self.assertIn('清空参数：启用', preview['summary'])
        self.assertIn('退出老化：跳过', preview['summary'])
        self.assertIn('vlan107 / COM7', preview['summary'])
        self.assertNotIn('test-password', str(preview))
        self.command('cancel')
        with self.assertRaisesRegex(CapabilityError, '失效'):
            self.command('execute', confirmation=preview['confirmation'])
        preview = self.preview()
        self.table.write_bytes(self.table.read_bytes() + b'changed')
        with self.assertRaisesRegex(CapabilityError, '发生变化'):
            self.command('execute', confirmation=preview['confirmation'])
        make_table(self.table)
        preview = self.preview()
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, '配置变化'):
            self.command('execute', confirmation=preview['confirmation'])
        self.assertFalse(self.harness.calls)
        self.assertTrue(self.execution.idle)

    def test_original_runner_options_and_independent_target_failures(self):
        self.harness.fail.add('vlan107')
        pending = self.preview(channel_ids=[1, 7], clear_parameters=True, exit_aging=True)
        self.command('execute', confirmation=pending['confirmation'])
        self.wait(lambda: self.execution.idle)
        status = self.command('poll')
        self.assertEqual([(x['vlan'], x['ok']) for x in status['items']], [('vlan101', True), ('vlan107', False)])
        requests, count, network = self.harness.calls[0]
        self.assertEqual(count, 2)
        self.assertEqual([req.serial_port for req in requests], ['COM1', 'COM7'])
        self.assertTrue(all(req.clear_parameters and req.exit_aging for req in requests))
        self.assertTrue(all(req.initial_password == 'test-password' for req in requests))
        self.assertEqual(set(network), {'vlan101', 'vlan107'})
        self.assertNotIn('test-password', str(status))
        self.assertEqual(self.execution.parameter_writer.serial.log_id, '')

    def test_original_serial_fallback_observes_each_session_and_rejects_late_callbacks(self):
        use_serial_fallback(self.workspace, self.context)
        self.open()
        harness = ParameterSerialHarness(Path(self.temp.name))
        self.addCleanup(harness.release.set)
        self.execution.capabilities.parameters.runner = harness.run
        harness.release.clear()
        token = self.preview(channel_ids=[1, 7])['confirmation']
        self.command('execute', confirmation=token)
        self.assertTrue(harness.entered.wait(5))
        ctl = self.execution.parameter_command
        self.assertEqual(self.execution.parameter_writer.serial.log_id, token)
        active = ctl('logs', dict(batch=token, active='vlan101'))
        self.assertEqual([(x['vlan'], x['port']) for x in active['tabs']],
                         [('vlan101', 'COM1'), ('vlan107', 'COM7')])
        self.assertTrue(active['tabs'][0]['path'].endswith('parameters-vlan101.log'))
        self.assertIn('vlan101 原写参串口', active['tabs'][0]['text'])
        self.assertNotIn('fixture-hidden-serial-write', str(active))
        self.assertEqual(active['tabs'][1]['text'], '')
        following = ctl('logs', dict(batch=token, active='vlan107'))
        self.assertIn('vlan107 原写参串口', following['tabs'][1]['text'])
        session = harness.sessions['vlan107']
        delivery, = session.subscribers
        manual = lambda event: None
        session.subscribe(manual)
        self.command('detach')
        self.assertFalse(ctl('logs', dict(batch=token, active='vlan107'))['closed'])
        harness.release.set()
        self.wait(lambda: self.execution.idle)
        self.assertTrue(delivery.invalid.is_set())
        self.assertTrue(ctl('logs', dict(batch=token, active='vlan107'))['closed'])
        self.assertEqual(session.subscribers, {manual})

        self.open()
        harness.entered.clear()
        harness.release.clear()
        new = self.preview()['confirmation']
        self.command('execute', confirmation=new)
        self.assertTrue(harness.entered.wait(5))
        harness.callbacks[0]('vlan107', session, Path('expired.log'))
        self.assertEqual(session.subscribers, {manual})
        self.assertNotIn('expired.log', str(ctl('logs', dict(batch=new, active='vlan107'))))
        self.command('stop')
        self.assertFalse(self.execution.idle)
        harness.release.set()
        self.wait(lambda: self.execution.idle)
        self.assertFalse(harness.sessions['vlan107'].subscribers)

    def test_stop_waits_for_original_cleanup_and_result_survives_reopen(self):
        self.harness.release.clear()
        pending = self.preview()
        self.command('execute', confirmation=pending['confirmation'])
        self.assertTrue(self.harness.entered.wait(5))
        self.command('stop')
        self.assertFalse(self.execution.idle)
        self.command('detach')
        self.open()
        self.assertTrue(self.window['active'])
        self.harness.release.set()
        self.wait(lambda: self.execution.idle)
        self.assertTrue(self.command('poll')['items'][0]['cancelled'])

    def test_setting_updates_preserve_upgrade_profile_and_load_real_table(self):
        result = self.command('select_table', selection=self.selection(parallel_count=8))
        self.assertTrue(result['ok'])
        self.assertEqual(self.store.load().parameter_table_path, str(self.table))
        self.assertEqual(self.store.load().parameter_parallel_count, 1)
        settings = dict(self.window['settings'], table_path=str(self.table), parallel_count=4,
                        initial_username=' other-user ', exit_aging=True)
        self.command('save', settings=settings)
        self.command('detach')
        self.open()
        self.assertEqual(self.window['settings']['table_path'], str(self.table))
        self.assertEqual(self.window['settings']['parallel_count'], 4)
        self.assertEqual(self.window['settings']['initial_username'], 'other-user')
        self.assertEqual(self.store.load().username, 'upgrade-unchanged')
        self.assertEqual(self.store.load().password, 'upgrade-private')
        data = self.command('preflight', selection=self.selection())
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['warnings']), 1)

    def test_missing_target_host_uses_original_project_host_without_changing_transport(self):
        from line_check_assistant.config_store import ChannelConfigStore
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        channels = store.load()
        target = next(channel for channel in channels if channel.section == 'channel_7')
        target.device_manage_ip = ''
        store.save(channels)
        self.workspace.projects.save(self.context)
        self.open()
        pending = self.preview()
        self.command('execute', confirmation=pending['confirmation'])
        self.wait(lambda: self.execution.idle)
        requests, _, _ = self.harness.calls[0]
        self.assertEqual(requests[0].device_host, next(c.device_manage_ip for c in channels if c.device_manage_ip))
        self.assertTrue(requests[0].factory_device_host)

    def test_generate_uses_original_rules_and_local_path(self):
        target = Path(self.temp.name) / 'operator' / 'sample.xlsx'
        target.parent.mkdir()
        result = self.command('generate', channel_ids=[1, 7], template=asdict(template()), output_path=str(target))
        self.assertEqual(result['count'], 2)
        self.assertEqual([row.vlan for row in load_parameter_records(target)], ['vlan101', 'vlan107'])
        self.assertFalse(self.harness.calls)

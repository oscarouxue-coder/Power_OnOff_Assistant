"""Two Windows processes, temporary ownership DB, simulated interfaces and device callbacks."""
import multiprocessing
import os
from shutil import copy2
from contextlib import ExitStack
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.core.host_resource_lock import HostResourceBusy
from src.models.capabilities import CapabilityError
from src.models.project_profile import dut_resource_keys
from src.services.project_profile_store import read_project_profile
from src.services.project_store import ProjectStore
from src.services.standalone_power_project import StandalonePowerProject
from src.services.device_project_info_service import DeviceProjectInfo
from src.services.pipeline_orchestrator import PipelineContext, PipelineOrchestrator
from src.services.pipeline_runtime import PipelineRun, run_pipeline
from src.services.physical_resource_guards import _power_admission
from src.services.host_resource_fence import HostResourceFence
from src.services.resource_lease_service import ResourceLeaseService
from src.services.workspace_resources import WorkspaceResources
from test_legacy_power_test_service import _write_config_tree
from test_standalone_power_project import fixture_project


def _adapter(source, index):
    return dict(name='fixture-' + uuid4().hex, guid=str(uuid4()), index=index, up=True,
                addresses=[(source, 24)])


def _fake_power_worker(request, messages, child_stop, controls, run_id, *rest):
    signals = Path(os.environ['DUTPILOT_FAKE_EXIT_DIR'])
    messages.put(dict(type='result', run_id=run_id, ok=True, detail='fixture result'))
    deadline = time.monotonic() + 10
    while not (signals / 'finish-cleanup').exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('fixture worker cleanup timed out')
        time.sleep(.02)
    (signals / 'exiting').touch()


def _pipeline_child(folder, project_root, inventory, mode, connection, stop):
    binding = None
    try:
        binding = StandalonePowerProject.open(ProjectStore(Path(folder) / 'source'), project_root)
        project = binding.context
        store = ChannelConfigStore(project.config_dir / 'network_card_ip.ini')
        app = SimpleNamespace(project_context=project, store=store, channels=store.load(),
                              power_serial_port=store.load_power_serial_port())
        root = project.saved_root / 'Auto_power_on_off_tool'
        run = PipelineRun(1, stop=stop)
        context = PipelineContext(app, app.channels, None, None, legacy_tool_root=root, stop_event=stop)
        binding.prepare_run(app, context)
        events = []

        def version(request, emit):
            events.append('precheck')
            if mode == 'pause_precheck':
                connection.send(('precheck', tuple(events)))
                if not connection.poll(12) or connection.recv() != 'continue':
                    raise RuntimeError('fixture precheck timed out')
            if mode == 'precheck_failure':
                raise RuntimeError('fixture precheck failure')
            return DeviceProjectInfo('fixture', 'fixture', 'fixture')

        def execute(*args, **kwargs):
            events.append('control')
            connection.send(('inflight', tuple(events)))
            if not connection.poll(12) or connection.recv() != 'release':
                raise RuntimeError('fixture did not allow cleanup')
            events.append('worker_exited')
            return SimpleNamespace(ok=True, detail='fixture')

        def environment(_):
            events.append('environment')
            if mode == 'rebind':
                inventory[0]['guid'] = str(uuid4())

        with ExitStack() as stack:
            stack.enter_context(patch('src.services.physical_resource_guards.adapters_ipv4', return_value=inventory))
            stack.enter_context(patch('src.services.physical_resource_guards.host_resource_directory',
                                      return_value=Path(folder) / 'owners'))
            stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('external I/O')))
            stack.enter_context(patch('src.services.pipeline_orchestrator.query_device_project_info', side_effect=version))
            if mode == 'worker_exit':
                stack.enter_context(patch.dict(os.environ, DUTPILOT_FAKE_EXIT_DIR=str(Path(folder) / 'tool')))
                def observe(message):
                    if message['type'] == 'result':
                        connection.send(('terminal_received', (Path(folder) / 'tool/exiting').exists()))
                context.app._observe_ai_power_event = observe
                stack.enter_context(patch('src.services.legacy_power_test_service._legacy_start_all_worker',
                                          _fake_power_worker))
            else:
                stack.enter_context(patch('src.services.legacy_power_test_service.run_legacy_power_test', side_effect=execute))
            stack.enter_context(patch.object(PipelineOrchestrator, '_run_env_check', environment))
            # Same worker entry as the compatibility window following local confirmation.
            run_pipeline(context, {'legacy_power_test', 'env_check'}, None, run, lambda _: None)
            connection.send(('done', tuple(events), run.outcome[1]))
    finally:
        if binding is not None:
            binding.store.close(binding.context)
        connection.close()


@unittest.skipUnless(os.name == 'nt', 'Windows 跨进程资源所有权')
class CompatibilityPowerAdmissionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.tool = _write_config_tree(self.root / 'tool', serial_port='COM897002')
        with (self.tool / 'config/test_project_config.ini').open('a', encoding='utf8') as stream:
            stream.write('\n[project_info]\nsoftware_version=fixture\ninternal_software_version=fixture\nonu_compile_time=fixture\n')
        self.a = _adapter('192.0.2.5', 5)
        self.b = _adapter('192.0.2.8', 8)
        self.hardware = 'asset-' + uuid4().hex
        self.resources = WorkspaceResources(self.root / 'owners')
        self.addCleanup(self.resources.close)
        self.queries = ResourceLeaseService(coordinator=self.resources, project_id='fixture-query', project_name='查询')

    def start(self, *, source='192.0.2.5', alias='', vlan='', inventory=None, mode='normal', extra='', rows=None):
        text = ('[power_supply]\nserial_port=COM897002\n[channel_5]\nenabled=1\n'
                f'network_card_ip={source}\ndevice_manage_ip=192.0.2.1\nadapter_alias={alias}\nvlan_name={vlan}\n' + extra)
        (self.tool / 'config/network_card_ip.ini').write_text(text, encoding='utf8')
        channels = ChannelConfigStore(self.tool / 'config/network_card_ip.ini').load()
        if rows is None:
            rows = [dict(label='CH05', channel=5, hardware_id=self.hardware)]
            if any(c.section == 'channel_8' for c in channels):
                rows.append(dict(label='CH08', channel=8, hardware_id=self.hardware + '-8'))
        project_root = self.root / uuid4().hex
        source_root = self.root / 'source'
        fixture_project(source_root, project_root, rows, channels, port='COM897002')
        store = ProjectStore(source_root)
        project = store.open(project_root)
        try:
            for path in (self.tool / 'config').iterdir():
                copy2(path, project.config_dir / path.name)
            store.save(project)
            self.project_id = project.identity.project_id
            self.dut_keys = set(dut_resource_keys(read_project_profile(project.config_dir)['duts']))
        finally:
            store.close(project)
        ctx = multiprocessing.get_context('spawn')
        self.stop = ctx.Event()
        self.pipe, child = ctx.Pipe()
        self.addCleanup(self.pipe.close)
        self.process = ctx.Process(target=_pipeline_child, args=(
            self.root, project_root, [self.a, self.b] if inventory is None else inventory, mode, child, self.stop))
        self.process.start()
        child.close()
        self.addCleanup(self.finish_process, self.process)

    def finish_process(self, proc):
        proc.join(2)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)

    def receive(self):
        self.assertTrue(self.pipe.poll(10), 'fixture worker did not reach the expected boundary')
        return self.pipe.recv()

    def assert_done(self, events, *, failed):
        stage, actual, error = self.receive()
        self.assertEqual((stage, actual), ('done', events), error)
        self.assertEqual(bool(error), failed, error)
        self.process.join(5)
        self.assertEqual(self.process.exitcode, 0)
        return error

    def assert_held(self):
        keys = {'adapter:' + self.a[f] for f in ('name', 'guid')}
        keys.update(self.dut_keys)
        entries = self.resources.lease_entries()
        self.assertTrue(keys <= {row.resource_key for row in entries})
        self.assertEqual(len({row.owner_id for row in entries}), 1)
        self.assertTrue(all(row.owner_id.startswith('gui:legacy-power:') for row in entries))
        for key in keys:
            with self.assertRaises((CapabilityError, HostResourceBusy)):
                self.queries.acquire('other', [key])

    def test_query_first_blocks_even_source_only_before_any_work(self):
        for alias, key in (('', self.a['guid']), (self.a['name'] + ' [Up]', self.a['name'])):
            with self.subTest(alias=alias), self.queries.lease('query', ['adapter:' + key]):
                self.start(alias=alias)
                self.assert_done((), failed=True)
                self.assertEqual({e.owner_id for e in self.resources.lease_entries()}, {'query'})
        self.assertFalse(self.resources.lease_entries())

    def test_owner_visible_until_normal_worker_exit_and_independent_adapter_available(self):
        self.start(alias=self.a['name'].upper() + ' [Up]', vlan=self.a['name'])
        self.assertEqual(self.receive(), ('inflight', ('environment', 'precheck', 'control')))
        self.assert_held()
        with self.queries.lease('independent', ['adapter:' + self.b['guid']]):
            self.assertIn('independent', {e.owner_id for e in self.resources.lease_entries()})
        self.pipe.send('release')
        self.assert_done(('environment', 'precheck', 'control', 'worker_exited'), failed=False)
        self.assertFalse(self.resources.lease_entries())
        with self.queries.lease('again', ['adapter:' + self.a['guid']]):
            self.assertTrue(self.resources.lease_entries())

    def test_cancel_does_not_release_until_worker_returns(self):
        self.start()
        self.assertEqual(self.receive()[0], 'inflight')
        self.stop.set()
        self.assert_held()
        self.pipe.send('release')
        self.assert_done(('environment', 'precheck', 'control', 'worker_exited'), failed=False)
        self.assertFalse(self.resources.lease_entries())

    def test_cancel_during_precheck_retains_lock_and_never_reaches_control(self):
        self.start(mode='pause_precheck')
        self.assertEqual(self.receive(), ('precheck', ('environment', 'precheck')))
        self.stop.set()
        self.assert_held()
        self.pipe.send('continue')
        self.assert_done(('environment', 'precheck'), failed=True)
        self.assertFalse(self.resources.lease_entries())

    def test_terminal_result_from_live_child_retains_lease_until_process_join(self):
        self.start(mode='worker_exit')
        self.assertEqual(self.receive(), ('terminal_received', False))
        try:
            self.assert_held()
        finally:
            (self.tool / 'finish-cleanup').touch()
        self.assert_done(('environment', 'precheck'), failed=False)
        self.assertTrue((self.tool / 'exiting').is_file())
        self.assertFalse(self.resources.lease_entries())

    def test_multichannel_admission_is_all_or_none(self):
        extra = '[channel_8]\nenabled=1\nnetwork_card_ip=192.0.2.8\ndevice_manage_ip=192.0.2.1\n'
        with self.queries.lease('query', ['adapter:' + self.b['guid']]):
            self.start(extra=extra)
            self.assert_done((), failed=True)
            self.assertEqual({r.owner_id for r in self.resources.lease_entries()}, {'query'})
        self.start(extra=extra)
        self.assertEqual(self.receive(), ('inflight', ('environment', 'precheck', 'precheck', 'control')))
        rows = self.resources.lease_entries()
        self.assertEqual(len({r.owner_id for r in rows}), 1)
        self.assertEqual({r.resource_key for r in rows},
                         self.dut_keys | {'adapter:' + nic[k] for nic in (self.a, self.b) for k in ('name', 'guid')})
        self.pipe.send('release')
        self.assert_done(('environment', 'precheck', 'precheck', 'control', 'worker_exited'), failed=False)
        self.assertFalse(self.resources.lease_entries())

    def test_bad_or_ambiguous_binding_runs_no_work(self):
        for options in (dict(source='192.0.2.99'), dict(alias=self.b['name']), dict(vlan=self.b['name']),
                        dict(inventory=[self.a, dict(self.b, addresses=self.a['addresses'])]),
                        dict(inventory=[self.a, dict(self.b, name=self.a['name'])]),
                        dict(inventory=[dict(self.a, up=False)]), dict(inventory=[dict(self.a, guid='')]),
                        dict(extra='[channel_05]\nenabled=1\nnetwork_card_ip=192.0.2.8\n'),
                        dict(extra='[channel_6]\nenabled=1\nnetwork_card_ip=192.0.2.5\n')):
            with self.subTest(options=options):
                self.start(**options)
                self.assert_done((), failed=True)
                self.assertFalse(self.resources.lease_entries())

    def test_precheck_failure_releases_and_never_starts_control(self):
        self.start(vlan=self.a['name'], mode='precheck_failure')
        self.assert_done(('environment', 'precheck'), failed=True)
        with self.queries.lease('again', ['adapter:' + self.a['guid']]):
            self.assertTrue(self.resources.lease_entries())

    def test_binding_changed_during_environment_check_blocks_precheck(self):
        self.start(mode='rebind')
        self.assert_done(('environment',), failed=True)
        self.assertFalse(self.resources.lease_entries())

    def other_project_keys(self, hardware):
        root = self.root / uuid4().hex
        fixture_project(self.root / 'source', root,
                        [dict(channel=5, label='CH05', hardware_id=hardware)],
                        [ChannelConfig('channel_5', network_card_ip=self.b['addresses'][0][0],
                                       adapter_alias=self.b['name'])])
        store = ProjectStore(self.root / 'source')
        project = store.open(root)
        try:
            rows = read_project_profile(project.saved_root / 'Auto_power_on_off_tool/config')['duts']
            return set(dut_resource_keys(rows)) | {'adapter:' + self.b[key] for key in ('guid', 'name')}
        finally:
            store.close(project)

    def test_same_physical_dut_on_other_nic_conflicts_in_both_orders(self):
        keys = self.other_project_keys(self.hardware.upper())
        with self.queries.lease('other-project', keys):
            self.start()
            self.assert_done((), failed=True)
            self.assertEqual({e.owner_id for e in self.resources.lease_entries()}, {'other-project'})
        self.start()
        self.assertEqual(self.receive()[0], 'inflight')
        try:
            self.assertEqual(keys & self.dut_keys, {'dut:hardware:' + self.hardware})
            self.assert_held()
            with self.assertRaises((CapabilityError, HostResourceBusy)):
                self.queries.acquire('other-project', keys)
            with self.queries.lease('independent', self.other_project_keys(self.hardware + '-independent')):
                self.assertTrue(self.resources.lease_entries())
        finally:
            self.pipe.send('release')
        self.assert_done(('environment', 'precheck', 'control', 'worker_exited'), failed=False)
        with self.queries.lease('other-project', keys):
            self.assertEqual({e.owner_id for e in self.resources.lease_entries()}, {'other-project'})

    def test_missing_ambiguous_or_conflicting_dut_refuses_before_any_callback(self):
        row = dict(label='CH05', channel=5, hardware_id=self.hardware)
        for rows in ([dict(row, hardware_id='')], [dict(row, channel=3)],
                     [row, dict(row, label='second', channel=8, hardware_id=self.hardware.upper())],
                     [dict(row, network_adapter=self.b['name'])], [dict(row, power_channel='CH04')]):
            with self.subTest(rows=rows):
                self.start(rows=rows)
                error = self.assert_done((), failed=True)
                self.assertIn('核对', error)
                self.assertIn('保存后', error)
                self.assertFalse(self.resources.lease_entries())

    def test_second_dut_busy_leaves_first_dut_and_both_nics_free(self):
        key = 'dut:hardware:' + self.hardware + '-8'
        with self.queries.lease('other', [key]):
            self.start(extra='[channel_8]\nenabled=1\nnetwork_card_ip=192.0.2.8\n')
            self.assert_done((), failed=True)
            self.assertEqual({(e.owner_id, e.resource_key) for e in self.resources.lease_entries()}, {('other', key)})
            with self.queries.lease('independent', (self.dut_keys - {key}) |
                                    {'adapter:' + nic[k] for nic in (self.a, self.b) for k in ('name', 'guid')}):
                pass

    def test_workspace_and_fence_handoffs_keep_original_owner_and_release_boundary(self):
        fence = HostResourceFence(self.root / 'owners')
        self.addCleanup(fence.close)
        channel = ChannelConfig('channel_5', network_card_ip='192.0.2.5')
        for parent in (self.resources, fence):
            with self.subTest(parent=type(parent).__name__):
                key = 'adapter:' + self.a['name']
                if parent is self.resources:
                    parent.acquire('original', 'fixture-project', 'fixture', [key])
                else:
                    parent.acquire('original', [key])
                try:
                    context = PipelineContext(None, [channel], None, None, power_resource_owner=(parent, 'original'))
                    with patch('src.services.physical_resource_guards.adapters_ipv4', return_value=[self.a]):
                        with _power_admission(context):
                            pass
                    self.assertEqual({r.resource_key for r in self.resources.lease_entries()},
                                     {key, 'adapter:' + self.a['guid']})
                finally:
                    parent.release('original')
                self.assertFalse(self.resources.lease_entries())

    def test_missing_and_uncertain_parent_cannot_create_or_revive_a_lease(self):
        channel = ChannelConfig('channel_5', network_card_ip='192.0.2.5')
        fence = HostResourceFence(self.root / 'owners')
        self.addCleanup(fence.close)
        with patch('src.services.physical_resource_guards.adapters_ipv4', return_value=[self.a]):
            for protection in (self.resources, fence):
                ctx = PipelineContext(None, [channel], None, None, power_resource_owner=(protection, 'missing'))
                with self.assertRaises(CapabilityError), _power_admission(ctx):
                    self.fail('missing owner admitted')
            key = 'adapter:' + self.a['name']
            fence.acquire('old', [key])
            fence.release('old', uncertain=True)
            ctx.power_resource_owner = (fence, 'old')
            with self.assertRaises(CapabilityError), _power_admission(ctx):
                self.fail('unknown owner admitted')
            self.assertEqual(list(fence.db.execute('SELECT resource,state FROM fence')), [(key, 'unknown')])

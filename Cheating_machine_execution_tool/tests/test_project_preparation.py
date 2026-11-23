"""Project-scoped evidence transitions, including original Job receipts from simulated runners."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from src.models.capabilities import CapabilityAuthority
from src.services.capability_jobs import CapabilityJobs
from src.services.project_preparation import preparation_for, preparation_plan
from src.services.project_profile_store import read_project_profile, write_project_profile
from src.services.project_status_service import ProjectStatusService
from src.services.project_store import ProjectStore


class FakeResources:
    def acquire(self, owner, keys):
        pass

    def release(self, owner):
        pass


class ProjectPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ProjectStore(Path(__file__).resolve().parents[1])
        self.addCleanup(lambda: [self.store.close(c) for c in list(self.store.opened.values())])
        data = dict(test_type='power_cycle', optional_steps=['parameters', 'voice'],
                    duts=[dict(label='DUT A', hardware_id='SN-A', target_firmware='V1', channel=1, vlan='vlan101'),
                          dict(label='DUT B', hardware_id='SN-B', target_firmware='V1', channel=2, vlan='vlan102')])
        self.ctx = self.store.create(self.root / 'one', '测试', profile=data)
        self.messages = []
        self.service = preparation_for(self.ctx, self.messages.append)
        self.a, self.b = (x['dut_id'] for x in read_project_profile(self.ctx.config_dir)['duts'])

    def steps(self, dut=None):
        target = next(d for d in self.service.snapshot()['duts'] if d['dut_id'] == (dut or self.a))
        return {s['id']: s for s in target['steps']}

    def complete(self, key, dut=None):
        dut = dut or self.a
        step = self.steps(dut)[key]
        attempt = self.service.record_manual(dut, key, step['token'], '现场执行或已有配置记录', '执行人')
        step = self.steps(dut)[key]
        self.assertEqual((step['state'], step['source']), ('executed', 'manual'))
        self.service.verify(dut, key, step['token'], attempt, True, '独立回读或现场核验凭证', '核验人')

    def edit(self, change):
        profile = read_project_profile(self.ctx.config_dir)
        change(profile)
        write_project_profile(self.ctx.config_dir, profile)
        self.store.save(self.ctx)

    def make_job(self, capability, arguments, result):
        jobs = CapabilityJobs(self.ctx.history / 'ai/business', FakeResources(),
                              project_context=self.ctx, status_service=ProjectStatusService())
        try:
            authority = CapabilityAuthority('fake-principal', 'session', uuid4().hex, (1, 2), source='gui', approved=True)
            started = jobs.start(capability, arguments, authority, (), lambda job: result)
            identifier = started['job_id']
            with jobs.lock:
                thread = jobs.threads.get(identifier)
            if thread:
                thread.join(5)
            self.assertTrue(jobs.idle)
            return identifier
        finally:
            jobs.close()

    def test_preparation_emits_once_with_original_text_and_source_target(self):
        events = []
        preparation_for(self.ctx, emit_event=lambda ctx, text, **params: events.append((ctx, text, params)))
        self.complete('environment', self.b)
        self.assertEqual(len(events), 2)
        self.assertIs(events[-1][0], self.ctx)
        self.assertIn(self.b, events[-1][1])
        self.assertIn('verified', events[-1][1])
        self.assertEqual(events[-1][2], dict(job_id='', dut_id=self.b, step='environment', channel=2, level='INFO'))
        self.assertEqual(self.messages, [])

    def test_type_dependencies_manual_skip_and_gate(self):
        steps = self.steps()
        self.assertIn('management_ip', steps)
        self.assertNotIn('telnet_credentials', steps)
        self.assertTrue(steps['parameters']['optional'])
        self.assertIn('wan', steps['voice']['depends_on'])
        aging = {s['id'] for s in preparation_plan({'test_type': 'service_aging'})}
        self.assertIn('telnet_credentials', aging)
        self.assertIn('initial_health', aging)
        self.assertNotIn('management_ip', aging)
        self.assertNotIn('pretest', aging)
        with self.assertRaises(ValueError):
            self.service.begin(self.a, 'firmware', steps['firmware']['token'], '操作员')
        with self.assertRaises(ValueError):
            self.service.skip(self.a, 'firmware', steps['firmware']['token'], '跳过', '操作员')
        with self.assertRaises(ValueError):
            self.service.require_ready()
        for dut in (self.a, self.b):
            for key in self.steps(dut):
                if key == 'parameters':
                    self.service.skip(dut, key, self.steps(dut)[key]['token'], '本机保留原参数', '操作员')
                else:
                    self.complete(key, dut)
            if dut == self.a:
                self.assertFalse(self.service.snapshot()['ready'])
        self.assertTrue(self.service.require_ready()['ready'])
        self.assertEqual(self.service.snapshot()['skipped'], 2)
        copy = self.store.duplicate(self.ctx, self.root / 'copy')
        copy_view = preparation_for(copy).snapshot()
        self.assertEqual(copy_view['verified'], 0)
        self.assertFalse(copy_view['ready'])
        retained = self.ctx.root
        self.store.close(self.ctx)
        self.ctx = self.store.open(retained)
        earlier = self.service
        self.service = preparation_for(self.ctx)
        self.assertEqual(self.steps()['pretest']['state'], 'stale')
        self.assertEqual(self.steps()['environment']['state'], 'verified')
        with self.assertRaises(ValueError):
            earlier.require_ready()

    def test_declared_adb_change_invalidates_only_its_dut_environment_receipt(self):
        self.complete('environment', self.a)
        self.complete('environment', self.b)
        self.edit(lambda profile: profile['duts'][0].update(adb_serial='ADB-A'))
        self.assertEqual(self.steps(self.a)['environment']['state'],'stale')
        self.assertEqual(self.steps(self.b)['environment']['state'],'verified')
        self.complete('environment', self.a)
        self.edit(lambda profile: profile['duts'][0].update(adb_serial='adb-a'))
        self.assertEqual(self.steps(self.a)['environment']['state'],'stale')
        self.assertEqual(self.steps(self.b)['environment']['state'],'verified')

    def test_execution_and_verification_bind_to_current_dut_attempt_and_configuration(self):
        self.assertIs(preparation_for(self.ctx), self.service)
        self.complete('environment')
        self.complete('environment', self.b)
        self.complete('firmware')
        self.complete('firmware', self.b)
        self.edit(lambda p: p['duts'][0].update(target_firmware='V2'))
        self.assertEqual(self.steps()['environment']['state'], 'verified')
        self.assertEqual(self.steps()['firmware']['state'], 'stale')
        self.assertEqual(self.steps(self.b)['firmware']['state'], 'verified')
        first = self.service.begin(self.a, 'firmware', self.steps()['firmware']['token'], '操作员')
        with self.assertRaises(ValueError):
            self.service.finish(self.a, 'firmware', first, 'executed', '无任务回执', '操作员')
        self.service.finish(self.a, 'firmware', first, 'stopped', '未下发，已取消', '操作员')
        second = self.service.begin(self.a, 'firmware', self.steps()['firmware']['token'], '操作员')
        with self.assertRaises(ValueError):
            self.service.finish(self.a, 'firmware', first, 'failed', '旧回执', '操作员')
        self.service.finish(self.a, 'firmware', second, 'failed', '原模块预检失败', '操作员')
        attempt = self.service.record_manual(self.a, 'firmware', self.steps()['firmware']['token'], '现场版本操作', '操作员')
        token = self.steps()['firmware']['token']
        self.service.verify(self.a, 'firmware', token, attempt, False, '当前版本不符', '核验人')
        with self.assertRaises(ValueError):
            self.service.verify(self.a, 'firmware', token, attempt, True, '迟到核验', '核验人')
        self.assertIn('当前版本不符', self.service.history(self.a, 'firmware')[0]['verification'])
        self.edit(lambda p: p['duts'][0].update(hardware_id='SN-C'))
        self.assertEqual(self.steps()['environment']['state'], 'stale')
        self.assertEqual(self.steps(self.b)['firmware']['state'], 'verified')

    def test_dirty_draft_concurrent_begin_and_interrupted_job(self):
        step = self.steps()['environment']
        staged = read_project_profile(self.ctx.config_dir)
        staged['requirements'] = '草稿'
        write_project_profile(self.ctx.config_dir, staged)
        self.assertTrue(self.service.snapshot()['dirty'])
        with self.assertRaises(ValueError):
            self.service.begin(self.a, 'environment', step['token'], '操作员')
        self.store.discard(self.ctx)
        def begin():
            try:
                return self.service.begin(self.a, 'environment', step['token'], '操作员')
            except ValueError:
                return None
        with ThreadPoolExecutor(2) as pool:
            results = [task.result() for task in (pool.submit(begin), pool.submit(begin))]
        attempt, = [value for value in results if value]
        self.assertFalse(self.service.snapshot()['ready'])
        prior = self.service
        root = self.ctx.root
        self.store.close(self.ctx)
        self.ctx = self.store.open(root)
        self.service = preparation_for(self.ctx)
        self.assertEqual(self.steps()['environment']['state'], 'interrupted')
        with self.assertRaises(ValueError):
            prior.finish(self.a, 'environment', attempt, 'executed', '旧线程迟到回执', '操作员')
        with self.assertRaises(ValueError):
            self.service.begin(self.a, 'environment', self.steps()['environment']['token'], '操作员')
        self.service.finish(self.a, 'environment', attempt, 'stopped', '现场已确认原任务停止', '复核人')
        self.assertEqual(self.steps()['environment']['state'], 'stopped')

    def test_only_exact_original_job_after_attempt_can_complete_automatic_execution(self):
        self.complete('environment')
        args = dict(channel_ids=[1])
        result = dict(ok=True, state='succeeded', items=[dict(vlan='vlan101', state='succeeded')])
        old = self.make_job('firmware.upgrade', args, result)
        self.service.begin(self.a, 'firmware', self.steps()['firmware']['token'], '操作员')
        token = self.steps()['firmware']['token']
        for invalid in (old, 'missing', self.make_job('firmware.upgrade', dict(channel_ids=[2]), result),
                        self.make_job('parameters.write', args, result)):
            with self.assertRaises(ValueError):
                self.service.link_job(self.a, 'firmware', token, invalid, '操作员')
        job = self.make_job('firmware.upgrade', args, result)
        attempt = self.service.link_job(self.a, 'firmware', token, job, '操作员')
        linked = self.steps()['firmware']
        self.assertEqual((linked['state'], linked['source']), ('executed', 'job'))
        self.assertIn(job, linked['evidence'])
        self.assertIn('firmware', self.steps()['parameters']['blocked_by'])
        self.service.verify(self.a, 'firmware', linked['token'], attempt, True, '设备重启后版本 V1', '核验人')
        self.service.begin(self.a, 'firmware', self.steps()['firmware']['token'], '操作员')
        with self.assertRaises(ValueError):
            self.service.link_job(self.a, 'firmware', self.steps()['firmware']['token'], job, '操作员')

    def test_exact_onu_sn_and_both_wifi_bands_missing_receipts_do_not_pass(self):
        self.edit(lambda p: p.update(test_type='service_aging', type_config={}, optional_steps=[]))
        for key in ('environment', 'telnet_credentials', 'firmware'):
            self.complete(key)
        self.service.begin(self.a, 'onu', self.steps()['onu']['token'], '操作员')
        token = self.steps()['onu']['token']
        for arguments in ({'plans_hash': 'hash-only'}, {'serial_numbers': ['SN-B']}):
            wrong = self.make_job('onu.register', arguments, dict(ok=True))
            with self.assertRaises(ValueError):
                self.service.link_job(self.a, 'onu', token, wrong, '操作员')
        good = self.make_job('onu.register', {'serial_numbers': ['SN-A']}, dict(ok=True))
        self.service.link_job(self.a, 'onu', token, good, '操作员')
        self.complete('telnet')
        self.service.begin(self.a, 'wifi', self.steps()['wifi']['token'], '操作员')
        for band, state in (('wifi_2g_configure', 'running'), ('wifi_5g_configure', 'executed')):
            item = dict(number=1, ok=True, state='success')
            job = self.make_job('dut.editor.execute', dict(action=band, channel_ids=[1]), dict(ok=True, items=[item]))
            self.service.link_job(self.a, 'wifi', self.steps()['wifi']['token'], job, '操作员')
            self.assertEqual(self.steps()['wifi']['state'], state)
        self.assertEqual(len(self.steps()['wifi']['evidence'].splitlines()), 2)

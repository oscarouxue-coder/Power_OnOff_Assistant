"""Continuous monitoring regression using isolated project snapshots and fake equipment."""
import csv
from datetime import datetime
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from src.core.aging_lan_ping import bound_echo
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.project_profile import dut_resource_keys
from src.services.capability_jobs import CapabilityJobs
from src.services.project_profile_store import read_project_profile, write_project_profile
from src.services.project_store import ProjectStore
from src.services.resource_lease_service import ResourceLeaseService
from src.services.service_aging import CAPABILITY, ServiceAging
from src.services.upgrade_stop_service import UpgradeStopControl
from src.services.workspace_resources import WorkspaceResources


class ServiceAgingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = ProjectStore(Path(__file__).resolve().parents[1])
        self.ctx = self.store.create(self.root / 'A', '老化', profile={
            'test_type':'service_aging', 'type_config':{'target_hours':1,'collectors':['lan_ping','voice','keys_led']},
            'duts':[dict(label='D1', hardware_id='SN-01', channel=1, network_adapter='nic',adb_serial='Fixture-A1')]})
        self.addCleanup(self.store.close, self.ctx)
        self.ctx.config_dir.joinpath('network_card_ip.ini').write_text(
            '[channel_1]\nadapter_alias=nic\nnetwork_card_ip=192.0.2.2\ndevice_manage_ip=192.0.2.1\nenabled=1\n',
            encoding='utf-8')
        self.store.save(self.ctx)
        self.nic = dict(name='nic',guid='guid-A',index=12,up=True,addresses=(('192.0.2.2',24),))
        self.t0 = datetime(2026,11,21,23,59,30).timestamp()
        self.seconds, self.events = 0, []
        self.probe = Mock(return_value=True)
        self.service = ServiceAging(self.ctx,clock=lambda:self.t0+self.seconds,monotonic=lambda:self.seconds,
                                   inventory=lambda:[self.nic],probe=self.probe,
                                   wait=lambda stop,s:self.advance(s), sample_interval=30)
        self.plan = self.service.prepare()
        self.dut = self.plan['duts'][0]['dut_id']

    def advance(self, seconds):
        self.seconds += seconds

    def job(self, identifier='job-A'):
        return SimpleNamespace(job_id=identifier, project_id=self.ctx.identity.project_id,
                               configuration_root=self.store.snapshot(self.ctx), stop=UpgradeStopControl(),
                               event=lambda *args, **kw:self.events.append((args,kw)))

    def test_probe_health_intervals_heartbeat_and_loss_require_actual_consecutive_observations(self):
        job = self.job()
        replies = iter([True, False, False, True, OSError('采集器不可用')])
        def probe(*_args):
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return result
        self.service.probe = probe
        def wait(stop, delay):
            self.advance(delay)
            if self.seconds == 150:
                stop.request_stop()
        self.service.wait = wait
        self.assertEqual(self.service.run(job, self.plan)['state'],'stopped')
        samples = [fields for _, fields in self.events if fields.get('step') == 'lan_ping']
        self.assertEqual(samples, [dict(dut_id=self.dut, channel=1, step='lan_ping', level=level)
                                   for level in ('INFO', 'WARN', 'WARN', 'INFO', 'WARN')])
        self.assertTrue(any('采样未能确认' in args[1] for args, _ in self.events))
        snapshot = self.service.snapshot()
        row = next(r for r in snapshot['rows'] if r['collector']=='lan_ping')
        self.assertEqual((row['checks'],row['successes'],row['failures'],row['state']),(4,2,2,'unknown'))
        self.assertEqual((row['observed_seconds'],row['abnormal_seconds'],row['recoveries']),(90,30,1))
        self.assertEqual(row['packet_loss'], .5)
        self.assertEqual(row['last_heartbeat'], self.t0 + 90)
        self.assertEqual(snapshot['incidents'][0]['reason'],'recovered')
        cpu = next(r for r in snapshot['rows'] if r['collector']=='cpu_memory')
        self.assertEqual((cpu['state'],cpu['success_rate']),('unavailable',None))

    def test_daily_final_records_cross_midnight_and_target_duration_never_grant_acceptance(self):
        job = self.job()
        def wait(_stop,_delay):
            self.service.record(job.job_id,self.dut,'voice','healthy','电话实际接通','现场 A',kind='daily')
            self.advance(60 if self.seconds==0 else 3540)
        self.service.wait = wait
        result = self.service.run(job,self.plan)
        self.assertFalse(result['accepted'])
        view = self.service.record(job.job_id,self.dut,'keys_led','abnormal','复位键异常','现场 B',kind='final')
        self.assertEqual(view['state'],'target_reached')
        self.assertEqual(view['elapsed_seconds'],3600)
        self.assertEqual({r['day'] for r in view['daily_checks']},{'2026-11-21','2026-11-22'})
        self.assertEqual(view['final_checks'][0]['outcome'],'abnormal')
        voice = next(r for r in view['rows'] if r['collector']=='voice')
        self.assertEqual((voice['checks'],voice['observed_seconds'],voice['last_heartbeat']),(2,0,None))
        page = self.service.history_page(job.job_id,kind='daily',limit=1)
        next_page = self.service.history_page(job.job_id,kind='daily',limit=1,before_id=page['next_before'])
        self.assertIsNone(next_page['next_before'])
        self.assertNotEqual(page['rows'][0]['id'],next_page['rows'][0]['id'])
        with self.assertRaises(ValueError):
            self.service.record(job.job_id,self.dut,'voice','healthy','迟到观测','现场 A')

    def test_missing_interface_keeps_manual_and_unavailable_sources_distinct(self):
        self.nic['up'] = False
        plan = self.service.prepare()
        self.assertIsNone(plan['duts'][0]['binding'])
        job = self.job()
        self.service.wait = lambda stop,_: stop.request_stop()
        self.service.run(job,plan)
        rows = {row['collector']:row for row in self.service.snapshot()['rows']}
        self.assertEqual(rows['lan_ping']['state'],'unavailable')
        self.assertEqual(rows['voice']['source'],'manual')
        self.assertEqual(rows['voice']['state'],'unknown')
        self.probe.assert_not_called()

    def test_bindings_are_rechecked_before_start_and_each_packet(self):
        job = self.job()
        self.nic['guid'] = 'replacement'
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.service.run(job,self.plan)
        self.assertFalse(self.service.snapshot())
        self.nic['guid'] = 'guid-A'
        def wait(stop,_):
            self.advance(30)
            self.nic['addresses'] = ()
            if self.seconds >= 60:
                stop.request_stop()
        self.service.wait = wait
        self.service.run(job,self.plan)
        self.probe.assert_called_once()
        row = next(r for r in self.service.snapshot()['rows'] if r['collector']=='lan_ping')
        self.assertEqual((row['checks'],row['state'],row['failures']),(1,'unknown',0))

    def test_interruption_and_long_gaps_never_extend_uptime_or_auto_restart(self):
        history = self.service.history
        history.begin('interrupted',self.plan,60)
        callback = lambda outcome: history.observe('interrupted',self.dut,'lan_ping',outcome,'模拟','',
                                                   kind='sample',elapsed=self.seconds)
        callback('abnormal')
        self.advance(300)
        callback('healthy')
        history.tick('interrupted',300)
        self.advance(100)
        stream = next(r for r in history.snapshot()['rows'] if r['collector']=='lan_ping')
        self.assertEqual((stream['state'],stream['recoveries'],stream['observed_seconds']),('unknown',0,0))
        with patch('src.services.service_aging_history._PROCESS','another-process'):
            view = self.service.snapshot()
            self.assertEqual((view['state'],view['elapsed_seconds']),('interrupted',300))
            with self.assertRaises(ValueError):
                self.service.record('interrupted',self.dut,'voice','healthy','恢复前','现场')
        self.probe.assert_not_called()

    def test_job_owns_snapshot_and_leases_until_stop_and_project_dut_keys_conflict(self):
        coordinator = WorkspaceResources(self.root/'host')
        self.addCleanup(coordinator.close)
        resources = ResourceLeaseService(coordinator=coordinator,project_id=self.ctx.identity.project_id,project_name='A')
        jobs = CapabilityJobs(self.ctx.history/'jobs',resources,project_context=self.ctx)
        self.addCleanup(jobs.close)
        entered = threading.Event()
        self.service.wait = lambda stop,seconds:(entered.set(),stop.event.wait(3))
        authority = CapabilityAuthority('gui:test','session','op',(1,),source='gui',approved=True)
        arguments = dict(channel_ids=[1],binding=self.plan['binding'])
        receipt = jobs.start(CAPABILITY,arguments,authority,self.plan['resources'],lambda j:self.service.run(j,self.plan))
        try:
            self.assertTrue(entered.wait(3))
            held = set(self.plan['resources'])
            self.assertIn('dut:hardware:sn-01', held)
            from src.models.project_profile import adb_resource_key
            self.assertIn(adb_resource_key('Fixture-A1'), held)
            with self.assertRaises(CapabilityError):
                coordinator.acquire('shared-adb','other-project','B',[adb_resource_key('Fixture-A1')])
            self.assertIn('adapter:guid-a',held)
            keys = dut_resource_keys([dict(dut_id=self.dut,hardware_id='sN-01',channel=8)], channels=[8])
            with self.assertRaises(CapabilityError):
                coordinator.acquire('other-job','other-project','B',keys)
            coordinator.acquire('independent','other-project','B',['dut:hardware:sn-02'])
            coordinator.release('independent')
            child = subprocess.run([sys.executable, '-c',
                "from src.core.host_resource_lock import HostResourceLock, HostResourceBusy\n"
                "try:\n    HostResourceLock(['dut:hardware:sn-01']).acquire()\n"
                "except HostResourceBusy:\n    print('shared-dut-busy')\n"],
                cwd=self.ctx.source_root, capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode,0,child.stderr)
            self.assertEqual(child.stdout.strip(),'shared-dut-busy')
            self.assertEqual(jobs.start(CAPABILITY,arguments,authority,self.plan['resources'],lambda _:None)['job_id'],
                             receipt['job_id'])
            self.assertEqual(len(list((self.ctx.root/'runs').glob('*/run.json'))),1)
        finally:
            jobs.cancel(receipt['job_id'],authority)
            deadline = time.monotonic()+4
            while not jobs.idle and time.monotonic()<deadline:
                time.sleep(.01)
        self.assertEqual(jobs.status(receipt['job_id'],authority)['state'],'stopped')
        coordinator.acquire('next-job','other-project','B',keys)
        coordinator.release('next-job')
        self.assertFalse(resources.busy)

    def test_raw_probe_binds_ipv4_and_interface_before_send_and_never_falls_back(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recvfrom.side_effect = socket.timeout()
        samples = iter([0,.01,1.1])
        sent = []
        binding = self.plan['duts'][0]['binding']
        self.assertFalse(bound_echo(binding,UpgradeStopControl(),sent.append,socket_factory=lambda *_:sock,
                                    monotonic=lambda:next(samples)))
        sock.bind.assert_called_once_with(('192.0.2.2',0))
        sock.setsockopt.assert_called_once_with(socket.IPPROTO_IP, getattr(socket,'IP_UNICAST_IF',31), struct.pack('!I',12))
        self.assertEqual(sock.sendto.call_args.args[1],('192.0.2.1',0))
        self.assertIn('192.0.2.2',sent[0])
        sock.reset_mock()
        sock.bind.side_effect = OSError('模拟无法绑定')
        with self.assertRaises(OSError):
            bound_echo(binding,UpgradeStopControl(),sent.append,socket_factory=lambda *_:sock)
        sock.sendto.assert_not_called()

    def test_seven_daily_inspections_are_separate_from_continuous_verification_and_export_in_full(self):
        profile = read_project_profile(self.ctx.config_dir)
        profile['type_config'] = dict(target_hours=168, collectors=['voice','keys_led'])
        write_project_profile(self.ctx.config_dir,profile)
        self.store.save(self.ctx)
        plan, job = self.service.prepare(), self.job('seven-days')
        def inspect(_stop,_delay):
            self.service.record(job.job_id,self.dut,'voice','healthy','当日人工检查','operator',kind='daily')
            self.advance(86400)
        self.service.wait = inspect
        self.service.run(job,plan)
        view = self.service.record(job.job_id,self.dut,'keys_led','healthy','全部按键及指示灯回读','operator',kind='final')
        self.assertEqual((view['target_hours'],view['elapsed_seconds']),(168,7*86400))
        self.assertEqual(len({r['day'] for r in view['daily_checks']}),7)
        voice = next(r for r in view['rows'] if r['collector']=='voice')
        self.assertEqual((voice['observed_seconds'],voice['checks'],voice['last_heartbeat']),(0,7,None))
        runs = self.service.list_runs()
        self.assertEqual([r['job_id'] for r in runs['rows']],['seven-days'])
        target = self.root/'记录.csv'
        self.assertEqual(self.service.export_history(job.job_id,target),8)
        with target.open(encoding='utf-8-sig',newline='') as f:
            records = list(csv.DictReader(f))
        self.assertEqual(records[-1]['证据'],'全部按键及指示灯回读')
        self.assertEqual({r['配置版本'] for r in records},{self.ctx.identity.revision})
        with self.assertRaisesRegex(ValueError,'文件已存在'):
            self.service.export_history(job.job_id,target)
        with self.assertRaisesRegex(ValueError,'本项目没有该'):
            self.service.history_page('别的批次')

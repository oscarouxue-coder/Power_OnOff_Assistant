"""Project-scoped observation receipts, fake time, local files and no live devices."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from src.services.project_store import ProjectStore
from src.services.project_profile_store import read_project_profile, write_project_profile
from src.services.service_aging import ServiceAging
from src.services.upgrade_stop_service import UpgradeStopControl


class ServiceAgingFeedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = ProjectStore(Path(__file__).resolve().parents[1])
        self.profile = dict(test_type='service_aging', type_config=dict(
            collectors=['voice','keys_led'],feed_collectors=['voice']), duts=[
            dict(label='A',hardware_id='ONU-A',channel=1), dict(label='B',hardware_id='ONU-B',channel=2)])
        self.ctx = self.store.create(self.root / 'project', '业务老化', profile=self.profile)
        self.addCleanup(self.store.close,self.ctx)
        self.now = 1700000000.
        self.t0 = self.now
        self.service = ServiceAging(self.ctx,clock=lambda:self.now,monotonic=lambda:self.now-self.t0,
            inventory=Mock(side_effect=AssertionError('现场文件无需枚举网卡')),probe=Mock())
        self.plan = self.service.prepare()
        self.job = SimpleNamespace(job_id=uuid4().hex,project_id=self.ctx.identity.project_id,
            configuration_root=self.store.snapshot(self.ctx),stop=UpgradeStopControl(),event=Mock())
        self.a,self.b = (d['dut_id'] for d in self.plan['duts'])

    def sample(self, dut, key, observed, outcome='healthy'):
        return dict(project_id=self.ctx.identity.project_id,job_id=self.job.job_id,dut_id=dut,collector='voice',
                    event_id=key,observed_at=datetime.fromtimestamp(self.t0+observed,timezone.utc).isoformat(),
                    outcome=outcome,detail='采集端证据 '+key)

    def test_job_reads_only_frozen_subscription_and_keeps_manual_evidence_separate(self):
        directory = self.ctx.history / 'aging-input'
        path = directory / (self.job.job_id + '.jsonl')
        manifest = directory / (self.job.job_id + '.plan.json')
        cycles = []

        def wait(stop, delay):
            self.now += delay
            cycles.append(delay)
            if len(cycles) == 1:
                doc = json.loads(manifest.read_text(encoding='utf-8'))
                self.assertEqual((doc['project_id'],doc['job_id'],doc['feed_collectors']),
                                 (self.ctx.identity.project_id,self.job.job_id,['voice']))
                self.assertEqual({d['hardware_id'] for d in doc['duts']},{'ONU-A','ONU-B'})
                self.assertFalse(path.exists())
                rows = [self.sample(self.a,'1',5),self.sample(self.b,'1',5)]
                path.write_text('bad json\n',encoding='utf-8')
            elif len(cycles) == 2:
                self.service.record(self.job.job_id,self.a,'voice','abnormal','人工日检凭据','现场',kind='daily')
                rows = [self.sample(self.a,'1',5),self.sample(self.a,'2',35,'abnormal'),
                        self.sample(self.a,'3',55,'abnormal')]
            elif len(cycles) == 3:
                rows = [self.sample(self.a,'4',85)]
            else:
                stop.request_stop()
                return
            with path.open('a',encoding='utf-8') as stream:
                for row in rows:
                    stream.write(json.dumps(row,ensure_ascii=False)+'\n')

        self.service.wait = wait
        self.assertEqual(self.service.run(self.job,self.plan)['state'],'stopped')
        self.service.probe.assert_not_called()
        view = self.service.snapshot(self.job.job_id)
        rows = {(r['dut_id'],r['collector']):r for r in view['rows']}
        a = rows[self.a,'voice']
        self.assertEqual((a['source'],a['checks'],a['successes'],a['failures'],a['recoveries']),('jsonl',4,2,2,1))
        self.assertEqual((a['last_heartbeat'],a['observed_seconds'],a['abnormal_seconds']),(self.t0+85,80,20))
        self.assertEqual((rows[self.b,'voice']['checks'],rows[self.b,'voice']['state']),(1,'unknown'))
        self.assertEqual(rows[self.a,'keys_led']['source'],'manual')
        self.assertEqual(rows[self.a,'cpu_memory']['source'],'unavailable')
        self.assertEqual(view['feed_path'],str(path))
        self.assertEqual(view['daily_checks'][0]['source'],'manual')
        page = self.service.history_page(self.job.job_id,kind='sample')
        first = next(r for r in page['rows'] if r['dut_id']==self.a and r['event_id']=='1')
        self.assertEqual((first['at'],first['received_at'],first['source']),(self.t0+5,self.t0+30,'jsonl'))
        output = self.root / '观察.csv'
        self.assertEqual(self.service.export_history(self.job.job_id,output),6)
        with output.open(encoding='utf-8-sig',newline='') as f:
            exported = list(csv.DictReader(f))
        self.assertSetEqual({row['采集来源'] for row in exported},{'jsonl','manual'})
        self.assertTrue(any(r['来源事件 ID']=='1' and r['时间']!=r['接收时间'] for r in exported))
        self.assertTrue(any('忽略' in str(call) for call in self.job.event.call_args_list))

    def test_durable_dedup_time_and_restart_do_not_bridge_missing_evidence(self):
        history = self.service.history
        job = self.job.job_id
        history.begin(job,self.plan,60)
        def record(key, observed, *, project=None, outcome='abnormal'):
            row = self.sample(self.a,key,observed,outcome)
            row['project_id'] = project or row['project_id']
            row['observed_at'] = self.t0+observed
            row['evidence'] = row.pop('detail')
            event = SimpleNamespace(**row)
            return history.observe(job,self.a,'voice',outcome,event.evidence,'',kind='sample',feed_event=event)

        self.now += 30
        self.assertIsNone(record('old',20))
        self.assertEqual(record('old',20), 'duplicate')
        self.assertEqual(record('earlier',15), 'out_of_order')
        self.assertEqual(record('future',40), 'invalid_time')
        with self.assertRaises(ValueError):
            record('wrong',25,project='other-project')
        with self.assertRaises(ValueError):
            history.observe(job,self.a,'voice','healthy','手工观察','现场',kind='observation')
        history.feed_gap(job)
        self.now += 120
        self.assertEqual(record('stale',30), 'invalid_time')
        self.assertIsNone(record('new',145,outcome='healthy'))
        row = next(r for r in history.snapshot(job)['rows'] if r['dut_id']==self.a and r['collector']=='voice')
        self.assertEqual((row['checks'],row['recoveries'],row['observed_seconds'],row['last_heartbeat']),
                         (2,0,0,self.t0+145))
        with patch('src.services.service_aging_history._PROCESS','other-process'):
            self.assertEqual(history.snapshot(job)['state'],'interrupted')
            with self.assertRaises(ValueError):
                record('after-crash',149)

    def test_legacy_history_without_feed_table_can_read_export_and_stays_unmodified(self):
        history = self.service.history
        job = self.job.job_id
        history.begin(job,dict(self.plan,feed_collectors=[]),60)
        history.observe(job,self.a,'voice','healthy','人工依据','检查员',kind='daily')
        with sqlite3.connect(str(history.path)) as db:
            db.execute('DROP TABLE feed_receipts')
        previous = history.path.read_bytes()
        row, = history.history_page(job)['rows']
        self.assertEqual((row['source'],row['event_id'],row['received_at']),('manual',None,row['at']))
        self.assertEqual(history.snapshot(job)['feed_path'],'')
        presence = history.snapshot(job)['dut_presence']
        self.assertEqual({item['dut_id'] for item in presence},{self.a,self.b})
        self.assertTrue(all(not item['subscribed'] and item['state']=='unknown' and item['reboot_count'] is None
                            for item in presence))
        self.assertEqual(history.export_history(job,self.root/'历史.csv'),1)
        self.assertEqual(history.path.read_bytes(),previous)
        self.assertFalse((self.ctx.history/'aging-input').exists())

    def test_presence_uses_frozen_dut_online_evidence_and_detects_proven_boot_changes_across_gaps(self):
        history = self.service.history
        plan = dict(self.plan,collectors=['dut_presence','voice'],feed_collectors=['dut_presence','voice'])
        job = self.job.job_id
        history.begin(job,plan,60)

        def event(dut, seq, outcome, boot=None, uptime=None, collector='dut_presence',owner=None):
            self.now += 1
            owner = owner or job
            sample = SimpleNamespace(project_id=self.ctx.identity.project_id,job_id=owner,dut_id=dut,
                collector=collector,event_id=str(seq),observed_at=self.now,outcome=outcome,evidence=f'读数 {seq}',
                boot_id=boot,uptime_seconds=uptime)
            return history.observe(owner,dut,collector,outcome,sample.evidence,'',kind='sample',feed_event=sample)

        def view(dut,owner=job):
            return next(r for r in history.snapshot(owner)['dut_presence'] if r['dut_id']==dut)

        self.assertEqual((view(self.a)['state'],view(self.a)['reboot_count']),('unknown',None))
        event(self.a,0,'healthy',collector='voice')
        self.assertIsNone(view(self.a)['last_heartbeat'])
        event(self.a,1,'healthy','boot-A',50)
        first = self.now
        event(self.b,0,'healthy',uptime=500)
        self.assertEqual(view(self.b)['last_uptime_seconds'],500)
        event(self.b,1,'healthy','different-device')
        self.assertIsNone(view(self.b)['last_uptime_seconds'])
        self.assertIsNone(view(self.b)['last_uptime_at'])
        self.assertEqual((view(self.a)['state'],view(self.a)['last_heartbeat']),('online',first))
        event(self.a,2,'healthy',None,1)
        self.assertEqual(view(self.a)['reboot_count'],0)
        history.feed_gap(job)
        self.assertEqual((view(self.a)['state'],view(self.a)['last_outcome']),('unknown','healthy'))
        event(self.a,3,'healthy','boot-A',0)
        self.assertEqual(view(self.a)['reboot_count'],0)
        event(self.a,4,'abnormal')
        offline = view(self.a)
        self.assertEqual((offline['state'],offline['boot_id'],offline['uptime_seconds']),('offline',None,None))
        self.assertEqual((offline['last_boot_id'],offline['last_boot_at'],offline['last_uptime_seconds']),
                         ('boot-A',self.now-1,0))
        self.assertEqual(offline['last_heartbeat'],self.now-1)
        event(self.a,5,'unknown')
        self.now += 90
        self.assertEqual(view(self.a)['state'],'unknown')
        history.feed_gap(job)
        event(self.a,6,'healthy','boot-B')
        change_time = self.now
        changed = view(self.a)
        self.assertEqual((changed['boot_id'],changed['reboot_count'],changed['last_reboot_at']),
                         ('boot-B',1,change_time))
        self.assertEqual((changed['last_uptime_seconds'],changed['last_uptime_at']),(None,None))
        self.assertEqual(event(self.a,6,'healthy','boot-C'),'duplicate')
        self.assertEqual(view(self.a)['reboot_count'],1)
        event(self.a,7,'healthy','boot-B',300)
        self.now += 67
        stale = view(self.a)
        self.assertEqual((stale['state'],stale['last_outcome'],stale['last_reboot_at']),('unknown','healthy',change_time))
        self.assertEqual(view(self.b)['reboot_count'],0)
        event(self.a,8,'healthy','boot-C')
        self.assertEqual(view(self.a)['reboot_count'],2)
        with patch('src.services.service_aging_history._PROCESS','new-process'):
            self.assertEqual(view(self.a)['state'],'unknown')
        history.tick(job,self.now-self.t0,'stopped')
        finished = view(self.a)
        self.assertEqual((finished['state'],finished['last_outcome'],finished['last_boot_id']),
                         ('unknown','healthy','boot-C'))
        self.assertTrue(all(r['collector']!='dut_presence' for r in history.snapshot(job)['rows']))
        self.assertEqual(history.snapshot(job)['incidents'],[])
        with self.assertRaises(ValueError):
            history.observe(job,self.a,'dut_presence','healthy','人工检查','operator',kind='final')
        other = uuid4().hex
        history.begin(other,dict(plan,collectors=['dut_presence'],feed_collectors=['dut_presence']),60)
        event(self.a,1,'healthy','boot-other',owner=other)
        self.assertEqual(view(self.a,other)['reboot_count'],0)
        self.assertTrue(history.snapshot(other)['feed_path'].endswith(other+'.jsonl'))
        exported = self.root/'presence.csv'
        history.export_history(job,exported)
        with exported.open(encoding='utf-8-sig',newline='') as stream:
            readings = list(csv.DictReader(stream))
        first_boot = next(r for r in readings if r['DUT ID']==self.a and r['来源事件 ID']=='1')
        self.assertEqual((first_boot['boot_id'],float(first_boot['uptime_seconds']),first_boot['启动周期变化']),
                         ('boot-A',50, '0'))
        cycle = next(r for r in readings if r['来源事件 ID']=='6')
        self.assertEqual((cycle['boot_id'],cycle['uptime_seconds'],cycle['启动周期变化']),('boot-B','','1'))
        self.assertEqual(readings[0]['启动周期变化'],'')

    def test_real_jsonl_presence_updates_only_the_named_dut_and_keeps_metadata_after_stop(self):
        profile = read_project_profile(self.ctx.config_dir)
        profile['type_config'] = dict(collectors=['dut_presence'],feed_collectors=['dut_presence'])
        write_project_profile(self.ctx.config_dir,profile)
        self.store.save(self.ctx)
        self.job.configuration_root = self.store.snapshot(self.ctx)
        plan = self.service.prepare()
        inbox = self.ctx.history/'aging-input'/(self.job.job_id+'.jsonl')
        def wait(stop, delay):
            self.now += delay
            if self.now == self.t0+30:
                sample = dict(self.sample(self.a,'presence-1',25),collector='dut_presence',
                              boot_id='boot.review-1',uptime_seconds=13.5)
                inbox.write_text(json.dumps(sample)+'\n',encoding='utf-8')
            else:
                a,b = self.service.snapshot()['dut_presence']
                self.assertEqual((a['state'],a['last_observation'],a['last_received']),
                                 ('online',self.t0+25,self.t0+30))
                self.assertEqual((b['state'],b['last_heartbeat']),('unknown',None))
                stop.request_stop()
        self.service.wait = wait
        self.assertEqual(self.service.run(self.job,plan)['state'],'stopped')
        reading, = self.service.history_page(self.job.job_id)['rows']
        self.assertEqual((reading['kind'],reading['source'],reading['boot_id'],reading['uptime_seconds']),
                         ('sample','jsonl','boot.review-1',13.5))
        a = self.service.snapshot()['dut_presence'][0]
        self.assertEqual((a['state'],a['last_boot_at'],a['last_uptime_at']),('unknown',self.t0+25,self.t0+25))

    def test_manifest_conflict_keeps_icmp_and_manual_working_then_retries_file_input(self):
        profile = read_project_profile(self.ctx.config_dir)
        profile['type_config']['collectors'].append('lan_ping')
        write_project_profile(self.ctx.config_dir,profile)
        self.ctx.config_dir.joinpath('network_card_ip.ini').write_text(
            '[channel_1]\nadapter_alias=nic\nnetwork_card_ip=192.0.2.2\ndevice_manage_ip=192.0.2.1\nenabled=1\n',
            encoding='utf-8')
        self.store.save(self.ctx)
        self.job.configuration_root = self.store.snapshot(self.ctx)
        self.service.inventory = lambda:[dict(name='nic',guid='guid-a',index=12,up=True,
                                             addresses=(('192.0.2.2',24),))]
        self.service.probe = Mock(return_value=True)
        plan = self.service.prepare()
        inbox = self.ctx.history/'aging-input'
        inbox.mkdir()
        manifest = inbox/(self.job.job_id+'.plan.json')
        samples = inbox/(self.job.job_id+'.jsonl')
        manifest.write_text('operator-owned',encoding='utf-8')
        def wait(stop, delay):
            self.now += delay
            if self.now == self.t0+30:
                self.assertEqual(manifest.read_text(encoding='utf-8'),'operator-owned')
                view = self.service.record(self.job.job_id,self.a,'keys_led','healthy','检查按键','operator')
                self.assertEqual(next(r for r in view['rows'] if r['dut_id']==self.a and
                                      r['collector']=='voice')['state'],'unknown')
                manifest.unlink()
                samples.write_text(json.dumps(self.sample(self.a,'recovered',20))+'\n',encoding='utf-8')
            else:
                stop.request_stop()
        self.service.wait = wait
        self.assertEqual(self.service.run(self.job,plan)['state'],'stopped')
        self.assertEqual(self.service.probe.call_count,2)
        rows = {r['collector']:r for r in self.service.snapshot()['rows'] if r['dut_id']==self.a}
        self.assertEqual((rows['voice']['source'],rows['voice']['checks']),('jsonl',1))
        self.assertEqual((rows['lan_ping']['source'],rows['lan_ping']['checks']),('icmp',2))
        self.assertEqual((rows['keys_led']['source'],rows['keys_led']['checks']),('manual',1))
        self.assertTrue(any('不可用' in str(call) for call in self.job.event.call_args_list))

    def test_burst_larger_than_a_reader_page_drains_in_one_sampling_tick(self):
        path = self.ctx.history/'aging-input'/(self.job.job_id+'.jsonl')
        def wait(stop, delay):
            self.now += delay
            if self.now == self.t0+30:
                with path.open('w',encoding='utf-8') as stream:
                    for index in range(160):
                        stream.write(json.dumps(self.sample(self.a,str(index),index/10))+'\n')
            else:
                stop.request_stop()
        self.service.wait = wait
        self.service.run(self.job,self.plan)
        row = next(r for r in self.service.snapshot()['rows'] if r['dut_id']==self.a and r['collector']=='voice')
        self.assertEqual(row['checks'],160)
        self.assertAlmostEqual(row['observed_seconds'],15.9,places=5)

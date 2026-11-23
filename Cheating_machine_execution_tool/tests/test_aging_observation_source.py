"""Job-scoped external facts. All producers and project files are local fixtures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from src.services.aging_observation_source import JsonlObservationSource, write_observation_manifest


class AgingObservationSourceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.context = SimpleNamespace(root=root, history=root / 'history',
                                       identity=SimpleNamespace(project_id='project-A'))
        self.context.history.mkdir()
        self.plan = dict(project_id='project-A', duts=[
            dict(dut_id='dut-1', label='样机 A', channel=1, hardware_id='fixture', password='not-for-export'),
            dict(dut_id='dut-2', label='样机 B', channel=None)],
            feed_collectors=['voice', 'iptv'], collectors=['voice', 'iptv', 'wan', 'lan_ping'],
            credential='not-for-export')
        self.job = '8caa8fce810b4a04a3a92ae7c81493fe'
        self.now = 1800000030
        self.start = self.now - 30
        self.reader = JsonlObservationSource(self.context, self.job, self.plan, started_at=self.start,
                                            clock=lambda: self.now, max_age=20)
        self.path = self.reader.path

    def line(self, event_id='1', *, at=None, **fields):
        at = self.now if at is None else at
        record = dict(project_id='project-A', job_id=self.job, dut_id='dut-1', collector='voice',
                      observed_at=datetime.fromtimestamp(at, timezone.utc).isoformat(), event_id=event_id,
                      outcome='healthy', detail='双向语音确认')
        record.update(fields)
        return json.dumps(record, ensure_ascii=False).encode('utf-8') + b'\n'

    def append(self, raw):
        self.path.parent.mkdir(exist_ok=True)
        with self.path.open('ab') as stream:
            stream.write(raw)

    def test_first_poll_reads_new_job_from_beginning_without_modifying_input(self):
        self.assertEqual(self.reader.poll().status, 'waiting')
        self.assertFalse(self.path.parent.exists())
        self.append(self.line('old', at=self.start - 1) + self.line('new', detail='已核对 双向语音'))
        self.path.chmod(stat.S_IREAD)
        self.addCleanup(self.path.chmod, stat.S_IWRITE | stat.S_IREAD)
        data = self.path.read_bytes()
        batch = self.reader.poll()
        self.assertEqual(batch.status, 'ready')
        self.assertEqual(batch.rejected, {'before_start': 1})
        observation, = batch.events
        self.assertEqual((observation.project_id, observation.job_id, observation.dut_id, observation.collector),
                         ('project-A', self.job, 'dut-1', 'voice'))
        self.assertEqual((observation.event_id, observation.evidence, observation.observed_at, observation.outcome),
                         ('new', '已核对 双向语音', self.now, 'healthy'))
        self.assertEqual(self.reader.poll().events, ())
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_subscriptions_offsets_timestamps_fields_and_event_identity(self):
        self.append(b''.join((
            self.line('id', at=self.now - 20), self.line('id', at=self.now - 20),
            self.line('id', dut_id='dut-2', outcome='abnormal'), self.line('id', collector='iptv', outcome='unknown'),
            self.line('zone', observed_at=datetime.fromtimestamp(self.now, timezone.utc).isoformat().replace('+00:00', 'Z')),
            self.line('local', observed_at=datetime.fromtimestamp(self.now, timezone(timedelta(hours=8))).isoformat()),
            self.line('a', project_id='project-B'),
            self.line('b', job_id='foreign'), self.line('c', dut_id='foreign'), self.line('d', collector='lan_ping'),
            self.line('e', collector='wan'), self.line('f', at=self.now - 21), self.line('g', at=self.now + 1),
            self.line('h', observed_at='2027-01-15T00:00:00'), self.line('i', observed_at=self.now),
            self.line('j', outcome='ok'), self.line('', detail='x'), self.line('k', schema_version=True),
            b'{"event_id":"1","event_id":"2"}\n', b'{"value":NaN}\n', b'\xff\xfe\n', b'[]\n',
            self.line('a'*129), b'{"project_id":"project-A","job_id":"' + self.job.encode() +
                b'","dut_id":"dut-1","collector":"voice","event_id":"bad","detail":"\\ud800"}\n',
        )))
        batch = self.reader.poll()
        self.assertEqual([e.event_id for e in batch.events], ['id','id','id','zone','local'])
        self.assertEqual(batch.events[-1].observed_at, self.now)
        self.assertEqual(batch.rejected, dict(duplicate=1, wrong_batch=2, unsubscribed=3,
                                              expired=1, future=1, invalid_time=2, invalid_fields=6, invalid_json=3))

    def test_partial_utf8_crlf_and_bom_work_without_emitting_incomplete_facts(self):
        row = b'\xef\xbb\xbf' + self.line('partial').rstrip(b'\n') + b'\r\n'
        split = row.index('双'.encode('utf-8')) + 1
        self.append(row[:split])
        for _ in range(2):
            self.assertEqual(self.reader.poll().events, ())
        self.append(row[split:-1])
        self.assertEqual(self.reader.poll().events, ())
        self.append(row[-1:])
        self.assertEqual(self.reader.poll().events[0].evidence, '双向语音确认')

    def test_dut_presence_requires_a_frozen_subscription_and_preserves_explicit_device_observations(self):
        self.append(b''.join((
            self.line('heartbeat', collector='dut_presence', boot_id='fw-1:abc.4', uptime_seconds=0),
            self.line('clock', collector='dut_presence', uptime_seconds=13.25),
            self.line('boot', collector='dut_presence', boot_id='B' * 128),
            self.line('online', collector='dut_presence'),
            self.line('offline', collector='dut_presence', outcome='abnormal'),
            self.line('unknown', collector='dut_presence', outcome='unknown'),
            self.line('voice', outcome='abnormal'),
        )))
        previous = self.reader.poll()
        self.assertEqual(previous.rejected, {'unsubscribed': 6})
        self.assertEqual([(e.collector, e.boot_id, e.uptime_seconds) for e in previous.events],
                         [('voice', None, None)])
        plan = dict(self.plan, feed_collectors=['voice', 'dut_presence'])
        reader = JsonlObservationSource(self.context, self.job, plan, started_at=self.start, clock=lambda: self.now)
        batch = reader.poll()
        self.assertEqual(batch.rejected, {})
        self.assertEqual([(e.event_id, e.outcome, e.boot_id, e.uptime_seconds) for e in batch.events], [
            ('heartbeat', 'healthy', 'fw-1:abc.4', 0.0), ('clock', 'healthy', None, 13.25),
            ('boot', 'healthy', 'B' * 128, None), ('online', 'healthy', None, None),
            ('offline', 'abnormal', None, None), ('unknown', 'unknown', None, None),
            ('voice', 'abnormal', None, None)])

    def test_boot_evidence_rejects_wrong_stream_state_and_malformed_fields_before_deduplication(self):
        plan = dict(self.plan, feed_collectors=['voice', 'dut_presence'])
        reader = JsonlObservationSource(self.context, self.job, plan, started_at=self.start, clock=lambda: self.now)
        invalid = [self.line('e', collector='dut_presence', boot_id=value)
                   for value in (None, '', '.boot', '  boot', 'b oo t', 'bad\nID', 'x' * 129, [], 9)]
        invalid.extend(self.line('e', collector='dut_presence', uptime_seconds=value)
                       for value in (True, None, '10', -1, [], {}, 10**360))
        invalid.append(self.line('e', collector='dut_presence', uptime_seconds='overflow').replace(b'"overflow"', b'1e999'))
        for collector, outcome in (('voice', 'healthy'), ('dut_presence', 'abnormal'), ('dut_presence', 'unknown')):
            invalid.extend([self.line('e', collector=collector, outcome=outcome, boot_id='boot-1'),
                            self.line('e', collector=collector, outcome=outcome, uptime_seconds=0)])
        self.append(b''.join(invalid) + self.line('e', collector='dut_presence', uptime_seconds=30))
        batch = reader.poll()
        self.assertEqual(batch.rejected, {'invalid_fields': len(invalid)})
        self.assertEqual([(e.event_id, e.boot_id, e.uptime_seconds) for e in batch.events], [('e', None, 30.0)])

    def test_rotation_and_copytruncate_restart_without_joining_incomplete_lines_or_replaying_ids(self):
        self.append(self.line('once') + b'{"partial":')
        self.assertEqual([e.event_id for e in self.reader.poll().events], ['once'])
        self.path.rename(self.path.with_suffix('.rotated'))
        self.assertEqual(self.reader.poll().status, 'waiting')
        self.append(self.line('once') + self.line('after_rotation'))
        rotated = self.reader.poll()
        self.assertEqual((rotated.status, [e.event_id for e in rotated.events], rotated.rejected),
                         ('reset', ['after_rotation'], {'duplicate': 1}))
        # Same inode, regrown beyond the old offset between polls.
        self.path.write_bytes(self.line('after_rotation') + self.line('regrown', detail='新证据' * 250))
        regrown = self.reader.poll()
        self.assertEqual((regrown.status, [e.event_id for e in regrown.events], regrown.rejected),
                         ('reset', ['regrown'], {'duplicate': 1}))

    def test_read_and_line_limits_do_not_drop_good_rows_after_oversize_unterminated_data(self):
        self.reader.BYTE_BUDGET = 512
        self.reader.LINE_BUDGET = 2
        self.reader.MAX_LINE = 420
        self.append(b'x' * 4096)
        rejected = 0
        for part in range(8):
            result = self.reader.poll()
            self.assertEqual(result.has_more, part < 7)
            rejected += result.rejected.get('oversize', 0)
            self.assertFalse(result.events)
            self.assertLessEqual(len(self.reader._partial), self.reader.MAX_LINE)
        self.assertEqual(rejected, 1)
        self.append(b'\n' + b'\n' * 5 + b''.join(self.line(str(i)) for i in range(8)))
        received = []
        for _ in range(14):
            result = self.reader.poll()
            self.assertLessEqual(len(result.events) + sum(result.rejected.values()), 2)
            received.extend(e.event_id for e in result.events)
        self.assertEqual(received, list(map(str, range(8))))

    def test_manifest_is_atomic_job_scoped_idempotent_and_contains_only_public_plan_fields(self):
        def publish(_):
            return write_observation_manifest(self.context, self.job, self.plan, self.start)
        with ThreadPoolExecutor(max_workers=4) as group:
            paths = list(group.map(publish, range(12)))
        path = paths[0]
        self.assertEqual(set(paths), {self.path.with_suffix('.plan.json')})
        manifest = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual(manifest['project_id'], 'project-A')
        self.assertEqual(manifest['job_id'], self.job)
        self.assertEqual(datetime.fromisoformat(manifest['started_at']).timestamp(), self.start)
        self.assertEqual(manifest['feed_collectors'], ['voice', 'iptv'])
        self.assertEqual(manifest['duts'], [
            dict(dut_id='dut-1', label='样机 A', channel=1, hardware_id='fixture'),
            dict(dut_id='dut-2', label='样机 B', channel=None)])
        self.assertNotIn('not-for-export', path.read_text(encoding='utf-8'))
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            write_observation_manifest(self.context, self.job, self.plan, self.start + 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_names_and_redirected_files_never_cross_into_another_job_or_touch_external_data(self):
        for name in ('../other', '/tmp/a', 'x:y', 'x.y', 'CON', 'NUL', 'a/b', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                write_observation_manifest(self.context, name, self.plan, self.start)
            with self.subTest(name=name), self.assertRaises(ValueError):
                JsonlObservationSource(self.context, name, self.plan, started_at=self.start)
        with self.assertRaises(ValueError):
            JsonlObservationSource(self.context, self.job, dict(self.plan, project_id='other'), started_at=self.start)
        foreign = self.context.root / 'external'
        foreign.mkdir()
        self.path.parent.symlink_to(foreign, target_is_directory=True)
        self.assertEqual(self.reader.poll().rejected, {'unsafe_path': 1})
        with self.assertRaises((OSError, ValueError)):
            write_observation_manifest(self.context, self.job, self.plan, self.start)
        self.assertFalse(list(foreign.iterdir()))
        self.path.parent.unlink()
        self.path.parent.mkdir()
        original = foreign / 'evidence'
        original.write_bytes(self.line('outside'))
        os.link(original, self.path)
        self.assertEqual(self.reader.poll().status, 'unavailable')
        self.assertEqual(original.read_bytes(), self.line('outside'))

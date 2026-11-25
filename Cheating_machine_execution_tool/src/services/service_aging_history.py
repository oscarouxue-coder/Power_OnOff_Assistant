"""Project-local continuous monitoring evidence, aggregated at observation time."""
from contextlib import closing, contextmanager
import csv
from datetime import datetime
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from src.services.service_aging_presence import PRESENCE, SCHEMA as PRESENCE_SCHEMA, presence_view, record_presence


_PROCESS = uuid.uuid4().hex
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs(job TEXT PRIMARY KEY,project TEXT,revision TEXT,process TEXT,state TEXT,
    started REAL,ended REAL,tick REAL,elapsed REAL,target_hours INTEGER,freshness REAL);
CREATE TABLE IF NOT EXISTS streams(job TEXT,dut TEXT,label TEXT,collector TEXT,source TEXT,state TEXT,detail TEXT,
    checks INTEGER DEFAULT 0,successes INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,last_success REAL,
    streak INTEGER DEFAULT 0,observed REAL DEFAULT 0,abnormal REAL DEFAULT 0,recoveries INTEGER DEFAULT 0,
    last_at REAL,last_tick REAL,heartbeat REAL,PRIMARY KEY(job,dut,collector));
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,job TEXT,dut TEXT,collector TEXT,kind TEXT,
    outcome TEXT,at REAL,day TEXT,evidence TEXT,operator TEXT);
CREATE INDEX IF NOT EXISTS observations_kind ON observations(job,kind,id);
CREATE TABLE IF NOT EXISTS feed_receipts(job TEXT,dut TEXT,collector TEXT,event_id TEXT,
    observation_id INTEGER UNIQUE,received_at REAL,PRIMARY KEY(job,dut,collector,event_id));
CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,job TEXT,dut TEXT,collector TEXT,
    first_at REAL,last_at REAL,closed_at REAL,reason TEXT);
CREATE INDEX IF NOT EXISTS incidents_stream ON incidents(job,dut,collector,closed_at);
'''


class ServiceAgingHistory:
    def __init__(self, context, clock):
        self.context, self.clock = context, clock
        self.path = context.history / 'service_aging.sqlite3'

    @contextmanager
    def _db(self):
        if self.path.is_symlink() or self.context.history.resolve() != self.context.history:
            raise ValueError('持续老化记录目录不能重定向')
        with closing(sqlite3.connect(str(self.path), timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def begin(self, job, plan, freshness):
        now = self.clock()
        with self._db() as db:
            db.executescript(_SCHEMA + (PRESENCE_SCHEMA if PRESENCE in plan.get('feed_collectors', ()) else ''))
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (job, self.context.identity.project_id, plan['revision'], _PROCESS, 'running',
                        now, None, now, 0, plan['target_hours'], freshness))
            for dut in plan['duts']:
                for collector in (*plan['collectors'], 'cpu_memory'):
                    source, detail = 'manual', '等待现场记录'
                    if collector == 'lan_ping':
                        source = 'icmp' if dut['binding'] else 'unavailable'
                        detail = '等待首次采样' if dut['binding'] else dut['reason']
                    if collector == 'cpu_memory':
                        source, detail = 'unavailable', '缺少设备 CPU / 内存采集器'
                    elif collector in plan.get('feed_collectors', ()) and collector != 'lan_ping':
                        source, detail = 'jsonl', '等待本 DUT 的现场采集数据'
                    state = 'unavailable' if source == 'unavailable' else 'unknown'
                    db.execute('INSERT INTO streams(job,dut,label,collector,source,state,detail) VALUES(?,?,?,?,?,?,?)',
                               (job, dut['dut_id'], dut['label'], collector, source, state, detail))
        return now

    def _run(self, db, job):
        row = db.execute('SELECT * FROM runs WHERE job=? AND project=?',
                         (job, self.context.identity.project_id)).fetchone()
        if not row:
            raise ValueError('本项目没有该持续老化批次')
        return row

    def tick(self, job, elapsed, state='running'):
        now = self.clock()
        with self._db() as db:
            db.execute('UPDATE runs SET state=?,tick=?,elapsed=?,ended=? WHERE job=? AND project=? AND process=?',
                       (state, now, elapsed, None if state == 'running' else now,
                        job, self.context.identity.project_id, _PROCESS))
            if state != 'running':
                db.execute("UPDATE incidents SET closed_at=?,reason=? WHERE job=? AND closed_at IS NULL",
                           (now, state, job))

    def feed_gap(self, job):
        """An unavailable/replaced source cannot bridge two observed intervals."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, job)
            if run['state'] != 'running' or run['process'] != _PROCESS:
                return
            db.execute("""UPDATE streams SET state='unknown',last_tick=NULL,streak=0,
                detail='采集文件中断，等待新的现场数据' WHERE job=? AND source='jsonl'""", (job,))
            db.execute("""UPDATE incidents SET closed_at=?,reason='source_gap' WHERE job=? AND closed_at IS NULL
                AND collector IN (SELECT collector FROM streams WHERE job=? AND source='jsonl')""",
                       (self.clock(), job, job))

    def observe(self, job, dut, collector, outcome, detail, operator, *, kind, elapsed=None, feed_event=None):
        if outcome not in ('healthy', 'abnormal', 'unknown'):
            raise ValueError('请记录正常、异常或未知的实际结果')
        if kind not in ('sample', 'observation', 'daily', 'final'):
            raise ValueError('检查记录类型无效')
        if not isinstance(detail, str) or not detail.strip() or (
                kind != 'sample' and (not isinstance(operator, str) or not operator.strip())):
            raise ValueError('请填写记录人和本次检查证据')
        received_at = self.clock()
        now = received_at
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, job)
            active = run['state'] == 'running' and run['process'] == _PROCESS
            if not active and not (kind == 'final' and run['state'] in ('target_reached', 'stopped')):
                raise ValueError('该批次已结束或中断，未记入本次观测')
            row = db.execute('SELECT * FROM streams WHERE job=? AND dut=? AND collector=?',
                             (job, dut, collector)).fetchone()
            if not row or row['source'] == 'unavailable':
                raise ValueError('DUT 或采集项不在本批次可记录范围')
            if collector == PRESENCE and feed_event is None:
                raise ValueError('DUT 在线状态只能来自本批次的现场专属观测')
            if feed_event is not None:
                if not (kind == 'sample' and row['source'] == 'jsonl' and
                        (feed_event.project_id,feed_event.job_id,feed_event.dut_id,feed_event.collector,
                         feed_event.outcome,feed_event.evidence) ==
                        (run['project'],job,dut,collector,outcome,detail) and feed_event.event_id):
                    raise ValueError('现场观测不属于当前批次的订阅流')
                key = (job,dut,collector,feed_event.event_id)
                if db.execute('SELECT 1 FROM feed_receipts WHERE job=? AND dut=? AND collector=? AND event_id=?',
                              key).fetchone():
                    return 'duplicate'
                now = feed_event.observed_at
                if (type(now) not in (int,float) or not math.isfinite(now)
                        or not run['started'] <= now <= received_at or received_at-now > run['freshness']):
                    return 'invalid_time'
                if row['last_at'] is not None and now <= row['last_at']:
                    return 'out_of_order'
                elapsed = now - run['started']
            elif kind == 'sample' and row['source'] != 'icmp':
                raise ValueError('该项没有自动采集源')
            if kind == 'observation' and row['source'] != 'manual':
                raise ValueError('自动采集项请使用日检或末检记录现场人工依据')
            day = datetime.fromtimestamp(now).date().isoformat()
            inserted = db.execute('INSERT INTO observations(job,dut,collector,kind,outcome,at,day,evidence,operator) '
                                  'VALUES(?,?,?,?,?,?,?,?,?)', (job,dut,collector,kind,outcome,now,day,detail.strip(),operator))
            if feed_event is not None:
                db.execute('INSERT INTO feed_receipts VALUES(?,?,?,?,?,?)', (*key,inserted.lastrowid,received_at))
                if collector == PRESENCE:
                    record_presence(db,job,dut,inserted.lastrowid,feed_event)
                    return
            # Daily/final forms carry their own evidence. They do not count as
            # network probes, or as observations made after monitoring ended.
            if (row['source'] != 'manual' and kind != 'sample') or not active:
                return
            valid = outcome != 'unknown'
            previous_valid = row['state'] in ('healthy', 'abnormal')
            delta = elapsed - row['last_tick'] if elapsed is not None and row['last_tick'] is not None else 0
            adjacent = valid and previous_valid and 0 < delta <= run['freshness']
            linked = adjacent or (row['source'] == 'manual' and previous_valid and
                                  0 <= now - row['last_at'] <= 86400)
            consecutive = row['streak'] + 1 if row['state'] == 'abnormal' and linked else 1
            recovered = outcome == 'healthy' and row['state'] == 'abnormal' and linked
            stream = (job, dut, collector)
            if outcome != 'abnormal' or not linked:
                reason = 'recovered' if recovered else 'observation_gap'
                db.execute('UPDATE incidents SET closed_at=?,reason=? WHERE job=? AND dut=? AND collector=? '
                           'AND closed_at IS NULL', (now, reason, *stream))
            if outcome == 'abnormal':
                if row['state'] == 'abnormal' and linked:
                    db.execute('UPDATE incidents SET last_at=? WHERE job=? AND dut=? AND collector=? '
                               'AND closed_at IS NULL', (now, *stream))
                else:
                    db.execute('INSERT INTO incidents(job,dut,collector,first_at,last_at) VALUES(?,?,?,?,?)',
                               (*stream, now, now))
            observed = delta if adjacent else 0
            # A sample on each side of an outage bounds the evidenced period.
            abnormal = observed if outcome == row['state'] == 'abnormal' else 0
            db.execute('''UPDATE streams SET state=?,detail=?,checks=checks+?,successes=successes+?,
                failures=failures+?,last_success=?,streak=?,observed=observed+?,abnormal=abnormal+?,
                recoveries=recoveries+?,last_at=?,last_tick=?,heartbeat=?
                WHERE job=? AND dut=? AND collector=?''',
                (outcome,detail.strip(),int(valid),int(outcome=='healthy'),int(outcome=='abnormal'),
                 now if outcome=='healthy' else row['last_success'], consecutive if outcome=='abnormal' else 0,
                 observed,abnormal,int(recovered),now,elapsed,
                 now if feed_event is not None or kind=='sample' and outcome=='healthy' else row['heartbeat'],
                 job,dut,collector))

    def snapshot(self, job=None):
        if not self.path.exists():
            return {}
        now = self.clock()
        with self._db() as db:
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                return {}
            if job is None:
                row = db.execute('SELECT job FROM runs WHERE project=? ORDER BY rowid DESC LIMIT 1',
                                 (self.context.identity.project_id,)).fetchone()
                if not row:
                    return {}
                job = row['job']
            run = self._run(db, job)
            state = run['state']
            if state == 'running' and run['process'] != _PROCESS:
                state = 'interrupted'
            rows, duts, presence_streams = [], {}, {}
            for r in db.execute('SELECT * FROM streams WHERE job=? ORDER BY rowid', (job,)):
                duts[r['dut']] = r['label']
                if r['collector'] == PRESENCE:
                    if r['source'] == 'jsonl':
                        presence_streams[r['dut']] = r
                    continue
                health = r['state']
                stale_after = 86400 if r['source'] == 'manual' else run['freshness']
                if health != 'unavailable' and (state == 'interrupted' or (
                        state == 'running' and r['last_at'] is not None and
                        not 0 <= now - r['last_at'] <= stale_after)):
                    health = 'unknown'
                if r['source'] == 'jsonl' and run['ended'] is not None and (
                        r['last_at'] is None or not 0 <= run['ended'] - r['last_at'] <= stale_after):
                    health = 'unknown'
                rows.append(dict(dut_id=r['dut'], label=r['label'], collector=r['collector'], source=r['source'],
                   state=health, checks=r['checks'], successes=r['successes'], failures=r['failures'],
                   success_rate=r['successes']/r['checks'] if r['checks'] else None,
                   last_success=r['last_success'], consecutive_failures=r['streak'],
                   abnormal_seconds=r['abnormal'], observed_seconds=r['observed'], recoveries=r['recoveries'],
                   last_heartbeat=r['heartbeat'], last_observation=r['last_at'], detail=r['detail'],
                   packet_loss=r['failures']/r['checks'] if r['source']=='icmp' and r['checks'] else None))
            inspections = {kind: self._page(db, job, before_id=None, kind=kind, limit=100)['rows']
                           for kind in ('daily', 'final')}
            incidents = [dict(r) for r in db.execute('SELECT dut AS dut_id,collector,first_at,last_at,closed_at,reason '
                'FROM incidents WHERE job=? ORDER BY id DESC LIMIT 100',(job,))]
            presence = presence_view(db, run, state, now, duts, presence_streams)
        return dict(job_id=job, state=state, started=run['started'], ended=run['ended'], revision=run['revision'],
                    dut_presence=presence,
                    feed_path=str(self.context.history / 'aging-input' / (job + '.jsonl'))
                    if presence_streams or any(row['source'] == 'jsonl' for row in rows) else '',
                    target_hours=run['target_hours'],elapsed_seconds=run['elapsed'], rows=rows,incidents=incidents,
                    daily_checks=inspections['daily'], final_checks=inspections['final'])

    @staticmethod
    def _observation_query(db, *, excerpt=False):
        # Older databases are readable without a migration or a write on first inspection.
        feed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feed_receipts'").fetchone()
        extras = 'f.event_id,coalesce(f.received_at,o.at) AS received_at' if feed else 'NULL AS event_id,o.at AS received_at'
        join = ' LEFT JOIN feed_receipts f ON f.observation_id=o.id' if feed else ''
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dut_presence_samples'").fetchone():
            extras += ',p.boot_id,p.uptime_seconds,CASE WHEN p.boot_id IS NOT NULL THEN p.boot_changed END AS boot_changed'
            join += ' LEFT JOIN dut_presence_samples p ON p.observation_id=o.id'
        else:
            extras += ',NULL AS boot_id,NULL AS uptime_seconds,NULL AS boot_changed'
        evidence = 'substr(o.evidence,1,512) AS evidence' if excerpt else 'o.evidence'
        return f"""SELECT o.id,o.dut AS dut_id,s.label,o.collector,o.kind,o.outcome,o.at,o.day,{evidence},o.operator,
            CASE WHEN o.kind='sample' THEN s.source ELSE 'manual' END AS source,{extras}
            FROM observations o JOIN streams s USING(job,dut,collector){join} WHERE o.job=?"""

    @staticmethod
    def _page(db, job, *, before_id, kind, limit):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('每页记录数须为 1–200')
        if before_id is not None and (type(before_id) is not int or before_id <= 0):
            raise ValueError('记录游标无效')
        sql = ServiceAgingHistory._observation_query(db)
        args = [job]
        if kind is not None:
            if kind not in ('observation','daily','final','sample'):
                raise ValueError('检查记录类型无效')
            sql += ' AND o.kind=?'
            args.append(kind)
        if before_id is not None:
            sql += ' AND o.id<?'
            args.append(before_id)
        rows = [dict(r) for r in db.execute(sql + ' ORDER BY o.id DESC LIMIT ?', (*args, limit + 1))]
        return dict(rows=rows[:limit], next_before=rows[limit-1]['id'] if len(rows)>limit else None)

    def channel_observations(self, job, revision, dut, stop, *, current_only=False):
        """Bound rows, excerpt length, SQLite work and lock waits for a single local question."""
        if self.path.resolve() != self.path or not self.path.is_file():
            raise ValueError('本项目缺少可读取的老化历史')
        # The aging writer uses SQLite's rollback journal. A read-only open of
        # a WAL database can create sidecars, even with mode=ro.
        with self.path.open('rb') as header:
            header.seek(18)
            if header.read(2) == b'\x02\x02':
                raise ValueError('此历史库采用 WAL 格式，本地只读查询未打开数据库')
        deadline = time.monotonic() + 1.5
        budget = 500

        def interrupt():
            nonlocal budget
            budget -= 1
            return stop.is_set() or budget <= 0 or time.monotonic() >= deadline

        try:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
                db.row_factory = sqlite3.Row
                db.set_progress_handler(interrupt, 1000)
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                if current_only:
                    current = db.execute('SELECT job FROM runs WHERE project=? ORDER BY rowid DESC LIMIT 1',
                                         (self.context.identity.project_id,)).fetchone()
                    if current is None or current['job'] != job:
                        raise ValueError('当前老化批次已变化，未读取观测')
                run = self._run(db, job)
                if run['revision'] != revision:
                    raise ValueError('观测记录与冻结批次版本不一致')
                if stop.is_set():
                    raise InterruptedError()
                query = self._observation_query(db, excerpt=True)
                sql = ('SELECT id,collector,kind,outcome,at,evidence,source,event_id IS NOT NULL AS has_event '
                       'FROM (' + query + ' AND o.dut=?) ORDER BY id DESC LIMIT 48')
                rows = db.execute(sql, (job, dut)).fetchall()
                return rows, run
        except sqlite3.Error as error:
            if stop.is_set():
                raise InterruptedError() from error
            raise ValueError('证据读取未完成，数据库忙、格式异常或达到查询上限') from error

    def history_page(self, job, *, before_id=None, kind=None, limit=100):
        if not self.path.exists():
            raise ValueError('本项目没有持续老化记录')
        with self._db() as db:
            self._run(db, job)
            return self._page(db, job, before_id=before_id, kind=kind, limit=limit)

    def list_runs(self, *, before_id=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('每页批次数须为 1–200')
        if before_id is not None and (type(before_id) is not int or before_id <= 0):
            raise ValueError('批次游标无效')
        rows = []
        if self.path.exists():
            with self._db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                    sql = '''SELECT rowid AS id,job AS job_id,started,ended,state,revision,target_hours,process
                        FROM runs WHERE project=?'''
                    args = [self.context.identity.project_id]
                    if before_id is not None:
                        sql += ' AND rowid<?'
                        args.append(before_id)
                    for r in db.execute(sql + ' ORDER BY rowid DESC LIMIT ?', (*args, limit+1)):
                        row = dict(r)
                        process = row.pop('process')
                        if row['state'] == 'running' and process != _PROCESS:
                            row['state'] = 'interrupted'
                        rows.append(row)
        return dict(rows=rows[:limit],next_before=rows[limit-1]['id'] if len(rows)>limit else None)

    def export_history(self, job, destination):
        path = Path(destination)
        if not path.is_absolute() or path.suffix.lower() != '.csv':
            raise ValueError('请选择绝对路径下的新 .csv 记录文件')
        if not self.path.exists():
            raise ValueError('本项目没有持续老化记录')
        with self._db() as db:
            run = self._run(db, job)
            high_water = db.execute('SELECT MAX(id) FROM observations WHERE job=?',(job,)).fetchone()[0] or 0
        output = tempfile.NamedTemporaryFile(mode='w',encoding='utf-8-sig',newline='',dir=path.parent,
                                             prefix='.dutpilot-aging-',delete=False)
        pending = Path(output.name)
        count, cursor = 0, 0
        try:
            with output:
                writer = csv.writer(output)
                writer.writerow(('项目 ID','批次 ID','配置版本','记录 ID','时间','DUT ID','DUT 名称','采集项','记录类型','结果','证据','记录人',
                                 '采集来源','来源事件 ID','接收时间','boot_id','uptime_seconds','启动周期变化'))
                # Observations are append-only. Keep a fixed export boundary but
                # release the SQLite read transaction between pages for the sampler.
                while cursor < high_water:
                    with self._db() as db:
                        rows = db.execute(self._observation_query(db) + ' AND o.id>? AND o.id<=? ORDER BY o.id LIMIT 200',
                                          (job,cursor,high_water)).fetchall()
                    if not rows:
                        break
                    for r in rows:
                        writer.writerow((run['project'],job,run['revision'],r['id'],
                            datetime.fromtimestamp(r['at']).astimezone().isoformat(),r['dut_id'],r['label'],r['collector'],
                            r['kind'],r['outcome'],r['evidence'],r['operator'],r['source'],r['event_id'] or '',
                            datetime.fromtimestamp(r['received_at']).astimezone().isoformat(),
                            r['boot_id'],r['uptime_seconds'],r['boot_changed']))
                    cursor = rows[-1]['id']
                    count += len(rows)
            if os.name == 'nt':
                pending.rename(path)
            else:
                os.link(pending,path)
        except FileExistsError:
            raise ValueError('文件已存在，请选择新的文件名') from None
        finally:
            pending.unlink(missing_ok=True)
        return count

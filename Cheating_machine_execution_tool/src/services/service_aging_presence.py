"""Keep DUT presence and observed boot changes separate from per-business health."""


PRESENCE = 'dut_presence'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS dut_presence_samples(
    observation_id INTEGER PRIMARY KEY,job TEXT NOT NULL,dut TEXT NOT NULL,boot_id TEXT,uptime_seconds REAL,
    boot_changed INTEGER NOT NULL,reboot_count INTEGER NOT NULL,last_reboot_at REAL,
    last_boot_id TEXT,last_boot_at REAL,last_uptime_seconds REAL,last_uptime_at REAL);
CREATE INDEX IF NOT EXISTS dut_presence_latest ON dut_presence_samples(job,dut,observation_id);
'''


def record_presence(db, job, dut, observation_id, event):
    previous = db.execute('SELECT * FROM dut_presence_samples WHERE job=? AND dut=? '
                          'ORDER BY observation_id DESC LIMIT 1', (job,dut)).fetchone()
    previous = dict(previous) if previous else {}
    at = event.observed_at
    boot = getattr(event, 'boot_id', None)
    uptime = getattr(event, 'uptime_seconds', None)
    if event.outcome != 'healthy' and (boot is not None or uptime is not None):
        raise ValueError('离线或未知观测不能提供 DUT 启动元数据')
    last_boot = previous.get('last_boot_id')
    new_boot = boot is not None and boot != last_boot
    changed = boot is not None and last_boot is not None and boot != last_boot
    last_uptime = previous.get('last_uptime_seconds')
    last_uptime_at = previous.get('last_uptime_at')
    if new_boot:
        # An earlier time can belong to a different, or as-yet unidentified, boot.
        last_uptime = last_uptime_at = None
    if uptime is not None:
        last_uptime, last_uptime_at = uptime, at
    count = previous.get('reboot_count', 0) + int(changed)
    db.execute('INSERT INTO dut_presence_samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (
        observation_id,job,dut,boot,uptime,int(changed),count,
        at if changed else previous.get('last_reboot_at'),
        boot if boot is not None else last_boot,
        at if boot is not None else previous.get('last_boot_at'),
        last_uptime,last_uptime_at))
    db.execute('''UPDATE streams SET state=?,detail=?,last_at=?,
        heartbeat=CASE WHEN ?='healthy' THEN ? ELSE heartbeat END
        WHERE job=? AND dut=? AND collector=?''',
        (event.outcome,event.evidence,at,event.outcome,at,job,dut,PRESENCE))


def presence_view(db, run, state, now, duts, streams):
    result = []
    for dut, label in duts.items():
        stream = streams.get(dut)
        item = dict(dut_id=dut,label=label,subscribed=stream is not None,state='unknown',last_outcome=None,
                    last_observation=None,last_received=None,last_heartbeat=None,detail='',event_id=None,
                    boot_id=None,uptime_seconds=None,reboot_count=None,last_reboot_at=None,last_boot_id=None,
                    last_boot_at=None,last_uptime_seconds=None,last_uptime_at=None)
        result.append(item)
        if stream is None:
            continue
        row = db.execute('''SELECT p.*,o.outcome,o.at,o.evidence,f.received_at,f.event_id
            FROM dut_presence_samples p JOIN observations o ON o.id=p.observation_id
            JOIN feed_receipts f ON f.observation_id=o.id WHERE p.job=? AND p.dut=?
            ORDER BY p.observation_id DESC LIMIT 1''', (run['job'],dut)).fetchone()
        if row is None:
            continue
        if state == 'running' and 0 <= now-row['at'] <= run['freshness']:
            item['state'] = {'healthy':'online','abnormal':'offline'}.get(stream['state'], 'unknown')
        item.update(last_outcome=row['outcome'],last_observation=row['at'],last_received=row['received_at'],
                    last_heartbeat=stream['heartbeat'],detail=row['evidence'])
        for key in ('event_id','boot_id','uptime_seconds','reboot_count','last_reboot_at','last_boot_id',
                    'last_boot_at','last_uptime_seconds','last_uptime_at'):
            item[key] = row[key]
        if row['last_boot_id'] is None:
            item['reboot_count'] = None
    return result

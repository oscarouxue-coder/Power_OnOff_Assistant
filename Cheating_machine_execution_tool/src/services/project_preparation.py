"""Per-DUT preparation plan and evidence ledger. Device commands stay with the original jobs."""
import configparser
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
import uuid

from src.services.project_profile_store import active_project_duts, configured_power_cycles, read_project_profile
from src.services.project_store import ProjectStore, configuration_digest


OPTIONAL_STEPS = {'parameters': '写入样机个参', 'wan': '配置 WAN', 'voice': '配置 VOICE', 'tr069': '配置 TR069'}
_CONTEXT_LOCK = threading.Lock()


def preparation_plan(profile):
    """Describe the selected steps. Suitable for a wizard preview before any project exists."""
    kind = profile.get('test_type') if profile else None
    if kind not in ('power_cycle', 'service_aging'):
        return ()
    options = set(profile.get('optional_steps', ()))
    if options - OPTIONAL_STEPS.keys():
        raise ValueError('存在无法识别的可选准备步骤')
    if options.intersection(('voice', 'tr069')):
        options.add('wan')
    steps = []

    def add(key, title, mode, *parents, optional=False):
        steps.append(dict(id=key, label=title, mode=mode, optional=optional, depends_on=parents))

    add('environment', '核对 DUT 身份、接线和资源', 'manual')
    if kind == 'power_cycle':
        add('management_ip', '核对统一管理 IP', 'manual', 'environment')
    else:
        add('telnet_credentials', '核对统一 Telnet 凭据', 'manual', 'environment')
    add('firmware', '核对固件升级与版本', 'automatic', 'environment')
    if 'parameters' in options:
        add('parameters', OPTIONAL_STEPS['parameters'], 'automatic', 'firmware', optional=True)
    provisioning = ('firmware', 'parameters') if 'parameters' in options else ('firmware',)
    add('onu', '注册 ONU 并核对上线', 'automatic', *provisioning)
    add('telnet', '开启并验证 Telnet', 'automatic', *provisioning,
        'management_ip' if kind == 'power_cycle' else 'telnet_credentials')
    if 'wan' in options:
        add('wan', OPTIONAL_STEPS['wan'], 'automatic', 'onu', 'telnet', optional=True)
    for key in ('voice', 'tr069'):
        if key in options:
            add(key, OPTIONAL_STEPS[key], 'automatic', 'wan', optional=True)
    if kind == 'service_aging':
        add('wifi', '配置并核对双频 WiFi', 'automatic', 'telnet')
    final_key, title, mode = (('pretest', '开关机预测试', 'automatic') if kind == 'power_cycle'
                              else ('initial_health', '现场初始业务检查', 'manual'))
    add(final_key, title, mode, *(step['id'] for step in steps))
    return tuple(steps)


def preparation_for(context, emit=None, *, emit_event=None):
    with _CONTEXT_LOCK:
        instance = getattr(context, '_preparation_service', None)
        if instance is None:
            instance = ProjectPreparation(context, emit)
            context._preparation_service = instance
        elif emit is not None:
            instance.emit = emit
        if emit_event is not None:
            instance.emit_event = emit_event
        return instance


def _digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _sections(directory, name):
    parser = configparser.RawConfigParser(strict=False)
    path = directory / name
    if path.is_symlink():
        raise ValueError('项目准备配置不能通过链接重定向')
    if path.is_file():
        with path.open(encoding='utf-8-sig') as stream:
            parser.read_file(stream)
    return {section: dict(parser.items(section)) for section in parser.sections()}


def _step_inputs(directory, profile):
    test = _sections(directory, 'test_project_config.ini')
    network = _sections(directory, 'network_card_ip.ini')
    upgrade = _sections(directory, 'sample_upgrade_settings.ini').get('sample_upgrade', {})
    common = {
        'telnet_credentials': {k: v for k, v in test.get('telnet', {}).items()
                               if k not in ('only_power_off_on', 'telnet_default_on')},
        'firmware': {k: v for k, v in upgrade.items() if not k.startswith('parameter_')},
        'parameters': {k: v for k, v in upgrade.items() if k.startswith('parameter_')},
        'onu': _sections(directory, 'onu_registration.ini'),
        'wifi': test.get('connect_wifi', {}),
        'pretest': (test.get('order', {}), test.get('connect_wifi', {}), test.get('telnet', {}),
                    profile.get('requirements'), profile.get('type_config')),
        'initial_health': (profile.get('requirements'), profile.get('type_config')),
    }
    if profile.get('environment_channels') and profile['test_type'] == 'power_cycle':
        try:
            cycles = configured_power_cycles(directory)
        except (KeyError, ValueError):
            cycles = None
        common['pretest'] = common['pretest'][:-1] + (cycles,)
    return common, network


def _binding(profile, dut, spec, common, network, parents):
    key = spec['id']
    identity = (profile['test_type'], profile.get('model'), dut['dut_id'], dut.get('hardware_id'))
    detail = common.get(key)
    channel = network.get('channel_' + str(dut.get('channel')), {})
    if key == 'environment':
        mapping = tuple(dut.get(k) for k in ('channel', 'serial_port', 'network_adapter', 'vlan', 'other_devices'))
        if profile.get('environment_channels'):
            mapping = (dut['channel'], dut.get('mapping_generation'), dut.get('other_devices'))
        if dut.get('adb_serial'):
            mapping += (dut['adb_serial'],)
        wiring = tuple(channel.get(k) for k in ('serial_port', 'adapter_alias', 'vlan_name', 'enabled'))
        power = (dut.get('power_channel') if not profile.get('environment_channels') else None,
                 network.get('power_supply')) if profile['test_type'] == 'power_cycle' else ()
        detail = (mapping, wiring, power)
    elif key == 'management_ip':
        detail = tuple(channel.get(k) for k in ('device_manage_ip', 'network_card_ip', 'subnet_mask'))
    elif key == 'telnet':
        detail = (common['telnet_credentials'], *(channel.get(k) for k in ('network_card_ip', 'device_manage_ip')))
    elif key == 'firmware':
        detail = (profile.get('software_version'), dut.get('target_firmware'), detail,
                  *(channel.get(k) for k in ('network_card_ip', 'device_manage_ip', 'factory_bind_ip', 'factory_device_host')))
    return _digest((identity, key, detail, parents))


def _required_text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'请填写{label}（最多 {maximum} 个字符）')
    return value.strip()


class ProjectPreparation:
    def __init__(self, context, emit=None):
        self.context = context
        self.emit = emit or (lambda message: None)
        self.emit_event = None
        self.session = uuid.uuid4().hex
        with closing(self._connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO preparation_session VALUES(?,?)', (context.identity.project_id, self.session))

    def _connect(self):
        ProjectStore._validate_paths(self.context)
        path = self.context.history / 'preparation.sqlite3'
        if path.resolve() != path:
            raise ValueError('准备证据库不能通过链接重定向')
        self.context.history.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=4)
        db.row_factory = sqlite3.Row
        try:
            db.execute('''CREATE TABLE IF NOT EXISTS preparation(
                seq INTEGER PRIMARY KEY, project TEXT NOT NULL, dut TEXT NOT NULL, step TEXT NOT NULL,
                binding TEXT NOT NULL, attempt TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, verification TEXT NOT NULL, operator TEXT NOT NULL,
                recorded TEXT NOT NULL, session TEXT NOT NULL, source TEXT NOT NULL DEFAULT '')''')
            db.execute('CREATE TABLE IF NOT EXISTS preparation_session(project TEXT PRIMARY KEY, session TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS preparation_jobs(
                project TEXT, dut TEXT, step TEXT, attempt TEXT, part TEXT, job TEXT, receipt TEXT,
                PRIMARY KEY(project,dut,step,job), UNIQUE(project,dut,step,attempt,part))''')
            db.execute('CREATE INDEX IF NOT EXISTS by_target ON preparation(project,dut,step,seq)')
        except BaseException:
            db.close()
            raise
        return db

    def _append(self, db, dut, step, binding, attempt, state, evidence, verification, operator, source=''):
        db.execute('''INSERT INTO preparation
            (project,dut,step,binding,attempt,state,evidence,verification,operator,recorded,session,source)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (self.context.identity.project_id, dut, step, binding, attempt, state,
                evidence, verification, operator, datetime.now(timezone.utc).isoformat(), self.session, source))

    def _snapshot(self, db):
        context = self.context
        owner = db.execute('SELECT session FROM preparation_session WHERE project=?', (context.identity.project_id,)).fetchone()
        if owner is None or owner[0] != self.session:
            raise ValueError('准备会话已关闭或由新工作区接管，请刷新')
        directory = context.saved_root / 'Auto_power_on_off_tool/config'
        profile = read_project_profile(directory)
        dirty = configuration_digest(directory) != configuration_digest(context.config_dir)
        view = dict(project_id=context.identity.project_id, test_type='', revision=context.identity.revision,
                    dirty=dirty, ready=False, verified=0, skipped=0, total=0, duts=[])
        if not profile:
            return view
        view['test_type'] = profile['test_type']
        view['environment_channels'] = bool(profile.get('environment_channels'))
        active_duts = active_project_duts(profile, directory)
        identifiers = [dut['hardware_id'].casefold() for dut in active_duts]
        plan = preparation_plan(profile)
        common, network = _step_inputs(directory, profile)
        rows = db.execute('''SELECT p.* FROM preparation p JOIN
            (SELECT MAX(seq) AS last FROM preparation WHERE project=? GROUP BY dut,step) latest
            ON p.seq=latest.last''', (view['project_id'],))
        latest = {(row['dut'], row['step']): row for row in rows}
        applicable = {(d['dut_id'], step['id']) for d in active_duts for step in plan}
        for (dut_id, key), row in latest.items():
            if (dut_id, key) not in applicable and row['state'] != 'stale':
                self._append(db, dut_id, key, row['binding'], row['attempt'], 'stale', row['evidence'],
                             row['verification'], '准备计划', row['source'])
        for dut in active_duts:
            target = dict(dut_id=dut['dut_id'], label=dut['label'], channel=dut['channel'], ready=False, steps=[])
            views = {}
            for spec in plan:
                parents = [views[parent] for parent in spec['depends_on']]
                inputs = [(p['id'], p['token']) for p in parents]
                binding = _binding(profile, dut, spec, common, network, inputs)
                row = latest.get((dut['dut_id'], spec['id']))
                state = row['state'] if row else 'pending'
                final = spec['id'] in ('pretest', 'initial_health')
                if row and state != 'stale' and (row['binding'] != binding
                        or final and state == 'verified' and row['session'] != self.session):
                    self._append(db, dut['dut_id'], spec['id'], binding, row['attempt'], 'stale',
                                 row['evidence'], row['verification'], '准备计划', row['source'])
                    row = db.execute('SELECT * FROM preparation WHERE seq=last_insert_rowid()').fetchone()
                    state = 'stale'
                elif row and state == 'running' and row['session'] != self.session:
                    state = 'interrupted'
                blocked = [p['id'] for p in parents if p['state'] != 'verified'
                           and not ((final or p['id'] == 'parameters') and p['optional'] and p['state'] == 'skipped')]
                token = _digest((view['project_id'], binding, row['seq'] if row else 0))
                step = dict(spec, state=state, token=token, binding=binding, blocked_by=blocked,
                            attempt=row['attempt'] if row else '', evidence=row['evidence'] if row else '',
                            verification=row['verification'] if row else '', operator=row['operator'] if row else '',
                            recorded=row['recorded'] if row else '', source=row['source'] if row else '')
                target['steps'].append(step)
                views[spec['id']] = step
                view['total'] += 1
                view['verified'] += int(state == 'verified')
                view['skipped'] += int(state == 'skipped')
            target['identity_confirmed'] = view['environment_channels'] or bool(dut.get('hardware_id'))
            target['ready'] = bool(target['identity_confirmed'] and all(
                step['state'] in ('verified', 'skipped') for step in target['steps']))
            sn = dut['hardware_id'].casefold()
            target['onu_receipt_available'] = bool(sn and identifiers.count(sn) == 1)
            view['duts'].append(target)
        view['ready'] = bool(view['duts']) and not dirty and all(dut['ready'] for dut in view['duts'])
        return view

    def snapshot(self):
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self._snapshot(db)

    def require_ready(self, *, channels=None, detailed=False):
        view = self.snapshot()
        if channels is None and not detailed:
            if not view['ready']:
                raise ValueError('请先保存配置，并完成当前 DUT 准备步骤及独立核验')
            return view
        if view['dirty']:
            raise ValueError('请先保存项目配置，再确认测试目标')
        targets = view['duts']
        if channels is not None:
            by_channel = {dut['channel']: dut for dut in targets}
            targets = []
            for number in channels:
                if number not in by_channel:
                    raise ValueError(f'CH{number:02d} 未映射到已保存的 DUT，请核对项目档案')
                targets.append(by_channel[number])
        if not targets:
            raise ValueError('请先在环境配置启用并保存测试通道' if view.get('environment_channels') else
                             '没有本次测试的 DUT，请核对已保存的目标')
        states = {'pending': '待执行', 'executed': '已执行，待独立核验', 'stale': '证据已过期',
                  'running': '执行中', 'interrupted': '执行中断', 'failed': '失败', 'stopped': '已停止'}
        for dut in targets:
            name = dut['label'] or dut['dut_id']
            if dut['channel'] is not None:
                name = f"CH{dut['channel']:02d} · {name}"
            if not dut['identity_confirmed']:
                raise ValueError(f'{name} 缺少 DUT 实物标识，请填写并保存')
            for step in dut['steps']:
                state = step['state']
                if state == 'verified' or (step['optional'] and state == 'skipped'):
                    continue
                raise ValueError(f"{name} 准备步骤「{step['label']}」{states.get(state, '待核实')}")
        return view

    def _transition(self, action, dut_id, step_id, operator, *, token=None, attempt=None, evidence=''):
        operator = _required_text(operator, '操作人', 160)
        if action != 'begin':
            evidence = _required_text(evidence, '操作记录、回读结果或证据位置', 4096)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            view = self._snapshot(db)
            dut = next((d for d in view['duts'] if d['dut_id'] == dut_id), None)
            step = next((s for s in dut['steps'] if s['id'] == step_id), None) if dut else None
            if not step:
                raise ValueError('DUT 或步骤已变化，请刷新准备计划')
            if view['dirty'] and action not in ('failed', 'stopped', 'invalidate'):
                raise ValueError('项目存在未保存配置，请保存或放弃草稿后核对准备步骤')
            if token is not None and step['token'] != token:
                raise ValueError('准备步骤或依赖证据已变化，请刷新')
            if attempt is not None and (not attempt or step['attempt'] != attempt):
                raise ValueError('回执不属于本次准备操作')
            state = step['state']
            source = step['source']
            if action in ('begin', 'manual', 'skip') and state in ('running', 'interrupted'):
                raise ValueError('本次执行尚未收尾，请先核实设备和原任务结果')
            if action in ('begin', 'manual'):
                if not dut['identity_confirmed']:
                    raise ValueError('请先填写可核对的 DUT 实物标识并保存项目')
                if step['blocked_by']:
                    raise ValueError('请先完成并核验前置步骤：' + '、'.join(step['blocked_by']))
                attempt = uuid.uuid4().hex
                new_state, executed, verification = ('running', '', '') if action == 'begin' else ('executed', evidence, '')
                source = step['mode'] if action == 'begin' else 'manual'
            elif action == 'skip':
                if not step['optional']:
                    raise ValueError('必需步骤不能跳过')
                attempt, new_state = uuid.uuid4().hex, 'skipped'
                executed, verification = evidence, ''
                source = 'manual'
            elif action == 'job':
                if step['mode'] != 'automatic' or state != 'running':
                    raise ValueError('请先开始当前自动准备步骤，再关联本次原任务')
                attempt = step['attempt']
                key = (view['project_id'], dut_id, step_id, attempt)
                first = db.execute('''SELECT recorded FROM preparation WHERE project=? AND dut=? AND step=?
                    AND attempt=? AND state='running' ORDER BY seq LIMIT 1''', key).fetchone()
                from src.services.project_preparation_jobs import preparation_job_receipt
                profile = read_project_profile(self.context.saved_root / 'Auto_power_on_off_tool/config')
                identity = next(d for d in profile['duts'] if d['dut_id'] == dut_id)
                part, receipt = preparation_job_receipt(self.context, identity, step_id, evidence,
                                                       datetime.fromisoformat(first[0]).timestamp())
                try:
                    db.execute('INSERT INTO preparation_jobs VALUES(?,?,?,?,?,?,?)', (*key, part, evidence, receipt))
                except sqlite3.IntegrityError as exc:
                    raise ValueError('本 DUT 已使用该任务或本次步骤已有对应回执') from exc
                receipts = list(db.execute('''SELECT receipt FROM preparation_jobs WHERE project=? AND dut=?
                    AND step=? AND attempt=? ORDER BY part''', key))
                new_state = 'running' if step_id == 'wifi' and len(receipts) < 2 else 'executed'
                executed, verification, source = '\n'.join(r[0] for r in receipts), '', 'job'
            elif action == 'invalidate':
                attempt, new_state = step['attempt'], 'stale'
                executed, verification = step['evidence'], evidence
            elif action in ('verify', 'reject'):
                if state != 'executed' or step['blocked_by']:
                    raise ValueError('请先完成本次执行，再记录独立核验结果')
                new_state = 'verified' if action == 'verify' else 'failed'
                executed, verification = step['evidence'], evidence
            else:
                if action == 'executed' and step['mode'] == 'automatic':
                    raise ValueError('自动步骤须关联原任务回执；现场已有状态请单独记录人工依据')
                if state != 'running' and not (state == 'interrupted' and action in ('failed', 'stopped')):
                    raise ValueError('该执行回执已过期，请重新核对 DUT 和当前步骤')
                new_state = action
                executed, verification = evidence, ''
            self._append(db, dut_id, step_id, step['binding'], attempt, new_state, executed, verification, operator, source)
        message = f'[DUT准备] {view["project_id"]} / {dut_id} / {step["label"]} · {new_state} · {operator}'
        if self.emit_event:
            self.emit_event(self.context, message, dut_id=dut_id, step=step_id, channel=dut['channel'],
                            level={'failed': 'ERROR', 'stale': 'WARN'}.get(new_state, 'INFO'),
                            job_id=evidence if action == 'job' else '')
        else:
            self.emit(message)
        return attempt

    def begin(self, dut_id, step_id, token, operator):
        return self._transition('begin', dut_id, step_id, operator, token=_required_text(token, '步骤凭据', 128))

    def record_manual(self, dut_id, step_id, token, evidence, operator):
        return self._transition('manual', dut_id, step_id, operator, token=_required_text(token, '步骤凭据', 128),
                                evidence=evidence)

    def link_job(self, dut_id, step_id, token, job_id, operator):
        return self._transition('job', dut_id, step_id, operator, token=_required_text(token, '步骤凭据', 128),
                                evidence=_required_text(job_id, '原任务 ID', 128))

    def finish(self, dut_id, step_id, attempt, outcome, evidence, operator):
        if outcome not in ('executed', 'failed', 'stopped'):
            raise ValueError('执行回执状态无效')
        return self._transition(outcome, dut_id, step_id, operator, attempt=_required_text(attempt, '执行凭据', 128),
                                evidence=evidence)

    def verify(self, dut_id, step_id, token, attempt, passed, evidence, operator):
        if type(passed) is not bool:
            raise ValueError('请选择核验是否通过')
        return self._transition('verify' if passed else 'reject', dut_id, step_id, operator,
                                token=_required_text(token, '步骤凭据', 128),
                                attempt=_required_text(attempt, '执行凭据', 128), evidence=evidence)

    def skip(self, dut_id, step_id, token, reason, operator):
        return self._transition('skip', dut_id, step_id, operator, token=_required_text(token, '步骤凭据', 128),
                                evidence=reason)

    def invalidate(self, dut_id, step_id, reason, operator):
        return self._transition('invalidate', dut_id, step_id, operator, evidence=reason)

    def history(self, dut_id, step_id, *, before=None):
        with closing(self._connect()) as db:
            return tuple(dict(row) for row in db.execute('''SELECT seq,attempt,state,source,operator,evidence,
                verification,recorded FROM preparation WHERE project=? AND dut=? AND step=? AND seq<?
                ORDER BY seq DESC LIMIT 100''', (self.context.identity.project_id, dut_id, step_id,
                before if before is not None else 2**63 - 1)))

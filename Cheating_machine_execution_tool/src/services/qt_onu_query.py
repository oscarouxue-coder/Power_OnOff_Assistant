"""Local Qt profiles and read actions over the original OLT capabilities."""
from dataclasses import asdict, dataclass, replace
import time
from typing import Optional
import uuid

from line_check_assistant.onu_registration_store import OnuRegistrationStore
from src.models.capabilities import CapabilityError, CapabilitySpec, fingerprint, object_schema
from src.models.project_review import ReviewRequired
from src.models.onu_registration_models import C300CleanupCandidate, DiscoveredOnu, OLT_FAMILIES, OnuDiscoveryScope, OnuProvisionRequest
from src.services.qt_configuration_service import QtConfigurationService
from src.services.qt_onu_management import QtOnuManagement
from src.services.qt_onu_registration import BUSINESS, REGISTRATION, REGISTRATION_OPTIONS, QtOnuRegistration
from src.services.qt_onu_save import QtOnuSave


OPERATIONS = {
    'connection': ('connection', '测试连接'),
    'unregistered': ('unregistered', '查询未注册 ONU'),
    'registered': ('registered', '查询已注册 ONU'),
    'onu_type': ('templates', '查询 ONU 类型模板'),
    'dba': ('templates', '查询 DBA 模板'),
}
CONNECTION_FIELDS = ('olt_ip', 'source_ip', 'username', 'password')
DISCOVERY_FIELDS = ('shelf', 'slot', 'pon')
CLEANUP_TITLE = '查询 C300 离线清理候选'


@dataclass(frozen=True)
class OnuQueryConfirmation:
    token: str
    created: float
    binding: str
    operation: str
    arguments: dict
    scope: dict
    cleanup_plan: Optional[OnuProvisionRequest] = None
    cleanup_selection: str = ''


class QtOnuQuery:
    def __init__(self, execution):
        self.execution = execution
        self.service = execution.capabilities
        self.store = OnuRegistrationStore(execution.context.config_dir / 'onu_registration.ini')
        self.token = ''
        self.binding = ''
        self.pending = None
        self.latest = ''
        self.latest_request = None
        self.discovery_job = ''
        self.discovery_request = None
        self.cleanup_query = None
        self.registration = QtOnuRegistration(self)
        self.management = QtOnuManagement(self)
        self.saving = QtOnuSave(self)
        family = dict(type='string', enum=list(OLT_FAMILIES))
        token = dict(type='string', minLength=32, maxLength=32)
        session = dict(token=token)
        profile = {key: dict(type='string', maxLength=4096) for key in CONNECTION_FIELDS}
        profile.update({key: dict(type='integer', minimum=0, maximum=64) for key in DISCOVERY_FIELDS})
        profiles = {name: object_schema(profile, tuple(profile)) for name in OLT_FAMILIES}
        for name, handler, fields, risk in (
            ('show', self.show, {}, 'read'),
            ('poll', self.poll, session, 'read'),
            ('save_profile', self.save_profile, dict(session, family=family,
                profiles=object_schema(profiles, OLT_FAMILIES)), 'modify'),
            ('preview', self.preview, dict(session, action=dict(type='string', enum=list(OPERATIONS)), family=family), 'read'),
            ('prepare_cleanup', self.prepare_cleanup, dict(session, **REGISTRATION), 'read'),
            ('execute', self.execute, dict(session, confirmation=token), 'dangerous'),
            ('save_business', self.registration.save, dict(session, family=family, business=BUSINESS), 'modify'),
            ('prepare_registration', self.registration.prepare, dict(session, **REGISTRATION, **REGISTRATION_OPTIONS), 'read'),
            ('register', self.registration.execute, dict(session, confirmation=token, **REGISTRATION, **REGISTRATION_OPTIONS), 'dangerous'),
            ('save_olt', self.saving.decide, dict(session, registration_job=token, accepted=dict(type='boolean')), 'dangerous'),
            ('prepare_delete', self.management.prepare_delete, dict(session, family=family, query_job=token,
                interfaces=dict(type='array', minItems=1, uniqueItems=True,
                                items=dict(type='string', minLength=1))), 'read'),
            ('delete', self.management.delete, dict(session, confirmation=token), 'dangerous'),
            ('cancel', self.cancel, session, 'read'),
            ('stop', self.stop, session, 'modify'),
            ('detach', self.detach, session, 'read'),
        ):
            job = name in ('execute', 'register', 'delete', 'save_olt')
            resources = ('device-business', 'olt') if name == 'save_olt' else ('device-business', 'olt', 'pon') if job else ()
            self.service.registry.register(CapabilitySpec('onu.editor.' + name, '本机 ONU 窗口',
                '通过原 ONU 本机控制面操作已保存的项目配置',
                object_schema(fields, tuple(key for key in fields if key not in REGISTRATION_OPTIONS)), handler,
                risk=risk, sources=('gui',), execution_mode='job' if job else 'sync',
                resource_requirements=resources,
                cancellation='cooperative' if job else 'none'))

    def _check(self, arguments):
        if not self.token or self.token != arguments['token']:
            raise CapabilityError('session_expired', 'ONU 窗口已失效，请重新打开')

    def _configuration(self):
        config = self.store.load()
        return dict(family=config.olt_family, profiles={
            family: {name: getattr(config, family.lower() + '_' + name)
                     for name in (*CONNECTION_FIELDS, *DISCOVERY_FIELDS)}
            for family in OLT_FAMILIES}, business=self.registration.settings(config))

    def show(self, arguments, authority):
        if not self.token:
            self.token = uuid.uuid4().hex
        self.binding = self.execution._binding()
        return dict(self.poll({'token': self.token}, authority), **self._configuration(),
                    token=self.token, project=self.execution.context.identity.name)

    def _check_binding(self, binding):
        if self.execution._binding() != binding:
            raise ReviewRequired('configuration_changed', '项目配置已变化，请重新打开 ONU 窗口核对', 'onu', 'close_button')

    def save_profile(self, arguments, authority):
        self._check(arguments)
        self.pending = self.registration.preview = None
        updates = {}
        for family, profile in arguments['profiles'].items():
            discovery = OnuDiscoveryScope(*(profile[key] for key in DISCOVERY_FIELDS))
            errors = discovery.validate()
            if errors:
                raise CapabilityError('invalid_parameters', family + '：' + '；'.join(errors))
            for key, value in profile.items():
                updates[family.lower() + '_' + key] = value.strip() if isinstance(value, str) else value
        family = arguments['family']
        active = {key: updates[family.lower() + '_' + key] for key in CONNECTION_FIELDS}
        self.discovery_request = None
        return self._save_settings(dict(updates, olt_family=family, **active))

    def _save_settings(self, updates):
        self.execution._prepare_guard()
        self._check_binding(self.binding)
        self.cleanup_query = None
        context = self.execution.context
        path = self.store.config_path
        owner = 'qt-onu-settings:' + uuid.uuid4().hex
        self.service.resources.acquire(owner, ('device-business', 'configuration'))
        uncertain = False
        try:
            original = path.read_bytes() if path.exists() else None
            updated = replace(self.store.load(), **updates)
            self._check_binding(self.binding)
            try:
                self.store.save(updated)
                self.execution.workspace.projects.save(context)
            except Exception:
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        QtConfigurationService._replace(path, original)
                except Exception:
                    uncertain = True
                    raise CapabilityError('configuration_rollback_failed', 'ONU 设置恢复失败，请本机核实') from None
                raise CapabilityError('configuration_save_failed', '保存未完成，已恢复原 ONU 设置') from None
            self.binding = self.execution._binding()
            self.execution._log('[Qt ONU] 已保存本项目的 C300/C600 设置')
            return self._configuration()
        finally:
            self.service.resources.release(owner, uncertain=uncertain)

    def preview(self, arguments, authority):
        self._check(arguments)
        self.pending = self.registration.preview = None
        self.management.pending = None
        self.cleanup_query = None
        self.execution._prepare_guard()
        self._check_binding(self.binding)
        operation, title = OPERATIONS[arguments['action']]
        data = dict(family=arguments['family'])
        if operation in ('connection', 'templates'):
            data.update(shelf=0, slot=0, pon=0)
        if operation == 'templates':
            data['kind'] = arguments['action']
        identifier = 'onu.' + operation
        self.service.validate(identifier, data, authority, check_scope=False)
        _, _, discovery, _ = self.service.onu.connection(data)
        if operation == 'registered' and discovery.is_all_olt:
            raise ReviewRequired('explicit_pon_required', '查询已注册 ONU 需要明确单个 PON', 'onu', 'pon')
        scope = self.service.onu.scope(data, operation)
        self._check_binding(self.binding)
        token = uuid.uuid4().hex
        self.pending = OnuQueryConfirmation(token, time.monotonic(), self.binding, operation, data, scope)
        target = '整台 OLT' if scope['target'] == 'OLT' else scope['target']
        details = [self.execution.context.identity.name, title, f"OLT {scope['family']} · {scope['host']}",
                   f"源 IP {scope['source_ip']}", f'结果范围：{target}']
        if operation == 'unregistered' and data['family'] == 'C300' and not discovery.is_all_olt:
            details.append('C300 先执行整机发现，再按目标 PON 筛选结果。')
        details.append('确认本次连接与查询？')
        return dict(confirmation=token, summary='\n'.join(details))

    @staticmethod
    def _check_cleanup_selection(arguments):
        if arguments['family'] != 'C300' or len(arguments['selection']) != 1:
            raise ReviewRequired('invalid_cleanup_selection', '离线清理仅支持 C300 单台注册', 'onu', 'unregistered')

    def prepare_cleanup(self, arguments, authority):
        self._check(arguments)
        self.pending = self.registration.preview = self.management.pending = self.cleanup_query = None
        self.execution._prepare_guard()
        self._check_binding(self.binding)
        self._check_cleanup_selection(arguments)
        plan, = self.registration.plans(arguments)
        data = self.registration.pon_arguments(plan.request)
        scope = self.service.onu.scope(data, 'cleanup_query')
        self._check_binding(self.binding)
        token = uuid.uuid4().hex
        self.pending = OnuQueryConfirmation(token, time.monotonic(), self.binding,
            'cleanup_query', data, scope, plan.request, fingerprint(self.registration.selection_data(arguments)))
        details = (self.execution.context.identity.name, CLEANUP_TITLE,
                   f"OLT C300 · {scope['host']} · 源 IP {scope['source_ip']}",
                   f"结果范围：{scope['target']} · 注册目标 SN {plan.request.onu.serial_number}",
                   '确认本次只读查询？')
        return dict(confirmation=token, summary='\n'.join(details))

    def _start_cleanup_query(self, pending, authority):
        scope = pending.scope
        _, connection, _, _ = self.service.onu.connection(pending.arguments)

        def recheck():
            self._check_binding(pending.binding)
            if self.service.onu.scope(pending.arguments, pending.operation) != scope:
                raise ReviewRequired('olt_configuration_changed', 'OLT 或 PON 已变化，未查询离线候选', 'onu', 'pon')
            self.service.scopes.require(authority, scope)

        def runner(context):
            context.stop.checkpoint()
            registration = self.service.onu.registration_factory(logger=lambda line: context.event('onu', line))
            result = registration.query_c300_cleanup_candidates(connection, pending.cleanup_plan, context.stop.event)
            state = 'stopped' if context.stop.is_set() else 'succeeded' if result.ok else 'failed'
            pon = scope['target'].casefold()
            prefix = pon.replace('gpon-olt_', 'gpon-onu_', 1)
            candidates = [asdict(row) for row in result.cleanup_candidates if state == 'succeeded'
                          and row.serial_number.strip() and row.pon_interface.casefold() == pon
                          and row.onu_interface.casefold() == f'{prefix}:{row.onu_id}']
            message = result.message
            if state == 'succeeded' and len(candidates) < len(result.cleanup_candidates):
                message += f' · 可确认身份的候选 {len(candidates)} 台'
            return dict(ok=state == 'succeeded', state=state, message=message, cleanup_candidates=candidates)

        return self.service.jobs.start('onu.cleanup_query', dict(scope=scope, selection=pending.cleanup_selection),
            authority, ('device-business', 'olt:' + scope['host'], 'pon:' + scope['host'] + ':' + scope['target']),
            runner, recheck=recheck, observational=True)

    def selected_cleanup(self, arguments):
        self._check_cleanup_selection(arguments)
        reference = arguments['cleanup']
        query = self.cleanup_query
        if (not query or reference['query_job'] != query[0] or query[1].binding != self.binding
                or query[1].cleanup_selection != fingerprint(self.registration.selection_data(arguments))):
            raise ReviewRequired('cleanup_query_expired', '注册目标或配置已变化，请重新查询离线候选', 'onu', 'unregistered')
        status = self.execution.jobs[query[0]]['status'] or {}
        if status.get('state') == 'succeeded':
            matches = [row for row in (status.get('result') or {}).get('cleanup_candidates', ())
                       if row['onu_interface'] == reference['interface']]
            if len(matches) == 1:
                return C300CleanupCandidate(**matches[0])
        raise CapabilityError('onu_identity_changed', '所选接口未在本次离线候选中唯一命中')

    def execute(self, arguments, authority):
        self._check(arguments)
        pending, self.pending = self.pending, None
        if not pending or pending.token != arguments['confirmation'] or time.monotonic() - pending.created > 120:
            raise ReviewRequired('confirmation_expired', 'ONU 查询确认已失效，请重新核对', 'onu', 'pon')
        self.execution._prepare_guard()
        self._check_binding(pending.binding)
        job_authority = replace(authority, principal=authority.principal + ':onu:' + pending.token,
                                operation_id=pending.token)
        self.execution._admission_binding = pending.binding
        try:
            scope = self.service.onu.scope(pending.arguments, pending.operation)
            if scope != pending.scope or scope['access'] != 'read':
                raise ReviewRequired('olt_configuration_changed', 'OLT 或 PON 已变化，未连接设备', 'onu', 'pon')
            self.service.scopes.grant(job_authority.principal, scope, authority.principal)
            try:
                if pending.cleanup_plan is not None:
                    result = self._start_cleanup_query(pending, job_authority)
                else:
                    result = self.service.execute('onu.' + pending.operation, pending.arguments, job_authority)
            finally:
                try:
                    self.service.scopes.revoke(job_authority.principal, scope['id'])
                except Exception:
                    self.execution._log('[Qt ONU] 任务专用授权回收记录失败，后续请求使用独立身份', 'WARN')
        finally:
            self.execution._admission_binding = None
        job = result['job_id']
        action = pending.arguments.get('kind', pending.operation)
        if pending.operation == 'unregistered':
            self.discovery_job, self.discovery_request = job, pending
        elif pending.operation == 'registered':
            self.management.job, self.management.request = job, pending
        elif pending.operation == 'cleanup_query':
            self.cleanup_query = (job, pending)
        title = CLEANUP_TITLE if pending.operation == 'cleanup_query' else OPERATIONS[action][1]
        return self._record_job(job, job_authority, pending, title, arguments['token'])

    def record_registration(self, job, authority, pending, token, reviewer):
        self.management.clear()
        request = OnuQueryConfirmation(pending.token, time.monotonic(), pending.binding, 'register',
                                      dict(family=pending.family), pending.scopes[0])
        self._track_job(job, authority, request, '注册 ONU')
        self.saving.arm(job, authority, pending, reviewer)
        return self.poll({'token': token}, authority)

    def _record_job(self, job, authority, pending, title, token):
        self._track_job(job, authority, pending, title)
        return self.poll({'token': token}, authority)

    def _track_job(self, job, authority, pending, title):
        self.execution.jobs[job] = dict(authority=authority, after=0, status=None, channels={}, progress=None,
                                        title=title, result_view='查看 ONU 窗口')
        self.latest = self.execution.latest = job
        self.latest_request = pending
        self.execution.parameters = ()
        self.execution._log('[Qt ONU] 本机确认后提交任务：' + title, job_id=job)

    def _discovery(self):
        request = self.discovery_request
        status = self.execution.jobs.get(self.discovery_job, {}).get('status') or {}
        if not request or request.binding != self.binding or status.get('state') != 'succeeded':
            return '', '', []
        return self.discovery_job, request.arguments['family'], (status.get('result') or {}).get('onus', [])

    def discovery_rows(self, identifier, family):
        job, current_family, rows = self._discovery()
        if job != identifier or current_family != family:
            raise ReviewRequired('discovery_expired', '请在当前配置下重新发现未注册 ONU', 'onu', 'unregistered')
        return tuple(DiscoveredOnu(**row) for row in rows)

    def poll(self, arguments, authority):
        self._check(arguments)
        self.execution.poll()
        status = self.execution.jobs.get(self.latest, {}).get('status') or {}
        result = status.get('result') or {}
        pending = self.latest_request
        data = pending.arguments if pending else {}
        current = bool(pending and self.binding == pending.binding)
        discovery, discovery_family, discovered = self._discovery()
        registered_job, registered_family, registered_rows = self.management.snapshot()
        message = (result.get('message') or result.get('error') or '') if current else ''
        notice_job, notice = self.saving.notice
        if current and status.get('state') == 'succeeded':
            if notice_job == self.latest:
                message = ' · '.join(filter(None, (message, notice)))
            elif pending.operation == 'register' and result.get('save_policy') == '':
                message = ' · '.join(filter(None, (message, '本次未选择保存 OLT 启动配置')))
        active = not self.execution.idle
        return dict(job=self.latest, state=status.get('state', 'idle'), active=active,
            stoppable=bool(self.latest and self.latest == self.execution.latest and active),
            family=data.get('family', ''), action=data.get('kind', pending.operation if pending else ''),
            target=pending.scope['target'] if pending else '', stale=bool(pending and not current),
            message=message, save_confirmation=self.saving.confirmation(), save_notice=notice if notice_job == self.latest else '',
            onus=result.get('onus', []) if current else [], templates=result.get('templates', []) if current else [],
            registered=result.get('registered_onus', []) if current else [],
            registered_job=registered_job, registered_family=registered_family, registered_rows=registered_rows,
            deleted=result.get('deleted', []) if current else [],
            cleanup_candidates=result.get('cleanup_candidates', []) if current else [],
            discovery=discovery, discovery_family=discovery_family, discovered=discovered)

    def cancel(self, arguments, authority):
        self._check(arguments)
        self.pending = self.registration.preview = None
        self.management.pending = None
        self.execution._log('[Qt ONU] 本机取消确认，未启动任务')

    def stop(self, arguments, authority):
        self._check(arguments)
        self.saving.cancel('操作员已停止')
        if self.latest and self.latest == self.execution.latest and not self.execution.idle:
            self.execution.stop(self.latest)
        return self.poll(arguments, authority)

    def detach(self, arguments, authority):
        self._check(arguments)
        self.shutdown()

    def shutdown(self):
        self.saving.cancel('ONU 窗口或工作区已关闭')
        self.pending = self.registration.preview = self.discovery_request = None
        self.cleanup_query = None
        self.management.clear()
        self.token = self.binding = ''

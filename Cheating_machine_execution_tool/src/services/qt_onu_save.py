"""Continue a confirmed registration with the original whole-OLT save service."""
from dataclasses import dataclass, replace

from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_jobs import TERMINAL


@dataclass(frozen=True)
class OnuSaveAttempt:
    registration_job: str
    binding: str
    scope: dict
    authority: CapabilityAuthority
    reviewer: str
    policy: str


class QtOnuSave:
    def __init__(self, query):
        self.query = query
        self.execution = query.execution
        self.service = query.service
        self.pending = None
        self.notice = ('', '')

    def arm(self, job, authority, registration, reviewer):
        self.notice = ('', '')
        self.pending = (OnuSaveAttempt(job, registration.binding, registration.save_scope,
                                       authority, reviewer, registration.save_policy)
                        if registration.save_scope else None)

    def cancel(self, reason):
        attempt, self.pending = self.pending, None
        if attempt:
            self._skip(attempt, reason)

    def _skip(self, attempt, reason):
        message = '未启动 OLT 保存 · ' + reason
        self.notice = (attempt.registration_job, message)
        self.execution._log('[Qt ONU] ' + message, job_id=attempt.registration_job)

    def _status(self, attempt):
        return self.execution.jobs[attempt.registration_job]['status'] or {}

    def _ready(self, attempt):
        status = self._status(attempt)
        return (self.execution.idle and self.query.latest == self.execution.latest == attempt.registration_job
                and status.get('state') == 'succeeded' and bool((status.get('result') or {}).get('save_ready')))

    def confirmation(self):
        attempt = self.pending
        if not attempt or attempt.policy != 'prompt' or not self._ready(attempt):
            return None
        scope = attempt.scope
        return dict(registration_job=attempt.registration_job, family=scope['family'],
                    summary='\n'.join((self.execution.context.identity.name,
                        f"OLT {scope['family']} · {scope['host']} · 源 IP {scope['source_ip']}",
                        '注册验证成功。是否执行 write，将整台 OLT 的当前运行配置写入启动配置？')))

    def advance(self):
        """Run on the existing workspace worker after the registration thread releases its lease."""
        attempt = self.pending
        if not attempt or not self.execution.idle:
            return
        if self.query.latest != attempt.registration_job or self.execution.latest != attempt.registration_job:
            self.cancel('已有后续任务')
            return
        state = self._status(attempt).get('state')
        if state not in TERMINAL:
            return
        if not self._ready(attempt):
            self.cancel('注册未完成完整验证或已停止')
            return
        if attempt.policy == 'automatic':
            self._submit(attempt)

    def decide(self, arguments, authority):
        self.query._check(arguments)
        authority.check((), 'dangerous')
        attempt = self.pending
        if (not attempt or attempt.policy != 'prompt' or arguments['registration_job'] != attempt.registration_job
                or authority.session_id != attempt.authority.session_id or authority.principal != attempt.reviewer
                or not self._ready(attempt)):
            raise CapabilityError('confirmation_expired', 'OLT 保存确认已失效')
        if arguments['accepted']:
            self._submit(attempt)
        else:
            self.cancel('操作员选择暂不保存')
        return self.query.poll(arguments, authority)

    def _submit(self, attempt):
        self.pending = None
        scope, operator = attempt.scope, attempt.authority
        family = scope['family']
        values = dict(family=family, shelf=0, slot=0, pon=0)
        try:
            self.execution._prepare_guard()
            if self.execution.other_jobs_active():
                raise CapabilityError('resource_busy', '其他项目正在处理设备任务')
            self.query._check_binding(attempt.binding)
            self.execution._admission_binding = attempt.binding
            try:
                _, connection, _, _ = self.service.onu.connection(values)
                self.service.scopes.grant(operator.principal, scope, attempt.reviewer)
                try:
                    def recheck():
                        self.query._check_binding(attempt.binding)
                        if self.service.onu.scope(values, 'save') != scope:
                            raise CapabilityError('olt_configuration_changed', 'OLT 连接已变化')
                        self.service.scopes.require(operator, scope)

                    def runner(context):
                        registration = self.service.onu.registration_factory(logger=lambda line: context.event('onu', line))
                        context.stop.checkpoint()
                        context.event('onu', '调用原独立保存服务，整台 OLT 启动配置', dispatched=True)
                        result = registration.save_configuration(family, connection, context.stop.event)
                        verified = result.ok and not result.outcome_uncertain
                        return dict(ok=verified, state='succeeded' if verified else 'unknown',
                                    message=result.message, registration_job=attempt.registration_job)

                    started = self.service.jobs.start('onu.save',
                        dict(registration_job=attempt.registration_job, scope=scope), operator,
                        ('device-business', 'olt:' + scope['host']), runner, recheck=recheck)
                finally:
                    try:
                        self.service.scopes.revoke(operator.principal, scope['id'])
                    except Exception:
                        self.execution._log('[Qt ONU] 保存任务专用授权回收记录失败', 'WARN')
            finally:
                self.execution._admission_binding = None
        except Exception as error:
            reason = str(error) if isinstance(error, CapabilityError) else '任务准入失败（' + type(error).__name__ + '）'
            self._skip(attempt, reason)
            return
        request = replace(self.query.latest_request, operation='save', arguments=values, scope=scope)
        self.query._track_job(started['job_id'], operator, request, '保存 OLT 启动配置')

"""Registered ONU deletion bound to the selected query result and local approval."""
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING
import uuid

from src.models.capabilities import CapabilityError
from src.models.onu_registration_models import RegisteredOnu
from src.services.onu_batch_delete_service import OnuBatchDeleteService

if TYPE_CHECKING:
    from src.services.qt_onu_query import OnuQueryConfirmation


@dataclass(frozen=True)
class DeleteConfirmation:
    token: str
    query_job: str
    request: 'OnuQueryConfirmation'
    scope: dict
    candidates: tuple[RegisteredOnu, ...]


class QtOnuManagement:
    def __init__(self, query):
        self.query = query
        self.execution = query.execution
        self.service = query.service
        self.job = ''
        self.request = None
        self.pending = None

    def clear(self):
        self.job = ''
        self.request = self.pending = None

    def snapshot(self):
        request = self.request
        state = self.execution.jobs.get(self.job, {}).get('status') or {}
        if not request or request.binding != self.query.binding or state.get('state') != 'succeeded':
            return '', '', []
        return self.job, request.arguments['family'], (state.get('result') or {}).get('registered_onus', [])

    def prepare_delete(self, arguments, authority):
        self.query._check(arguments)
        self.pending = self.query.pending = self.query.registration.preview = None
        self.execution._prepare_guard()
        self.query._check_binding(self.query.binding)
        job, family, rows = self.snapshot()
        if not job or job != arguments['query_job'] or family != arguments['family']:
            raise CapabilityError('registered_query_expired', '请重新查询当前 PON 的已注册 ONU')
        candidates = []
        for interface in arguments['interfaces']:
            matches = [row for row in rows if row['onu_interface'] == interface]
            if len(matches) != 1:
                raise CapabilityError('onu_identity_changed', '选择的接口不属于本次查询，或接口重复')
            candidates.append(RegisteredOnu(**matches[0]))
        request = self.request
        scope = self.service.onu.scope(request.arguments, 'delete')
        if scope['target'] != request.scope['target'] or scope['connection_revision'] != request.scope['connection_revision']:
            raise CapabilityError('olt_configuration_changed', '本次查询的 OLT 或 PON 已变化')
        error = OnuBatchDeleteService.validate_targets(family, scope['target'], candidates)
        if error:
            raise CapabilityError('invalid_delete_selection', error)
        token = uuid.uuid4().hex
        self.pending = DeleteConfirmation(token, job, request, scope, tuple(candidates))
        summary = f"{self.execution.context.identity.name}\n{family} · {scope['host']} · {scope['target']}\n源 IP {scope['source_ip']}"
        return dict(confirmation=token, summary=summary, targets=[candidate.display_text for candidate in candidates])

    def delete(self, arguments, authority):
        self.query._check(arguments)
        pending, self.pending = self.pending, None
        if not pending or arguments['confirmation'] != pending.token or pending.query_job != self.job:
            raise CapabilityError('confirmation_expired', '删除确认已失效，请重新选择并确认')
        self.execution._prepare_guard()
        request = pending.request
        self.query._check_binding(request.binding)
        authority.check((), 'dangerous')
        operator = replace(authority, principal=authority.principal + ':onu:' + pending.token,
                           operation_id=pending.token)
        scope = pending.scope
        resources = ['device-business', 'olt:' + scope['host'], 'pon:' + scope['host'] + ':' + scope['target']]

        def recheck():
            self.query._check_binding(request.binding)
            if self.service.onu.scope(request.arguments, 'delete') != scope:
                raise CapabilityError('olt_configuration_changed', 'OLT 或 PON 已变化，未执行删除')
            self.service.scopes.require(operator, scope)

        def runner(context):
            logger = lambda line: context.event('onu', line)
            registration = self.service.onu.registration_factory(logger=logger)
            deletion = self.service.onu.delete_factory(logger=logger, registration_service=registration)
            context.stop.checkpoint()
            context.event('onu', '按已确认的接口和 SN 调用原批量删除服务', dispatched=True)
            result = deletion.delete(scope['family'], connection, scope['target'], pending.candidates, context.stop.event)
            uncertain = any(
                item.operation.outcome_uncertain if item.operation is not None else
                item.status == 'failed' and bool(item.candidate.serial_number.strip())
                for item in result.items
            )
            state = ('unknown' if uncertain else 'succeeded' if result.ok else
                     'stopped' if context.stop.is_set() else 'failed')
            return dict(ok=result.ok, state=state, message=result.message, deleted=[
                dict(interface=item.candidate.onu_interface, sn=item.candidate.serial_number,
                     status=item.status, message=item.message) for item in result.items])

        self.execution._admission_binding = request.binding
        try:
            _, connection, _, _ = self.service.onu.connection(request.arguments)
            self.service.scopes.grant(operator.principal, scope, authority.principal)
            try:
                result = self.service.jobs.start('onu.delete',
                    dict(query_job=pending.query_job, scope=scope, targets=[asdict(row) for row in pending.candidates]),
                    operator, resources, runner, recheck=recheck)
            finally:
                try:
                    self.service.scopes.revoke(operator.principal, scope['id'])
                except Exception:
                    self.execution._log('[Qt ONU] 删除任务专用授权回收记录失败', 'WARN')
        finally:
            self.execution._admission_binding = None
        self.clear()
        self.query.discovery_request = None
        record = replace(request, token=pending.token, operation='delete', scope=scope)
        return self.query._record_job(result['job_id'], operator, record, '删除已注册 ONU', arguments['token'])

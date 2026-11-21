"""Qt registration control over the original target allocation and OLT services."""
from dataclasses import asdict, dataclass, replace
import re
from typing import Optional
import uuid

from src.core.zte_c600_onu import parse_service_mappings
from src.models.capabilities import CapabilityError, fingerprint, object_schema
from src.models.onu_registration_models import C300CleanupCandidate, OnuProvisionRequest
from src.services.onu_batch_registration_service import build_batch_requests
from src.services.onu_command_edit_service import OnuCommandEditService


COMMON_FIELDS = ('onu_id', 'onu_type', 'tcont_id', 'tcont_profile', 'services')
BUSINESS_FIELDS = {
    'C300': COMMON_FIELDS,
    'C600': COMMON_FIELDS + ('real_speed', 'gemport_id', 'vport_id', 'sn_bind_both'),
}
TEXT = dict(type='string', maxLength=256)
NUMBER = dict(type='integer', minimum=1)
TOKEN = dict(type='string', minLength=32, maxLength=32)
FAMILY = dict(type='string', enum=list(BUSINESS_FIELDS))
BUSINESS = object_schema({
    'onu_id': NUMBER, 'onu_type': TEXT, 'tcont_id': NUMBER, 'tcont_profile': TEXT,
    'services': dict(type='string', maxLength=32768),
    'real_speed': dict(type='string', enum=['auto', 'gpon', 'xgpon', 'xgspon']),
    'gemport_id': NUMBER, 'vport_id': NUMBER, 'sn_bind_both': dict(type='boolean'),
}, COMMON_FIELDS)
SELECTION = dict(type='array', minItems=1, items=object_schema(
    {'sn': TEXT, 'pon': TEXT, 'id': NUMBER}, ('sn', 'pon')))
REGISTRATION = dict(family=FAMILY, discovery=TOKEN, selection=SELECTION, business=BUSINESS)
REGISTRATION_OPTIONS = dict(
    write_after_success=dict(type='boolean'),
    cleanup=object_schema({'query_job': TOKEN, 'interface': TEXT}, ('query_job', 'interface')),
)


@dataclass(frozen=True)
class RegistrationPreview:
    token: str
    binding: str
    discovery: str
    selection: str
    family: str
    scopes: tuple
    plans: tuple
    save_policy: str
    save_scope: dict
    cleanup_candidate: Optional[C300CleanupCandidate] = None


class QtOnuRegistration:
    def __init__(self, query):
        self.query = query
        self.execution = query.execution
        self.service = query.service
        self.preview = None

    @staticmethod
    def settings(config):
        return {family: {key: getattr(config, family.lower() + '_' + key) for key in fields}
                for family, fields in BUSINESS_FIELDS.items()}

    def _business(self, arguments):
        family = arguments['family']
        business = arguments['business']
        if set(business) != set(BUSINESS_FIELDS[family]):
            raise CapabilityError('invalid_parameters', '业务参数与当前 OLT 型号不匹配')
        return business

    def save(self, arguments, authority):
        self.query._check(arguments)
        self.preview = self.query.pending = None
        family = arguments['family']
        values = self._business(arguments)
        updates = {family.lower() + '_' + key: value for key, value in values.items()}
        previous_binding = self.query.binding
        payload = self.query._save_settings(updates)
        if self.query.discovery_request and self.query.discovery_request.binding == previous_binding:
            self.query.discovery_request = replace(self.query.discovery_request, binding=self.query.binding)
        return payload['business']

    @staticmethod
    def selection_data(arguments):
        return {key: arguments[key] for key in REGISTRATION}

    def _data(self, arguments):
        return dict(self.selection_data(arguments), write_after_success=arguments.get('write_after_success', False),
                    cleanup=arguments.get('cleanup'))

    @staticmethod
    def pon_arguments(request):
        family = request.family
        prefix = 'gpon-olt_' if family == 'C300' else 'gpon_olt-'
        pon = request.onu.pon_interface.casefold()
        parts = re.fullmatch(re.escape(prefix) + r'(\d+)/(\d+)/(\d+)', pon)
        if parts is None:
            raise CapabilityError('invalid_pon', '发现结果缺少有效的 PON 接口')
        shelf, slot, port = map(int, parts.groups())
        return dict(family=family, shelf=shelf, slot=slot, pon=port)

    def _scopes(self, plans):
        scopes = {}
        for plan in plans:
            scope = self.service.onu.scope(self.pon_arguments(plan.request), 'register')
            scopes[scope['id']] = scope
        return tuple(scopes.values())

    def plans(self, arguments):
        family = arguments['family']
        business = self._business(arguments)
        rows = self.query.discovery_rows(arguments['discovery'], family)
        targets, ids = [], {}
        for item in arguments['selection']:
            matches = [row for row in rows if row.pon_interface == item['pon'] and row.serial_number == item['sn']]
            if len(matches) != 1:
                raise CapabilityError('onu_identity_changed', '目标已变化，请重新发现 ONU')
            target = matches[0]
            targets.append(target)
            if 'id' in item:
                ids[target] = str(item['id'])
        options = dict(business, onu_type=business['onu_type'].split('（', 1)[0].strip(),
                       tcont_profile=business['tcont_profile'].split('（', 1)[0].strip())
        try:
            options['services'] = tuple(parse_service_mappings(business['services'], allow_translation=family == 'C600'))
            base = OnuProvisionRequest(family=family, onu=targets[0], **options)
            requests = build_batch_requests(targets, base, ids)
            editor = OnuCommandEditService()
            return tuple(editor.build_default(request) for request in requests)
        except ValueError as error:
            raise CapabilityError('invalid_onu_plan', str(error)) from None

    def prepare(self, arguments, authority):
        self.query._check(arguments)
        self.preview = self.query.pending = None
        self.execution._prepare_guard()
        self.query._check_binding(self.query.binding)
        family = arguments['family']
        write = arguments.get('write_after_success', False)
        if write and family != 'C600':
            raise CapabilityError('invalid_parameters', 'C300 仅在注册成功后单独确认是否保存')
        plans = self.plans(arguments)
        scopes = self._scopes(plans)
        cleanup = self.query.selected_cleanup(arguments) if arguments.get('cleanup') else None
        save_policy = 'prompt' if family == 'C300' else 'automatic' if write else ''
        save_scope = self.service.onu.scope(dict(family=family, shelf=0, slot=0, pon=0), 'save') if save_policy else {}
        self.query._check_binding(self.query.binding)
        token = uuid.uuid4().hex
        self.preview = RegistrationPreview(token, self.query.binding, arguments['discovery'],
            fingerprint(self._data(arguments)), family, scopes, plans, save_policy, save_scope, cleanup)
        summary = [self.execution.context.identity.name, f"OLT {family} · {scopes[0]['host']}",
                   f"源 IP {scopes[0]['source_ip']}"]
        sections = []
        for plan in plans:
            target = plan.request
            header = f'{target.onu.serial_number} · {target.onu.pon_interface} · ONU ID {target.onu_id}'
            summary.append(header)
            sections.append(header + '\n' + '\n'.join(plan.commands))
        policy_note = {
            'prompt': '完整验证成功后，另行确认是否保存整台 OLT 的启动配置。',
            'automatic': '完整验证成功后，将在独立会话执行 write，保存整台 OLT 的启动配置。',
            '': '本次未选择保存 OLT 启动配置。',
        }[save_policy]
        if cleanup is not None:
            note = '若注册配置遇到 CLI 错误，复核同 PON 离线状态和 SN 后，仅删除以下候选并重试一次：\n'
            summary.append(note + cleanup.display_text)
            sections.append(note + cleanup.display_text)
        summary.extend((policy_note, '确认修改以上 ONU 的运行配置？'))
        sections.append(policy_note)
        return dict(confirmation=token, summary='\n'.join(summary), commands='\n\n'.join(sections))

    def execute(self, arguments, authority):
        self.query._check(arguments)
        pending, self.preview = self.preview, None
        if (not pending or arguments['confirmation'] != pending.token
                or fingerprint(self._data(arguments)) != pending.selection):
            raise CapabilityError('confirmation_expired', '目标或配置已变化，请重新生成命令预览')
        self.execution._prepare_guard()
        self.query._check_binding(pending.binding)
        self.query.discovery_rows(pending.discovery, pending.family)
        if pending.cleanup_candidate is not None and self.query.selected_cleanup(arguments) != pending.cleanup_candidate:
            raise CapabilityError('confirmation_expired', '离线清理候选已变化，请重新查询')
        authority.check((), 'dangerous')
        operator = replace(authority, principal=authority.principal + ':onu:' + pending.token,
                           operation_id=pending.token)
        scopes = pending.scopes
        resources = ['device-business', 'olt:' + scopes[0]['host'],
                     *('pon:' + scope['host'] + ':' + scope['target'] for scope in scopes)]

        def recheck():
            self.query._check_binding(pending.binding)
            if self._scopes(pending.plans) != scopes:
                raise CapabilityError('olt_configuration_changed', 'OLT 或 PON 发生变化，未执行注册')
            for scope in scopes:
                self.service.scopes.require(operator, scope)

        def runner(context):
            registration = self.service.onu.registration_factory(logger=lambda line: context.event('onu', line))
            context.stop.checkpoint()
            context.event('onu', '调用原注册服务进行整批预检、注册和回读', dispatched=True)
            cleanup = pending.cleanup_candidate
            extra = {'c300_cleanup_candidate': cleanup} if cleanup is not None else {}
            if cleanup is not None:
                context.event('onu', '已确认失败后的离线清理候选：' + cleanup.display_text)
            result = registration.register(connection, tuple(plan.request for plan in pending.plans),
                cancel_event=context.stop.event, command_plans=pending.plans, **extra)
            # The original register result does not say which configuration
            # commands were applied before a failure or cooperative stop.
            state = 'succeeded' if result.ok and not result.outcome_uncertain else 'unknown'
            save_ready = state == 'succeeded' and not context.stop.is_set()
            if save_ready and not pending.save_policy:
                context.event('onu', '注册验证完成，操作员未选择保存 OLT 启动配置')
            return dict(ok=result.ok, message=result.message, state=state, save_ready=save_ready,
                        save_policy=pending.save_policy)

        self.execution._admission_binding = pending.binding
        granted = []
        try:
            _, connection, _, _ = self.service.onu.connection({'family': pending.family})
            for scope in scopes:
                self.service.scopes.grant(operator.principal, scope, authority.principal)
                granted.append(scope)
            data = dict(family=pending.family, scopes=scopes, save_policy=pending.save_policy,
                        plans_hash=fingerprint([asdict(plan) for plan in pending.plans]))
            if pending.cleanup_candidate is not None:
                data['cleanup'] = asdict(pending.cleanup_candidate)
            result = self.service.jobs.start('onu.register', data, operator, resources, runner, recheck=recheck)
        finally:
            self.execution._admission_binding = None
            for scope in granted:
                try:
                    self.service.scopes.revoke(operator.principal, scope['id'])
                except Exception:
                    self.execution._log('[Qt ONU] 注册任务专用授权回收记录失败', 'WARN')
        self.query.discovery_request = None
        self.query.cleanup_query = None
        return self.query.record_registration(result['job_id'], operator, pending, arguments['token'], authority.principal)

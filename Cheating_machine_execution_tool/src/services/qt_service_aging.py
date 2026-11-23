"""Local, confirmed admission of continuous monitoring through the project Job store."""
import getpass
import uuid
from src.models.capabilities import CapabilityAuthority, CapabilityError, CapabilitySpec, object_schema
from src.services.project_preparation import preparation_for


START = 'service_aging.start'


class QtServiceAging:
    def __init__(self, execution):
        self.execution = execution
        from src.services.service_aging import ServiceAging
        self.service = ServiceAging(execution.context, emit_event=execution._log)
        self.approval = None

    def register(self):
        self.execution.capabilities.registry.register(CapabilitySpec(START, '持续供电业务老化',
            '按保存的 DUT 和业务计划持续观察、记录证据并安全停止。',
            object_schema({'token': dict(type='string', minLength=32, maxLength=32)}, ['token']),
            self._execute, risk='dangerous', execution_mode='job',
            resource_requirements=('device-business',), sources=('gui',)))
        text = {'type': 'string', 'minLength': 1, 'maxLength': 1000}
        params = {key: text for key in ('job_id','dut_id','collector','kind','outcome','evidence')}
        self.execution.capabilities.registry.register(CapabilitySpec('service_aging.record', '记录本地业务检查',
            '关联本项目老化任务、DUT 和采集项，保留本机操作人及结果。', object_schema(params, params.keys()),
            self._record, risk='write', sources=('gui',)))

    def record(self, values):
        authority = CapabilityAuthority('local-operator:' + self.execution.context.identity.project_id,
            self.execution.session, uuid.uuid4().hex, (), source='gui', approved=True)
        return self.execution.capabilities.execute('service_aging.record', values, authority)

    def _record(self, args, authority):
        self.service.record(args['job_id'], args['dut_id'], args['collector'], args['outcome'],
                            args['evidence'], getpass.getuser(), kind=args['kind'])
        return {'ok': True}

    def plan(self):
        self.execution._prepare_guard()
        preparation_for(self.execution.context).require_ready()
        return self.service.prepare()

    def dispatch(self, confirmation, authority):
        self.approval = (confirmation, authority)
        try:
            return self.execution.capabilities.execute(START, {'token': confirmation.token}, authority)
        finally:
            self.approval = None

    def _execute(self, arguments, authority):
        if not self.approval or self.approval[1] != authority or self.approval[0].token != arguments['token']:
            raise CapabilityError('approval_required', '请先确认本项目的业务老化计划')
        confirmed_binding = self.approval[0].aging_binding
        plan = self.plan()
        if plan['binding'] != confirmed_binding:
            raise CapabilityError('configuration_changed', '项目或老化采集资源已变化，请重新确认')

        def recheck():
            if self.execution.workspace_close_requested() or self.plan()['binding'] != plan['binding']:
                raise CapabilityError('configuration_changed', '项目或老化采集资源已变化，请重新确认')

        return self.execution.capabilities.jobs.start(START, dict(channel_ids=list(plan['channel_ids']),
            binding=plan['binding'], revision=plan['revision']), authority, plan['resources'],
            lambda job: self.service.run(job, plan), recheck=recheck)

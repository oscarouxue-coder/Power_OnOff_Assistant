"""Local Qt command/data boundary over the original controlled business jobs.

No widgets or device commands. Only an explicit, current local confirmation can
admit a new job. Existing jobs own timing, verdicts, snapshots and safe stops.
"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import os
import json
import time
from typing import Optional
import uuid

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings, SampleUpgradeSettingsStore
from line_check_assistant.onu_registration_store import OnuRegistrationConfig, OnuRegistrationStore
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.qt_log_history import job_event_view
from src.models.workbench_presentation import LogView
from src.services.ai_evidence_context import AiEvidenceContext
from src.services.capability_jobs import TERMINAL
from src.services.pipeline_orchestrator import SUBTASK_LABELS
from src.services.qt_pipeline_serial import PipelineSerialPrestart
from src.services.qt_job_review import QtJobReview
from src.services.qt_power_resume import QtPowerResume
from src.services.qt_single_power import CAPABILITY as SINGLE_POWER, POWER_ACTIONS, QtSinglePower, SinglePowerTarget
from src.services.qt_service_aging import START as SERVICE_AGING_START, QtServiceAging


PIPELINE_TASKS = {
    'env_check': '环境线路检查',
    'serial_terminal': '串口日志',
    'legacy_power_test': '执行开关机测试',
}


@dataclass(frozen=True)
class ExecutionConfirmation:
    token: str
    project_id: str
    operation: str
    channel_ids: tuple
    summary: str
    tasks: tuple = ()
    serial_directory: str = ''
    power_target: Optional[SinglePowerTarget] = None
    aging_binding: str = ''


class QtExecutionAdapter:
    OPERATIONS = {'aging.start': ('legacy_power_test', '自动开关机挂测'),
                  SERVICE_AGING_START: ('', '全业务老化'),
                  'network.line_check': ('env_check', '环境线路检查'),
                  'pipeline.start': ('', '全流程执行')}

    def __init__(self, workspace, context, record, other_jobs_active=lambda: False, *,
                 workspace_close_requested=lambda: False, adapter_rename=None, other_power_blocked=None):
        self.workspace, self.context, self.record = workspace, context, record
        self.ai_evidence = AiEvidenceContext()
        self.ai_event_listener = None
        from src.services.qt_feishu_notifications import QtFeishuNotifications
        self.feishu_notifications = QtFeishuNotifications(self)
        self.capabilities = None
        self.service_aging = None
        self.manager = None
        self.configuration = None
        self.channel_editor = None
        self.adapter_rename = adapter_rename
        self.terminal = None
        self.dut = None
        self.upgrade = None
        self.parameter_writer = None
        self.onu = None
        self.pretest = None
        self.version_query = None
        self.push_trial = None
        self.session = uuid.uuid4().hex
        self.pending = None
        self.parameters = ()
        self.jobs = {}  # Only jobs admitted by this local control, never old GUI batches.
        self.latest = ''
        self.power_log_job = ''
        self.closed = False
        self.closing = False
        self._admission_binding = None
        self.other_jobs_active = other_jobs_active
        self.other_power_blocked = other_power_blocked or other_jobs_active
        self.workspace_close_requested = workspace_close_requested
        self.pipeline_serial = PipelineSerialPrestart()
        self.resume = QtPowerResume(self)
        self.single_power = QtSinglePower(self)
        self.job_review = QtJobReview(self)

    def _log(self, message, level='INFO', job_id='', channel=None, *, dut_id='', step=''):
        if message.startswith('[能力执行] configuration.editor.checkpoint；'):
            return
        self.record(LogView(datetime.now().strftime('%H:%M:%S'), level,
            self.context.identity.project_id, self.context.identity.name, message, job_id, channel,
            dut_id=dut_id, step=step, job_id=job_id, batch_id=self._log_run(job_id)))

    def _log_run(self, job_id):
        # These two identity fields are populated before the owner record is published.
        # A producer need not acquire the status lock held during filesystem updates.
        record = self.workspace.status.records.get(job_id) if job_id else None
        if record and record.get('project_id') == self.context.identity.project_id:
            return record.get('run_id', '')
        return ''

    def open_power_log(self, number, kind):
        from src.services.qt_power_logs import open_channel_log

        if type(number) is not int or not 1 <= number <= 16 or kind not in ('power', 'wifi'):
            raise ValueError('请选择有效的日志类型及通道')
        owner = self.power_log_job
        with self.workspace.status.lock:
            record = self.workspace.status.records.get(owner)
            root = record['_path'].parent if record and record['project_id'] == self.context.identity.project_id else None
        title = '本次 WiFi 连接日志' if kind == 'wifi' else '开关机运行日志'
        try:
            if self.closing or self.closed or self.workspace_close_requested():
                raise ValueError('项目或工作区正在收尾，未打开日志')
            if owner and root is None:
                raise ValueError('当前开关机批次缺少项目运行记录')
            path = open_channel_log(self.context, number, kind, run_root=root, session=self.resume.log_session(owner))
        except (OSError, ValueError) as error:
            message = str(error) if isinstance(error, ValueError) else '结果目录无法读取，请核对项目日志位置'
            self._log(f'[{title}] CH{number:02d} {message}', 'WARN', owner, number)
            raise ValueError(f'{self.context.identity.name} · CH{number:02d} · {message}') from error
        self._log(f'[{title}] 已打开 CH{number:02d}：{path}', job_id=owner, channel=number)
        return f'{self.context.identity.name} · CH{number:02d} · 已打开{title}'

    def validate_channel_history(self, job, number):
        if self.closing or self.closed or self.workspace_close_requested():
            raise ValueError('项目或工作区正在收尾，未读取通道历史')
        item = self.jobs.get(job)
        if job != self.power_log_job or item is None or type(number) is not int or number not in item['authority'].channels:
            raise ValueError('开关机批次或通道已变化，请重新打开通道历史')

    def _log_job_event(self, job_id, created, stage, message, *, dut_id='', channel=None, step='', level=''):
        row = job_event_view(self.context.identity.project_id, self.context.identity.name, job_id, created, stage, message)
        if stage == 'pipeline':
            message = row.message
            for index, (code, title) in enumerate(PIPELINE_TASKS.items(), 1):
                message = message.replace(SUBTASK_LABELS[code], f'{index}. {title}')
            row = replace(row, message=message)
        self.record(replace(row, level=level or row.level, step=step or stage, dut_id=dut_id,
                            channel=row.channel if channel is None else channel,
                            job_id=job_id, batch_id=self._log_run(job_id)))

    def _binding(self):
        """Bind every config byte and revision; neither credentials nor hashes enter UI."""
        from src.services.project_store import ProjectStore
        ProjectStore(self.context.source_root)._validate_paths(self.context)
        digest = hashlib.sha256(self.context.identity.revision.encode())
        for root in (self.context.config_dir, self.context.saved_root / 'Auto_power_on_off_tool/config'):
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    digest.update(path.relative_to(root).as_posix().encode())
                    digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def _snapshot(self):
        if self._admission_binding is not None and self._binding() != self._admission_binding:
            raise CapabilityError('configuration_changed', '任务准入期间配置变化，未执行')
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        from src.services.qt_channel_configuration import channel_slots
        data = self.channel_editor.snapshot() if self.channel_editor is not None else None
        channels = [ChannelConfig(**c) for c in data['channels']] if data else channel_slots(store.load())
        return dict(channels=[asdict(c) for c in channels],
            upgrade_settings=asdict(SampleUpgradeSettingsStore(self.context.config_dir / 'sample_upgrade_settings.ini').load()),
            power_serial_port=data['power_serial_port'] if data else store.load_power_serial_port(),
            device_ip=data['device_ip'] if data else next((c.device_manage_ip for c in channels if c.device_manage_ip), ''),
            serial_log_dir=str(self.terminal.log_directory() if self.terminal else self.context.root / 'logs/serial'),
            configuration_editor_open=self.editor_open,
            upgrade_editor_open=False, onu_editor_open=False)

    def _ensure_runtime(self):
        if self.capabilities is not None:
            return
        from src.core.serial_transport import SerialSessionManager
        from src.services.capability_service import CapabilityService
        self.manager = SerialSessionManager(resource_coordinator=self.workspace.resources,
            project_id=self.context.identity.project_id, project_name=self.context.identity.name)
        modules = {'devices', 'channels', 'parameters', 'onu'}
        configured = os.environ.get('LINECHECK_CAPABILITY_MODULES')
        if os.environ.get('LINECHECK_DISABLE_CAPABILITIES') != '1' and (
                configured is None or 'extensions' in {item.strip() for item in configured.split(',')}):
            modules.add('extensions')
        self.capabilities = CapabilityService(self.context.history / 'ai/business', self.manager,
            self._snapshot, admissible=lambda owner, keys: not self.closing and not self.workspace.maintenance.active,
            emit=self._log, tool_root=self.context.working_root, enabled_modules=modules,
            onu_configuration=self._onu_configuration,
            resource_coordinator=self.workspace.resources, project_context=self.context,
            status_service=self.workspace.status)
        self.capabilities.jobs.event_output = self._log_job_event
        self.capabilities.jobs.structured_event_output = self._log_job_event
        self.single_power.register()
        self.capabilities.maintenance = self.workspace.maintenance
        from src.services.qt_configuration_service import QtConfigurationService
        self.configuration = QtConfigurationService(self.workspace, self.context, self.capabilities,
            other_editor_open=lambda: bool(self.channel_editor and self.channel_editor.opened))
        from src.services.qt_channel_configuration import QtChannelConfiguration
        self.channel_editor = QtChannelConfiguration(self.workspace, self.context, self.capabilities,
            other_editor_open=lambda: self.configuration.opened, adapter_rename=self.adapter_rename)
        from src.services.qt_serial_terminal import QtSerialTerminal
        self.terminal = QtSerialTerminal(self.capabilities, self.context)
        self.capabilities.devices.gui_pipeline_serial_prestart = self.pipeline_serial.request
        self.capabilities.devices.gui_diagnostic_observer = self.observe_ai_event
        self.resume.register()
        from src.services.qt_dut_configuration import QtDutConfiguration
        self.dut = QtDutConfiguration(self)

    def read_chat_serial(self, target):
        from src.services.ai_serial_client import read_existing_serial
        if self.closing or self.closed:
            raise ValueError('项目正在关闭，本次串口读取已跳过')
        return read_existing_serial(self.manager, target.port)

    def observe_ai_event(self, message):
        self.feishu_notifications.observe(message)
        self.ai_evidence.observe(message)
        listener = self.ai_event_listener
        if listener is not None:
            listener(message)

    def instance_registry(self):
        self._ensure_runtime()
        return self.capabilities.registry

    def dut_command(self, suffix, arguments):
        self._ensure_runtime()
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, tuple(arguments.get('channel_ids', ())), source='gui', approved=True)
        identifier = 'dut.editor.' + suffix
        if suffix == 'poll':
            self.capabilities.validate(identifier, arguments, authority)
            return self.dut.poll(arguments, authority)
        return self.capabilities.execute(identifier, arguments, authority)

    def upgrade_command(self, suffix, arguments):
        self._ensure_runtime()
        if self.upgrade is None:
            from src.services.qt_firmware_upgrade import QtFirmwareUpgrade
            self.upgrade = QtFirmwareUpgrade(self)
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, (), source='gui', approved=suffix in ('execute', 'stop', 'save'))
        identifier = 'firmware.editor.' + suffix
        if suffix in ('poll', 'logs'):
            self.capabilities.validate(identifier, arguments, authority)
            return getattr(self.upgrade, suffix)(arguments, authority)
        return self.capabilities.execute(identifier, arguments, authority)

    def parameter_command(self, suffix, arguments):
        self._ensure_runtime()
        if self.parameter_writer is None:
            from src.services.qt_parameter_writer import QtParameterWriter
            self.parameter_writer = QtParameterWriter(self)
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, tuple(arguments.get('channel_ids', ())), source='gui',
            approved=suffix in ('execute', 'save', 'select_table', 'generate', 'stop'))
        identifier = 'parameters.editor.' + suffix
        if suffix in ('poll', 'logs'):
            self.capabilities.validate(identifier, arguments, authority)
            return getattr(self.parameter_writer, suffix)(arguments, authority)
        return self.capabilities.execute(identifier, arguments, authority)

    def _onu_configuration(self):
        if self._admission_binding is not None and self._binding() != self._admission_binding:
            raise CapabilityError('configuration_changed', 'ONU 任务准入期间项目配置变化，未连接设备')
        return asdict(OnuRegistrationStore(self.context.config_dir / 'onu_registration.ini').load())

    def onu_command(self, suffix, arguments):
        self._ensure_runtime()
        if self.onu is None:
            from src.services.qt_onu_query import QtOnuQuery
            self.onu = QtOnuQuery(self)
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, (), source='gui',
            approved=suffix in ('execute', 'stop', 'save_profile', 'save_business', 'register', 'delete', 'save_olt'))
        identifier = 'onu.editor.' + suffix
        if suffix == 'poll':
            self.capabilities.validate(identifier, arguments, authority)
            return self.onu.poll(arguments, authority)
        return self.capabilities.execute(identifier, arguments, authority)

    def serial_command(self, suffix, arguments):
        self._ensure_runtime()
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, (), source='gui', approved=True)
        identifier = 'serial.terminal.' + suffix
        if suffix == 'poll':
            # Validated high-frequency display reads do not create normal log spam.
            self.capabilities.validate(identifier, arguments, authority)
            return self.terminal.poll(arguments, authority)
        return self.capabilities.execute(identifier, arguments, authority)

    @property
    def editor_open(self):
        return bool(self.configuration and self.configuration.opened or self.channel_editor and self.channel_editor.opened)

    def channel_command(self, suffix, arguments):
        if suffix == 'open' and self.resume.has_waiting:
            raise CapabilityError('resource_busy', '已有等待续跑的通道，请等待或停止')
        if suffix not in ('open', 'reload', 'close', 'resources', 'preview', 'save', 'cancel',
                          'rename_preview', 'rename_confirm', 'rename_cancel'):
            raise CapabilityError('unavailable', '通道编辑操作不可用')
        self._ensure_runtime()
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, (), source='gui', approved=suffix in ('save', 'rename_confirm'))
        return self.capabilities.execute('channels.editor.' + suffix, arguments, authority)

    def configuration_command(self, suffix, arguments):
        if suffix == 'open' and self.resume.has_waiting:
            raise CapabilityError('resource_busy', '已有等待续跑的通道，请等待或停止')
        pretest = suffix.startswith('pretest_')
        version = suffix.startswith('version_')
        push = suffix.startswith('push_')
        if suffix not in ('open', 'reload', 'close', 'checkpoint', 'defaults', 'save', 'wifi_interfaces',
                          'pretest_preview', 'pretest_execute', 'pretest_cancel', 'pretest_stop',
                          'version_preview', 'version_execute', 'version_cancel',
                          'push_preview', 'push_execute', 'push_cancel'):
            raise CapabilityError('unavailable', '配置操作不可用')
        self._ensure_runtime()
        if pretest and self.pretest is None:
            from src.services.qt_pretest import QtPretest
            self.pretest = QtPretest(self)
        if version and self.version_query is None:
            from src.services.qt_version_query import QtVersionQuery
            self.version_query = QtVersionQuery(self)
        if push and self.push_trial is None:
            from src.services.qt_push_trial import QtPushTrial
            self.push_trial = QtPushTrial(self)
        if (suffix in ('close', 'reload', 'defaults', 'save') and self.pretest is not None
                and arguments['token'] == self.configuration.token):
            if suffix == 'close' and self.pretest.snapshot()[2]:
                raise CapabilityError('resource_busy', '预备测试仍在收尾，请等待后关闭配置')
            self.pretest.pending = None
        if (suffix in ('close', 'reload', 'save') and self.version_query is not None
                and arguments['token'] == self.configuration.token):
            query = self.version_query.snapshot()
            if query and query.active:
                raise CapabilityError('resource_busy', '样机版本查询仍在收尾，请等待')
            self.version_query.pending = None
        if (suffix in ('close', 'reload', 'save') and self.push_trial is not None
                and arguments['token'] == self.configuration.token):
            if self.push_trial.active:
                raise CapabilityError('resource_busy', '测试消息正在发送，请等待结果后关闭或修改配置')
            self.push_trial.pending = None
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, uuid.uuid4().hex, (), source='gui',
            approved=suffix in ('save', 'pretest_execute', 'pretest_stop', 'version_execute', 'push_execute'))
        if pretest:
            identifier = 'pretest.editor.' + suffix.removeprefix('pretest_')
        elif version:
            identifier = 'version.editor.' + suffix.removeprefix('version_')
        elif push:
            identifier = 'notifications.editor.' + suffix.removeprefix('push_')
        else:
            identifier = 'configuration.editor.' + suffix
        return self.capabilities.execute(identifier, arguments, authority)

    @property
    def idle(self):
        return self.jobs_idle and not self.resume.has_waiting

    @property
    def jobs_idle(self):
        return self.capabilities is None or self.capabilities.jobs.idle

    def has_only_power_tasks(self, *, include_continuous=False):
        if self.resume.has_waiting and self.jobs.get(self.power_log_job, {}).get('operation') != 'aging.start':
            return False
        if self.capabilities is None:
            return True
        jobs = self.capabilities.jobs
        allowed = ('aging.start', 'aging.resume', SERVICE_AGING_START) if include_continuous else ('aging.start', 'aging.resume')
        with jobs.lock:
            return all(self.jobs.get(key, {}).get('operation') in allowed
                       for key, thread in jobs.threads.items() if thread.is_alive())

    def pending_operation(self, token):
        if self.pending and self.pending[0].token == token:
            return self.pending[0].operation
        if self.resume.pending and self.resume.pending.token == token:
            return 'aging.resume'
        return None

    @property
    def ready_to_close(self):
        return (self.idle and not self.feishu_notifications.busy and
                (self.push_trial is None or not self.push_trial.active))

    @property
    def configuration_dir(self):
        # A draft edited externally must never relabel the targets of a live run.
        with self.workspace.status.lock:
            record = self.workspace.status.records.get(self.latest)
            if record is not None:
                return record['_path'].parent / 'Auto_power_on_off_tool/config'
        return self.context.config_dir

    def prepare(self, operation, tasks=(), *, detected_ports=()):
        if operation == SERVICE_AGING_START:
            self.pending = None
            self.resume.pending = None
            monitor = self.aging_monitor()
            plan = monitor.plan()
            parameters = (('目标时长', f"{plan['target_hours']} 小时"), ('DUT 数量', str(len(plan['duts']))))
            labels = '、'.join(dut['label'] for dut in plan['duts'])
            confirmation = ExecutionConfirmation(uuid.uuid4().hex, self.context.identity.project_id, operation,
                tuple(plan['channel_ids']), f"项目：{self.context.identity.name}\n持续供电业务老化 · 目标 {plan['target_hours']} 小时\nDUT：{labels}", aging_binding=plan['binding'])
            self.pending = (confirmation, self._binding(), time.monotonic(), parameters)
            self._log('[业务老化] 计划已读取，等待本机确认')
            return confirmation
        if operation == SINGLE_POWER:
            self.pending = None
            self.resume.pending = None
            if not isinstance(tasks, SinglePowerTarget):
                raise CapabilityError('invalid_target', '请先选择单次上/下电动作和电源口')
            selection, summary = self.single_power.preview(tasks, detected_ports)
            confirmation = ExecutionConfirmation(uuid.uuid4().hex, self.context.identity.project_id, operation,
                selection.numbers, summary, power_target=tasks)
            parameters = (('动作', POWER_ACTIONS[tasks.action]), ('本次电源口', tasks.port or '手动重启'))
            self.pending = (confirmation, selection.binding, time.monotonic(), parameters)
            self._log('[Qt电源] 等待本机确认单次' + POWER_ACTIONS[tasks.action])
            return confirmation
        if operation == 'aging.resume':
            self.pending = None
            if len(tasks) != 1:
                raise CapabilityError('invalid_target', '续跑须明确选择一个通道')
            token, summary = self.resume.preview(tasks[0])
            return ExecutionConfirmation(token, self.context.identity.project_id, operation, tuple(tasks), summary)
        if self.closing or self.closed or operation not in self.OPERATIONS:
            raise CapabilityError('unavailable', '当前操作不可用')
        self._prepare_guard()
        self.resume.pending = None
        data = self._snapshot()
        channels = [c for c in data['channels'] if c['enabled']]
        if not channels:
            raise CapabilityError('invalid_target', '未选择测试通道，请先配置并保存项目')
        tasks = tuple(tasks)
        if operation == 'pipeline.start':
            if not tasks or any(not isinstance(task, str) or task not in PIPELINE_TASKS for task in tasks) or len(set(tasks)) != len(tasks):
                raise CapabilityError('invalid_parameters', '请选择明确定义的全流程子任务')
            if 'serial_terminal' in tasks:
                self._ensure_runtime()
                data['serial_log_dir'] = str(self.terminal.log_directory())
        return self._prepare_pipeline(operation, data, channels, tasks)

    def _prepare_guard(self, *, own_configuration=None, resume_handoff=False):
        if self.closing or self.closed:
            raise CapabilityError('unavailable', '当前操作不可用')
        if not self.jobs_idle or (self.resume.has_waiting and not resume_handoff):
            raise CapabilityError('resource_busy', '本项目任务仍在执行或收尾，请等待')
        owns_editor = bool(own_configuration and self.configuration and self.configuration.token == own_configuration
                           and not (self.channel_editor and self.channel_editor.opened))
        if self.editor_open and not owns_editor:
            raise CapabilityError('editor_open', '请先保存或关闭本项目配置编辑器，再启动测试')
        if self.workspace.projects.dirty(self.context):
            raise CapabilityError('unsaved_configuration', '请先保存项目配置，再确认测试目标')
        if self.workspace.resources.unknown_for(self.context.identity.project_id):
            raise CapabilityError('previous_result_unknown', '本项目有结果未知的操作，请先由本机操作员核实')
        with self.workspace.status.lock:
            unowned = [r for owner, r in self.workspace.status.records.items()
                if r['project_id'] == self.context.identity.project_id and owner not in self.jobs
                and (r['state'] in ('prepared', 'queued', 'running', 'stopping')
                     or r['state'] == 'unknown' and not r.get('reconciled'))]
        if unowned:
            raise CapabilityError('previous_result_unknown', '项目有历史未核实任务，请先核实，不自动接管或恢复')

    def _pipeline_context(self, data, channels):
        from src.services.pipeline_orchestrator import PipelineContext
        from pathlib import Path
        return PipelineContext(None, [ChannelConfig(**c) for c in channels],
            SampleUpgradeSettings(**data['upgrade_settings']), OnuRegistrationConfig(),
            serial_log_dir=Path(data['serial_log_dir']),
            legacy_tool_root=self.context.working_root / 'Auto_power_on_off_tool')

    def pipeline_status(self):
        from src.services.pipeline_orchestrator import compute_all_subtask_statuses
        self._ensure_runtime()
        data = self._snapshot()
        config = self._pipeline_context(data, [row for row in data['channels'] if row['enabled']])
        return {code: asdict(value) for code, value in compute_all_subtask_statuses(config, tuple(PIPELINE_TASKS)).items()}

    def _prepare_pipeline(self, operation, data, channels, tasks):
        from src.services.pipeline_orchestrator import compute_all_subtask_statuses, execution_order_for
        code, title = self.OPERATIONS[operation]
        config = self._pipeline_context(data, channels)
        codes = tasks if operation == 'pipeline.start' else (code,)
        statuses = compute_all_subtask_statuses(config, codes)
        missing = [status for status in statuses.values() if not status.ready]
        if missing:
            detail = ['；'.join(status.missing) for status in missing]
            raise CapabilityError('configuration_incomplete', '配置未就绪：' + '；'.join(detail))
        parameters = ()
        version_note = ''
        if 'legacy_power_test' in codes:
            from src.services.legacy_power_test_service import LegacyPowerChannel, prepare_legacy_power_test_request
            request = prepare_legacy_power_test_request(config.legacy_tool_root,
                [LegacyPowerChannel(int(c['section'].rsplit('_', 1)[1]), c['network_card_ip']) for c in channels])
            from src.services.project_power_plan import check_project_power_plan
            check_project_power_plan(self.context, [ChannelConfig(**row) for row in channels], cycles=request.number_of_tests)
            parameters = (('通信方式', request.communication_method), ('测试轮次', str(request.number_of_tests)),
                ('启动等待', str(request.startup_time) + ' 秒'), ('间隔等待', str(request.interval_time) + ' 秒'),
                ('命令等待', str(request.wait_command_done) + ' 秒'))
            if operation == 'pipeline.start':
                from line_check_assistant.test_item_config_store import TestItemConfigStore
                from src.services.device_project_info_service import power_test_version_precheck_required
                try:
                    version = TestItemConfigStore(config.legacy_tool_root / 'config' / request.profile_filename).load(required=True)
                    if power_test_version_precheck_required(version.project_info):
                        version_note = '开关机前逐台核对已保存的三项版本基准。'
                    else:
                        version_note = '三项版本基准均为空，跳过开始前版本校验。'
                except (ValueError, OSError) as error:
                    raise CapabilityError('configuration_incomplete', str(error)) from None
        ids = tuple(int(c['section'].rsplit('_', 1)[1]) for c in channels)
        target_lines = ['CH%02d · %s · %s → %s · %s' % (n, c['vlan_name'],
            c['network_card_ip'], c['device_manage_ip'], c['serial_port'] or '按原VLAN映射')
            for n, c in zip(ids, channels)]
        lines = [self.context.identity.name, title]
        if operation == 'pipeline.start':
            order = execution_order_for(set(codes))
            lines.append('执行顺序：' + ' → '.join(PIPELINE_TASKS[task] for task in order))
            lines.extend(PIPELINE_TASKS[task] + ' · ' + statuses[task].summary for task in order)
            if len(order) > 1:
                lines.append('串口日志预启动和环境线路检查完成后不等待。其余子任务后若还有下一项，等待 120 秒。')
            if 'legacy_power_test' in codes:
                lines.append('开关机初始化仅断电已勾选通道。')
                lines.append(version_note)
        else:
            lines.append(statuses[code].summary)
        lines.append('；'.join(key + '=' + value for key, value in parameters))
        lines.extend(target_lines)
        lines.append('将调用原业务流程，可能改变设备供电或网卡配置。是否执行？')
        serial_directory = data['serial_log_dir'] if 'serial_terminal' in codes else ''
        confirmation = ExecutionConfirmation(uuid.uuid4().hex, self.context.identity.project_id, operation,
            ids, '\n'.join(filter(None, lines)), tasks, serial_directory)
        self.pending = (confirmation, self._binding(), time.monotonic(), parameters)
        self._log('[Qt测试] 已准备确认：' + title + '；通道=' + ','.join(map(str, ids)))
        return confirmation

    def confirm(self, token):
        resume = self.resume.pending
        if resume is not None and resume.token == token:
            authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
                self.session, token, (resume.channel,), source='gui', approved=True)
            return self.capabilities.execute('aging.qt_resume.confirm', {'token': token}, authority)
        pending, self.pending = self.pending, None
        if not pending or pending[0].token != token or time.monotonic() - pending[2] > 120:
            raise CapabilityError('confirmation_expired', '确认已失效，请重新核对目标')
        confirmation, binding, _, parameters = pending
        if self.closing or self.editor_open or not self.idle or self.workspace.projects.dirty(self.context) or self._binding() != binding:
            raise CapabilityError('configuration_changed', '确认后配置或任务状态已变化，未执行，请重新确认')
        adapters = {} if confirmation.power_target is not None or confirmation.aging_binding else self._verify_nics(confirmation.channel_ids, binding)
        self._ensure_runtime()
        if confirmation.serial_directory and str(self.terminal.log_directory()) != confirmation.serial_directory:
            raise CapabilityError('configuration_changed', '确认后串口日志目录已变化，请重新核对')
        authority = CapabilityAuthority('local-operator:' + self.context.identity.project_id,
            self.session, confirmation.token, confirmation.channel_ids, source='gui', approved=True)
        self._log('[Qt测试] 本机已确认，提交原受控入口：' + confirmation.operation)
        self._admission_binding = binding
        try:
            arguments = {'channel_ids': list(confirmation.channel_ids)}
            if confirmation.power_target is not None:
                result, adapters = self.single_power.dispatch(confirmation, authority)
            elif confirmation.aging_binding:
                result = self.aging_monitor().dispatch(confirmation, authority)
            else:
                if confirmation.operation == 'pipeline.start':
                    arguments['tasks'] = list(confirmation.tasks)
                result = self.capabilities.execute(confirmation.operation, arguments, authority)
        finally:
            self._admission_binding = None
        identifier = result['job_id']
        self.jobs[identifier] = dict(authority=authority, after=0, status=None, channels={}, progress=None,
            binding=binding, adapters=adapters, parameters=parameters, operation=confirmation.operation)
        if confirmation.power_target is not None:
            self.jobs[identifier].update(title='单次' + POWER_ACTIONS[confirmation.power_target.action], stop_available=False)
        self.latest = identifier
        if confirmation.operation == 'aging.start' or 'legacy_power_test' in confirmation.tasks:
            self.power_log_job = identifier
        self.parameters = parameters
        return identifier

    def aging_monitor(self):
        self._ensure_runtime()
        if self.service_aging is None:
            self.service_aging = QtServiceAging(self)
            self.service_aging.register()
        return self.service_aging

    def _verify_nics(self, channel_ids, binding, *, expected=None):
        # Resolve real NIC identities before original host resource admission.
        from src.core.network_adapter import read_adapter_identities
        identities = read_adapter_identities()
        aliases = {i.alias.casefold(): i.interface_guid.casefold() for i in identities if i.interface_guid}
        from line_check_assistant.network_ops import adapter_alias_from_display
        selected = [c for c in self._snapshot()['channels'] if int(c['section'].rsplit('_', 1)[1]) in channel_ids]
        targets = tuple(adapter_alias_from_display(c['adapter_alias'] or c['vlan_name']).casefold() for c in selected)
        if any(alias not in aliases for alias in targets):
            raise CapabilityError('inventory_pending', '目标网卡身份无法核实，未发送设备命令，请核对VLAN/网卡名称')
        if expected is not None and any(expected.get(alias) != aliases[alias] for alias in targets):
            raise CapabilityError('configuration_changed', '目标网卡身份与原批次不同，未提交续跑')
        for identity in identities:
            self.workspace.resources.register_adapter(identity.alias, identity.interface_guid)
        self.workspace.resources.inventory_ready = True
        if self._binding() != binding:
            raise CapabilityError('configuration_changed', '网卡核验期间配置变化，未执行')
        return {alias: aliases[alias] for alias in targets}

    def stop(self, identifier):
        if identifier not in self.jobs:
            raise CapabilityError('job_forbidden', '此任务不属于当前Qt控制面，未发送停止请求')
        identifier = self.resume.stop_target(identifier)
        item = self.jobs[identifier]
        self._log('[Qt测试] 请求原业务安全停止；等待实际终态', job_id=identifier)
        return self.capabilities.jobs.cancel(identifier, item['authority'])

    def discard_confirmation(self, token):
        self.resume.cancel(token)
        if self.pending and self.pending[0].token == token:
            self.pending = None
            self._log('[Qt测试] 本机取消确认，跳过执行，未启动设备任务')

    def poll(self):
        if self.capabilities is None:
            return
        self.pipeline_serial.drain(self.terminal)
        if self.upgrade is not None and self.idle:
            # Pinning or an early stop can end a Job before dispatch starts.
            self.upgrade.observation.disarm()
        for identifier, item in self.jobs.items():
            if item.get('drained'):
                continue
            status = self.capabilities.jobs.status(identifier, item['authority'], item['after'])
            item['status'] = status
            item['drained'] = status['state'] in TERMINAL and len(status['events']) < 200 and self.jobs_idle
            for event in status['events']:
                item['after'] = event['event_id']
                stage = event['stage']
                if stage not in ('aging', 'history'):
                    continue
                try:
                    data = json.loads(event['message'])
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue
                number = data.get('channel')
                if stage == 'history':
                    if identifier == self.power_log_job and type(number) is int and number in item['authority'].channels:
                        item.setdefault('history_events', {})[number] = item['after']
                    continue
                if type(number) is int and number in item['authority'].channels:
                    current = item['channels'].setdefault(number, {})
                    current.update({k: v for k, v in data.items() if k in ('status', 'completed', 'total', 'stage', 'detail')})
                elif number is None and type(data.get('completed')) is int and type(data.get('total')) is int:
                    item['progress'] = (data['completed'], data['total'])
        self.resume.advance()
        if self.onu is not None:
            self.onu.saving.advance()

    def present(self, project):
        self.poll()
        if self.power_log_job:
            power = self.jobs[self.power_log_job]
            events = power.get('history_events', {})
            project = replace(project, power_history_job=self.power_log_job,
                power_history_events=tuple((number, events.get(number, 0)) for number in power['authority'].channels))
        if not self.latest:
            return replace(project, can_start=project.state != 'unknown' and not self.closing)
        item = self.jobs[self.latest]
        status = item['status']
        if status is None:
            return replace(project, can_start=False)
        state = status['state']
        active = state not in TERMINAL
        mapped = {'queued': 'queued', 'running': 'running', 'stop_requested': 'stopping',
                  'succeeded': 'completed', 'failed': 'failed', 'stopped': 'stopped', 'unknown': 'unknown', 'skipped': 'stopped'}
        texts = {'queued': '等待执行', 'running': '运行中', 'stop_requested': '停止中',
                 'succeeded': '已完成', 'failed': '失败', 'stopped': '已停止', 'unknown': '结果未知', 'skipped': '未执行'}
        elapsed = max(0, int((time.time() if active else status['updated']) - status['created']))
        hours, seconds = divmod(elapsed, 3600)
        minutes, seconds = divmod(seconds, 60)
        progress = item['progress']
        percentage = (max(0, min(100, int(progress[0] * 100 / progress[1]))) if progress and progress[1] > 0 else None)
        channels = []
        for channel in project.channels:
            data = item['channels'].get(channel.number, {})
            channel_state = data.get('status', channel.state)
            if state == 'stopped' and channel_state == 'retry':
                channel_state = 'stopped'
            elif not active and channel_state == 'running':
                channel_state = 'stopped' if state == 'stopped' else 'unknown'
            detail = data.get('detail')
            stage = data.get('stage')
            channels.append(replace(channel, state=channel_state, cycle=data.get('completed'), total=data.get('total'),
                detail=detail if isinstance(detail, str) else '', stage=stage if isinstance(stage, str) else ''))
        failures = sum(c.state == 'failed' for c in channels)
        stages = {'preparing': '准备执行', 'pipeline': '原业务流程执行中', 'aging': '开关机测试',
                  'history': '记录通道事件', 'succeeded': '执行完成', 'failed': '执行失败',
                  'stopped': '安全停止完成', 'unknown': '结果待核实', 'skipped': '未执行', 'power': '单次电源控制'}
        serial_observation = ('', '')
        for kind, editor in (('upgrade', self.upgrade), ('parameter', self.parameter_writer)):
            if editor is not None and editor.latest == self.latest:
                serial = editor.observation.serial if kind == 'upgrade' else editor.serial
                batch = serial.log_id
                if batch:
                    serial_observation = (kind, batch)
                break
        pipeline_detail = ''
        pretest_run = self.pretest.snapshot() if self.pretest is not None else ('', '', False, '')
        passed = failed = None
        count_unit = ''
        if status['capability_id'] == 'pretest.start':
            result = status.get('result')
            counts = result.get('result') if isinstance(result, dict) else None
            if isinstance(counts, dict) and all(type(counts.get(key)) is int and counts[key] >= 0
                                                for key in ('passed', 'failed')):
                passed, failed = counts['passed'], counts['failed']
                count_unit = '条命令'
        state_text = texts.get(state, '结果未知')
        display_state = mapped.get(state, 'unknown')
        configuration = project.configuration
        if pretest_run[1] == 'unchecked':
            state_text, display_state = '完成（含未校验）', 'unchecked'
        if status['capability_id'] == 'pipeline.start':
            result = status['result'] or {}
            outcomes = [PIPELINE_TASKS[row['code']] + ('完成' if row['ok'] else '失败')
                        for row in result.get('items', ()) if row['code'] in PIPELINE_TASKS]
            if state == 'failed' and any(row['ok'] for row in result.get('items', ())):
                state_text = '部分失败'
            pipeline_detail = str(result.get('error') or ' · '.join(outcomes) or state_text)
        elif status['capability_id'] == SINGLE_POWER:
            result = status['result'] or {}
            item['result_view'] = result.get('message') or result.get('error') or '等待原电源服务结果'
            configuration = (('本次电源操作', item['parameters']),) + configuration
            if result.get('manual'):
                state_text = '已确认手动重启'
        if status['capability_id'] != SINGLE_POWER and self.parameters:
            section = '持续监测参数' if status['capability_id'] == SERVICE_AGING_START else '开关机参数'
            configuration += ((section, self.parameters),)
        view = replace(project, test_type=item.get('title') or self.OPERATIONS[status['capability_id']][1], state=display_state,
            state_text=state_text, elapsed=f'{hours:02d}:{minutes:02d}:{seconds:02d}',
            progress=percentage, progress_text=(f'已完成 {progress[0]} / {progress[1]} 轮' if progress else
                item.get('result_view') or ('逐台结果见DUT配置窗口' if item.get('title') else '等待原业务进度事件')),
            channels=tuple(channels), attention_count=max(failures, int(state in ('failed', 'unknown'))),
            success_count=passed, failure_count=failed, count_unit=count_unit,
            channel_text=f'已选 {len(item["authority"].channels)} 通道', active_task_count=int(active),
            channel_snapshot_label='本次任务配置快照',
            run_id=self.latest, can_start=self.idle and state != 'unknown' and not self.closing,
            can_stop=active and item.get('stop_available', True),
            configuration=configuration,
            serial_observation=serial_observation,
            pipeline_serial_run=self.pipeline_serial.last_run,
            pipeline_detail=pipeline_detail,
            pretest_run=pretest_run,
            version_query=self.version_query.snapshot() if self.version_query is not None else None,
            task_stage=stages.get(status['stage'] if active else state, '原业务执行中'))
        return self.resume.present(view)

    def begin_close(self):
        self.closing = True
        self.feishu_notifications.begin_close()
        self.job_review.pending = None
        self.pending = None
        self.resume.begin_close()
        if self.pretest is not None:
            self.pretest.pending = None
        if self.version_query is not None:
            self.version_query.pending = None
        if self.push_trial is not None:
            self.push_trial.pending = None
        if self.dut is not None:
            self.dut.pending = None
        if self.upgrade is not None:
            self.upgrade.shutdown()
        if self.parameter_writer is not None:
            self.parameter_writer.shutdown()
        if self.onu is not None:
            self.onu.shutdown()
        if self.configuration is not None:
            self.configuration.token = ''
        if self.channel_editor is not None:
            self.channel_editor.token = ''
            self.channel_editor.pending = None
        if self.capabilities is not None:
            self.capabilities.jobs.begin_close()

    def close(self):
        if not self.ready_to_close:
            raise RuntimeError('测试业务仍在安全收尾，不能释放项目')
        if self.closed:
            return
        self.feishu_notifications.finish()
        if self.terminal is not None:
            self.terminal.shutdown()
        if self.upgrade is not None:
            self.upgrade.shutdown()
        if self.parameter_writer is not None:
            self.parameter_writer.shutdown()
        if self.onu is not None:
            self.onu.shutdown()
        if self.manager is not None:
            tickets = self.manager.shutdown_all(wait=True)
            if any(ticket.error for ticket in tickets):
                raise RuntimeError('串口收尾失败，不能确认安全退出')
        if self.capabilities is not None:
            self.capabilities.jobs.close()
        self.ai_event_listener = None
        self.closed = True

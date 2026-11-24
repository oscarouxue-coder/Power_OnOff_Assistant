"""Qt operator control over the existing firmware capability and Job."""
from dataclasses import dataclass, replace
import time
import uuid

from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.project_review import ReviewRequired
from src.services.firmware_upgrade_service import (
    UPGRADE_SCHEMA, build_upgrade_requests, normalized_upgrade_arguments,
)
from src.services.firmware_upgrade_validation_service import inspect_upgrade_network
from src.services.qt_firmware_observation import FirmwareObservation
from src.services.qt_serial_observation import SERIAL_LOG_REQUEST


@dataclass(frozen=True)
class UpgradeConfirmation:
    token: str
    binding: str
    arguments: dict
    authority: object
    challenge: str
    created: float
    manual_restart: bool


class QtFirmwareUpgrade:
    """A window session can only confirm its own immutable preflight."""

    def __init__(self, execution):
        self.execution = execution
        self.capabilities = execution.capabilities
        self.token = ''
        self.pending = None
        self.latest = ''
        self.settings_binding = ''
        self.observation = FirmwareObservation(self.capabilities.upgrade_dispatch, execution._log)
        self.capabilities.upgrade_dispatch = self.observation.dispatch
        self.capabilities.upgrades.network_check = inspect_upgrade_network
        text = dict(type='string', minLength=32, maxLength=32)
        session = {'token': text}
        fields = UPGRADE_SCHEMA['properties']
        settings = dict(upgrade_mode=fields['upgrade_type'], transfer_method=fields['transfer_method'],
                        boot_entry_method=fields['boot_entry_method'], parallel_count=fields['parallel_count'],
                        restore_factory=fields['restore_factory'], firmware_path=dict(type='string', maxLength=4096),
                        username=dict(type='string', maxLength=500), password=dict(type='string', maxLength=4096))
        for name, handler, fields, required, risk in (
            ('show', self.show, {}, (), 'read'),
            ('poll', self.poll, session, ('token',), 'read'),
            ('logs', self.logs, SERIAL_LOG_REQUEST,
             ('batch', 'active'), 'read'),
            ('preview', self.preview, dict(session, upgrade=UPGRADE_SCHEMA), ('token', 'upgrade'), 'read'),
            ('execute', self.execute, dict(session, confirmation=text, manual_restart_confirmed=dict(type='boolean')),
             ('token', 'confirmation'), 'dangerous'),
            ('cancel', self.cancel, session, ('token',), 'read'),
            ('save', self.save, dict(session, settings=object_schema(settings, tuple(settings))),
             ('token', 'settings'), 'modify'),
            ('stop', self.stop, session, ('token',), 'modify'),
            ('detach', self.detach, session, ('token',), 'read'),
        ):
            self.capabilities.registry.register(CapabilitySpec(
                'firmware.editor.' + name, '样机升级窗口', '本机项目窗口控制面', object_schema(fields, required),
                handler, sources=('gui',), risk=risk,
                execution_mode='job' if name == 'execute' else 'sync',
                cancellation='safe_boundary' if name == 'execute' else 'none',
                resource_requirements=('device-business', 'channel', 'serial', 'adapter', 'power')
                if name == 'execute' else ()))

    def _check(self, arguments):
        if not self.token or arguments['token'] != self.token:
            raise CapabilityError('session_expired', '升级窗口已失效，请重新打开')

    def show(self, arguments, authority):
        if not self.token:
            self.token = uuid.uuid4().hex
        self.settings_binding = self.execution._binding()
        data = self.execution._snapshot()
        settings = data['upgrade_settings']
        defaults = {key: settings[key] for key in ('upgrade_mode', 'firmware_path', 'transfer_method',
                                                   'boot_entry_method', 'parallel_count', 'restore_factory')}
        targets = [dict(number=int(row['section'].rsplit('_', 1)[1]), vlan=row['vlan_name'],
                        adapter=row['adapter_alias'], port=row['serial_port'], host=row['device_manage_ip'])
                   for row in data['channels'] if row.get('enabled', True)]
        return dict(self.poll({'token': self.token}, authority), token=self.token,
                    project=self.execution.context.identity.name, defaults=defaults, targets=targets,
                    power=data['power_serial_port'], username=settings['username'], password=settings['password'])

    def save(self, arguments, authority):
        from src.services.qt_configuration_service import QtConfigurationService

        self._check(arguments)
        self._discard()
        self.execution._prepare_guard()
        if self.execution._binding() != self.settings_binding:
            raise ReviewRequired('configuration_changed', '项目设置已变化，请关闭后重新打开核对', 'upgrade', 'close_button')
        owner = 'qt-firmware-settings:' + uuid.uuid4().hex
        self.capabilities.resources.acquire(owner, ('device-business', 'configuration'))
        uncertain = False
        try:
            context = self.execution.context
            path = context.config_dir / 'sample_upgrade_settings.ini'
            store = SampleUpgradeSettingsStore(path)
            previous = path.read_bytes() if path.exists() else None
            updated = replace(store.load(), **arguments['settings'])
            if self.execution._binding() != self.settings_binding:
                raise CapabilityError('configuration_changed', '保存准备期间项目设置变化，未写入')
            try:
                store.save(updated)
                self.execution.workspace.projects.save(context)
            except Exception:
                try:
                    if previous is None:
                        path.unlink(missing_ok=True)
                    else:
                        QtConfigurationService._replace(path, previous)
                except Exception:
                    uncertain = True
                    raise CapabilityError('configuration_rollback_failed', '升级设置恢复失败，须本机核实') from None
                raise CapabilityError('configuration_save_failed', '保存未完成，已恢复原升级设置') from None
            self.execution._log('[Qt升级] 已通过项目设置文件保存升级参数')
            self.settings_binding = self.execution._binding()
            return self.poll(arguments, authority)
        finally:
            self.capabilities.resources.release(owner, uncertain=uncertain)

    def poll(self, arguments, authority):
        self._check(arguments)
        self.execution.poll()
        job = self.execution.jobs.get(self.latest, {})
        status = job.get('status') or {}
        result = status.get('result') or {}
        return dict(job=self.latest, state=status.get('state', 'idle'),
                    stage=status.get('stage', ''), active=not self.execution.idle,
                    stoppable=bool(self.latest and self.latest == self.execution.latest and not self.execution.idle),
                    items=result.get('items', []) if result else self.observation.progress(
                        job.get('authority').operation_id if job else ''),
                    notice=result.get('notice', ''))

    def logs(self, arguments, authority):
        # A read-only log view is keyed by the live batch, separately from the
        # upgrade editor session. Closing the editor never stops observation.
        return self.observation.serial.logs(arguments['batch'], arguments['active'])

    def preview(self, arguments, authority):
        self._check(arguments)
        self._discard()
        self.execution._prepare_guard()
        args = normalized_upgrade_arguments(arguments['upgrade'])
        if args['upgrade_type'] == '页面升级':
            # The original page worker uses its default limit of eight.
            args['parallel_count'] = 8
        binding = self.execution._binding()
        if binding != self.settings_binding:
            raise ReviewRequired('configuration_changed', '项目设置已变化，请关闭后重新打开核对', 'upgrade', 'close_button')
        targets = self.execution._snapshot()
        settings = targets['upgrade_settings']
        if not settings['username'].strip() or not settings['password'].strip():
            raise ReviewRequired('configuration_incomplete', '请填写并保存超级用户名和密码', 'upgrade', 'username')
        requests = build_upgrade_requests(args, targets)
        manual_restart = args['upgrade_type'] == '全包升级' and not targets['power_serial_port']
        vlans = {request.vlan.casefold() for request in requests}
        ports = [request.serial_port.casefold() for request in requests if getattr(request, 'serial_port', '')]
        if len(vlans) != len(requests) or len(set(ports)) != len(ports):
            raise ReviewRequired('duplicate_target', '升级目标存在重复网卡或样机串口，请核对已选通道', 'channels', 'binding', channels=args['channel_ids'])
        token = uuid.uuid4().hex
        job_authority = replace(authority, principal=f'{authority.principal}:{token}',
                                operation_id=token, channels=tuple(args['channel_ids']), approved=False)
        self.execution._verify_nics(job_authority.channels, binding)
        try:
            self.capabilities.upgrades.validate(args, job_authority, local_manual_restart=manual_restart)
        except CapabilityError as error:
            if error.code in ('firmware_not_found', 'firmware_changed', 'invalid_firmware'):
                raise ReviewRequired(error.code, str(error), 'upgrade', 'firmware') from None
            if error.code == 'network_conflict':
                raise ReviewRequired(error.code, str(error), 'channels', 'vlan',
                                     channels=args['channel_ids'], **error.details) from None
            if error.code != 'compatibility_confirmation_required':
                raise
            firmware = error.details['firmware']
            challenge = error.details['confirmation'].rsplit(' ', 1)[-1]
        else:
            raise CapabilityError('unexpected_confirmation', '未取得本次独立的固件适配确认')
        self.pending = UpgradeConfirmation(token, binding, args, job_authority, challenge, time.monotonic(), manual_restart)
        if self.execution._binding() != binding:
            self._discard()
            raise ReviewRequired('configuration_changed', '预检期间配置变化，请重新预检', 'upgrade', 'preview_button')
        summary = [self.execution.context.identity.name, args['upgrade_type'],
                   f"固件：{firmware['path']}", f"SHA256：{firmware['sha256']}",
                   f"最多并行 {min(args['parallel_count'], len(requests))} 台"]
        if args['upgrade_type'] == '全包升级':
            summary.extend((f"传输：{args['transfer_method']} · Boot：{args['boot_entry_method']}",
                            '电源：手动重启' if manual_restart else f"程控电源：{targets['power_serial_port']}"))
        summary += [self._target_line(number, request) for number, request in zip(args['channel_ids'], requests)]
        summary.append('恢复出厂：' + ('开启' if args['restore_factory'] else '关闭'))
        summary.append('请核对目标型号与固件适配。确认后可能刷写固件、重启样机及调整网卡。')
        summary.append('请手动重启以上样机，再点击「已重启，继续升级」。' if manual_restart else '是否继续？')
        self.execution._log('[Qt升级] 已完成预检，等待本机确认')
        return dict(confirmation=token, summary='\n'.join(summary), manual_restart=manual_restart)

    @staticmethod
    def _target_line(number, request):
        if hasattr(request, 'bind_ip'):
            route = f'{request.bind_ip} → {request.device_ip}'
        elif request.web_source_ip:
            route = f'{request.web_source_ip} → {request.web_device_ip} · {request.serial_port}'
        else:
            route = f'{request.tftp_server_ip} ↔ 192.168.1.1 · {request.serial_port}'
        return f'CH{number:02d} · {request.vlan} · {route}'

    def execute(self, arguments, authority):
        self._check(arguments)
        pending = self.pending
        if not pending or pending.token != arguments['confirmation'] or (
                not pending.manual_restart and time.monotonic() - pending.created > 120):
            self._discard()
            raise ReviewRequired('confirmation_expired', '升级确认已失效，请重新预检', 'upgrade', 'preview_button')
        if arguments.get('manual_restart_confirmed', False) != pending.manual_restart:
            self._discard()
            raise ReviewRequired('manual_restart_confirmation_required', '请按本次预检的电源方式重新确认', 'upgrade', 'preview_button')
        try:
            self.execution._prepare_guard()
            self.execution._verify_nics(pending.authority.channels, pending.binding)
            self.capabilities.upgrades.confirm(pending.authority.principal, pending.challenge)
            job_authority = replace(pending.authority, approved=True)
            self.execution._admission_binding = pending.binding
            self.observation.arm(pending.token)
            if pending.manual_restart:
                result = self.capabilities._upgrade(pending.arguments, job_authority, local_manual_restart=True)
            else:
                result = self.capabilities.execute('firmware.upgrade', pending.arguments, job_authority)
        except Exception:
            self.observation.disarm()
            raise
        finally:
            self.execution._admission_binding = None
            self._discard()
        identifier = result['job_id']
        self.execution.jobs[identifier] = dict(authority=job_authority, after=0, status=None,
            channels={}, progress=None, title=pending.arguments['upgrade_type'], result_view='查看样机升级窗口')
        self.latest = self.execution.latest = identifier
        self.execution.parameters = ()
        self.execution._log('[Qt升级] 本机确认后提交原升级任务', job_id=identifier)
        return self.poll(arguments, authority)

    def _discard(self):
        pending, self.pending = self.pending, None
        if pending:
            validation = self.capabilities.upgrades
            with validation.lock:
                principal = pending.authority.principal
                for cache in (validation.pending, validation.confirmed):
                    for key in tuple(cache):
                        if key[0] == principal:
                            cache.pop(key)

    def cancel(self, arguments, authority):
        self._check(arguments)
        self._discard()
        self.execution._log('[Qt升级] 本机已取消，未启动升级')

    def stop(self, arguments, authority):
        self._check(arguments)
        if self.latest and self.latest == self.execution.latest and not self.execution.idle:
            self.execution.stop(self.latest)
        return self.poll(arguments, authority)

    def detach(self, arguments, authority):
        self._check(arguments)
        self.shutdown()

    def shutdown(self):
        self._discard()
        self.token = ''
        self.settings_binding = ''

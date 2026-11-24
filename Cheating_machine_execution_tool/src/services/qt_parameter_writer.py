"""Local operator controls for the shared sample parameter writer."""
from dataclasses import dataclass, replace
from functools import partial
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import uuid

from line_check_assistant.network_ops import adapter_alias_from_display, factory_bind_ip_for, factory_device_host_for
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
from src.core.sample_parameter_table import generate_parameter_records, load_parameter_records, save_parameter_records_xlsx
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.project_review import ReviewRequired
from src.models.sample_parameter_models import ParameterGenerationTemplate
from src.services.capability_device_services import CHANNEL_PROPERTIES
from src.services.qt_configuration_service import QtConfigurationService
from src.services.qt_serial_observation import JobSerialObservation, SERIAL_LOG_REQUEST


TABLE = dict(CHANNEL_PROPERTIES, table_path=dict(type='string', minLength=1, maxLength=4096))
OPTIONS = dict(parallel_count=dict(type='integer', minimum=1, maximum=8),
               clear_parameters=dict(type='boolean'), exit_aging=dict(type='boolean'))
CREDENTIALS = dict(initial_username=dict(type='string', maxLength=500),
                   initial_password=dict(type='string', maxLength=4096))


@dataclass(frozen=True)
class ParameterConfirmation:
    token: str
    created: float
    binding: str
    arguments: dict
    records: tuple
    digest: str
    targets: tuple


class QtParameterWriter:
    def __init__(self, execution):
        self.execution = execution
        self.service = execution.capabilities
        self.shared = self.service.parameters
        self.token = ''
        self.binding = ''
        self.pending = None
        self.latest = ''
        self.latest_targets = ()
        self.serial = JobSerialObservation('Qt写参', execution._log)
        token = dict(type='string', minLength=32, maxLength=32)
        session = dict(token=token)
        preview = object_schema(dict(TABLE, **OPTIONS), tuple(TABLE) + tuple(OPTIONS))
        settings = dict(OPTIONS, **CREDENTIALS, table_path=dict(type='string', maxLength=4096))
        generator = self.service.registry.get('parameters.generate').input_schema['properties']['template']
        for name, handler, fields, risk in (
            ('show', self.show, {}, 'read'),
            ('poll', self.poll, session, 'read'),
            ('logs', self.logs, SERIAL_LOG_REQUEST, 'read'),
            ('preflight', self.preflight, dict(session, selection=preview), 'read'),
            ('select_table', self.select_table, dict(session, selection=preview), 'modify'),
            ('preview', self.preview, dict(session, selection=preview), 'read'),
            ('execute', self.execute, dict(session, confirmation=token), 'dangerous'),
            ('cancel', self.cancel, session, 'read'),
            ('save', self.save, dict(session, settings=object_schema(settings, tuple(settings))), 'modify'),
            ('generate', self.generate, dict(session, **CHANNEL_PROPERTIES, template=generator,
                 output_path=dict(type='string', minLength=1, maxLength=4096)), 'modify'),
            ('stop', self.stop, session, 'modify'),
            ('detach', self.detach, session, 'read'),
        ):
            self.service.registry.register(CapabilitySpec(
                'parameters.editor.' + name, '写样机参数窗口', '本机项目窗口控制面',
                object_schema(fields, tuple(fields)), handler, risk=risk, sources=('gui',),
                execution_mode='job' if name == 'execute' else 'sync',
                resource_requirements=('device-business', 'adapter', 'serial') if name == 'execute' else (),
                cancellation='cooperative' if name == 'execute' else 'none'))

    def _check(self, arguments):
        if not self.token or self.token != arguments['token']:
            raise CapabilityError('session_expired', '写参窗口已失效，请重新打开')

    def show(self, arguments, authority):
        if not self.token:
            self.token = uuid.uuid4().hex
        self.binding = self.execution._binding()
        snapshot = self.execution._snapshot()
        data = snapshot['upgrade_settings']
        settings = {key: data['parameter_' + key] for key in (*OPTIONS, *CREDENTIALS, 'table_path')}
        targets = [dict(number=int(c['section'].rsplit('_', 1)[1]), vlan=c['vlan_name'], port=c['serial_port'],
                        host=c['device_manage_ip']) for c in snapshot['channels'] if c['enabled']]
        return dict(self.poll({'token': self.token}, authority), token=self.token,
                    project=self.execution.context.identity.name, settings=settings, targets=targets)

    def _check_binding(self):
        if self.execution._binding() != self.binding:
            raise ReviewRequired('configuration_changed', '项目配置已变化，请关闭窗口后重新打开核对', 'parameter', 'close_button')

    def _load(self, table_path):
        # Parse the exact bytes whose digest the operator will approve. A later
        # write uses these records and the original Job's admission recheck.
        info = self.service.files.information(table_path)
        path = Path(info['path'])
        digest = hashlib.sha256()
        try:
            with TemporaryDirectory(prefix='dutpilot-parameter-preview-') as root:
                copy = Path(root) / ('table' + path.suffix)
                with path.open('rb') as source, copy.open('wb') as target:
                    for chunk in iter(lambda: source.read(65536), b''):
                        digest.update(chunk)
                        target.write(chunk)
                expected = digest.hexdigest()
                if expected != info['sha256']:
                    raise ReviewRequired('parameter_table_changed', '读取期间参数表发生变化，请重新预检', 'parameter', 'path')
                records = tuple(load_parameter_records(copy))
        except CapabilityError:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            raise ReviewRequired('parameter_table_unreadable', '参数表读取失败：' + str(error), 'parameter', 'path') from None
        return str(path), expected, records

    def _checked_table(self, arguments, authority):
        self._check(arguments)
        self.pending = None
        self._check_binding()
        selection = dict(arguments['selection'])
        path, digest, records = self._load(selection['table_path'])
        selection['table_path'] = path
        authority = replace(authority, channels=tuple(selection['channel_ids']))
        snapshot, checked, indexed = self.shared._prepare(selection, authority, records=records)
        self._check_binding()
        targets = tuple(dict(vlan=t.vlan, port=t.serial_port, row=t.record.source_row,
                             mac=t.record.values.get('MAC', '')) for t in checked.targets)
        result = dict(ok=checked.ok, errors=list(checked.errors), warnings=list(checked.warnings), targets=targets)
        return selection, records, digest, snapshot, indexed, result

    def preflight(self, arguments, authority):
        *_, result = self._checked_table(arguments, authority)
        self.execution._log('[Qt写参] 参数表预检' + ('通过' if result['ok'] else '失败'))
        return result

    def select_table(self, arguments, authority):
        self.execution._prepare_guard()
        selection, *_, result = self._checked_table(arguments, authority)
        self._save_changes({'parameter_table_path': selection['table_path']})
        self.execution._log('[Qt写参] 已加载参数表，原预检' + ('通过' if result['ok'] else '未通过'))
        return dict(result, path=selection['table_path'])

    def preview(self, arguments, authority):
        self.execution._prepare_guard()
        selection, records, digest, snapshot, indexed, result = self._checked_table(arguments, authority)
        if not result['ok']:
            return result
        settings = snapshot['upgrade_settings']
        if not settings['parameter_initial_username'].strip() or not settings['parameter_initial_password']:
            raise ReviewRequired('configuration_incomplete', '请填写并保存首次登录账号和密码', 'parameter', 'username')
        for target in result['targets']:
            vlan = target['vlan'].lower()
            channel = indexed[vlan]
            source = channel.network_card_ip.strip()
            host = channel.device_manage_ip.strip() or snapshot.get('device_ip', '').strip()
            number = int(channel.section.rsplit('_', 1)[1])
            if source and host and source == host:
                raise ReviewRequired('invalid_target', f'{vlan} 的 PC 静态 IP 与样机管理 IP 相同', 'channels',
                                     'device_ip', channels=(number,))
            if source and host and not ((channel.factory_bind_ip or factory_bind_ip_for(source))
                                        and (channel.factory_device_host or factory_device_host_for(host))):
                raise ReviewRequired('invalid_target', f'{vlan} 缺少工厂模式网络配置', 'channels',
                                     'binding', channels=(number,))
        selection_ids = selection['channel_ids']
        self.execution._verify_nics(selection_ids, self.binding)
        confirmation = uuid.uuid4().hex
        self.pending = ParameterConfirmation(confirmation, time.monotonic(), self.binding,
            selection, records, digest, tuple(t['vlan'] for t in result['targets']))
        steps = [
            '1. 进入工厂模式', '2. 重启样机', '3. 等待 100 秒', '4. 工厂模式二次登录',
            '5. 退出老化' + ('：启用' if selection['exit_aging'] else '：跳过'),
            '6. 清空参数' + ('：启用' if selection['clear_parameters'] else '：跳过'),
            '7. 写入并读回校验全部 15 项参数', '8. 退出工厂模式', '9. 重启样机',
        ]
        target_lines = [f"{t['vlan']} / {t['port']} / MAC {t['mac']}" for t in result['targets']]
        summary = '\n'.join([self.execution.context.identity.name, f"参数表：{selection['table_path']}",
                            f"最多并行 {min(len(target_lines), selection['parallel_count'])} 台",
                            *target_lines, '', *steps, '', '确认写入并重启所选样机？'])
        self.execution._log('[Qt写参] 预检通过，等待本机确认')
        return dict(result, confirmation=confirmation, summary=summary)

    def execute(self, arguments, authority):
        self._check(arguments)
        pending, self.pending = self.pending, None
        if not pending or arguments['confirmation'] != pending.token or time.monotonic() - pending.created > 120:
            raise ReviewRequired('confirmation_expired', '写参确认已失效，请重新预检', 'parameter', 'preflight_button')
        self.execution._prepare_guard()
        ids = tuple(pending.arguments['channel_ids'])
        self.execution._verify_nics(ids, pending.binding)
        job_authority = replace(authority, operation_id=pending.token, channels=ids)
        self.execution._admission_binding = pending.binding
        try:
            self.service.validate('parameters.write', pending.arguments, job_authority)
            job_authority.check(ids, self.service.registry.get('parameters.write').risk)
            result = self.shared.write(pending.arguments, job_authority,
                confirmed_table=(pending.digest, pending.records),
                observe_serial=partial(self.serial.track, pending.token))
        finally:
            self.execution._admission_binding = None
        job = result['job_id']
        self.execution.jobs[job] = dict(authority=job_authority, after=0, status=None, channels={}, progress=None,
                                       title='批量写样机参数', result_view='查看写样机参数窗口')
        self.latest = self.execution.latest = job
        self.latest_targets = pending.targets
        self.execution.parameters = ()
        self.execution._log('[Qt写参] 本机已确认，已提交原写参任务', job_id=job)
        return self.poll(arguments, authority)

    def save(self, arguments, authority):
        self._check(arguments)
        changes = {'parameter_' + key: value for key, value in arguments['settings'].items()}
        changes['parameter_initial_username'] = changes['parameter_initial_username'].strip()
        self._save_changes(changes)

    def _save_changes(self, changes):
        self.pending = None
        self.execution._prepare_guard()
        self._check_binding()
        owner = 'qt-parameter-settings:' + uuid.uuid4().hex
        self.service.resources.acquire(owner, ('device-business', 'configuration'))
        uncertain = False
        try:
            context = self.execution.context
            path = context.config_dir / 'sample_upgrade_settings.ini'
            store = SampleUpgradeSettingsStore(path)
            previous = path.read_bytes() if path.exists() else None
            updated = replace(store.load(), **changes)
            self._check_binding()
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
                    raise CapabilityError('configuration_rollback_failed', '写参设置恢复失败，须本机核实') from None
                raise CapabilityError('configuration_save_failed', '保存未完成，已恢复原写参设置') from None
            self.binding = self.execution._binding()
            self.execution._log('[Qt写参] 已保存项目写参设置')
        finally:
            self.service.resources.release(owner, uncertain=uncertain)

    def generate(self, arguments, authority):
        self._check(arguments)
        self._check_binding()
        authority = replace(authority, channels=tuple(arguments['channel_ids']))
        _, channels = self.service.devices.selected(arguments, authority)
        output = Path(arguments['output_path']).expanduser().resolve()
        if output.suffix.lower() != '.xlsx' or not output.parent.is_dir():
            raise CapabilityError('invalid_output', '请选择有效的 Excel 参数表输出位置')
        vlans = [adapter_alias_from_display(c.vlan_name or c.adapter_alias).lower() for c in channels]
        try:
            records = generate_parameter_records(vlans, ParameterGenerationTemplate(**arguments['template']))
            with TemporaryDirectory(dir=output.parent, prefix='.dutpilot-parameters-') as root:
                temporary = Path(root) / 'parameters.xlsx'
                save_parameter_records_xlsx(temporary, records)
                temporary.replace(output)
        except (OSError, ValueError, RuntimeError) as error:
            raise CapabilityError('parameter_generation_failed', '参数表生成失败：' + str(error)) from None
        self.execution._log(f'[Qt写参] 已生成参数表：{output}，{len(records)} 台')
        return dict(path=str(output), count=len(records))

    def poll(self, arguments, authority):
        self._check(arguments)
        self.execution.poll()
        status = (self.execution.jobs.get(self.latest, {}).get('status') or {})
        result = status.get('result') or {}
        items = [dict(item, vlan=vlan) for vlan, item in zip(self.latest_targets, result.get('items', []))]
        return dict(job=self.latest, state=status.get('state', 'idle'), stage=status.get('stage', ''),
                    active=not self.execution.idle, items=items,
                    stoppable=bool(self.latest and self.latest == self.execution.latest and not self.execution.idle))

    def logs(self, arguments, authority):
        return self.serial.logs(arguments['batch'], arguments['active'])

    def cancel(self, arguments, authority):
        self._check(arguments)
        self.pending = None
        self.execution._log('[Qt写参] 本机取消确认，未启动设备任务')

    def stop(self, arguments, authority):
        self._check(arguments)
        if self.latest and self.latest == self.execution.latest and not self.execution.idle:
            self.execution.stop(self.latest)
        return self.poll(arguments, authority)

    def detach(self, arguments, authority):
        self._check(arguments)
        self.shutdown()

    def shutdown(self):
        self.pending = None
        self.token = self.binding = ''

"""Local DUT presentation commands; original services own device execution.

Only immutable request data crosses into a job. Window tokens and confirmations
are never device authority for AI/remote callers. Credentials stay in memory and
are excluded from durable job arguments, result payloads and display logs.
"""
from dataclasses import asdict
from copy import deepcopy
import threading
import time
import uuid
import re

from line_check_assistant.network_ops import adapter_alias_from_display
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.dut_config_models import DutTelnetEnableRequest, DutWanSettings, DutAdvancedConfigRequest, DutWifiSettings
from src.services.dut_config_service import validate_dut_telnet_request, run_dut_telnet_enable_batch
from src.services.dut_status_query_service import run_dut_status_query_batch
from src.services.capability_jobs import TERMINAL
from src.services.capability_device_services import settings_schema
from src.services.dut_wan_query_service import run_dut_wan_query_batch, common_wan_connection_names, common_wan_connection_details
from src.services.dut_advanced_config_service import run_dut_advanced_config_batch, validate_dut_advanced_request


from src.services.qt_dut_voice_tr069 import ACTION_LABELS, MODELS, QtDutVoiceTr069


class QtDutConfiguration:
    def __init__(self, execution):
        self.execution = execution
        self.capabilities = execution.capabilities
        self.token = ''
        self.pending = None
        self.latest = ''
        self.rows = {}
        self.run_targets = None
        self.credentials = None
        self.feature = 'telnet'
        self.wan_cache = None  # Private GUI-only results, never durable job data.
        self.lock = threading.RLock()
        from src.services.qt_dut_wifi import QtDutWifi
        self.wifi = QtDutWifi(self)
        self.voice_tr069 = QtDutVoiceTr069(self)
        token = dict(type='string', minLength=32, maxLength=32)
        base = {'token': token}
        preview = dict(base, action=dict(type='string', enum=['enable', 'query', 'wan_query', 'wan_configure', *self.wifi.ACTIONS, *ACTION_LABELS]),
            channel_ids=dict(type='array', minItems=1, maxItems=16, uniqueItems=True,
                items=dict(type='integer', minimum=1, maximum=16)),
            username=dict(type='string', maxLength=500), password=dict(type='string', maxLength=4096),
            parallel_count=dict(type='integer', minimum=1, maximum=8))
        for suffix, handler, schema, risk in (
            ('show', self.show, object_schema(), 'read'),
            ('poll', self.poll, object_schema(base, ('token',)), 'read'),
            ('preview', self.preview, object_schema(dict(preview, settings=object_schema(dict(
                settings_schema(DutWanSettings)['properties'], **settings_schema(DutWifiSettings)['properties'],
                **settings_schema(MODELS['voice'])['properties'], **settings_schema(MODELS['tr069'])['properties'])),
                line_index=dict(type='string', maxLength=50),
                query_id=dict(type='string', maxLength=32), increment_ssid=dict(type='boolean'),
                ssid_index=dict(type='string', enum=[str(n) for n in range(1,9)])), tuple(preview)), 'read'),
            ('execute', self.execute, object_schema(dict(base, confirmation=token), ('token', 'confirmation')), 'dangerous'),
            ('cancel', self.cancel, object_schema(base, ('token',)), 'read'),
            ('stop', self.stop, object_schema(base, ('token',)), 'modify'),
            ('detach', self.detach, object_schema(dict(base,
                username=preview['username'], password=preview['password'], parallel_count=preview['parallel_count']), ('token',)), 'read'),
        ):
            self.capabilities.registry.register(CapabilitySpec('dut.editor.' + suffix, '本机DUT配置 ' + suffix,
                '仅本机GUI；复用原DUT服务、任务和资源保护，不新增设备并行能力。', schema, handler,
                sources=('gui',), risk=risk, execution_mode='job' if suffix == 'execute' else 'sync',
                resource_requirements=('device-business',) if suffix == 'execute' else (),
                cancellation='cooperative' if suffix == 'execute' else 'none'))

    def _check(self, arguments):
        if not self.token or arguments.get('token') != self.token:
            raise CapabilityError('window_expired', 'DUT窗口上下文已失效，请重新打开')
        if self.execution.closing:
            raise CapabilityError('closing', '项目正在收尾')

    def _targets(self):
        return [c for c in self.execution._snapshot()['channels'] if c['enabled']]

    def show(self, arguments, authority):
        if self.execution.closing:
            raise CapabilityError('closing', '项目正在收尾')
        if not self.token:
            self.token = uuid.uuid4().hex
        values = self.poll({'token': self.token}, authority)
        options = self.execution._snapshot()['upgrade_settings']
        saved_login = (options.get('parameter_initial_username', ''), options.get('parameter_initial_password', ''))
        values.update(self.credentials or dict(username=saved_login[0], password=saved_login[1], parallel_count=1))
        values['saved_parameter_login'] = saved_login
        self.execution._log('[Qt DUT] 已载入当前项目DUT目标；未连接设备')
        return values

    def poll(self, arguments, authority):
        self._check(arguments)
        self.execution.poll()
        job = self.execution.jobs.get(self.latest, {})
        status = job.get('status') or {}
        with self.capabilities.jobs.lock:
            thread = self.capabilities.jobs.threads.get(self.latest)
        active = bool(self.latest and (status.get('state') not in TERMINAL or thread and thread.is_alive()))
        with self.lock:
            rows = deepcopy(list(self.rows.values()))
            cache = deepcopy(self.wan_cache)
        targets = [{
                'number': int(c['section'].rsplit('_', 1)[1]), 'label': c['section'].replace('channel_', '通道 '), 'vlan': c['vlan_name'],
                'source': c['network_card_ip'], 'host': c['device_manage_ip'], 'adapter': c['adapter_alias']
            } for c in self._targets()]
        return dict(token=self.token, project_id=self.execution.context.identity.project_id,
            project_name=self.execution.context.identity.name, targets=deepcopy(self.run_targets) if active and self.run_targets else targets,
            rows=rows, job_id=self.latest, state=status.get('state', 'idle'),
            feature=self.feature, wan_query=(dict(query_id=cache['query_id'], channel_ids=list(cache['ids']),
                names=list(cache['names']), details=cache['details']) if cache else None),
            wifi_queries=self.wifi.snapshot(), voice_tr069_queries=self.voice_tr069.snapshot(),
            active=active, error=(status.get('result') or {}).get('error', ''),
            can_execute=self.execution.idle and not self.execution.editor_open)

    def preview(self, arguments, authority):
        self._check(arguments)
        self.pending = None
        self.execution._prepare_guard()
        self.credentials = {key: arguments[key] for key in ('username', 'password', 'parallel_count')}
        targets = {int(c['section'].rsplit('_', 1)[1]): c for c in self._targets()}
        requests, vlans = [], set()
        for number in arguments['channel_ids']:
            if number not in targets:
                raise CapabilityError('invalid_target', '目标已取消选择或不存在，请刷新DUT目标')
            c = targets[number]
            vlan = adapter_alias_from_display(c['vlan_name'] or c['adapter_alias']).strip().lower()
            if vlan in vlans:
                raise CapabilityError('invalid_target', '所选目标重复使用VLAN，请先修正通道配置')
            vlans.add(vlan)
            request = DutTelnetEnableRequest(c['section'].replace('channel_', '通道 '), vlan,
                adapter_alias_from_display(c['adapter_alias'] or c['vlan_name']).strip(),
                c['network_card_ip'].strip(), c['device_manage_ip'].strip(),
                c['subnet_mask'].strip() or '255.255.255.0', arguments['username'].strip(), arguments['password'])
            errors = validate_dut_telnet_request(request)
            if errors:
                raise CapabilityError('configuration_incomplete', '；'.join(errors))
            requests.append(request)
        confirmation = uuid.uuid4().hex
        settings = None
        if arguments['action'] == 'wan_configure':
            if 'settings' not in arguments:
                raise CapabilityError('invalid_parameters', '必须明确WAN参数')
            try:
                settings = DutWanSettings(**arguments['settings'])
            except TypeError:
                raise CapabilityError('invalid_parameters', 'WAN字段包含其它页面参数') from None
            errors = [e for r in requests for e in validate_dut_advanced_request(
                DutAdvancedConfigRequest(**asdict(r), feature='wan', settings=settings))]
            if errors:
                raise CapabilityError('invalid_parameters', '；'.join(errors))
            if settings.operation in ('modify', 'delete'):
                self._check_wan_query(arguments, requests)
        wifi_options = self.wifi.prepare(arguments, requests) if arguments['action'] in self.wifi.ACTIONS else {}
        voice_tr069_options = self.voice_tr069.prepare(arguments, requests) if arguments['action'] in ACTION_LABELS else {}
        feature_options = wifi_options or voice_tr069_options
        if feature_options:
            settings = feature_options['settings']
        self.pending = (confirmation, self.execution._binding(), time.monotonic(),
            tuple(arguments['channel_ids']), tuple(requests), arguments['action'], arguments['parallel_count'],
            dict(settings=settings, query_id=arguments.get('query_id', ''), **{k:v for k,v in feature_options.items() if k!='settings'}))
        title = self._title(arguments['action'])
        summary = self.execution.context.identity.name + '\n' + title + '；并行数 ' + str(arguments['parallel_count']) + '\n'
        ubus = arguments['action'].startswith(('wan_', 'wifi_', 'voice_', 'tr069_'))
        summary += '\n'.join(f'{r.channel} / {r.vlan} / {"UBUS" if ubus else "TCP"} '
            f'{r.bind_ip} → {r.device_host}:{r.ubus_port if ubus else 23}' for r in requests)
        if isinstance(settings, DutWanSettings):
            operation_name = {'add':'新增', 'modify':'修改', 'delete':'删除'}[settings.operation]
            summary += (f'\nWAN操作={operation_name}，连接={settings.connection_index or "新增"}，'
                f'模式={settings.mode}，业务={settings.service_type}，VLAN={settings.vlan_id}，'
                f'PortBind={settings.port_bind}，MTU={settings.mtu}，协议={settings.ip_protocol}')
            if settings.operation == 'delete':
                summary += '\n危险：将删除每台DUT上指定索引的现有WAN，不会自动恢复；请确认索引对应关系一致。'
        if wifi_options:
            summary += self.wifi.summary(wifi_options)
        if voice_tr069_options:
            summary += self.voice_tr069.summary(voice_tr069_options)
        summary += ('\n将按原流程准备本机网卡并修改DUT配置，可能中断业务，是否继续？'
            if arguments['action'] == 'enable' or arguments['action'].endswith('_configure') else '\n仅查询DUT状态；原服务仍会准备本机网卡/IP，是否继续？')
        self.execution._log('[Qt DUT] 已准备本机确认：' + title + '；目标数=' + str(len(requests)))
        return dict(confirmation=confirmation, summary=summary)

    def execute(self, arguments, authority):
        self._check(arguments)
        pending, self.pending = self.pending, None
        if not pending or pending[0] != arguments['confirmation'] or time.monotonic() - pending[2] > 120:
            raise CapabilityError('confirmation_expired', 'DUT确认已失效，请重新核对目标')
        _, binding, _, ids, requests, action, parallel, options = pending
        self.execution._prepare_guard()
        if self.execution._binding() != binding:
            raise CapabilityError('configuration_changed', '确认后项目配置发生变化，未执行')
        self.execution._verify_nics(ids, binding)
        if action == 'wan_configure' and options['settings'].operation in ('modify', 'delete'):
            self._check_wan_query(dict(channel_ids=list(ids), username=requests[0].username,
                password=requests[0].password, query_id=options['query_id'], settings=asdict(options['settings'])), requests)
        if action in self.wifi.ACTIONS:
            self.wifi.recheck(options, ids, requests)
        voice_tr069 = action in ACTION_LABELS
        if voice_tr069:
            self.voice_tr069.recheck(options, ids, requests)
        # The capability authority comes from the trusted local adapter, bound
        # again to this one-use confirmation and explicit target subset.
        from dataclasses import replace
        authority = replace(authority, operation_id=arguments['confirmation'], channels=ids)
        feature_secret = getattr(options['settings'], 'pppoe_password', '') or getattr(options['settings'], 'password', '')
        secrets = tuple(r.password for r in requests if r.password) + ((feature_secret,) if feature_secret else ())
        if voice_tr069 and options['settings'] is not None:
            secrets += self.voice_tr069.secrets(options['settings'], options['feature'])

        def clean(value):
            if voice_tr069 and options['feature'] == 'tr069':
                value = re.sub(r'(https?://)[^/@\s]+@', r'\1', value, flags=re.IGNORECASE)
            for secret in sorted(set(secrets), key=len, reverse=True):
                value = value.replace(secret, '<已隐藏>')
            return re.sub(r'''(?i)((?:['"]?(?:[\w_]*password|X_SDMC_Key|KeyPassphrase|PreSharedKey)['"]?)\s*[:=]\s*)(["'])(?:\\.|(?!\2).)*\2''',
                lambda match: match[1] + '<已隐藏>', value)
        def run(context, snapshot, channels):
            context.stop.checkpoint()
            def completed(value):
                index = next(n for n, r in zip(ids, requests) if (r.channel, r.bind_ip, r.device_host) ==
                    (value.request.channel, value.request.bind_ip, value.request.device_host))
                row = dict(number=index, ok=value.ok, stage=value.stage, message=clean(value.message),
                    state='success' if value.ok else 'stopped' if value.stage == 'stopped' else 'failed',
                    source=value.request.bind_ip, host=value.request.device_host, vlan=value.request.vlan)
                settings = getattr(value, 'settings', None)
                if settings is not None:
                    row['settings'] = (self.voice_tr069.public_settings(settings, options['feature'])
                                       if voice_tr069 else asdict(settings))
                    row['settings'].pop('password', None)
                    if 'probe_message' in row['settings']:
                        row['settings']['probe_message'] = clean(row['settings']['probe_message'])
                if action == 'wan_query':
                    row['wan_names'] = list(value.connection_names)
                    row['connections'] = [{k: v for k, v in asdict(c).items() if k != 'pppoe_password'} for c in value.connections]
                with self.lock:
                    if self.rows.get(index) == row:
                        return
                    self.rows[index] = row
                context.event('dut_item', clean(value.request.channel + '：' + value.message))
            kwargs = dict(max_workers=parallel, stop_event=context.stop.event,
                on_output=lambda line: context.event('dut', clean(line)), on_item_complete=completed)
            context.event('dut', '调用原业务服务：' + self._title(action), dispatched=True)
            try:
                if action == 'wan_query':
                    values = run_dut_wan_query_batch(requests, **kwargs)
                elif action == 'wan_configure':
                    advanced = tuple(DutAdvancedConfigRequest(**asdict(r), feature='wan', settings=options['settings']) for r in requests)
                    values = run_dut_advanced_config_batch(advanced, **kwargs)
                elif action in self.wifi.ACTIONS:
                    if action.endswith('_query'):
                        values = run_dut_status_query_batch(requests, options['feature'], ssid_index=options['ssid_index'], **kwargs)
                    else:
                        values = run_dut_advanced_config_batch(options['advanced'],
                            shared_wifi_settle=options['increment'] and len(requests)>1, **kwargs)
                elif voice_tr069:
                    if action.endswith('_query'):
                        index = {'line_index': options['line_index']} if options['feature'] == 'voice' else {}
                        values = run_dut_status_query_batch(requests, options['feature'], **index, **kwargs)
                    else:
                        values = run_dut_advanced_config_batch(options['advanced'], **kwargs)
                else:
                    values = (run_dut_telnet_enable_batch(requests, **kwargs) if action == 'enable' else
                        run_dut_status_query_batch(requests, 'telnet', **kwargs))
            except Exception as error:
                raise RuntimeError(clean(str(error))) from None
            for value in values:
                completed(value)
            ok = len(values) == len(requests) and all(v.ok for v in values)
            if action == 'wan_query' and ok and not context.stop.is_set():
                with self.lock:
                    self.wan_cache = dict(query_id=uuid.uuid4().hex, ids=ids, binding=binding,
                        credentials=(requests[0].username, requests[0].password),
                        names=common_wan_connection_names(values),
                        details={name: asdict(info) for name, info in common_wan_connection_details(values).items()})
            if action in self.wifi.ACTIONS and action.endswith('_query'):
                self.wifi.finish_query(options['feature'], values, ids, requests, binding, options['ssid_index'])
            if voice_tr069 and action.endswith('_query') and not context.stop.is_set():
                self.voice_tr069.finish_query(options, values, ids, requests, binding)
            succeeded = sum(v.ok for v in values)
            stopped = sum(v.stage == 'stopped' for v in values)
            context.event('dut', f'批次结束：成功 {succeeded}，失败 {len(values) - succeeded - stopped}，'
                f'停止/跳过 {stopped}；请求目标 {len(requests)}')
            with self.lock:
                rows = [dict(row) for row in self.rows.values()]
            return dict(ok=ok, state='stopped' if context.stop.is_set() else 'succeeded' if ok else
                'failed' if action == 'query' or action.endswith('_query') else 'unknown', items=rows)
        with self.lock:
            previous_rows = self.rows
            self.rows = {n: dict(number=n, state='queued', stage='queued', message='等待原服务执行') for n in ids}
        previous_targets = self.run_targets
        previous_cache = self.wan_cache
        previous_wifi = deepcopy(self.wifi.queries)
        with self.lock:
            previous_voice_tr069 = dict(self.voice_tr069.queries)
            if voice_tr069:
                self.voice_tr069.queries.pop(options['feature'], None)
        if action.startswith('wan_'):
            self.wan_cache = None
        if action in self.wifi.ACTIONS:
            self.wifi.queries.pop(options['feature'], None)
        self.run_targets = None
        self.run_targets = self.poll({'token': self.token}, authority)['targets']
        self.execution._admission_binding = binding
        try:
            if action in self.wifi.ACTIONS:
                recorded_extra = self.wifi.recorded(options)
            elif voice_tr069:
                recorded_extra = self.voice_tr069.recorded(options)
            else:
                recorded_extra = None
            result = self.capabilities.devices._job('dut.editor.execute',
                dict(channel_ids=list(ids), action=action, parallel_count=parallel), authority, run,
                recorded_extra=recorded_extra)
        except Exception:
            # Admission failure must not relabel the previous batch as queued.
            with self.lock:
                self.rows = previous_rows
            self.run_targets = previous_targets
            self.wan_cache = previous_cache
            self.wifi.queries = previous_wifi
            with self.lock:
                self.voice_tr069.queries = previous_voice_tr069
            raise
        finally:
            self.execution._admission_binding = None
        identifier = result['job_id']
        self.execution.jobs[identifier] = dict(authority=authority, after=0, status=None, channels={}, progress=None,
            title='DUT ' + self._title(action))
        self.latest = self.execution.latest = identifier
        self.feature = options.get('feature') or ('wan' if action.startswith('wan_') else 'telnet')
        self.execution.parameters = ()
        self.execution._log('[Qt DUT] 本机确认后已提交原受控任务：' + identifier)
        return self.poll({'token': self.token}, authority)

    @staticmethod
    def _title(action):
        if action in ACTION_LABELS:
            return ACTION_LABELS[action]
        return {'enable': 'Telnet开启', 'query': 'Telnet状态查询', 'wan_query': 'WAN查询',
            'wan_configure': 'WAN配置', 'wifi_2g_query':'2.4G WiFi查询', 'wifi_5g_query':'5G WiFi查询',
            'wifi_2g_configure':'2.4G WiFi配置', 'wifi_5g_configure':'5G WiFi配置'}[action]

    def _check_wan_query(self, arguments, requests):
        cache = self.wan_cache
        if (not cache or arguments.get('query_id') != cache['query_id'] or
                tuple(arguments['channel_ids']) != cache['ids'] or self.execution._binding() != cache['binding'] or
                (requests[0].username, requests[0].password) != cache['credentials'] or
                arguments['settings'].get('connection_index') not in cache['names']):
            raise CapabilityError('query_expired', 'WAN查询目标或参数已变化，请重新查询共同连接后选择')

    def cancel(self, arguments, authority):
        self._check(arguments)
        self.pending = None
        self.execution._log('[Qt DUT] 已取消确认，未启动设备操作')
        return {}

    def stop(self, arguments, authority):
        self._check(arguments)
        if self.latest:
            self.execution.stop(self.latest)
        return self.poll(arguments, authority)

    def detach(self, arguments, authority):
        self._check(arguments)
        if 'username' in arguments and 'password' in arguments and 'parallel_count' in arguments:
            self.credentials = {key: arguments[key] for key in ('username', 'password', 'parallel_count')}
        self.pending = None
        self.token = ''
        self.wan_cache = None
        self.wifi.queries.clear()
        with self.lock:
            self.voice_tr069.queries.clear()
        # Closing a presentation never cancels the real business job.
        self.execution._log('[Qt DUT] 已关闭显示窗口；真实任务按原生命周期运行')
        return {}

"""Project records and model tests over original services; human approval is not a tool."""
from dataclasses import asdict, replace
import threading
from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.models.ai_session_scope import source_identity
from src.services.ai_store import profile_fingerprint
from src.core.ai_source_ip import list_source_ips


class AiDataCapabilities:
    def __init__(self, runtime, conversation):
        self.runtime, self.conversation, self.store = runtime, conversation, conversation.store
        self.handoff_lock = threading.RLock()
        add = runtime.registry.register
        identifier = dict(type='string', minLength=1, maxLength=100)
        add(CapabilitySpec('ai.sessions.create', '创建空白会话',
            '使用当前可信身份及其模型的已保存配置创建普通会话；不切换GUI、不发送模型请求或操作设备。',
            object_schema(), self.create_session, risk='modify', sources=('local', 'gui')))
        for kind in ('sessions', 'reports'):
            add(CapabilitySpec('ai.' + kind + '.list', '查询' + kind, '查询当前身份及通道范围的项目记录摘要。',
                object_schema(), lambda a, auth, k=kind: self.list(k, a, auth), sources=('local', 'gui')))
            add(CapabilitySpec('ai.' + kind + '.read', '读取' + kind, '读取留存材料，不启动诊断。',
                object_schema({'id': identifier}, ('id',)), lambda a, auth, k=kind: self.read(k, a, auth), sources=('local', 'gui')))
            add(CapabilitySpec('ai.' + kind + '.rename', '重命名' + kind, '共用原记录显示名存储。',
                object_schema({'id': identifier, 'title': dict(type='string', minLength=1, maxLength=200)}, ('id', 'title')),
                lambda a, auth, k=kind: self.rename(k, a, auth), risk='modify', sources=('local', 'gui')))
            add(CapabilitySpec('ai.' + kind + '.delete', '删除指定' + kind, '按明确ID列表整批删除；不删除活动记录或自动清空其它记录。',
                object_schema({'ids': dict(type='array', minItems=1, maxItems=100, uniqueItems=True, items=identifier)}, ('ids',)),
                lambda a, auth, k=kind: self.delete(k, a, auth), risk='modify', sources=('local', 'gui')))
        add(CapabilitySpec('ai.profiles.list', '查询模型配置', '仅配置元数据，不返回密钥或更改当前模型。', object_schema(),
            lambda a, auth: dict(items=[asdict(p) for p in self.store.profiles()]), sources=('local', 'gui')))
        add(CapabilitySpec('ai.source_ip.list', '查询模型出口候选', '只读枚举本机网卡 IPv4；出口配置写入和选择仍由本地模型配置控制面完成。',
            object_schema(), lambda a, auth: dict(items=list_source_ips(self.runtime.emit)), sources=('local', 'gui')))
        for testing in (False, True):
            add(CapabilitySpec('ai.models.test' if testing else 'ai.models.query', '测试模型连接' if testing else '查询模型列表',
                '使用已保存配置和原客户端；不接受模型提供的URL/密钥，测试结果由客户端产生。',
                object_schema({'profile_id': identifier}, ('profile_id',)),
                lambda a, auth, t=testing: self.model_job(a, auth, t), risk='modify', execution_mode='job', sources=('local', 'gui')))
        add(CapabilitySpec('ai.cases.query', '查询人工案例', '读取原共用案例，不登记或确认模型编造的根因。',
            object_schema({'query': dict(type='string', maxLength=500), 'include_inactive': dict(type='boolean')}),
            self.cases))
        case_schema = {'case_id': dict(type='integer', minimum=1), 'revision': dict(type='string', minLength=64, maxLength=64)}
        add(CapabilitySpec('ai.cases.set_active', '设置人工案例启用状态', '显式设定状态，复用原共用案例存储；不能确认根因、创建或修订案例内容。',
            object_schema(dict(case_schema, active=dict(type='boolean')), ('case_id', 'revision', 'active')),
            lambda a, auth: self.change_case(a, auth), risk='modify', sources=('local', 'gui')))
        add(CapabilitySpec('ai.cases.delete', '删除明确人工案例', '按案例ID和当前revision删除，不删除过期选择或同ID的新内容。',
            object_schema(case_schema, ('case_id', 'revision')), lambda a, auth: self.change_case(a, auth, delete=True),
            risk='modify', sources=('local', 'gui')))
        add(CapabilitySpec('ai.reports.continue', '从报告接手排查', '共用原报告接手服务，只建立材料会话，不发送模型请求或操作设备。缺少目标快照的旧报告必须另经本地审阅。',
            object_schema({'id': identifier, 'revision': dict(type='string', minLength=64, maxLength=64),
                'legacy_target_channel': dict(type='integer', minimum=1, maximum=16)}, ('id', 'revision')),
            self.continue_report, risk='modify', sources=('local', 'gui'), resource_scope=self.handoff_scope))
        add(CapabilitySpec('ai.evidence.import', '导入文本证据', '原证据导入，保留待核实标签，材料不能改变权限。',
            object_schema({'path': dict(type='string', minLength=1)}, ('path',)), self.import_evidence, risk='modify', sources=('local', 'gui')))

    def _record(self, kind, identifier, authority):
        value = self.store.chat(identifier) if kind == 'sessions' else self.store.report(identifier)
        if kind == 'sessions':
            if fingerprint(source_identity(value.get('source') or {})) != authority.principal:
                raise CapabilityError('record_forbidden', '记录属于另一可信来源身份')
            targets = value.get('batch_targets') or ([value['target']] if value.get('target') else [])
            authority.check([t['channel'] for t in targets])
        else:
            if type(value.get('channel')) is not int:
                raise CapabilityError('record_scope_unknown', '历史报告未记录明确通道，须本地界面审阅')
            authority.check([value['channel']])
        return value

    def create_session(self, arguments, authority):
        session = self._record('sessions', authority.session_id, authority)
        operation = dict(session_id=authority.session_id, operation_id=authority.operation_id,
                         principal=authority.principal)
        with self.handoff_lock:
            for candidate in self.store.chats():
                if candidate.get('capability_create_operation') == operation:
                    self._record('sessions', candidate['id'], authority)
                    return dict(ok=True, session_id=candidate['id'], reused=True, device_operations=False)
            profile = self._profile(session['profile']['id'])
            created = self.conversation.create_blank_session(profile, source=session.get('source'))
            self.store.update_chat(created, capability_create_operation=operation)
        return dict(ok=True, session_id=created, reused=False, device_operations=False)

    def list(self, kind, arguments, authority):
        identifiers = [s['id'] for s in self.store.chats()] if kind == 'sessions' else [r[0] for r in self.store.reports()]
        titles = self.store.record_titles('chat' if kind == 'sessions' else 'report')
        rows = []
        for identifier in identifiers:
            try:
                value = self._record(kind, identifier, authority)
            except CapabilityError:
                continue
            rows.append(dict(id=identifier, title=titles.get(identifier, value.get('title', '')), channel=value.get('channel'), status=value.get('status', '')))
            if len(rows) >= 100:
                break
        return dict(items=rows, limit=100)

    def read(self, kind, arguments, authority):
        value = self._record(kind, arguments['id'], authority)
        if kind == 'sessions':
            value = dict(value, messages=self.store.chat_items(arguments['id'])[-100:])
        return dict(record=self.conversation.redactor.object(value), revision=fingerprint(value))

    def cases(self, arguments, authority):
        return dict(items=[dict(row, capability_revision=fingerprint(row)) for row in
            self.store.cases(arguments.get('query', ''), arguments.get('include_inactive', False))])

    def change_case(self, arguments, authority, delete=False):
        owner = self.store.case_store if self.store.case_store is not None else self.store
        with owner.lock:
            row = next((r for r in self.store.cases(include_inactive=True) if r['id'] == arguments['case_id']), None)
            if row is None:
                if delete:
                    return dict(ok=True, state='already_deleted')
                raise CapabilityError('case_missing', '案例已不存在，请刷新列表')
            if not delete and bool(row['active']) == arguments['active']:
                return dict(ok=True, active=bool(row['active']), reused=True)
            if fingerprint(row) != arguments['revision']:
                raise CapabilityError('case_changed', '案例版本/内容已变化，未执行过期选择')
            self.conversation.diagnostic.update_case_state(arguments['case_id'], delete=delete, expected_version=row.get('version'))
        return dict(ok=True, deleted=delete, **({} if delete else {'active': arguments['active']}))

    def handoff_scope(self, arguments):
        report = self.store.report(arguments['id'])
        if fingerprint(report) != arguments['revision']:
            raise CapabilityError('report_changed', '报告内容已变化，请读取当前报告后重试')
        if report.get('target'):
            if 'legacy_target_channel' in arguments:
                raise CapabilityError('invalid_parameters', '带目标快照的报告不能更换接手目标')
            return None
        number = arguments.get('legacy_target_channel')
        target = self.conversation.diagnostic.targets.get(number)
        if target is None or number != report.get('channel'):
            raise CapabilityError('legacy_target_required', '旧报告缺少目标快照，须明确同通道当前目标并由本地负责人核对')
        return dict(id='historical-report:' + arguments['id'] + ':' + arguments['revision'],
                    channel=number, report_revision=arguments['revision'], target_revision=fingerprint(asdict(target)))

    def continue_report(self, arguments, authority):
        report = self._record('reports', arguments['id'], authority)
        self.handoff_scope(arguments)
        session = self._record('sessions', authority.session_id, authority)
        profile = self.conversation._profile(session)
        target = self.conversation.diagnostic.targets.get(arguments.get('legacy_target_channel'))
        if target is not None:
            authority.check([target.channel])
        with self.handoff_lock:
            for candidate in self.store.chats():
                if candidate.get('capability_handoff_operation') == authority.operation_id:
                    if (candidate.get('source_report_id') != arguments['id'] or
                            candidate.get('capability_handoff_report_revision') != arguments['revision']):
                        raise CapabilityError('request_changed', '同一接手操作标识的报告或版本已变化')
                    self._record('sessions', candidate['id'], authority)
                    return dict(ok=True, session_id=candidate['id'], reused=True, device_operations=False)
            mode = self.conversation.permissions.status(authority.session_id)['mode']
            created = self.conversation.create_session_from_report(arguments['id'], profile,
                target=target, legacy_confirmed=target is not None,
                expected_report_sha256=arguments['revision'], source=session.get('source'), default_permission=mode)
            self.store.update_chat(created, capability_handoff_operation=authority.operation_id,
                                   capability_handoff_report_revision=arguments['revision'])
        return dict(ok=True, session_id=created, reused=False, device_operations=False,
                    notice='仅建立留存材料会话，未发送模型请求或设备命令；旧批次不作为当前现场')

    def rename(self, kind, arguments, authority):
        self._record(kind, arguments['id'], authority)
        self.store.rename_record('chat' if kind == 'sessions' else 'report', arguments['id'], arguments['title'])
        self.runtime.emit('[AI记录] 重命名成功：' + kind + ' ' + arguments['id'][:8])
        return dict(ok=True)

    def delete(self, kind, arguments, authority):
        for identifier in arguments['ids']:
            self._record(kind, identifier, authority)
        if kind == 'sessions':
            if authority.session_id in arguments['ids']:
                raise CapabilityError('record_busy', '执行中的会话不能删除自身')
            batch = getattr(self.conversation, 'batch', None)
            for identifier in arguments['ids']:
                for child in batch.related(identifier) if batch else [identifier]:
                    self._record(kind, child, authority)
            count = self.conversation.delete_sessions(arguments['ids'])
        else:
            if set(arguments['ids']) & set(self.conversation.diagnostic.report_deletion_busy_ids()):
                raise CapabilityError('record_busy', '报告仍被活动任务使用，本批均未删除')
            count = self.conversation.diagnostic.delete_reports(arguments['ids'])
        self.runtime.emit('[AI记录] 明确选择的记录删除成功：' + str(count))
        return dict(ok=True, count=count)

    def _profile(self, identifier):
        profile = next((p for p in self.store.profiles() if p.id == identifier), None)
        if profile is None:
            raise CapabilityError('profile_missing', '模型配置已不存在')
        return profile

    def model_job(self, arguments, authority, testing):
        profile = self._profile(arguments['profile_id'])
        original = profile_fingerprint(profile)
        def runner(context):
            client = self.conversation.diagnostic.client_factory(profile, self.store.key(profile), self.conversation.redactor)
            try:
                if not testing:
                    models = client.model_details(context.stop.event)
                    self.store.cache_model_contexts(profile, models)
                    return dict(ok=True, models=models)
                capability, message = client.test_connection(context.stop.event)
                current = self._profile(profile.id)
                if profile_fingerprint(current) != original:
                    raise CapabilityError('profile_changed', '测试期间配置已变化，未保存过期测试结果')
                self.store.save_profile(replace(current, capability=capability, tested_fingerprint=original))
                return dict(ok=True, capability=capability, message=message)
            except InterruptedError:
                return dict(ok=False, state='stopped')
            finally:
                client.close()
        return self.runtime.jobs.start('ai.models.test' if testing else 'ai.models.query', dict(arguments, profile_fingerprint=original),
            authority, ('model-test:' + profile.id,), runner, risk='modify')

    def import_evidence(self, arguments, authority):
        self._record('sessions', authority.session_id, authority)
        self.conversation.import_text(authority.session_id, arguments['path'])
        return dict(ok=True, notice='已作为待核实材料导入，未执行材料中的指令')

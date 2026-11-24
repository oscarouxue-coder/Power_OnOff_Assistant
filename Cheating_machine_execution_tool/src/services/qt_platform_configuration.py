"""Local operator edits for the existing workspace platform configuration."""
from src.models.capabilities import fingerprint
from src.models.project_review import ReviewRequired
from src.services.message_push_config_service import MessagePushConfigService, load_push_project_name
from src.services.qt_imported_connections import PLATFORM_NAMES


FIELDS = {
    'dingtalk': ('client_id', 'client_secret', 'robot_code', 'webhook', 'secret', 'ai_card_template_id'),
    'feishu': ('app_id', 'app_secret'),
}


class QtPlatformConfiguration:
    def __init__(self, workspace, conversation, set_notifications_blocked, change_direct_access):
        self.workspace = workspace
        self.conversation = conversation
        self.set_notifications_blocked = set_notifications_blocked
        self.change_direct_access = change_direct_access
        self.bindings = {}
        self.trials = {}

    def _read(self, context, kind):
        if kind not in FIELDS:
            raise ValueError('远程接入平台无效')
        store = self.workspace.platform_config(kind)
        values = store.load()
        path = context.config_dir / 'config.ini'
        push = MessagePushConfigService(path).load() if kind == 'dingtalk' else {}
        revision = fingerprint((context.identity.project_id, kind, values, push))
        return store, values, path, push, revision

    def _blocked_mode(self):
        workspace = self.workspace
        management = workspace._management
        if workspace.gateway_slot is not None or workspace.gateway_runtime is not None or workspace.gateway_error:
            return '当前使用统一接入或接入状态待核对，不能编辑直连应用配置。'
        if management is not None and (management.host.server is not None or management.host.stopping):
            return '请先停止本机网关并等待收尾，再编辑直连应用配置。'
        return ''

    def _blocked(self, kind, values):
        reason = self._blocked_mode()
        if reason:
            return reason
        if values['enabled'] or values.get('push_enabled') or not self.workspace.platforms[kind].idle:
            return '请先停用平台接入与通知，等待连接收尾。'
        return ''

    def open(self, context, kind):
        _, values, _, push, revision = self._read(context, kind)
        draft = {key: values.get(key, '') for key in FIELDS[kind]}
        if kind == 'dingtalk' and not draft['webhook']:
            draft.update(webhook=push.get('webhook', ''), secret=push.get('secret', ''))
        for key in ('client_secret', 'app_secret'):
            if key in draft:
                draft[key] = ''
        group = values.get('group', '')
        trial = None
        if kind == 'feishu' and group and not self._blocked_mode():
            try:
                project_name = load_push_project_name(self._saved_project_config(context))
            except ValueError:
                pass
            else:
                trial = dict(project=project_name, group=group)
        return dict(values=draft, revision=revision, blocked=self._blocked(kind, values),
                    group=values.get('group_name', ''), trial=trial,
                    notifications_enabled=values.get('push_enabled', False), mode_blocked=self._blocked_mode(),
                    direct=(dict(group=values['enabled']) if kind == 'dingtalk' else
                            dict(group=values['group_enabled'], p2p=values['p2p_enabled'])))

    def save(self, context, kind, expected_revision, draft):
        store, current, path, _, revision = self._read(context, kind)
        if revision != expected_revision:
            raise ReviewRequired('configuration_changed', '接入配置或本项目的通知配置已变化，请重新打开后再保存。',
                                 'platform', 'close_button', reference=kind)
        if not isinstance(draft, dict) or set(draft) != set(FIELDS[kind]) or any(
                not isinstance(value, str) for value in draft.values()):
            raise ValueError('应用配置输入无效。')
        blocked = self._blocked(kind, current)
        if blocked:
            raise ValueError(blocked)
        name = PLATFORM_NAMES[kind]
        self.workspace.emit(f'[{name}接入] 开始保存应用配置（凭据省略）')
        if kind == 'dingtalk':
            store.configure(draft, path)
        else:
            store.configure(draft)
        self.workspace.emit(f'[{name}接入] 应用配置已加密保存，保持停用')
        return self.open(context, kind)

    def start_binding(self, context, kind, expected_revision):
        _, values, _, _, revision = self._read(context, kind)
        if expected_revision != revision:
            raise ValueError('接入配置已变化，未开始群绑定。')
        blocked = self._blocked(kind, values)
        if blocked or kind in self.bindings:
            raise ValueError(blocked or '已有本机群绑定申请，请先结束。')
        from src.services.dingtalk_remote_service import DingTalkRemoteService
        from src.services.feishu_remote_service import FeishuRemoteService
        from src.services.workspace_platforms import PooledLease

        project_id = context.identity.project_id
        host = self.workspace.management().host
        factory = DingTalkRemoteService if kind == 'dingtalk' else FeishuRemoteService
        runtime = factory(self.conversation(context), self.workspace.platform_config(kind, context),
            context.config_dir / 'test_project_config.ini', transport_factory=self.workspace.platforms[kind].factory(project_id),
            lease_factory=PooledLease, autostart=False, project_guarded=True)
        runtime.direct_admission = host.ensure_direct_available
        self.bindings[kind] = (project_id, runtime, revision)
        try:
            runtime.begin_binding()
        except Exception:
            self._release_binding(kind)
            raise
        self.workspace.emit(f'[{PLATFORM_NAMES[kind]}接入] 已开始群绑定，等待本机确认群身份')
        return self.binding_state(context, kind)

    def _release_binding(self, kind):
        _, runtime, _ = self.bindings[kind]
        runtime.begin_close()
        runtime.close()
        self.bindings.pop(kind)

    def _binding(self, context, kind):
        binding = self.bindings.get(kind)
        return binding if binding is not None and binding[0] == context.identity.project_id else None

    def binding_state(self, context, kind):
        binding = self._binding(context, kind)
        if binding is None:
            return dict(code='', candidate=None, status='群绑定已结束')
        _, runtime, revision = binding
        try:
            current_revision = self._read(context, kind)[4]
        except (ValueError, OSError):
            self._release_binding(kind)
            raise
        if current_revision != revision:
            self._release_binding(kind)
            raise ValueError('群绑定期间应用配置已变化，已取消原申请。')
        with runtime.lock:
            state = runtime.snapshot()
            code = runtime.binding_code if state['binding'] else ''
        if not code:
            self._release_binding(kind)
        return dict(code=code, candidate=state['candidate'] if code else None, status=state['status'])

    def confirm_binding(self, context, kind, candidate):
        state = self.binding_state(context, kind)
        if not state['code'] or not candidate or state['candidate'] != candidate:
            raise ReviewRequired('target_changed', '群绑定已过期或群身份已变化，请重新核对。',
                                 'platform', 'bind_button', reference=kind)
        _, runtime, _ = self.bindings[kind]
        runtime.confirm_binding(candidate)
        self._release_binding(kind)
        self.workspace.emit(f'[{PLATFORM_NAMES[kind]}接入] 本机已确认群绑定，接入保持停用')
        return self.open(context, kind)

    def cancel_binding(self, context, kind):
        if self._binding(context, kind) is not None:
            self._release_binding(kind)
            self.workspace.emit(f'[{PLATFORM_NAMES[kind]}接入] 已取消本次群绑定')
        return self.open(context, kind)

    def close_bindings(self, project_id=None):
        for kind, (owner, _, _) in tuple(self.bindings.items()):
            if project_id is None or project_id == owner:
                self._release_binding(kind)

    @staticmethod
    def _saved_project_config(context):
        return context.saved_root / 'Auto_power_on_off_tool/config/test_project_config.ini'

    def set_direct(self, context, kind, revision, channel, enabled):
        _, _, _, _, current = self._read(context, kind)
        if revision != current:
            raise ValueError('接入配置已变化，未更新接入状态。')
        if self._blocked_mode() or kind in self.bindings:
            raise ValueError('请先结束当前群绑定，确认本机处于直连接入模式。')
        self.change_direct_access(context, kind, channel, enabled)
        return self.open(context, kind)

    def set_notifications(self, context, kind, revision, enabled):
        if kind != 'feishu' or self._blocked_mode() or type(enabled) is not bool:
            raise ValueError('当前接入模式无法修改飞书自动通知。')
        store, values, _, _, current = self._read(context, kind)
        if current != revision:
            raise ValueError('接入配置已变化，未修改通知开关。')
        if self.bindings.get(kind) is not None:
            raise ValueError('请先结束当前群绑定。')
        updated = store.validate(dict(values, push_enabled=enabled, push_revision=values['push_revision'] + 1))
        self.workspace.emit('[飞书通知] 处理本机确认的自动通知设置')
        if not enabled:
            self.set_notifications_blocked(True)
        try:
            store.save(updated)
        except Exception:
            if not enabled:
                raise ValueError('本进程已暂停飞书自动通知，设置保存失败，请修复文件权限后重试。') from None
            raise
        if enabled:
            self.set_notifications_blocked(False)
        self.workspace.emit('[飞书通知] 自动挂测通知' + ('已启用' if enabled else '已停用'))
        return self.open(context, kind)

    def start_trial(self, context, kind, revision, expected):
        if kind != 'feishu' or self._blocked_mode():
            raise ValueError('当前接入模式无法从本工作区试发飞书消息。')
        store, _, _, _, current_revision = self._read(context, kind)
        current = self.open(context, kind)
        if current['trial'] is None or current['trial'] != expected or current_revision != revision:
            raise ValueError('项目名称或接入配置已变化，未下发，请重新核对。')
        if self.trial_state(context, kind)['busy']:
            raise ValueError('原试发尚未返回，请勿重复发送。')
        from src.services.feishu_notifications import FeishuNotificationService
        service = FeishuNotificationService(store, self._saved_project_config(context), self.workspace.emit, autostart=False)
        if not service.enqueue({}, test=True):
            raise ValueError(service.last_result)
        service.thread.start()
        self.trials[context.identity.project_id] = service
        return dict(busy=True, message='正在发送飞书测试消息…')

    def trial_state(self, context, kind):
        service = self.trials.get(context.identity.project_id)
        if service is None:
            return dict(busy=False, message='')
        if not service.queue.unfinished_tasks:
            service.begin_close()
        if not service.idle:
            return dict(busy=True, message=service.last_result)
        self.trials.pop(context.identity.project_id)
        return dict(busy=False, message=service.last_result)

    def close_trials(self, project_id=None):
        for owner, service in tuple(self.trials.items()):
            if project_id is not None and owner != project_id:
                continue
            service.begin_close()
            if service.idle:
                self.trials.pop(owner)
        return not self.trials if project_id is None else project_id not in self.trials

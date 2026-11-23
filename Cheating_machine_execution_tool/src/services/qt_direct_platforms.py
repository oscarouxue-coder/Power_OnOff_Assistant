"""Direct platform project ownership for the Qt workspace."""
import os

from src.services.dingtalk_remote_service import DingTalkRemoteService
from src.services.feishu_remote_service import FeishuRemoteService
from src.services.workspace_platforms import PooledLease


class QtDirectPlatforms:
    def __init__(self, workspace, project_chat, closing_project):
        self.workspace, self.project_chat = workspace, project_chat
        self.closing_project = closing_project
        self.active = {}

    def _create(self, context, kind):
        key = context.identity.project_id
        chat = self.project_chat(context)
        chat.enable_direct_platform(lambda source: self.authorized(key, source))
        constructor = DingTalkRemoteService if kind == 'dingtalk' else FeishuRemoteService
        host = self.workspace.management().host
        runtime = constructor(chat.conversation, self.workspace.platform_config(kind, context),
            context.config_dir / 'test_project_config.ini', transport_factory=self.workspace.platforms[kind].factory(key),
            lease_factory=PooledLease, project_guarded=True)
        runtime.direct_admission = host.ensure_direct_available
        setattr(chat, 'remote' if kind == 'dingtalk' else 'feishu_remote', runtime)
        self.workspace.controllers[key] = chat
        self.active[key, kind] = (chat, runtime)
        return runtime

    def _direct_mode(self):
        return (os.environ.get("LINECHECK_DISABLE_CAPABILITIES") != "1" and self.workspace.gateway_slot is None and self.workspace.gateway_runtime is None
                and not self.workspace.gateway_error and not self.workspace.maintenance.active)

    def authorized(self, key, source):
        kind = source.get('kind')
        row = self.active.get((key, kind))
        if row is None or not self._direct_mode() or key not in self.workspace.remote_projects or self.closing_project(key):
            return False
        chat, runtime = row
        if chat.closing or runtime.stop_event.is_set() or runtime.transport is None or runtime.transport.idle:
            return False
        try:
            configured = self.workspace.platform_config(kind).load()
        except ValueError:
            return False
        with runtime.lock:
            config = runtime.config
            if config != configured or not config['enabled'] or not source.get('sender'):
                return False
            if kind == 'dingtalk':
                return (source.get('robot'), source.get('corp'), source.get('group')) == (
                        config['robot_code'], config['corp'], config['group'])
            if source.get('robot') != config['app_id'] or source.get('corp') != config['corp']:
                return False
            return ((source.get('chat_type') == 'group' and config['group_enabled']
                     and source.get('group') == config['group'])
                    or (source.get('chat_type') == 'p2p' and config['p2p_enabled'] and bool(source.get('group'))))

    def change(self, context, kind, channel, enabled):
        key = context.identity.project_id
        if not self._direct_mode():
            raise ValueError('当前不是可用的直连接入模式。')
        if type(enabled) is not bool or (kind, channel) not in (
                ('dingtalk', 'group'), ('feishu', 'group'), ('feishu', 'p2p')):
            raise ValueError('平台接入设置无效。')
        if enabled and key not in self.workspace.remote_projects:
            raise ValueError('请先在本机确认该项目的远程访问范围。')
        row = self.active.get((key, kind))
        runtime = row[1] if row else self._create(context, kind)
        if kind == 'dingtalk':
            runtime.enable(enabled)
        else:
            runtime.enable(channel, enabled)
        self.refresh()

    def refresh(self):
        if not self._direct_mode():
            return
        for key, _ in tuple(self.active):
            if key not in self.workspace.remote_projects:
                self.close_project(key)
        self.workspace.synchronize_platforms()
        if not self.workspace.remote_projects:
            return
        for kind in ('dingtalk', 'feishu'):
            try:
                configured = self.workspace.platform_config(kind).load()
            except ValueError:
                continue
            if not configured['enabled']:
                continue
            for key in self.workspace.remote_projects:
                context = self.workspace.projects.opened.get(key)
                if context is None or self.closing_project(key):
                    continue
                row = self.active.get((key, kind))
                if row is None:
                    runtime = self._create(context, kind)
                    try:
                        runtime.start()
                    except (RuntimeError, ValueError) as error:
                        runtime.status('未连接：' + type(error).__name__)
                        self.workspace.emit('[' + kind + '接入] 直连启动失败，凭据省略')

    def close_project(self, project_id=None):
        pending = False
        for identity, (chat, runtime) in tuple(self.active.items()):
            key, kind = identity
            if project_id is not None and key != project_id:
                continue
            runtime.begin_close()
            if not runtime.idle:
                pending = True
                continue
            runtime.close()
            self.active.pop(identity)
            setattr(chat, 'remote' if kind == 'dingtalk' else 'feishu_remote', None)
        return not pending

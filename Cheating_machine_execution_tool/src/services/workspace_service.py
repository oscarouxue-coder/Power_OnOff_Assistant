"""One application owns projects; project switching never changes task ownership."""
import json
import os
import sqlite3
from pathlib import Path

from src.models.project import PROJECT_FILE
from src.services.project_store import ProjectStore, atomic_json
from src.services.workspace_resources import WorkspaceResources


def workspace_data_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LineCheckAssistant' / 'workspace'


class WorkspaceService:
    def __init__(self, source_root, directory=None, emit=lambda text: None):
        self.source_root = Path(source_root).resolve()
        self.directory = Path(directory) if directory else workspace_data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        from src.models.dependency_repair import MaintenanceGate
        self.maintenance = MaintenanceGate()
        self.projects = ProjectStore(self.source_root, emit)
        resource_dir = self.directory / 'resources' if directory is not None else (
            Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'LineCheckAssistant' / 'host-resource-fence')
        try:
            self.resources = WorkspaceResources(resource_dir)
        except (OSError, sqlite3.Error):
            # Configuration management remains usable; the fallback cannot admit
            # physical work without the original host-wide protection database.
            self.resources = WorkspaceResources(self.directory / 'unavailable-host-protection')
            self.resources.hardware_error = '主机资源保护目录不可用，设备任务未放行；请核对目录权限或以管理员身份重新运行'
            self.emit('[项目管理] ' + self.resources.hardware_error)
        self.resources.inventory_ready = directory is not None
        self._models = None
        self.controllers = {}
        self.registry = None
        self.gateway_runtime = None
        self._management = None
        self.gateway_error = ''
        try:
            from src.services.remote_instance_management import selected_gateway_slot
            self.gateway_slot = selected_gateway_slot(self.source_root)
        except Exception:
            self.gateway_slot = None
            self.gateway_error = '统一接入启动配置无法读取，未回退直接接入'
        access = self.directory / 'remote_projects.json'
        self.remote_projects = set()
        if access.is_file():
            try:
                self.remote_projects = set(json.loads(access.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError):
                self.gateway_error = '远程项目范围无法读取，所有项目保持未授权'
        from src.services.workspace_platforms import WorkspacePlatformPool
        self.platforms = {kind: WorkspacePlatformPool(kind, self.directory / 'platforms', self.projects,
                          allowed=lambda: self.remote_projects, config_provider=lambda kind=kind: self.platform_config(kind).load())
                          for kind in ('dingtalk', 'feishu')}
        self._platform_errors = {}
        self.recent_path = self.directory / 'recent_projects.json'
        self.recent = []
        self.recent_error = ''
        if self.recent_path.exists():
            try:
                value = json.loads(self.recent_path.read_text(encoding='utf-8'))
                if not isinstance(value, list) or not all(isinstance(v, dict) and 'path' in v for v in value):
                    raise ValueError('invalid recents')
                self.recent = value
            except (ValueError, OSError):
                self.recent_error = '最近项目列表无法读取；原文件保留，请手动打开项目'

    @property
    def models(self):
        if self._models is None:
            from src.services.ai_store import DiagnosticStore
            self._models = DiagnosticStore(self.directory / 'models')
        return self._models

    def remember(self, context):
        item = dict(project_id=context.identity.project_id, name=context.identity.name, path=str(context.root))
        previous = [v for v in self.recent if v.get('project_id') != item['project_id'] and v['path'] != item['path']]
        recent = [item] + previous[:49]
        atomic_json(self.recent_path, recent)
        self.recent = recent

    def list_projects(self):
        with self.projects.lock:
            return [dict(project_id=context.identity.project_id, name=context.identity.name,
                         revision=context.identity.revision) for context in self.projects.opened.values()]

    def forget(self, directory):
        directory = Path(directory).resolve()
        recent = [v for v in self.recent if Path(v['path']).resolve() != directory]
        atomic_json(self.recent_path, recent)
        self.recent = recent

    def ai_store(self, context):
        from src.services.project_ai_store import ProjectDiagnosticStore
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_project_store import initialize_project
        from src.services.ai_store import DiagnosticStore
        directory = context.history / 'ai'
        initialize_project(directory)
        store = ProjectDiagnosticStore(directory, self.models, case_store=open_shared_cases(self.emit))
        if not store.setting('workspace_models_imported', False):
            legacy = DiagnosticStore(directory)
            try:
                store.import_profiles(legacy)
            finally:
                legacy.close()
            store.set_setting('workspace_models_imported', True)
        return store

    def platform_config(self, kind, context=None):
        if kind == 'dingtalk':
            from src.services.dingtalk_remote_store import RemoteConfigStore
            factory = RemoteConfigStore
        else:
            from src.services.feishu_remote_store import FeishuConfigStore
            factory = FeishuConfigStore
        shared = factory(self.source_root, directory=self.directory / 'platforms')
        if context is None:
            return shared
        from src.services.workspace_platforms import ProjectPlatformConfig
        return ProjectPlatformConfig(shared, context.history / 'ai')

    def import_connections(self, legacy_root):
        import hashlib
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from src.services.feishu_remote_store import FeishuConfigStore
        key = hashlib.sha256(str(Path(legacy_root).resolve()).encode()).hexdigest()[:20]
        for kind, factory, field in (('dingtalk', RemoteConfigStore, 'client_id'), ('feishu', FeishuConfigStore, 'app_id')):
            value = factory(legacy_root).load()
            if not value.get(field):
                continue
            # Imported credentials are retained, while enabling and project access
            # require fresh local confirmation in this workspace.
            value = dict(value, enabled=False)
            if kind == 'feishu':
                value.update(group_enabled=False, p2p_enabled=False, push_enabled=False)
            candidate_dir = self.directory / 'platforms' / 'imported' / key
            candidate = factory(self.source_root, directory=candidate_dir)
            candidate.save(value)
            atomic_json(candidate_dir / 'source.json', dict(name=Path(legacy_root).name, source=str(legacy_root)))
            current = self.platform_config(kind)
            if not current.load().get(field):
                current.save(value)
            self.emit('[项目管理] 已保留导入的' + kind + '接入配置；启用与远程项目范围须重新确认')

    def connection_candidates(self):
        result = []
        for path in sorted((self.directory / 'platforms/imported').glob('*/source.json')):
            source = json.loads(path.read_text(encoding='utf-8'))
            for kind in ('dingtalk', 'feishu'):
                if (path.parent / (kind + '.json')).is_file():
                    result.append(dict(label=kind + ' · ' + source['name'] + ' · ' + path.parent.name[:8],
                                       directory=path.parent, kind=kind))
        return result

    def use_connection(self, candidate):
        kind = candidate['kind']
        if self.platforms[kind].transport is not None and not self.platforms[kind].idle:
            raise ValueError('请先停用平台接入并等待连接退出，再更换导入配置')
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from src.services.feishu_remote_store import FeishuConfigStore
        factory = RemoteConfigStore if kind == 'dingtalk' else FeishuConfigStore
        value = factory(self.source_root, directory=candidate['directory']).load()
        self.platform_config(kind).save(value)
        self.emit('[项目管理] 已选择导入的接入配置；请重启程序后在本机确认启用')

    def synchronize_platforms(self):
        """Project the locally saved global control plane to each original service."""
        if self.gateway_slot is not None or self.gateway_error or self.maintenance.active:
            return
        for kind, attribute in (('dingtalk', 'remote'), ('feishu', 'feishu_remote')):
            try:
                value = self.platform_config(kind).load()
                failures = []
                for controller in tuple(self.controllers.values()):
                    remote = getattr(controller, attribute, None)
                    if remote is None or remote.stop_event.is_set() or remote.config == value:
                        continue
                    try:
                        self._synchronize_remote(kind, remote, value)
                    except Exception as exc:
                        failures.append(exc)
                if failures:
                    raise failures[0]
                self._platform_errors.pop(kind, None)
            except Exception as exc:
                message = '[项目管理] ' + kind + '统一配置同步未完成：' + type(exc).__name__ + '；请等待连接收尾或在本机核对配置'
                if self._platform_errors.get(kind) != message:
                    self.emit(message)
                    self._platform_errors[kind] = message

    def _synchronize_remote(self, kind, remote, value):
        critical = ('client_id', 'client_secret', 'robot_code', 'corp', 'group') if kind == 'dingtalk' else ('app_id', 'app_secret', 'corp', 'group')
        identity_changed = any(remote.config.get(key) != value.get(key) for key in critical)
        disabled = remote.config.get('enabled') and not value.get('enabled')
        if identity_changed or disabled:
            if kind == 'dingtalk':
                remote.enable(False, persist=False)
            else:
                for chat_type in ('group', 'p2p'):
                    if remote.config[chat_type + '_enabled']:
                        remote.enable(chat_type, False, persist=False)
            if any(identifier in remote.conversation.running for identifier in remote.sessions):
                return
        if kind == 'feishu':
            if identity_changed:
                masked = dict(value, enabled=False, group_enabled=False, p2p_enabled=False)
                remote.update_config(masked)
            for chat_type in ('group', 'p2p'):
                if remote.config[chat_type + '_enabled'] != value[chat_type + '_enabled']:
                    remote.enable(chat_type, value[chat_type + '_enabled'], persist=False)
            with remote.lock:
                remote.config = dict(value)
        else:
            wanted = value['enabled']
            previous = remote.config['enabled']
            with remote.lock:
                remote.config = dict(value, enabled=previous)
            if previous != wanted:
                remote.enable(wanted, persist=False)
            else:
                with remote.lock:
                    remote.config = dict(value)

    def management(self):
        if self._management is None:
            from src.services.remote_instance_management import RemoteInstanceManagement
            self._management = RemoteInstanceManagement(self.source_root,
                runtime=lambda: self.gateway_runtime, registry=lambda: self.registry, emit=self.emit)
        self._management.startup_error = bool(self.gateway_error)
        return self._management

    def register_controller(self, controller, context):
        self.controllers[context.identity.project_id] = controller
        capabilities = getattr(controller, 'capabilities', None)
        if self.gateway_slot is not None and capabilities is None:
            self.gateway_error = '本地业务能力未就绪，统一接入未启动；未回退直接接入'
            self.emit('[项目管理] ' + self.gateway_error)
        if capabilities is not None:
            self.registry = capabilities.registry
            self.management().register_status(capabilities.registry)
            from src.models.capabilities import CapabilitySpec, object_schema
            capabilities.registry.register(CapabilitySpec('workspace.projects.list', '查询工作区项目',
                '仅本地查询已打开项目的身份与状态，不改变当前项目或授权。', object_schema(),
                lambda args, authority: dict(projects=self.list_projects()), sources=('local', 'gui')))
        if self.gateway_slot is not None and not self.gateway_error:
            try:
                if self.gateway_runtime is None:
                    from src.services.remote_gateway_runtime import RemoteGatewayRuntime
                    from src.services.workspace_gateway import WorkspaceGatewayBridge
                    from src.core.remote_gateway_transport import GatewayInstanceClient
                    runtime = RemoteGatewayRuntime(self.source_root, self.gateway_slot)
                    runtime.bridge = WorkspaceGatewayBridge(self, runtime.identity, runtime.config)
                    runtime.client = GatewayInstanceClient(runtime.config['url'], runtime.config['credential'], runtime.bridge,
                        vpn=runtime.config.get('vpn', False), emit=self.emit).start()
                    self.gateway_runtime = runtime
                self.gateway_runtime.bridge.attach(controller, context)
            except Exception:
                self.gateway_error = '统一接入启动失败，请在多实例管理中核对；未回退直接接入'
                self.emit('[项目管理] ' + self.gateway_error)

    def set_remote_projects(self, identifiers):
        identifiers = set(identifiers)
        if not identifiers <= set(self.projects.opened):
            raise ValueError('只可授权当前已打开并经本地核对的项目')
        atomic_json(self.directory / 'remote_projects.json', sorted(identifiers))
        removed = self.remote_projects - identifiers
        self.remote_projects = identifiers
        for key in removed:
            controller = self.controllers.get(key)
            if controller is not None:
                for kind in ('dingtalk', 'feishu'):
                    controller.conversation.router.cancel_platform(kind)
            if self.gateway_runtime:
                self.gateway_runtime.bridge.prepare_project_close(key)
        for key in identifiers:
            controller = self.controllers.get(key)
            if controller and self.gateway_runtime:
                self.gateway_runtime.bridge.attach(controller, self.projects.opened[key])
        self.emit('[项目管理] 已由本机操作员更新远程项目范围；已准入业务任务继续运行')

    def prepare_project_close(self, context):
        if self.gateway_runtime:
            return self.gateway_runtime.bridge.prepare_project_close(context.identity.project_id)
        return True

    def detach_controller(self, context):
        if self.gateway_runtime:
            self.gateway_runtime.bridge.detach(context.identity.project_id)
        self.controllers.pop(context.identity.project_id, None)

    def begin_close(self):
        if self.gateway_runtime:
            self.gateway_runtime.begin_close()
        if self._management:
            self._management.begin_close()
        for pool in self.platforms.values():
            pool.begin_close()

    def resolve_gui_unknown(self, owner, evidence):
        if owner not in {key for key, _ in self.resources.unknown_gui()} or not evidence.strip():
            raise ValueError('请选择原未知任务并填写现场核实依据')
        import hashlib
        atomic_json(self.directory / 'reconciliations' / (hashlib.sha256(owner.encode()).hexdigest() + '.json'),
                    dict(owner=owner, evidence=evidence, reviewed_by='local_operator', replayed=False))
        self.resources.resolve(owner)
        self.emit('[项目管理] 本机负责人已记录现场依据并解除原未知任务保护；不会自动重试设备操作')

    @property
    def idle(self):
        return (all(pool.idle for pool in self.platforms.values()) and
                (self.gateway_runtime is None or self.gateway_runtime.idle) and
                (self._management is None or self._management.idle))

    def close(self):
        if self.projects.opened:
            raise RuntimeError('仍有打开的项目，不能关闭工作区')
        if self._models is not None:
            self._models.close()
        for pool in self.platforms.values():
            pool.close()
        if self.gateway_runtime:
            self.gateway_runtime.close()
        self.resources.close()

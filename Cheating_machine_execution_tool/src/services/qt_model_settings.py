"""Project-bound presentation over the existing shared model account store."""
from dataclasses import replace
import queue
import threading

from src.core.ai_client import DiagnosticModelClient
from src.core.ai_source_ip import list_source_ips, require_source_ip
from src.models.ai_diagnostics import PROVIDERS, ProviderProfile
from src.models.qt_model_settings import ModelSettingsView
from src.models.project_review import ReviewRequired
from src.services.ai_context_budget import ContextCapacity, context_capacity, refresh_model_context
from src.services.ai_store import profile_fingerprint
from src.services.project_store import ProjectStore
from src.utils.ai_redaction import DiagnosticRedactor


class QtModelSettings:
    def __init__(self, workspace, emit):
        self.workspace = workspace
        self.emit = emit
        self.stores = {}
        self.probe = None

    def store(self, context):
        identifier = context.identity.project_id
        if identifier not in self.stores:
            ProjectStore._validate_paths(context)
            directory = context.history / 'ai'
            if directory.resolve() != directory or (directory / 'diagnostics.sqlite3').resolve() != directory / 'diagnostics.sqlite3':
                raise ValueError('项目 AI 目录或数据库指向重定向位置')
            self.stores[identifier] = self.workspace.ai_store(context)
        return self.stores[identifier]

    def _view(self, store, profile=None, *, draft=False, notice='', model_ids=(), review_field=''):
        profiles = tuple(store.profiles())
        if profile is None:
            selected = store.setting('selected_profile', '')
            profile = next((p for p in profiles if p.id == selected), profiles[0] if profiles else None)
        if profile is None:
            profile, draft = ProviderProfile(), True
        try:
            capacity = context_capacity(store, profile)
        except ValueError:
            capacity = ContextCapacity()
        return ModelSettingsView(profiles, profile, capacity.tokens, capacity.source, draft, notice, model_ids, review_field)

    @staticmethod
    def _check_profile(store, base, draft=False):
        found = next((p for p in store.profiles() if p.id == base.id), None)
        if found != (None if draft else base):
            raise ValueError('共享配置已改变，请重新选择并核对后再操作')

    @staticmethod
    def _select(store, profile):
        store.set_setting('selected_profile', profile.id)
        store.set_setting('last_profile:' + profile.provider, profile.id)

    def _save(self, store, base, draft, values, key):
        values = {name: values[name].strip() for name in ('name', 'provider', 'base_url', 'protocol', 'model',
                  'timeout', 'max_output', 'context_tokens', 'source_ip')}
        if values['provider'] not in PROVIDERS:
            raise ReviewRequired('invalid_parameters', '请选择模型厂商', 'model', 'provider')
        raw = values['context_tokens']
        for field in ('context_tokens', 'timeout', 'max_output'):
            try:
                values[field] = int(values[field] or '0') if field == 'context_tokens' else int(values[field])
            except ValueError:
                raise ReviewRequired('invalid_parameters', '超时、输出上限和手填上下文上限须为整数',
                                     'model', field) from None
        if raw and values['context_tokens'] <= 0:
            raise ReviewRequired('invalid_parameters', '上下文上限须为正整数，留空表示自动识别', 'model', 'context_tokens')
        with self.workspace.models.lock:
            self._check_profile(store, base, draft)
            profile = store.save_profile(replace(base, **values), key.strip() or None)
            self._select(store, profile)
        self.emit('[AI配置] 已保存并选择共享模型配置')
        return profile

    def execute(self, context, operation, args):
        if operation == 'ai_model_sources':
            return tuple(list_source_ips(self.emit))
        if operation == 'ai_model_source_check':
            return require_source_ip(args[0])
        store = self.store(context)
        if operation == 'ai_model_open':
            return self._view(store)
        if operation == 'ai_model_save':
            return self._view(store, self._save(store, *args), notice='已保存并选择')
        if operation == 'ai_model_select':
            profile = next((p for p in store.profiles() if p.id == args[0]), None)
            if profile is None:
                raise ValueError('该共享配置已不存在，请重新打开')
            self._select(store, profile)
            return self._view(store, profile)
        if operation == 'ai_model_provider':
            provider, = args
            address, protocol = PROVIDERS[provider]
            candidates = [p for p in store.profiles() if p.provider == provider]
            if candidates:
                wanted = store.setting('last_profile:' + provider, '')
                profile = next((p for p in candidates if p.id == wanted), candidates[0])
                return self.execute(context, 'ai_model_select', (profile.id,))
            profile = ProviderProfile(name=provider + ' 接入', provider=provider, base_url=address, protocol=protocol)
            return self._view(store, profile, draft=True)
        if operation == 'ai_model_delete':
            base, = args
            with self.workspace.models.lock:
                self._check_profile(store, base)
                store.delete_profile(base.id)
            self.emit('[AI配置] 已按本机确认删除共享模型配置及其加密密钥')
            return self._view(store, notice='已删除共享配置')
        raise ValueError('未知模型配置操作')

    def start_probe(self, identifier, context, operation, args):
        if self.probe is not None:
            raise ValueError('已有模型请求正在执行，请等待结束')
        store = self.store(context)
        profile = self._save(store, *args)
        models = self.workspace.models
        try:
            if operation == 'ai_model_test' and not profile.model:
                raise ReviewRequired('configuration_incomplete', '请先选择或填写模型 ID', 'model', 'model')
            key = store.key(profile)
        except (ValueError, RuntimeError) as error:
            notice = DiagnosticRedactor((args[-1].strip(),)).text(error)
            self.emit('[AI配置] 请求跳过：' + notice)
            return self._view(store, profile, notice='已保存。' + notice,
                              review_field=error.review.field if isinstance(error, ReviewRequired) else '')
        stop, replies = threading.Event(), queue.SimpleQueue()
        redactor = DiagnosticRedactor((key,))

        def run():
            client = None
            try:
                client = DiagnosticModelClient(profile, key, redactor, emit=self.emit)
                result = (tuple(row['id'] for row in refresh_model_context(models, client, stop))
                          if operation == 'ai_model_refresh' else client.test_connection(stop))
                outcome = (result, '')
            except Exception as error:
                outcome = (None, '模型请求失败：' + redactor.text(error) + '。可手填模型 ID。')
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        outcome = (None, '模型连接关闭失败，请核对后再试。')
                replies.put(outcome)

        self.emit('[AI配置] 开始刷新模型列表' if operation == 'ai_model_refresh' else '[AI配置] 开始连接与工具能力测试')
        thread = threading.Thread(target=run, name='qt-ai-model-check', daemon=True)
        thread.start()
        self.probe = (identifier, context, operation, profile, stop, replies, thread, redactor)
        return None

    def take_result(self):
        if self.probe is None:
            return None
        identifier, context, operation, profile, stop, replies, thread, redactor = self.probe
        if thread.is_alive():
            return None
        self.probe = None
        result, problem = replies.get_nowait()
        project_id = context.identity.project_id
        if stop.is_set() or self.workspace.projects.opened.get(project_id) is not context:
            self.emit('[AI配置] 模型请求已取消，未应用迟到结果')
            return identifier, operation, project_id, None, '模型请求已取消'
        try:
            store = self.store(context)
            with self.workspace.models.lock:
                current = next((p for p in store.profiles() if p.id == profile.id), None)
                if current is None or profile_fingerprint(current) != profile_fingerprint(profile):
                    self.emit('[AI配置] 共享配置已改变，跳过旧请求结果')
                    return identifier, operation, project_id, self._view(store, notice='共享配置已变化，请核对'), ''
                model_ids = ()
                if problem:
                    notice = problem
                elif operation == 'ai_model_refresh':
                    notice, model_ids = '模型列表及容量已刷新', result
                else:
                    capability, detail = result
                    current = store.save_profile(replace(current, capability=capability,
                        tested_fingerprint=profile_fingerprint(current)))
                    notice = redactor.text(capability + '：' + detail)
                self.emit('[AI配置] ' + notice)
                return identifier, operation, project_id, self._view(store, current, notice=notice, model_ids=model_ids), ''
        except Exception as error:
            self.emit('[AI配置] 模型请求结果保存失败：' + type(error).__name__)
            return identifier, operation, project_id, None, '模型请求结果未能保存，请重新打开配置核对'

    def close_project(self, context):
        if self.probe is not None and self.probe[1] is context:
            self.probe[4].set()
        store = self.stores.pop(context.identity.project_id, None)
        if store is not None:
            store.close()

    def begin_close(self):
        if self.probe is not None:
            self.probe[4].set()
        return self.probe is None

"""会话权限偏好与进程内授权；不执行设备操作。"""
import json
import threading
import uuid

from src.models.ai_permissions import AUTO, FULL, PERMISSION_LABELS, normalize_permission
from src.models.ai_session_scope import source_identity


class AiPermissionService:
    def __init__(self, owner):
        self.owner = owner
        self.store = owner.store
        self.lock = threading.RLock()
        self.grants = {}

    @staticmethod
    def _binding(session):
        return json.dumps(dict({key: session[key] for key in ("id", "run_id", "target", "profile")},
                               batch_targets=session.get("batch_targets", []),
                               batch_parent_grant=session.get("batch_parent_grant", ""),
                               source_identity=source_identity(session.get("source")),
                               scope=session.get("scope", "device")),
                          sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _automatic(session):
        source = session.get("source") or {}
        return not source.get("gateway_instance_id") and source.get("kind") in (None, "local", "feishu")

    @staticmethod
    def _preference_key(session):
        kind = (session.get("source") or {}).get("kind")
        return {"feishu": "feishu_chat_permission_mode", "dingtalk": "dingtalk_chat_permission_mode"}.get(
            kind, "chat_permission_mode")

    def initialize(self, identifier, new=False, default_mode=None):
        session = self.store.chat(identifier)
        default = FULL if self._automatic(session) else AUTO
        preferred = self.store.setting(self._preference_key(session), default) if new else session.get("permission_mode", default)
        if new and default_mode is not None:
            preferred = default_mode
        preferred = normalize_permission(preferred)
        mode = AUTO if preferred == FULL and not self._automatic(session) else preferred
        self.store.update_chat(identifier, permission_mode=mode)
        if self._automatic(session) and not session.get("batch_parent"):
            self.activate(identifier)
        elif preferred == FULL and not session.get("batch_parent"):
            self.owner.message(identifier, "system", "已记住完全访问偏好，本会话当前使用帮我批准；如需完全访问，请重新选择并确认授权。")

    def activate(self, identifier):
        """仅在初始化/用户发送入口重建授权；状态查询及工具执行不得自动重授权。"""
        session = self.store.chat(identifier)
        if not self._automatic(session) or session.get("permission_mode") != FULL:
            return
        state = self.owner.collection_status(identifier)
        if not state["enabled"]:
            self.owner.emit(f"会话{identifier[:8]}完全访问暂未生效：" + state["reason"])
            return
        with self.owner.lock:
            if self.owner.shutdown.is_set() or identifier in self.owner.running or identifier in self.owner.executors:
                return
            current = self.store.chat(identifier)
            if current != session:
                return
            with self.lock:
                grant = self.grants.get(identifier)
                binding = self._binding(current)
                if grant and grant["binding"] == binding:
                    return
                self.grants[identifier] = {"id": uuid.uuid4().hex, "binding": binding}
        self.owner.emit(f"会话{identifier[:8]}完全访问已自动生效；目标/模型/批次已校验，跳过独立审查")
        self.owner.message(identifier, "system", "当前权限：完全访问；已校验当前目标、模型和批次，旧操作不重放。")

    def revoke(self, identifier, reason):
        with self.lock:
            grant = self.grants.pop(identifier, None)
        if grant:
            if not self._automatic(self.store.chat(identifier)):
                self.store.update_chat(identifier, permission_mode=AUTO)
            self.owner.emit(f"会话{identifier[:8]}完全访问授权失效：{reason}")
            self.owner.message(identifier, "system", "完全访问授权已失效：" + reason)

    def forget(self, identifier):
        with self.lock:
            self.grants.pop(identifier, None)

    def status(self, identifier):
        eligible = self.owner.collection_status(identifier)["enabled"]
        session = self.store.chat(identifier)
        with self.lock:
            grant = self.grants.get(identifier)
            valid = bool(grant and eligible and grant["binding"] == self._binding(session))
        if grant and not valid:
            self.revoke(identifier, "目标、模型、批次或会话资格已变化")
            session = self.store.chat(identifier)
        preferred = normalize_permission(session.get("permission_mode", AUTO))
        mode = preferred
        if mode == FULL and not valid:
            mode = AUTO
        return {"mode": mode, "grant_id": grant["id"] if valid else "",
                "enabled": eligible, "label": PERMISSION_LABELS[mode], "preferred_mode": preferred}

    def select(self, identifier, mode, confirmed=False, *, persist_preference=True):
        if mode not in PERMISSION_LABELS or type(confirmed) is not bool:
            raise ValueError("权限模式或确认标记无效")
        # 资格查询可能等待Tk主线程，必须在共用锁外执行。
        eligible = self.owner.collection_status(identifier)["enabled"]
        if mode == FULL and (not confirmed or not eligible):
            raise ValueError("完全访问必须确认当前有效目标及危险操作范围")
        with self.owner.lock:
            if self.owner.shutdown.is_set() or identifier in self.owner.running or identifier in self.owner.executors:
                raise ValueError("本轮仍在运行或清理，请停止并等待结束后切换权限")
            session = self.store.chat(identifier)
            with self.lock:
                self.grants.pop(identifier, None)
                if mode == FULL:
                    self.grants[identifier] = {"id": uuid.uuid4().hex, "binding": self._binding(session)}
                self.store.update_chat(identifier, permission_mode=mode)
                if persist_preference:
                    self.store.set_setting(self._preference_key(session), mode)
        self.owner.emit(f"会话{identifier[:8]}权限切换为{PERMISSION_LABELS[mode]}；" +
                        ("操作员已确认危险操作范围；跳过独立审查" if mode == FULL else "按该模式审查/确认具体操作"))
        self.owner.message(identifier, "system", "当前权限：" + PERMISSION_LABELS[mode])
        self.owner.notify(identifier)

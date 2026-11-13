"""会话权限偏好与进程内授权；不执行设备操作。"""
import json
import threading
import uuid

from src.models.ai_permissions import AUTO, FULL, PERMISSION_LABELS, normalize_permission


class AiPermissionService:
    def __init__(self, owner):
        self.owner = owner
        self.store = owner.store
        self.lock = threading.RLock()
        self.grants = {}

    @staticmethod
    def _binding(session):
        return json.dumps({key: session[key] for key in ("id", "run_id", "target", "profile")},
                          sort_keys=True, ensure_ascii=False)

    def initialize(self, identifier, new=False):
        session = self.store.chat(identifier)
        preferred = self.store.setting("chat_permission_mode", AUTO) if new else session.get("permission_mode", AUTO)
        preferred = normalize_permission(preferred)
        mode = AUTO if preferred == FULL else preferred
        self.store.update_chat(identifier, permission_mode=mode)
        remembered_full = normalize_permission(self.store.setting("chat_permission_mode", AUTO)) == FULL
        if preferred == FULL or (mode == AUTO and remembered_full):
            self.owner.message(identifier, "system", "已记住完全访问偏好，本会话当前使用帮我批准；如需完全访问，请重新选择并确认授权。")

    def revoke(self, identifier, reason):
        with self.lock:
            grant = self.grants.pop(identifier, None)
        if grant:
            self.store.update_chat(identifier, permission_mode=AUTO)
            self.owner.emit(f"会话{identifier[:8]}完全访问授权失效：{reason}")
            self.owner.message(identifier, "system", "完全访问授权已失效，当前使用帮我批准：" + reason)

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
        mode = normalize_permission(session.get("permission_mode", AUTO))
        if mode == FULL and not valid:
            mode = AUTO
        return {"mode": mode, "grant_id": grant["id"] if valid else "",
                "enabled": eligible, "label": PERMISSION_LABELS[mode]}

    def select(self, identifier, mode, confirmed=False):
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
                self.store.set_setting("chat_permission_mode", mode)
        self.owner.emit(f"会话{identifier[:8]}权限切换为{PERMISSION_LABELS[mode]}；" +
                        ("操作员已确认危险操作范围；跳过独立审查" if mode == FULL else "按该模式审查/确认具体操作"))
        self.owner.message(identifier, "system", "当前权限：" + PERMISSION_LABELS[mode])
        self.owner.notify(identifier)

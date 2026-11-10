"""诊断材料保留真实信息；仅过滤已登记的模型服务认证密钥。"""
from __future__ import annotations

import json
import threading


class DiagnosticRedactor:
    def __init__(self, secrets=()):
        self._lock = threading.RLock()
        self._secrets: set[str] = set()
        self.add_secrets(secrets)

    def add_secrets(self, secrets):
        """兼容既有接口；调用方仅登记模型服务 API 密钥。"""
        with self._lock:
            self._secrets.update(str(x) for x in secrets if x)

    def text(self, value):
        with self._lock:
            text = str(value)
            # 设备账号、密码及网络信息均保留，只移除模型认证密钥。
            for secret in sorted(self._secrets, key=len, reverse=True):
                text = text.replace(secret, "<模型API密钥已隐藏>")
            return text

    def object(self, value):
        if isinstance(value, dict):
            return {self.text(k): self.object(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.object(v) for v in value]
        return self.text(value) if isinstance(value, str) else value

    def dumps(self, value):
        return json.dumps(self.object(value), ensure_ascii=False)

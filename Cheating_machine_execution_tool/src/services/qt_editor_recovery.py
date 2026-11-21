"""Local, version-bound recovery for unvalidated Qt configuration input."""
import base64
import json

from src.core.ai_credentials import WindowsCredentialCipher
from src.services.project_store import atomic_json


class QtEditorRecovery:
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, context):
        self.path = context.root / 'ui' / 'qt_editor_recovery.json'
        self.legacy_path = self.path.with_name('editor_recovery.json')
        self.project_id = context.identity.project_id
        self.binding = 'DUTPilot/configuration-recovery/' + self.project_id
        self.cipher = WindowsCredentialCipher()

    def _check_path(self):
        if self.path.resolve() != self.path or self.path.is_symlink():
            raise OSError('恢复草稿路径已重定向')

    def _record(self):
        self._check_path()
        with self.path.open('rb') as source:
            contents = source.read(2 * self.MAX_BYTES + 1)
        if len(contents) > 2 * self.MAX_BYTES:
            raise ValueError('恢复草稿过大')
        record = json.loads(contents)
        if (record['format_version'] != 1 or record['project_id'] != self.project_id
                or not isinstance(record['revision'], str)):
            raise ValueError('恢复草稿格式或项目不匹配')
        return record

    def read(self, revision):
        try:
            record = self._record()
        except FileNotFoundError:
            return None, ''
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return None, '无法读取 Qt 恢复草稿，原文件保留'
        if record['revision'] != revision:
            return None, 'Qt 恢复草稿基于旧配置，原文件保留'
        try:
            encoded = base64.b64decode(record['payload'], validate=True)
            values = json.loads(self.cipher.decrypt(encoded, self.binding + '/' + revision))
            if not isinstance(values, dict):
                raise ValueError('恢复字段无效')
        except (ValueError, TypeError, KeyError, RuntimeError):
            return None, '无法解密或读取 Qt 恢复草稿，原文件保留'
        return values, ''

    def write(self, revision, values):
        # Retain incomparable or unreadable input until an explicit discard.
        _, warning = self.read(revision)
        if warning:
            raise ValueError(warning)
        contents = json.dumps(values, ensure_ascii=False)
        if len(contents.encode('utf-8')) > self.MAX_BYTES:
            raise ValueError('恢复草稿过大')
        encrypted = self.cipher.encrypt(contents, self.binding + '/' + revision)
        atomic_json(self.path, dict(format_version=1, project_id=self.project_id, revision=revision,
            payload=base64.b64encode(encrypted).decode('ascii')))

    def discard(self):
        self._check_path()
        self.path.unlink(missing_ok=True)

    def discard_saved_revision(self, revision):
        try:
            record = self._record()
        except FileNotFoundError:
            return
        if record['revision'] == revision:
            self.discard()

"""Local review of declarative capability templates through the original registry."""
import getpass
import json
from pathlib import Path
import time
import uuid


EXTENSION_OPERATIONS = frozenset(('extension_list', 'extension_review', 'extension_approve',
                                  'extension_cancel', 'extension_set_enabled'))
MAX_TEMPLATE_BYTES = 1024 * 1024


class QtControlledExtensions:
    def __init__(self):
        self.reviews = {}

    def discard(self, project_id):
        self.reviews.pop(project_id, None)

    def execute(self, execution, operation, arguments):
        if execution.closing or execution.workspace_close_requested():
            raise ValueError('项目正在关闭，本次受控扩展操作已取消。')
        execution.instance_registry()
        runtime = execution.capabilities
        extensions = runtime.extensions
        project_id = execution.context.identity.project_id
        enabled = 'extensions' in runtime.enabled_modules
        if operation == 'extension_review':
            if not enabled:
                raise ValueError('当前启动配置已停用受控扩展。')
            self.discard(project_id)
            with Path(arguments[0]).open('rb') as stream:
                raw = stream.read(MAX_TEMPLATE_BYTES + 1)
            if len(raw) > MAX_TEMPLATE_BYTES:
                raise ValueError('模板超过 1 MiB。')
            try:
                manifest = json.loads(raw.decode('utf-8-sig'))
            except (UnicodeError, json.JSONDecodeError):
                raise ValueError('模板必须是有效的 UTF-8 JSON。') from None
            reviewed = extensions.review(manifest)
            token = uuid.uuid4().hex
            self.reviews[project_id] = (token, manifest, reviewed['reviewed_sha256'], time.monotonic())
            execution._log('[受控扩展] 已生成本机审阅内容，等待人工确认')
            return dict(token=token, review=reviewed)
        if operation in ('extension_approve', 'extension_cancel'):
            proof = self.reviews.get(project_id)
            if not proof or proof[0] != arguments[0]:
                raise ValueError('模板审阅已变化，请重新打开原文件审阅。')
            self.discard(project_id)
            if operation == 'extension_approve':
                if time.monotonic() - proof[3] > 300:
                    raise ValueError('模板审阅已过期，请重新核对。')
                extensions.approve(proof[1], proof[2], getpass.getuser())
            else:
                execution._log('[受控扩展] 本机已取消模板审阅')
        if operation == 'extension_set_enabled':
            identifier, expected_digest, wanted = arguments
            row = next((row for row in extensions.list() if row['id'] == identifier), None)
            if row is None or row['reviewed_sha256'] != expected_digest:
                raise ValueError('所选模板已变化，请刷新后重新核对。')
            extensions.set_enabled(identifier, wanted, getpass.getuser())
            execution._log('[受控扩展] ' + identifier + (' 已恢复' if wanted else ' 已停用'))
        return dict(enabled=enabled, rows=extensions.list())

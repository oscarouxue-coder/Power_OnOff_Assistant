"""Asynchronous source update check/download; never executes a downloaded package."""
from dataclasses import asdict
from pathlib import Path
import re
import sys

from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema
from src.models.app_update import AppUpdateCheckResult, ReleaseAsset, UpdateCheckStatus
from src.services.app_update_service import AppUpdateService, AppUpdateCancelled, PORTABLE_ZIP_NAME


class UpdateCapabilities:
    def __init__(self, service, tool_root):
        self.service, self.root = service, Path(tool_root)
        self.updater = AppUpdateService()
        service.registry.register(CapabilitySpec('updates.check', '检查软件更新', '调用原更新服务并保存可信检查结果，不安装或运行程序。',
            object_schema(), self.check, execution_mode='job', cancellation='cooperative'))
        service.registry.register(CapabilitySpec('updates.download', '下载已核验更新', '只能下载原检查任务返回的正式ZIP，沿用原SHA256/压缩包检查；输出在受控工作区，不启动EXE。',
            object_schema({'check_job_id': dict(type='string', minLength=1)}, ('check_job_id',)),
            self.download, risk='modify', execution_mode='job', cancellation='cooperative', sources=('local', 'gui')))

    def _version(self):
        directory = Path(getattr(sys, '_MEIPASS', self.root / 'line_check_assistant' / 'packaging_assets'))
        text = (directory / 'VERSION_INFO.txt').read_text(encoding='utf-8-sig')
        match = re.search(r'版本[：:]\s*[vV]?(\d+\.\d+\.\d+)', text)
        if not match:
            raise CapabilityError('version_unavailable', '未识别本程序版本说明，不猜测版本')
        return match[1]

    def check(self, arguments, authority):
        version = self._version()
        def runner(context):
            try:
                result = self.updater.check_for_update(version, context.stop.event, log=lambda message: context.event('checking', message))
                return dict(ok=True, update=asdict(result))
            except AppUpdateCancelled:
                return dict(ok=False, state='stopped')
        return self.service.jobs.start('updates.check', dict(current_version=version), authority, (), runner, risk='read', observational=True)

    def download(self, arguments, authority):
        checked = self.service.jobs.status(arguments['check_job_id'], authority)
        if checked['capability_id'] != 'updates.check' or checked['state'] != 'succeeded':
            raise CapabilityError('update_check_required', '必须先读取同一身份成功完成的更新检查任务')
        raw = checked['result']['update']
        update = AppUpdateCheckResult(**dict(raw, status=UpdateCheckStatus(raw['status']),
            package_asset=ReleaseAsset(**raw['package_asset']) if raw.get('package_asset') else None))
        if not update.update_available:
            raise CapabilityError('no_update', '该检查结果没有可下载的更新包')
        destination = (self.service.files.workspace / 'updates' / update.latest_version / PORTABLE_ZIP_NAME).resolve()
        if self.service.files.workspace not in destination.parents:
            raise CapabilityError('workspace_required', '更新输出路径越过受控工作区，未下载')
        def runner(context):
            try:
                path = self.updater.download_update(update, destination, context.stop.event,
                    progress=lambda p: context.event('download', str(asdict(p))), log=lambda message: context.event('download', message))
                return dict(ok=True, path=str(path), sha256=update.expected_sha256, executed=False)
            except AppUpdateCancelled:
                return dict(ok=False, state='stopped')
        return self.service.jobs.start('updates.download', arguments, authority, ('update-download',), runner, risk='modify')

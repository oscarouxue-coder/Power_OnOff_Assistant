"""Run the original release checker outside the workspace command queue."""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
import threading
from typing import Optional

from src.models.app_update import AppUpdateProgress
from src.services.app_update_service import AppUpdateCancelled, AppUpdateError, AppUpdateService


def qt_release_version(source_root):
    if getattr(sys, 'frozen', False):
        version_path = Path(sys.executable).resolve().parent / 'VERSION_INFO.txt'
    else:
        version_path = Path(source_root) / 'line_check_assistant/packaging_assets/QT_VERSION_INFO.txt'
    try:
        match = re.search(r'^DUTPilot [vV]?(\d+\.\d+\.\d+)(?=\s|$)',
                          version_path.read_text(encoding='utf-8-sig'), re.MULTILINE)
    except OSError as error:
        raise AppUpdateError('无法读取 DUTPilot 版本说明') from error
    if not match:
        raise AppUpdateError('无法识别 DUTPilot 当前版本')
    return match[1]


@dataclass
class _UpdateTask:
    kind: str
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    progress: Optional[AppUpdateProgress] = None
    result: Optional[tuple] = None
    future: Optional[Future] = None

    def report(self, progress):
        with self.lock:
            self.progress = progress


class QtAppUpdate:
    def __init__(self, source_root, log, service_factory=AppUpdateService):
        self.source_root = source_root
        self._write_log = log
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-app-update')
        self._last_action_log = None
        self.service_factory = service_factory
        self.task = None

    @property
    def idle(self):
        return self.task is None

    def log(self, message):
        """Enqueue an operator action from the GUI, ordered with check and download."""
        self._last_action_log = self._worker.submit(self._write_log, message)

    def finish_close(self):
        if not self.idle or self._last_action_log is not None and not self._last_action_log.done():
            return False
        self._worker.shutdown(wait=False)
        return True

    def start(self, kind, *arguments):
        if not self.idle:
            return False
        task = _UpdateTask(kind)
        task.future = self._worker.submit(self._run, task, arguments)
        self.task = task
        return True

    def cancel(self):
        if self.task is not None:
            self.task.cancel.set()

    def poll(self):
        task = self.task
        if task is None:
            return None, None
        with task.lock:
            progress, task.progress = task.progress, None
        if not task.future.done():
            return progress, None
        self.task = None
        return progress, (task.kind, *(task.result or ('error', '更新任务意外退出，请重试。')))

    def _run(self, task, arguments):
        service = None
        try:
            service = self.service_factory()
            if task.kind == 'check':
                version = qt_release_version(self.source_root)
                self._write_log(f'[检查更新] 开始手动检查，当前版本 {version}。')
                value = service.check_for_update(version, task.cancel, log=self._write_log)
                summary = f'发现新版 {value.latest_version}' if value.update_available else '当前已是最新版本'
            else:
                update, destination, overwrite = arguments
                self._write_log(f'[检查更新] 开始下载 {update.latest_version}。')
                value = service.download_update(update, destination, task.cancel, task.report, overwrite=overwrite, log=self._write_log)
                summary = f'下载成功，SHA256 校验通过：{value}'
            self._write_log(f'[检查更新] {summary}。')
            task.result = ('success', value)
        except AppUpdateCancelled as error:
            self._write_log(f'[检查更新] 操作已取消：{error}')
            task.result = ('cancelled', str(error))
        except Exception as error:
            message = str(error) if isinstance(error, AppUpdateError) else f'更新操作异常：{error}'
            self._write_log(f'[检查更新] 失败：{message}')
            task.result = ('error', message)
        finally:
            if service is not None:
                try:
                    service.close()
                except Exception as error:
                    self._write_log(f'[检查更新] 关闭网络会话异常：{error}')

"""Manual update check, verified download and cooperative Qt shutdown."""
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QProgressBar, QVBoxLayout

from src.models.app_update import UpdateProgressStage
from src.services.qt_app_update import QtAppUpdate
from src.ui.qt.theme import button, label


def _size(value):
    if value < 1024:
        return f'{value} B'
    if value < 1024 * 1024:
        return f'{value / 1024:.1f} KiB'
    return f'{value / (1024 * 1024):.1f} MiB'


class AppUpdateDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.workspace.window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.controller = controller
        self.update = None
        self.saved_path = None
        self.setWindowTitle('DUTPilot · 检查更新')
        available = self.screen().availableGeometry()
        self.resize(min(680, int(available.width() * .94)), min(520, int(available.height() * .90)))
        layout = QVBoxLayout(self)
        layout.addWidget(label('检查软件更新', 'title'))
        self.summary = label('', 'muted')
        self.release_date = label('', 'muted')
        self.status = label('', 'muted')
        hint = label('请在测试结束并退出旧版后，将 ZIP 完整解压到新目录。先备份旧版配置，再按便携包说明迁移本机配置。', 'muted')
        for widget in (self.summary, self.release_date, self.status, hint):
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(self.release_date)
        layout.addWidget(label('更新说明'))
        self.notes = QPlainTextEdit()
        self.notes.setAccessibleName('更新说明')
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch()
        self.primary = button('打开所在文件夹', self._primary, 'primary')
        self.dismiss = button('暂不下载', self._dismiss)
        self.primary.setMinimumWidth(self.primary.sizeHint().width())
        self.dismiss.setMinimumWidth(self.dismiss.sizeHint().width())
        self.primary.setText('重新检查')
        self.dismiss.setText('关闭')
        row.addWidget(self.primary)
        row.addWidget(self.dismiss)
        layout.addLayout(row)

    def _primary(self):
        if self.saved_path is not None:
            directory = self.saved_path.parent
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                self.controller.worker.log(f'[检查更新] 已打开下载目录：{directory}')
            else:
                self.status.setText('无法打开下载目录，请从资源管理器打开保存位置。')
                self.controller.worker.log('[检查更新] 打开下载目录失败。')
        elif self.update is not None:
            self.controller.download()
        else:
            self.controller.check()

    def _dismiss(self):
        task = self.controller.worker.task
        if task is not None and task.kind == 'download':
            self.controller.worker.cancel()
            self.status.setText('正在取消，等待网络读取和临时文件清理…')
            self.dismiss.setEnabled(False)
        else:
            self.close()

    def starting(self, kind):
        self.primary.setEnabled(False)
        self.dismiss.setText('取消')
        self.progress.setValue(0)
        if kind == 'check':
            self.update = self.saved_path = None
            self.summary.clear()
            self.release_date.hide()
            self.primary.setText('重新检查')
            self.notes.clear()
            self.status.setText('正在检查最新正式版本…')
        else:
            self.status.setText('正在下载更新包…')

    def show_progress(self, progress):
        total = progress.total_bytes
        percent = min(100, progress.completed_bytes * 100 // total) if total else 0
        phase = '正在校验 SHA256' if progress.stage == UpdateProgressStage.VERIFYING else '正在下载'
        size = _size(progress.completed_bytes)
        if total:
            size += f' / {_size(total)}（{percent}%）'
        self.progress.setValue(percent)
        if not self.controller.worker.task.cancel.is_set():
            self.status.setText(f'{phase} · {size}')

    def finish(self, kind, outcome, payload):
        self.primary.setEnabled(True)
        self.dismiss.setText('关闭')
        self.dismiss.setEnabled(True)
        if outcome != 'success':
            self.status.setText(payload)
            self.primary.setText('重新下载' if self.update else '重新检查')
        elif kind == 'check':
            self.summary.setText(f'当前版本 {payload.current_version}    最新版本 {payload.latest_version}')
            self.release_date.setText(f'发布日期 {payload.published_at or "未提供"}')
            self.release_date.show()
            self.notes.setPlainText(payload.release_notes or '此版本未填写更新说明。')
            if payload.update_available:
                self.update = payload
                self.status.setText(f'发现新版本，便携包大小 {_size(payload.package_asset.size)}。')
                self.primary.setText('下载')
                self.dismiss.setText('暂不下载')
            else:
                self.status.setText('当前已是最新版本。')
                self.primary.setText('重新检查')
        else:
            self.saved_path = payload
            self.status.setText(f'下载成功，SHA256 校验通过。\n保存位置 {payload}')
            self.progress.setValue(100)
            self.primary.setText('打开所在文件夹')


class AppUpdateController:
    def __init__(self, workspace, source_root):
        self.workspace = workspace
        self.worker = QtAppUpdate(source_root, workspace.adapter.record_update_log)
        self.dialog = None

    def open(self):
        if not self.workspace.ready or self.workspace.closing:
            return
        if self.dialog is None:
            if not self.worker.idle:
                self.workspace.window.statusBar().showMessage('正在等待更新任务收尾', 5000)
                return
            self.dialog = AppUpdateDialog(self)
            self.dialog.finished.connect(self._closed)
            self.check()
        self.dialog.showNormal()
        self.dialog.raise_()

    def _start(self, kind, *arguments):
        if self.dialog is not None and not self.workspace.closing:
            try:
                if self.worker.start(kind, *arguments):
                    self.dialog.starting(kind)
            except RuntimeError:
                self.dialog.finish(kind, 'error', '无法启动更新任务，请重试。')

    def check(self):
        self._start('check')

    def download(self):
        dialog = self.dialog
        if dialog is None or not self.worker.idle or dialog.update is None or self.workspace.closing:
            return
        update = dialog.update
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        default_path = Path(location) / f'DUTPilot_portable_{update.latest_version}.zip'
        name, _ = QFileDialog.getSaveFileName(dialog, '保存新版本便携包', str(default_path), 'ZIP 压缩包 (*.zip)',
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if self.dialog is not dialog or self.workspace.closing:
            return
        if not name:
            self.worker.log('[检查更新] 已跳过下载：未选择保存位置。')
            return
        destination = Path(name)
        if not destination.suffix:
            destination = destination.with_suffix('.zip')
        overwrite = destination.exists()
        if overwrite:
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            if QMessageBox.question(dialog, '确认覆盖文件', f'下载和校验成功后覆盖以下文件？\n{destination}', yes | no, no) != yes:
                self.worker.log('[检查更新] 已跳过下载：取消覆盖已有文件。')
                return
        if self.dialog is dialog and dialog.update is update:
            self._start('download', update, destination, overwrite)

    def _closed(self, _result):
        dialog, self.dialog = self.dialog, None
        if not self.worker.idle:
            self.worker.cancel()
        elif dialog.update is not None and dialog.saved_path is None:
            self.worker.log('[检查更新] 已跳过下载：暂不下载。')

    def begin_close(self):
        self.worker.cancel()
        if self.dialog is not None:
            self.dialog.close()

    def poll(self):
        progress, result = self.worker.poll()
        if self.dialog is not None:
            if result is not None:
                self.dialog.finish(*result)
            elif progress is not None:
                self.dialog.show_progress(progress)

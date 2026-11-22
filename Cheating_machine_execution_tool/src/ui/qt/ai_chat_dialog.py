"""Project-bound local conversation, using the original persisted chat records."""
import json
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPlainTextEdit, QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget)

from src.ui.qt.ai_session_manager_dialog import AiSessionManagerDialog
from src.ui.qt.ai_chat_transcript import AiChatComposer, AiChatStatusLabel, AiChatTranscript
from src.ui.qt.theme import button, label


class AiChatDialog(QDialog):
    action_requested = Signal(str, object)
    model_settings_requested = Signal()
    reports_requested = Signal()
    cases_requested = Signal()

    def __init__(self, project, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project_id = project.project_id
        self.project_name = project.name
        self.monitor_dialog = None
        self.manager = None
        self.progress_dialog = None
        self.review_dialog = None
        self.progress_text = None
        self.setWindowTitle('Ai助手 · ' + project.name)
        available = self.screen().availableGeometry()
        self.resize(min(940, int(available.width() * .94)), min(640, int(available.height() * .90)))
        self.view = None
        self.busy = False
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = label('Ai助手 · ' + project.name, 'title')
        title.setWordWrap(True)
        header.addWidget(title, 1)
        self.reports_button = button('诊断报告…', self.reports_requested.emit)
        header.addWidget(self.reports_button)
        self.cases_button = button('已确认案例…', self.cases_requested.emit)
        header.addWidget(self.cases_button)
        header.addWidget(button('模型连接…', self.model_settings_requested.emit))
        layout.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        self.new_button = QToolButton()
        self.new_button.setProperty('kind', 'primary')
        self.new_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.new_button.setText('新建普通问答')
        self.new_button.clicked.connect(lambda: self._submit('ai_chat_new'))
        self.new_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        new_menu = QMenu(self.new_button)
        self.new_pc_action = new_menu.addAction('新建本机电脑连续诊断', lambda: self._submit('ai_chat_new_pc'))
        self.monitor_action = new_menu.addAction('实时诊断与监控…', lambda: self._submit('ai_chat_monitor_settings'))
        self.new_button.setMenu(new_menu)
        side_layout.addWidget(self.new_button)
        self.sessions = QListWidget()
        self.sessions.setAccessibleName('项目会话')
        self.sessions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sessions.currentItemChanged.connect(self._select)
        self.sessions.customContextMenuRequested.connect(self._menu)
        side_layout.addWidget(self.sessions, 1)
        self.manage_button = button('管理会话…', self._manage)
        side_layout.addWidget(self.manage_button)
        self.session_menu = QMenu(self)
        self.import_action = self.session_menu.addAction('导入文本材料…', self._import)
        self.progress_action = self.session_menu.addAction('查看本会话排查进展',
            lambda: self._submit('ai_chat_progress', self.view.selected))
        self.permission_action = self.session_menu.addAction('查看会话权限…',
            lambda: self._submit('ai_chat_permissions', self.view.selected))
        self.review_action = self.session_menu.addAction('查看待确认操作…',
            lambda: self._submit('ai_chat_review', self.view.selected))
        self.session_menu.addAction('查看留存证据…', lambda: self._submit('ai_chat_evidence', self.view.selected))
        self.session_menu.addAction('重命名会话…', self._rename)
        self.delete_action = self.session_menu.addAction('删除会话…', self._delete)
        splitter.addWidget(side)

        content = QWidget()
        body = QVBoxLayout(content)
        self.status = label('', 'muted')
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.latest_status = AiChatStatusLabel()
        body.addWidget(self.latest_status)
        pages = QHBoxLayout()
        self.older = button('更早消息', lambda: self._submit('ai_chat_page', self.view.selected, self.view.next_cursor))
        self.latest = button('最新消息', lambda: self._submit('ai_chat_page', self.view.selected, None))
        pages.addWidget(self.older)
        pages.addWidget(self.latest)
        pages.addStretch()
        body.addLayout(pages)
        self.transcript = AiChatTranscript()
        body.addWidget(self.transcript, 1)
        self.usage = label('', 'muted')
        self.usage.setWordWrap(True)
        body.addWidget(self.usage)
        self.composer = AiChatComposer()
        self.composer.send_requested.connect(self._send)
        self.composer.setPlaceholderText('输入问题')
        self.composer.setMaximumHeight(self.composer.fontMetrics().lineSpacing() * 5)
        body.addWidget(self.composer)
        actions = QHBoxLayout()
        actions.addStretch()
        self.stop_button = button('停止本轮', lambda: self._submit('ai_chat_stop', self.view.selected), 'danger')
        self.send_button = button('发送', self._send, 'primary')
        actions.addWidget(self.stop_button)
        actions.addWidget(self.send_button)
        body.addLayout(actions)
        splitter.addWidget(content)
        splitter.setSizes((245, 695))
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.set_busy(True)
        self.composer.textChanged.connect(self._sync)

    def _submit(self, operation, *args):
        if not self.busy:
            self.action_requested.emit(operation, args)

    def _sync(self):
        view = self.view
        usable = view is not None and not self.busy
        writable = bool(usable and view.selected and view.writable)
        self.new_button.setEnabled(usable)
        self.manage_button.setEnabled(usable)
        self.sessions.setEnabled(usable)
        self.progress_action.setEnabled(bool(usable and view.selected))
        self.permission_action.setEnabled(bool(usable and view.selected))
        self.review_action.setEnabled(bool(usable and view.selected))
        self.composer.setEnabled(writable)
        self.send_button.setEnabled(writable and not view.routing and (view.pc_diagnosis or not view.running) and
                                    bool(self.composer.toPlainText().strip()))
        self.stop_button.setEnabled(writable and view.running)
        self.older.setEnabled(bool(usable and view.next_cursor))
        self.latest.setEnabled(bool(usable and view.selected))

    def set_busy(self, busy):
        self.busy = busy
        if self.manager is not None:
            self.manager.set_busy(busy)
        self._sync()

    def _manage(self):
        if self.manager is None:
            self.manager = AiSessionManagerDialog(self.project_name, self)
            self.manager.action_requested.connect(lambda operation, args: self._submit(operation, *args))
            self.manager.finished.connect(lambda _: setattr(self, 'manager', None))
            self.manager.show_view(self.view)
        self.manager.showNormal()
        self.manager.raise_()
        self._submit('ai_chat_manage')

    def _select(self, item, _previous):
        if item is not None:
            identifier = item.data(Qt.ItemDataRole.UserRole)
            if self.view is None or self.view.selected != identifier:
                self._submit('ai_chat_select', identifier)

    def _menu(self, point):
        item = self.sessions.itemAt(point)
        if not self.busy and item and item.data(Qt.ItemDataRole.UserRole) == self.view.selected:
            self.import_action.setEnabled(self.view.writable and not self.view.running)
            self.delete_action.setEnabled(not self.view.running)
            self.session_menu.popup(self.sessions.viewport().mapToGlobal(point))

    def _rename(self):
        row = self._selected_row()
        name, accepted = QInputDialog.getText(self, '重命名会话', '会话名称', text=row.title)
        if accepted and name.strip():
            self._submit('ai_chat_rename', row.identifier, name)

    def _delete(self):
        row = self._selected_row()
        answer = QMessageBox.question(self, '永久删除会话',
            f'删除「{row.title}」的消息、上下文及留存证据？原始文件、诊断报告和案例保留。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._submit('ai_chat_delete', row.identifier)

    def _selected_row(self):
        return next(row for row in self.view.sessions if row.identifier == self.view.selected)

    def _import(self):
        identifier = self.view.selected
        path, _ = QFileDialog.getOpenFileName(self, '导入排障文本材料', '', '文本日志 (*.txt *.log *.csv *.json *.md)')
        if path:
            self._submit('ai_chat_import', identifier, path)

    def _send(self):
        if self.send_button.isEnabled():
            self._submit('ai_chat_send', self.view.selected, self.composer.toPlainText())

    def show_view(self, view):
        from dataclasses import asdict
        prior = self.view
        self.view = view
        if self.monitor_dialog is not None and view.monitor_status is not None:
            self.monitor_dialog.update_status(asdict(view.monitor_status))
        if (view.retry_input and prior is not None and prior.selected == view.selected
                and prior.retry_input != view.retry_input and not self.composer.toPlainText()):
            self.composer.setPlainText(view.retry_input)
        if self.review_dialog is not None and prior.selected != view.selected:
            self.review_dialog.close()
        if self.progress_dialog is not None and prior.selected != view.selected:
            self.progress_dialog.close()
        if view.deleted is not None and prior is not None and prior.selected != view.selected:
            self.composer.clear()
        if self.manager is not None:
            self.manager.show_view(view)
        if prior is None or (prior.sessions, prior.selected) != (view.sessions, view.selected):
            with QSignalBlocker(self.sessions):
                self.sessions.clear()
                for row in view.sessions:
                    item = QListWidgetItem(f'{row.title}\n{row.target} · {row.status}')
                    item.setData(Qt.ItemDataRole.UserRole, row.identifier)
                    item.setToolTip(' · '.join(value for value in (row.title, row.model, row.origin) if value))
                    self.sessions.addItem(item)
                    if row.identifier == view.selected:
                        self.sessions.setCurrentItem(item)
        self.transcript.show_messages(view.selected, view.messages, view.draft)
        if prior is None or prior.latest_status != view.latest_status:
            self.latest_status.show_status(view.latest_status)
        if view.selected:
            row = self._selected_row()
            suffix = ' · 仅分析留存材料' if view.history_analysis else ('' if view.writable else ' · 仅查看历史')
            if view.passive_serial:
                suffix = ' · 可读取已打开串口'
            if view.pc_diagnosis:
                suffix = ' · 连续诊断（只读取证）'
            status = '正在识别会话目标' if view.routing and view.running else row.status
            self.status.setText(f'{row.target} · {row.model} · {status}' + suffix)
        else:
            self.status.setText('请选择会话或新建普通问答')
        self.usage.setText(view.context)
        self.composer.setPlaceholderText('输入关于留存材料的问题' if view.history_analysis else '输入问题')
        self._sync()

    def show_progress(self, identifier, text):
        self.show_session_details(identifier, '连续诊断进展', text)

    def show_permissions(self, identifier, preferred, current, enabled, passive_serial=False):
        collection = '可用' if enabled else '不可用'
        if passive_serial:
            collection = '仅可读取已打开的本项目串口'
        self.show_session_details(identifier, '会话权限',
            f'保存的权限偏好：{preferred}\n当前权限模式：{current}\n本会话实时取证：{collection}')

    def show_session_details(self, identifier, title, text):
        if self.view is None or identifier != self.view.selected:
            return
        dialog = self.progress_dialog
        if dialog is None:
            dialog = self.progress_dialog = QDialog(self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            available = self.screen().availableGeometry()
            dialog.resize(min(760, int(available.width() * .94)), min(480, int(available.height() * .9)))
            layout = QVBoxLayout(dialog)
            self.progress_text = QPlainTextEdit(dialog)
            self.progress_text.setReadOnly(True)
            layout.addWidget(self.progress_text)
            layout.addWidget(button('关闭', dialog.close))
            dialog.finished.connect(self._progress_closed)
        dialog.setWindowTitle(title + ' · ' + self._selected_row().title)
        self.progress_text.setPlainText(text)
        dialog.showNormal()
        dialog.raise_()

    def _progress_closed(self):
        self.progress_dialog = None
        self.progress_text = None

    def show_monitor(self, view):
        from src.ui.qt.ai_monitor_dialog import AiMonitorDialog
        if self.monitor_dialog is not None:
            self.monitor_dialog.close()
        panel = self.monitor_dialog = AiMonitorDialog(view, self)
        panel.requested.connect(lambda operation, args: self._submit(operation, *args))
        panel.finished.connect(lambda _: setattr(self, 'monitor_dialog', None))
        panel.show()

    def review_action_result(self, identifier, action, *, monitor=False):
        if not monitor and (self.view is None or identifier != self.view.selected):
            return
        if self.review_dialog is not None:
            self.review_dialog.close()
        if not action:
            self.feedback.setText('监控没有待确认操作' if monitor else '当前会话没有待确认操作')
            return
        from src.models.ai_session_scope import target_label
        target = action.get('target') or {}
        target_text = (f"通道{target['channel']} · {target['vlan']} · {target['port']} · "
                       f"{target['bind_ip']} → {target['host']}:{target['telnet_port']}" if target else target_label(action))
        text = (f"目标：{target_text}\n操作：{action['name']}\n编号：{action['id']}\n"
                f"原因：{action['assessment']['reason']}\n指纹：{action['fingerprint']}\n\n实际参数\n"
                + json.dumps(action['params'], ensure_ascii=False, indent=2))
        if action.get('preview'):
            text += '\n\n文件差异\n' + json.dumps(action['preview'], ensure_ascii=False, indent=2)
        review = self.review_dialog = QDialog(self)
        review.finished.connect(lambda _: setattr(self, 'review_dialog', None))
        review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        review.setWindowTitle('确认监控操作 · ' + self.project_name if monitor else '确认 AI 具体操作 · ' + self._selected_row().title)
        layout = QVBoxLayout(review)
        content = QPlainTextEdit()
        content.setReadOnly(True)
        content.setPlainText(text)
        layout.addWidget(content)
        def decide(approved):
            review.close()
            if monitor:
                self._submit('ai_chat_monitor_decide', action['id'], action['fingerprint'], approved)
            elif self.view and identifier == self.view.selected:
                self._submit('ai_chat_decide', identifier, action['id'], action['fingerprint'], approved)
        actions = QHBoxLayout()
        for title, callback in (('批准本次操作', lambda: decide(True)), ('拒绝', lambda: decide(False)),
                                ('关闭', review.close)):
            control = button(title, callback)
            control.setAutoDefault(False)
            actions.addWidget(control)
            if title == '拒绝':
                control.setFocus()
        layout.addLayout(actions)
        available = self.screen().availableGeometry()
        review.resize(min(800, int(available.width() * .94)), min(530, int(available.height() * .90)))
        review.show()

    def show_evidence(self, rows):
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle('当前会话留存证据')
        available = self.screen().availableGeometry()
        dialog.resize(min(720, int(available.width() * .94)), min(480, int(available.height() * .90)))
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText('\n\n'.join(f'{source} · {timing}\n{content}' for source, timing, content in rows) or '暂无留存证据')
        layout.addWidget(text)
        layout.addWidget(button('关闭', dialog.close))
        dialog.show()

"""Qt views only: serial ownership and all I/O live in the service adapter."""
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QPlainTextEdit, QLineEdit, QFileDialog, QMessageBox, QMenu, QScrollBar,
    QStyle, QStyleOptionSlider)

from src.ui.qt.blocker_review import focus_widget
from src.ui.qt.theme import BACKGROUND, assert_gui_thread, button, label


class _SerialLogScrollBar(QScrollBar):
    def contextMenuEvent(self, event):
        if not self.style().styleHint(QStyle.StyleHint.SH_ScrollBar_ContextMenu, None, self):
            super().contextMenuEvent(event)
            return

        menu = QMenu(self)
        click_y = event.pos().y()
        menu.addAction('滚动到此处', lambda: self._scroll_to_click(click_y))
        action = QScrollBar.SliderAction
        for group in (
            (('滚动到顶部', action.SliderToMinimum), ('滚动到底部', action.SliderToMaximum)),
            (('向上翻页', action.SliderPageStepSub), ('向下翻页', action.SliderPageStepAdd)),
            (('向上滚动一行', action.SliderSingleStepSub), ('向下滚动一行', action.SliderSingleStepAdd)),
        ):
            menu.addSeparator()
            for title, scroll_action in group:
                menu.addAction(title, lambda step=scroll_action: self.triggerAction(step))
        menu.aboutToHide.connect(menu.deleteLater)
        event.accept()
        menu.popup(event.globalPos())

    def _scroll_to_click(self, click_y):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        control = QStyle.ComplexControl.CC_ScrollBar
        groove = style.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarGroove, self)
        thumb = style.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, self)
        # Qt maps the click to the thumb's top edge across its available travel.
        self.setValue(QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), click_y - groove.top(),
            groove.height() - thumb.height(), option.upsideDown))


class SerialTerminalDialog(QDialog):
    command_requested = Signal(str, dict)
    window_state_changed = Signal(str)

    def __init__(self, snapshot):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                         Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint |
                         Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(snapshot['project_name'] + ' · 串口日志')
        self.setStyleSheet(f'QDialog {{ background: {BACKGROUND}; }}')
        self.resize(1040, 660)
        self.setMinimumSize(560, 380)
        self.token = snapshot['token']
        self.project_id = snapshot['project_id']
        self.views = {}
        self.diagnostic_window = None
        self.busy = False
        self._send_pending = False
        self.detaching = False
        self._allow_close = False
        self.pin_action = QAction('窗口置顶', self)
        self.pin_action.setCheckable(True)
        self.pin_action.triggered.connect(self._set_pinned, Qt.ConnectionType.QueuedConnection)
        layout = QVBoxLayout(self)
        title = label(self.windowTitle(), 'title')
        title.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        title.customContextMenuRequested.connect(lambda point: self._title_menu(title.mapToGlobal(point)))
        layout.addWidget(title)
        controls = QHBoxLayout()
        self.open_button = button('打开全部', lambda: self.request('open_all'), 'primary')
        self.stop_button = button('停止全部', lambda: self.request('stop_all'))
        controls.addWidget(self.open_button)
        controls.addWidget(self.stop_button)
        controls.addStretch()
        self.directory_button = button('日志目录…', self.choose_directory)
        for control in (self.open_button, self.stop_button, self.directory_button):
            control.setAutoDefault(False)
        controls.addWidget(self.directory_button)
        layout.addLayout(controls)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.path.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.path.customContextMenuRequested.connect(self.directory_menu)
        layout.addWidget(self.path)
        self.tabs = QTabWidget()
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tabs, 1)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.apply_snapshot(snapshot)

    @property
    def active(self):
        return next((key for key, view in self.views.items() if view['page'] is self.tabs.currentWidget()), '')

    def focus_review(self, target):
        if target.reference:
            view = self.views.get(target.reference)
            return bool(view and focus_widget(view.get(target.field)))
        return focus_widget(getattr(self, target.field, None))

    def request(self, suffix, values=None):
        if self.busy or self.detaching:
            return
        self.set_busy(True, sending=suffix == 'preview_send')
        self.command_requested.emit(suffix, dict(token=self.token, **(values or {})))

    def set_busy(self, value, *, sending=False):
        self.busy = value
        self._send_pending = sending
        self._update_controls()

    def _update_controls(self):
        available = not self.detaching and (not self.busy or self._send_pending)
        for control in (self.open_button, self.stop_button, self.directory_button, self.tabs.tabBar()):
            control.setEnabled(available)
        for view in self.views.values():
            writable = available and view['writable']
            view['input'].setEnabled(writable)
            # Keep the submitted text and focus until the controller handles the reply.
            view['input'].setReadOnly(self._send_pending)
            view['enter'].setEnabled(writable)

    def eventFilter(self, watched, event):
        if self._send_pending and watched is self.tabs.tabBar() and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                QEvent.Type.KeyPress, QEvent.Type.Wheel):
            return True
        return super().eventFilter(watched, event)

    def _add(self, item):
        key = item['target']
        page = QWidget()
        layout = QVBoxLayout(page)
        status = label('', 'muted')
        status.setWordWrap(True)
        layout.addWidget(status)
        output = QPlainTextEdit()
        output.setVerticalScrollBar(_SerialLogScrollBar(Qt.Orientation.Vertical, output))
        output.setReadOnly(True)
        output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        output.document().setMaximumBlockCount(5000)
        output.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        output.customContextMenuRequested.connect(lambda point: self.output_menu(key, point))
        layout.addWidget(output, 1)
        row = QHBoxLayout()
        command = QLineEdit()
        command.setMaxLength(4096)
        command.setPlaceholderText('输入命令后按 Enter；空输入发送回车')
        command.returnPressed.connect(lambda target=key: self.prepare_send(target))
        enter = button('回车', lambda: self.prepare_send(key, True))
        enter.setAutoDefault(False)
        row.addWidget(command, 1)
        row.addWidget(enter)
        layout.addLayout(row)
        self.views[key] = dict(page=page, status=status, output=output, input=command, enter=enter,
            port=item['port'], writable=item['writable'])
        self.tabs.addTab(page, key + ' / ' + item['port'])

    def create_output_menu(self, target):
        view = self.views[target]
        output, port = view['output'], view['port']
        menu = output.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction('查看串口诊断快照…', lambda: self.request('diagnostics', dict(target=target, port=port)))
        menu.addAction('清屏（仅清显示）', output.clear)
        menu.addSeparator()
        menu.addAction(self.pin_action)
        return menu

    def output_menu(self, target, point):
        output = self.views[target]['output']
        menu = self.create_output_menu(target)
        menu.exec(output.mapToGlobal(point))
        menu.deleteLater()

    def _title_menu(self, position):
        menu = QMenu(self)
        menu.addAction(self.pin_action)
        menu.exec(position)
        menu.deleteLater()

    def _set_pinned(self, pinned):
        if not self.isVisible():
            return
        geometry = self.normalGeometry()
        state = self.windowState() & ~Qt.WindowState.WindowActive
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        # Changing a QWidget window flag hides the window and can reset its position.
        self.setGeometry(geometry)
        self.setWindowState(state)
        self.show()
        self.window_state_changed.emit('已置顶' if pinned else '已取消置顶')

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            was_minimized = bool(event.oldState() & Qt.WindowState.WindowMinimized)
            if was_minimized != self.isMinimized():
                self.window_state_changed.emit('已最小化' if self.isMinimized() else '已恢复窗口')

    def show_diagnostics(self, snapshot):
        if self.diagnostic_window is not None:
            self.diagnostic_window.close()
        window = QDialog(self)
        window.setWindowTitle(f"{self.windowTitle()} · {snapshot['target']} / {snapshot['port']} · 诊断快照")
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.resize(720, 460)
        layout = QVBoxLayout(window)
        state = snapshot['state']
        status = '正在关闭' if state['closing_in_program'] else '已打开' if state['opened_in_program'] else '未打开'
        lines = [f"采集时间：{snapshot['captured']}　程序内串口：{status}",
                 '监控所有者：' + ('、'.join(state['monitor_owners']) or '无'),
                 '控制所有者：' + (state['control_owner'] or '无')]
        if state['power_port_conflict']:
            lines.append('当前项目的程控电源也配置了此端口')
        if state['last_open_error']:
            lines.append('最近打开失败：' + state['last_open_error'])
        details = label('\n'.join(lines), 'muted')
        details.setWordWrap(True)
        layout.addWidget(details)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText(snapshot['text'])
        layout.addWidget(output)
        self.diagnostic_window = window
        window.finished.connect(lambda: setattr(self, 'diagnostic_window', None))
        self.finished.connect(window.close)
        window.show()

    def prepare_send(self, target, force_enter=False):
        view = self.views.get(target)
        if view is not None:
            self.request('preview_send', dict(target=target, text='' if force_enter else view['input'].text()))

    def close_tab(self, index):
        target = next((key for key, view in self.views.items() if view['page'] is self.tabs.widget(index)), '')
        if not target or self.busy or self.detaching:
            return
        view = self.views[target]
        answer = QMessageBox.question(self, '确认关闭串口标签', target + ' / ' + view['port'] +
            '\n关闭后停止此标签监控，已保存日志保留。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.views.get(target) is view:
            self.request('close_tab', dict(target=target))
        else:
            self.feedback.setText('取消关闭 ' + target + ' / ' + view['port'])
            self.request('cancel', dict(target=target))

    def directory_menu(self, point):
        menu = self.path.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction('打开日志目录', lambda: self.request('folder'))
        menu.exec(self.path.mapToGlobal(point))
        menu.deleteLater()

    def choose_directory(self):
        if self.busy or self.detaching:
            return
        path = QFileDialog.getExistingDirectory(self, '选择串口日志保存目录', self.path.text())
        if path:
            self.request('directory', dict(path=path))

    @staticmethod
    def append_output(output, text):
        if not text:
            return
        bar = output.verticalScrollBar()
        follow = bar.value() >= bar.maximum()
        # A live cursor follows the same text through prefix/block trimming.
        # Reusing the old scrollbar number would jump by the removed lines.
        anchor = output.cursorForPosition(QPoint(0, 0))
        block = anchor.block()
        line = block.layout().lineForTextPosition(anchor.positionInBlock())
        offset = bar.value() - block.firstLineNumber() - (line.lineNumber() if line.isValid() else 0)
        cursor = QTextCursor(output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        # A stream without newlines must be bounded too.
        excess = output.document().characterCount() - 512 * 1024
        if excess > 0:
            trim = QTextCursor(output.document())
            trim.setPosition(0)
            trim.setPosition(excess, QTextCursor.MoveMode.KeepAnchor)
            trim.removeSelectedText()
        if follow:
            bar.setValue(bar.maximum())
        else:
            block = anchor.block()
            line = block.layout().lineForTextPosition(anchor.positionInBlock())
            position = block.firstLineNumber() + (line.lineNumber() if line.isValid() else 0)
            bar.setValue(max(0, position + offset) if anchor.position() else 0)

    def apply_snapshot(self, snapshot):
        assert_gui_thread()
        if snapshot['token'] not in ('', self.token):
            return
        self.path.setText(snapshot['log_dir'])
        keys = {item['target'] for item in snapshot['tabs']}
        for key in tuple(self.views):
            if key not in keys:
                view = self.views.pop(key)
                self.tabs.removeTab(self.tabs.indexOf(view['page']))
                view['page'].deleteLater()
        for item in snapshot['tabs']:
            if item['target'] not in self.views:
                self._add(item)
            view = self.views[item['target']]
            view.update(port=item['port'], writable=item['writable'])
            self.tabs.setTabText(self.tabs.indexOf(view['page']), item['target'] + ' / ' + item['port'])
            view['status'].setText(item['state'] + (' · 日志：' + item['path'] if item['path'] else '') +
                (' · 手动发送锁定' if not item['writable'] else '') +
                (' · 显示已合并 ' + str(item['dropped']) + ' 字符' if item['dropped'] else ''))
            self.append_output(view['output'], item['text'])
        self.detaching = snapshot['closing']
        self._update_controls()
        if snapshot.get('failures'):
            self.feedback.setText('部分串口打开失败：' + '、'.join(snapshot['failures']))
        elif snapshot['dropped_events']:
            self.feedback.setText('显示事件累计跳过 ' + str(snapshot['dropped_events']) + ' 条；原串口日志独立落盘')
        if not snapshot['token']:
            self._allow_close = True
            self.close()

    def closeEvent(self, event):
        if self._allow_close:
            return super().closeEvent(event)
        event.ignore()
        if not self.busy and not self.detaching:
            self.request('detach')
            self.feedback.setText('正在等待串口停止并保存日志…')

    def reject(self):
        # Escape follows the same safe cleanup handshake as the window X.
        if self._allow_close:
            super().reject()
        else:
            self.close()

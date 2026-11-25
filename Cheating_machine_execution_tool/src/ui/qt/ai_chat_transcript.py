"""Native chat formatting using the shared literal Markdown projection."""
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QTextEdit

from src.ui.qt.theme import BACKGROUND, BRAND, DANGER, MUTED, TEXT
from src.utils.ai_chat_markdown import parse_markdown


class AiChatStatusLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAccessibleName('最新会话状态')
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._line = ''

    def show_status(self, message):
        time = message.created if message else ''
        if time:
            try:
                time = datetime.fromisoformat(time.replace('Z', '+00:00')).strftime('%H:%M:%S')
            except ValueError:
                pass
        text = message.text if message else ''
        self._line = ' · '.join(part for part in (time, ' '.join(text.split())) if part)
        self.setToolTip('<qt>' + escape(text).replace('\n', '<br>') + '</qt>' if text else '')
        self.setStyleSheet(f'color: {DANGER if message and message.kind == "error" else MUTED};')
        self.setVisible(bool(text))
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._line, Qt.TextElideMode.ElideRight, self.contentsRect().width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class AiChatComposer(QPlainTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if modifiers in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier):
                self.send_requested.emit()
                event.accept()
                return
            if modifiers == Qt.KeyboardModifier.AltModifier:
                self.insertPlainText('\n')
                event.accept()
                return
        super().keyPressEvent(event)


class AiChatTranscript(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setAccessibleName('会话消息')
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self._session = ''
        self._messages = ()
        self._draft = ''
        self._tail = 0

    def show_messages(self, session, messages, draft):
        messages = tuple(message for message in messages if message.role != 'system')
        same_page = (session, messages) == (self._session, self._messages)
        if same_page and draft == self._draft:
            return
        scroll = self.verticalScrollBar()
        position = scroll.value()
        stick = session != self._session or position >= scroll.maximum()
        retained = len(self._messages)
        if session == self._session and messages[:retained] == self._messages:
            cursor = QTextCursor(self.document())
            cursor.setPosition(self._tail)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            self.clear()
            cursor = QTextCursor(self.document())
            retained = 0
        for message in messages[retained:]:
            self._insert_message(cursor, message.role, message.created, message.text, message.kind)
        self._tail = cursor.position()
        if draft:
            self._insert_message(cursor, 'assistant', '正在生成', draft, 'text')
        self._session, self._messages, self._draft = session, messages, draft
        scroll.setValue(scroll.maximum() if stick else min(position, scroll.maximum()))

    def _insert_message(self, cursor, role, stamp, text, kind):
        heading = QTextCharFormat()
        heading.setFontWeight(QFont.Weight.Bold)
        heading.setForeground(QColor(DANGER if kind == 'error' else BRAND))
        name = '本地证据' if kind == 'local_evidence' else {'user': '我', 'assistant': 'AI'}.get(role, role)
        title = QTextBlockFormat()
        title.setTopMargin(9 if cursor.position() else 0)
        if cursor.position():
            cursor.insertBlock(title, heading)
        else:
            cursor.setBlockFormat(title)
        cursor.insertText(f'{name} · {stamp[:19].replace("T", " ")}', heading)
        body = QTextCharFormat()
        body.setForeground(QColor(DANGER if kind == 'error' else TEXT))
        if role != 'assistant' or kind == 'local_evidence':
            cursor.insertBlock(QTextBlockFormat(), body)
            cursor.insertText(text, body)
            return
        for line in parse_markdown(text):
            self._insert_markdown_line(cursor, line, body)

    def _insert_markdown_line(self, cursor, line, body):
        block = QTextBlockFormat()
        style = QTextCharFormat(body)
        if line.kind in ('h1', 'h2'):
            block.setTopMargin(5)
            style.setFontWeight(QFont.Weight.Bold)
            style.setFontPointSize(self.fontInfo().pointSizeF() + (2 if line.kind == 'h1' else 1))
        elif line.kind.startswith('code'):
            block.setLeftMargin(12)
            style.setFontFamilies(['Consolas'])
            style.setBackground(QColor(BACKGROUND))
        elif line.marker:
            block.setLeftMargin(8 + min(24, line.indent) * self.fontMetrics().horizontalAdvance(' '))
        cursor.insertBlock(block, style)
        cursor.insertText(line.marker, style)
        for value, flags in line.spans:
            span = QTextCharFormat(style)
            if 'md_bold' in flags:
                span.setFontWeight(QFont.Weight.Bold)
            if 'md_inline_code' in flags:
                span.setFontFamilies(['Consolas'])
                span.setBackground(QColor(BACKGROUND))
            cursor.insertText(value, span)

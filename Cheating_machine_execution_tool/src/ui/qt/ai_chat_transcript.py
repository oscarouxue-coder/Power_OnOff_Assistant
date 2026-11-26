"""Native chat formatting using the shared literal Markdown projection."""
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat, QTextOption
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QTextEdit

from src.ui.qt.theme import BACKGROUND, BRAND, DANGER, MUTED, TEXT, V13_PALETTE
from src.utils.ai_chat_markdown import parse_markdown


_MESSAGE_ROLE = QTextFormat.Property.UserProperty.value
_MESSAGE_INDENT = _MESSAGE_ROLE + 1
_MESSAGE_WIDTH = _MESSAGE_ROLE + 2
_MESSAGE_START = _MESSAGE_ROLE + 3


def _message_margins(role, width, indent=0, natural_width=0):
    """Leave the opposite side empty; the text inside both bubbles is left aligned."""
    width = max(1, int(width))
    edge_limit = 8
    edge = min(edge_limit, width // 20)
    available = width - edge * 2
    # Preserve the last compact-width limit until the normal wide ratio catches
    # up, so crossing 320 px never makes an existing long message narrower.
    compact_limit = min(available * 88 // 100, (320 - edge_limit * 2) * 88 // 100)
    limit = max(1, available * 76 // 100, compact_limit)
    bubble = min(limit, max(min(150, limit), natural_width or limit))
    gap = available - bubble
    left = edge + (gap if role == 'user' else 0)
    right = edge + (gap if role == 'assistant' else 0)
    # Retain Markdown indentation where there is room without squeezing the text
    # out of a narrow chat viewport (including long code and unbroken words).
    indent = min(max(0, indent), width // 4, max(0, width - left - right - 48))
    return left + indent, right


def _message_block(role, width, indent=0, natural_width=0):
    block = QTextBlockFormat()
    block.setAlignment(Qt.AlignmentFlag.AlignLeft)
    block.setProperty(_MESSAGE_ROLE, role)
    block.setProperty(_MESSAGE_INDENT, indent)
    block.setProperty(_MESSAGE_WIDTH, natural_width)
    left, right = _message_margins(role, width, indent, natural_width)
    block.setLeftMargin(left)
    block.setRightMargin(right)
    return block


def _bubble_color(role):
    if role == 'user':
        return QColor(V13_PALETTE.hover_background)
    if role == 'assistant':
        return QColor(V13_PALETTE.neutral.background)
    return None


def _bubble_regions(document, viewport_width):
    """Group native laid-out paragraphs by message heading, not adjacent roles."""
    width = document.textWidth()
    if width <= 0:
        width = viewport_width
    margin = document.documentMargin()
    layout = document.documentLayout()

    def region(role, first, last):
        style = first.blockFormat()
        left = max(0, margin + style.leftMargin() - 5)
        right = min(width, width - margin - style.rightMargin() + 5)
        top = max(0, layout.blockBoundingRect(first).top() - 3)
        bottom = layout.blockBoundingRect(last).bottom() + 3
        return role, QRectF(left, top, max(0, right - left), max(0, bottom - top))

    first = last = None
    active_role = None
    block = document.begin()
    while block.isValid():
        style = block.blockFormat()
        role = style.property(_MESSAGE_ROLE)
        start = style.property(_MESSAGE_START) is True
        if start or role != active_role:
            if first is not None:
                yield region(active_role, first, last)
            first = last = None
            active_role = None
            if start and _bubble_color(role) is not None:
                active_role, first, last = role, block, block
        elif first is not None:
            last = block
        block = block.next()
    if first is not None:
        yield region(active_role, first, last)


def _draw_rounded_bubble(painter, role, rect):
    color = _bubble_color(role)
    if color is None or rect.isEmpty():
        return
    radius = min(10.0, rect.width() / 2, rect.height() / 2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(rect, radius, radius)


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
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._session = ''
        self._messages = ()
        self._draft = ''
        self._tail = 0
        self._layout_width = max(1, self.viewport().width())

    def paintEvent(self, event):
        # The viewport already has its normal widget background. Paint message
        # backgrounds first; the original QTextEdit then draws text, selection,
        # caret and code spans over them, without replacing the native editor.
        if hasattr(self, '_layout_width'):
            painter = QPainter(self.viewport())
            if painter.isActive():
                try:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setClipRect(event.rect())
                    x = self.horizontalScrollBar().value()
                    y = self.verticalScrollBar().value()
                    painter.translate(-x, -y)
                    visible = QRectF(event.rect()).translated(x, y)
                    for role, rect in _bubble_regions(self.document(), self.viewport().width()):
                        if rect.intersects(visible):
                            _draw_rounded_bubble(painter, role, rect)
                finally:
                    painter.end()
        super().paintEvent(event)

    def resizeEvent(self, event):
        ready = hasattr(self, '_layout_width')
        if ready:
            scroll = self.verticalScrollBar()
            position, stick = scroll.value(), scroll.value() >= scroll.maximum()
        super().resizeEvent(event)
        if not ready:
            return
        width = max(1, self.viewport().width())
        if width == self._layout_width:
            return
        self._reflow_message_blocks(width)
        scroll.setValue(scroll.maximum() if stick else min(position, scroll.maximum()))

    def _reflow_message_blocks(self, width):
        self._layout_width = width
        # Reflow only formats, not text. Keep the existing cursor/selection and
        # incremental draft boundary intact when the chat window is resized.
        block = self.document().begin()
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        try:
            while block.isValid():
                style = block.blockFormat()
                role = style.property(_MESSAGE_ROLE)
                if role is not None:
                    left, right = _message_margins(role, width, style.property(_MESSAGE_INDENT) or 0,
                                                  style.property(_MESSAGE_WIDTH) or 0)
                    if (style.leftMargin(), style.rightMargin()) != (left, right):
                        style.setLeftMargin(left)
                        style.setRightMargin(right)
                        cursor.setPosition(block.position())
                        cursor.setBlockFormat(style)
                block = block.next()
        finally:
            cursor.endEditBlock()

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
        heading_text = f'{name} · {stamp[:19].replace("T", " ")}'
        metrics = self.fontMetrics()
        # Short messages occupy a compact bubble; long ones wrap within the
        # viewport limit. Measuring a capped prefix is sufficient for that limit.
        natural_width = 24 + max(metrics.horizontalAdvance(heading_text),
            max((metrics.horizontalAdvance(line[:300]) for line in text.splitlines()), default=0))
        title = _message_block(role, self._layout_width, natural_width=natural_width)
        title.setProperty(_MESSAGE_START, True)
        title.setTopMargin(12 if cursor.position() else 0)
        title.setBottomMargin(2)
        if cursor.position():
            cursor.insertBlock(title, heading)
        else:
            cursor.setBlockFormat(title)
        cursor.insertText(heading_text, heading)
        body = QTextCharFormat()
        body.setForeground(QColor(DANGER if kind == 'error' else TEXT))
        if role != 'assistant' or kind == 'local_evidence':
            cursor.insertBlock(_message_block(role, self._layout_width, natural_width=natural_width), body)
            cursor.insertText(text, body)
            return
        for line in parse_markdown(text):
            self._insert_markdown_line(cursor, line, body, natural_width)

    def _insert_markdown_line(self, cursor, line, body, natural_width):
        indent = 0
        style = QTextCharFormat(body)
        if line.kind in ('h1', 'h2'):
            style.setFontWeight(QFont.Weight.Bold)
            style.setFontPointSize(self.fontInfo().pointSizeF() + (2 if line.kind == 'h1' else 1))
        elif line.kind.startswith('code'):
            indent = 12
            style.setFontFamilies(['Consolas'])
            style.setBackground(QColor(BACKGROUND))
        elif line.marker:
            indent = 8 + min(24, line.indent) * self.fontMetrics().horizontalAdvance(' ')
        block = _message_block('assistant', self._layout_width, indent, natural_width)
        if line.kind in ('h1', 'h2'):
            block.setTopMargin(5)
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

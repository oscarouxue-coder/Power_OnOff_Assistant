"""Actual in-memory Qt document/cursor selection, no QApplication or clipboard."""
from types import SimpleNamespace
from unittest import TestCase

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QTextCursor, QTextDocument
from src.models.qt_ai_chat import ChatMessageView
from src.ui.qt.ai_chat_transcript import AiChatTranscript, _MESSAGE_ROLE, _MESSAGE_START


class MemoryTranscript:
    _insert_message = AiChatTranscript._insert_message
    _insert_markdown_line = AiChatTranscript._insert_markdown_line
    _reflow_message_blocks = AiChatTranscript._reflow_message_blocks
    show_messages = AiChatTranscript.show_messages

    def __init__(self):
        self.doc = QTextDocument()
        self.doc.setLayoutEnabled(False)
        self._layout_width = 720
        self._session, self._messages, self._draft, self._tail = '', (), '', 0
        self.scroll_position = 0
    def document(self):
        return self.doc
    def clear(self):
        self.doc.clear()
    def verticalScrollBar(self):
        return SimpleNamespace(value=lambda: self.scroll_position,
            maximum=lambda: self.doc.characterCount(), setValue=lambda v: setattr(self, 'scroll_position', v))
    def fontInfo(self):
        return SimpleNamespace(pointSizeF=lambda: 10)
    def fontMetrics(self):
        return SimpleNamespace(horizontalAdvance=lambda text: len(text) * 8)


class DocumentSelectionProbe(TestCase):
    def test_real_memory_cursor_selection_and_plain_text_through_reflow_and_stream(self):
        self.assertIsNone(QCoreApplication.instance())
        transcript = MemoryTranscript()
        m = ChatMessageView
        selected_user = '用户原文👩‍💻e\u0301 **字面**'
        user = selected_user + '\r\n第二行'
        assistant = '# 合成标题\n**可见强调**\n```text\n  合成代码\n```\n[字面链接](https://example.invalid)'
        history = (m('user', user, '2026-11-26T12:00:00', 'text'),
                   m('assistant', assistant, '2026-11-26T12:00:01', 'text'),
                   m('system', '单独状态', '', 'progress'))
        transcript.show_messages('a', history, '')
        document = transcript.doc
        visible = document.toPlainText()
        self.assertIn(selected_user + '\n第二行', visible)
        self.assertIn('合成标题\n可见强调\n  合成代码\n[字面链接](https://example.invalid)', visible)
        self.assertNotIn('单独状态', visible)
        self.assertNotIn('# 合成标题', visible)

        selected = document.find(selected_user)
        self.assertTrue(selected.hasSelection())
        self.assertEqual(selected.selectedText(), selected_user)
        self.assertEqual(selected.selection().toPlainText(), selected_user)
        full = QTextCursor(document)
        full.select(QTextCursor.SelectionType.Document)
        self.assertEqual(full.selection().toPlainText(), visible)

        transcript._reflow_message_blocks(180)
        self.assertEqual(document.toPlainText(), visible)
        self.assertEqual(selected.selection().toPlainText(), selected_user)
        transcript.show_messages('a', history, '合成暂存回复')
        self.assertEqual(selected.selection().toPlainText(), selected_user)
        transcript.show_messages('a', history, '合成更新回复')
        self.assertEqual(selected.selection().toPlainText(), selected_user)
        final = m('assistant', '最终合成正文👩‍💻e\u0301', '2026-11-26T12:00:02', 'incomplete')
        transcript.show_messages('a', history + (final,), '')
        transcript._reflow_message_blocks(900)
        current = document.toPlainText()
        self.assertTrue(current.startswith(visible))
        self.assertTrue(current.endswith(final.text))
        self.assertNotIn('合成暂存回复', current)
        self.assertNotIn('合成更新回复', current)
        self.assertEqual(selected.selection().toPlainText(), selected_user)
        full = QTextCursor(document)
        full.select(QTextCursor.SelectionType.Document)
        self.assertEqual(full.selection().toPlainText(), current)
        starts = []
        block = document.begin()
        while block.isValid():
            fmt = block.blockFormat()
            if fmt.property(_MESSAGE_START) is True:
                starts.append(fmt.property(_MESSAGE_ROLE))
            block = block.next()
        self.assertEqual(starts, ['user', 'assistant', 'assistant'])
        self.assertIsNone(QCoreApplication.instance())


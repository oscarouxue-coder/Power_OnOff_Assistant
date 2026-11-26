"""Inspect actual Qt paragraph/character formats without creating a GUI window."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
from src.models.qt_ai_chat import ChatMessageView
from src.ui.qt.ai_chat_transcript import (AiChatTranscript, _message_block, _message_margins,
                                         _MESSAGE_ROLE, _MESSAGE_INDENT, _MESSAGE_WIDTH, _bubble_color)
from src.ui.qt.theme import BACKGROUND, V13_PALETTE


class RecordingDocument:
    def __init__(self):
        self.text, self.runs = '', []


class RecordingCursor:
    # Preserve the real Qt enum contract used by show_messages; only the cursor's
    # document writes are recorded, never a real QWidget or rendering surface.
    MoveOperation = QTextCursor.MoveOperation
    MoveMode = QTextCursor.MoveMode

    def __init__(self, document):
        self.doc, self.pos, self.anchor = document, len(document.text), None
        self.block = QTextBlockFormat()
    def position(self):
        return self.pos
    def setPosition(self, position):
        self.pos = position
    def movePosition(self, operation, mode):
        assert operation == self.MoveOperation.End and mode == self.MoveMode.KeepAnchor
        self.anchor, self.pos = self.pos, len(self.doc.text)
    def removeSelectedText(self):
        assert self.pos == len(self.doc.text)
        self.doc.text = self.doc.text[:self.anchor]
        self.doc.runs = [run for run in self.doc.runs if run[1] <= self.anchor]
        self.pos = self.anchor
    def setBlockFormat(self, block):
        self.block = QTextBlockFormat(block)
    def insertBlock(self, block, _character):
        assert self.pos == len(self.doc.text)
        self.doc.text += '\n'
        self.pos += 1
        self.setBlockFormat(block)
    def insertText(self, text, style):
        assert self.pos == len(self.doc.text)
        start = self.pos
        self.doc.text += text
        self.pos += len(text)
        self.doc.runs.append((start, self.pos, text, QTextBlockFormat(self.block), QTextCharFormat(style)))


class ScrollProjection:
    def __init__(self, document):
        self.doc, self.position = document, 0
    def maximum(self):
        return len(self.doc.text)
    def value(self):
        return self.position
    def setValue(self, value):
        self.position = value


class TranscriptProjection:
    _insert_message = AiChatTranscript._insert_message
    _insert_markdown_line = AiChatTranscript._insert_markdown_line
    show_messages = AiChatTranscript.show_messages
    def __init__(self, width=720):
        self._layout_width = width
        self._session, self._messages, self._draft, self._tail = '', (), '', 0
        self.doc = RecordingDocument()
        self.scroll = ScrollProjection(self.doc)
        self.clears = 0
    def document(self):
        return self.doc
    def verticalScrollBar(self):
        return self.scroll
    def clear(self):
        self.clears += 1
        self.doc.text, self.doc.runs = '', []
    def fontInfo(self):
        return SimpleNamespace(pointSizeF=lambda: 10)
    def fontMetrics(self):
        return SimpleNamespace(horizontalAdvance=lambda text: len(text) * 8)


class ChatBubbleProjectionProbe(TestCase):
    def test_real_block_formats_mirror_roles_and_leave_readable_narrow_width(self):
        for width in (1000, 720, 320, 240, 120, 40):
            for natural in (160, 2500):
                right = _message_block('user', width, natural_width=natural)
                left = _message_block('assistant', width, natural_width=natural)
                self.assertEqual(right.leftMargin(), left.rightMargin())
                self.assertEqual(right.rightMargin(), left.leftMargin())
                self.assertGreater(right.leftMargin(), right.rightMargin())
                self.assertGreater(left.rightMargin(), left.leftMargin())
                self.assertGreater(width - right.leftMargin() - right.rightMargin(), 0)
                self.assertEqual(right.alignment(), Qt.AlignmentFlag.AlignLeft)
                self.assertEqual(left.alignment(), Qt.AlignmentFlag.AlignLeft)
                self.assertEqual(right.property(_MESSAGE_ROLE), 'user')
                self.assertEqual(left.property(_MESSAGE_WIDTH), natural)
                # Rounded backgrounds now use the separate real painter, not
                # square paragraph brushes. Preserve the same role colors.
                self.assertEqual(right.background().style(), Qt.BrushStyle.NoBrush)
                self.assertEqual(left.background().style(), Qt.BrushStyle.NoBrush)
                self.assertEqual(_bubble_color('user').name(), V13_PALETTE.hover_background.lower())
                self.assertEqual(_bubble_color('assistant').name(), V13_PALETTE.neutral.background.lower())
                # Narrow long nested Markdown remains within a positive content width.
                nested = _message_block('assistant', width, 240, natural)
                self.assertGreater(width - nested.leftMargin() - nested.rightMargin(), 0)
                self.assertEqual(nested.property(_MESSAGE_INDENT), 240)
        self.assertGreater(_message_margins('user', 1000, natural_width=160)[0], 500)
        self.assertGreater(_message_margins('assistant', 1000, natural_width=160)[1], 500)
        neutral = _message_block('notice', 720)
        self.assertEqual(neutral.leftMargin(), neutral.rightMargin())

    def test_resize_reflows_formats_only_and_retains_role_and_markdown_indent(self):
        formats = [_message_block('user', 900, natural_width=180),
                   _message_block('assistant', 900, 96, 2200), QTextBlockFormat()]
        formats[0].setTopMargin(9)
        class Block:
            def __init__(self, index):
                self.index = index
            def isValid(self):
                return self.index < len(formats)
            def blockFormat(self):
                return QTextBlockFormat(formats[self.index])
            def position(self):
                return self.index
            def next(self):
                return Block(self.index + 1)
        class Cursor:
            def __init__(self, _doc):
                self.index = None
            def beginEditBlock(self):
                pass
            def endEditBlock(self):
                pass
            def setPosition(self, index):
                self.index = index
            def setBlockFormat(self, block):
                formats[self.index] = QTextBlockFormat(block)
        doc = SimpleNamespace(begin=lambda: Block(0), text='原合成正文不变')
        transcript = SimpleNamespace(document=lambda: doc, _layout_width=900, _tail=17)
        with patch('src.ui.qt.ai_chat_transcript.QTextCursor', Cursor):
            AiChatTranscript._reflow_message_blocks(transcript, 180)
            self.assertEqual((formats[0].leftMargin(), formats[0].rightMargin()),
                             _message_margins('user', 180, natural_width=180))
            self.assertEqual((formats[1].leftMargin(), formats[1].rightMargin()),
                             _message_margins('assistant', 180, 96, 2200))
            self.assertEqual(formats[1].property(_MESSAGE_INDENT), 96)
            self.assertEqual(formats[0].topMargin(), 9)
            self.assertIsNone(formats[2].property(_MESSAGE_ROLE))
            AiChatTranscript._reflow_message_blocks(transcript, 900)
        self.assertEqual(doc.text, '原合成正文不变')
        self.assertEqual(transcript._tail, 17)
        self.assertEqual((formats[1].leftMargin(), formats[1].rightMargin()),
                         _message_margins('assistant', 900, 96, 2200))

    def test_markdown_code_literal_text_and_local_evidence_preserve_roles_and_formats(self):
        transcript = TranscriptProjection(720)
        cursor = RecordingCursor(transcript.doc)
        user = '**用户原文** <img src="literal.png">\n' + '长' * 600
        reply = '# 合成标题\n**合成重点** 与 `inline`\n- 列表\n```text\n  code **literal**\n```\n[外部地址](https://example.test)\n<img src="literal.png">'
        transcript._insert_message(cursor, 'user', '2026-11-26T12:00:00', user, 'text')
        transcript._insert_message(cursor, 'assistant', '2026-11-26T12:00:01', reply, 'text')
        transcript._insert_message(cursor, 'assistant', '2026-11-26T12:00:02', '**本地原文**', 'local_evidence')
        self.assertIn(user, transcript.doc.text)  # no truncation or interpretation
        self.assertIn('合成标题', transcript.doc.text)
        self.assertNotIn('# 合成标题', transcript.doc.text)
        self.assertIn('  code **literal**', transcript.doc.text)
        self.assertIn('[外部地址](https://example.test)', transcript.doc.text)
        self.assertIn('<img src="literal.png">', transcript.doc.text)
        self.assertIn('**本地原文**', transcript.doc.text)
        by_text = {run[2]: (run[3], run[4]) for run in transcript.doc.runs}
        self.assertEqual(by_text[user][0].property(_MESSAGE_ROLE), 'user')
        self.assertEqual(by_text['**本地原文**'][0].property(_MESSAGE_ROLE), 'assistant')
        self.assertEqual(by_text['合成重点'][1].fontWeight(), QFont.Weight.Bold)
        self.assertIn('Consolas', by_text['inline'][1].fontFamilies())
        self.assertEqual(by_text['inline'][1].background().color().name(), BACKGROUND.lower())
        self.assertTrue(all(not style.isAnchor() for _, _, _, _, style in transcript.doc.runs))
        self.assertTrue(all(block.alignment() == Qt.AlignmentFlag.AlignLeft
                            for _, _, _, block, _ in transcript.doc.runs))

    def test_stream_replaces_only_draft_and_preserves_chronology_and_role(self):
        transcript = TranscriptProjection(240)
        m = ChatMessageView
        first = (m('user', '历史提问', '2026-11-26T12:00:00', 'text'),
                 m('assistant', '历史回复', '2026-11-26T12:00:01', 'text'),
                 m('system', '独立状态', '', 'progress'),
                 m('user', '诊断补充（已接收）', '2026-11-26T12:00:02', 'text'))
        with patch('src.ui.qt.ai_chat_transcript.QTextCursor', RecordingCursor):
            transcript.show_messages('a', first, '')
            prefix = transcript.doc.text
            clears = transcript.clears
            self.assertNotIn('独立状态', prefix)
            self.assertLess(prefix.index('历史提问'), prefix.index('历史回复'))
            self.assertLess(prefix.index('历史回复'), prefix.index('诊断补充'))
            transcript.scroll.setValue(1)
            transcript.show_messages('a', first, '旧流式片段')
            self.assertTrue(transcript.doc.text.startswith(prefix))
            self.assertEqual(transcript.scroll.value(), 1)
            transcript.show_messages('a', first, '新流式片段')
            self.assertNotIn('旧流式片段', transcript.doc.text)
            self.assertTrue(transcript.doc.text.startswith(prefix))
            final = m('assistant', '最终保留部分正文［已取消］', '2026-11-26T12:00:03', 'incomplete')
            transcript.show_messages('a', first + (final,), '')
            self.assertNotIn('新流式片段', transcript.doc.text)
            self.assertTrue(transcript.doc.text.startswith(prefix))
            self.assertEqual(transcript.clears, clears)
            roles = [(text, fmt.property(_MESSAGE_ROLE)) for _, _, text, fmt, _ in transcript.doc.runs]
            self.assertIn(('诊断补充（已接收）', 'user'), roles)
            self.assertIn(('最终保留部分正文［已取消］', 'assistant'), roles)
            transcript.show_messages('b', (m('user', '另一会话', '', 'text'),), '')
            self.assertNotIn('历史提问', transcript.doc.text)
            self.assertIn('另一会话', transcript.doc.text)


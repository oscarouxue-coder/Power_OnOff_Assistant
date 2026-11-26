"""Narrow-width transition and very long literal text; no widgets or external I/O."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.models.qt_ai_chat import ChatMessageView
from src.ui.qt.ai_chat_transcript import _message_block, _MESSAGE_ROLE
import bubble_projection_probe as previous


class LongTextProbe(TestCase):
    def test_long_message_limit_never_shrinks_across_compact_width_transition(self):
        for role in ('user', 'assistant'):
            content_widths = []
            for width in range(280, 501):
                block = _message_block(role, width, natural_width=6000)
                content_widths.append(width - block.leftMargin() - block.rightMargin())
            self.assertTrue(all(a <= b for a, b in zip(content_widths, content_widths[1:])))
            self.assertEqual(content_widths[319 - 280], 266)
            self.assertEqual(content_widths[320 - 280], 267)

    def test_long_literal_chinese_url_and_ascii_survive_stream_and_history(self):
        raw = ('中文' * 6000 + '\nhttps://example.invalid/' + 'x' * 12000 + '\n' +
               'ABCDEFGHIJ0123456789' * 800)
        self.assertGreater(len(raw), 40000)
        measured = []
        def measure(text):
            measured.append(len(text))
            return len(text) * 8
        m = ChatMessageView
        first = (m('user', raw, '2026-11-26T12:00:00', 'text'),
                 m('system', '仅系统状态', '', 'progress'))
        final = m('assistant', raw, '2026-11-26T12:00:01', 'text')
        narrow = previous.TranscriptProjection(240)
        narrow.fontMetrics = lambda: SimpleNamespace(horizontalAdvance=measure)
        with patch('src.ui.qt.ai_chat_transcript.QTextCursor', previous.RecordingCursor):
            narrow.show_messages('session', first, '')
            prefix = narrow.doc.text
            narrow.show_messages('session', first, raw[:1024])
            self.assertTrue(narrow.doc.text.startswith(prefix))
            narrow.show_messages('session', first, raw)
            self.assertTrue(narrow.doc.text.startswith(prefix))
            self.assertTrue(narrow.doc.text.endswith(raw))
            narrow.show_messages('session', first + (final,), '')
            actual = narrow.doc.text
            self.assertEqual(actual.count(raw), 2)
            self.assertNotIn('正在生成', actual)
            self.assertNotIn('仅系统状态', actual)
            self.assertTrue(all(not style.isAnchor() for _, _, _, _, style in narrow.doc.runs))
            self.assertEqual({fmt.property(_MESSAGE_ROLE) for _, _, _, fmt, _ in narrow.doc.runs},
                             {'user', 'assistant'})
            wide = previous.TranscriptProjection(1000)
            wide.fontMetrics = lambda: SimpleNamespace(horizontalAdvance=measure)
            wide.show_messages('session', first + (final,), '')
            self.assertEqual(wide.doc.text, actual)
        self.assertTrue(measured)
        self.assertLessEqual(max(measured), 300)  # sizing bound, not a content bound


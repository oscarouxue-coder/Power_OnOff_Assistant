"""Real offscreen QImage rounded-paint pixels and synthetic message geometry, no QWidget."""
from types import SimpleNamespace
from unittest import TestCase

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QTextBlockFormat
from src.ui.qt.ai_chat_transcript import (_bubble_color, _bubble_regions, _draw_rounded_bubble,
                                         _message_block, _MESSAGE_ROLE, _MESSAGE_START)
import bubble_projection_probe as previous


class RoundedBubbleProbe(TestCase):
    def test_real_qpainter_image_pixels_have_rounded_corners_and_role_colors(self):
        for role in ('user', 'assistant'):
            image = QImage(100, 60, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                self.assertTrue(painter.isActive())
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                _draw_rounded_bubble(painter, role, QRectF(8, 8, 84, 44))
            finally:
                painter.end()
            self.assertEqual(image.pixelColor(50, 30), _bubble_color(role))
            self.assertEqual(image.pixelColor(8, 8).alpha(), 0)
            self.assertEqual(image.pixelColor(91, 8).alpha(), 0)
            self.assertEqual(image.pixelColor(8, 51).alpha(), 0)
            self.assertEqual(image.pixelColor(91, 51).alpha(), 0)
            self.assertGreater(image.pixelColor(12, 30).alpha(), 0)
            self.assertEqual(_message_block(role, 640).background().style(), Qt.BrushStyle.NoBrush)
        self.assertNotEqual(_bubble_color('user'), _bubble_color('assistant'))
        self.assertIsNone(_bubble_color('system'))

    def test_message_boundaries_group_round_rectangles_without_merging_same_role(self):
        def heading(role, width):
            fmt = _message_block(role, 640, natural_width=width)
            fmt.setProperty(_MESSAGE_START, True)
            return fmt
        formats = [heading('user', 180), _message_block('user', 640, natural_width=180),
                   heading('user', 220), _message_block('user', 640, natural_width=220),
                   heading('assistant', 500), _message_block('assistant', 640, 12, 500),
                   _message_block('assistant', 640, 16, 500), QTextBlockFormat()]
        bounds = [QRectF(0, y, 640, h) for y, h in ((8, 20), (30, 32), (76, 18), (96, 32),
                                                    (142, 20), (164, 35), (201, 40), (250, 10))]
        class Block:
            def __init__(self, index):
                self.index = index
            def isValid(self):
                return self.index < len(formats)
            def blockFormat(self):
                return formats[self.index]
            def next(self):
                return Block(self.index + 1)
        doc = SimpleNamespace(textWidth=lambda: 640, documentMargin=lambda: 4,
                              documentLayout=lambda: SimpleNamespace(blockBoundingRect=lambda b: bounds[b.index]),
                              begin=lambda: Block(0))
        bubbles = tuple(_bubble_regions(doc, 640))
        self.assertEqual([role for role, _ in bubbles], ['user', 'user', 'assistant'])
        first, second, assistant = (rect for _, rect in bubbles)
        self.assertGreater(first.left(), 320)
        self.assertGreater(second.left(), 320)
        self.assertGreater(first.right(), 600)
        self.assertGreater(second.right(), 600)
        self.assertLess(assistant.left(), 20)
        self.assertLess(first.bottom(), second.top())
        self.assertLess(second.bottom(), assistant.top())
        self.assertGreater(assistant.bottom(), bounds[6].bottom())

        # The real insertion method emits one boundary per message, even when
        # two consecutive senders have the same role and an AI reply has Markdown.
        transcript = previous.TranscriptProjection(640)
        cursor = previous.RecordingCursor(transcript.doc)
        transcript._insert_message(cursor, 'user', '', '同角色一', 'text')
        transcript._insert_message(cursor, 'user', '', '同角色二', 'text')
        transcript._insert_message(cursor, 'assistant', '', '# 标题\n正文\n- 条目', 'text')
        starts = [(text, fmt.property(_MESSAGE_ROLE)) for _, _, text, fmt, _ in transcript.doc.runs
                  if fmt.property(_MESSAGE_START) is True]
        self.assertEqual([role for _, role in starts], ['user', 'user', 'assistant'])
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(fmt.background().style() == Qt.BrushStyle.NoBrush
                            for _, _, _, fmt, _ in transcript.doc.runs))


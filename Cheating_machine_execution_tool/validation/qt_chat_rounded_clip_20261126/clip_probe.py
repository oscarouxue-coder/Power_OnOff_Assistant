"""Verify the actual QPainter clip/translation sequence in memory, no widget."""
from unittest import TestCase

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from src.ui.qt.ai_chat_transcript import _bubble_color, _draw_rounded_bubble


class RoundedClipProbe(TestCase):
    def test_scrolled_dirty_rectangle_does_not_paint_outside_visible_region(self):
        base = QColor('#FDFDFD')
        image = QImage(120, 90, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(base)
        dirty = QRect(20, 12, 70, 60)
        x, y = 18, 90
        regions = (('user', QRectF(56, 82, 70, 46)),
                   ('assistant', QRectF(0, 140, 80, 48)),
                   ('user', QRectF(90, 200, 40, 40)))
        painted = []
        painter = QPainter(image)
        try:
            self.assertTrue(painter.isActive())
            # The same ordering and coordinate transforms as transcript.paintEvent.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(dirty)
            painter.translate(-x, -y)
            visible = QRectF(dirty).translated(x, y)
            for role, rect in regions:
                if rect.intersects(visible):
                    _draw_rounded_bubble(painter, role, rect)
                    painted.append(role)
        finally:
            painter.end()
        self.assertEqual(painted, ['user', 'assistant'])
        self.assertEqual(image.pixelColor(60, 25), _bubble_color('user'))
        self.assertEqual(image.pixelColor(35, 60), _bubble_color('assistant'))
        self.assertEqual(image.pixelColor(60, 45), base)
        outside = 0
        for yy in range(image.height()):
            for xx in range(image.width()):
                if not dirty.contains(xx, yy):
                    outside += 1
                    self.assertEqual(image.pixelColor(xx, yy), base, (xx, yy))
        self.assertEqual(outside, 6600)


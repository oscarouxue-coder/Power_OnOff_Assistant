"""Determinate progress views for the Qt component showcase and workbench."""
from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QAbstractAnimation, QPropertyAnimation, QRectF, QSize, Qt,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QWidget

from .showcase_components import BORDER, BRAND, STATUS_STYLES, TEXT
from .theme import assert_gui_thread


_STATUS_KEYS = {
    'normal': 'healthy',
    'warning': 'warning',
    'error': 'error',
    'unknown': 'unknown',
    'unavailable': 'unavailable',
}


class _ProgressView(QWidget):
    """Keep the reported value distinct from the short visual transition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = None
        self._state = 'unknown'
        self._painted = 0.0
        self._animation = QPropertyAnimation(self, b'paintedProgress', self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setAccessibleName('进度')

    @property
    def value(self):
        return self._value

    @property
    def state(self):
        return self._state

    @property
    def display_text(self):
        if self._value is None:
            return STATUS_STYLES['unavailable' if self._state == 'unavailable' else 'unknown'].label
        return f'{self._value}%'

    @property
    def is_animating(self):
        return self._animation.state() == QAbstractAnimation.State.Running

    def _get_painted(self):
        return self._painted

    def _set_painted(self, value):
        self._painted = float(value)
        self._update_fill()

    paintedProgress = Property(float, _get_painted, _set_painted)

    def set_progress(self, value: int | None, state='normal', *, animate=True):
        """Update from a reported percentage. Unknown observations never draw a fill."""
        assert_gui_thread()
        if state not in _STATUS_KEYS:
            raise ValueError(f'未知的进度状态：{state}')
        if value is not None and (type(value) is not int or not 0 <= value <= 100):
            raise ValueError('进度必须为 0–100 的整数或 None')
        if state in ('unknown', 'unavailable'):
            value = None
        elif value is None and state == 'normal':
            state = 'unknown'

        if (value, state) == (self._value, self._state):
            if not animate and self.is_animating:
                self._finish_transition()
            return
        previous_value = self._value
        self._value, self._state = value, state
        self._update_status()
        self.setAccessibleDescription(self._caption())
        # A state-only change recolors the existing transition without restarting it.
        if value == previous_value and animate:
            return
        self._animation.stop()
        if animate and self.isVisible() and value is not None and previous_value is not None:
            self._animation.setStartValue(self._painted)
            self._animation.setEndValue(float(value))
            self._animation.start()
        else:
            self._set_painted(value or 0)

    def _caption(self):
        if self._state in ('warning', 'error'):
            return f'{STATUS_STYLES[_STATUS_KEYS[self._state]].label} · {self.display_text}'
        return self.display_text

    def _fill_color(self):
        return BRAND if self._state == 'normal' else STATUS_STYLES[_STATUS_KEYS[self._state]].color

    def _finish_transition(self):
        self._animation.stop()
        self._set_painted(self._value or 0)

    def hideEvent(self, event):
        if self.is_animating:
            self._finish_transition()
        super().hideEvent(event)


class ProgressBar(_ProgressView):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        self._bar.setValue(0)
        layout.addWidget(self._bar, 1)
        self._label = QLabel(self)
        layout.addWidget(self._label)
        self._update_status()
        self.setAccessibleDescription(self._caption())

    def _update_status(self):
        style = (
            f'QProgressBar {{ background: {BORDER}; border: none; border-radius: 4px; }}'
            f'QProgressBar::chunk {{ background: {self._fill_color()}; border-radius: 4px; }}'
        )
        if style != self._bar.styleSheet():
            self._bar.setStyleSheet(style)
        self._label.setText(self._caption())

    def _update_fill(self):
        self._bar.setValue(round(self._painted))


class CircularProgress(_ProgressView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(80, 80)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAccessibleDescription(self._caption())

    def sizeHint(self):
        return QSize(104, 104)

    def _update_status(self):
        self.update()

    def _update_fill(self):
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.contentsRect())
        side = min(bounds.width(), bounds.height()) - 8
        ring = QRectF(0, 0, side, side)
        ring.moveCenter(bounds.center())
        pen = QPen(QColor(BORDER), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(ring)
        if self._value is not None and self._painted > 0:
            pen.setColor(QColor(self._fill_color()))
            painter.setPen(pen)
            painter.drawArc(ring, 90 * 16, -round(360 * 16 * self._painted / 100))

        text = QRectF(ring)
        show_status = self._state in ('warning', 'error')
        line_height = painter.fontMetrics().height()
        if show_status:
            text.translate(0, -line_height / 2)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        painter.drawText(text, Qt.AlignmentFlag.AlignCenter, self.display_text)
        if show_status:
            font.setBold(False)
            painter.setFont(font)
            text.translate(0, line_height)
            painter.drawText(text, Qt.AlignmentFlag.AlignCenter, STATUS_STYLES[_STATUS_KEYS[self._state]].label)
        painter.end()

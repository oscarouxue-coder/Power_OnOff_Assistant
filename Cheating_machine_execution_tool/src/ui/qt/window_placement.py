"""Keep restored project dialogs on a screen that is currently available."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QStyle

from src.models.qt_window_placement import WindowPlacement


def current_placement(dialog):
    if dialog.isMaximized() or dialog.isMinimized():
        rect = dialog.normalGeometry()
        if rect.isValid():
            position = rect.topLeft()
            if dialog.isMinimized():
                # normalGeometry uses the client origin, while saved positions use the frame origin.
                position -= dialog.geometry().topLeft() - dialog.pos()
            return WindowPlacement(rect.width(), rect.height(), position.x(), position.y())
    return WindowPlacement(dialog.width(), dialog.height(), dialog.x(), dialog.y())


def _saved_position(placement, screen):
    if placement.x is None or placement.y is None:
        return None
    x, y = placement.x, placement.y
    if placement.legacy:
        if x == 0 and y == 0:
            return None
        bounds = screen.geometry()
        x = bounds.right() + 1 - placement.width + x if x < 0 else bounds.left() + x
        y = bounds.bottom() + 1 - placement.height + y if y < 0 else bounds.top() + y
    return QPoint(x, y)


def restore_placement(dialog, placement, *, reference_window=None):
    if placement is None:
        if reference_window is None:
            return
        placement = WindowPlacement(dialog.width(), dialog.height())
    parent = reference_window if reference_window is not None else dialog.parentWidget()
    screen = parent.screen() if parent is not None else dialog.screen()
    width, height = placement.width, placement.height
    position = _saved_position(placement, QGuiApplication.primaryScreen() if placement.legacy else screen)
    if position is not None:
        saved = QRect(position.x(), position.y(), width, height)
        visible = []
        for candidate in QGuiApplication.screens():
            overlap = saved.intersected(candidate.availableGeometry())
            if overlap.width() >= 120 and overlap.height() >= 120:
                visible.append((overlap.width() * overlap.height(), candidate))
        if visible:
            screen = max(visible, key=lambda pair: pair[0])[1]
        else:
            position = None
    bounds = screen.availableGeometry()
    border = 2 * dialog.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth)
    title = dialog.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight)
    frame_width = max(border, dialog.frameGeometry().width() - dialog.width())
    frame_height = max(border + title, dialog.frameGeometry().height() - dialog.height())
    if dialog.layout() is not None:
        dialog.layout().activate()
    minimum = dialog.minimumSizeHint().expandedTo(dialog.minimumSize())
    width = max(minimum.width(), min(width, bounds.width() - frame_width))
    height = max(minimum.height(), min(height, bounds.height() - frame_height))
    dialog.resize(width, height)
    if position is None:
        center = parent.frameGeometry().center() if parent is not None else bounds.center()
        position = QPoint(center.x() - (width + frame_width) // 2, center.y() - (height + frame_height) // 2)
    x = max(bounds.left(), min(position.x(), bounds.right() + 1 - width - frame_width))
    y = max(bounds.top(), min(position.y(), bounds.bottom() + 1 - height - frame_height))
    dialog.move(x, y)

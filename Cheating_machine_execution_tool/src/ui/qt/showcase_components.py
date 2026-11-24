"""V1.3.x components shared by the design preview and the workbench."""
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from src.models.project_profile import TEST_TYPES
from src.ui.qt.theme import CARD_PADDING, GAP, V13_PALETTE, assert_gui_thread, button, label


BRAND = V13_PALETTE.brand
INFO = V13_PALETTE.info
MUTED = V13_PALETTE.muted
TEXT = V13_PALETTE.text
BORDER = V13_PALETTE.border
BACKGROUND = V13_PALETTE.background
SURFACE = V13_PALETTE.surface


@dataclass(frozen=True)
class StatusStyle:
    label: str
    color: str
    background: str
    ink: str
    icon: str


STATUS_STYLES = {
    'running': StatusStyle('运行中', *V13_PALETTE.success, 'play'),
    'healthy': StatusStyle('正常', *V13_PALETTE.success, 'check'),
    'waiting': StatusStyle('等待资源', *V13_PALETTE.warning, 'clock'),
    'warning': StatusStyle('警告', *V13_PALETTE.warning, 'warning'),
    'error': StatusStyle('异常', *V13_PALETTE.error, 'error'),
    'stopped': StatusStyle('已停止', *V13_PALETTE.neutral, 'stop'),
    'unknown': StatusStyle('未知', *V13_PALETTE.neutral, 'question'),
    'unavailable': StatusStyle('未接入', *V13_PALETTE.neutral, 'unplug'),
    'busy': StatusStyle('使用中', *V13_PALETTE.information, 'lock'),
}

# ProjectView.state is the operation or ledger state. Keep the supplied
# state_text: e.g. "部分失败" shares the failed code, "未执行" shares stopped.
_PROJECT_STYLES = {
    'idle': StatusStyle('空闲', *V13_PALETTE.neutral, 'idle'),
    'running': STATUS_STYLES['running'],
    'queued': StatusStyle('等待执行', *V13_PALETTE.information, 'queue'),
    'stopping': StatusStyle('停止中', *V13_PALETTE.warning, 'pause'),
    'stopped': STATUS_STYLES['stopped'],
    'completed': StatusStyle('已完成', *V13_PALETTE.success, 'check'),
    'unchecked': StatusStyle('完成（含未校验）', *V13_PALETTE.warning, 'inspect'),
    'failed': StatusStyle('失败', *V13_PALETTE.error, 'error'),
    'unknown': StatusStyle('结果未知', *V13_PALETTE.neutral, 'question'),
    'recovery_required': StatusStyle('需要恢复确认', *V13_PALETTE.warning, 'refresh'),
    'pending': StatusStyle('待接入', *V13_PALETTE.neutral, 'unplug'),
}


def project_status_style(state):
    """Presentation only; never infer an execution result from operator text."""
    return _PROJECT_STYLES.get(state, _PROJECT_STYLES['unknown'])


# A common viewBox and stroke keep the symbols legible at toolbar and badge sizes.
_SYMBOLS = {
    'play': '<path d="M6 4l13 8-13 8z"/>',
    'check': '<circle cx="12" cy="12" r="9"/><path d="m7.5 12 3 3 6-6"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6.5V12l4 2.5"/>',
    'warning': '<path d="m12 3 10 17H2zM12 9v4m0 3h.01"/>',
    'error': '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
    'stop': '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    'question': '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 5.4 1.9c-.9 1.1-2.4 1-2.4 3m0 2h.01"/>',
    'unplug': '<path d="m3 21 4-4m-2-5 7 7m-6-6 3-3m1 7 3-3m1-8 3-3m-4 2 6 6m-2-8 3-3"/>',
    'refresh': '<path d="M20 5v5h-5M4 19v-5h5M5.4 8a7.5 7.5 0 0 1 13-2L20 9M4 15l1.6 3a7.5 7.5 0 0 0 13-2"/>',
    'lock': '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    'idle': '<circle cx="12" cy="12" r="8"/><path d="M8 12h8"/>',
    'queue': '<path d="M9 6h11M9 12h8M9 18h5M4 6h.1M4 12h.1M4 18h.1"/>',
    'pause': '<rect x="5" y="4" width="4" height="16" rx="1"/><rect x="15" y="4" width="4" height="16" rx="1"/>',
    'inspect': '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 6 6m-13-10.5h5"/>',
    'projects': '<path d="M3 7V5h7l2 2h9v12H3z"/>',
    'grid': '<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>',
    'model-link': '<path d="m9 15 6-6m-5-2 2-2a5 5 0 0 1 7 7l-2 2M7 10l-2 2a5 5 0 0 0 7 7l2-2"/>',
    'chat': '<path d="M4 4h16v12H10l-6 4zM8 8h8M8 12h5"/>',
    'devices': '<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M12 15v5m-5 0h10"/>',
    'settings': '<path d="M3 7h3m5 0h10M3 17h10m5 0h3"/>'
                '<circle cx="8.5" cy="7" r="2.5"/><circle cx="15.5" cy="17" r="2.5"/>',
    'navigation': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    'more': '<path d="m5 6 6 6-6 6m7-12 6 6-6 6"/>',
    'power-cycle': '<path d="M12 2v8M8 6a7 7 0 1 0 8 0M3 15a10 10 0 0 0 16 5m-4 0h4v-4"/>',
    'heartbeat': '<path d="M2 13h5l3-9 4 16 3-7h5"/>',
}


_TYPE_SYMBOLS = {'power_cycle': 'power-cycle', 'service_aging': 'heartbeat'}
_LABEL_TYPES = {title: key for key, title in TEST_TYPES.items()}


def test_type_symbol(project_type, test_type=''):
    """A legacy snapshot may carry only the canonical test-type label."""
    return _TYPE_SYMBOLS.get(project_type or _LABEL_TYPES.get(test_type))


def _symbol_renderer(name, color, background=None):
    symbol = _SYMBOLS[name]
    if background:
        symbol = (f'<circle cx="12" cy="12" r="12" stroke="none" fill="{background}"/>'
                  f'<g transform="translate(2 2) scale(.833333)">{symbol}</g>')
    data = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{symbol}</svg>')
    return QSvgRenderer(QByteArray(data.encode('ascii')))


def _render_symbol(renderer, size):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    return pixmap


@lru_cache(maxsize=48)
def semantic_icon(name, color=BRAND, *, on_dark=False):
    """Build a Qt icon for 16–24 px controls, including scaled Windows displays."""
    assert_gui_thread()
    icon = QIcon()
    for mode, ink in ((QIcon.Mode.Normal, color), (QIcon.Mode.Active, SURFACE if on_dark else V13_PALETTE.hover),
                      (QIcon.Mode.Selected, SURFACE if on_dark else V13_PALETTE.selected),
                      (QIcon.Mode.Disabled, V13_PALETTE.disabled)):
        renderer = _symbol_renderer(name, ink)
        for size in (16, 20, 24, 32, 48, 64):
            pixmap = _render_symbol(renderer, size)
            icon.addPixmap(pixmap, mode, QIcon.State.Off)
            if mode == QIcon.Mode.Selected:
                for checked_mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
                    icon.addPixmap(pixmap, checked_mode, QIcon.State.On)
            elif mode == QIcon.Mode.Disabled:
                icon.addPixmap(pixmap, mode, QIcon.State.On)
    return icon


@lru_cache(maxsize=32)
def _project_icon(style):
    # Selection changes the row surface. Keep the status glyph identifiable
    # even on the dark sidebar or a selected table row.
    icon = QIcon()
    for disabled in (False, True):
        color = V13_PALETTE.muted if disabled else style.ink
        background = V13_PALETTE.neutral.background if disabled else style.background
        renderer = _symbol_renderer(style.icon, color, background)
        modes = (QIcon.Mode.Disabled,) if disabled else (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected)
        for size in (16, 20, 24, 32, 48, 64):
            pixmap = _render_symbol(renderer, size)
            for mode in modes:
                icon.addPixmap(pixmap, mode, QIcon.State.Off)
                icon.addPixmap(pixmap, mode, QIcon.State.On)
    return icon


def project_status_icon(state):
    assert_gui_thread()
    return _project_icon(project_status_style(state))


SHOWCASE_QSS = f'''
QWidget {{ font-family: "Microsoft YaHei UI", "Segoe UI"; color: {TEXT}; }}
QWidget#ComponentShowcase, QWidget#ShowcaseContent {{ background: {BACKGROUND}; }}
QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="metric"] {{ font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 26px; font-weight: 700; }}
QPushButton, QToolButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {BRAND}; color: {V13_PALETTE.hover}; background: {V13_PALETTE.hover_background}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {INFO}; }}
QPushButton[kind="primary"] {{ background: {BRAND}; color: white; border-color: {BRAND}; }}
QPushButton[kind="primary"]:hover {{ background: {V13_PALETTE.hover}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {V13_PALETTE.selected_background}; }}
QPushButton[kind="primary"]:pressed {{ background: {V13_PALETTE.selected}; }}
QPushButton:disabled, QPushButton[kind="primary"]:disabled, QToolButton:disabled {{
    background: {BACKGROUND}; color: {MUTED}; border-color: {BORDER};
}}
'''


def primary_button(text, callback=None, parent=None):
    return button(text, callback, 'primary', parent)


def secondary_button(text, callback=None, parent=None):
    return button(text, callback, parent=parent)


def icon_button(icon_name, accessible_name, callback=None, parent=None):
    widget = QToolButton(parent)
    widget.setIcon(semantic_icon(icon_name))
    widget.setIconSize(QSize(20, 20))
    widget.setMinimumSize(32, 32)
    widget.setAccessibleName(accessible_name)
    widget.setToolTip(accessible_name)
    if callback is not None:
        widget.clicked.connect(callback)
    return widget


class SymbolView(QWidget):
    def __init__(self, parent, size=16):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.icon = QIcon()

    def paintEvent(self, event):
        painter = QPainter(self)
        self.icon.paint(painter, self.rect())
        painter.end()


class _BadgeCaption(QLabel):
    """Retain the complete plain text, eliding only the painted caption."""
    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()


class StatusBadge(QFrame):
    def __init__(self, state='unknown', parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setProperty('badge', True)
        self._appearance = None
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(5)
        self._symbol = SymbolView(self)
        self._caption = _BadgeCaption(self)
        self._caption.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self._symbol)
        row.addWidget(self._caption)
        self.set_state(state)

    def set_state(self, state):
        assert_gui_thread()
        style = STATUS_STYLES.get(state, STATUS_STYLES['unknown'])
        self._set_presentation(style, semantic_icon(style.icon, style.color), style.label)

    def set_project_state(self, state, text):
        assert_gui_thread()
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._set_presentation(project_status_style(state), project_status_icon(state), text)
        self.setToolTip(text)

    def text(self):
        return self._caption.text()

    def _set_presentation(self, style, icon, text):
        appearance = (style, icon.cacheKey())
        if appearance != self._appearance:
            self._appearance = appearance
            self._symbol.icon = icon
            self._symbol.update()
            self._caption.setStyleSheet(f'color: {style.ink}; font-weight: 600;')
            self.setStyleSheet(f'QFrame[badge="true"] {{background: {style.background}; border-radius: 10px;}}')
        if text != self.text():
            self._caption.setText(text)
            self.setAccessibleName(text)


class MetricCard(QFrame):
    def __init__(self, title, value, parent=None, *, symbol=None):
        super().__init__(parent)
        self.setProperty('card', True)
        column = QVBoxLayout(self)
        column.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        column.setSpacing(GAP // 2)
        caption = label(title, 'muted', self)
        if symbol:
            row = QHBoxLayout()
            row.setSpacing(5)
            mark = SymbolView(self)
            mark.icon = semantic_icon(symbol, MUTED)
            row.addWidget(mark)
            row.addWidget(caption)
            column.addLayout(row)
        else:
            column.addWidget(caption)
        self.value_label = label('', 'metric', self)
        column.addWidget(self.value_label)
        self.set_value(value)

    def set_value(self, value):
        assert_gui_thread()
        self.value_label.setText(str(value))


class StatusCard(QFrame):
    """A named resource, DUT or preparation step with a reported state and detail."""
    def __init__(self, title, detail, state, parent=None):
        super().__init__(parent)
        self.setProperty('card', True)
        column = QVBoxLayout(self)
        column.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        column.setSpacing(GAP // 2)
        row = QHBoxLayout()
        heading = label(title, 'section', self)
        heading.setWordWrap(True)
        row.addWidget(heading, 1)
        self.badge = StatusBadge(state, self)
        row.addWidget(self.badge)
        column.addLayout(row)
        self.detail = label(detail, 'muted', self)
        self.detail.setWordWrap(True)
        column.addWidget(self.detail)

    def set_state(self, state):
        self.badge.set_state(state)

"""Shared Qt design tokens and small shell/component stylesheets."""
from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton


BRAND = '#0F766E'
HEADER = '#064E52'
NAVIGATION = '#083C45'
BACKGROUND = '#F5F7FA'
SURFACE = '#FFFFFF'
TEXT = '#1F2937'
MUTED = '#6B7280'
SUCCESS = '#16A34A'
WARNING = '#D97706'
DANGER = '#DC2626'
BORDER = '#E5E7EB'
GAP = 12
CARD_PADDING = 16

SHELL_QSS = f'''
QMainWindow, QWidget#WorkbenchRoot {{ background: {BACKGROUND}; color: {TEXT}; }}
QWidget#GlobalHeader {{ background: {HEADER}; color: white; }}
QWidget#GlobalHeader QLabel {{ color: white; background: transparent; }}
QWidget#GlobalHeader QPushButton {{ color: white; border: none; background: transparent; }}
QWidget#GlobalHeader QPushButton:hover {{ background: {BRAND}; }}
QWidget#GlobalHeader QPushButton:disabled {{ color: #87A9AA; }}
QWidget#GlobalHeader QToolButton {{ color: white; background: transparent; border: none; padding: 7px; }}
QWidget#GlobalHeader QToolButton:disabled {{ color: #87A9AA; }}
QWidget#Sidebar, QTreeView#ProjectNavigation {{ background: {NAVIGATION}; color: #DDECEF; border: none; }}
QWidget#Sidebar QLabel {{ color: #C1D6DA; }}
QWidget#Sidebar QPushButton {{ text-align: left; color: white; border: none; background: transparent; }}
QWidget#Sidebar QPushButton:hover, QWidget#Sidebar QPushButton:checked {{ background: {BRAND}; }}
QTreeView#ProjectNavigation::item {{ padding: 7px 3px; }}
QTreeView#ProjectNavigation::item:selected {{ background: {BRAND}; color: white; }}
QSplitter::handle {{ background: {BACKGROUND}; }}
QSplitter::handle:hover {{ background: #C6DEDC; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
'''

COMPONENT_QSS = f'''
QWidget {{ color: {TEXT}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="section"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="metric"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame[attention="true"] {{ border-color: #F0B7B7; }}
QPushButton {{ background: white; border: 1px solid #CDD6DE; border-radius: 4px; padding: 6px 12px; min-height: 20px; }}
QPushButton:hover {{ border-color: {BRAND}; color: {BRAND}; background: #F0FAF8; }}
QPushButton:disabled {{ color: #9CA3AF; background: #F3F4F6; border-color: {BORDER}; }}
QPushButton[kind="primary"], QPushButton:checked {{ color: white; background: {BRAND}; border-color: {BRAND}; }}
QPushButton[kind="danger"] {{ color: white; background: {DANGER}; border-color: {DANGER}; }}
QToolButton[kind="primary"] {{ color: white; background: {BRAND}; border: 1px solid {BRAND}; border-radius: 4px; padding: 6px 18px; min-height: 20px; }}
QToolButton[kind="primary"]::menu-button {{ width: 20px; border-left: 1px solid white; }}
QToolButton[kind="primary"]:disabled {{ color: #9CA3AF; background: #F3F4F6; border-color: {BORDER}; }}
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled {{ color: #9CA3AF; background: #F3F4F6; border-color: {BORDER}; }}
QPushButton[kind="link"] {{ color: {BRAND}; border: none; background: transparent; padding: 2px; }}
QPushButton[channelTile="true"] {{ padding: 4px 5px; }}
QLineEdit, QComboBox {{ background: white; border: 1px solid #CDD6DE; border-radius: 4px; padding: 5px 8px; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {BRAND}; }}
QProgressBar {{ border: none; background: #E2E7EC; border-radius: 4px; min-height: 8px; max-height: 8px; }}
QProgressBar::chunk {{ background: {BRAND}; border-radius: 4px; }}
QTabBar::tab {{ padding: 10px 14px; border-bottom: 2px solid transparent; background: transparent; }}
QTabBar::tab:selected {{ color: {BRAND}; border-bottom: 2px solid {BRAND}; font-weight: 600; }}
QTabBar::tab:disabled {{ color: #9CA3AF; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BACKGROUND}; border-radius: 5px; }}
QWidget#ConfigurationPage, QWidget#ConfigurationViewport {{ background: {BACKGROUND}; }}
QWidget#SystemHealthDetails {{ background: {SURFACE}; }}
QTableView {{ background: white; border: 1px solid {BORDER}; gridline-color: {BORDER}; selection-background-color: #DFF2EE; selection-color: {TEXT}; }}
QHeaderView::section {{ background: #EEF2F5; border: none; border-bottom: 1px solid {BORDER}; padding: 7px; }}
QPlainTextEdit {{ background: #FAFCFE; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px; }}
QScrollArea {{ background: transparent; border: none; }}
QCheckBox {{ spacing: 6px; }}
'''


def assert_gui_thread():
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('Qt presentation updates require the GUI main thread')


def apply_theme(app):
    app.setFont(QFont('Microsoft YaHei UI', 9))
    app.setStyleSheet(COMPONENT_QSS + SHELL_QSS)


def label(text, role='', parent=None):
    widget = QLabel(str(text), parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty('role', role)
    return widget


def button(text, callback=None, kind='', parent=None):
    widget = QPushButton(text, parent)
    if kind:
        widget.setProperty('kind', kind)
    if callback is not None:
        widget.clicked.connect(callback)
    return widget


def card(parent=None):
    widget = QFrame(parent)
    widget.setProperty('card', True)
    return widget


def status_style(state):
    color, background = ({'running': (SUCCESS, '#E9F9EF'), 'queued': (WARNING, '#FFF5DE'),
                          'completed': (SUCCESS, '#E9F9EF'), 'stopping': (WARNING, '#FFF5DE'),
                          'failed': (DANGER, '#FDECEC'), 'unknown': (WARNING, '#FFF5DE')}
                         .get(state, (MUTED, '#EDF0F4')))
    return f'color: {color}; background: {background}; border-radius: 10px; padding: 3px 10px; font-weight: 600;'


def status_badge(text, state, parent=None):
    widget = label(text, parent=parent)
    widget.setStyleSheet(status_style(state))
    return widget

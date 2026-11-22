"""Qt workbench shell. It owns views, never devices or test execution."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QMainWindow,
    QSizePolicy, QSplitter, QStackedWidget, QToolBar, QTreeView, QVBoxLayout, QWidget)
from src.ui.qt.dashboard import Dashboard
from src.ui.qt.log_panel import LogPanel
from src.ui.qt.project_detail import ProjectDetail
from src.ui.qt.theme import GAP, SUCCESS, MUTED, WARNING, assert_gui_thread, button, label


def state_icon(state):
    image = QPixmap(14, 14)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(SUCCESS if state == 'running' else WARNING if state in ('queued', 'unknown') else MUTED))
    painter.drawEllipse(2, 2, 10, 10)
    painter.end()
    return QIcon(image)


class MainWindow(QMainWindow):
    def __init__(self, projects=(), logs=(), *, demo=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle('DUTPilot · PySide6 迁移原型' + ('（演示）' if demo else ''))
        self.setMinimumSize(800, 440)
        self.projects = ()
        self.selected_project = ''
        self.demo = demo
        self._last_log_height = 180
        self._user_log_split = False
        self.project_status = label('', 'muted')
        self.statusBar().addPermanentWidget(self.project_status)
        toolbar = QToolBar('全局工具栏', self)
        toolbar.setObjectName('GlobalHeader')
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        collapse = toolbar.addAction('☰')
        collapse.setToolTip('折叠 / 展开项目导航')
        collapse.triggered.connect(self.toggle_sidebar)
        mark = label('D')
        mark.setStyleSheet('QLabel { background: #0D9488; color: white; border-radius: 5px; padding: 4px 8px; font-size: 18px; font-weight: 700; }')
        toolbar.addWidget(mark)
        brand = label('DUTPilot')
        brand.setStyleSheet('QLabel { font-size: 19px; font-weight: 700; padding: 0 12px; }')
        toolbar.addWidget(brand)
        toolbar.addWidget(label('统一测试工作台'))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.mode_label = label('演示模式 · 未连接硬件' if demo else '正在加载工作区')
        self.mode_label.setStyleSheet('QLabel { color: #FDE68A; padding: 0 10px; font-weight: 600; }')
        toolbar.addWidget(self.mode_label)
        self.resource_refresh_action = toolbar.addAction('刷新串口/网卡')
        self.resource_refresh_action.setEnabled(False)
        self.resource_refresh_action.setToolTip('只读刷新本机串口和网卡候选')
        self.model_settings_action = toolbar.addAction('AI 模型连接')
        self.model_settings_action.setEnabled(False)
        self.ai_chat_action = toolbar.addAction('Ai助手')
        self.ai_chat_action.setEnabled(False)
        self.devices_action = toolbar.addAction('设备管理')
        self.devices_action.setEnabled(False)
        self.settings_button = button('全局设置 ▾')
        self.settings_button.setEnabled(False)
        toolbar.addWidget(self.settings_button)
        root = QWidget()
        root.setObjectName('WorkbenchRoot')
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.horizontal.setChildrenCollapsible(False)
        root_layout.addWidget(self.horizontal)
        self.sidebar = QWidget()
        self.sidebar.setObjectName('Sidebar')
        self.sidebar.setMinimumWidth(150)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 16, 10, 12)
        side_layout.setSpacing(8)
        self.overview_button = button('▦  总览工作台', self.show_dashboard)
        self.overview_button.setCheckable(True)
        self.overview_button.setChecked(True)
        side_layout.addWidget(self.overview_button)
        side_layout.addWidget(label('项目管理'))
        self.sidebar_search = QLineEdit()
        self.sidebar_search.setPlaceholderText('搜索项目…')
        self.sidebar_search.setClearButtonEnabled(True)
        side_layout.addWidget(self.sidebar_search)
        self.navigation = QTreeView()
        self.navigation.setObjectName('ProjectNavigation')
        self.navigation.setHeaderHidden(True)
        self.navigation.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setIndentation(12)
        self.navigation_model = QStandardItemModel(self)
        self.navigation.setModel(self.navigation_model)
        self.navigation.clicked.connect(self._navigation_selected)
        side_layout.addWidget(self.navigation, 1)
        side_layout.addWidget(label('DUTPilot  ·  测试工作台'))
        self.horizontal.addWidget(self.sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 10)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.pages = QStackedWidget()
        self.dashboard = Dashboard()
        self.detail = ProjectDetail()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.detail)
        self.vertical.addWidget(self.pages)
        self.logs = LogPanel()
        self.logs.setMinimumHeight(60)
        self.vertical.addWidget(self.logs)
        self.vertical.setStretchFactor(0, 1)
        self.vertical.setStretchFactor(1, 0)
        self.vertical.setSizes((620, 180))
        self.vertical.splitterMoved.connect(self._log_dragged)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._fit_log)
        self.dashboard.system_health.layout_changed.connect(lambda: self._layout_timer.start(0))
        self.logs.expanded_changed.connect(self._log_expanded)
        content_layout.addWidget(self.vertical, 1)
        self.horizontal.addWidget(content)
        self.horizontal.setStretchFactor(0, 0)
        self.horizontal.setStretchFactor(1, 1)
        self.horizontal.setSizes((220, 1380))
        self.dashboard.project_requested.connect(self.select_project)
        self.detail.back_requested.connect(self.show_dashboard)
        self.sidebar_search.textChanged.connect(self._filter_navigation)
        self.dashboard.new_button.setEnabled(False)
        self.dashboard.open_button.setEnabled(False)
        self.dashboard.new_button.setToolTip('演示原型不创建或修改真实项目')
        self.dashboard.open_button.setToolTip('项目管理在下一阶段接入原服务')
        self.set_projects(projects)
        self.logs.append_batch(logs)
        self.show_dashboard()

    def _log_dragged(self, position, index):
        self._user_log_split = True
        self._layout_timer.start(0)

    def _fit_log(self):
        current_top, current_log = self.vertical.sizes()
        total = current_top + current_log
        if total <= 0:
            return
        automatic_split = not self._user_log_split and self.logs.expanded
        dashboard_visible = self.pages.currentWidget() is self.dashboard
        health = self.dashboard.system_health
        if dashboard_visible and not health.isHidden():
            health.fit_body(total if automatic_split else current_top)
        if not automatic_split:
            return
        ceiling = int(total * .74)
        if dashboard_visible:
            width = max(1, self.dashboard.cards.viewport().width())
            columns = max(1, min(len(self.projects) or 1, 4, width // 310))
            rows = (len(self.projects) + columns - 1) // columns
            preferred = 180 + min(2, max(1, rows)) * 194
            if not health.isHidden():
                self.dashboard.layout().activate()
                views = self.dashboard.views
                non_project_height = self.dashboard.sizeHint().height() - views.sizeHint().height()
                card_height = self.dashboard.cards.gridSize().height()
                preferred = non_project_height + min(2, max(1, rows)) * card_height
                ceiling = total - max(self.logs.minimumHeight(), self.logs.minimumSizeHint().height())
        else:
            preferred = 510
        top = max(0, min(ceiling, preferred))
        self.vertical.setSizes((top, total - top))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_layout_timer'):
            self._layout_timer.start(0)

    def set_projects(self, projects):
        assert_gui_thread()
        projects = tuple(projects)
        if projects == self.projects:
            return
        self.projects = projects
        self.dashboard.set_projects(projects)
        expanded = [self.navigation.isExpanded(self.navigation_model.index(row, 0))
                    for row in range(self.navigation_model.rowCount())]
        scroll = self.navigation.verticalScrollBar().value()
        self.navigation_model.clear()
        running = [p for p in projects if p.active_task_count]
        other = [p for p in projects if not p.active_task_count]
        for title, entries in (('运行中项目', running), ('其他项目', other)):
            group = QStandardItem(f'{title}（{len(entries)}）')
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.navigation_model.appendRow(group)
            for project in entries:
                item = QStandardItem(state_icon(project.state), project.name)
                item.setData(project.project_id, Qt.ItemDataRole.UserRole)
                item.setToolTip(project.state_text + ' · ' + project.test_type)
                group.appendRow(item)
        for row in range(self.navigation_model.rowCount()):
            group = self.navigation_model.item(row)
            self.navigation.setExpanded(group.index(), expanded[row] if row < len(expanded) else True)
            for child_row in range(group.rowCount()):
                child = group.child(child_row)
                if child.data(Qt.ItemDataRole.UserRole) == self.selected_project:
                    self.navigation.setCurrentIndex(child.index())
        self.navigation.verticalScrollBar().setValue(scroll)
        self._filter_navigation(self.sidebar_search.text())
        self.project_status.setText(('演示快照 · ' if self.demo else '') + f'{len(projects)} 个项目 · ' +
                                    ('未连接真实硬件' if self.demo else f'{sum(p.active_task_count for p in projects)} 个活动任务'))
        if self.selected_project:
            project = next((p for p in projects if p.project_id == self.selected_project), None)
            if project is None:
                self.show_dashboard()
            else:
                self.detail.set_project(project)
                self.logs.set_scope(project.project_id, project.name, project.run_id,
                                    tuple(channel.number for channel in project.channels))
        if hasattr(self, '_layout_timer'):
            self._layout_timer.start(0)

    def closeEvent(self, event):
        coordinator = getattr(self, '_close_coordinator', None)
        if coordinator is not None:
            event.ignore()
            coordinator()
        else:
            event.accept()

    def _filter_navigation(self, text):
        for group_row in range(self.navigation_model.rowCount()):
            group = self.navigation_model.item(group_row)
            for row in range(group.rowCount()):
                self.navigation.setRowHidden(row, group.index(), text.casefold() not in group.child(row).text().casefold())

    def _navigation_selected(self, index):
        identifier = index.data(Qt.ItemDataRole.UserRole)
        if identifier:
            self.select_project(identifier)

    def select_project(self, identifier):
        assert_gui_thread()
        project = next((project for project in self.projects if project.project_id == identifier), None)
        if project is None:
            return
        self.selected_project = identifier
        self.detail.set_project(project)
        self.pages.setCurrentWidget(self.detail)
        self.overview_button.setChecked(False)
        self.logs.set_scope(identifier, project.name, project.run_id,
                            tuple(channel.number for channel in project.channels))
        self._layout_timer.start(0)
        for group_row in range(self.navigation_model.rowCount()):
            group = self.navigation_model.item(group_row)
            for row in range(group.rowCount()):
                item = group.child(row)
                if item.data(Qt.ItemDataRole.UserRole) == identifier:
                    self.navigation.setCurrentIndex(item.index())

    def show_dashboard(self):
        assert_gui_thread()
        self.selected_project = ''
        self.pages.setCurrentWidget(self.dashboard)
        self.overview_button.setChecked(True)
        self.logs.set_scope()
        self._layout_timer.start(0)

    def toggle_sidebar(self):
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        if visible:
            self.horizontal.setSizes((220, max(300, self.width() - 220)))

    def _log_expanded(self, expanded):
        sizes = self.vertical.sizes()
        total = sum(sizes)
        if expanded:
            self.logs.setMinimumHeight(100)
            self.vertical.setSizes((max(100, total - self._last_log_height), self._last_log_height))
        else:
            self._last_log_height = sizes[1]
            self.logs.setMinimumHeight(44)
            self.vertical.setSizes((max(100, total - 44), 44))

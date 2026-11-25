"""Qt workbench shell. It owns views, never devices or test execution."""
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QLineEdit, QMainWindow, QMenu,
    QSplitter, QStackedWidget, QToolBar, QToolButton, QTreeView, QVBoxLayout, QWidget)
from src.models.workbench_presentation import LogView, matches_project_filter
from src.ui.qt.dashboard import Dashboard
from src.ui.qt.log_panel import LogPanel
from src.ui.qt.project_detail import ProjectDetail
from src.ui.qt.project_templates_page import ProjectTemplatesPage
from src.ui.qt.showcase_components import project_status_icon, semantic_icon
from src.ui.qt.theme import GAP, V13_PALETTE, WORKBENCH_QSS, assert_gui_thread, button, label


class MainWindow(QMainWindow):
    project_context_updated = Signal()

    def __init__(self, projects=(), logs=(), *, demo=True, refreshed=True, parent=None):
        super().__init__(parent)
        self._refreshed = refreshed
        self._compact = False
        self._applying_compact = False
        self._user_sidebar = False
        self._user_log_visibility = False
        self.setWindowTitle('DUTPilot（演示）' if demo else 'DUTPilot')
        self.setMinimumSize(800, 440)
        self.projects = ()
        self.selected_project = ''
        self.demo = demo
        self._last_log_height = 180
        self._user_log_split = False
        self.project_status = label('', 'muted')
        self.statusBar().addPermanentWidget(self.project_status)
        header = QWidget(self)
        header.setObjectName('WorkbenchHeader')
        header.setMinimumHeight(48)
        self.setMenuWidget(header)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(4)
        collapse = QToolButton(header)
        collapse.setText('☰')
        collapse.setToolTip('折叠 / 展开项目导航')
        collapse.setAccessibleName(collapse.toolTip())
        collapse.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        collapse.clicked.connect(self.toggle_sidebar)
        row.addWidget(collapse)
        brand = label('DUTPilot')
        brand.setStyleSheet('QLabel { font-size: 19px; font-weight: 700; padding: 0 12px; }')
        row.addWidget(brand)
        row.addWidget(label('综合测试工作台'))
        row.addStretch()
        toolbar = QToolBar('全局工具栏', header)
        toolbar.setObjectName('GlobalHeader')
        toolbar.setMovable(False)
        row.addWidget(toolbar)
        view_menu = QMenu('视图', header)
        toolbar_visibility = toolbar.toggleViewAction()
        toolbar_visibility.setText('显示全局工具栏')
        toolbar_visibility.setShortcut(QKeySequence('Ctrl+Shift+T'))
        toolbar_visibility.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(toolbar_visibility)
        view_menu.addAction(toolbar_visibility)
        view_shortcut = QShortcut(QKeySequence('Alt+V'), self)
        def open_view_menu():
            view_menu.popup(header.mapToGlobal(header.rect().bottomLeft()))
            view_menu.setActiveAction(toolbar_visibility)
        view_shortcut.activated.connect(open_view_menu)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(lambda pos: view_menu.popup(header.mapToGlobal(pos)))
        self.mode_label = label('演示模式 · 未连接硬件' if demo else '正在加载工作区')
        self.mode_label.setStyleSheet('QLabel { color: #FDE68A; padding: 0 10px; font-weight: 600; }')
        self._mode_action = toolbar.addWidget(self.mode_label)
        self.resource_refresh_action = toolbar.addAction('刷新串口/网卡')
        self.resource_refresh_action.setEnabled(False)
        self.resource_refresh_action.setToolTip('只读刷新本机串口和网卡候选')
        self.model_settings_action = toolbar.addAction('AI 模型连接')
        self.model_settings_action.setEnabled(False)
        self.ai_chat_action = toolbar.addAction('Ai助手')
        self.ai_chat_action.setEnabled(False)
        self.devices_action = toolbar.addAction('设备管理')
        self.devices_action.setEnabled(False)
        settings = QMenu('全局设置' if refreshed else '全局设置 ▾', toolbar)
        self.settings_action = settings.menuAction()
        self.settings_action.setEnabled(False)
        toolbar.addAction(self.settings_action)
        self.settings_button = toolbar.widgetForAction(self.settings_action)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if refreshed:
            header.setStyleSheet(WORKBENCH_QSS)
            toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toolbar.setIconSize(QSize(16, 16))
            collapse.setIcon(semantic_icon('navigation', '#DDECEF', on_dark=True))
            for action, symbol in ((self.resource_refresh_action, 'refresh'),
                                   (self.model_settings_action, 'model-link'), (self.ai_chat_action, 'chat'),
                                   (self.devices_action, 'devices')):
                action.setIcon(semantic_icon(symbol, '#DDECEF', on_dark=True))
                control = toolbar.widgetForAction(action)
                control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                control.setAccessibleName(action.text())
            more = toolbar.findChild(QToolButton, 'qt_toolbar_ext_button')
            if more is not None:
                more.setIcon(semantic_icon('more', '#DDECEF', on_dark=True))
                more.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                more.setAccessibleName('更多工具栏操作')
            settings.setIcon(semantic_icon('settings', '#DDECEF', on_dark=True))
            self.settings_button.setIconSize(toolbar.iconSize())
            self.settings_button.setAccessibleName('全局设置')
        root = QWidget()
        root.setObjectName('WorkbenchRoot')
        if refreshed:
            root.setStyleSheet(f'QWidget#WorkbenchRoot {{ background: {V13_PALETTE.background}; }}')
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
        self.overview_button = button('▦  总览工作台', self.show_all_projects)
        if refreshed:
            self.overview_button.setText('总览工作台')
            self.overview_button.setIcon(semantic_icon('grid', '#DDECEF', on_dark=True))
            self.overview_button.setAccessibleName('总览工作台')
        self.overview_button.setCheckable(True)
        self.overview_button.setChecked(True)
        side_layout.addWidget(self.overview_button)
        self.project_management_button = button('项目管理')
        self.project_management_button.setEnabled(False)
        side_layout.addWidget(self.project_management_button)
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
        self.navigation.activated.connect(self._navigation_selected)
        side_layout.addWidget(self.navigation, 1)
        self.templates_button = button('测试模板', self.show_templates)
        self.templates_button.setCheckable(True)
        self.history_button = button('历史记录')
        self.sidebar_settings_button = button('全局设置')
        self.sidebar_devices_button = button('设备管理')
        self.sidebar_devices_button.setToolTip('查看已有串口、网卡及工作区资源占用快照')
        shortcuts = QGridLayout()
        shortcuts.setSpacing(4)
        for index, control in enumerate((self.templates_button, self.history_button,
                                         self.sidebar_devices_button, self.sidebar_settings_button)):
            control.setEnabled(control is self.templates_button)
            shortcuts.addWidget(control, index // 2, index % 2)
        side_layout.addLayout(shortcuts)
        self.horizontal.addWidget(self.sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 10)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.pages = QStackedWidget()
        self.dashboard = Dashboard(refreshed=refreshed)
        self.detail = ProjectDetail(refreshed=refreshed)
        self.templates_page = ProjectTemplatesPage()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.detail)
        self.pages.addWidget(self.templates_page)
        self.vertical.addWidget(self.pages)
        self.logs = LogPanel(global_project_filter=True)
        if refreshed:
            for surface in (self.sidebar, self.dashboard, self.detail, self.logs):
                surface.setStyleSheet(WORKBENCH_QSS)
            self.logs.layout().setContentsMargins(12, 7, 12, 8)
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
        self.templates_page.project_requested.connect(self.select_project)
        self.detail.back_requested.connect(self.show_dashboard)
        self.detail.metric_detail_opened.connect(self._record_metric_detail_open)
        self.sidebar_search.textChanged.connect(self._filter_navigation)
        self.dashboard.new_button.setEnabled(False)
        self.dashboard.open_button.setEnabled(False)
        self.dashboard.new_button.setToolTip('演示原型不创建或修改真实项目')
        self.dashboard.open_button.setToolTip('项目管理在下一阶段接入原服务')
        self.set_projects(projects)
        self.logs.append_batch(logs)
        self.show_dashboard()

    def set_mode_message(self, text):
        self.mode_label.setText(text)
        self._mode_action.setVisible(bool(text))

    def _record_metric_detail_open(self, project, title, has_records):
        result = '已显示记录' if has_records else '暂无可显示的记录'
        entry = LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', project.project_id, project.name,
                        f'[运行概览] 打开{title}详情 · {result}', project.run_id)
        self.logs.append_batch((entry,))

    def _log_dragged(self, position, index):
        self._user_log_split = True
        self._layout_timer.start(0)

    def _fit_log(self):
        if self._refreshed:
            self._fit_log_visibility()
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
        elif self._refreshed:
            log_height = min(190, max(130, round(total * .19)))
            preferred = total - log_height
            ceiling = total
        else:
            preferred = 510
        top = max(0, min(ceiling, preferred))
        self.vertical.setSizes((top, total - top))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_layout_timer'):
            if self._refreshed:
                self._set_compact(event.size().width() < 1000 and event.size().height() < 650)
            self._layout_timer.start(0)

    def _set_compact(self, compact):
        if compact == self._compact:
            return
        self._compact = compact
        self.dashboard.set_compact_metrics(compact)
        if not self._user_sidebar:
            self._set_sidebar_visible(not compact)
        self._fit_log_visibility()

    def _fit_log_visibility(self):
        if self._user_log_visibility or self._user_log_split:
            return
        detail_compact = self.pages.currentWidget() is self.detail and self.height() < 850
        if self.logs.expanded == (self._compact or detail_compact):
            self._applying_compact = True
            try:
                self.logs.toggle_expanded()
            finally:
                self._applying_compact = False

    def set_projects(self, projects):
        assert_gui_thread()
        projects = tuple({project.project_id: project for project in projects}.values())
        if projects == self.projects and self.navigation_model.rowCount():
            return
        self.projects = projects
        self.dashboard.set_projects(projects)
        self.logs.set_global_projects(projects)
        if self.pages.currentWidget() is self.templates_page:
            self.templates_page.set_projects(projects)
        expanded = [self.navigation.isExpanded(self.navigation_model.index(row, 0))
                    for row in range(self.navigation_model.rowCount())]
        scroll = self.navigation.verticalScrollBar().value()
        self.navigation_model.clear()
        running, other = [], []
        for project in projects:
            group = running if matches_project_filter(project, 'active') else other
            group.append(project)
        for title, entries, active_group in (('活动项目', running, True), ('其他项目', other, False)):
            group = QStandardItem(f'{title}（{len(entries)}）')
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if active_group:
                group.setData('active', Qt.ItemDataRole.UserRole + 1)
                group.setToolTip('查看有活动任务的项目，包含等待及收尾中的任务')
            self.navigation_model.appendRow(group)
            for project in entries:
                item = QStandardItem(project_status_icon(project.state), project.name)
                item.setData(project.project_id, Qt.ItemDataRole.UserRole)
                item.setToolTip(project.state_text + ' · ' + project.test_type)
                item.setAccessibleDescription(item.toolTip())
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
                                    ('未连接真实硬件' if self.demo else f'{sum(p.overview_task_count for p in projects)} 个活动任务'))
        if self.selected_project:
            project = next((p for p in projects if p.project_id == self.selected_project), None)
            if project is None:
                self.show_dashboard()
            else:
                self._show_project_context(project)
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
        elif index.data(Qt.ItemDataRole.UserRole + 1) == 'active':
            self.show_dashboard()
            self.dashboard.show_active_projects()

    def select_project(self, identifier):
        assert_gui_thread()
        project = next((project for project in self.projects if project.project_id == identifier), None)
        if project is None:
            return
        if not self._show_project_context(project):
            return
        self._layout_timer.start(0)
        for group_row in range(self.navigation_model.rowCount()):
            group = self.navigation_model.item(group_row)
            for row in range(group.rowCount()):
                item = group.child(row)
                if item.data(Qt.ItemDataRole.UserRole) == identifier:
                    self.navigation.setCurrentIndex(item.index())

    def _show_project_context(self, project):
        self.selected_project = ''
        try:
            self.detail.set_project(project)
            self.logs.set_scope(project.project_id, project.name, project.run_id,
                                tuple(channel.number for channel in project.channels))
            self.pages.setCurrentWidget(self.detail)
        except Exception as error:
            self.show_dashboard()
            self.navigation.setCurrentIndex(self.navigation.rootIndex())
            self.statusBar().showMessage(f'无法显示项目“{project.name}”（{type(error).__name__}），已返回总览')
            return False
        self.overview_button.setChecked(False)
        self.templates_button.setChecked(False)
        self.selected_project = project.project_id
        self.project_context_updated.emit()
        return True

    def show_dashboard(self):
        assert_gui_thread()
        self.selected_project = ''
        self.navigation.clearSelection()
        self.pages.setCurrentWidget(self.dashboard)
        self.overview_button.setChecked(True)
        self.templates_button.setChecked(False)
        self.logs.set_scope()
        self.project_context_updated.emit()
        self._layout_timer.start(0)

    def show_all_projects(self):
        self.show_dashboard()
        self.dashboard.clear_project_filter()

    def show_templates(self):
        assert_gui_thread()
        self.selected_project = ''
        self.navigation.clearSelection()
        self.templates_page.set_projects(self.projects)
        self.pages.setCurrentWidget(self.templates_page)
        self.templates_button.setChecked(True)
        self.overview_button.setChecked(False)
        self.logs.set_scope()
        self.project_context_updated.emit()
        self._layout_timer.start(0)

    def toggle_sidebar(self):
        self._user_sidebar = True
        self._set_sidebar_visible(self.sidebar.isHidden())

    def _set_sidebar_visible(self, visible):
        self.sidebar.setVisible(visible)
        if visible:
            self.horizontal.setSizes((220, max(300, self.width() - 220)))

    def _log_expanded(self, expanded):
        if not self._applying_compact:
            self._user_log_visibility = True
        sizes = self.vertical.sizes()
        total = sum(sizes)
        if expanded:
            self.logs.setMinimumHeight(100)
            self.vertical.setSizes((max(100, total - self._last_log_height), self._last_log_height))
        else:
            self._last_log_height = sizes[1]
            self.logs.setMinimumHeight(44)
            self.vertical.setSizes((max(100, total - 44), 44))

"""Capture offline function-icon evidence from the production views on a private desktop."""
import os
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QHoverEvent, QIcon, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QStyle, QStyleOptionToolButton, QToolBar, QToolButton, QWidget
from qt_test_guard import install_qt_test_scope

from src.ui.qt.main_window import MainWindow
from src.ui.qt.model_settings_dialog import ModelSettingsDialog
from src.ui.qt.project_wizard import ProjectWizard
from src.ui.qt.theme import V13_PALETTE, apply_theme
from src.ui.qt.visual_preview_data import POWER, preview_snapshots


class FunctionIconTests(unittest.TestCase):
    def setUp(self):
        self.scope = install_qt_test_scope(self)
        apply_theme(self.scope.app)
        projects, logs, _ = preview_snapshots()
        self.window = MainWindow(projects, logs)
        self.addCleanup(self.window.close)
        self.window.mode_label.setText('离线模拟')
        # Unbound actions. Only the widgets are enabled, with no business controller.
        for control in (self.window.resource_refresh_action, self.window.model_settings_action,
                        self.window.ai_chat_action, self.window.devices_action, self.window.settings_button):
            control.setEnabled(True)
        self.window.resize(1440, 900)
        self.toolbar = self.window.findChild(QToolBar, 'GlobalHeader')

    def capture(self, widget, scene):
        QTest.qWait(180)
        scale = float(os.environ['QT_SCALE_FACTOR'])
        self.assertAlmostEqual(widget.devicePixelRatioF(), scale)
        output = os.environ.get('DUTPILOT_FUNCTION_ICON_CAPTURE')
        if output:
            path = Path(output) / f'{scene}-{scale:g}.png'
            self.assertTrue(widget.grab().save(str(path)), str(path))

    def test_offline_pages(self):
        window = self.window
        window.show()
        self.capture(window, 'overview')
        self.assertEqual([label.text() for label in window.dashboard.metric_numbers],
                         ['6', '2', '1', '1', '2', '0'])
        window.select_project(POWER)
        self.capture(window, 'detail')
        self.assertEqual(window.detail.tabs.tabText(0), '运行概览')
        window.show_dashboard()
        window.resize(800, 520)
        self.capture(window, 'narrow')
        self.assertEqual(window.dashboard.cards.horizontalScrollBar().maximum(), 0)
        wizard = ProjectWizard(window)
        self.addCleanup(wizard.close)
        wizard.show()
        wizard.test_type.setCurrentIndex(1)
        self.capture(wizard, 'wizard')
        wizard.test_type.setCurrentIndex(0)
        wizard.hide()
        settings = ModelSettingsDialog(window.projects[0], window)
        self.addCleanup(settings.close)
        settings.show()
        QTest.qWait(50)
        self.assertTrue(settings.fields['name'].isVisible())
        self.assertEqual(settings.key.text(), '')

    def test_toolbar_brand_and_sidebar(self):
        window = self.window
        window.show()
        row = window.menuWidget().layout()
        toggle, brand, subtitle = [row.itemAt(i).widget() for i in range(3)]
        self.assertEqual(toggle.accessibleName(), '折叠 / 展开项目导航')
        self.assertEqual((brand.text(), subtitle.text()), ('DUTPilot', '综合测试工作台'))
        self.assertNotIn('D', [label.text() for label in window.menuWidget().findChildren(QLabel)])
        self.assertTrue(all(widget.isVisible() for widget in (toggle, brand, subtitle)))
        self.capture(window, 'overview')
        window.select_project(POWER)
        window.show_dashboard()
        window.resize(800, 520)
        self.capture(window, 'narrow')
        self.assertTrue(window.sidebar.isHidden())
        for width, height in ((800, 520), (1440, 900)):
            window.resize(width, height)
            QTest.qWait(60)
            self.assertTrue(all(widget.isVisible() for widget in (toggle, brand, subtitle)))
            hidden = window.sidebar.isHidden()
            for expected in (not hidden, hidden):
                toggle.setFocus()
                QTest.keyClick(toggle, Qt.Key.Key_Space)
                self.assertEqual(window.sidebar.isHidden(), expected)
            self.assertEqual([number.text() for number in window.dashboard.metric_numbers],
                             ['6', '2', '1', '1', '2', '0'])

    def test_native_window_inherits_01_application_icon(self):
        import ctypes
        from ctypes import wintypes
        from src.ui.qt import application

        app = self.scope.app
        self.addCleanup(app.setWindowIcon, app.windowIcon())
        # The isolation guard already created QApplication and established DPI.
        # Run the launcher's own resource lookup and setWindowIcon on that app.
        with patch.object(application, 'QApplication', return_value=app), patch.object(application, 'QGuiApplication'):
            self.assertIs(application._create_application(), app)
        expected = QIcon(str(Path(__file__).resolve().parents[1] / 'assets/icons/DUTPilot-01.ico'))
        self.assertTrue(expected.availableSizes())
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        QTest.qWait(100)
        for size in expected.availableSizes():
            reference = expected.pixmap(size, 1.0).toImage()
            self.assertEqual(window.windowIcon().pixmap(size, 1.0).toImage(), reference)
        user32 = ctypes.windll.user32
        message = user32.SendMessageW
        message.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        message.restype = ctypes.c_ssize_t
        # WM_GETICON (small and large) with the documented class-icon fallback.
        class_icon = user32.GetClassLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetClassLongW
        class_icon.argtypes = (wintypes.HWND, ctypes.c_int)
        class_icon.restype = ctypes.c_void_p
        # Compare native to native, including Qt/Windows alpha and mask conversion.
        reference_window = QWidget()
        self.addCleanup(reference_window.close)
        reference_window.setWindowIcon(expected)
        reference_window.show()
        QTest.qWait(40)

        def read_icon(widget, kind, class_index):
            hwnd = int(widget.winId())
            handle = message(hwnd, 0x007F, kind, 0) or class_icon(hwnd, class_index)
            self.assertTrue(handle)
            image = QImage.fromHICON(handle)
            self.assertFalse(image.isNull())
            return image

        for kind, class_index in ((0, -34), (1, -14)):
            with self.subTest(native_icon=kind):
                self.assertEqual(read_icon(window, kind, class_index), read_icon(reference_window, kind, class_index))

    def test_actions_states_and_type_metadata(self):
        from src.models.project_profile import TEST_TYPES
        from src.ui.qt.dashboard import METRIC_CAPTIONS, METRIC_SYMBOLS
        from src.ui.qt.showcase_components import SymbolView, semantic_icon, test_type_symbol

        window = self.window
        window.show()
        calls = []
        expected = ((window.resource_refresh_action, '刷新串口/网卡', 'refresh'),
                    (window.model_settings_action, 'AI 模型连接', 'model-link'),
                    (window.ai_chat_action, 'Ai助手', 'chat'),
                    (window.devices_action, '设备管理', 'devices'))
        for action, title, symbol in expected:
            control = self.toolbar.widgetForAction(action)
            self.assertIs(control.defaultAction(), action)
            self.assertEqual((control.text(), control.accessibleName()), (title, title))
            self.assertEqual(control.iconSize(), QSize(16, 16))
            self.assertEqual(control.icon().cacheKey(), semantic_icon(symbol, '#DDECEF', on_dark=True).cacheKey())
            action.triggered.connect(lambda checked=False, key=title: calls.append(key))
            control.setFocus()
            QTest.keyClick(control, Qt.Key.Key_Space)
            self.assertEqual(calls[-1], title)
            for mode, ink in ((QIcon.Mode.Normal, '#ddecef'), (QIcon.Mode.Active, '#ffffff'),
                              (QIcon.Mode.Disabled, '#a1acb9')):
                image = control.icon().pixmap(QSize(16, 16), window.devicePixelRatioF(), mode).toImage()
                self.assertEqual(image.width(), round(16 * window.devicePixelRatioF()))
                self.assertTrue(any(image.pixelColor(x, y).name() == ink and image.pixelColor(x, y).alpha() > 200
                                    for x in range(image.width()) for y in range(image.height())))
        self.assertEqual(calls, [title for _, title, _ in expected])
        self.assertEqual(window.resource_refresh_action.toolTip(), '只读刷新本机串口和网卡候选')
        self.assertEqual(window.settings_button.accessibleName(), '全局设置')
        refresh = self.toolbar.widgetForAction(window.resource_refresh_action)
        self.scope.app.setActiveWindow(window)
        refresh.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        refresh.setFocus(Qt.FocusReason.TabFocusReason)
        self.assertTrue(refresh.hasFocus())
        hovered = refresh.grab().toImage()
        colors = {hovered.pixelColor(x, y).name() for x in range(hovered.width()) for y in range(hovered.height())}
        self.assertIn('#166569', colors)
        self.assertTrue('#8fcfe6' in colors, 'focused toolbar action needs its visible focus border')
        refresh.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        window.resource_refresh_action.setEnabled(False)
        disabled = refresh.grab().toImage()
        self.assertNotEqual(disabled, hovered)
        QTest.keyClick(refresh, Qt.Key.Key_Space)
        self.assertEqual(len(calls), len(expected))
        for frame, caption, symbol in zip(window.dashboard.metric_cards, METRIC_CAPTIONS, METRIC_SYMBOLS.values()):
            self.assertEqual(frame.layout().itemAt(0).layout().itemAt(1).widget().text(), caption)
            self.assertEqual(frame.findChild(SymbolView).icon.cacheKey(), semantic_icon(symbol, V13_PALETTE.muted).cacheKey())
        for key, symbol in (('power_cycle', 'power-cycle'), ('service_aging', 'heartbeat')):
            self.assertEqual(test_type_symbol(key, '其它类型'), symbol)
            self.assertEqual(test_type_symbol('', TEST_TYPES[key]), symbol)
        self.assertIsNone(test_type_symbol('future_type', '自动开关机'))
        self.assertIsNone(test_type_symbol('', '样机升级'))
        power, aging = window.projects[:2]
        unknown = replace(aging, project_id='other', project_type='unsupported', name=power.name)
        window.set_projects((power, aging, unknown))
        for project, symbol in ((aging, 'heartbeat'), (power, 'power-cycle'), (unknown, None)):
            window.select_project(project.project_id)
            view = window.detail.type_symbol
            self.assertEqual(view.isVisible(), bool(symbol))
            if symbol:
                self.assertEqual(view.icon.cacheKey(), semantic_icon(symbol).cacheKey())

        window.show_dashboard()
        for width, height in ((1440, 900), (800, 520)):
            window.resize(width, height)
            QTest.qWait(60)
            board = window.dashboard
            self.assertEqual((window.width(), window.height()), (width, height))
            for card in board.metric_cards:
                self.assertGreaterEqual(card.width(), card.sizeHint().width())
            board.list_button.click()
            self.assertEqual(board.views.currentWidget(), board.table)
            board.cards_button.click()
            self.assertEqual(board.views.currentWidget(), board.cards)

    def test_ready_header_releases_space_and_preserves_status_and_refresh(self):
        from tempfile import TemporaryDirectory
        from src.models.workbench_presentation import WorkspaceHealthView
        from src.services.qt_workspace_adapter import ProjectCommandResult
        from src.ui.qt.workspace_controller import WorkspaceController

        window = MainWindow(demo=False)
        self.addCleanup(window.close)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        adapter = Mock()
        adapter.closed.is_set.return_value = False
        adapter.health_snapshot.return_value = WorkspaceHealthView(None, 0, 32, 0, 0, None, None, None, None)
        controller = WorkspaceController(window, Path(temporary.name), adapter=adapter)
        controller.timer.stop()
        self.addCleanup(controller.app_update.worker.finish_close)
        self.addCleanup(setattr, window, '_close_coordinator', None)
        toolbar = window.findChild(QToolBar, 'GlobalHeader')
        mode = next(action for action in toolbar.actions() if toolbar.widgetForAction(action) is window.mode_label)
        refresh = window.resource_refresh_action
        window.resize(1440, 900)
        window.show()
        QTest.qWait(30)
        self.assertTrue(window.mode_label.isVisible())
        self.assertIn('加载', window.mode_label.text())
        loading_offset = toolbar.actionGeometry(refresh).x()

        def deliver(result):
            adapter.take_updates.return_value = ((), (), (result,))
            controller.poll()
            self.scope.app.processEvents()

        deliver(ProjectCommandResult(1, 'initialization_failed', error='模拟项目服务错误'))
        self.assertEqual(window.mode_label.text(), '项目服务加载失败')
        self.assertEqual(window.statusBar().currentMessage(), '模拟项目服务错误')
        self.assertEqual(window.logs.entries[-1].message, '模拟项目服务错误')
        deliver(ProjectCommandResult(2, 'ready', payload=((), '模拟最近项目读取提示')))
        self.assertEqual(window.statusBar().currentMessage(), '模拟最近项目读取提示')
        self.assertLess(toolbar.actionGeometry(refresh).x(), loading_offset)
        for width, height in ((1440, 900), (800, 520)):
            window.resize(width, height)
            self.capture(window.menuWidget(), f'ready-header-{width}')
            self.assertFalse(mode.isVisible())
            self.assertFalse(window.mode_label.isVisible())
            self.assertEqual(window.mode_label.text(), '')
            row = window.menuWidget().layout()
            self.assertEqual(row.count(), 5)
            self.assertEqual(row.itemAt(2).widget().text(), '综合测试工作台')
            self.assertIsNotNone(row.itemAt(3).spacerItem())
            self.assertIs(row.itemAt(4).widget(), toolbar)
            control = toolbar.widgetForAction(refresh)
            self.assertTrue(control.isVisible() and control.isEnabled())
            adapter.submit.return_value = 3
            QTest.mouseClick(control, Qt.LeftButton)
            adapter.submit.assert_called_with('refresh_inventory')
            self.assertIn('正在读取', window.statusBar().currentMessage())
            result = (ProjectCommandResult(3, 'refresh_inventory', payload={'errors': ()}) if width == 1440
                      else ProjectCommandResult(3, 'refresh_inventory', error='模拟串口枚举失败'))
            deliver(result)
            self.assertEqual(window.statusBar().currentMessage(), result.error or '串口/网卡候选已更新')
        window.resize(1440, 900)
        window.close()
        self.scope.app.processEvents()
        self.assertTrue(window.mode_label.isVisible())
        self.assertIn('收尾', window.mode_label.text())
        adapter.begin_close.assert_called_once()

    def test_assembled_toolbar_menus_and_overflow(self):
        from src.ui.qt.workspace_controller import WorkspaceController

        window = self.window
        adapter = Mock()
        with patch('src.ui.qt.ai_chat_controller.AiChatController.open') as open_chat:
            controller = WorkspaceController(window, Path(os.environ['TEMP']), adapter=adapter)
        window.show()
        controller.timer.stop()
        self.addCleanup(controller.app_update.worker.finish_close)
        self.addCleanup(setattr, window, '_close_coordinator', None)
        window.select_project(POWER)
        controller.ready = True
        controller._sync_actions()
        window.mode_label.setText('离线模拟工作区')
        project = self.toolbar.widgetForAction(controller.menu.menuAction())
        self.assertEqual(project.accessibleName(), '项目')
        self.assertFalse(project.icon().isNull())
        self.assertIs(project.defaultAction().menu(), window.project_management_button.menu())
        self.assertIs(window.settings_button.defaultAction().menu(), window.sidebar_settings_button.menu())
        self.assertIn(controller.open_action, project.defaultAction().menu().actions())
        self.assertIn(controller.update_action, window.settings_action.menu().actions())
        self.capture(window, 'workspace-detail')
        header = window.menuWidget()
        self.assertTrue(project.isVisible())
        self.assertTrue(window.settings_button.isVisible())
        chat = self.toolbar.widgetForAction(window.ai_chat_action)
        for control in (chat, window.settings_button, project, window.project_management_button,
                        window.history_button, window.sidebar_settings_button):
            with self.subTest(chevron=control.text(), location=control.parentWidget().objectName()):
                self.assertTrue(control.isVisible() and control.isEnabled())
                self.assert_menu_chevron(control, (221, 236, 239))
                try:
                    control.setEnabled(False)
                    self.assert_menu_chevron(control, (145, 172, 180))
                finally:
                    control.setEnabled(True)

        option = QStyleOptionToolButton()
        chat.initStyleOption(option)
        arrow = chat.style().subControlRect(QStyle.CC_ToolButton, option, QStyle.SC_ToolButtonMenu, chat)
        main = chat.style().subControlRect(QStyle.CC_ToolButton, option, QStyle.SC_ToolButton, chat)
        self.assertFalse(arrow.isEmpty())
        self.assertFalse(arrow.contains(main.center()))
        QTest.mouseClick(chat, Qt.LeftButton, pos=main.center())
        open_chat.assert_called_once()
        drop_down = chat.menu()
        shown = Mock()
        drop_down.aboutToShow.connect(shown)
        QTimer.singleShot(100, drop_down.close)
        QTest.mouseClick(chat, Qt.LeftButton, pos=arrow.center())
        shown.assert_called_once()
        open_chat.assert_called_once()

        height = header.height()
        def check_single_row():
            y = self.toolbar.mapTo(header, QPoint(0, self.toolbar.height() // 2)).y()
            self.assertLessEqual(abs(y - height // 2), 1)
            self.assertEqual(header.height(), height)
            self.assertEqual(window.centralWidget().y(), height)
        check_single_row()
        window.resize(800, 520)
        QTest.qWait(100)
        more = self.toolbar.findChild(QToolButton, 'qt_toolbar_ext_button')
        self.assertIsNotNone(more)
        self.assertTrue(more.isVisible())
        self.assertFalse(project.isVisible())
        self.assertEqual(more.accessibleName(), '更多工具栏操作')
        self.assertEqual((window.width(), window.height()), (800, 520))
        check_single_row()
        self.capture(window, 'workspace-narrow')
        # Long workspace status can also push the split Ai助手 button into the popup.
        window.mode_label.setText('正在等待测试、串口、项目和更新操作收尾…')
        QTest.qWait(50)
        self.assertFalse(chat.isVisible())
        evidence, = chat.menu().actions()
        for keyboard in (False, True):
            observed = []
            def inspect_overflow():
                popup = self.scope.app.activePopupWidget()
                if popup is None:
                    return
                actions = popup.actions()
                observed.append(controller.menu.menuAction() in actions)
                observed.append(window.settings_button.isVisible() or window.settings_action in actions)
                observed.append(header.height() == height)
                observed.append(window.ai_chat_action in actions and actions.count(evidence) == 1
                                and evidence.isEnabled() == window.ai_chat_action.isEnabled())
                if controller.menu.menuAction() in actions:
                    if keyboard:
                        for _ in range(len(actions) + 1):
                            if popup.activeAction() is controller.menu.menuAction():
                                break
                            QTest.keyClick(popup, Qt.Key_Down)
                        QTest.keyClick(popup, Qt.Key_Right)
                    else:
                        pos = popup.actionGeometry(controller.menu.menuAction()).center()
                        QTest.mouseMove(popup, pos)
                        QTest.mouseClick(popup, Qt.LeftButton, pos=pos)
                    QTest.qWait(300)
                    observed.append(controller.menu.isVisible())
                    controller.menu.close()
                popup.close()
            if keyboard:
                self.scope.app.setActiveWindow(window)
                window.menuWidget().layout().itemAt(0).widget().setFocus()
                for _ in range(30):
                    if more.hasFocus():
                        break
                    QTest.keyClick(self.scope.app.focusWidget(), Qt.Key_Tab)
                self.assertTrue(more.hasFocus())
            QTimer.singleShot(100, inspect_overflow)
            if keyboard:
                QTest.keyClick(more, Qt.Key_Space)
            else:
                QTest.mouseClick(more, Qt.LeftButton)
            QTest.qWait(150)
            self.assertEqual(observed, [True] * 5, keyboard)
        adapter.submit.assert_not_called()

    def assert_menu_chevron(self, control, rgb):
        image = control.grab().toImage()
        scale = image.devicePixelRatio()
        ink_columns = {}
        for x in range(image.width() - round(28 * scale), image.width()):
            ink = []
            for y in range(image.height()):
                red, green, blue, _ = image.pixelColor(x, y).getRgb()
                if max(abs(red - rgb[0]), abs(green - rgb[1]), abs(blue - rgb[2])) <= 34:
                    ink.append(y)
            if ink:
                ink_columns[x] = ink
        self.assertTrue(ink_columns, 'menu chevron must be visible')
        left = right = max(ink_columns)
        while left - 1 in ink_columns:
            left -= 1
        points = [(x, y) for x in range(left, right + 1) for y in ink_columns[x]]
        top, bottom = min(y for _, y in points), max(y for _, y in points)
        width = right - left + 1
        self.assertTrue(round(6 * scale) <= width <= round(10 * scale), (left, right, scale))
        self.assertLessEqual(abs((top + bottom + 1) / 2 - image.height() / 2), 2 * scale)
        center = (left + right) / 2
        self.assertFalse(any(abs(x - center) <= scale and y <= top + scale for x, y in points),
                         'the top of the chevron should be open')
        self.assertTrue(all(abs(x - center) <= 2 * scale for x, y in points if y == bottom),
                        'only the middle of the chevron should reach the bottom')
        self.assertGreaterEqual(image.width() - right - 1, round(3 * scale))
        preceding_ink = max((x for x in ink_columns if x < left), default=image.width() - round(28 * scale) - 1)
        self.assertGreaterEqual(left - preceding_ink - 1, round(3 * scale), 'text must clear the chevron')

    def test_project_module_tab_hover_preserves_bottom_border(self):
        window = self.window
        window.show()
        window.select_project(POWER)
        tabs = window.detail.tabs
        indices = (6, 7, 8)
        for index in indices:
            tabs.setTabEnabled(index, True)
        blank = QPoint(tabs.width() - 10, tabs.height() // 2)
        self.assertEqual(tabs.tabAt(blank), -1)
        idle = tabs.grab().toImage()
        scale = idle.devicePixelRatio()
        divider_x = round(blank.x() * scale)
        divider_rows = [y for y in range(idle.height() - round(3 * scale), idle.height())
                        if idle.pixelColor(divider_x, y).name() != V13_PALETTE.surface.lower()]
        self.assertTrue(divider_rows, 'the tab bar should have a bottom border')
        selected_x = round(tabs.tabRect(tabs.currentIndex()).center().x() * scale)
        selected_underline = [idle.pixelColor(selected_x, y).name() for y in divider_rows]
        self.assertIn(V13_PALETTE.brand.lower(), selected_underline)

        previous = blank
        for index in indices:
            with self.subTest(tab=tabs.tabText(index)):
                rect = tabs.tabRect(index)
                center = rect.center()
                self.scope.app.sendEvent(tabs, QHoverEvent(QEvent.HoverMove, center, tabs.mapToGlobal(center), previous))
                previous = center
                hovered = tabs.grab().toImage()
                sample_x = round((rect.left() + 5) * scale)
                sample_y = round(rect.center().y() * scale)
                self.assertEqual(hovered.pixelColor(sample_x, sample_y).name(), V13_PALETTE.hover_background.lower())
                for y in divider_rows:
                    self.assertEqual(hovered.pixelColor(sample_x, y), idle.pixelColor(divider_x, y),
                                     'hover should leave the bottom border continuous')
                self.assertEqual([hovered.pixelColor(selected_x, y).name() for y in divider_rows], selected_underline)

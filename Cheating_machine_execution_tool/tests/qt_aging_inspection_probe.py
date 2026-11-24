"""Browse the production project detail through a synthetic, offline workspace."""
from contextlib import ExitStack
from dataclasses import replace
import builtins
import io
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton

from qt_test_guard import install_qt_test_scope
from src.models.workbench_presentation import ProjectView
from src.services.qt_workspace_adapter import QtWorkspaceAdapter
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import apply_theme
from src.ui.qt.workspace_controller import WorkspaceController


class AgingInspectionTests(unittest.TestCase):
    def test_browse_inspections_and_switch_projects_without_dispatch_or_writes(self):
        scope = install_qt_test_scope(self)
        apply_theme(scope.app)
        aging = ProjectView('fixture-aging', '合成项目 A', '全业务老化', '合成 DUT', 'idle',
                            '空闲', '—', '', None, '', project_type='service_aging', can_start=True)
        power = replace(aging, project_id='fixture-power', name='合成开关机项目',
                        test_type='自动开关机', project_type='power_cycle')
        other = replace(aging, project_id='fixture-other')
        window = MainWindow((aging, power, other), demo=False)
        self.window = window
        self.addCleanup(setattr, window, '_close_coordinator', None)
        adapter = Mock(spec_set=QtWorkspaceAdapter)
        controller = WorkspaceController(window, Path(__file__).resolve().parents[1], adapter=adapter)
        self.controller = controller
        controller.timer.stop()  # Exclude the workbench's independent periodic polling.
        controller.ready = True
        window.mode_label.setText('')
        window.resize(1180, 760)
        window.show()
        scope.app.processEvents()
        left = Qt.MouseButton.LeftButton
        scale = os.environ.get('QT_SCALE_FACTOR', '1')
        capture = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def save(widget, name, target_scale):
            if capture and scale == target_scale:
                self.assertTrue(widget.grab().save(str(Path(capture) / (name + '.png'))))

        entry = window.detail.inspection_entry

        def select(project):
            # Drive the real navigation row, including two projects with the same name.
            model = window.navigation_model
            for group in range(model.rowCount()):
                parent = model.item(group)
                for i in range(parent.rowCount()):
                    item = parent.child(i)
                    if item.data(Qt.ItemDataRole.UserRole) == project.project_id:
                        tree = window.navigation
                        tree.scrollTo(item.index())
                        QTest.mouseClick(tree.viewport(), left, pos=tree.visualRect(item.index()).center())
                        scope.app.processEvents()
                        self.assertEqual(window.selected_project, project.project_id)
                        controller._sync_actions()
                        return
            self.fail(project.project_id)

        def open_preview():
            self.assertTrue(entry.isVisible())
            QTest.mouseClick(entry, left)
            scope.app.processEvents()
            self.assertTrue(entry.dialog.isVisible())
            return entry.dialog

        attempts = []

        def read_only(original):
            def checked(file, mode='r', *args, **kwargs):
                if any(flag in mode for flag in 'wax+'):
                    attempts.append(('write', mode))
                    raise AssertionError('Browsing tried to write a file')
                return original(file, mode, *args, **kwargs)
            return checked

        with ExitStack() as guards:
            for operation in ('threading.Thread.start', 'subprocess.Popen', 'socket.socket',
                              'PySide6.QtCore.QSettings.setValue', 'PySide6.QtCore.QThread.start',
                              'PySide6.QtCore.QThreadPool.start'):
                blocked = guards.enter_context(patch(operation, side_effect=AssertionError(operation)))
                self.addCleanup(blocked.assert_not_called)
            guards.enter_context(patch('builtins.open', read_only(builtins.open)))
            guards.enter_context(patch('io.open', read_only(io.open)))
            select(aging)
            self.assertTrue(window.detail.aging_status.isVisible())
            self.assertTrue(window.detail.start_button.isEnabled())
            save(window, 'project-entry', '1')
            dialog = open_preview()
            self.assertIn('界面预览 / 采集未接入', [w.text() for w in dialog.findChildren(QLabel)])
            self.assertFalse(dialog.findChildren(QPushButton))
            self.assertFalse(dialog.findChildren(QTimer))
            self.assertEqual(dialog.stage.currentText(), '开始基线')
            self.assertAlmostEqual(dialog.devicePixelRatioF(), float(scale), places=2)
            save(dialog, 'overview', '1')
            items = ('进程清单', '状态与占用', '文件描述符', '系统可用内存', 'Slab 内存', '套接字', 'CPU 使用率')
            fields = (('进程列表', 'PID', '进程数量', '疑似消失线索', '疑似重启线索'), ('线程数', 'VmSize', 'VmRSS'),
                      ('实际打开的 FD 数', 'FD 类型', 'FDSize'), ('MemAvailable', '趋势'),
                      ('Slab', 'SReclaimable', 'SUnreclaim', '趋势'),
                      ('TCP', 'UDP', 'Unix', '监听', '方向', '数量变化'), ('CPU 使用率', '趋势'))
            self.assertEqual([dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())],
                             ['进程', '内存', '网络', 'CPU'])
            for width in (840, 480):
                dialog.resize(width, 480)
                scope.app.processEvents()
                self.assertEqual(dialog.width(), width)
                self.assertEqual(dialog.compact_items.isVisible(), width == 480)
                for i, title in enumerate(items):
                    if width == 480:
                        dialog.compact_items.setFocus()
                        QTest.keyClick(dialog.compact_items, Qt.Key.Key_Home)
                        for _ in range(i):
                            QTest.keyClick(dialog.compact_items, Qt.Key.Key_Down)
                    else:
                        leaf = dialog.leaves[i]
                        dialog.tree.scrollToItem(leaf)
                        QTest.mouseClick(dialog.tree.viewport(), left, pos=dialog.tree.visualItemRect(leaf).center())
                    self.assertTrue(dialog.title.text().endswith(title))
                    tabs = dialog.views
                    QTest.mouseClick(tabs, left, pos=tabs.tabRect(0).center())
                    QTest.keyClick(dialog.stage, Qt.Key.Key_Home)
                    for j, stage in enumerate(('开始基线', '运行中', '结束')):
                        if j:
                            QTest.keyClick(dialog.stage, Qt.Key.Key_Down)
                        self.assertTrue(dialog.stage.isVisible())
                        self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), stage)
                        for row in range(dialog.table.rowCount()):
                            self.assertEqual(dialog.table.item(row, 1).text(), '无数据')
                    QTest.mouseClick(tabs, left, pos=tabs.tabRect(1).center())
                    scope.app.processEvents()
                    table = dialog.table
                    self.assertTrue(dialog.stage.isHidden())
                    self.assertEqual([table.horizontalHeaderItem(c).text() for c in range(table.columnCount())],
                                     ['观察字段', '开始基线', '运行中', '结束'])
                    labels = ' '.join(table.item(r, 0).text() for r in range(table.rowCount()))
                    for required in fields[i]:
                        self.assertIn(required, labels)
                    for row in range(table.rowCount()):
                        for col in (1, 2, 3):
                            self.assertEqual(table.item(row, col).text(), '无数据')
                    self.assertEqual(table.horizontalScrollBar().maximum(), 0, (width, title))
                    if i == 4 and width == 840:
                        save(dialog, 'slab-comparison', '1.25')
                    if i == 5 and width == 480:
                        save(dialog, 'narrow-sockets', '1.5')

            # A routine same-project refresh preserves the view. A different
            # identity, even with the same display name, must retire it.
            window.set_projects((replace(aging, elapsed='— · 合成刷新'), power, other))
            self.assertIs(entry.dialog, dialog)
            self.assertEqual(dialog.views.currentIndex(), 1)
            select(other)
            self.assertIsNone(entry.dialog)
            fresh = open_preview()
            self.assertEqual(fresh.views.currentIndex(), 0)
            self.assertEqual(fresh.compact_items.currentIndex(), 0)
            select(power)
            self.assertTrue(entry.isHidden())
            self.assertIsNone(entry.dialog)
            entry.click()
            self.assertIsNone(entry.dialog)
            self.assertTrue(window.detail.start_button.isEnabled())
            select(aging)
            window.resize(800, 550)
            scope.app.processEvents()
            self.assertEqual(window.width(), 800)
            self.assertTrue(window.rect().contains(entry.mapTo(window, QPoint(0, 0))))
            self.assertTrue(window.rect().contains(entry.mapTo(window, entry.rect().bottomRight())))
            open_preview()
            window.show_dashboard()
            self.assertIsNone(entry.dialog)
            self.assertFalse(attempts)
            self.assertEqual(adapter.mock_calls, [])

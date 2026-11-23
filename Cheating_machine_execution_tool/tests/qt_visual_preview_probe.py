"""Windows native layout and shared-snapshot checks for the isolated visual preview."""
import os
from itertools import combinations
from pathlib import Path
import unittest

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox
from qt_test_guard import install_qt_test_scope

from dataclasses import replace

from src.ui.qt.dashboard import WorkbenchCardDelegate
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import apply_theme
from src.ui.qt.visual_preview import VisualPreview
from src.ui.qt.visual_preview_data import AGING, POWER, preview_snapshots


class VisualPreviewTests(unittest.TestCase):
    def setUp(self):
        self.scope = install_qt_test_scope(self)
        apply_theme(self.scope.app)
        self.window = VisualPreview()
        self.addCleanup(self.window.close)
        self.window.resize(1440, 900)
        self.window.show()
        self.scope.app.processEvents()

    def test_layout_and_evidence_match_in_both_versions(self):
        before, after = self.window.original, self.window.proposed
        self.assertIs(before.projects[0], after.projects[0])
        self.assertIsInstance(after.dashboard.cards.itemDelegate(), WorkbenchCardDelegate)
        self.assertNotIsInstance(before.dashboard.cards.itemDelegate(), WorkbenchCardDelegate)
        for size in ((1440, 900), (800, 520)):
            self.window.resize(*size)
            for variant, workbench in enumerate((before, after)):
                self.window.variants.button(variant).click()
                self.assertEqual(self.window.pages.currentWidget(), workbench)
                for name, identifier in (('overview', ''), ('power', POWER), ('aging', AGING)):
                    with self.subTest(size=size, version=variant, page=name):
                        self.window.show_page(identifier)
                        workbench.vertical.setSizes((size[1] - 190, 147))
                        QTest.qWait(250)
                        self.assertEqual((self.window.width(), self.window.height()), size)
                        self._capture(workbench, size, variant, name)
                        self.assertGreaterEqual(workbench.logs.height(), 100 if size[0] > 800 else 44)
                        if variant and size[0] == 800:
                            self.assertTrue(workbench.sidebar.isHidden())
                            self.assertFalse(workbench.logs.expanded)
                        self.assertEqual(workbench.logs.scope_id, identifier)
                        if identifier == POWER:
                            detail = workbench.detail
                            self.assertIn('320 / 500', detail.progress_text.text())
                            self.assertEqual(detail.test_type_panel.ring.value, 64)
                            self.assertEqual(detail.test_type_panel.table.item(2, 7).text(), '2')
                            self.assertIn('异常', detail.channels.tiles[2].text())
                            if variant:
                                self.assertIn('PON 注册超时', detail.channels.tiles[2].text())
                            self.assertTrue(detail.stop_button.isVisible())
                            self.assertLessEqual(detail.stop_button.mapTo(workbench, detail.stop_button.rect().topRight()).x(),
                                                 workbench.width())
                        elif identifier == AGING:
                            panel = workbench.detail.test_type_panel
                            self.assertIn('27时46分', panel.title.text())
                            self.assertTrue(panel.ring.isHidden())
                            self.assertEqual([panel.table.item(n, 2).text() for n in range(4)],
                                             ['正常', '异常', '未知', '未接入'])
                            self.assertEqual(panel.presence.item(3, 1).text(), '未接入')
                            self.assertEqual(panel.table.item(1, 3).text(), '现场采集')
                            self.assertIn('已记录 IPTV 异常', panel.inspections.text())
                            self.assertTrue(workbench.detail.stop_button.isVisible())
                        else:
                            self.assertEqual(workbench.dashboard.proxy.rowCount(), 6)
                            self.assertTrue(workbench.dashboard.system_health.isVisible())
                            if variant:
                                metrics = workbench.dashboard.metric_cards
                                for metric in metrics:
                                    self.assertGreaterEqual(metric.value_label.height(), metric.value_label.sizeHint().height())
                                    self.assertLess(metric.geometry().bottom(), workbench.dashboard.search.geometry().top())
                                for first, second in combinations(metrics, 2):
                                    self.assertFalse(first.geometry().intersects(second.geometry()))

    def _capture(self, workbench, size, variant, page):
        directory = os.environ.get('DUTPILOT_VISUAL_PREVIEW_DIRECTORY')
        if not directory:
            return
        scale = workbench.devicePixelRatioF()
        if (size == (1440, 900) and scale == 1) or (size == (800, 520) and scale == 1.5 and variant):
            suffix = '-narrow' if size[0] == 800 else ''
            version = 'after' if variant else 'before'
            path = Path(directory) / f'{page}-{version}{suffix}.png'
            self.assertTrue(workbench.grab().save(str(path)), str(path))
            if page == 'aging' and variant and not suffix:
                scroll = workbench.detail.execution_scroll.verticalScrollBar()
                position = scroll.value()
                scroll.setValue(scroll.maximum())
                self.scope.app.processEvents()
                path = Path(directory) / 'aging-after-observations.png'
                self.assertTrue(workbench.grab().save(str(path)), str(path))
                scroll.setValue(position)

    def test_switch_filters_and_cancel_simulated_stop(self):
        workbench = self.window.proposed
        workbench.dashboard.search.setText('兼容性')
        self.assertEqual(workbench.dashboard.proxy.rowCount(), 1)
        workbench.dashboard.list_button.click()
        self.assertEqual(workbench.dashboard.views.currentIndex(), 1)
        self.window.show_page(POWER)
        snapshots = tuple(workbench.projects)
        workbench.detail.stop_button.click()
        self.scope.app.processEvents()
        dialog = workbench.findChild(QDialog)
        self.assertTrue(dialog.isVisible())
        cancel = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
        self.assertTrue(cancel.isDefault())
        cancel.click()
        self.scope.app.processEvents()
        self.assertEqual(workbench.projects, snapshots)
        self.window.variants.button(0).click()
        self.assertEqual(self.window.original.selected_project, POWER)
        self.assertEqual(self.window.original.logs.scope_id, POWER)
        self.window.variants.button(1).click()
        self.assertEqual(workbench.detail.project.project_id, POWER)
        self.window.resize(800, 520)
        self.scope.app.processEvents()
        self.assertFalse(workbench.logs.expanded)
        workbench.logs.fold_button.click()
        self.assertTrue(workbench.logs.expanded)
        self.assertFalse(workbench.logs.text.isHidden())

    def test_formal_window_refreshes_live_snapshots_and_keeps_manual_controls(self):
        projects, logs, health = preview_snapshots()
        formal = MainWindow(projects, logs, demo=False)
        formal.mode_label.setText('布局验证 · 模拟快照')
        self.addCleanup(formal.close)
        formal.resize(1440, 900)
        formal.show()
        QTest.qWait(30)
        self.assertIsInstance(formal.dashboard.cards.itemDelegate(), WorkbenchCardDelegate)
        system = formal.dashboard.system_health
        system.show()
        self.assertTrue(system.scroll.isHidden())
        system.update_status(health, 0.2, 22, 1, projects)
        self.assertIn('网卡 8', system.resource_summary.text())
        new_health = replace(health, resources=replace(health.resources, adapters=2))
        system.update_status(new_health, 0.3, 22, 1, projects)
        self.assertIn('网卡 2', system.resource_summary.text())
        self._capture_formal(formal, 'overview')
        formal.select_project(POWER)
        detail = formal.detail
        panel = detail.test_type_panel
        self.assertIs(panel.ring.parentWidget(), detail.summary)
        self.assertEqual(panel.ring.value, detail.progress.value())
        new_channels = tuple(replace(channel, cycle=channel.cycle + 10,
                                     stage='PON 等待重新检测' if channel.number == 3 else channel.stage)
                             for channel in projects[0].channels)
        new_rows = [dict(row, cycle=row['cycle'] + 10, completed=channel.cycle, success=row['success'] + 10,
                         stage=channel.stage)
                    for row, channel in zip(projects[0].test_overview['rows'], new_channels)]
        updated = replace(projects[0], channels=new_channels, progress=66, success_count=sum(row['success'] for row in new_rows),
                          progress_text='整批已完成 330 / 500 轮',
                          test_overview=dict(projects[0].test_overview, rows=new_rows))
        formal.set_projects((updated, *projects[1:]))
        self.assertIn('PON 等待重新检测', detail.channels.tiles[2].text())
        self.assertEqual(panel.ring.value, 66)
        self.assertEqual(panel.ring.value, detail.progress.value())
        self.assertEqual(formal.logs.scope_id, POWER)
        self._capture_formal(formal, 'power')
        formal.select_project(AGING)
        self.assertTrue(panel.ring.isHidden())
        self.assertTrue(panel.presence_title.isVisible())
        self.assertFalse(detail.progress.isVisible())
        self._capture_formal(formal, 'aging')
        formal.resize(800, 440)
        QTest.qWait(30)
        self.assertTrue(formal.sidebar.isHidden())
        self.assertFalse(formal.logs.expanded)
        formal.toggle_sidebar()
        formal.logs.fold_button.click()
        formal.resize(1440, 900)
        QTest.qWait(30)
        formal.resize(800, 440)
        QTest.qWait(30)
        self.assertFalse(formal.sidebar.isHidden())
        self.assertTrue(formal.logs.expanded)
        self.assertEqual(formal.logs.scope_id, AGING)

    def _capture_formal(self, workbench, name):
        directory = os.environ.get('DUTPILOT_VISUAL_WORKBENCH_DIRECTORY')
        if directory and workbench.devicePixelRatioF() == 1:
            QTest.qWait(220)
            path = Path(directory) / f'formal-{name}.png'
            self.assertTrue(workbench.grab().save(str(path)), str(path))

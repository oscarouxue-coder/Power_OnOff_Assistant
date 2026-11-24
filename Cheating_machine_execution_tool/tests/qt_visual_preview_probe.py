"""Windows native layout and shared-snapshot checks for the isolated visual preview."""
import json
import os
from itertools import combinations
from pathlib import Path
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel
from qt_test_guard import install_qt_test_scope

from dataclasses import replace

from src.models.workbench_presentation import LogView
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


class ProjectOverviewTests(unittest.TestCase):
    def setUp(self):
        self.scope = install_qt_test_scope(self)
        apply_theme(self.scope.app)
        projects, logs, _ = preview_snapshots()
        self.power, self.aging = projects[:2]
        self.idle = replace(projects[4], name='离线模拟 · 开关机待启动',
                            channels=tuple(replace(channel, state='unknown', cycle=None, stage='',
                                                   detail='', can_resume=False) for channel in self.power.channels))
        self.window = MainWindow((self.idle, self.power, self.aging), logs, demo=True)
        self.window.mode_label.setText('离线界面验证 · 模拟数据')
        self.addCleanup(self.window.close)
        scale = self.window.devicePixelRatioF()
        self.window.resize(round(1920 / scale), round(1080 / scale))
        self.window.show()
        QTest.qWait(50)

    @staticmethod
    def _values(metrics):
        return tuple(frame.value_label.text() for frame in metrics.cards)

    def test_power_metric_details_open_by_mouse_and_keyboard(self):
        self.window.select_project(self.power.project_id)
        detail = self.window.detail
        elapsed, success, failure, attention = detail.cycle_metrics.cards
        QTest.mouseClick(elapsed, Qt.MouseButton.LeftButton)
        self.assertIsNone(detail._metric_dialog)

        position = success.value_label.mapTo(success, success.value_label.rect().center())
        self.assertTrue(success.rect().contains(position))
        self.assertIsNone(success.childAt(position))
        QTest.mouseClick(success, Qt.MouseButton.LeftButton, pos=position)
        dialog = detail._metric_dialog
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isModal())
        self.assertIn('成功详情', dialog.windowTitle())
        self.assertLessEqual(dialog.width(), dialog.screen().availableGeometry().width())
        self.assertEqual(dialog.table.rowCount(), 8)
        self.assertEqual(dialog.table.item(0, 1).text(), 'CH01')
        self.assertEqual(dialog.table.item(0, 2).text(), '324')
        self.assertEqual(dialog.record_text.toPlainText(), '等待启动完成')
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertIsNone(detail._metric_dialog)

        QTest.keyClick(failure, Qt.Key.Key_Return)
        dialog = detail._metric_dialog
        self.assertTrue(dialog.isVisible())
        self.assertIn('失败详情', dialog.windowTitle())
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual([dialog.table.item(0, col).text() for col in range(1, 4)], ['CH03', '1', '321'])
        self.assertEqual(dialog.record_text.toPlainText(), 'PON 注册超时')
        close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Close)
        QTest.mouseClick(close, Qt.MouseButton.LeftButton)
        self.assertIsNone(detail._metric_dialog)

        QTest.keyClick(attention, Qt.Key.Key_Space)
        dialog = detail._metric_dialog
        self.assertIn('当前异常详情', dialog.windowTitle())
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 1).text(), 'CH03')
        self.assertEqual(dialog.record_text.toPlainText(), 'PON 注册超时')
        self.assertEqual(self.window.logs.entries[-1].project_id, self.power.project_id)
        self.assertIn('打开当前异常详情 · 已显示记录', self.window.logs.entries[-1].message)
        self.window.select_project(self.aging.project_id)
        self.assertIsNone(detail._metric_dialog)
        self.assertFalse(detail.cycle_metrics.isVisible())

    def test_power_metric_details_use_current_run_and_report_empty_or_unknown(self):
        self.window.select_project(self.power.project_id)
        detail = self.window.detail
        _, success, failure, attention = detail.cycle_metrics.cards
        recovered = replace(self.power, attention_count=0, success_count=None, failure_count=None,
                            channels=tuple(replace(c, state='success') for c in self.power.channels))
        self.window.set_projects((self.idle, recovered, self.aging))
        self.assertEqual(success.value_label.text(), '—')
        QTest.mouseClick(success, Qt.MouseButton.LeftButton)
        self.assertEqual(detail._metric_dialog.table.rowCount(), 8)
        QTest.mouseClick(failure, Qt.MouseButton.LeftButton)
        self.assertEqual(detail._metric_dialog.table.item(0, 1).text(), 'CH03')
        self.assertEqual(detail._metric_dialog.record_text.toPlainText(), 'PON 注册超时')
        QTest.mouseClick(attention, Qt.MouseButton.LeftButton)
        self.assertEqual(detail._metric_dialog.table.rowCount(), 0)

        unknown = replace(recovered, run_id='SAMPLE-UPGRADE', attention_count=1, state='unknown',
                          state_text='结果未知', task_stage='结果待核实', pipeline_detail='升级回执中断',
                          channels=tuple(replace(c, state='unknown') for c in self.power.channels))
        self.window.set_projects((self.idle, unknown, self.aging))
        self.assertIsNone(detail._metric_dialog)
        QTest.mouseClick(failure, Qt.MouseButton.LeftButton)
        self.assertEqual(detail._metric_dialog.table.rowCount(), 0)
        self.assertIn('暂无可显示的记录', self.window.logs.entries[-1].message)
        QTest.mouseClick(attention, Qt.MouseButton.LeftButton)
        dialog = detail._metric_dialog
        self.assertEqual([dialog.table.item(0, col).text() for col in range(3)], ['任务', '—', '结果待核实'])
        self.assertEqual(dialog.record_text.toPlainText(), '升级回执中断')
        without_reason = replace(unknown, pipeline_detail='', progress_text='查看样机升级窗口')
        self.window.set_projects((self.idle, without_reason, self.aging))
        self.assertIs(detail._metric_dialog, dialog)
        QTest.mouseClick(attention, Qt.MouseButton.LeftButton)
        self.assertIsNot(detail._metric_dialog, dialog)
        self.assertEqual(detail._metric_dialog.record_text.toPlainText(), '暂无具体原因')
        self.window.show_dashboard()
        self.assertIsNone(detail._metric_dialog)

    def test_running_overview_distinguishes_power_and_continuous_aging(self):
        detail = self.window.detail
        panel = detail.test_type_panel
        evidence = {}
        for name, project in (('idle', self.idle), ('power-running', self.power), ('aging-running', self.aging)):
            with self.subTest(scene=name):
                self.window.select_project(project.project_id)
                detail.execution_scroll.verticalScrollBar().setValue(0)
                QTest.qWait(100)
                self.assertIs(self.window.pages.currentWidget(), detail)
                self.assertEqual(detail.config_scroll.isVisible(), detail.width() >= 1100)
                self.assertEqual(self.window.logs.expanded, self.window.height() >= 850)
                self.assertEqual(detail.execution_scroll.horizontalScrollBar().maximum(), 0)
                self.assertLessEqual(detail.execution.width(), detail.execution_scroll.viewport().width())
                labels = {widget.text() for widget in detail.execution.findChildren(QLabel)}
                self.assertTrue(labels.isdisjoint({'近期事件', '近期事件 · 当前任务', '暂无项目事件', '暂无当前任务事件'}))
                self.assertEqual(detail.execution_layout.indexOf(detail.test_type_panel),
                                 detail.execution_layout.indexOf(detail.aging_status) + 1)
                if name != 'aging-running':
                    self.assertTrue(panel.title.parentWidget().isHidden())
                    self.assertTrue(panel.table.isVisible())
                    self.assertEqual(panel.table.geometry().top(), panel.contentsRect().top())
                    self.assertEqual(panel.table.columnCount(), 9)
                if name == 'idle':
                    self.assertEqual(self._values(detail.cycle_metrics), ('—', '—', '—', '—'))
                    self.assertIsNone(detail.test_type_panel.ring.value)
                    self.assertTrue(detail.progress.isHidden())
                    self.assertIn('VLAN116 / COM16', detail.channels.tiles[0].text())
                elif name == 'power-running':
                    self.assertEqual(self._values(detail.cycle_metrics), ('06:21:38', self.power.success_text, '1 轮', '1'))
                    self.assertEqual(detail.progress.value(), detail.test_type_panel.ring.value)
                    self.assertIn('320 / 500', detail.progress_text.text())
                    self.assertIn('CH03 PON 注册超时', detail.stage.text())
                    self.assertEqual(panel.table.rowCount(), 8)
                    self.assertEqual(panel.table.item(2, 7).text(), '2')
                else:
                    self.assertTrue(panel.title.isVisible())
                    self.assertIn('全业务老化 · 监测中', panel.title.text())
                    self.assertTrue(panel.record_button.isVisible())
                    self.assertTrue(panel.history_button.isVisible())
                    metrics = self._values(detail.aging_metrics)
                    self.assertEqual(metrics[:5], ('1 天 03:46:00', '3', '1', '1', '1'))
                    self.assertNotEqual(metrics[-1], '—')
                    self.assertTrue(detail.cycle_metrics.isHidden())
                    self.assertTrue(detail.test_type_panel.ring.isHidden())
                    self.assertTrue(detail.progress.isHidden())
                    self.assertTrue(detail.aging_trend.isVisible())
                    self.assertIn('暂无', detail.aging_trend.text())
                    self.assertEqual(detail.test_type_panel.presence.rowCount(), 4)
                    self.assertEqual(detail.test_type_panel.table.rowCount(), 4)
                metrics = detail.aging_metrics if name == 'aging-running' else detail.cycle_metrics
                for first, second in combinations(metrics.cards, 2):
                    self.assertFalse(first.geometry().intersects(second.geometry()))
                self.assertTrue(all(metrics.rect().contains(frame.geometry()) for frame in metrics.cards))
                self._capture_overview(name, evidence)
                viewport = detail.execution_scroll.viewport()
                if name == 'power-running' and self.window.devicePixelRatioF() >= 1.5:
                    detail.table_button.click()
                    QTest.qWait(35)
                    self.assertEqual(detail.channel_model.rowCount(), 8)
                    detail.execution_scroll.ensureWidgetVisible(detail.channel_table, 0, 2)
                    self.scope.app.processEvents()
                    table = detail.channel_table
                    self.assertTrue(viewport.rect().intersects(table.rect().translated(table.mapTo(viewport, table.rect().topLeft()))))
                    self._capture_overview('power-running-list', evidence)
                    detail.matrix_button.click()
                if name == 'aging-running':
                    table = detail.test_type_panel.table
                    detail.execution_scroll.ensureWidgetVisible(table, 0, 2)
                    self.scope.app.processEvents()
                    self.assertTrue(viewport.rect().intersects(table.rect().translated(table.mapTo(viewport, table.rect().topLeft()))))

        self.window.show_dashboard()
        QTest.qWait(40)
        self.assertTrue(self.window.logs.expanded)
        self.window.select_project(self.aging.project_id)
        QTest.qWait(40)

        self.window.set_projects((self.idle, self.power, replace(self.aging, state='idle', state_text='待启动',
                                                                 run_id='', test_overview={})))
        self.assertEqual(self._values(detail.aging_metrics), ('—',) * 6)
        self.assertTrue(detail.aging_empty.isVisible())
        self.assertFalse(detail.test_type_panel.health_cards.isVisible())
        self.assertTrue(detail.summary.isHidden())
        self.window.resize(800, 520)
        QTest.qWait(40)
        self.assertTrue(detail.config_scroll.isHidden())
        self.assertLessEqual(detail.execution.width(), detail.execution_scroll.viewport().width())
        self.assertLess(detail.aging_metrics.columns, len(detail.aging_metrics.cards))
        QTest.mouseClick(detail.config_toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(detail.config_scroll.isVisible())
        self.window.logs.fold_button.click()
        self.window.resize(900, 540)
        QTest.qWait(40)
        self.assertTrue(detail.config_scroll.isVisible())
        self.assertTrue(self.window.logs.expanded)

        self.window.show_dashboard()
        QTest.qWait(40)
        self.assertTrue(self.window.logs.expanded)

        if evidence:
            scale = self.window.devicePixelRatioF()
            (Path(os.environ['DUTPILOT_QT_MONITOR_CAPTURE']) / f'geometry-{scale:g}.json').write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def _capture_overview(self, name, evidence):
        output = os.environ.get('DUTPILOT_QT_MONITOR_CAPTURE')
        if not output:
            return
        image = self.window.grab()
        scale = image.devicePixelRatio()
        path = Path(output) / f'{name}-{scale:g}.png'
        self.assertTrue(image.save(str(path)), str(path))
        evidence[name] = dict(file=str(path), logical_size=[self.window.width(), self.window.height()],
                              pixels=[image.width(), image.height()], scale=scale, logs_expanded=self.window.logs.expanded,
                              configuration_visible=self.window.detail.config_scroll.isVisible())

    def test_project_log_preserves_raw_lines_and_current_task_scope(self):
        self.window.select_project(POWER)
        log = self.window.logs
        log.scope.setCurrentIndex(log.scope.findData('run'))
        entry = LogView('14:40:00', 'INFO', POWER, self.power.name, '本批设备阶段更新', self.power.run_id)
        log.append_batch((replace(entry, message='旧任务消息', run_id='old'),
                          replace(entry, message='其他项目消息', project_id=AGING), entry,
                          replace(entry, message='原始串口模拟行', raw=True)))
        text = log.text.toPlainText()
        self.assertIn(entry.message, text)
        self.assertIn('原始串口模拟行', text.splitlines())
        self.assertNotIn('旧任务消息', text)
        self.assertNotIn('其他项目消息', text)
        batch_entry = replace(entry, message='批次关联事件', run_id='job-receipt', batch_id=self.power.run_id)
        log.append_batch((batch_entry,))
        self.assertIn(batch_entry.message, log.text.toPlainText())
        log.search.setText('无匹配')
        self.assertEqual(log.text.toPlainText(), '')
        log.search.clear()
        self.window.select_project(AGING)
        self.assertIn('在线心跳', log.text.toPlainText())
        self.assertNotIn(entry.message, log.text.toPlainText())
        log.scope.setCurrentIndex(log.scope.findData('run'))
        self.window.set_projects((self.idle, self.power, replace(self.aging, run_id='new-aging-run')))
        self.assertEqual(log.scope.currentData(), 'run')
        self.assertEqual(log.text.toPlainText(), '')
        self.window.select_project(POWER)
        log.clear_display()
        self.assertEqual(log.text.toPlainText(), '')


class DashboardPriorityTests(unittest.TestCase):
    def setUp(self):
        self.scope = install_qt_test_scope(self)
        apply_theme(self.scope.app)
        projects, logs, _ = preview_snapshots()
        self.power, self.aging, self.queued, self.done, self.idle, self.pending = projects
        self.idle = replace(self.idle, name=self.aging.name, progress=95)
        self.pending = replace(self.pending, project_type='service_aging')
        self.unknown = replace(self.idle, project_id='awaiting-review', name='状态另待核实',
                               state='unknown', state_text='待核实', unresolved_tasks=True)
        self.projects = (self.idle, self.done, self.pending, self.unknown, self.queued, self.power, self.aging)
        self.window = MainWindow(self.projects, logs, demo=True)
        self.addCleanup(self.window.close)
        self.window.resize(1440, 870)
        self.window.show()
        QTest.qWait(60)
        self.board = self.window.dashboard

    def _visible_ids(self):
        proxy = self.board.proxy
        return [proxy.index(row, 0).data(Qt.ItemDataRole.UserRole).project_id for row in range(proxy.rowCount())]

    def _index_for(self, identifier, column=0):
        return self.board.proxy.index(self._visible_ids().index(identifier), column)

    def test_dashboard_default_priority_keeps_identity_filters_manual_sort_and_opening(self):
        from PySide6.QtCore import QPersistentModelIndex

        self.assertEqual(self._visible_ids(), [POWER, AGING, self.unknown.project_id, self.queued.project_id,
                                               self.idle.project_id, self.done.project_id, self.pending.project_id])
        self.assertEqual([metric.text() for metric in self.board.metric_numbers], ['7', '2', '1', '1', '3', '1'])
        self.board.list_button.click()
        self.board.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.assertEqual(self._visible_ids()[:3], [AGING, POWER, self.done.project_id])
        self.board.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self._visible_ids()[:3], [POWER, AGING, self.unknown.project_id])

        self.board.search.setText(self.aging.name)
        self.assertEqual(self._visible_ids(), [AGING, self.idle.project_id])
        self.board.state_filter.setCurrentIndex(self.board.state_filter.findData('attention'))
        self.assertEqual(self._visible_ids(), [AGING])
        self.board.state_filter.setCurrentIndex(self.board.state_filter.findData(''))
        self.board.cards_button.click()
        QTest.qWait(25)
        first_card = self._index_for(AGING)
        QTest.mouseClick(self.board.cards.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.board.cards.visualRect(first_card).center())
        self.assertEqual(self.window.selected_project, AGING)
        self.assertIs(self.window.pages.currentWidget(), self.window.detail)
        self.window.show_dashboard()
        self.board.list_button.click()
        QTest.qWait(25)
        idle_row = self._index_for(self.idle.project_id)
        QTest.mouseClick(self.board.table.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.board.table.visualRect(idle_row).center())
        self.assertEqual(self.window.selected_project, self.idle.project_id)

        self.window.show_dashboard()
        self.board.clear_project_filter()
        persistent = QPersistentModelIndex(self._index_for(AGING))
        self.board.table.setCurrentIndex(self._index_for(AGING))
        changed = replace(self.idle, state='running', state_text='运行中', active_task_count=1)
        # Last snapshot for an identical ID wins; equal names still represent distinct projects.
        self.window.set_projects((*self.projects, changed))
        self.assertEqual(self._visible_ids()[:3], [self.idle.project_id, POWER, AGING])
        self.assertEqual(self.board.proxy.rowCount(), 7)
        self.assertEqual(self.board.metric_numbers[1].text(), '3')
        self.assertTrue(persistent.isValid())
        self.assertEqual(persistent.data(Qt.ItemDataRole.UserRole).project_id, AGING)
        self.assertEqual(self.board.table.currentIndex().data(Qt.ItemDataRole.UserRole).project_id, AGING)

    def test_dashboard_shows_reported_run_fields_and_fits_compact_first_row(self):
        from src.ui.qt.dashboard import _RUN_ROLE

        current_power = self._index_for(POWER).data(_RUN_ROLE)
        self.assertEqual(current_power.progress, 64)
        self.assertIn('320 / 500 轮', current_power.headline)
        self.assertIn('PON 注册超时', current_power.detail)
        self.assertIn('64%', self._index_for(POWER, 4).data())
        self.assertIn('CH04 正在重试', self._index_for(POWER, 4).data())
        self.assertIsNone(self._index_for(self.idle.project_id).data(_RUN_ROLE).progress)

        aging = self._index_for(AGING).data(_RUN_ROLE)
        self.assertEqual(aging.elapsed, '1 天 03:46:00')
        self.assertEqual(aging.detail, '健康 1 · 异常 1 · 未知 1')
        self.assertIn('最近检测', self._index_for(AGING, 4).data())
        self.assertIsNone(aging.progress)
        pending = self._index_for(self.pending.project_id).data(_RUN_ROLE)
        self.assertEqual((pending.elapsed, pending.detail, pending.latest), ('—', '暂无业务观测', ''))

        live = replace(self.power, progress=0, progress_text='整批已完成 0 / 500 轮', task_stage='开始前检查')
        missing = replace(self.aging, progress=88, progress_text='不应呈现的 44 / 50 轮', test_overview={})
        self.window.set_projects((*self.projects, live, missing))
        self.assertIn('0%', self._index_for(POWER, 4).data())
        self.assertIn('开始前检查', self._index_for(POWER, 4).data())
        self.assertEqual(self._index_for(AGING, 3).data(), '—')
        self.assertEqual(self._index_for(AGING, 4).data(), '暂无业务观测')
        self.assertIsNone(self._index_for(AGING).data(_RUN_ROLE).progress)

        self.window.resize(900, 550)
        QTest.qWait(45)
        view = self.board.cards
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)
        first_row = [view.visualRect(self.board.proxy.index(row, 0)) for row in range(3)]
        self.assertTrue(all(view.viewport().rect().contains(rect) for rect in first_row))
        self.assertEqual(len({rect.y() for rect in first_row}), 1)
        for first, second in combinations(first_row, 2):
            self.assertFalse(first.intersects(second))
        self.assertTrue(self.board.search.isVisible())

        self.window.set_projects(())
        self.assertEqual(self.board.proxy.rowCount(), 0)
        self.assertEqual([metric.text() for metric in self.board.metric_numbers], ['0'] * 6)

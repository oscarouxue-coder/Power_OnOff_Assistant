"""Mandatory isolated Windows coverage for the project creation and preparation UI."""
import os
import csv
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox
from qt_test_guard import install_qt_test_scope
from qt_execution_fakes import block_live_model_transport, install_native_fixture_locks
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import apply_theme
from src.ui.qt.workspace_controller import WorkspaceController


def complete_new_dialog(test, directory, name, test_type='power_cycle'):
    wizard = test.controller.project_wizard
    test.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
    dialog = wizard.dialog
    dialog.name.setText(name)
    dialog.directory.setText(str(directory))
    dialog.test_type.setCurrentIndex(dialog.test_type.findData(test_type))
    for _ in range(3):
        dialog.forward.click()
    test.assertEqual(dialog.pages.currentIndex(), 3)
    dialog.forward.click()
    test.wait_for(lambda: wizard.dialog is not None and wizard.dialog is not dialog
                  and not wizard.dialog.busy and wizard.dialog.pages.currentIndex() == 4)
    wizard.dialog.reject()


class ProjectWizardTests(unittest.TestCase):
    def setUp(self):
        block_live_model_transport(self)
        install_native_fixture_locks(self)
        self.scope = install_qt_test_scope(self)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-project-wizard-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.window = MainWindow(demo=False)
        apply_theme(self.scope.app)
        self.controller = WorkspaceController(self.window, Path(__file__).resolve().parents[1],
                                              directory=self.root / 'workspace')
        self.addCleanup(self._close)
        self.window.show()
        self.wait_for(lambda: self.controller.ready)

    def _close(self):
        self.controller.timer.stop()
        wizard = self.controller.project_wizard.dialog
        if wizard is not None:
            wizard.accept()
        self.window._close_coordinator = None
        self.controller.adapter.begin_close({p.project_id: 'discard' for p in self.window.projects})
        self.assertTrue(self.controller.adapter.wait_closed(5))
        self.window.close()

    def wait_for(self, check):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            self.scope.app.processEvents()
            if check():
                return
            time.sleep(.01)
        dialog = self.controller.project_wizard.dialog
        self.fail('未收到向导回执：' + (dialog.feedback.text() if dialog else self.window.statusBar().currentMessage()))

    def test_qt_wizard_recovers_typed_duts_prepares_and_upgrades_untyped_project(self):
        workspace, wizard = self.controller, self.controller.project_wizard
        workspace.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('service_aging'))
        dialog.name.setText('同名项目')
        destination = self.root / 'service-project'
        dialog.directory.setText(str(destination))
        dialog.model.setText('样机型号')
        dialog.forward.click()
        dialog.add_dut({'label': 'DUT A', 'hardware_id': 'LAB-01'})
        adb_column = next(n for n in range(dialog.dut_table.columnCount())
                          if dialog.dut_table.horizontalHeaderItem(n).text() == 'ADB 设备标识')
        self.assertNotIn('adb_serial', dialog.profile()['duts'][0])
        dialog.dut_table.item(0,adb_column).setText('Emulator-A:5555')
        dut_id = dialog.profile()['duts'][0]['dut_id']
        self.assertTrue(dialog.dut_table.isColumnHidden(7))
        dialog.forward.click()
        dialog.hours.setText('168')
        dialog.collectors['iptv'].setChecked(True)
        self.assertNotIn('统一管理 IP', dialog.plan_text.text())
        dialog.save_draft.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertFalse(destination.exists())
        self.assertFalse(self.window.projects)
        dialog.reject()
        workspace.new_project()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.pages.currentIndex(), 2)
        self.assertEqual(dialog.profile()['duts'][0]['dut_id'], dut_id)
        self.assertEqual(dialog.profile()['duts'][0]['adb_serial'], 'Emulator-A:5555')
        self.assertEqual(dialog.profile()['type_config'], {'target_hours': 168, 'collectors': ['iptv']})
        dialog.forward.click()
        self.assertIn('IPTV', dialog.review.toPlainText())
        self.assertIn('Emulator-A:5555', dialog.review.toPlainText())
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is not None and wizard.dialog is not dialog
                      and not wizard.dialog.busy and wizard.dialog.pages.currentIndex() == 4)
        dialog = wizard.dialog
        project = self.window.projects[0]
        self.assertEqual(dialog.project_id, project.project_id)
        self.assertEqual(project.project_type, 'service_aging')
        self.assertEqual(project.active_task_count, 0)
        detail = self.window.detail
        for widget in (detail.summary, detail.channel_card, detail.pipeline_button, detail.test_type_panel.ring):
            self.assertTrue(widget.isHidden())
        self.assertFalse(detail.tabs.isTabVisible(1))
        self.assertIn('尚无运行', detail.test_type_panel.title.text())
        self.assertNotIn('监测时长', detail.test_type_panel.title.text())
        self.assertFalse(dialog.forward.isEnabled())
        prep = dialog.preparation
        self.assertEqual(prep.dut.currentData(), dut_id)
        self.assertEqual(prep._step()['id'], 'environment')
        prep.apply.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertEqual(prep._step()['state'], 'running')
        prep.evidence.setText('现场模拟接线记录 E01')
        prep.apply.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertEqual(prep._step()['state'], 'executed')
        prep.evidence.setText('独立核对标识 LAB-01')
        prep.apply.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertEqual(prep._step()['state'], 'verified')
        self.assertFalse(dialog.forward.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'typed-project-preparation.png')))
        # Provide explicitly manual fixture receipts, never dispatch a hardware job.
        for index in range(1, len(prep.steps)):
            prep.table.setCurrentCell(index, 0)
            step = prep._step()
            self.assertFalse(step['blocked_by'])
            if step['mode'] == 'manual':
                prep.apply.click()
                self.wait_for(lambda: not dialog.busy)
                self.assertEqual(prep._step()['state'], 'running', dialog.feedback.text())
            else:
                prep.operation.setCurrentIndex(prep.operation.findData('manual'))
                self.assertEqual(prep.operation.currentData(), 'manual')
            prep.evidence.setText('模拟现场记录 ' + step['id'])
            prep.apply.click()
            self.wait_for(lambda: not dialog.busy)
            self.assertEqual(prep._step()['state'], 'executed', dialog.feedback.text())
            prep.evidence.setText('单独核对模拟结果 ' + step['id'])
            self.assertEqual(prep.operation.currentData(), 'pass')
            prep.apply.click()
            self.wait_for(lambda: not dialog.busy)
            self.assertEqual(prep._step()['state'], 'verified', dialog.feedback.text())
        self.assertTrue(dialog.forward.isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm, \
                patch.object(QMessageBox, 'warning') as warning:
            dialog.forward.click()
            self.wait_for(lambda: not dialog.busy)
            self.assertIn('持续供电业务老化', confirm.call_args.args[2])
            warning.assert_not_called()
        self.assertIn('已取消启动', dialog.feedback.text())
        self.assertEqual(self.window.projects[0].active_task_count, 0)
        dialog.reject()
        legacy = self.root / 'old-project'
        workspace.submit('create', legacy, '同名项目')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != project.project_id)
        old_id = self.window.selected_project
        workspace.setup_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.project_id, old_id)
        self.assertFalse(dialog.test_type.currentData())
        self.assertEqual(dialog.dut_table.rowCount(), 0)
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('power_cycle'))
        self.assertFalse(dialog.dut_table.isColumnHidden(7))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            workspace.close_project()
        self.assertIs(wizard.dialog, dialog)
        self.assertEqual(len(self.window.projects), 2)
        for _ in range(3):
            dialog.forward.click()
        dialog.forward.click()
        self.wait_for(lambda: not dialog.busy and dialog.pages.currentIndex() == 4)
        saved = {p.project_id: p.project_type for p in self.window.projects}
        self.assertEqual(saved, {project.project_id: 'service_aging', old_id: 'power_cycle'})
        for widget in (detail.summary, detail.channel_card, detail.pipeline_button, detail.test_type_panel.ring):
            self.assertFalse(widget.isHidden())
        self.assertTrue(detail.tabs.isTabVisible(1))
        self.assertIn('自动开关机', detail.test_type_panel.title.text())
        self.assertFalse(dialog.forward.isEnabled())

    def test_qt_wizard_saves_selected_field_feed_sources_and_keeps_legacy_defaults(self):
        wizard = self.controller.project_wizard
        self.controller.new_project()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.name.setText('业务来源')
        dialog.directory.setText(str(self.root / 'field-input'))
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('service_aging'))
        dialog.forward.click()
        dialog.add_dut({'label': '样机 A', 'hardware_id': 'DUT-1'})
        dialog.forward.click()
        self.assertNotIn('lan_ping', dialog.collector_sources)
        self.assertNotIn('cpu_memory', dialog.collector_sources)
        self.assertNotIn('dut_presence', dialog.collector_sources)
        self.assertFalse(dialog.collector_sources['iptv'].isEnabled())
        dialog.collectors['lan_ping'].setChecked(True)
        for key in ('voice', 'iptv', 'tr069'):
            dialog.collectors[key].setChecked(True)
            self.assertEqual(dialog.collector_sources[key].currentData(), 'manual')
        self.assertNotIn('feed_collectors', dialog.profile()['type_config'])
        presence = dialog.collectors['dut_presence']
        self.assertFalse(presence.isChecked())
        self.assertEqual(presence.text(), 'DUT 在线与启动状态')
        presence.click()
        self.assertEqual(dialog.profile()['type_config']['feed_collectors'], ['dut_presence'])
        presence.click()
        self.assertNotIn('feed_collectors', dialog.profile()['type_config'])
        for key in ('iptv', 'voice'):
            source = dialog.collector_sources[key]
            self.assertTrue(source.isEnabled())
            source.setCurrentIndex(source.findData('feed'))
        dialog.collectors['voice'].setChecked(False)
        self.assertEqual(dialog.profile()['type_config']['feed_collectors'], ['iptv'])
        dialog.collectors['voice'].setChecked(True)
        self.assertEqual(dialog.collector_sources['voice'].currentData(), 'manual')
        dialog.collector_sources['voice'].setCurrentIndex(dialog.collector_sources['voice'].findData('feed'))
        presence.click()
        expected = dialog.profile()['type_config']
        self.assertEqual(expected['feed_collectors'], ['iptv', 'voice', 'dut_presence'])
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('power_cycle'))
        self.assertEqual(dialog.profile()['type_config'], {'target_cycles': None})
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('service_aging'))
        self.assertEqual(dialog.profile()['type_config'], expected)
        dialog.save_draft.click()
        self.wait_for(lambda: not dialog.busy)
        dialog.reject()
        self.controller.new_project()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.profile()['type_config'], expected)
        dialog.forward.click()
        self.assertIn('现场采集：IPTV 视频、VOICE 连续通话、DUT 在线与启动状态', dialog.review.toPlainText())
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is not None and wizard.dialog is not dialog
                      and not wizard.dialog.busy and wizard.dialog.pages.currentIndex() == 4)
        self.assertEqual(wizard.dialog.profile()['type_config'], expected)
        self.assertEqual(wizard.dialog.profile()['duts'][0]['hardware_id'], 'DUT-1')
        self.assertEqual(self.window.projects[0].active_task_count, 0)

    def test_qt_model_presets_derive_saved_plans_and_apply_to_recovered_creation_drafts(self):
        from src.services.project_model_presets import ProjectModelPresets

        workspace, wizard = self.controller, self.controller.project_wizard
        source = dict(model='LAB-T1', test_type='service_aging', software_version='源软件', requirements='源要求',
                      optional_steps=['wan'], type_config=dict(target_hours=168, collectors=['voice'],
                                                               feed_collectors=['voice']),
                      duts=[dict(label='源 DUT', hardware_id='SOURCE-1')])
        workspace.submit('create_typed', self.root / 'model-source', '型号来源项目', source)
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        self.window.select_project(project.project_id)
        workspace.setup_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy and
                      wizard.dialog.pages.currentIndex() == 4)
        dialog = wizard.dialog
        dialog.back.click()
        dialog.model.setText('尚未保存的型号')
        dialog.project_menu.aboutToShow.emit()
        self.assertFalse(dialog.save_preset_action.isEnabled())
        dialog.model.setText('LAB-T1')
        dialog.project_menu.aboutToShow.emit()
        self.assertTrue(dialog.save_preset_action.isEnabled())
        store = ProjectModelPresets(self.root / 'workspace')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.save_preset_action.trigger()
        self.assertEqual(store.list(), [])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.save_preset_action.trigger()
        self.wait_for(lambda: not dialog.busy and len(dialog.presets) == 1)
        saved = store.list()[0]
        self.assertEqual(saved, dict(model='LAB-T1', test_type='service_aging', version=1,
                                     optional_steps=source['optional_steps'], type_config=source['type_config']))
        # A second writer publishes the same case-insensitive model while the wizard is open.
        store.save(dict(source, model='Lab-T1'), 1)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.save_preset_action.trigger()
        self.wait_for(lambda: not dialog.busy and '模板已更新' in dialog.feedback.text())
        self.assertEqual(store.list()[0]['version'], 2)
        dialog.reject()

        workspace.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.name.setText('已有输入')
        dialog.directory.setText(str(self.root / 'from-template'))
        dialog.model.setText('旧型号')
        dialog.version.setText('目标软件')
        dialog.requirements.setPlainText('目标项目要求')
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('power_cycle'))
        dialog.cycles.setText('500')
        dialog.add_dut(dict(label='目标 DUT', hardware_id='DEST-1', channel=2, serial_port='COM18'))
        dialog.save_draft.click()
        self.wait_for(lambda: not dialog.busy)
        original = dialog.draft()
        dialog.reject()
        workspace.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.draft(), original)
        dialog.preset_choice.setCurrentIndex(1)
        self.assertIn('Lab-T1', dialog.preset_choice.currentText())
        self.assertIn('版本 2', dialog.preset_choice.currentText())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.apply_preset.click()
        self.assertEqual(dialog.draft(), original)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.apply_preset.click()
        now = dialog.draft()
        self.assertTrue(dialog.has_unsaved_inputs())
        self.assertEqual((now['name'], now['directory']), (original['name'], original['directory']))
        before, after = original['profile'], now['profile']
        for field in ('duts', 'software_version', 'requirements'):
            self.assertEqual(after[field], before[field])
        for field in ('test_type', 'model', 'optional_steps', 'type_config'):
            self.assertEqual(after[field], store.list()[0][field])
        self.assertEqual(len(self.window.projects), 1)
        self.assertFalse((self.root / 'from-template').exists())
        dialog.save_draft.click()
        self.wait_for(lambda: not dialog.busy)
        dialog.reject()
        # A damaged preset catalog still allows opening the user's unrelated saved draft.
        store.path.write_text('{', encoding='utf-8')
        workspace.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.draft(), now)
        self.assertTrue(dialog.preset_error.isVisible())
        self.assertFalse(dialog.preset_choice.isEnabled())
        self.assertTrue(dialog.forward.isEnabled())
        for _ in range(3):
            dialog.forward.click()
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is not None and wizard.dialog is not dialog and
                      not wizard.dialog.busy and wizard.dialog.pages.currentIndex() == 4)
        self.assertEqual(wizard.dialog.profile(), after)
        self.assertEqual(len(self.window.projects), 2)

    def test_qt_aging_history_pages_and_exports_only_the_bound_batch(self):
        import sqlite3
        from contextlib import closing
        from PySide6.QtWidgets import QFileDialog
        from src.services.service_aging_history import ServiceAgingHistory

        workspace = self.controller
        for i in range(2):
            workspace.submit('create_typed', self.root / f'aging-{i}', '同名老化', {'test_type': 'service_aging'})
            self.wait_for(lambda: len(self.window.projects) == i + 1)
        a, b = self.window.projects
        context = workspace.adapter._service.projects.opened[a.project_id]
        history = ServiceAgingHistory(context, time.time)
        plan = dict(revision=context.identity.revision, target_hours=168, collectors=['iptv'],
                    duts=[dict(dut_id='device-1', label='测试 DUT', binding=None, reason='')])
        for job in ('older-batch', 'current-batch'):
            history.begin(job, plan, 180)
            history.observe(job, 'device-1', 'iptv', 'healthy', job + ' 第一天检查', '操作员', kind='daily')
            history.tick(job, 60, 'stopped')
            history.observe(job, 'device-1', 'iptv', 'unknown', job + ' 待核实', '操作员', kind='final')
        # Additional persisted observations exercise pagination without running a sampler.
        with closing(sqlite3.connect(history.path)) as db, db:
            db.executemany('INSERT INTO observations(job,dut,collector,kind,outcome,at,day,evidence,operator) '
                           'VALUES(?,?,?,?,?,?,?,?,?)', [
                ('current-batch','device-1','iptv','observation','healthy',i+100000,'2026-11-22',f'回执 {i}','操作员')
                for i in range(101)])
        self.window.select_project(a.project_id)
        self.window.detail.test_type_panel.history_button.click()
        viewer = workspace.aging_history.windows[a.project_id]
        self.wait_for(lambda: viewer.table.rowCount() == 100)
        self.assertEqual(viewer.runs.currentData(), 'current-batch')
        self.assertTrue(viewer.old_page.isEnabled())
        viewer.old_page.click()
        self.wait_for(lambda: viewer.table.rowCount() == 3)
        self.assertFalse(viewer.old_page.isEnabled())
        viewer.kind.setCurrentIndex(viewer.kind.findData('daily'))
        self.wait_for(lambda: viewer.table.rowCount() == 1)
        self.assertIn('current-batch 第一天检查', viewer.table.item(0, 6).text())
        viewer.runs.setCurrentIndex(viewer.runs.findData('older-batch'))
        self.wait_for(lambda: viewer.table.rowCount() == 1)
        self.assertIn('older-batch 第一天检查', viewer.table.item(0, 6).text())
        destination = self.root / 'evidence.csv'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            viewer.export.click()
        self.assertFalse(destination.exists())
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), '')):
            viewer.export.click()
            self.wait_for(lambda: '已导出' in viewer.feedback.text())
            original = destination.read_bytes()
            viewer.export.click()
            self.wait_for(lambda: '已存在' in viewer.feedback.text())
        self.assertEqual(destination.read_bytes(), original)
        with destination.open(encoding='utf-8-sig', newline='') as stream:
            records = list(csv.DictReader(stream))
        self.assertEqual([row['批次 ID'] for row in records], ['older-batch', 'older-batch'])
        self.assertEqual({row['记录类型'] for row in records}, {'daily', 'final'})
        self.assertEqual({row['DUT 名称'] for row in records}, {'测试 DUT'})
        self.window.select_project(b.project_id)
        self.window.detail.test_type_panel.history_button.click()
        empty = workspace.aging_history.windows[b.project_id]
        self.wait_for(lambda: '暂无老化批次' in empty.feedback.text())
        self.assertFalse(empty.export.isEnabled())
        self.assertTrue(viewer.isVisible())
        self.assertIsNot(empty, viewer)
        empty.close()
        viewer.close()

    def test_qt_structured_archive_filters_identity_pages_and_drops_late_receipts(self):
        import threading
        from src.models.workbench_presentation import LogView
        from src.services.workspace_event_log import read_workspace_events

        workspace = self.controller
        for index in range(2):
            workspace.submit('create', self.root / f'event-{index}', '同名项目')
            self.wait_for(lambda: len(self.window.projects) == index + 1)
        first, second = self.window.projects
        writer = workspace.adapter._log_writer
        def append(project, dut, channel, level, text):
            self.assertTrue(writer.offer(LogView('10:30:00', level, project.project_id, project.name, text,
                                                 channel=channel, dut_id=dut, step='check', job_id='job-A',
                                                 batch_id='run-A')))
        for index in range(101):
            append(first, 'DUT-A', 2, 'WARN', f'分页记录-{index:03d}')
        append(first, 'DUT-B', 2, 'WARN', '另一个 DUT')
        append(first, 'DUT-A', 3, 'WARN', '另一通道')
        append(first, 'DUT-A', 2, 'INFO', '另一等级')
        append(second, 'DUT-A', 2, 'WARN', '同名第二项目')
        self.assertTrue(writer.flush())
        with (workspace.adapter._service.directory / 'workspace.log').open('a', encoding='utf-8') as legacy:
            legacy.write('旧版无结构字段的独立原文\n')
        self.window.select_project(first.project_id)
        workspace.archived_logs_action.trigger()
        view = workspace.archived_logs.dialog
        self.wait_for(lambda: not view.busy and '旧版无结构字段的独立原文' in view.logs.text.toPlainText())
        view.source.setCurrentIndex(view.source.findData('events'))
        self.wait_for(lambda: not view.busy)
        self.assertEqual(view.filters()['project_id'], first.project_id)
        view.event_dut.setEditText('DUT-A')
        view.event_channel.setCurrentIndex(view.event_channel.findData(2))
        view.event_level.setCurrentIndex(view.event_level.findData('WARN'))
        view.latest.click()
        self.wait_for(lambda: not view.busy and len(view.logs.entries) == 100)
        text = view.logs.text.toPlainText()
        for expected in ('分页记录-100', 'Job job-A', '批次 run-A', first.project_id):
            self.assertIn(expected, text)
        for excluded in ('分页记录-000', '另一个 DUT', '另一通道', '另一等级', '同名第二项目', '旧版无结构字段的独立原文'):
            self.assertNotIn(excluded, text)
        view.older.click()
        self.wait_for(lambda: not view.busy and len(view.logs.entries) == 1)
        self.assertIn('分页记录-000', view.logs.text.toPlainText())
        self.assertFalse(view.older.isEnabled())
        view.event_dut.setEditText('DUT-B')
        view.latest.click()
        self.wait_for(lambda: not view.busy and '另一个 DUT' in view.logs.text.toPlainText())
        self.assertEqual(len(view.logs.entries), 1)
        entered, release = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(7):
                raise ValueError('测试未释放归档线程')
            return read_workspace_events(*args, **kwargs)
        with patch('src.services.workspace_event_log.read_workspace_events', delayed):
            view.latest.click()
            try:
                self.wait_for(entered.is_set)
                self.window.select_project(second.project_id)
                workspace.archived_logs_action.trigger()
                replacement = workspace.archived_logs.dialog
                self.assertIsNot(replacement, view)
                self.assertEqual(replacement.project_id, second.project_id)
            finally:
                release.set()
            self.wait_for(lambda: not replacement.busy)
        replacement.source.setCurrentIndex(replacement.source.findData('events'))
        self.wait_for(lambda: not replacement.busy)
        self.assertIn('同名第二项目', replacement.logs.text.toPlainText())
        self.assertNotIn('分页记录-', replacement.logs.text.toPlainText())
        replacement.close()

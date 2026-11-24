"""Mandatory isolated Windows coverage for the project creation and channel configuration UI."""
import os
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton
from qt_test_guard import install_qt_test_scope
from qt_execution_fakes import block_live_model_transport, install_native_fixture_locks
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import apply_theme
from src.ui.qt.workspace_controller import WorkspaceController


def complete_new_dialog(test, parent, name, test_type='power_cycle'):
    wizard = test.controller.project_wizard
    test.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
    dialog = wizard.dialog
    dialog.name.setText(name)
    dialog.directory.setText(str(parent))
    dialog.test_type.setCurrentIndex(dialog.test_type.findData(test_type))
    destination = Path(dialog.final_path.toPlainText())
    dialog.forward.click()
    test.assertEqual(dialog.pages.currentIndex(), dialog.REVIEW)
    dialog.forward.click()
    test.wait_for(lambda: wizard.dialog is None and test.window.selected_project)
    return destination


class ProjectWizardTests(unittest.TestCase):
    def setUp(self):
        block_live_model_transport(self)
        install_native_fixture_locks(self)
        self.scope = install_qt_test_scope(self)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-project-wizard-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / 'fixture-source'
        config = source / 'Auto_power_on_off_tool/config'
        config.mkdir(parents=True)
        for filename, section in (('config.ini', 'dingtalk_config'), ('onu_registration.ini', 'onu_registration'),
                                  ('sample_upgrade_settings.ini', 'sample_upgrade'),
                                  ('test_project_config.default.ini', 'project_info')):
            (config / filename).write_text(f'[{section}]\n', encoding='utf-8')
        self.window = MainWindow(demo=False)
        apply_theme(self.scope.app)
        self.controller = WorkspaceController(self.window, source,
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

    def open_new_wizard(self, name, kind):
        wizard = self.controller.project_wizard
        self.controller.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.name.setText(name)
        dialog.test_type.setCurrentIndex(dialog.test_type.findData(kind))
        return dialog

    def reach_review(self, dialog):
        self.assertEqual(dialog.pages.count(), 2)
        dialog.forward.click()
        self.assertEqual(dialog.pages.currentIndex(), dialog.REVIEW, dialog.feedback.text())

    def assert_creation_feedback(self, dialog, expected):
        self.wait_for(lambda: not dialog.busy)
        feedback = dialog.feedback.text()
        self.assertIn(expected, feedback)
        self.assertTrue(self.controller.adapter._log_writer.flush())
        archive = (self.root / 'workspace/workspace.log').read_text(encoding='utf-8')
        self.assertIn('wizard_create失败：' + feedback, archive)
        self.assertNotIn('fixture-private-value', archive + feedback)
        return archive

    def test_sidebar_actions_follow_only_the_rendered_project(self):
        import sqlite3
        import sys
        from contextlib import closing
        from dataclasses import replace
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from src.services.project_store import ProjectStore
        from src.services.service_aging_history import _SCHEMA

        window, controller = self.window, self.controller
        store = ProjectStore(self.root / 'fixture-source')
        def open_fixture(name, kind):
            context = store.create(self.root / name, name, profile=dict(test_type=kind))
            store.close(context)
            controller.open_project(str(context.root))
            self.wait_for(lambda: window.selected_project == context.identity.project_id)
            return context

        b = open_fixture('Old B', 'service_aging')
        a = open_fixture('Healthy A', 'power_cycle')
        window.resize(1440, 900)
        if window.sidebar.isHidden():
            window.toggle_sidebar()

        def click(context):
            key = context.identity.project_id
            for group_row in range(window.navigation_model.rowCount()):
                group = window.navigation_model.item(group_row)
                for row in range(group.rowCount()):
                    index = group.child(row).index()
                    if index.data(Qt.ItemDataRole.UserRole) == key:
                        window.navigation.scrollTo(index)
                        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                                         pos=window.navigation.visualRect(index).center())
                        return
            self.fail('合成项目未出现于侧栏')

        def assert_context(context):
            key = context.identity.project_id
            self.assertIs(window.pages.currentWidget(), window.detail)
            self.assertEqual(window.navigation.currentIndex().data(Qt.ItemDataRole.UserRole), key)
            self.assertEqual(window.detail.name.text(), context.identity.name)
            self.assertEqual((window.selected_project, window.detail.project.project_id, window.logs.scope_id,
                              controller._current().project_id), (key,) * 4)
            with patch.object(controller, 'submit') as submit:
                controller.save_project()
                submit.assert_called_once_with('save', key)

        with patch.object(sys, 'excepthook') as uncaught:
            click(b)
            assert_context(b)
            self.assertEqual(window.detail.test_type_panel.table.rowCount(), 0)
            click(a)
            assert_context(a)
            with closing(sqlite3.connect(str(b.root / 'history/service_aging.sqlite3'))) as db:
                db.executescript(_SCHEMA)
                db.execute("INSERT INTO runs(job,project,state,started,ended,elapsed,freshness) "
                           "VALUES('archived',?,'stopped',100,200,100,60)", (b.identity.project_id,))
                db.execute("INSERT INTO streams(job,dut,label,collector,source,state,last_at,detail) "
                           "VALUES('archived','fixture','DUT','iptv','manual','unknown',1e15,'fixture')")
                db.commit()
                for stamp in (1234567890, 1e15):
                    with self.subTest(timestamp=stamp):
                        db.execute('UPDATE streams SET last_at=?', (stamp,))
                        db.commit()
                        controller.submit('refresh')
                        self.wait_for(lambda: any(p.project_id == b.identity.project_id and
                            any(r.get('last_observation') == stamp for r in (p.test_overview or {}).get('rows', ()))
                            for p in window.projects))
                        click(b)
                        assert_context(b)
                        observed = window.detail.test_type_panel.table.item(0, 13).text()
                        self.assertEqual(observed == '—', stamp == 1e15)
                        self.assertEqual(window.detail.aging_metrics.cards[-1].value_label.text(), observed)
                        click(a)
                        assert_context(a)
            set_scope = window.logs.set_scope

            def set_scope_with_failure(*args, **kwargs):
                set_scope(*args, **kwargs)
                if window.logs.scope_id == b.identity.project_id:
                    raise ValueError('fixture')

            with patch.object(window.logs, 'set_scope', side_effect=set_scope_with_failure):
                click(b)
            self.assertIs(window.pages.currentWidget(), window.dashboard)
            self.assertEqual((window.selected_project, window.logs.scope_id), ('', ''))
            self.assertIsNone(controller._current())
            with patch.object(controller, 'submit') as submit:
                controller.start_test()
                controller.stop_test()
                controller.close_project()
                submit.assert_not_called()
            click(b)
            assert_context(b)
            controller.timer.stop()
            # A real stop-capable view, with every submission intercepted at the controller.
            target = replace(controller._current(), can_stop=True, run_id='synthetic-job')
            window.set_projects((target, next(p for p in window.projects if p.project_id == a.identity.project_id)))
            with patch.object(controller, 'submit', return_value=None) as submit, patch.object(
                    QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                controller.start_test()
                submit.assert_called_with('prepare_execution', b.identity.project_id, 'service_aging.start', ())
                controller.stop_test()
                submit.assert_called_with('stop_execution', b.identity.project_id, 'synthetic-job')
                controller.close_project()
                submit.assert_called_with('close', b.identity.project_id, '')
            uncaught.assert_not_called()

    def test_failed_creation_reports_the_stage_and_allows_correcting_the_same_inputs(self):
        parent = self.root / '模拟保存位置'
        parent.mkdir()
        wizard = self.controller.project_wizard
        for kind, field, reason in (('service_aging', 'hours', '目标时长须为正整数'),):
            with self.subTest(kind=kind):
                dialog = self.open_new_wizard('模拟项目', kind)
                dialog.directory.setText(str(parent))
                dialog.model.setText('fixture-private-value')
                number = getattr(dialog, field)
                number.setText('0')
                self.reach_review(dialog)
                caption = '计划目标轮数' if kind == 'power_cycle' else '目标时长（小时）'
                self.assertIn(caption + '：0', dialog.review.toPlainText().splitlines())
                target = Path(dialog.final_path.toPlainText())
                self.assertFalse(target.exists())
                dialog.forward.click()
                archive = self.assert_creation_feedback(dialog, reason)
                attempt = archive.rsplit('开始项目操作：wizard_create', 1)[1]
                self.assertIn('核对新项目目标目录', attempt)
                self.assertNotIn('正在创建项目', attempt)
                self.assertFalse(target.exists())
                self.assertEqual(dialog.model.text(), 'fixture-private-value')
                dialog.back.click()
                number.setText('1')
                dialog.forward.click()
                dialog.forward.click()
                self.wait_for(lambda: wizard.dialog is None)
                self.assertTrue((target / 'project.linecheck.json').is_file())

        dialog = self.open_new_wizard('故障注入', 'power_cycle')
        dialog.directory.setText(str(parent))
        self.reach_review(dialog)
        target = Path(dialog.final_path.toPlainText())
        for method, error, reason in (
                ('scripts.create_portable_config.create_portable_config',
                 ValueError('fixture-private-value'), '核对程序配置模板'),
                ('src.services.project_store.ProjectStore._publish_exclusive_project',
                 PermissionError('fixture-private-value'), '访问被拒绝'),
                ('src.services.project_store.ProjectStore._publish_exclusive_project',
                 OSError('fixture-private-value'), '发布项目目录失败')):
            with self.subTest(reason=reason), patch(method, side_effect=error):
                dialog.forward.click()
                self.assert_creation_feedback(dialog, reason)
                self.assertFalse(target.exists())

        from src.services.project_wizard_draft import ProjectWizardDraft
        drafts = ProjectWizardDraft(self.root / 'workspace')
        saved = drafts.write(dialog.draft(), drafts.read()['token'])
        dialog.forward.click()
        archive = self.assert_creation_feedback(dialog, '创建前向导草稿已更新')
        self.assertNotIn('核对新项目目标目录', archive.rsplit('开始项目操作：wizard_create', 1)[1])
        self.assertEqual(drafts.read(), saved)
        self.assertFalse(target.exists())
        dialog.accept()

        self.controller.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.pages.currentIndex(), dialog.REVIEW)
        with patch.object(self.controller.adapter, '_load_project_state', side_effect=ValueError('fixture-private-value')):
            dialog.forward.click()
            self.assert_creation_feedback(dialog, '项目目录已创建，工作区载入失败')
        self.assertTrue((target / 'project.linecheck.json').is_file())

    def test_new_project_previews_and_creates_only_the_confirmed_named_child(self):
        from src.models.project import PROJECT_FILE
        from src.services.project_profile_store import read_project_profile

        parent = self.root / '部门 测试' / '项目 库'
        parent.mkdir(parents=True)
        for name in ('已有 开关机', '已有 老化'):
            sibling = parent / name
            sibling.mkdir()
            (sibling / 'marker.txt').write_text(name, encoding='utf-8')
        wizard = self.controller.project_wizard
        for kind, suffix in (('power_cycle', '开关机挂测'), ('service_aging', '全业务老化')):
            with self.subTest(kind=kind):
                dialog = self.open_new_wizard('临时 名称', kind)
                self.assertEqual(dialog.final_path.toPlainText(), '')
                browse = next(control for control in dialog.findChildren(QPushButton) if control.text() == '选择文件夹…')
                with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(parent)) as picker:
                    browse.click()
                    picker.assert_called_once_with(dialog, '选择保存位置', '')
                self.assertEqual(dialog.directory.text(), str(parent))
                self.assertEqual(dialog.directory.accessibleName(), '保存到')
                self.assertEqual(dialog.final_path.toPlainText(), str(parent / f'临时 名称_{suffix}'))
                name = '离线模拟 样机 A'
                dialog.name.setText(name)
                destination = parent / f'{name}_{suffix}'
                self.assertEqual(dialog.final_path.toPlainText(), str(destination))
                other = 'service_aging' if kind == 'power_cycle' else 'power_cycle'
                other_suffix = '全业务老化' if kind == 'power_cycle' else '开关机挂测'
                dialog.test_type.setCurrentIndex(dialog.test_type.findData(other))
                self.assertEqual(dialog.final_path.toPlainText(), str(parent / f'{name}_{other_suffix}'))
                dialog.test_type.setCurrentIndex(dialog.test_type.findData(kind))
                self.assertEqual(dialog.final_path.toPlainText(), str(destination))
                self.assertTrue(dialog.final_path.isReadOnly())
                self.assertFalse(destination.exists())
                output = os.environ.get('DUTPILOT_QT_WIZARD_CAPTURE_DIRECTORY')
                if output:
                    self.scope.app.processEvents()
                    capture = dialog.grab()
                    scale = f'{capture.devicePixelRatio():g}'
                    self.assertTrue(capture.save(str(Path(output) / f'preview-{kind}-{scale}.png')))
                self.reach_review(dialog)
                self.assertIn(str(destination), dialog.review.toPlainText())
                self.assertFalse(destination.exists())
                dialog.forward.click()
                self.wait_for(lambda: wizard.dialog is None)
                project = next(p for p in self.window.projects if p.project_id == self.window.selected_project)
                self.assertEqual((project.name, project.project_type, project.active_task_count), (name, kind, 0))
                self.assertTrue((destination / PROJECT_FILE).is_file())
                config = destination / 'revisions' / project.saved_revision / 'Auto_power_on_off_tool/config'
                self.assertEqual(read_project_profile(config)['test_type'], kind)
                self.assertFalse((parent / PROJECT_FILE).exists())
        for name in ('已有 开关机', '已有 老化'):
            self.assertEqual((parent / name / 'marker.txt').read_text(encoding='utf-8'), name)

    def test_new_project_rejects_conflicts_invalid_paths_and_late_directory_claim(self):
        from src.services.project_store import ProjectStore

        parent = self.root / '模拟父目录'
        parent.mkdir()
        occupied = parent / '冲突_开关机挂测'
        occupied.mkdir()
        marker = occupied / 'keep.txt'
        for filled in (False, True):
            if filled:
                marker.write_text('现有内容', encoding='utf-8')
            dialog = self.open_new_wizard('冲突', 'power_cycle')
            dialog.directory.setText(str(parent))
            self.reach_review(dialog)
            dialog.forward.click()
            self.assert_creation_feedback(dialog, '请更换项目名称')
            self.assertEqual(tuple(occupied.iterdir()), (marker,) if filled else ())
            if filled:
                self.assertEqual(marker.read_text(encoding='utf-8'), '现有内容')
            dialog.accept()

        occupied_file = parent / '同名文件_全业务老化'
        occupied_file.write_bytes(b'keep')
        dialog = self.open_new_wizard('同名文件', 'service_aging')
        dialog.directory.setText(str(parent))
        self.reach_review(dialog)
        dialog.forward.click()
        self.assert_creation_feedback(dialog, '已有同名目录或文件')
        self.assertEqual(occupied_file.read_bytes(), b'keep')
        dialog.accept()

        dialog = self.open_new_wizard('CON.txt', 'service_aging')
        dialog.directory.setText(str(parent))
        for name, message in (('CON.txt', 'Windows 保留名'), ('../越界', '不能包含路径分隔符'),
                              ('C:另一个位置', 'Windows 禁用字符'), ('名称.', '不能以点结尾'),
                              ('😀' * 129, '生成的项目文件夹名称过长')):
            dialog.name.setText(name)
            self.assertEqual(dialog.final_path.toPlainText(), '')
            dialog.forward.click()
            self.assertEqual(dialog.pages.currentIndex(), 0)
            self.assertIn(message, dialog.feedback.text())
        dialog.name.setText('跨目录')
        dialog.directory.setText(str(parent / '..'))
        dialog.forward.click()
        self.assertIn('有效的绝对保存位置', dialog.feedback.text())
        missing = parent / '不可用父目录'
        dialog.directory.setText(str(missing))
        self.reach_review(dialog)
        dialog.forward.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertIn('保存位置必须是已存在的文件夹', dialog.feedback.text())
        self.assertFalse(missing.exists())
        dialog.accept()

        raced = parent / '晚到冲突_全业务老化'
        dialog = self.open_new_wizard('晚到冲突', 'service_aging')
        dialog.directory.setText(str(parent))
        self.reach_review(dialog)
        before_publish = threading.Event()
        competitor_ready = threading.Event()
        publish = ProjectStore._publish_exclusive_project

        def claim():
            try:
                if not before_publish.wait(5):
                    raise AssertionError('未到达发布边界')
                raced.mkdir()
                return raced.stat().st_ino
            finally:
                competitor_ready.set()

        def publish_after_claim(stage, destination):
            self.assertEqual(destination, raced.resolve())
            before_publish.set()
            self.assertTrue(competitor_ready.wait(5))
            return publish(stage, destination)

        with ThreadPoolExecutor(max_workers=1) as pool, \
                patch.object(ProjectStore, '_publish_exclusive_project', staticmethod(publish_after_claim)):
            winner = pool.submit(claim)
            dialog.forward.click()
            self.wait_for(lambda: not dialog.busy)
            self.assertEqual(raced.stat().st_ino, winner.result(timeout=5))
        self.assert_creation_feedback(dialog, '请更换项目名称')
        self.assertEqual(tuple(raced.iterdir()), ())
        self.assertEqual(set(parent.iterdir()), {occupied, occupied_file, raced})
        self.assertFalse(self.window.projects)

    def test_old_draft_requires_reselecting_parent_and_cancel_does_not_create(self):
        from src.services.project_wizard_draft import ProjectWizardDraft

        old_target = self.root / '旧版保存的最终目录'
        legacy = dict(name='旧版草稿', directory=str(old_target), page=3,
                      profile=dict(test_type='service_aging', model='离线型号', type_config={'target_hours': 168}))
        drafts = ProjectWizardDraft(self.root / 'workspace')
        saved = drafts.write(legacy, '')
        self.controller.new_action.trigger()
        wizard = self.controller.project_wizard
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertEqual((dialog.name.text(), dialog.model.text(), dialog.hours.text()), ('旧版草稿', '离线型号', '168'))
        self.assertEqual(dialog.test_type.currentData(), 'service_aging')
        self.assertIn('重新选择「保存到」', dialog.feedback.text())
        self.assertEqual(dialog.directory.text(), '')
        self.assertEqual(dialog.final_path.toPlainText(), '')
        dialog.forward.click()
        self.assertIn('请选择保存位置', dialog.feedback.text())
        dialog.directory.setText(str(self.root))
        destination = self.root / '旧版草稿_全业务老化'
        self.reach_review(dialog)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.close_button.click()
        self.assertIs(wizard.dialog, dialog)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.close_button.click()
        self.assertIsNone(wizard.dialog)
        self.assertFalse(old_target.exists())
        self.assertFalse(destination.exists())
        self.assertFalse(self.window.projects)
        self.assertEqual(drafts.read(), saved)

    def test_qt_wizard_recovers_legacy_draft_and_uses_main_start_confirmation(self):
        workspace, wizard = self.controller, self.controller.project_wizard
        workspace.new_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('service_aging'))
        dialog.name.setText('同名项目')
        parent = self.root / 'service-project'
        parent.mkdir()
        destination = parent / '同名项目_全业务老化'
        dialog.directory.setText(str(parent))
        dialog.model.setText('样机型号')
        dialog.hours.setText('168')
        dialog.collectors['iptv'].setChecked(True)
        from uuid import uuid4
        dut_id = str(uuid4())
        dialog.duts.append(dict(dut_id=dut_id, channel=1, label='DUT A', adb_serial='Emulator-A:5555'))
        dialog.legacy_environment = dict(channels=dict(device_ip='', power_serial_port='', rows=[
            dict(number=n, enabled=n == 1, vlan_name='', serial_port='') for n in range(1, 17)]))
        self.reach_review(dialog)
        dialog.save_draft.click()
        self.wait_for(lambda: not dialog.busy)
        self.assertFalse(destination.exists())
        self.assertFalse(self.window.projects)
        dialog.reject()
        workspace.new_project()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.pages.count(), 2)
        self.assertEqual(dialog.pages.currentIndex(), dialog.REVIEW)
        self.assertEqual(dialog.profile()['duts'][0]['dut_id'], dut_id)
        self.assertEqual(dialog.profile()['duts'][0]['adb_serial'], 'Emulator-A:5555')
        self.assertIn('IPTV', dialog.review.toPlainText())
        self.assertIn('沿用旧草稿中的通道设置', dialog.review.toPlainText())
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is None)
        project = self.window.projects[0]
        self.assertEqual(self.window.selected_project, project.project_id)
        self.assertEqual(project.project_type, 'service_aging')
        self.assertEqual(project.active_task_count, 0)
        detail = self.window.detail
        for widget in (detail.summary, detail.channel_card, detail.pipeline_button, detail.test_type_panel.ring):
            self.assertTrue(widget.isHidden())
        self.assertFalse(detail.tabs.isTabVisible(1))
        self.assertIn('尚无运行', detail.test_type_panel.title.text())
        self.assertNotIn('监测时长', detail.test_type_panel.title.text())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm, \
                patch.object(QMessageBox, 'warning') as warning:
            detail.start_button.click()
            self.wait_for(lambda: confirm.called)
            self.assertIn('持续供电业务老化', confirm.call_args.args[2])
            warning.assert_not_called()
        self.assertEqual(self.window.projects[0].active_task_count, 0)
        self.assertFalse((destination / 'history/preparation.sqlite3').exists())
        legacy = self.root / 'old-project'
        workspace.submit('create', legacy, '同名项目')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != project.project_id)
        old_id = self.window.selected_project
        workspace.setup_action.trigger()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        self.assertEqual(dialog.project_id, old_id)
        self.assertFalse(dialog.test_type.currentData())
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('power_cycle'))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            workspace.close_project()
        self.assertIs(wizard.dialog, dialog)
        self.assertEqual(len(self.window.projects), 2)
        dialog.forward.click()
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is None)
        saved = {p.project_id: p.project_type for p in self.window.projects}
        self.assertEqual(saved, {project.project_id: 'service_aging', old_id: 'power_cycle'})
        for widget in (detail.summary, detail.channel_card, detail.pipeline_button, detail.test_type_panel.ring):
            self.assertFalse(widget.isHidden())
        self.assertTrue(detail.tabs.isTabVisible(1))
        self.assertTrue(detail.test_type_panel.title.parentWidget().isHidden())
        self.assertEqual(detail.test_type_panel.table.horizontalHeaderItem(4).text(), '完成轮')

    def test_qt_wizard_saves_selected_field_feed_sources_and_keeps_legacy_defaults(self):
        wizard = self.controller.project_wizard
        self.controller.new_project()
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
        dialog.name.setText('业务来源')
        dialog.directory.setText(str(self.root))
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('service_aging'))
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
        self.wait_for(lambda: wizard.dialog is None)
        from src.services.project_profile_store import read_project_profile
        project = self.window.projects[0]
        context = self.controller.adapter._service.projects.opened[project.project_id]
        committed = read_project_profile(context.config_dir)
        self.assertEqual(committed['type_config'], expected)
        self.assertEqual(committed['duts'], [])
        self.assertTrue(committed['environment_channels'])
        self.assertEqual(self.window.projects[0].active_task_count, 0)

    def test_main_channel_entry_reuses_saved_configuration_and_keeps_old_dut_history(self):
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.services.project_profile_store import read_project_profile

        controller = self.controller
        profile = dict(test_type='service_aging', duts=[dict(label='旧 DUT', hardware_id='LEGACY')])
        controller.submit('create_typed', self.root / 'existing', '老化项目', profile)
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        context = controller.adapter._service.projects.opened[project.project_id]
        old = read_project_profile(context.config_dir)['duts'][0]
        store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
        store.save([ChannelConfig(f'channel_{n}', vlan_name=f'VLAN{vlan}', serial_port=f'COM{vlan-100}',
                                  device_manage_ip='192.168.1.1', network_card_ip=f'192.168.1.{vlan}')
                    for n, vlan in ((1, 116), (2, 115), (7, 114))])
        controller.submit('save', project.project_id)
        self.wait_for(lambda: self.window.projects[0].saved_revision != project.saved_revision)
        detail = self.window.detail
        self.assertEqual(self.window.selected_project, project.project_id)
        if not detail.config_scroll.isVisible():
            detail.config_toggle.click()
        entry = next(button for button in detail.configuration.findChildren(QPushButton)
                     if button.text() == '环境配置' and button.isVisible())
        entry.click()
        self.wait_for(lambda: project.project_id in controller.configuration_editors)
        dialog = controller.configuration_editors[project.project_id]
        def close_editor():
            if controller.configuration_editors.get(project.project_id) is dialog:
                dialog.set_draft(dialog.draft)
                dialog.set_busy(False)
                dialog.close()
        self.addCleanup(close_editor)
        active = [row for row in dialog.rows if row.enabled.isChecked()]
        self.assertEqual([(r.number, r.vlan.currentText(), r.port.currentText()) for r in active],
                         [(1, 'VLAN116', 'COM16'), (2, 'VLAN115', 'COM15'), (7, 'VLAN114', 'COM14')])
        self.assertTrue(dialog.power_port.isHidden())
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QInputDialog, QMenu
        with patch.object(QInputDialog, 'getText', return_value=('Legacy-ADB', True)):
            active[-1].customContextMenuRequested.emit(QPoint())
            menu = active[-1].findChild(QMenu)
            self.assertIsNotNone(menu)
            next(action for action in menu.actions() if action.text() == 'ADB 设备标识…').trigger()
            menu.close()
        choice = dialog.assignments[old['dut_id']]
        choice.setCurrentIndex(choice.findData(7))
        evidence = context.history / 'preparation.sqlite3'
        evidence.write_bytes(b'legacy history')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as preview, \
                patch.object(QMessageBox, 'warning') as warning:
            dialog.save_button.click()
            self.wait_for(lambda: not dialog.busy and (preview.called or warning.called))
            self.assertFalse(warning.called, dialog.feedback.text())
            self.assertIn('旧 DUT → CH07', preview.call_args.args[2])
        dialog.close()
        saved = read_project_profile(context.saved_root / 'Auto_power_on_off_tool/config')
        by_channel = {dut['channel']: dut for dut in saved['duts']}
        self.assertEqual(by_channel[7]['dut_id'], old['dut_id'])
        self.assertEqual(by_channel[7]['hardware_id'], 'LEGACY')
        self.assertEqual(by_channel[7]['adb_serial'], 'Legacy-ADB')
        self.assertEqual(evidence.read_bytes(), b'legacy history')
        self.assertEqual({n: by_channel[n]['label'] for n in (1, 2)}, {1: 'CH01', 2: 'CH02'})
        self.assertEqual([row.section for row in store.load()], ['channel_1', 'channel_2', 'channel_7'])
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
        self.wait_for(lambda: wizard.dialog is not None and not wizard.dialog.busy)
        dialog = wizard.dialog
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
                                     optional_steps=[], type_config=source['type_config']))
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
        parent = self.root / 'from-template'
        parent.mkdir()
        dialog.directory.setText(str(parent))
        dialog.model.setText('旧型号')
        dialog.version.setText('目标软件')
        dialog.requirements.setPlainText('目标项目要求')
        dialog.test_type.setCurrentIndex(dialog.test_type.findData('power_cycle'))
        from uuid import uuid4
        dialog.duts.append(dict(dut_id=str(uuid4()), label='目标 DUT', channel=2, adb_serial='test-adb'))
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
        self.assertEqual((now['name'], now['parent_directory']), (original['name'], original['parent_directory']))
        before, after = original['profile'], now['profile']
        for field in ('duts', 'software_version', 'requirements'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['optional_steps'], [])
        for field in ('test_type', 'model', 'type_config'):
            self.assertEqual(after[field], store.list()[0][field])
        self.assertEqual(len(self.window.projects), 1)
        self.assertEqual(tuple(parent.iterdir()), ())
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
        dialog.forward.click()
        dialog.forward.click()
        self.wait_for(lambda: wizard.dialog is None)
        from src.services.project_profile_store import read_project_profile
        context = workspace.adapter._service.projects.opened[self.window.selected_project]
        committed = read_project_profile(context.config_dir)
        self.assertTrue(committed['environment_channels'])
        self.assertEqual(committed['type_config'], after['type_config'])
        self.assertEqual(committed['duts'][0]['dut_id'], after['duts'][0]['dut_id'])
        self.assertEqual(committed['duts'][0]['adb_serial'], 'test-adb')
        self.assertEqual(len(self.window.projects), 2)

    def test_qt_aging_history_pages_and_exports_only_the_bound_batch(self):
        import sqlite3
        from contextlib import closing
        from PySide6.QtWidgets import QFileDialog
        from src.services.service_aging_history import ServiceAgingHistory

        workspace = self.controller
        for i in range(2):
            directory = self.root / f'aging-{i}'
            if i == 0:
                directory.mkdir()  # Direct compatibility entry still accepts an existing empty destination.
            workspace.submit('create_typed', directory, '同名老化', {'test_type': 'service_aging'})
            self.wait_for(lambda: len(self.window.projects) == i + 1)
            self.assertTrue((directory / 'project.linecheck.json').is_file())
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

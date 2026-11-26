"""Independent native Qt synthetic evidence: cross-process reports and old capacity."""
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
MODE = sys.argv[1]
assert MODE in ('writer', 'reader', 'capacity')


def run():
    with tempfile.TemporaryDirectory(prefix='p1-p2-remaining-synthetic-') as temporary, ExitStack() as scope:
        root = Path(temporary).resolve()
        local, roaming = root / 'local', root / 'roaming'
        local.mkdir()
        roaming.mkdir()
        scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming),
                                       TEMP=str(root), TMP=str(root), TMPDIR=str(root)))
        old = tempfile.tempdir
        tempfile.tempdir = str(root)
        scope.callback(setattr, tempfile, 'tempdir', old)
        guards = {key: scope.enter_context(patch(key, side_effect=AssertionError('live I/O forbidden')))
                  for key in (
                      'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                      'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
                      'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
                      'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
                      'subprocess.Popen', 'os.startfile')}
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=()))
        scope.enter_context(patch('src.core.serial_inventory.list_serial_port_names', return_value=[]))
        scope.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))
        from PySide6.QtCore import Qt
        from qt_workbench_probe import QtProjectWorkspaceTests
        from src.services.capability_jobs import CapabilityJobs
        from test_qt_log_history import QtLogHistoryTests
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        import run_tests

        location = json.loads((OUT / 'fixture-location.json').read_text(encoding='utf-8'))
        shared = Path(location['project']).resolve()
        assert shared.parent == Path(location['synthetic_root']).resolve()
        assert shared.parent.name.startswith('dutpilot-p1-cross-process-')
        evidence = {}

        class RemainingCase(QtProjectWorkspaceTests):
            def add_history(self, project, job):
                workspace = self.controller.adapter._service
                context = workspace.projects.opened[project]
                jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
                try:
                    QtLogHistoryTests.insert_job(jobs, job, 1795040200)
                    with jobs.db:
                        jobs.db.execute('UPDATE jobs SET payload=? WHERE id=?',
                            (json.dumps({'arguments': {'channel_ids': [7]}}), job))
                finally:
                    jobs.close()
                run_path = workspace.projects.snapshot(context)
                workspace.status.begin(context, job, run_path, 'aging.start')
                workspace.status.update(job, 'succeeded')
                return run_path

            def history(self, project, job):
                self.controller.history_action.trigger()
                history = self.controller.log_history
                self.wait_for(lambda: project in history.windows and history.windows[project].saved_reports_action.isEnabled())
                dialog = history.windows[project]
                dialog.jobs.setCurrentIndex(dialog.jobs.findData(job))
                self.wait_for(lambda: dialog.jobs.currentData() == job and dialog.saved_reports_action.isEnabled())
                return history, dialog

            def open_report(self, dialog):
                dialog.saved_reports_action.trigger()
                self.wait_for(lambda: dialog.saved_reports_dialog is not None)
                return dialog.saved_reports_dialog

            def test_writer(self):
                self.assertFalse(shared.exists())
                self.controller.submit('create', shared, '合成跨进程报告')
                self.wait_for(lambda: len(self.window.projects) == 1)
                project = self.window.selected_project
                job = 'fixture-cross-process-report'
                run_path = self.add_history(project, job)
                folder = run_path / 'Auto_power_on_off_tool/test_results/device_7'
                folder.mkdir(parents=True)
                source = folder / 'device_7_command_results_20261120221001.log'
                source.write_text('通道 7 ping 通\nsynthetic-private-body\n', encoding='utf-8')
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                history, dialog = self.history(project, job)
                dialog.result_files_action.trigger()
                self.wait_for(lambda: dialog.result_files_dialog is not None)
                files = dialog.result_files_dialog
                files.summary_action.trigger()
                self.wait_for(lambda: files.summary.isVisible() and files.save_report_action.isEnabled())
                self.assertIn('缺失 1 份', files.summary.toPlainText())
                with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('no source reread')) as reread:
                    files.save_report_action.trigger()
                    self.wait_for(lambda: '已保存历史报告' in files.feedback.text())
                    files.close()
                    self.wait_for(lambda: dialog.result_files_dialog is None)
                    view = self.open_report(dialog)
                    self.assertEqual(view.reports.count(), 1)
                    report = view.reports.item(0).data(Qt.ItemDataRole.UserRole)
                    self.assertEqual(report.project_id, project)
                    self.assertEqual(report.run_id, run_path.name)
                    self.assertEqual(reread.call_count, 0)
                    body = view.body.toPlainText()
                    self.assertNotIn('synthetic-private-body', body)
                    self.assertIn('不代表实时状态', body)
                    view.close()
                exact_file = next((shared / 'history/material_reports').glob('*/*.json'))
                self.assertEqual(exact_file.name, report.report_id + '.json')
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
                evidence.update(pid=os.getpid(), project_id=project, job_id=job, run_id=run_path.name,
                    report=asdict(report), body=body, record_sha256=hashlib.sha256(exact_file.read_bytes()).hexdigest(),
                    source_sha256=source_hash, source_relative=str(source.relative_to(shared)), source_rereads=0)
                dialog.close()
                self.wait_for(lambda: project not in history.windows)
                self.controller.submit('close', project, 'discard')
                self.wait_for(lambda: not self.window.projects)
                self.window.close()
                self.wait_for(lambda: self.controller.adapter.closed.is_set() and not self.window.isVisible())
                evidence['closed_normally'] = True

            def test_reader(self):
                expected = json.loads((OUT / 'writer-observation.json').read_text(encoding='utf-8'))
                self.assertNotEqual(os.getpid(), expected['pid'])
                self.assertTrue(expected['closed_normally'])
                correct = list((shared / 'history/material_reports').glob('*/*.json'))
                self.assertEqual(len(correct), 1)
                valid = correct[0]
                self.assertEqual(valid.name, expected['report']['report_id'] + '.json')
                self.assertEqual(hashlib.sha256(valid.read_bytes()).hexdigest(), expected['record_sha256'])
                corrupt = valid.parent / ('b' * 32 + '.json')
                self.assertFalse(corrupt.exists())
                with corrupt.open('x', encoding='utf-8') as stream:
                    stream.write('synthetic invalid record')
                source = shared / expected['source_relative']
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected['source_sha256'])
                self.controller.submit('open', shared)
                self.wait_for(lambda: self.window.selected_project == expected['project_id'])
                with ExitStack() as no_sources:
                    source_guards = [no_sources.enter_context(patch(endpoint, side_effect=AssertionError('no source reread')))
                        for endpoint in ('src.services.qt_archived_logs._read_page',
                                         'src.services.qt_power_logs.summarize_history_materials',
                                         'src.services.qt_power_logs.summarize_history_materials_batch')]
                    history, dialog = self.history(expected['project_id'], expected['job_id'])
                    view = self.open_report(dialog)
                    self.assertEqual(view.reports.count(), 1)
                    actual = view.reports.item(0).data(Qt.ItemDataRole.UserRole)
                    self.assertEqual(actual.report_id, expected['report']['report_id'])
                    self.assertEqual(view.body.toPlainText(), expected['body'])
                    self.assertIn('已保存 1 份；无法读取 1 份', view.feedback.text())
                    self.assertTrue(view.body.isReadOnly())
                    original_feedback = view.feedback.text()
                    view.close()
                    dialog.close()
                    self.wait_for(lambda: expected['project_id'] not in history.windows)
                    self.controller.submit('create', self.root / 'other-project', '另一合成项目')
                    self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != expected['project_id'])
                    other = self.window.selected_project
                    self.add_history(other, 'fixture-other-project-job')
                    _, other_dialog = self.history(other, 'fixture-other-project-job')
                    other_view = self.open_report(other_dialog)
                    self.assertEqual(other_view.reports.count(), 0)
                    self.assertIn('已保存 0 份；无法读取 0 份', other_view.feedback.text())
                    self.assertFalse(other_view.body.toPlainText())
                    evidence.update(pid=os.getpid(), writer_pid=expected['pid'], distinct_process=True,
                        report_id=actual.report_id, report_body_exact=True, valid_count=1, invalid_count=1,
                        original_feedback=original_feedback, other_project_count=0,
                        other_project_feedback=other_view.feedback.text(),
                        source_rereads=sum(item.call_count for item in source_guards),
                        no_business_execution=not self.controller.adapter._executions)
                    self.assertEqual(evidence['source_rereads'], 0)
                    self.assertTrue(evidence['no_business_execution'])
                    other_view.close()
                    other_dialog.close()
                self.assertEqual(hashlib.sha256(valid.read_bytes()).hexdigest(), expected['record_sha256'])
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected['source_sha256'])
                evidence['valid_record_unchanged'] = True
                evidence['original_source_unchanged'] = True

            def test_capacity(self):
                with ExitStack() as mocks:
                    mocks.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-chat'))
                    mocks.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                        side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'chat-cases')))
                    project_root = self.root / 'historical-capacity'
                    self.controller.submit('create', project_root, '合成历史容量')
                    self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
                    project = self.window.selected_project
                    model_store = self.controller.adapter._service.models
                    profile = ProviderProfile(base_url='https://fixture.invalid', model='fixture-capacity',
                                              context_tokens=65536)
                    model_store.save_profile(profile, 'synthetic-only-key')
                    self.window.ai_chat_action.trigger()
                    chat = self.controller.ai_chat
                    self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
                    dialog = chat.windows[project]
                    dialog.new_button.click()
                    self.wait_for(lambda: dialog.view.selected and not dialog.busy)
                    chosen = dialog.view.selected
                    snapshot = dict(identity=dict(capacity=65536), state='completed', basis='reply',
                        source='api', input_tokens=12, output_tokens=3, total_tokens=15,
                        updated='2026-11-25T10:00:00+08:00')
                    store = self.controller.adapter._model_settings.stores[project]
                    store.update_chat(chosen, context_usage=snapshot)
                    dialog.new_button.click()
                    self.wait_for(lambda: dialog.view.selected != chosen and not dialog.busy)
                    unknown_id = dialog.view.selected
                    dialog.close()
                    self.wait_for(lambda: project not in chat.windows)
                    current = next(item for item in model_store.profiles() if item.id == profile.id)
                    model_store.save_profile(replace(current, context_tokens=131072))
                    self.assertEqual(next(item for item in model_store.profiles() if item.id == profile.id).context_tokens, 131072)
                    self.controller.submit('close', project, 'discard')
                    self.wait_for(lambda: not self.window.projects)
                    self.controller.submit('open', project_root)
                    self.wait_for(lambda: self.window.selected_project == project and self.window.ai_chat_action.isEnabled())
                    self.window.ai_chat_action.trigger()
                    self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
                    dialog = chat.windows[project]
                    def select(identifier):
                        index = next(i for i, view in enumerate(dialog.view.sessions) if view.identifier == identifier)
                        dialog.sessions.setCurrentRow(index)
                        self.wait_for(lambda: dialog.view.selected == identifier and not dialog.busy)
                        self.assertFalse(dialog.view.running)
                    select(chosen)
                    old_text = dialog.usage.text()
                    self.assertIn('已保存历史用量（非当前请求）', old_text)
                    self.assertIn('记录当时上限 65,536', old_text)
                    self.assertIn('合计 15 Token', old_text)
                    self.assertNotIn('131,072', old_text)
                    select(unknown_id)
                    unknown = dialog.usage.text()
                    self.assertIn('已保存历史用量未知', unknown)
                    self.assertNotIn('131,072', unknown)
                    self.assertNotIn('65,536', unknown)
                    reopened = self.controller.adapter._model_settings.stores[project]
                    self.assertEqual(reopened.chat(chosen)['context_usage'], snapshot)
                    self.assertFalse(reopened.chat(unknown_id).get('context_usage'))
                    evidence.update(saved_capacity=65536, changed_synthetic_capacity=131072, displayed=old_text,
                                    unknown_displayed=unknown, historical_unchanged=True, running=dialog.view.running)

        globals()['RemainingCase'] = RemainingCase
        code = run_tests.main(['-v', '__main__.RemainingCase.test_' + MODE])
        counts = {key: item.call_count for key, item in guards.items()}
        evidence.update(mode=MODE, result_code=code, denied_calls=counts)
        (OUT / (MODE + '-observation.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REMAINING_L0_EVIDENCE: ' + json.dumps(evidence, ensure_ascii=False), flush=True)
        return code or int(any(counts.values()))


if __name__ == '__main__':
    sys.exit(run())

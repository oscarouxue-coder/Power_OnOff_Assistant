"""Synthetic read/display projection only. No actual widgets, workers, or execution."""
from contextlib import nullcontext
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import Qt
from src.models.qt_log_history import HistoryEventFilter, HistoryMaterialTarget, HistoryMaterialSummary
from src.services.ai_record_titles import AiRecordTitles
from src.services.qt_ai_chat import CHAT_PAGE
from src.services.qt_ai_reports import QtAiReports
from src.services.qt_log_history import JOBS_PER_PAGE, read_log_history
from src.services.qt_power_logs import (material_report_snapshot, save_material_report, read_material_reports,
                                        _REPORT_LIMIT)
from src.services.qt_workspace_adapter import ProjectCommandResult
from src.ui.qt.ai_chat_controller import AiChatController
from src.ui.qt.ai_chat_dialog import AiChatDialog
from src.ui.qt.ai_report_dialog import AiReportDialog
from src.ui.qt.log_history_dialog import LogHistoryController, LogHistoryDialog, SavedMaterialReportsDialog
import test_qt_ai_turn_display as chat_fixtures
import test_qt_log_history as history_fixtures


class TextProjection:
    def __init__(self):
        self.text = ''
    def setText(self, text):
        self.text = text
    setPlainText = setText


class ItemProjection:
    def __init__(self, text):
        self.text, self.values, self.selected = text, {}, False
    def setData(self, role, value):
        self.values[role] = value
    def data(self, role):
        return self.values.get(role)
    def setSelected(self, selected):
        self.selected = selected


class ListProjection:
    def __init__(self):
        self.clear()
    def clear(self):
        self.items, self.current = [], None
    def addItem(self, item):
        self.items.append(item)
    def currentItem(self):
        return self.current
    def selectedItems(self):
        return [item for item in self.items if item.selected]
    def setCurrentItem(self, item, _flags=None):
        self.current = item
    def scrollToItem(self, item):
        pass


class ReportProjection:
    show_view = AiReportDialog.show_view
    show_detail = AiReportDialog.show_detail
    _selected = AiReportDialog._selected
    _current = AiReportDialog._current
    def __init__(self, project_id):
        self.project_id = project_id
        self.reports, self.rows, self.detail = ListProjection(), {}, None
        self.analysis, self.evidence, self.metadata, self.feedback = (TextProjection() for _ in range(4))
    def _sync(self):
        pass
    def set_busy(self, busy):
        self.busy = busy


class ComboProjection:
    """Models the first-current-row contract, not native QComboBox rendering."""
    def __init__(self):
        self.clear()
    def clear(self):
        self.rows, self.index = [], -1
    def addItem(self, label, identifier):
        self.rows.append({Qt.ItemDataRole.UserRole: identifier})
        if self.index < 0:
            self.index = 0
    def count(self):
        return len(self.rows)
    def setItemData(self, index, value, role):
        self.rows[index][role] = value
    def currentData(self, role=Qt.ItemDataRole.UserRole):
        return self.rows[self.index].get(role) if self.index >= 0 else None


class LogProjection:
    def __init__(self):
        self.entries = []
    def clear_display(self):
        self.entries.clear()
    def set_scope(self, project, _name, job, _channels):
        self.scope = project, job
    def append_batch(self, entries):
        self.entries.extend(entries)
    def set_export_enabled(self, enabled):
        pass


class HistoryProjection:
    show_jobs = LogHistoryDialog.show_jobs
    _select_job = LogHistoryDialog._select_job
    _request_events = LogHistoryDialog._request_events
    show_logs = LogHistoryDialog.show_logs
    _job_title = staticmethod(LogHistoryDialog._job_title)
    def __init__(self, project, controller):
        self.project_id, self.project_name = project.identity.project_id, project.identity.name
        self.jobs, self.logs, self.feedback = ComboProjection(), LogProjection(), TextProjection()
        self.source_generation, self.busy, self.reloads = 0, False, 0
        self.jobs_cursor = self.events_cursor = None
        self.page_filter = HistoryEventFilter()
        self.saved_reports_dialog = None
        self.events_requested = SimpleNamespace(emit=lambda job, before, filters:
            controller._submit(self, 'history_events', before, job, filters))
    def set_busy(self, busy, **_kwargs):
        self.busy = busy
    def _update_filter_feedback(self):
        pass
    def load_source(self):
        self.reloads += 1


class SavedViewerProjection:
    def __init__(self, _dialog, job, page):
        self.job, self.page = job, page
        self.finished = SimpleNamespace(connect=lambda _callback: None)
    def show(self):
        pass
    def close(self):
        pass


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class HistoryIdentityProbe(TestCase):
    _cancel_store = chat_fixtures.TurnDisplayTests._cancel_store
    _open_cancel_store = chat_fixtures.TurnDisplayTests._open_cancel_store
    _cancel_conversation = staticmethod(chat_fixtures.TurnDisplayTests._cancel_conversation)
    _cancel_view = staticmethod(chat_fixtures.TurnDisplayTests._cancel_view)
    open_jobs = history_fixtures.QtLogHistoryTests.open_jobs
    insert_job = staticmethod(history_fixtures.QtLogHistoryTests.insert_job)

    def test_conversation_list_past_100_and_paged_messages_keep_selected_id(self):
        store, _ = self._cancel_store()
        conversation, _ = self._cancel_conversation(store)
        ids = [f'session-{index:03d}' for index in range(125)]
        for identifier in ids:
            store.create_chat(dict(id=identifier, created='2026-11-26T10:00:00+08:00', scope='general',
                title='同名会话', target_label='fixture', model='', status='等待'))
        for identifier in (ids[0], ids[100]):
            for index in range(CHAT_PAGE + 3):
                conversation.message(identifier, 'user' if index % 2 == 0 else 'assistant', f'{identifier}:{index}')
        selected_ids = []
        conversation.router = SimpleNamespace(select=selected_ids.append)
        chat = self._cancel_view(store, conversation, ids[0])
        chat.titles = AiRecordTitles(store, lambda _line: None)
        chat._select(ids[0])
        latest = chat.snapshot()
        self.assertEqual(len(latest.sessions), 128)
        self.assertEqual(len([row for row in latest.sessions if row.title == '同名会话']), 125)
        self.assertTrue(all(m.text.startswith(ids[0] + ':') for m in latest.messages))
        self.assertEqual(len(latest.messages), CHAT_PAGE)
        self.assertIsNotNone(latest.next_cursor)
        chat.cursor = latest.next_cursor
        older = chat.snapshot()
        self.assertEqual(len(older.messages), 3)
        self.assertTrue(all(m.text.startswith(ids[0] + ':') for m in older.messages))
        chat._select(ids[100])
        second = chat.snapshot()
        self.assertEqual(second.selected, ids[100])
        self.assertEqual(len(second.messages), CHAT_PAGE)
        self.assertTrue(all(m.text.startswith(ids[100] + ':') for m in second.messages))
        self.assertFalse(AiChatDialog.accepts_view(SimpleNamespace(view=second), older))
        chat._select(ids[0])
        returned = chat.snapshot()
        self.assertEqual(returned.selected, ids[0])
        self.assertEqual(returned.messages, latest.messages)
        self.assertEqual(selected_ids, [ids[0], ids[100], ids[0]])

    def test_report_list_over_100_exact_id_detail_and_closed_window_late_response(self):
        store, _ = self._cancel_store()
        ids = [f'report-{index:03d}' for index in range(125)]
        for identifier in ids:
            store.save_report(identifier, dict(report=f'合成正文 {identifier}', evidence='合成证据', channel=7))
            store.rename_record('report', identifier, '同名报告')
        diagnostic = SimpleNamespace(store=store, report_deletion_busy_ids=lambda: set())
        service = QtAiReports(diagnostic, AiRecordTitles(store, lambda _line: None))
        dialog = ReportProjection('project-a')
        with patch('src.ui.qt.ai_report_dialog.QSignalBlocker', side_effect=lambda _obj: nullcontext()), \
                patch('src.ui.qt.ai_report_dialog.QListWidgetItem', ItemProjection):
            view = service.execute('ai_report_open', ('',))
            self.assertEqual(len(view.rows), 125)
            self.assertTrue(all(row.title == '同名报告' for row in view.rows))
            dialog.show_view(view)
            self.assertEqual(dialog._current(), dialog.detail.identifier)
            self.assertIn(dialog._current(), dialog.analysis.text)
            target = ids[100]
            item = next(item for item in dialog.reports.items if item.data(Qt.ItemDataRole.UserRole) == target)
            for row in dialog.reports.items:
                row.setSelected(row is item)
            dialog.reports.setCurrentItem(item)
            detail = service.execute('ai_report_select', (target,))
            dialog.show_detail(detail)
            self.assertEqual(dialog._current(), detail.identifier)
            self.assertEqual(dialog.analysis.text, f'合成正文 {target}')
            self.assertIn(target, dialog.metadata.text)
            refreshed = service.execute('ai_report_open', (target,))
            dialog.show_view(refreshed)
            self.assertEqual(dialog._current(), target)
            self.assertEqual(dialog.detail.identifier, target)
            self.assertEqual(dialog._selected(), (target,))

            reopened = ReportProjection('project-a')
            reopened.show_view(service.execute('ai_report_open', (ids[0],)))
            controller = object.__new__(AiChatController)
            controller.requests = {101: dialog}
            controller.workspace = SimpleNamespace(closing=False)
            controller.windows, controller.case_windows = {}, {}
            controller.report_windows = {'project-a': reopened}
            result = ProjectCommandResult(101, 'ai_report_select', 'project-a', payload=detail)
            self.assertTrue(controller.handle_result(result))
            self.assertEqual(reopened._current(), ids[0])
            self.assertEqual(reopened.detail.identifier, ids[0])
            self.assertFalse(controller.handle_result(result))

    def test_task_pages_select_actual_first_id_and_batch_reports_do_not_cross(self):
        history_fixtures.QtLogHistoryTests.setUp(self)
        jobs = self.open_jobs(self.project)
        other = self.open_jobs(self.other)
        all_ids = [f'batch-{index:03d}' for index in range(JOBS_PER_PAGE * 2 + 3)]
        for index, identifier in enumerate(all_ids):
            self.insert_job(jobs, identifier, index)
            jobs.event(identifier, 'history', f'{{"channel":7,"text":"record-{identifier}"}}')
        self.insert_job(other, all_ids[-1], 0)
        other.event(all_ids[-1], 'history', '{"channel":7,"text":"other-project"}')
        submitted = {}
        def submit(operation, project, *args):
            identifier = len(submitted) + 1
            submitted[identifier] = (operation, project, args)
            return identifier
        controller = object.__new__(LogHistoryController)
        controller.workspace = SimpleNamespace(closing=False, submit=submit,
            window=SimpleNamespace(selected_project=self.project.identity.project_id))
        controller.requests, controller.report_requests = {}, {}
        dialog = HistoryProjection(self.project, controller)
        controller.windows = {dialog.project_id: dialog}

        def deliver(identifier):
            operation, project, args = submitted[identifier]
            self.assertEqual(project, dialog.project_id)
            result = read_log_history(self.project, *args)
            return controller.handle_result(ProjectCommandResult(identifier, operation, project, payload=result))

        def check_details(expected):
            self.assertEqual(dialog.jobs.currentData(), expected)
            self.assertEqual(dialog.logs.scope, (dialog.project_id, expected))
            identifier = max(submitted)
            self.assertEqual(submitted[identifier][2][1], expected)
            self.assertTrue(deliver(identifier))
            self.assertEqual(len(dialog.logs.entries), 1)
            row = dialog.logs.entries[0]
            self.assertEqual((row.project_id, row.run_id), (dialog.project_id, expected))
            self.assertIn('record-' + expected, row.message)
            self.assertNotIn('other-project', row.message)
            return identifier

        with patch('src.ui.qt.log_history_dialog.QSignalBlocker', side_effect=lambda _obj: nullcontext()):
            controller._submit(dialog, 'history_jobs', None)
            self.assertTrue(deliver(max(submitted)))
            first = check_details(all_ids[-1])
            self.assertEqual(dialog.jobs.count(), JOBS_PER_PAGE)
            controller._submit(dialog, 'history_jobs', dialog.jobs_cursor)
            self.assertTrue(deliver(max(submitted)))
            second_job = all_ids[-1 - JOBS_PER_PAGE]
            check_details(second_job)
            self.assertFalse(deliver(first))  # duplicate old completion
            self.assertEqual(dialog.jobs.currentData(), second_job)
            controller._submit(dialog, 'history_jobs', None)
            self.assertTrue(deliver(max(submitted)))
            check_details(all_ids[-1])
            dialog.jobs.index = 1
            dialog._select_job()
            check_details(all_ids[-2])
            controller._submit(dialog, 'history_events', None, all_ids[-2], HistoryEventFilter())
            stale = max(submitted)
            dialog.source_generation += 1  # source change while reading is allowed
            self.assertTrue(deliver(stale))
            self.assertEqual(dialog.reloads, 1)

        a_job, b_job = all_ids[-1], all_ids[-2]
        records = {a_job: dict(owner=a_job, project_id=dialog.project_id, run_id='a' * 32, state='succeeded', updated_at=1795040123),
                   b_job: dict(owner=b_job, project_id=dialog.project_id, run_id='b' * 32, state='succeeded', updated_at=1795040123)}
        with patch('src.services.qt_power_logs.datetime', FixedDatetime):
            for job, count in ((a_job, _REPORT_LIMIT), (b_job, 2)):
                record = records[job]
                target = HistoryMaterialTarget(dialog.project_id, job, record['run_id'], 7)
                for index in range(count):
                    summary = HistoryMaterialSummary(target, f'合成报告 {job}/{index}', 1, 0, 0)
                    snapshot = material_report_snapshot(self.project, record, summary)
                    save_material_report(self.project, record, snapshot, Event())
            too_many = material_report_snapshot(self.project, records[a_job],
                HistoryMaterialSummary(HistoryMaterialTarget(dialog.project_id, a_job, records[a_job]['run_id'], 7), '额外合成记录', 1, 0, 0))
            with self.assertRaises(ValueError):
                save_material_report(self.project, records[a_job], too_many, Event())

        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('must not reread source')):
            a_page = read_material_reports(self.project, records[a_job], a_job, Event())
            b_page = read_material_reports(self.project, records[b_job], b_job, Event())
        self.assertEqual((len(a_page.reports), len(b_page.reports)), (_REPORT_LIMIT, 2))
        self.assertEqual(len({(row.saved_at, row.channels) for row in a_page.reports}), 1)
        self.assertEqual(len({row.report_id for row in a_page.reports}), _REPORT_LIMIT)
        self.assertTrue(all(row.job_id == a_job and row.run_id == records[a_job]['run_id'] for row in a_page.reports))
        self.assertTrue(all(row.job_id == b_job and row.run_id == records[b_job]['run_id'] for row in b_page.reports))

        dialog.jobs.index = 0
        controller._read_saved_reports(dialog, a_job)
        late = max(submitted)
        dialog.jobs.index = 1
        with patch('src.ui.qt.log_history_dialog.SavedMaterialReportsDialog', SavedViewerProjection):
            self.assertTrue(controller.handle_result(ProjectCommandResult(late, 'history_material_reports', dialog.project_id, payload=a_page)))
            self.assertIsNone(dialog.saved_reports_dialog)
            controller._read_saved_reports(dialog, b_job)
            self.assertTrue(controller.handle_result(ProjectCommandResult(max(submitted), 'history_material_reports', dialog.project_id, payload=b_page)))
            self.assertEqual(dialog.saved_reports_dialog.job, b_job)
            self.assertEqual(dialog.saved_reports_dialog.page, b_page)
        display = SimpleNamespace(body=TextProjection())
        for report in (a_page.reports[0], a_page.reports[-1], b_page.reports[1]):
            item = ItemProjection(report.saved_at)
            item.setData(Qt.ItemDataRole.UserRole, report)
            SavedMaterialReportsDialog._show_report(display, item, None)
            self.assertIn(report.report_id, display.body.text)
            self.assertTrue(display.body.text.endswith(report.text))


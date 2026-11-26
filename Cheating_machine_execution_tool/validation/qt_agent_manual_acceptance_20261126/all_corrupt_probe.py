"""One synthetic, all-invalid saved-report read and empty detail projection."""
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.models.qt_log_history import HistoryMaterialSummary, HistoryMaterialTarget
from src.services.qt_power_logs import (_report_scope, material_report_snapshot,
                                        read_material_reports, save_material_report)
from src.ui.qt.log_history_dialog import SavedMaterialReportsDialog
import test_qt_log_history as history_fixtures


class AllCorruptSavedReportsProbe(TestCase):
    open_jobs = history_fixtures.QtLogHistoryTests.open_jobs
    insert_job = staticmethod(history_fixtures.QtLogHistoryTests.insert_job)

    def test_all_corrupt_batch_has_no_report_or_stale_detail(self):
        history_fixtures.QtLogHistoryTests.setUp(self)
        jobs = self.open_jobs(self.project)
        self.insert_job(jobs, 'valid-batch', 1)
        self.insert_job(jobs, 'corrupt-batch', 2)
        self.insert_job(jobs, 'empty-batch', 3)
        project_id = self.project.identity.project_id
        def record(job, run):
            return dict(owner=job, run_id=run, project_id=project_id, state='succeeded', updated_at=1795040123)
        valid = record('valid-batch', 'a' * 32)
        corrupt = record('corrupt-batch', 'b' * 32)
        empty = record('empty-batch', 'c' * 32)
        target = HistoryMaterialTarget(project_id, 'valid-batch', valid['run_id'], 7)
        snapshot = material_report_snapshot(self.project, valid,
            HistoryMaterialSummary(target, '合成有效报告正文', 1, 0, 0))
        saved = save_material_report(self.project, valid, snapshot, Event())
        _, directory = _report_scope(self.project, corrupt, 'corrupt-batch')
        directory.mkdir(parents=True)
        fixtures = {'1' * 32 + '.json': b'{"version":1,',
                    '2' * 32 + '.json': b'{"version":1,"digest":"invalid","report":{}}'}
        for name, contents in fixtures.items():
            with (directory / name).open('xb') as stream:
                stream.write(contents)

        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('must not reread source')) as source:
            good = read_material_reports(self.project, valid, 'valid-batch', Event())
            bad = read_material_reports(self.project, corrupt, 'corrupt-batch', Event())
            absent = read_material_reports(self.project, empty, 'empty-batch', Event())
            self.assertEqual(source.call_count, 0)
        self.assertEqual((good.reports, good.invalid_count), ((saved,), 0))
        self.assertEqual((bad.run_id, bad.reports, bad.invalid_count), (corrupt['run_id'], (), 2))
        self.assertEqual((absent.run_id, absent.reports, absent.invalid_count), (empty['run_id'], (), 0))

        text = []
        projection = SimpleNamespace(body=SimpleNamespace(setPlainText=text.append))
        item = SimpleNamespace(data=lambda _role: good.reports[0])
        SavedMaterialReportsDialog._show_report(projection, item, None)
        self.assertIn(saved.report_id, text[-1])
        self.assertTrue(text[-1].endswith('合成有效报告正文'))
        SavedMaterialReportsDialog._show_report(projection, None, item)
        self.assertEqual(text[-1], '')
        self.assertEqual({name: (directory / name).read_bytes() for name in fixtures}, fixtures)


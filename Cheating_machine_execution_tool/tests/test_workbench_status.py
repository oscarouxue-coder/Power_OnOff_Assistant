import threading
from types import SimpleNamespace
import unittest

from src.services.workbench_status_service import workbench_projects, run_channel_snapshot


class WorkbenchStatusTests(unittest.TestCase):
    def test_retained_channels_from_a_previous_run_are_not_aggregated(self):
        progress = {1: (5, 100, 'current'), 2: (90, 100, 'previous')}
        states = {1: ('running', ''), 2: ('success', '')}
        current, results = run_channel_snapshot(progress, states, [1])
        self.assertEqual(set(current), {1})
        self.assertNotIn(2, results)
        self.assertEqual(run_channel_snapshot(progress, states, None), ({}, {}))
        self.assertEqual(set(progress), {1, 2})

    def rows(self, progress, states=None, records=None):
        service = SimpleNamespace(lock=threading.RLock(), records=records or {})
        project = dict(project_id='p', name='test', state='running', active_task_count=1,
                       unknown_task_count=0, last_result='', updated_at=0)
        return workbench_projects(service, [project], {'p': (progress, states or {})})[0]

    def test_different_channel_rounds_do_not_become_a_single_percentage(self):
        row = self.rows({1: (10, 100, 'waiting'), 2: (30, 100, 'running')})
        self.assertIsNone(row['fraction'])
        self.assertIn('10–30', row['progress_text'])
        self.assertIn('正常 0', row['channel_text'])

    def test_equal_rounds_and_explicit_results_are_projected_without_mutation(self):
        progress = {1: (20, 100, 'complete'), 2: (20, 100, 'complete')}
        row = self.rows(progress, {1: ('success', ''), 2: ('failed', '')})
        self.assertEqual(row['fraction'], .2)
        self.assertIn('正常 1  失败 1', row['channel_text'])
        self.assertEqual(progress[1], (20, 100, 'complete'))

    def test_aging_capability_is_explicitly_presented_as_power_cycling(self):
        record = dict(project_id='p', state='running', operation='aging.start', started_at=1, updated_at=1)
        row = self.rows({}, records={'job': record})
        self.assertEqual(row['task_label'], '开关机挂测')
        self.assertIsNone(row['fraction'])
        self.assertIn('尚无', row['channel_text'])

    def test_invalid_historical_start_time_does_not_break_overview(self):
        record = dict(project_id='p', state='running', started_at='invalid', updated_at=1)
        self.assertEqual(self.rows({}, records={'job': record})['started_text'], '开始时间待核实')

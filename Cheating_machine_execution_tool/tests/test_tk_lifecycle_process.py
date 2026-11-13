"""All potentially hanging Tk/GC pressure is confined to a timed child."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TkLifecycleProcessTests(unittest.TestCase):
    def test_eight_readers_gc_close_reopen_and_complete_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary)/'result.json'
            script = Path(__file__).with_name('serial_lifecycle_stress.py')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(script), '--child',
                                     '--seconds', '3', '--cycles', '8', '--report', str(report)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(evidence['passed'], evidence)
            self.assertEqual(evidence['cycles'], 8)
            self.assertGreaterEqual(evidence['tk_finalizers'], 8*9)
            self.assertEqual(evidence['wrong_tk_threads'], [])
            self.assertEqual(evidence['retained_closed_pipeline_windows'], 0)
            self.assertEqual(evidence['max_subscriptions'], 8)
            self.assertTrue(all(evidence['log_integrity'].values()))
            self.assertEqual(evidence['remaining_sim_threads'], [])
            self.assertGreaterEqual(evidence['offscreen_windows_created'], 10)
            self.assertEqual(evidence['offscreen_violations'], [])

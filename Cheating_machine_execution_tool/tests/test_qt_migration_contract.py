"""Qt migration contracts that do not add Qt to the original Tk environment."""
import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import Mock
from unittest.mock import patch
from src.models.workbench_presentation import ChannelView, ProjectView


class QtMigrationContractTests(unittest.TestCase):
    def test_frozen_qt_defaults_to_workspace_while_source_requires_a_mode(self):
        import run_dutpilot_qt

        app = ModuleType('src.ui.qt.application')
        app.run_workspace = Mock(return_value=0)
        app.run_demo = Mock(return_value=0)
        with patch.dict(sys.modules, {'src.ui.qt.application': app}), \
                patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(run_dutpilot_qt.main([]), 0)
            self.assertEqual(run_dutpilot_qt.main(['工程副本/project.linecheck.json']), 0)
            self.assertEqual(run_dutpilot_qt.main(['--demo']), 0)
        self.assertEqual([call.args for call in app.run_workspace.call_args_list],
                         [(None,), ('工程副本/project.linecheck.json',)])
        app.run_demo.assert_called_once_with()
        with patch.object(sys, 'frozen', False, create=True), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            run_dutpilot_qt.main([])

    def test_native_verification_keeps_timeout_diagnostics_and_checks_every_scale(self):
        from scripts import verify_qt_migration

        timeout = subprocess.TimeoutExpired('simulated native child', 210, output='partial text', stderr=b'partial bytes')
        with tempfile.TemporaryDirectory() as directory, \
             patch('verify_gui_test_coverage.check', return_value=[]), \
             patch('tk_test_windows.run_gui_child', side_effect=timeout) as native:
            status = verify_qt_migration.main(['--python', sys.executable, '--output', directory])
            self.assertEqual(status, 1)
            self.assertEqual(native.call_count, 3)
            reports = json.loads((Path(directory) / 'results.json').read_text(encoding='utf-8'))
            for scale, report in zip(('1', '1.25', '1.5'), reports):
                self.assertEqual(report['scale'], scale)
                self.assertFalse(report['passed'])
                text = (Path(directory) / ('scale-' + scale) / 'tests.txt').read_text(encoding='utf-8')
                self.assertIn('partial text', text)
                self.assertIn('partial bytes', text)
                self.assertIn('exceeded 210 seconds', text)

    def test_ui_package_no_longer_eagerly_imports_tk(self):
        code = "import sys;import src.ui;assert 'tkinter' not in sys.modules;assert 'PySide6' not in sys.modules"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_ui_exports_keep_their_identity(self):
        from src.ui import SerialTerminalWindow, DutConfigWindow, load_module_window_size
        from src.ui.serial_terminal import SerialTerminalWindow as OriginalSerial
        from src.ui.dut_config_window import DutConfigWindow as OriginalDut
        self.assertIs(SerialTerminalWindow, OriginalSerial)
        self.assertIs(DutConfigWindow, OriginalDut)
        self.assertTrue(callable(load_module_window_size))

    def test_display_unknowns_are_not_defaulted_to_normal_or_zero(self):
        channel = ChannelView(1, 'unknown')
        self.assertIsNone(channel.cycle)
        self.assertIsNone(channel.total)
        project = ProjectView('p', 'name', 'type', 'dut', 'unknown', '未知', '—', '待核实', None, '暂无结果')
        self.assertIsNone(project.progress)
        self.assertIsNone(project.success_count)
        self.assertIsNone(project.failure_count)

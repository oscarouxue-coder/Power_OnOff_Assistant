"""Qt migration contracts that do not add Qt to the original Tk environment."""
import json
import os
from contextlib import redirect_stderr
from dataclasses import replace
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
    def test_workspace_startup_failure_reports_existing_instance(self):
        import run_dutpilot_qt
        from src.core.workspace_instance import WorkspaceInstanceError

        app = ModuleType('src.ui.qt.application')
        app.run_workspace = Mock(side_effect=WorkspaceInstanceError('此电脑已有 DUTPilot 正在运行'))
        app.run_demo = app.run_showcase = app.run_visual_preview = Mock()
        with patch.dict(sys.modules, {'src.ui.qt.application': app}), \
                patch.object(sys, 'frozen', True, create=True), \
                patch.object(run_dutpilot_qt, 'report_startup_error') as report:
            self.assertEqual(run_dutpilot_qt.main([]), 1)
        report.assert_called_once_with('此电脑已有 DUTPilot 正在运行')

    def test_frozen_and_source_default_to_workspace_and_keep_explicit_previews(self):
        import run_dutpilot_qt

        app = ModuleType('src.ui.qt.application')
        app.run_workspace = Mock(return_value=0)
        app.run_demo = Mock(return_value=0)
        app.run_showcase = Mock(return_value=0)
        app.run_visual_preview = Mock(return_value=0)
        with patch.dict(sys.modules, {'src.ui.qt.application': app}), \
                patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(run_dutpilot_qt.main([]), 0)
            self.assertEqual(run_dutpilot_qt.main(['工程副本/project.linecheck.json']), 0)
            self.assertEqual(run_dutpilot_qt.main(['--demo']), 0)
            self.assertEqual(run_dutpilot_qt.main(['--showcase']), 0)
            self.assertEqual(run_dutpilot_qt.main(['--visual-preview']), 0)
            for extra in (['project.linecheck.json'], ['--project-peers', 'peers.json'], ['--workspace'],
                          ['--gateway-slot', '1']):
                for preview in ('--showcase', '--visual-preview'):
                    with self.subTest(preview=preview, extra=extra), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                        run_dutpilot_qt.main([preview, *extra])
        self.assertEqual([call.args for call in app.run_workspace.call_args_list],
                         [(None,), (str(Path.cwd() / '工程副本/project.linecheck.json'),)])
        app.run_demo.assert_called_once_with()
        app.run_showcase.assert_called_once_with()
        app.run_visual_preview.assert_called_once_with()
        with patch.dict(sys.modules, {'src.ui.qt.application': app}):
            self.assertEqual(run_dutpilot_qt.main([]), 0)
            app.run_workspace.assert_called_with(None)
            app.run_workspace.reset_mock()
            for slot in ('0', '65'):
                with self.subTest(slot=slot), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    run_dutpilot_qt.main(['--gateway-slot', slot])
            with redirect_stderr(StringIO()) as message:
                self.assertEqual(run_dutpilot_qt.main(['--legacy-single-project']), 2)
                self.assertIn('导入旧配置目录', message.getvalue())
            app.run_workspace.assert_not_called()

    def test_missing_qt_forwards_arguments_once_or_reports_setup(self):
        import run_dutpilot_qt
        argv = ['工程 副本/project.linecheck.json', '--gateway-slot', '64']
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'LOCALAPPDATA': folder}), \
                patch.dict(sys.modules, {'PySide6.QtCore': None}), patch('subprocess.call', return_value=7) as launch:
            sys.modules.pop('src.ui.qt.application', None)
            python = Path(folder) / 'LineCheckAssistant/qt-dev-py39/Scripts/python.exe'
            with redirect_stderr(StringIO()) as message:
                self.assertEqual(run_dutpilot_qt.main(argv), 2)
                self.assertIn('-WithBusinessDependencies', message.getvalue())
                launch.assert_not_called()
            python.parent.mkdir(parents=True)
            python.touch()
            self.assertEqual(run_dutpilot_qt.main(argv), 7)
            launch.assert_called_once_with([str(python), str(Path(run_dutpilot_qt.__file__).resolve()), *argv])
            with patch.object(sys, 'executable', str(python)), redirect_stderr(StringIO()):
                self.assertEqual(run_dutpilot_qt.main(argv), 2)
            self.assertEqual(launch.call_count, 1)

    def test_native_verification_keeps_timeout_diagnostics_and_checks_every_scale(self):
        from scripts import verify_qt_migration

        timeout = subprocess.TimeoutExpired('simulated native child', 210, output='partial text', stderr=b'partial bytes')
        with tempfile.TemporaryDirectory() as directory, \
             patch('verify_gui_test_coverage.check', return_value=[]), \
             patch('scripts.gui_test_process.run_gui_child', side_effect=timeout) as native:
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

    def test_display_unknowns_are_not_defaulted_to_normal_or_zero(self):
        channel = ChannelView(1, 'unknown')
        self.assertIsNone(channel.cycle)
        self.assertIsNone(channel.total)
        project = ProjectView('p', 'name', 'type', 'dut', 'unknown', '未知', '—', '待核实', None, '暂无结果')
        self.assertIsNone(project.progress)
        self.assertIsNone(project.success_count)
        self.assertIsNone(project.failure_count)
        self.assertEqual((project.success_text, project.failure_text, project.attention_text), ('—', '—', '—'))
        partial = replace(project, success_count=0, attention_count=3)
        self.assertEqual((partial.success_text, partial.failure_text, partial.attention_text), ('0', '—', '3'))
        measured = replace(project, success_count=17, failure_count=2, attention_count=1)
        self.assertEqual((measured.success_text, measured.failure_text, measured.attention_text), ('17', '2', '1'))

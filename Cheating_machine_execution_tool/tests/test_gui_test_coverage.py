"""Fail-closed GUI preflight and runtime ownership; negative probes are isolated."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_gui_test_coverage import check
from tk_test_windows import _private_render_desktop, run_gui_child


class GuiCoverageTests(unittest.TestCase):
    def inspect_source(self, source, extra=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_example.py').write_text(source, encoding='utf-8')
            for name, content in (extra or {}).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            return check(root)

    def test_missing_fixture_and_import_only_fail(self):
        for setup in ('', 'from tk_test_windows import install_offscreen_windows\n'):
            with self.subTest(setup=setup):
                errors = self.inspect_source(setup + 'import tkinter as ui\nroot = ui.Tk()\n')
                self.assertTrue(errors)
                self.assertIn('test_example.py:', errors[0])

    def test_late_or_conditional_installation_fails(self):
        cases = (
            'root=Tk()\ninstall_offscreen_windows(self)',
            'if condition:\n    install_offscreen_windows(self)\nroot=Tk()',
        )
        for body in cases:
            with self.subTest(body=body):
                source = 'from tkinter import Tk\nfrom tk_test_windows import install_offscreen_windows\ndef test(self):\n'
                source += '\n'.join('    ' + line for line in body.splitlines())
                self.assertTrue(self.inspect_source(source))

    def test_alias_setup_and_inherited_fixture_pass(self):
        source = '''from tkinter import Tk as Root
from tk_test_windows import install_offscreen_windows as own
class Base:
    def setUp(self):
        own(self)
        self.root=Root()
class Derived(Base):
    def test_child(self):
        self.other=Root()
'''
        self.assertEqual(self.inspect_source(source), [])

    def test_with_scope_does_not_protect_following_creation(self):
        prefix = 'from tkinter import Tk\nfrom tk_test_windows import OffscreenTkWindows\n'
        self.assertEqual(self.inspect_source(prefix + 'with OffscreenTkWindows():\n    root=Tk()\n'), [])
        self.assertTrue(self.inspect_source(prefix + 'with OffscreenTkWindows():\n    pass\nroot=Tk()\n'))

    def test_source_tk_subclass_is_detected(self):
        errors = self.inspect_source('from src.ui.example import Window\nroot=Window()\n',
            {'src/ui/example.py': 'import tkinter as tk\nclass Window(tk.Tk):\n    pass\n'})
        self.assertTrue(errors)

    def test_mock_constructor_and_tcl_do_not_require_scope(self):
        self.assertEqual(self.inspect_source('''import tkinter as tk
from unittest.mock import patch
interpreter=tk.Tcl()
other=tk.Tk(useTk=False)
with patch.object(tk.Tk, '__init__'):
    root=tk.Tk()
'''), [])

    def test_native_creation_and_new_framework_are_rejected(self):
        for source in ("import _tkinter\nroot=_tkinter.create()", "import PySide6", "from wx import Frame"):
            with self.subTest(source=source):
                self.assertTrue(self.inspect_source(source))

    def test_qt_and_tk_require_their_own_scopes(self):
        qt = 'from PySide6.QtWidgets import QWidget\nfrom qt_test_guard import QtTestScope\n'
        self.assertEqual(self.inspect_source(qt + 'with QtTestScope():\n    window=QWidget()\n'), [])
        self.assertTrue(self.inspect_source(qt + 'with QtTestScope():\n    pass\nwindow=QWidget()\n'))
        self.assertTrue(self.inspect_source(qt + 'from tkinter import Tk\nwith QtTestScope():\n    window=Tk()\n'))
        self.assertTrue(self.inspect_source(qt + 'from tk_test_windows import OffscreenTkWindows\nwith OffscreenTkWindows():\n    window=QWidget()\n'))

    def test_derived_qt_window_requires_a_qt_fixture(self):
        child = {'src/ui/example.py': 'from PySide6.QtWidgets import QMainWindow\nclass Window(QMainWindow):\n    pass\n'}
        prefix = 'from src.ui.example import Window\nfrom qt_test_guard import QtTestScope\n'
        self.assertTrue(self.inspect_source(prefix + 'window=Window()\n', child))
        self.assertEqual(self.inspect_source(prefix + 'with QtTestScope():\n    window=Window()\n', child), [])

    def test_inline_child_requires_own_scope_and_evidence_wrapper(self):
        child = 'import tkinter as tk\nroot=tk.Tk()\n'
        source = 'import subprocess,sys\nsubprocess.run([sys.executable,"-c",' + repr(child) + '])'
        self.assertTrue(self.inspect_source(source))
        child = 'import tkinter as tk\nfrom tk_test_windows import OffscreenTkWindows\nwith OffscreenTkWindows():\n    root=tk.Tk()\n'
        source = 'from tk_test_windows import run_gui_child\nimport sys\nrun_gui_child([sys.executable,"-c",' + repr(child) + '],timeout=3)'
        self.assertEqual(self.inspect_source(source), [])

    def test_unresolved_inline_child_fails(self):
        self.assertTrue(self.inspect_source('import subprocess,sys\nsubprocess.run([sys.executable,"-c",make_code()])'))

    def test_named_gui_child_requires_independent_evidence(self):
        source = '''import subprocess,sys
from pathlib import Path
script=Path(__file__).with_name('gui_child.py')
subprocess.run([sys.executable,str(script)])
'''
        child = '''import tkinter as tk
from tk_test_windows import OffscreenTkWindows
with OffscreenTkWindows():
    root=tk.Tk()
'''
        errors = self.inspect_source(source, {'tests/gui_child.py': child})
        self.assertTrue(any('independent runtime evidence' in error for error in errors))

    def test_unknown_script_and_unwrapped_module_children_fail(self):
        for command in ('[sys.executable,str(make_path())]', '[sys.executable,"-m","unittest","test_example"]',
                        '["python","-m","unittest","test_example"]'):
            with self.subTest(command=command):
                self.assertTrue(self.inspect_source('import subprocess,sys\nsubprocess.run(' + command + ')'))

    def test_child_source_binding_does_not_leak_between_test_methods(self):
        source = '''import subprocess,sys
def first():
    code="import tkinter as tk; root=tk.Tk()"
    subprocess.run([sys.executable,"-c",code])
def second():
    code="print('no gui')"
    subprocess.run([sys.executable,"-c",code])
'''
        errors = self.inspect_source(source)
        self.assertTrue(any('GUI child must use' in error for error in errors))

    def test_repository_gui_entries_are_owned(self):
        self.assertEqual(check(ROOT), [])

    def test_preflight_failure_never_starts_unittest(self):
        import run_tests
        with patch('verify_gui_test_coverage.check', return_value=['missing fixture']), \
                patch('unittest.main') as run:
            self.assertEqual(run_tests.main(['test_example']), 1)
        run.assert_not_called()

    def test_runner_refuses_zero_tests(self):
        import run_tests
        with patch('verify_gui_test_coverage.check', return_value=[]), \
                patch('unittest.main', return_value=Mock(result=Mock(testsRun=0))):
            self.assertEqual(run_tests.main(['unused']), 1)


class GuiRuntimeTests(unittest.TestCase):
    def test_retired_interpreter_is_collected_on_runner_main_thread(self):
        result = run_gui_child([sys.executable, str(ROOT / 'scripts' / 'run_tests.py'),
            'fixtures.tk_gc_lifecycle_probe', '-v'], capture_output=True, text=True,
            encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 2 tests', result.stderr)
        self.assertTrue(result.offscreen_report['passed'])
        self.assertEqual(result.offscreen_report['managed_windows'], 1)

    def probe(self, mode, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / 'report.json'
            marker = Path(temporary) / 'native_called.txt'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run_gui_child.py'),
                '--report', str(report), '--', str(ROOT / 'tests' / 'fixtures' / 'gui_guard_probe.py'),
                mode, str(marker)], capture_output=True, text=True, encoding='utf-8', timeout=15, **kwargs)
            evidence = json.loads(report.read_text(encoding='utf-8'))
            self.assertFalse(marker.exists(), result.stdout + result.stderr)
            return result, evidence

    def test_caught_missing_scope_fails_before_native_constructor(self):
        for mode in ('missing', 'subclass', 'thread', 'dialog', 'loadtk', 'leak'):
            with self.subTest(mode=mode):
                result, evidence = self.probe(mode)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(evidence['passed'])
                self.assertTrue(evidence['violations'])
                self.assertEqual(evidence['managed_windows'], 0)

    def test_managed_child_and_tcl_pass(self):
        for mode, count in (('managed', 1), ('tcl', 0)):
            with self.subTest(mode=mode):
                result, evidence = self.probe(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(evidence['passed'])
                self.assertEqual(evidence['managed_windows'], count)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native render isolation')
    def test_forged_private_desktop_request_fails_closed(self):
        result, evidence = self.probe('managed', env=dict(os.environ,
            DUTPILOT_NATIVE_RENDER_DESKTOP='DUTPilot_render_nonexistent'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(evidence['passed'])
        self.assertEqual(evidence['managed_windows'], 0)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native render isolation')
    def test_private_desktop_rejects_active_or_unverifiable_input_state(self):
        import ctypes
        from ctypes import wintypes

        desktop = 'DUTPilot_render_fixture'
        user = Mock()
        kernel = Mock()
        for state, message in ((1, 'not the verified non-input desktop'), (None, 'Cannot verify GUI test desktop input state')):
            def desktop_info(handle, index, buffer, size, needed):
                if index == 2:
                    buffer.value = desktop
                    return True
                self.assertEqual(index, 6)
                if state is None:
                    return False
                ctypes.cast(buffer, ctypes.POINTER(wintypes.BOOL))[0] = state
                ctypes.cast(needed, ctypes.POINTER(wintypes.DWORD))[0] = size
                return True

            user.GetUserObjectInformationW.side_effect = desktop_info
            with self.subTest(state=state), patch.dict(os.environ, DUTPILOT_NATIVE_RENDER_DESKTOP=desktop), \
                 patch('ctypes.WinDLL', side_effect=(user, kernel)), self.assertRaisesRegex(AssertionError, message):
                _private_render_desktop()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native render isolation')
    def test_private_desktop_child_returns_os_verified_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_gui_child([sys.executable, str(ROOT / 'tests' / 'fixtures' / 'gui_guard_probe.py'),
                'managed', str(Path(temporary) / 'unused')], native_render=True,
                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = result.offscreen_report
        self.assertEqual(evidence['isolation'], 'private_desktop')
        self.assertTrue(evidence['desktop'].startswith('DUTPilot_render_'))
        self.assertEqual(evidence['violations'], [])

    def test_child_without_evidence_fails(self):
        with patch('subprocess.run', return_value=Mock(stdout='', stderr='')):
            with self.assertRaisesRegex(AssertionError, 'no offscreen report'):
                run_gui_child([sys.executable, 'unused.py'], timeout=1)

    def test_child_with_failed_or_empty_evidence_fails(self):
        def fake_run(command, **kwargs):
            Path(command[command.index('--report') + 1]).write_text(json.dumps(evidence), encoding='utf-8')
            return Mock(stdout='', stderr='')
        for evidence in (dict(passed=False, managed_windows=1, violations=['missing scope']),
                         dict(passed=True, managed_windows=0, violations=[])):
            with self.subTest(evidence=evidence), patch('subprocess.run', side_effect=fake_run):
                with self.assertRaisesRegex(AssertionError, 'offscreen failure'):
                    run_gui_child([sys.executable, 'unused.py'], timeout=1)


if __name__ == '__main__':
    unittest.main()

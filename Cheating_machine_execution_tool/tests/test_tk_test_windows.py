"""Real-window coverage for the test-only desktop isolation fixture."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
from ctypes import wintypes
import sys
import tkinter as tk
from tkinter import Toplevel  # imported before the fixture patches constructors
import unittest
from unittest.mock import patch

from tk_test_windows import OffscreenTkWindows, install_offscreen_windows


class OffscreenWindowTests(unittest.TestCase):
    def test_mapped_controls_resize_aliases_transient_and_reopen_stay_outside(self):
        with OffscreenTkWindows() as windows:
            root = tk.Tk()
            root.geometry("1000x600+50+50")
            dialog = Toplevel(root)
            dialog.transient(root)
            label = tk.Label(dialog, text="real layout")
            label.pack()
            for geometry in ("820x520", "880x540-10-10", "=900x560+10+20"):
                dialog.wm_geometry(geometry)
                root.update()
                size = geometry.lstrip("=").split("+")[0].split("-")[0]
                self.assertEqual(dialog.geometry().split("+")[0], size)
                self.assertTrue(label.winfo_ismapped())
                self.assertTrue(label.winfo_viewable())
                self.assertGreater(label.winfo_width(), 1)
                windows.assert_offscreen()
            dialog.withdraw()
            dialog.deiconify()
            dialog.lift()
            root.update()
            self.assertTrue(dialog.winfo_viewable())
            self.assertEqual(root.winfo_width(), 1000)
            self.assertEqual(root.winfo_height(), 600)
            self.assertGreater(windows.checked_events, 0)
            dialog.geometry("=")  # Tk accepts this as an empty geometry request.
            windows.assert_offscreen()
            for malformed in ("invalid", "+bad+bad"):
                with self.assertRaises(tk.TclError):
                    dialog.geometry(malformed)
            if sys.platform == "win32":
                # Check the decorated native frame too, not only Tk client coords.
                user32 = ctypes.windll.user32
                user32.GetParent.argtypes = [wintypes.HWND]
                user32.GetParent.restype = wintypes.HWND
                user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                for widget in (root, dialog):
                    frame = user32.GetParent(widget.winfo_id())
                    rect = wintypes.RECT()
                    self.assertTrue(user32.GetWindowRect(frame, ctypes.byref(rect)))
                    left, top, width, height = windows.desktop
                    self.assertTrue(rect.left >= left + width or rect.top >= top + height)

    def test_negative_virtual_desktop_origin_includes_secondary_monitors(self):
        if sys.platform != "win32":
            return  # Windows API branch; other coverage still uses real Tk.
        desktop = (-5000, -1500, 6920, 2580)
        with patch.object(ctypes.windll.user32, "GetSystemMetrics",
                          side_effect=lambda index: dict(zip((76, 77, 78, 79), desktop))[index]):
            with OffscreenTkWindows() as windows:
                root = tk.Tk()
                root.update()
                self.assertEqual(windows.desktop, desktop)
                self.assertGreater(root.winfo_rootx(), desktop[0] + desktop[2])
                self.assertGreater(root.winfo_rooty(), desktop[1] + desktop[3])

    def test_exception_destroys_survivors_restores_hooks_and_tcl_stays_usable(self):
        originals = (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry, tk.Wm.wm_geometry)
        root = dialog = None
        with self.assertRaisesRegex(RuntimeError, "expected failure"):
            with OffscreenTkWindows():
                interpreter = tk.Tcl()
                self.assertEqual(interpreter.eval("expr 6 * 7"), "42")
                root = tk.Tk()
                dialog = Toplevel(root)
                root.update()
                raise RuntimeError("expected failure")
        self.assertFalse(OffscreenTkWindows._exists(root))
        self.assertFalse(OffscreenTkWindows._exists(dialog))
        self.assertEqual(originals, (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry, tk.Wm.wm_geometry))
        # A subsequent context starts cleanly and accepts already-destroyed roots.
        with OffscreenTkWindows():
            next_root = tk.Tk()
            next_root.update_idletasks()
            next_root.destroy()

    def test_callback_violation_fails_cleanup_even_after_window_was_destroyed(self):
        # Intentional failures run in their own guard. A surrounding strict
        # suite must not erase or excuse a recorded violation to make this pass.
        if os.environ.get('DUTPILOT_EXPECTED_GUI_VIOLATION') != '1':
            with tempfile.TemporaryDirectory() as temporary:
                report = Path(temporary) / 'report.json'
                wrapper = Path(__file__).resolve().parents[1] / 'scripts' / 'run_gui_child.py'
                result = subprocess.run([sys.executable, str(wrapper), '--report', str(report), '--',
                    '-m', 'unittest', self.id(), '-v'],
                    env=dict(os.environ, DUTPILOT_EXPECTED_GUI_VIOLATION='1'),
                    capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                evidence = json.loads(report.read_text(encoding='utf-8'))
                self.assertFalse(evidence['passed'])
                self.assertTrue(any('entered the desktop' in v for v in evidence['violations']))
                self.assertIn('OK', result.stderr)
            return
        originals = (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry)
        with self.assertRaisesRegex(AssertionError, "entered the desktop"):
            with OffscreenTkWindows() as windows:
                root = tk.Tk()
                # Simulate a window manager moving the client into the desktop.
                # Only queried coordinates change; the real window stays outside.
                left, top, _width, _height = windows.desktop
                with patch.object(root, "winfo_rootx", return_value=left + 50), patch.object(
                    root, "winfo_rooty", return_value=top + 50
                ):
                    root.update()
                self.assertTrue(windows.violations)
                root.destroy()
        self.assertEqual(originals, (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry))

    def test_nested_scopes_cleanup_only_own_windows_and_preserve_centering(self):
        with OffscreenTkWindows() as outer:
            root = tk.Tk()
            root.geometry('800x600')
            root.update()
            with OffscreenTkWindows() as inner:
                dialog = tk.Toplevel(root)
                x, y = root.winfo_rootx() + 100, root.winfo_rooty() + 100
                dialog.geometry(f'600x400+{x}+{y}')
                root.update()
                self.assertAlmostEqual(dialog.winfo_x() + 300, root.winfo_rootx() + 400, delta=2)
                self.assertEqual(inner.created_windows, 1)
                self.assertEqual(outer.created_windows, 1)
            self.assertFalse(OffscreenTkWindows._exists(dialog))
            self.assertTrue(OffscreenTkWindows._exists(root))
            root.geometry('900x650')
            root.update()
            outer.assert_offscreen()

    def test_repeated_installation_reuses_scope_and_cleanup(self):
        case = unittest.TestCase()
        first = install_offscreen_windows(case)
        try:
            self.assertIs(first, install_offscreen_windows(case))
            root = tk.Tk()
        finally:
            case.doCleanups()
        self.assertFalse(OffscreenTkWindows._exists(root))

    def test_failed_setup_runs_registered_cleanup(self):
        originals = (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry)
        survivors = []

        class FailedSetup(unittest.TestCase):
            def setUp(self):
                install_offscreen_windows(self)
                survivors.append(tk.Tk())
                raise RuntimeError("setup failure")

            def runTest(self):
                raise AssertionError("setUp must fail first")

        result = unittest.TestResult()
        FailedSetup().run(result)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("setup failure", result.errors[0][1])
        self.assertFalse(OffscreenTkWindows._exists(survivors[0]))
        self.assertEqual(originals, (tk.Tk.__init__, tk.Toplevel.__init__, tk.Wm.geometry))


if __name__ == "__main__":
    unittest.main()

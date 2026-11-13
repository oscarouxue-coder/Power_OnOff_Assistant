"""Real-window coverage for the test-only desktop isolation fixture."""
import ctypes
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

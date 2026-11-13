"""Keep real test windows mapped outside the desktop; never imported by the app.

Use install_offscreen_windows(self) before constructing Tk in a unittest, or
``with OffscreenTkWindows():`` in an isolated UI simulation. These process-local
patches are for sequential UI-thread tests, including already imported classes.
"""
from contextlib import ExitStack
import ctypes
import re
import sys
import tkinter as tk
from unittest.mock import patch
import weakref


class OffscreenTkWindows:
    def __init__(self):
        self._windows = weakref.WeakSet()
        self._hooks = None
        self.desktop = None
        self.violations = []
        self.checked_events = 0
        self.created_windows = 0

    def __enter__(self):
        if self._hooks is not None:
            raise RuntimeError("OffscreenTkWindows is already active")
        self._hooks = ExitStack()
        original_geometry = tk.Wm.wm_geometry
        original_root_init = tk.Tk.__init__
        original_top_init = tk.Toplevel.__init__

        def geometry(window, newGeometry=None):
            if window not in self._windows or newGeometry is None:
                return original_geometry(window, newGeometry)
            value = str(newGeometry)
            match = re.fullmatch(r"=?(?:(\d+x\d+))?(?:[+-]\d+[+-]\d+)?", value)
            if match is None or value == "=":
                # Preserve Tk's validation/error for malformed geometry.
                return original_geometry(window, newGeometry)
            if value == "":
                original_geometry(window, "")  # reset to natural requested size
            size = match.group(1) or ""
            return original_geometry(window, size + self._position())

        def root_init(window, *args, **kwargs):
            original_root_init(window, *args, **kwargs)
            if window._tkloaded:  # tkinter.Tcl()/Tk(useTk=False) stays untouched
                self._manage(window, original_geometry)

        def top_init(window, *args, **kwargs):
            original_top_init(window, *args, **kwargs)
            self._manage(window, original_geometry)

        try:
            for owner, name, replacement in (
                (tk.Tk, "__init__", root_init),
                (tk.Toplevel, "__init__", top_init),
                (tk.Wm, "wm_geometry", geometry),
                (tk.Wm, "geometry", geometry),
            ):
                self._hooks.enter_context(patch.object(owner, name, replacement))
        except BaseException:
            self._hooks.close()
            self._hooks = None
            raise
        return self

    def _position(self):
        left, top, width, height = self.desktop
        return f"+{left + width + 4096}+{top + height + 4096}"

    def _manage(self, window, original_geometry):
        if self.desktop is None:
            if sys.platform == "win32":
                # Virtual screen is the bounding rectangle of ALL monitors,
                # including monitors left of or above the primary display.
                user32 = ctypes.windll.user32
                self.desktop = tuple(user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
            else:
                self.desktop = (window.winfo_vrootx(), window.winfo_vrooty(),
                                window.winfo_vrootwidth(), window.winfo_vrootheight())
            if self.desktop[2] <= 0 or self.desktop[3] <= 0:
                raise RuntimeError("Cannot determine the virtual desktop")
        self._windows.add(window)
        self.created_windows += 1
        # Before the first update/map: no visible on-screen placement first.
        original_geometry(window, self._position())
        reference = weakref.ref(window)

        def check(event):
            target = reference()
            if target is not None and event.widget is target:
                self._check_window(target)

        window.bind("<Map>", check, add="+")
        window.bind("<Configure>", check, add="+")

    def _check_window(self, window):
        if not self._exists(window) or not window.winfo_ismapped():
            return
        self.checked_events += 1
        left, top, width, height = self.desktop
        x, y = window.winfo_rootx(), window.winfo_rooty()
        if (x < left + width and x + window.winfo_width() > left
                and y < top + height and y + window.winfo_height() > top):
            # Tk reports callback exceptions without failing unittest. Defer the
            # assertion to normal test/cleanup code, even if this window closes.
            self.violations.append((str(window), window.wm_geometry()))

    @staticmethod
    def _exists(window):
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            # Tk's interpreter no longer accepts winfo after root.destroy().
            return False

    def assert_offscreen(self):
        for window in list(self._windows):
            self._check_window(window)
        if self.violations:
            raise AssertionError(f"Test windows entered the desktop: {self.violations}")

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            # Finish toolkit idle/theme notifications before destroying a root,
            # including a root whose test failed before its first update().
            for window in list(self._windows):
                if isinstance(window, tk.Tk) and self._exists(window):
                    window.update_idletasks()
            if exc_type is None:
                self.assert_offscreen()
        finally:
            try:
                # Weak references avoid retaining retired window/controller
                # graphs during lifecycle/GC tests. Destroy survivors on failure.
                windows = sorted(self._windows, key=lambda w: isinstance(w, tk.Tk))
                for window in windows:
                    if self._exists(window):
                        window.destroy()
            finally:
                self._windows.clear()
                self._hooks.close()
                self._hooks = None
        return False


def install_offscreen_windows(test_case):
    """Register cleanup immediately, including when a later setUp step fails."""
    windows = OffscreenTkWindows().__enter__()
    test_case.addCleanup(windows.__exit__, None, None, None)
    return windows

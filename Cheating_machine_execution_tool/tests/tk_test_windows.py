"""Keep real test windows mapped outside the desktop; never imported by the app.

Use install_offscreen_windows(self) before constructing Tk in a unittest, or
``with OffscreenTkWindows():`` in an isolated UI simulation. These process-local
patches are for sequential UI-thread tests, including already imported classes.
"""
from contextlib import ExitStack, contextmanager
import ctypes
import os
import re
import sys
import threading
import traceback
import tkinter as tk
from unittest.mock import patch
import weakref


from scripts.gui_test_process import _private_render_desktop, run_gui_child


class _WindowRuntime:
    """One set of patches; each window belongs to its innermost scope."""
    scopes = []
    guards = []
    hooks = None
    owners = weakref.WeakKeyDictionary()

    @classmethod
    def violation(cls, message):
        caller = next((f for f in reversed(traceback.extract_stack()[:-1])
                       if f.filename != __file__), None)
        if caller:
            message = f'{caller.filename}:{caller.lineno}: {message}'
        for guard in cls.guards:
            guard.violations.append(f'{guard.test_id}: {message}' if guard.test_id else message)
        return AssertionError(message)

    @classmethod
    def scope(cls):
        if threading.current_thread() is not threading.main_thread():
            raise cls.violation("GUI test created a window outside the Tk main thread")
        if not cls.scopes:
            raise cls.violation("GUI test missing OffscreenTkWindows / install_offscreen_windows before window creation")
        return cls.scopes[-1]

    @classmethod
    def acquire(cls):
        if cls.hooks is not None:
            return
        cls.hooks = ExitStack()
        original_root = tk.Tk.__init__
        original_top = tk.Toplevel.__init__
        original_geometry = tk.Wm.wm_geometry
        original_loadtk = tk.Tk.loadtk

        def root_init(window, *args, **kwargs):
            use_tk = kwargs.get('useTk', args[3] if len(args) > 3 else True)
            owner = cls.scope() if use_tk else None
            original_root(window, *args, **kwargs)
            if owner is not None:
                owner._manage(window, original_geometry)

        def top_init(window, *args, **kwargs):
            owner = cls.scope()
            original_top(window, *args, **kwargs)
            owner._manage(window, original_geometry)

        def loadtk(window):
            owner = cls.scope()
            original_loadtk(window)
            if window not in cls.owners:
                owner._manage(window, original_geometry)

        def geometry(window, newGeometry=None):
            owner = cls.owners.get(window)
            if owner is None or newGeometry is None:
                return original_geometry(window, newGeometry)
            if owner.private_desktop:
                return original_geometry(window, newGeometry)
            value = str(newGeometry)
            match = re.fullmatch(r"=?(?:(\d+x\d+))?((?:[+-]\d+[+-]\d+)?)", value)
            if match is None or value == '=':
                return original_geometry(window, newGeometry)
            if value == '':
                original_geometry(window, '')
            position = match.group(2)
            if not position:
                current = original_geometry(window)
                position = re.search(r'([+-]\d+[+-]\d+)$', current).group(1)
            coordinates = re.fullmatch(r'\+(\d+)\+(\d+)', position)
            left, top, width, height = owner.desktop
            if not coordinates or not (int(coordinates[1]) >= left + width + 32
                                       or int(coordinates[2]) >= top + height + 32):
                position = owner._position()
            return original_geometry(window, (match.group(1) or '') + position)

        # Native OS dialogs are not Tk Toplevel instances and cannot be managed
        # by geometry hooks. Tests must mock their answers explicitly.
        def native_dialog(dialog, **options):
            raise cls.violation("Unadapted native GUI dialog in test; mock the dialog response")

        from tkinter.commondialog import Dialog
        try:
            for owner, name, replacement in (
                (tk.Tk, '__init__', root_init), (tk.Toplevel, '__init__', top_init),
                (tk.Tk, 'loadtk', loadtk), (tk.Wm, 'geometry', geometry),
                (tk.Wm, 'wm_geometry', geometry),
            ):
                cls.hooks.enter_context(patch.object(owner, name, replacement))
            if cls.guards:
                cls.hooks.enter_context(patch.object(Dialog, 'show', native_dialog))
        except BaseException:
            cls.hooks.close()
            cls.hooks = None
            raise

    @classmethod
    def release(cls):
        if not cls.scopes and not cls.guards and cls.hooks is not None:
            cls.hooks.close()
            cls.hooks = None


class StrictTkGuard:
    """Fail before an unmanaged native constructor, even if the test catches it."""
    def __init__(self):
        self.violations = []
        self.created_windows = 0
        self.test_id = ''
        self.private_desktop = None

    def __enter__(self):
        self.private_desktop = _private_render_desktop()
        self._initial_scopes = list(_WindowRuntime.scopes)
        _WindowRuntime.guards.append(self)
        try:
            _WindowRuntime.acquire()
        except BaseException:
            _WindowRuntime.guards.remove(self)
            raise
        return self

    def report(self):
        return dict(passed=not self.violations, managed_windows=self.created_windows,
                    violations=list(self.violations), isolation='private_desktop' if self.private_desktop else 'offscreen',
                    desktop=self.private_desktop)

    def assert_clean(self):
        if self.violations:
            raise AssertionError('; '.join(self.violations))

    def finish_test(self):
        # An unclosed scope must not authorize the following test. Always make
        # this a failure, even if destroying its windows happens to succeed.
        leaked = [s for s in _WindowRuntime.scopes if s not in self._initial_scopes]
        if leaked:
            _WindowRuntime.violation('GUI test leaked an offscreen scope; register cleanup immediately')
            for scope in reversed(leaked):
                try:
                    scope.__exit__(None, None, None)
                except BaseException as exc:
                    _WindowRuntime.violation(f'GUI cleanup failed: {exc}')

    def __exit__(self, *exc):
        try:
            if self.private_desktop:
                try:
                    _private_render_desktop()
                except AssertionError as error:
                    _WindowRuntime.violation(str(error))
            self.finish_test()
        finally:
            _WindowRuntime.guards.remove(self)
            _WindowRuntime.release()
        return False


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
        self.private_desktop = _private_render_desktop()
        self._hooks = True
        _WindowRuntime.scopes.append(self)
        try:
            _WindowRuntime.acquire()
        except BaseException:
            _WindowRuntime.scopes.remove(self)
            self._hooks = None
            raise
        return self

    def _position(self):
        if self.private_desktop:
            return '+32+32'
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
        _WindowRuntime.owners[window] = self
        self.created_windows += 1
        for guard in _WindowRuntime.guards:
            guard.created_windows += 1
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
        if self.private_desktop:
            try:
                _private_render_desktop()
            except AssertionError as error:
                self.violations.append((str(window), str(error)))
                _WindowRuntime.violation(str(error))
            return
        left, top, width, height = self.desktop
        x, y = window.winfo_rootx(), window.winfo_rooty()
        if (x < left + width and x + window.winfo_width() > left
                and y < top + height and y + window.winfo_height() > top):
            # Tk reports callback exceptions without failing unittest. Defer the
            # assertion to normal test/cleanup code, even if this window closes.
            self.violations.append((str(window), window.wm_geometry()))
            _WindowRuntime.violation(f"Test windows entered the desktop: {self.violations[-1]}")

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
                _WindowRuntime.scopes.remove(self)
                _WindowRuntime.release()
                self._hooks = None
        return False


def install_offscreen_windows(test_case):
    """Register cleanup immediately, including when a later setUp step fails."""
    existing = getattr(test_case, '_offscreen_test_windows', None)
    if existing is not None and existing._hooks is not None:
        return existing
    windows = OffscreenTkWindows().__enter__()
    test_case._offscreen_test_windows = windows
    test_case.addCleanup(windows.__exit__, None, None, None)
    return windows


def requires_offscreen(function):
    """Declare and enforce ownership for a shared GUI test helper."""
    from functools import wraps
    @wraps(function)
    def checked(*args, **kwargs):
        _WindowRuntime.scope()
        return function(*args, **kwargs)
    return checked

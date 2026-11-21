"""Test-only Qt ownership on an OS-verified non-input Windows desktop.

Imported by the GUI child wrapper, never by the product. No offscreen QPA
fallback: tests exercise the Windows platform plugin and real mapped widgets.
"""
from contextlib import ExitStack
import threading
import weakref
from unittest.mock import patch


_active = None


class QtRuntimeGuard:
    def __init__(self):
        self.scopes = []
        self.violations = []
        self.created_windows = 0
        self.windows = weakref.WeakSet()
        self.application = None
        self.hooks = ExitStack()

    def reject(self, message):
        self.violations.append(message)
        raise AssertionError(message)

    def require_scope(self):
        if threading.current_thread() is not threading.main_thread():
            self.reject('Qt widgets must be created and shown on the GUI main thread')
        if not self.scopes:
            self.reject('Qt GUI test missing QtTestScope before widget creation/show')
        return self.scopes[-1]

    def own(self, widget, shown=False):
        self.require_scope().objects.add(widget)
        if shown and widget.isWindow() and widget not in self.windows:
            self.windows.add(widget)
            self.require_scope().windows.add(widget)
            self.created_windows += 1

    def __enter__(self):
        global _active
        from tk_test_windows import _private_render_desktop
        self.desktop = _private_render_desktop()
        if not self.desktop:
            self.reject('Qt native tests require the verified private desktop wrapper')
        from PySide6 import QtCore, QtWidgets
        import shiboken6
        if _active is not None or QtWidgets.QApplication.instance() is not None:
            self.reject('Qt guard must be installed before QApplication')
        self.QtCore, self.QtWidgets, self.shiboken = QtCore, QtWidgets, shiboken6
        _active = self
        try:
            def constructor(original):
                def initialize(widget, *args, **kwargs):
                    self.require_scope()
                    original(widget, *args, **kwargs)
                    if isinstance(widget, QtWidgets.QWidget):
                        self.own(widget)
                return initialize
            # PySide lazily populates its module dictionary. Force all exported
            # Qt widget types to load before taking constructor snapshots.
            values = [getattr(QtWidgets, name) for name in dir(QtWidgets) if name.startswith('Q')]
            types = {value for value in values if isinstance(value, type)
                     and (issubclass(value, QtWidgets.QWidget) or value is QtWidgets.QApplication)}
            originals = {cls: cls.__init__ for cls in types}
            for cls, original in originals.items():
                self.hooks.enter_context(patch.object(cls, '__init__', constructor(original)))
            def checked_call(original):
                def invoke(widget, *args, **kwargs):
                    self.require_scope()
                    return original(widget, *args, **kwargs)
                return invoke
            for name in ('show', 'showMaximized', 'showNormal', 'setVisible'):
                self.hooks.enter_context(patch.object(QtWidgets.QWidget, name, checked_call(getattr(QtWidgets.QWidget, name))))
            def native_dialog(*args, **kwargs):
                self.reject('Unadapted native Qt dialog; mock the answer in GUI tests')
            for name in ('getOpenFileName', 'getOpenFileNames', 'getSaveFileName', 'getExistingDirectory', 'exec'):
                self.hooks.enter_context(patch.object(QtWidgets.QFileDialog, name, native_dialog))
            for name in ('information', 'warning', 'critical', 'question', 'about', 'exec'):
                self.hooks.enter_context(patch.object(QtWidgets.QMessageBox, name, native_dialog))
            for name in ('getText', 'getMultiLineText', 'getInt', 'getDouble', 'getItem'):
                self.hooks.enter_context(patch.object(QtWidgets.QInputDialog, name, native_dialog))
            runtime = self
            class OwnershipFilter(QtCore.QObject):
                def eventFilter(self, watched, event):
                    if isinstance(watched, QtWidgets.QWidget) and event.type() == QtCore.QEvent.Type.Show:
                        try:
                            runtime.require_scope()
                            runtime.own(watched, shown=True)
                        except AssertionError:
                            watched.hide()
                            return True
                    return False
            self.filter_type = OwnershipFilter
            return self
        except BaseException:
            self.hooks.close()
            _active = None
            raise

    def report(self):
        return dict(passed=not self.violations, managed_windows=self.created_windows,
                    violations=list(self.violations), isolation='private_desktop',
                    desktop=self.desktop, framework='qt', platform=getattr(self, 'platform', None))

    def __exit__(self, *exc):
        global _active
        try:
            if self.scopes:
                self.violations.append('Qt GUI test leaked an ownership scope')
                for scope in reversed(tuple(self.scopes)):
                    scope.__exit__(None, None, None)
            if self.application is not None:
                self.application.removeEventFilter(self.filter)
                self.shiboken.delete(self.filter)
                self.shiboken.delete(self.application)
                self.application = None
        finally:
            self.hooks.close()
            _active = None


class QtTestScope:
    """Create QApplication once; dispose this scope's top-levels before returning."""
    def __init__(self):
        self.windows = weakref.WeakSet()
        self.objects = weakref.WeakSet()

    def __enter__(self):
        if _active is None:
            raise AssertionError('Launch Qt tests with run_gui_child(framework="qt", native_render=True)')
        self.runtime = _active
        self.runtime.scopes.append(self)
        try:
            widgets = self.runtime.QtWidgets
            if self.runtime.application is None:
                self.runtime.application = widgets.QApplication(['DUTPilot Qt native tests'])
                self.runtime.application.setQuitOnLastWindowClosed(False)
                self.runtime.platform = self.runtime.application.platformName()
                if self.runtime.platform != 'windows':
                    self.runtime.reject('Qt tests must use the native Windows QPA plugin')
                self.runtime.filter = self.runtime.filter_type(self.runtime.application)
                self.runtime.application.installEventFilter(self.runtime.filter)
            self.app = self.runtime.application
            return self
        except BaseException:
            self.runtime.scopes.remove(self)
            raise

    def __exit__(self, *exc):
        try:
            for window in tuple(self.objects):
                if self.runtime.shiboken.isValid(window) and window.isWindow():
                    window.close()
                    window.deleteLater()
            self.runtime.QtCore.QCoreApplication.sendPostedEvents(None, self.runtime.QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            for window in tuple(self.windows):
                if self.runtime.shiboken.isValid(window):
                    self.runtime.violations.append('Qt test window survived deferred disposal')
                    self.runtime.shiboken.delete(window)
        finally:
            self.windows.clear()
            self.objects.clear()
            self.runtime.scopes.remove(self)


def install_qt_test_scope(test_case):
    scope = QtTestScope().__enter__()
    test_case.addCleanup(scope.__exit__, None, None, None)
    return scope

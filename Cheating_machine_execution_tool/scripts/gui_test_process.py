"""Test-only Windows desktop identity and GUI child evidence."""
from contextlib import ExitStack, contextmanager
import ctypes
import os
import sys


def _private_render_desktop():
    """Verify OS desktop identity, never trusting an environment flag alone."""
    expected = os.environ.get('DUTPILOT_NATIVE_RENDER_DESKTOP')
    if not expected:
        return None
    if sys.platform != 'win32' or not expected.startswith('DUTPilot_render_'):
        raise AssertionError('Invalid private GUI rendering desktop request')
    from ctypes import wintypes as w
    user, kernel = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32')
    kernel.GetCurrentThreadId.restype = w.DWORD
    user.GetThreadDesktop.argtypes, user.GetThreadDesktop.restype = [w.DWORD], w.HANDLE
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    handle = user.GetThreadDesktop(kernel.GetCurrentThreadId())
    name = ctypes.create_unicode_buffer(512)
    needed = w.DWORD()
    UOI_NAME, UOI_IO = 2, 6
    if not handle or not user.GetUserObjectInformationW(handle, UOI_NAME, name, ctypes.sizeof(name), ctypes.byref(needed)):
        raise AssertionError('Cannot verify GUI test desktop identity')
    if name.value.casefold() != expected.casefold():
        raise AssertionError('GUI rendering desktop is not the verified non-input desktop')
    # Ask Windows whether this desktop receives input. The desktop receiving
    # input may have an ACL that prevents opening it from this test process.
    receives_input = w.BOOL(-1)
    if (not user.GetUserObjectInformationW(handle, UOI_IO, ctypes.byref(receives_input),
            ctypes.sizeof(receives_input), ctypes.byref(needed)) or needed.value != ctypes.sizeof(receives_input)):
        raise AssertionError('Cannot verify GUI test desktop input state')
    if receives_input.value != 0:
        raise AssertionError('GUI rendering desktop is not the verified non-input desktop')
    return name.value


@contextmanager
def _render_desktop():
    """Own a disposable desktop for the native-pixel child; never SwitchDesktop."""
    from ctypes import wintypes as w
    import uuid
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.CreateDesktopW.argtypes = [w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
    user.CreateDesktopW.restype = w.HANDLE
    user.CloseDesktop.argtypes = [w.HANDLE]
    desktop_name = 'DUTPilot_render_' + uuid.uuid4().hex
    handle = user.CreateDesktopW(desktop_name, None, None, 0, 0x1ff, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield desktop_name
    finally:
        if not user.CloseDesktop(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def run_gui_child(command, native_render=False, framework='tk', **kwargs):
    """A timed Python child must return independent, fail-closed GUI evidence."""
    import json
    from pathlib import Path
    import subprocess
    import tempfile
    if 'timeout' not in kwargs:
        raise ValueError('GUI child requires a timeout')
    if framework not in ('tk', 'qt') or (framework == 'qt' and not native_render):
        raise ValueError('Qt tests require the native private desktop adapter')
    wrapper = Path(__file__).resolve().with_name('run_gui_child.py')
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as resources:
        report = Path(temporary) / 'offscreen.json'
        if native_render:
            if sys.platform != 'win32' or 'startupinfo' in kwargs:
                raise ValueError('Native rendering requires a managed Windows desktop')
            desktop = resources.enter_context(_render_desktop())
            # CPython subprocess does not forward an arbitrary lpDesktop
            # attribute. The wrapper binds its fresh thread before importing Tk.
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            kwargs['env'] = dict(kwargs.get('env', os.environ), DUTPILOT_NATIVE_RENDER_DESKTOP=desktop)
        result = subprocess.run([command[0], str(wrapper), '--report', str(report), '--framework', framework, '--',
                                 *map(str, command[1:])], **kwargs)
        if not report.is_file():
            raise AssertionError(f'GUI child returned no offscreen report: {result.stdout} {result.stderr}')
        evidence = json.loads(report.read_text(encoding='utf-8'))
        if not evidence['passed'] or evidence['managed_windows'] < 1:
            raise AssertionError(f'GUI child offscreen failure: {evidence}\n{result.stdout}\n{result.stderr}')
        if native_render and (evidence.get('isolation') != 'private_desktop' or evidence.get('desktop') != desktop):
            raise AssertionError(f'GUI child did not verify its private desktop: {evidence}')
        result.offscreen_report = evidence
        return result

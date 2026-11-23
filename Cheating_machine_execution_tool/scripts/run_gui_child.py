"""Execute an isolated GUI test child and always return independent evidence."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import traceback


def bind_render_desktop():
    expected = os.environ.get('DUTPILOT_NATIVE_RENDER_DESKTOP')
    if not expected:
        return
    import ctypes
    from ctypes import wintypes as w
    if sys.platform != 'win32' or not expected.startswith('DUTPilot_render_'):
        raise AssertionError('Invalid private rendering desktop request')
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.OpenDesktopW.argtypes, user.OpenDesktopW.restype = [w.LPCWSTR, w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    user.SetThreadDesktop.argtypes, user.SetThreadDesktop.restype = [w.HANDLE], w.BOOL
    handle = user.OpenDesktopW(expected, 0, False, 0x1ff)
    if not handle or not user.SetThreadDesktop(handle):
        raise ctypes.WinError(ctypes.get_last_error())
    # This short-lived process owns the assigned handle until process exit.
    # SetThreadDesktop assigns this thread; it never switches the input desktop.


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--framework', choices=('tk', 'qt'), default='tk')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    while command[:1] in (['-X'], ['-W']):
        command = command[2:]
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'tests'), str(root)]
    guard = None
    status = 0
    try:
        bind_render_desktop()  # Before importing either framework or application code.
        if args.framework == 'qt':
            from qt_test_guard import QtRuntimeGuard
            guard = QtRuntimeGuard()
        else:
            from tk_test_windows import StrictTkGuard
            guard = StrictTkGuard()
        with guard:
            if command[:1] == ['-c']:
                sys.argv = ['-c', *command[2:]]
                exec(compile(command[1], '<gui-test-child>', 'exec'), {'__name__': '__main__'})
            elif command[:1] == ['-m']:
                sys.argv = [command[1], *command[2:]]
                runpy.run_module(command[1], run_name='__main__', alter_sys=True)
            else:
                sys.argv = command
                runpy.run_path(command[0], run_name='__main__')
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        traceback.print_exc()
        status = 1
    evidence = guard.report() if guard is not None else dict(
        passed=False, managed_windows=0, violations=['GUI child bootstrap failed'], isolation='unverified', desktop=None)
    if args.framework == 'qt' and evidence.get('framework') == 'qt':
        evidence['qt'] = dict(evidence)
    evidence['passed'] = evidence['passed'] and status == 0
    Path(args.report).write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
    return status or (0 if evidence['passed'] else 1)


if __name__ == '__main__':
    sys.exit(main())

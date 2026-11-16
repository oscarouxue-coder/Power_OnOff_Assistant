"""Run only repair-related regression, offscreen and without device/platform I/O."""
import asyncio
import builtins
from contextlib import ExitStack
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Cheating_machine_execution_tool'
os.chdir(SOURCE)
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]
temp = str(Path(tempfile.gettempdir()).resolve())
for key in ('TMPDIR', 'TEMP', 'TMP'):
    os.environ[key] = temp
tempfile.tempdir = temp
if importlib.util.find_spec('lark_oapi') is None:
    raise SystemExit('Real SDK is required; skipped SDK checks are not accepted.')

from tk_test_windows import OffscreenTkWindows

MODULES = (
    'test_feishu_dependency_repair', 'test_feishu_remote', 'test_feishu_stream',
    'test_dingtalk_remote', 'test_ai_remote_management', 'test_ai_conversation',
    'test_ai_core', 'test_ai_monitor_permissions', 'test_ai_session_router',
    'test_capabilities', 'test_capability_coverage', 'test_capability_application',
    'test_app', 'test_pipeline_window', 'test_test_item_pretest',
)


class Tee:
    def __init__(self, file):
        self.file = file

    def write(self, value):
        sys.stdout.write(value)
        self.file.write(value)

    def flush(self):
        sys.stdout.flush()
        self.file.flush()


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    repair_only = '--repair-only' in sys.argv[1:]
    modules = ('test_feishu_dependency_repair',) if repair_only else MODULES
    log = Path(__file__).with_name('repair_final.txt' if repair_only else 'focused.txt')
    config_root = (SOURCE / 'Auto_power_on_off_tool/config').resolve()
    original_open, original_io_open, original_replace = builtins.open, io.open, os.replace
    def protected(path):
        if isinstance(path, (str, bytes, os.PathLike)):
            candidate = Path(os.fsdecode(path)).resolve()
            return candidate == config_root or config_root in candidate.parents
        return False
    def guarded_open(original):
        def call(path, mode='r', *args, **kwargs):
            if any(c in mode for c in 'wax+') and protected(path):
                raise AssertionError('Regression must not write the operator configuration: ' + str(path))
            return original(path, mode, *args, **kwargs)
        return call
    def guarded_replace(source, destination, *args, **kwargs):
        if protected(destination):
            raise AssertionError('Regression must not replace the operator configuration: ' + str(destination))
        return original_replace(source, destination, *args, **kwargs)
    with log.open('w', encoding='utf-8') as file, OffscreenTkWindows() as windows, ExitStack() as stack:
        stack.enter_context(patch('builtins.open', guarded_open(original_open)))
        stack.enter_context(patch('io.open', guarded_open(original_io_open)))
        stack.enter_context(patch('os.replace', guarded_replace))
        stream = Tee(file)
        stream.write('Interpreter: ' + sys.executable + '\nModules: ' + ', '.join(modules) + '\n')
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        windows.assert_offscreen()
        sdk_skipped = [t.id() for t, reason in result.skipped if t.id().startswith('test_feishu_stream.')]
        if sdk_skipped:
            raise SystemExit('Real SDK checks were skipped: ' + repr(sdk_skipped))
        stream.write('OPERATOR_CONFIGURATION_WRITE_GUARD_ACTIVE\n')
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())

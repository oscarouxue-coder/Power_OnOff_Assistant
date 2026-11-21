"""Supported unittest entry: preflight before imports, strict GUI runtime guard."""
from pathlib import Path
import gc
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    from verify_gui_test_coverage import check
    errors = check(ROOT)
    if errors:
        print('GUI_TEST_COVERAGE_FAILED\n' + '\n'.join(errors), file=sys.stderr)
        return 1
    print('GUI_TEST_COVERAGE_OK', flush=True)
    sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    # Normalize Windows short temp paths for existing parent/child comparisons.
    temporary = str(Path(tempfile.gettempdir()).resolve())
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        os.environ[name] = temporary
    tempfile.tempdir = temporary
    from tk_test_windows import StrictTkGuard
    with StrictTkGuard() as guard:
        class GuardedResult(unittest.TextTestResult):
            def startTest(self, test):
                # unittest removes the previous case only after stopTest.
                # Reclaim its destroyed Tk/Variable cycles here on the main
                # thread, before this test can start a worker that triggers GC.
                gc.collect()
                guard.test_id = test.id()
                super().startTest(test)

            def stopTest(self, test):
                guard.finish_test()
                super().stopTest(test)
                guard.test_id = ''

        class GuardedRunner(unittest.TextTestRunner):
            resultclass = GuardedResult

        program = unittest.main(module=None, argv=[sys.argv[0], *(sys.argv[1:] if argv is None else argv)],
                                testRunner=GuardedRunner, exit=False)
        gc.collect()
        guard.finish_test()
    report = guard.report()
    print(f"GUI_RUNTIME_REPORT: {report}", flush=True)
    if not program.result.testsRun:
        print('No tests executed; refusing an empty successful run', file=sys.stderr)
    return 0 if program.result.testsRun and program.result.wasSuccessful() and report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())

"""Run final native/full/source checks sequentially and retain UTF-8 evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    directory = Path(__file__).resolve().parent
    root = directory.parents[1]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    checks = (
        ('native', ['scripts/verify_qt_migration.py', '--output',
            'validation/pyside6_migration_20261118/qt_dut_telnet_final']),
        ('baseline', ['scripts/verify_baseline.py']),
        ('source', ['validation/pyside6_migration_20261118/verify_dut_telnet.py']),
    )
    results = []
    for name, arguments in checks:
        print('START', name, flush=True)
        started = time.monotonic()
        result = subprocess.run([sys.executable, *arguments], cwd=str(root), env=env,
            capture_output=True, text=True, encoding='utf-8', timeout=1800)
        path = directory / ('dut_telnet_' + name + '.txt')
        path.write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        results.append(dict(name=name, passed=result.returncode == 0, exit_code=result.returncode,
            seconds=round(time.monotonic() - started, 3), output=path.name))
        (directory / 'dut_telnet_delivery_checks.json').write_text(
            json.dumps(results, indent=2) + '\n', encoding='utf-8')
        print('FINISH', name, result.returncode, flush=True)
        if result.returncode:
            print((result.stdout + '\n' + result.stderr)[-5000:], flush=True)
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

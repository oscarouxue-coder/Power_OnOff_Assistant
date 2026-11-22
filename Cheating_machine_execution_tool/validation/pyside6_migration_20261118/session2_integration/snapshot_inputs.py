"""Fingerprint the local candidate inputs and locked toolchain, independently of Git."""
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
TREES = ('assets', 'Auto_power_on_off_tool', 'line_check_assistant', 'Page_upgrade',
         'SdmcUbusLib', 'scripts', 'src', 'tests', 'ZteTitanOnuProvisioner')
EXCLUDED = {'__pycache__', 'script_logs', 'test_results', '.pytest_cache'}
ROOT_INPUTS = ('build_line_check_assistant.ps1', 'line_check_assistant_README.md',
               'requirements-build.txt', 'requirements-qt.txt', 'requirements.txt',
               'run_dutpilot_qt.py', 'run_line_check_assistant.py', 'THIRD_PARTY_NOTICES.md')


def inventory(root):
    paths = [root / name for name in ROOT_INPUTS]
    for directory in TREES:
        paths.extend(path for path in (root / directory).rglob('*')
                     if path.is_file() and not EXCLUDED.intersection(path.parts)
                     and path.suffix != '.pyc')
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


if __name__ == '__main__':
    files = inventory(ROOT)
    fingerprint = sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    print(json.dumps(dict(sha256=fingerprint, count=len(files), python=sys.version,
                          interpreter=sys.executable,
                          packages={p: version(p) for p in ('PySide6-Essentials', 'shiboken6', 'PyInstaller')},
                          files=files), ensure_ascii=False, indent=2))

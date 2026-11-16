"""Real missing-SDK repair ONLY in the disposable, repository-external test venv."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2] / 'Cheating_machine_execution_tool'
sys.path.insert(0, str(ROOT))

from src.core.feishu_dependency_install import install_feishu, run_checked


def main():
    expected = Path(os.environ['LOCALAPPDATA']) / 'LineCheckAssistant/feishu-repair-validation-py39'
    if Path(sys.prefix).resolve() != expected.resolve() or sys.prefix == sys.base_prefix:
        raise SystemExit('Refusing to change any environment other than the dedicated repair-validation venv.')
    with Path(__file__).with_name('real_install.txt').open('w', encoding='utf-8') as file:
        def emit(message):
            print(message, flush=True)
            file.write(message + '\n')
            file.flush()
        emit('Validation environment: ' + sys.prefix)
        run_checked([sys.executable, '-I', '-X', 'utf8', '-m', 'pip', 'uninstall', '-y', 'lark-oapi'],
                    '仅在专用测试环境模拟缺包', emit)
        if importlib.util.find_spec('lark_oapi') is not None:
            raise RuntimeError('SDK must be absent before exercising real repair')
        emit('SDK_MISSING_BEFORE_REPAIR')
        install_feishu(ROOT, emit)
        emit('REAL_FEISHU_REPAIR_OK; no application was restarted')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

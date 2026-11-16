"""Focused compile/inventory/coverage checks; does not run the full baseline."""
import importlib.util
import json
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Cheating_machine_execution_tool'
FILES = (
    'src/models/dependency_repair.py', 'src/core/feishu_dependency_install.py',
    'src/core/source_restart.py', 'src/core/feishu_stream.py',
    'src/services/feishu_dependency_repair.py', 'src/services/ai_diagnostic_service.py',
    'src/services/ai_conversation_service.py', 'src/services/ai_session_router.py',
    'src/services/capability_service.py', 'src/services/capability_catalog.py',
    'src/ui/feishu_dependency_dialog.py', 'src/ui/feishu_dependency_controller.py',
    'src/ui/feishu_setup_window.py', 'src/ui/ai_assistant_controller.py',
    'src/ui/capability_ui_bridge.py', 'line_check_assistant/app.py',
    'scripts/restart_source_after_exit.py', 'scripts/verify_baseline.py',
    'scripts/source_environment_guard.py', 'run_line_check_assistant.py',
    'tests/test_feishu_dependency_repair.py',
)


def main():
    with tempfile.TemporaryDirectory(prefix='repair-compile-') as directory:
        for index, name in enumerate(FILES):
            py_compile.compile(str(SOURCE / name), cfile=str(Path(directory) / f'{index}.pyc'), doraise=True)
    spec = importlib.util.spec_from_file_location('repair_inventory_check', SOURCE / 'scripts/verify_baseline.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    inventory = baseline.check_py_compile_inventory(SOURCE)
    if not inventory.passed:
        raise RuntimeError(inventory.detail)
    report = dict(compiled=list(FILES), inventory=inventory.detail,
                  capability_coverage='CAPABILITY_COVERAGE_OK', full_baseline_run=False)
    subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SOURCE / 'scripts/verify_capability_coverage.py')],
                   cwd=SOURCE, check=True)
    subprocess.run(['git', 'diff', '--check', '--', '.',
                    ':!Cheating_machine_execution_tool/Auto_power_on_off_tool/config/'], cwd=ROOT, check=True)
    report['diff_check'] = 'passed; independent operator configuration changes excluded'
    for name in ('PROJECT_STATUS.md', 'ACCEPTANCE_BASELINE.md', 'DEVELOPMENT_LOG.md', 'CAPABILITY_COVERAGE.md',
                 'Cheating_machine_execution_tool/line_check_assistant_README.md',
                 '.claude/plans/feishu-sdk-repair.md', 'validation/feishu_sdk_repair_20261116/IMPLEMENTATION.md'):
        (ROOT / name).read_text(encoding='utf-8')
    assert '87 项' in (ROOT / 'CAPABILITY_COVERAGE.md').read_text(encoding='utf-8')
    for name in ('PROJECT_STATUS.md', 'DEVELOPMENT_LOG.md'):
        assert 'validation/feishu_sdk_repair_20261116/IMPLEMENTATION.md' in (ROOT / name).read_text(encoding='utf-8')
    Path(__file__).with_name('static.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'REPAIR_STATIC_OK {len(FILES)} compiled; {inventory.detail}')


if __name__ == '__main__':
    main()

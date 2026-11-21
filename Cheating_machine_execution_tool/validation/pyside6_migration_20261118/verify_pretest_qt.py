"""Check the Qt one-shot pretest and preserve the original implementation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_parameter_writer import check_parameter_bridge
from verify_wifi import verify


def source_checks():
    return verify('pretest_qt_source_checks.json', {
        'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'},
    }, ('tests/test_qt_execution_adapter.py',), {
        'src/services/capability_parameter_services.py': check_parameter_bridge,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='store_true')
    args = parser.parse_args()
    if args.source:
        return source_checks()
    output = Path(__file__).resolve().parent
    native_output = output / 'qt_pretest_verified'
    stages = {
        'unit': ['scripts/run_tests.py', 'test_qt_execution_adapter', 'test_qt_configuration_service',
                 'test_qt_workspace_adapter', 'test_test_item_pretest', 'test_project_completion',
                 'test_gui_test_coverage', '-v'],
        'source': [__file__, '--source'],
        'coverage': ['scripts/verify_capability_coverage.py'],
        'native': ['scripts/verify_qt_migration.py', '--output', str(native_output)],
    }
    evidence = []
    for name, command in stages.items():
        print('START', name, flush=True)
        log = output / f'pretest_qt_{name}.txt'
        run = subprocess.run([sys.executable, *command], cwd=output.parents[1],
            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'),
            capture_output=True, text=True, encoding='utf-8', timeout=540 if name == 'native' else 180)
        transcript = run.stdout + '\n' + run.stderr
        exit_code = run.returncode
        log.write_text(transcript, encoding='utf-8')
        evidence.append(dict(stage=name, passed=exit_code == 0, exit_code=exit_code, output=log.name))
        (output / 'pretest_qt_checks.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print('FINISH', name, exit_code, flush=True)
    return int(not all(row['passed'] for row in evidence))


if __name__ == '__main__':
    raise SystemExit(main())

"""Check Qt test-message dispatch with fake transports and native Windows rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_parameter_writer import check_parameter_bridge
from verify_wifi import verify


def main():
    if sys.argv[1:] == ['--source']:
        return verify('push_trial_qt_source_checks.json', {
            'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'},
        }, ('tests/test_qt_execution_adapter.py',), {
            'src/services/capability_parameter_services.py': check_parameter_bridge,
        })
    output = Path(__file__).resolve().parent
    stages = {
        'unit': ['scripts/run_tests.py', 'test_qt_execution_adapter', 'test_qt_configuration_service',
                 'test_qt_workspace_adapter', 'test_webhook_push', 'test_message_push_config',
                 'test_capability_application', '-v'],
        'source': [__file__, '--source'],
        'coverage': ['scripts/verify_capability_coverage.py'],
        'native': ['scripts/verify_qt_migration.py', '--output', str(output / 'qt_push_trial_verified')],
    }
    evidence = []
    for name, command in stages.items():
        print('START', name, flush=True)
        run = subprocess.run([sys.executable, *command], cwd=output.parents[1],
            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'),
            capture_output=True, text=True, encoding='utf-8', timeout=540 if name == 'native' else 180)
        log = output / f'push_trial_qt_{name}.txt'
        transcript = run.stdout + '\n' + run.stderr
        log.write_text(transcript, encoding='utf-8')
        evidence.append(dict(stage=name, passed=run.returncode == 0, exit_code=run.returncode, output=log.name))
        (output / 'push_trial_qt_checks.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print('FINISH', name, run.returncode, flush=True)
        if run.returncode:
            print(transcript[-3500:], flush=True)
            return run.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

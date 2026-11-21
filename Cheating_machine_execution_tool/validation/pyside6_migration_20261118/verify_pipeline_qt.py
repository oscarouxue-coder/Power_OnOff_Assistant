"""Run the Qt pipeline, source preservation, and native window gates."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_parameter_writer import check_parameter_bridge
from verify_wifi import verify


def main():
    if '--source' in sys.argv:
        return verify('pipeline_qt_source_checks.json', {
            'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
        }, ('tests/test_qt_execution_adapter.py',), {
            'src/services/capability_parameter_services.py': check_parameter_bridge,
        })
    output = Path(__file__).resolve().parent
    stages = {
        'unit': ['scripts/run_tests.py', 'test_qt_execution_adapter', 'test_qt_workspace_adapter',
                 'test_qt_serial_terminal', 'test_pipeline_orchestrator', 'test_capabilities', 'test_project_completion', '-v'],
        'source': [__file__, '--source'],
        'native': ['scripts/verify_qt_migration.py', '--output', str(output / 'qt_pipeline_verified')],
    }
    evidence = []
    for name, command in stages.items():
        print('START', name, flush=True)
        run = subprocess.run([sys.executable, *command], cwd=output.parents[1],
            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'), capture_output=True,
            text=True, encoding='utf-8', timeout=400)
        log = output / f'pipeline_qt_{name}.txt'
        transcript = run.stdout + '\n' + run.stderr
        log.write_text(transcript, encoding='utf-8')
        evidence.append(dict(stage=name, passed=run.returncode == 0, exit_code=run.returncode, output=log.name))
        (output / 'pipeline_qt_checks.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print('FINISH', name, run.returncode, flush=True)
        if run.returncode:
            print(transcript[-3000:], flush=True)
            return run.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

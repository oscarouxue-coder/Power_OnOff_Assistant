"""Verify the legacy import, DUT store path, and TR069 display follow-up."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_wifi import verify


def main():
    if '--source' in sys.argv:
        return verify('qt_followup_source_checks.json', {
            'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
        }, ('tests/test_qt_workspace_adapter.py', 'tests/test_qt_dut_configuration.py'))
    output = Path(__file__).resolve().parent
    root = output.parents[1]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    steps = {
        'unit': ['scripts/run_tests.py', 'test_qt_workspace_adapter', 'test_qt_dut_configuration',
                 'test_qt_dut_voice_tr069', 'test_qt_dut_wifi', 'test_qt_dut_wan', 'test_qt_execution_adapter', '-v'],
        'source': [str(Path(__file__).resolve()), '--source'],
        'native': ['scripts/verify_qt_migration.py', '--output', str(output/'qt_followup_verified')],
    }
    results = []
    for stage, args in steps.items():
        print('START', stage, flush=True)
        result = subprocess.run([sys.executable, *args], cwd=root, env=env, capture_output=True, text=True,
                                encoding='utf-8', timeout=360)
        transcript = result.stdout+'\n'+result.stderr
        log = output/f'qt_followup_{stage}.txt'
        log.write_text(transcript, encoding='utf-8')
        results.append(dict(stage=stage, passed=result.returncode == 0, exit_code=result.returncode, output=log.name))
        (output/'qt_followup_checks.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
        print('FINISH', stage, result.returncode, flush=True)
        if result.returncode:
            print(transcript[-1500:])
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

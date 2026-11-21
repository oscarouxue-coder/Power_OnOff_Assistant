"""Cumulative DUT source preservation and original/Qt verification receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_wifi import verify


def main():
    if '--source' in sys.argv:
        return verify('voice_tr069_source_checks.json', {
            'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
        }, ('tests/qt_voice_tr069_fakes.py', 'tests/test_qt_dut_voice_tr069.py'))
    output = Path(__file__).resolve().parent
    root = output.parents[1]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    checks = []
    steps = {
        'unit': ['scripts/run_tests.py', 'test_qt_dut_voice_tr069', 'test_qt_dut_wifi', 'test_qt_dut_wan',
                 'test_qt_dut_configuration', 'test_qt_execution_adapter', '-v'],
        'source': [str(Path(__file__).resolve()), '--source'],
        'native': ['scripts/verify_qt_migration.py', '--output', str(output/'qt_voice_tr069_verified')],
        'baseline': ['scripts/verify_baseline.py'],
    }
    for stage, command in steps.items():
        print('START', stage, flush=True)
        result = subprocess.run([sys.executable, *command], cwd=root, env=env, text=True, encoding='utf-8',
                                capture_output=True, timeout=1800)
        transcript = result.stdout+'\n'+result.stderr
        file = output/f'voice_tr069_{stage}.txt'
        file.write_text(transcript, encoding='utf-8')
        checks.append(dict(stage=stage, passed=result.returncode == 0, exit_code=result.returncode, output=file.name))
        (output/'voice_tr069_delivery_checks.json').write_text(json.dumps(checks, indent=2)+'\n', encoding='utf-8')
        print('FINISH', stage, result.returncode, flush=True)
        if result.returncode:
            print(transcript[-1200:])
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

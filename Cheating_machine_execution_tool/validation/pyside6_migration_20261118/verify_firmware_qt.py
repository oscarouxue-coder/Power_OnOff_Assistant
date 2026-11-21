"""Run the Qt firmware controller checks without accessing hardware."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_parameter_writer import check_parameter_bridge
from verify_wifi import verify


def main():
    manual = '--manual-restart' in sys.argv
    observation = '--observation' in sys.argv or manual
    prefix = 'firmware_manual' if manual else 'firmware_observation' if observation else 'firmware_final'
    if '--source' in sys.argv:
        return verify(prefix + '_source_checks.json', {
            'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
        }, ('tests/test_qt_firmware_upgrade.py',), {
            'src/services/capability_parameter_services.py': check_parameter_bridge,
        })
    output = Path(__file__).resolve().parent
    root = output.parents[1]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    steps = {
        'unit': ['scripts/run_tests.py', 'test_qt_firmware_upgrade', 'test_qt_execution_adapter',
                 'test_qt_workspace_adapter', 'test_capability_upgrade_equivalence', 'test_page_upgrade',
                 'test_serial_upgrade_service', 'test_web_gateway_upgrade', 'test_upgrade_stop',
                 'test_sample_upgrade_settings_store', *(['test_qt_serial_terminal'] if observation else []),
                 *(['test_capabilities',
                    'test_app.CurrentChannelSelectionTests.test_full_package_requires_manual_reboot_confirmation_when_power_port_empty']
                   if manual else []), '-v'],
        'source': [__file__, '--source', *(['--manual-restart'] if manual else ['--observation'] if observation else [])],
        'native': ['scripts/verify_qt_migration.py', '--output', str(output / ('qt_' + prefix + '_verified'))],
    }
    results = []
    for stage, args in steps.items():
        print('START', stage, flush=True)
        check = subprocess.run([sys.executable, *args], cwd=root, env=env, capture_output=True,
                               text=True, encoding='utf-8', timeout=400)
        transcript = check.stdout + '\n' + check.stderr
        log = output / f'{prefix}_{stage}.txt'
        log.write_text(transcript, encoding='utf-8')
        results.append(dict(stage=stage, passed=check.returncode == 0, exit_code=check.returncode, output=log.name))
        (output / (prefix + '_checks.json')).write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
        print('FINISH', stage, check.returncode, flush=True)
        if check.returncode:
            print(transcript[-2000:], flush=True)
            return check.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

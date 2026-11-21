"""Verify the Qt ONU read stage without accessing a real OLT."""
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_parameter_writer import check_parameter_bridge
from verify_wifi import verify


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]


def verify_source(prefix):
    return verify(prefix + '_source_checks.json', {
        'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
    }, ('tests/test_qt_onu_query.py',), {
        'src/services/capability_parameter_services.py': check_parameter_bridge
    })


def render_original():
    sys.path.insert(0, str(ROOT / 'tests'))
    from tk_test_windows import run_gui_child

    directory = OUTPUT / 'tk_onu_query'
    result = run_gui_child([sys.executable, str(ROOT / 'tests/workbench_visual_probe.py'), '--output', str(directory),
        '--size', '1366x768', '--onu-query'], cwd=str(ROOT), timeout=48, native_render=True,
        capture_output=True, text=True, encoding='utf-8')
    print(result.stdout, end='')
    print(result.stderr, end='')
    evidence = result.offscreen_report
    evidence['passed'] = bool(result.returncode == 0 and (directory / 'onu-tk-before.png').is_file())
    (directory / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return 0 if evidence['passed'] else 1


def main():
    retry = '--retry' in sys.argv
    registration = '--registration' in sys.argv
    cleanup = '--cleanup' in sys.argv
    saving = '--save' in sys.argv or cleanup
    management = '--management' in sys.argv or saving
    if cleanup:
        prefix, native_output = 'onu_cleanup', 'qt_onu_cleanup'
    elif saving:
        prefix, native_output = 'onu_save', 'qt_onu_save'
    elif management:
        prefix, native_output = 'onu_management', 'qt_onu_management'
    elif registration:
        prefix = 'onu_registration_final' if retry else 'onu_registration_qt'
        native_output = 'qt_onu_registration_final' if retry else 'qt_onu_registration_verified'
    else:
        prefix = 'onu_query_verified' if retry else 'onu_query'
        native_output = 'qt_onu_query_verified' if retry else 'qt_onu_query_final'
    if '--source' in sys.argv:
        return verify_source(prefix)
    if '--legacy' in sys.argv:
        return render_original()
    stages = {
        'unit': ['scripts/run_tests.py', 'test_qt_onu_query', 'test_onu_registration_store',
                 'test_onu_registration_service', 'test_onu_registered_query',
                 'test_capability_application', 'test_qt_execution_adapter', 'test_qt_workspace_adapter',
                 *(['test_onu_command_edit_service', 'test_onu_batch_registration_service',
                    'test_onu_vlan_translation'] if registration or management else []),
                 *(['test_onu_batch_delete', 'test_onu_batch_delete_app'] if management else []),
                 *(['test_capability_onu'] if saving else []),
                 *(['test_onu_command_editor_app', 'test_project_completion'] if cleanup else []), '-v'],
        'source': [__file__, '--source', *(['--retry'] if retry else []), *(['--registration'] if registration else []),
                   *(['--cleanup'] if cleanup else ['--save'] if saving else ['--management'] if management else [])],
        **({} if retry or registration or management else {'legacy': [__file__, '--legacy']}),
        'native': ['scripts/verify_qt_migration.py', '--output', str(OUTPUT / native_output)],
    }
    receipt = []
    for name, command in stages.items():
        print('START', name, flush=True)
        completed = subprocess.run([sys.executable, *command], cwd=ROOT, timeout=400,
            capture_output=True, text=True, encoding='utf-8', env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
        transcript = completed.stdout + '\n' + completed.stderr
        log = OUTPUT / f'{prefix}_{name}.txt'
        log.write_text(transcript, encoding='utf-8')
        receipt.append(dict(stage=name, passed=completed.returncode == 0, exit_code=completed.returncode, output=log.name))
        (OUTPUT / (prefix + '_checks.json')).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print('FINISH', name, completed.returncode, flush=True)
        if completed.returncode:
            print(transcript[-4000:], flush=True)
            return completed.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

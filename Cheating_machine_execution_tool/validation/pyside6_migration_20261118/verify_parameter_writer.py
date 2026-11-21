"""Verify the project-parameter writer and render the original and Qt windows."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from verify_wifi import verify


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]


def check_parameter_bridge(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    text = current.read_text(encoding='utf-8')
    serial_bridge = '''            runner_args = (requests, arguments.get("parallel_count", 1), context.stop.event,
                           self.service.manager, network, lambda line: context.event("parameters", line))
            if observe_serial is None:
                values = self.runner(*runner_args)
            else:
                with observe_serial(requests) as ready:
                    values = self.runner(*runner_args, on_session_ready=ready)'''
    if 'observe_serial=None' in text:
        if text.count(serial_bridge) != 1:
            return False
        text = text.replace(', observe_serial=None', '').replace(serial_bridge,
            '''            values = self.runner(requests, arguments.get("parallel_count", 1), context.stop.event, self.service.manager,
                network, lambda line: context.event("parameters", line))''')
    for added, prior in (
        ('snapshot=None, *, records=None', 'snapshot=None'),
        ('        if records is None:\n            records = load_parameter_records', '        records = load_parameter_records'),
        ('authority, *, confirmed_table=None', 'authority'),
        ('''        records = None
        if confirmed_table is not None:
            expected_digest, records = confirmed_table
            if table_info['sha256'] != expected_digest:
                raise CapabilityError('parameter_table_changed', '参数表自本机确认后发生变化，未写参')
        prepared = self._prepare(arguments, authority, records=records)''', '        prepared = self._prepare(arguments, authority)'),
        ("                if confirmed_table is not None and not host:\n                    host = snapshot.get('device_ip', '').strip()\n", ''),
    ):
        if text.count(added) != 1:
            return False
        text = text.replace(added, prior)
    return text == original.decode('utf-8').replace('\r\n', '\n')


def verify_source(prefix):
    return verify(prefix + '_source_checks.json', {
        'dut_voice_tr069_form': {'voice_status_form_values', 'tr069_status_form_values', 'voice_choice_options'}
    }, ('tests/test_qt_parameter_writer.py',), {
        'src/services/capability_parameter_services.py': check_parameter_bridge
    })


def render_original():
    sys.path.insert(0, str(ROOT / 'tests'))
    from tk_test_windows import run_gui_child

    directory = OUTPUT / 'tk_parameter_writer'
    result = run_gui_child([sys.executable, str(ROOT / 'tests/workbench_visual_probe.py'), '--output', str(directory),
        '--size', '1366x768', '--channels', '2', '--parameter-writer'],
        cwd=str(ROOT), timeout=45, native_render=True, capture_output=True, text=True, encoding='utf-8')
    print(result.stdout, end='')
    print(result.stderr, end='')
    evidence = result.offscreen_report
    evidence['passed'] = bool(result.returncode == 0 and (directory / 'parameters-tk-before.png').is_file())
    (directory / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return 0 if evidence['passed'] else 1


def main():
    observation = '--observation' in sys.argv
    prefix = 'parameter_observation' if observation else 'parameter_writer'
    if '--source' in sys.argv:
        return verify_source(prefix)
    if '--legacy' in sys.argv:
        return render_original()
    stages = {
        'unit': ['scripts/run_tests.py', 'test_qt_parameter_writer', 'test_sample_parameter_table',
                 'test_sample_parameter_service', 'test_sample_parameter_pacing', 'test_sample_parameter_app',
                 'test_capability_devices', 'test_sample_upgrade_settings_store', 'test_qt_execution_adapter',
                 'test_qt_workspace_adapter', 'test_qt_firmware_upgrade',
                 *(['test_qt_serial_terminal', 'test_serial_terminal'] if observation else []), '-v'],
        'source': [__file__, '--source', *(['--observation'] if observation else [])],
        **({} if observation else {'legacy': [__file__, '--legacy']}),
        'native': ['scripts/verify_qt_migration.py', '--output', str(OUTPUT / ('qt_' + prefix + '_final'))],
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

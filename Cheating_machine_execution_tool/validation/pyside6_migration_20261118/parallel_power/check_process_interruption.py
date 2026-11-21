"""Abruptly exit a fixture process with two admitted Qt jobs, then reopen its workspace."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGES / 'archived_projects'))
from check_archived_projects import Workspace, block_external_io
from line_check_assistant.config_store import ChannelConfigStore
from qt_execution_fakes import ControlledPipeline, configure_project
from src.models.network_adapter import AdapterIdentity


def run_phase(root, interrupt):
    blocked = []
    block_external_io(blocked)
    engine = ControlledPipeline()
    nics = []
    with ExitStack() as scope:
        scope.enter_context(patch.dict(os.environ, dict(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'),
                                                       PROGRAMDATA=str(root/'machine'))))
        serial = scope.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial forbidden')))
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=nics))
        scope.enter_context(patch('src.services.capability_device_services.PipelineOrchestrator', engine.factory))
        ui = Workspace(root)
        original_path = root / 'before.json'
        records = []
        try:
            if interrupt:
                for i in range(2):
                    directory = root / str(i)
                    pid = ui.command('create', directory, '模拟退出项目 ' + str(i)).project_id
                    context = ui.adapter._service.projects.opened[pid]
                    configure_project(ui.adapter._service, context, (i + 1,))
                    store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
                    alias = 'VLAN' + str(903 + i)
                    store.save([replace(c, adapter_alias=alias, vlan_name=alias, serial_port=f'COM{7521+i}')
                                for c in store.load()], f'COM{7541+i}')
                    ui.adapter._service.projects.save(context)
                    nics.append(AdapterIdentity(alias, 'fixture-process-death-' + alias, 'Up'))
                    token = ui.command('prepare_execution', pid, 'aging.start').payload.token
                    ui.command('confirm_execution', pid, token)
                    ui.wait(lambda: len(engine.calls) == i + 1)
                    ui.command('refresh')
                    ui.wait(lambda: ui.rows[pid].state == 'running')
                    records.append(dict(project=pid, job=ui.rows[pid].run_id, before='running'))
                assert len(ui.adapter._service.resources.owners) == len(engine.calls) == 2
                assert len({r['job'] for r in records}) == 2
                assert not blocked and not serial.called
                original_path.write_text(json.dumps(records), encoding='utf-8')
                # This is the purpose-built fixture process, with no physical workers or descendants.
                os._exit(47)
            original = json.loads(original_path.read_text(encoding='utf-8'))
            for i, record in enumerate(original):
                alias = 'VLAN' + str(903 + i)
                nics.append(AdapterIdentity(alias, 'fixture-process-death-' + alias, 'Up'))
                pid = ui.command('open', root / str(i)).project_id
                assert pid == record['project']
                ui.wait(lambda: pid in ui.rows)
                view = ui.rows[pid]
                assert view.state == 'unknown' and not view.can_start and not view.can_stop and not view.active_task_count
                resource = ui.adapter._service.resources
                owners = resource.unknown_for(pid)
                assert set(owners) == {record['job']}
                key = ui.adapter.submit('prepare_execution', pid, 'aging.start')
                ui.wait(lambda: key in ui.results)
                assert ui.results[key].error and not ui.results[key].payload
                assert set(resource.unknown_for(pid)) == {record['job']}
                history = ui.command('history_jobs', pid, None).payload
                assert len(history.entries) == 1 and history.entries[0].job_id == record['job']
                assert history.entries[0].state in ('running', 'unknown')
                records.append(dict(**record, after=view.state, active_jobs=view.active_task_count,
                                    stored_job_state=history.entries[0].state, previous_resource_owner_preserved=True,
                                    restart_blocked=True))
            assert len(ui.rows) == 2 and not engine.calls and not blocked and not serial.called
            first, second = records
            review = ui.command('job_review_prepare', first['project'], first['job']).payload
            result = ui.command('job_review_commit', first['project'], review.token, 'failed',
                                '模拟进程已退出，测试引擎未完成本批次').payload
            assert result == 'failed'
            assert not resource.unknown_for(first['project'])
            assert set(resource.unknown_for(second['project'])) == {second['job']}
            confirmation = ui.command('prepare_execution', first['project'], 'aging.start').payload
            assert confirmation.token and confirmation.project_id == first['project']
            ui.command('cancel_confirmation', first['project'], confirmation.token)
            assert ui.rows[second['project']].state == 'unknown'
            assert not engine.calls and not blocked and not serial.called
        finally:
            engine.release_stop.set()
            engine.finish.set()
            ui.close()
        (root / 'after.json').write_text(json.dumps(dict(projects=records, new_engine_calls=len(engine.calls),
            external_io=blocked, physical_serial_opens=serial.call_count, first_review_outcome=result,
            first_can_prepare_after_review=True, second_remains_protected=True)), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('interrupt', 'reopen'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.phase:
        run_phase(args.root, args.phase == 'interrupt')
    else:
        assert args.output
        with tempfile.TemporaryDirectory(prefix='dutpilot-qt-death-') as tmp:
            root = Path(tmp).resolve()
            for phase, expected in [('interrupt', 47), ('reopen', 0)]:
                command = [sys.executable, '-X', 'utf8', __file__, '--phase', phase, '--root', str(root)]
                code = subprocess.run(command, timeout=90).returncode
                assert code == expected, (phase, code)
            result = json.loads((root / 'after.json').read_text(encoding='utf-8'))
        args.output.write_text(json.dumps(dict(expected_abrupt_exit_code=47, **result), indent=2), encoding='utf-8')
        print('TWO_PROJECT_PROCESS_INTERRUPTION_VERIFIED')

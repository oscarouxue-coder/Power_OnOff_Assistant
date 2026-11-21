"""Replay copied pre-migration project data through the Qt workspace without hardware."""
import argparse
from contextlib import closing
from dataclasses import fields
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4
import zipfile

STAGES = Path(__file__).resolve().parents[1]
SOURCE = STAGES.parents[1]
sys.path[:0] = [str(SOURCE), str(STAGES / 'power_worker_replay')]
from replay import block_external_io
from line_check_assistant.config_store import ChannelConfigStore
from src.core.host_resource_lock import HostResourceLock
from src.models.project import PROJECT_FILE
from src.services.legacy_power_test_service import LegacyPowerChannel, prepare_legacy_power_test_request
from src.services.qt_workspace_adapter import QtWorkspaceAdapter


def digest_file(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(path):
    return {p.relative_to(path): digest_file(p) for p in path.rglob('*') if p.is_file()}


def restore(archive, root):
    with zipfile.ZipFile(archive) as bundle:
        groups = sorted({n.split('/')[0] for n in bundle.namelist() if n.count('/') == 1 and n.endswith('/' + PROJECT_FILE)})
        assert groups, 'no archived projects'
        for group in groups:
            target_root = root / group
            for info in bundle.infolist():
                if info.is_dir() or not info.filename.startswith(group + '/'):
                    continue
                parts = PurePosixPath(info.filename).parts[1:]
                target = target_root.joinpath(*parts)
                assert target.resolve().is_relative_to(target_root.resolve()) and not target.exists()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(info))
        return [root / group for group in groups]


class Workspace:
    def __init__(self, root):
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=root / 'workspace')
        self.rows = {}
        self.results = {}
        self.wait(lambda: any(r.operation == 'ready' for r in self.results.values()))

    def wait(self, condition):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            rows, _, messages = self.adapter.take_updates()
            self.rows = {r.project_id: r for r in rows}
            self.results.update((r.identifier, r) for r in messages)
            if condition():
                return
            time.sleep(.02)
        raise AssertionError('workspace command timed out')

    def command(self, operation, *args):
        key = self.adapter.submit(operation, *args)
        self.wait(lambda: key in self.results)
        reply = self.results.pop(key)
        assert not reply.error, f'{operation} failed'
        return reply

    def close(self):
        self.adapter.begin_close({pid: 'discard' for pid in self.rows})
        assert self.adapter.wait_closed(25)


def check_history(ui, directory, pid):
    jobs = []
    database = directory / 'history/ai/business/capability_jobs.sqlite3'
    expected_events = {}
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            jobs = db.execute('SELECT id,capability,state FROM jobs ORDER BY rowid DESC').fetchall()
            expected_events = dict(db.execute("SELECT job_id,count(*) FROM job_events WHERE message != '' GROUP BY job_id"))
    seen, cursor = [], None
    while True:
        page = ui.command('history_jobs', pid, cursor).payload
        seen.extend((j.job_id, j.capability, j.state) for j in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == jobs
    count = 0
    for job, _, _ in jobs:
        cursor, n = None, 0
        while True:
            page = ui.command('history_events', pid, cursor, job).payload
            n += len(page.entries)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert n == expected_events.get(job, 0)
        count += n
    runs = [json.loads(p.read_text(encoding='utf-8')) for p in (directory / 'runs').glob('*/run.json')]
    # The archived data set contains both original successful and uncertain runs.
    original = {}
    states = {'succeeded': '成功', 'unknown': '结果未知，待核实'}
    for record in runs:
        if record.get('project_id') == pid and str(record.get('owner', '')).startswith('gui:' + pid + ':'):
            title = states[record['state']]
            if record['state'] == 'unknown' and record.get('reconciled') is True:
                title = '已核实（原结果未知）'
            original[record['run_id']] = (record['operation'], record['revision'], title)
    page = ui.command('history_legacy_runs', pid, None).payload
    assert page.next_cursor is None
    assert {r.run_id: (r.operation, r.revision, r.state) for r in page.entries} == original
    return dict(database_jobs=len(jobs), database_events=count, legacy_gui_runs=len(original),
                succeeded_runs=sum(r['state'] == 'succeeded' for r in runs),
                unknown_runs=sum(r['state'] == 'unknown' for r in runs))


def check_project_logs(ui, directory, pid):
    root = directory / 'logs/main'
    expected = {p for p in root.rglob('*') if p.is_file()}
    files = ui.command('archive_project_files', pid).payload
    assert {f.path for f in files} == expected and len(files) == len(expected)
    counts = dict(main_log_files=0, monitor_files=0, source_log_lines=0)
    for entry in files:
        cursor, pages = None, []
        while True:
            page = ui.command('archive_project_log', pid, entry.path, cursor).payload
            assert all(row.project_id == pid and row.raw for row in page.entries)
            pages.append([row.message for row in page.entries])
            cursor = page.next_cursor
            if cursor is None:
                break
        original = entry.path.read_text(encoding='utf-8-sig').splitlines()
        assert [line for group in reversed(pages) for line in group] == original
        counts['monitor_files' if entry.path.suffix == '.jsonl' else 'main_log_files'] += 1
        counts['source_log_lines'] += len(original)
    return counts


def verify(ui, directory):
    descriptor = json.loads((directory / PROJECT_FILE).read_text(encoding='utf-8'))
    pid = descriptor['project_id']
    cfg = directory / 'draft/Auto_power_on_off_tool/config'
    old_cfg = inventory(cfg)
    revisions = inventory(directory / 'revisions')
    run_inputs = {p: v for p, v in inventory(directory / 'runs').items() if 'config' in p.parts}
    logs = inventory(directory / 'logs')
    store = ChannelConfigStore(cfg / 'network_card_ip.ini')
    expected = {int(c.section.split('_')[-1]): (c.enabled, c.vlan_name, c.serial_port) for c in store.load()}
    assert ui.command('open', directory).project_id == pid
    ui.wait(lambda: pid in ui.rows)
    row = ui.rows[pid]
    assert row.name == descriptor['name'] and row.active_task_count == 0
    actual = {c.number: (c.state != 'disabled', c.vlan, c.port) for c in row.channels}
    assert all(actual.get(n) == v for n, v in expected.items())
    counts = check_history(ui, directory, pid)
    log_counts = check_project_logs(ui, directory, pid)
    ui.command('save', pid)
    saved = json.loads((directory / PROJECT_FILE).read_text(encoding='utf-8'))
    assert saved['project_id'] == pid and saved['revision'] != descriptor['revision']
    assert inventory(directory / 'revisions' / saved['revision'] / 'Auto_power_on_off_tool/config') == old_cfg
    ui.command('close', pid)
    ui.wait(lambda: pid not in ui.rows)
    assert ui.command('open', directory).project_id == pid
    ui.wait(lambda: pid in ui.rows)
    assert ui.rows[pid].channels == row.channels and ui.rows[pid].name == row.name
    assert counts == check_history(ui, directory, pid)
    assert log_counts == check_project_logs(ui, directory, pid)
    assert inventory(cfg) == old_cfg and all(digest_file(directory / 'revisions' / p) == v for p, v in revisions.items())
    assert all(digest_file(directory / 'runs' / p) == v for p, v in run_inputs.items())
    assert inventory(directory / 'logs') == logs and not ui.adapter._service.resources.owners
    return dict(channels_in_config=len(expected), displayed_channels=len(actual), draft_files=len(old_cfg),
                previous_revision_files=len(revisions), run_config_files=len(run_inputs), previous_logs=len(logs),
                **counts, **log_counts)


def verify_single_project_import(ui, archive, root):
    old = root / 'legacy/Auto_power_on_off_tool/config'
    old.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        candidates = [n for n in bundle.namelist() if n.count('/') == 1 and n.endswith('/network_card_ip.ini')]
        assert len(candidates) == 1
        group = candidates[0].split('/')[0]
        for info in bundle.infolist():
            if not info.is_dir() and info.filename.startswith(group + '/'):
                target = old.joinpath(*PurePosixPath(info.filename).parts[1:])
                assert target.resolve().is_relative_to(old) and not target.exists()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(info))
    before = inventory(old)
    assert all(p.suffix.lower() in ('.ini', '.py', '.pyc') or '.bak_' in p.suffix for p in before)
    destination = root / 'imported'
    pid = ui.command('import_legacy', old, destination, '单项目配置复验').project_id
    ui.wait(lambda: pid in ui.rows)
    backups = list((destination / 'backups/imports').iterdir())
    assert len(backups) == 1
    manifest = json.loads((backups[0] / 'manifest.json').read_text(encoding='utf-8'))
    expected = {p: v for p, v in before.items() if p.suffix.lower() == '.ini'}
    assert manifest['state'] == 'complete' and inventory(backups[0] / 'config') == expected
    current = destination / 'draft/Auto_power_on_off_tool/config'
    assert set(inventory(current)) == set(expected)

    def request(config):
        channel_store = ChannelConfigStore(config / 'network_card_ip.ini')
        channels = [LegacyPowerChannel(int(c.section.split('_')[-1]), c.network_card_ip)
                    for c in channel_store.load() if c.enabled]
        return prepare_legacy_power_test_request(config.parent, channels)

    old_request, imported_request = request(old), request(current)
    parameters = [f.name for f in fields(old_request) if f.name != 'tool_root']
    assert all(getattr(old_request, f) == getattr(imported_request, f) for f in parameters)
    assert imported_request.tool_root == current.parent and old_request.tool_root == old.parent
    ui.command('save', pid)
    ui.command('close', pid)
    ui.wait(lambda: pid not in ui.rows)
    assert ui.command('open', destination).project_id == pid and request(current) == imported_request
    assert inventory(old) == before and not ui.adapter._service.resources.owners
    return dict(source_files=len(before), imported_ini_files=len(expected), checked_request_fields=len(parameters),
                selected_channels=len(old_request.channels), source_files_preserved=True)


def archived_workspace_log(archive, root):
    with zipfile.ZipFile(archive) as bundle:
        matches = [n for n in bundle.namelist() if n.endswith('/workspace.log')]
        assert len(matches) == 1
        content = bundle.read(matches[0])
    directory = root / 'workspace'
    directory.mkdir()
    (directory / 'workspace.log').write_bytes(content)
    return content.decode('utf-8-sig').splitlines()


def read_workspace_log(ui, expected):
    cursor, pages = None, []
    while True:
        page = ui.command('archive_workspace_log', '', cursor).payload
        assert all(entry.raw for entry in page.entries)
        pages.append([entry.message for entry in page.entries])
        cursor = page.next_cursor
        if cursor is None:
            break
    lines = [line for page in reversed(pages) for line in page]
    # Recent working-session messages may follow the original archival data.
    assert expected and lines[:len(expected)] == expected
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads((STAGES / 'backup_receipt.json').read_text(encoding='utf-8-sig'))
    archive = Path(receipt['directory']) / 'data.zip'
    assert digest_file(archive) == receipt['data_zip_sha256']
    blocked = []
    block_external_io(blocked)
    with tempfile.TemporaryDirectory(prefix='dutpilot-old-project-') as tmp:
        root = Path(tmp).resolve()
        projects = restore(archive, root)
        old_workspace_lines = archived_workspace_log(archive, root)
        isolated_mutex = partial(HostResourceLock, namespace='compatibility-' + uuid4().hex)
        with patch.dict(os.environ, dict(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'),
                                         PROGRAMDATA=str(root/'machine'))), \
                patch('src.services.project_store.HostResourceLock', isolated_mutex), \
                patch('serial.Serial', side_effect=AssertionError('unexpected serial access')) as serial:
            ui = Workspace(root)
            try:
                rows = [verify(ui, p) for p in projects]
                assert len(ui.rows) == len(projects)
                imported = verify_single_project_import(ui, archive, root)
                log_lines = read_workspace_log(ui, old_workspace_lines)
            finally:
                ui.close()
            serial.assert_not_called()
    assert not blocked and digest_file(archive) == receipt['data_zip_sha256']
    args.output.write_text(json.dumps(dict(projects=rows, single_project_import=imported, archived_workspace_log_lines=log_lines,
                                           changes_to_archive=False, external_io=blocked,
                                           physical_serial_opens=0), indent=2), encoding='utf-8')
    print('ARCHIVED_PROJECTS_PASSED', len(rows))


if __name__ == '__main__':
    main()

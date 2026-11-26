"""Export only a generated synthetic persisted report as validation evidence."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import json
import sys
from threading import Event
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
with ExitStack() as guard:
    endpoints = ('requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                 'socket.socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.startfile')
    denied = [guard.enter_context(patch(name, side_effect=AssertionError('live I/O forbidden'))) for name in endpoints]
    from test_qt_log_history import QtLogHistoryTests
    from src.services.qt_archived_logs import _read_page
    from src.services.qt_power_logs import (material_report_snapshot, read_material_reports,
                                            save_material_report, summarize_history_materials_batch)
    test = QtLogHistoryTests('test_saved_material_report_exact_scope_round_trip_without_source_reread')
    test.setUp()
    try:
        target, record, paths = test.material_batch_fixture()
        record.update(state='succeeded', updated_at=1795040123)
        original = {path: path.read_bytes() for path in paths}
        def read(path, *args):
            if path == paths[4]:
                raise PermissionError('synthetic failure')
            return _read_page(path, *args)
        with patch('src.services.qt_archived_logs._read_page', side_effect=read):
            summary = summarize_history_materials_batch(test.project, record, target, Event())
        snapshot = material_report_snapshot(test.project, record, summary)
        saved = save_material_report(test.project, record, snapshot, Event())
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('must not reread')) as reread:
            page = read_material_reports(test.project, record, target.job_id, Event())
        assert page.reports == (saved,) and not page.invalid_count and not reread.call_count
        assert all(path.read_bytes() == data for path, data in original.items())
        assert 'fixture-secret-never-copy' not in saved.text
        assert not any(item.call_count for item in denied)
        path = Path(__file__).resolve().parent / 'saved-example.json'
        path.write_text(json.dumps(dict(synthetic=True, persisted=asdict(saved),
            source_rereads=reread.call_count, original_unchanged=True,
            denied_calls={name: item.call_count for name, item in zip(endpoints, denied)}),
            ensure_ascii=False, indent=2), encoding='utf-8')
        print('SYNTHETIC_REPORT_ROUND_TRIP_OK')
    finally:
        test.doCleanups()

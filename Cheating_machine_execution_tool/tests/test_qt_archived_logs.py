import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from src.models.project import ProjectContext, ProjectIdentity
from src.services.qt_archived_logs import read_serial_log, read_workspace_log, serial_log_files
from src.services.qt_log_export import export_log_snapshot
from src.services.qt_archived_logs import project_log_files, read_project_log


class ArchivedLogsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dutpilot-archive-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = ProjectContext(self.root / 'project', ProjectIdentity(str(uuid.uuid4()), '归档项目', 'revision'), self.root)
        self.project.root.mkdir()

    def test_project_main_logs_use_original_names_and_reject_other_directories(self):
        directory = self.project.root / 'logs/main'
        monitor = directory / 'resource_monitor'
        monitor.mkdir(parents=True)
        log = directory / 'line_check_20261120_113355.log'
        resource = monitor / 'transport_history_20261120_113355_123456.jsonl'
        log.write_text('原主日志\n', encoding='utf-8')
        resource.write_text('{"serial_bytes":5}\n', encoding='utf-8')
        for path in (directory / 'unrelated.log', directory / resource.name, monitor / log.name):
            path.touch()
        self.assertEqual([entry.path for entry in project_log_files(self.project)], [resource, log])
        for path in (directory / 'unrelated.log', directory / resource.name, monitor / log.name, self.root / log.name):
            with self.assertRaises(ValueError):
                read_project_log(self.project, path, None)
        entry, = read_project_log(self.project, log, None).entries
        self.assertEqual((entry.message, entry.project_id, entry.raw), ('原主日志', self.project.identity.project_id, True))

    def test_workspace_pages_preserve_original_records_and_append_cursor(self):
        path = self.root / 'workspace.log'
        lines = [f'历史事件 {i:03d}' for i in range(275)]
        path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-8-sig'))
        newest = read_workspace_log(self.root, None)
        self.assertEqual([item.message for item in newest.entries], lines[-120:])
        self.assertTrue(all(item.raw and not (item.level or item.project_id or item.run_id) and item.channel is None
                            for item in newest.entries))
        with path.open('ab') as stream:
            stream.write(b'new record\n')
        middle = read_workspace_log(self.root, newest.next_cursor)
        complete = read_workspace_log(self.root, middle.next_cursor)
        self.assertEqual([item.message for item in complete.entries + middle.entries + newest.entries], lines)
        self.assertIsNone(complete.next_cursor)
        raw_before = path.read_bytes()
        output = self.root / 'filtered.txt'
        export_log_snapshot(output, '工作区日志原文', newest.entries[-2:])
        self.assertTrue(output.read_text(encoding='utf-8-sig').endswith('\n'.join(lines[-2:]) + '\n'))
        self.assertEqual(path.read_bytes(), raw_before)

    def test_long_utf8_line_advances_and_rotated_archive_rejects_old_cursor(self):
        path = self.root / 'workspace.log'
        message = '设备长行' * 110
        original = (message + '\n').encode()
        path.write_bytes(original)
        with patch('src.services.qt_archived_logs.MAX_PAGE_BYTES', 253):
            page = read_workspace_log(self.root, None)
            cursor = page.next_cursor
            recovered = [page.entries[0].message]
            self.assertIn('跨页长行', page.note)
            while page.next_cursor is not None:
                page = read_workspace_log(self.root, page.next_cursor)
                recovered.extend(item.message for item in page.entries)
            self.assertEqual(''.join(reversed(recovered)), message)
        renamed = self.root / 'workspace.old'
        path.rename(renamed)
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, '已替换'):
            read_workspace_log(self.root, cursor)

    def test_serial_files_require_project_location_and_original_filename(self):
        inside = self.project.root / 'logs/serial'
        inside.mkdir(parents=True)
        older = inside / 'vlan101_COM1_20261119.log'
        older.write_text('2026-11-19_01:02:03 RX 旧设备输出\n', encoding='utf-8')
        (inside / 'notes.log').write_text('other data', encoding='utf-8')
        custom = self.root / 'selected' / self.project.identity.project_id
        custom.mkdir(parents=True)
        latest = custom / 'vlan102_COM2_20261120.log'
        latest.write_text('2026-11-20_01:02:03 TX show uptime\n', encoding='utf-8')
        state = self.project.root / 'ui/serial.json'
        state.parent.mkdir()
        state.write_text(json.dumps({'log_dir': str(custom)}), encoding='utf-8')
        self.assertEqual([item.path for item in serial_log_files(self.project)], [latest, older])
        row, = read_serial_log(self.project, latest, None).entries
        self.assertEqual(row.project_id, self.project.identity.project_id)
        self.assertIsNone(row.channel)
        self.assertEqual(row.message, '2026-11-20_01:02:03 TX show uptime')
        outside = self.root / 'shared'
        outside.mkdir()
        wrong = outside / latest.name
        wrong.write_text('outside project', encoding='utf-8')
        state.write_text(json.dumps({'log_dir': str(outside)}), encoding='utf-8')
        self.assertEqual([item.path for item in serial_log_files(self.project)], [older])
        with self.assertRaisesRegex(ValueError, '不属于'):
            read_serial_log(self.project, wrong, None)
        with self.assertRaisesRegex(ValueError, '目录已变化'):
            read_serial_log(self.project, latest, None)

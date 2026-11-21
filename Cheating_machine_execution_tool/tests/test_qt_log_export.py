from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.models.workbench_presentation import LogView
from src.services.qt_log_export import export_log_snapshot


class QtLogExportTests(unittest.TestCase):
    def test_writes_utf8_selected_records_with_full_identity_without_overwriting(self):
        row = LogView('10:02:03', 'WARN', 'project-uuid', '模拟项目', '等待通道\n仍在运行', 'full-job-id', 7)
        with TemporaryDirectory() as directory:
            path = Path(directory) / '已选日志.txt'
            self.assertEqual(export_log_snapshot(path, '当前任务 · WARN', (row,)), 1)
            first = path.read_bytes()
            content = first.decode('utf-8-sig')
            self.assertIn('[项目=project-uuid 任务=full-job-id 通道=CH07]', content)
            self.assertIn('等待通道\n仍在运行', content)
            with self.assertRaisesRegex(ValueError, '文件已存在'):
                export_log_snapshot(path, '不同的范围', (row,))
            self.assertEqual(path.read_bytes(), first)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_or_failed_output_does_not_leave_a_partial_file(self):
        row = LogView('10:02:03', 'INFO', '', '工作区', '模拟日志')
        with TemporaryDirectory() as directory:
            path = Path(directory) / '记录.txt'
            for target, rows in ((Path('relative.txt'), (row,)), (path.with_suffix('.ini'), (row,)), (path, ())):
                with self.assertRaises(ValueError):
                    export_log_snapshot(target, '', rows)
            with patch('src.services.qt_log_export.Path.rename', side_effect=PermissionError), \
                    patch('src.services.qt_log_export.os.link', side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    export_log_snapshot(path, '当前范围', (row,))
            self.assertEqual(list(path.parent.iterdir()), [])

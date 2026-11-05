import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.power_test_log_service import latest_power_test_result_log, latest_power_test_wifi_log


class PowerTestLogLookupTests(unittest.TestCase):
    def test_latest_log_is_selected_by_filename_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results_dir = root / "test_results" / "device_2"
            results_dir.mkdir(parents=True)
            older = results_dir / "device_2_command_results_20260830235959.log"
            latest = results_dir / "device_2_command_results_20260831002652.log"
            older.write_text("older", encoding="utf-8")
            latest.write_text("latest", encoding="utf-8")

            self.assertEqual(latest_power_test_result_log(root, 2), latest)

    def test_lookup_uses_only_the_selected_channel_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            other_dir = root / "test_results" / "device_3"
            other_dir.mkdir(parents=True)
            (other_dir / "device_3_command_results_20260831002652.log").write_text(
                "other", encoding="utf-8"
            )

            self.assertIsNone(latest_power_test_result_log(root, 2))

    def test_lookup_rejects_non_positive_channel_number(self):
        with self.assertRaisesRegex(ValueError, "通道编号"):
            latest_power_test_result_log(Path("."), 0)

    def test_wifi_lookup_uses_latest_timestamp_including_resume_and_never_command_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'test_results/device_2'
            target.mkdir(parents=True)
            names = ['device_2_wifi_20261106000102123456.log',
                     'device_2_wifi_20261106000502123456_resume_1.log',
                     'device_2_command_results_20261107000102.log']
            for name in names:
                (target / name).write_text(name, encoding='utf-8')
            self.assertEqual(latest_power_test_wifi_log(root, 2), target / names[1])
            self.assertEqual(latest_power_test_result_log(root, 2), target / names[2])

    def test_wifi_lookup_is_channel_scoped_and_ignores_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'test_results/device_2'
            target.mkdir(parents=True)
            (target / 'device_2_wifi_20990101.log').mkdir()
            (target / 'device_7_wifi_20261106.log').write_text('other', encoding='utf-8')
            other = root / 'test_results/device_7'
            other.mkdir()
            (other / 'device_2_wifi_20261106.log').write_text('wrong folder', encoding='utf-8')
            self.assertIsNone(latest_power_test_wifi_log(root, 2))

    def test_wifi_lookup_without_directory_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(latest_power_test_wifi_log(root, 2))
            self.assertFalse((root / 'test_results').exists())

    def test_wifi_lookup_rejects_invalid_channel_and_reports_permission_error(self):
        with self.assertRaisesRegex(ValueError, '通道编号'):
            latest_power_test_wifi_log(Path('.'), 0)
        with patch.object(Path, 'glob', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(OSError, 'WiFi结果目录'):
                latest_power_test_wifi_log(Path('.'), 2)


if __name__ == "__main__":
    unittest.main()

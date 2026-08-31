import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.power_test_log_service import latest_power_test_result_log


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


if __name__ == "__main__":
    unittest.main()

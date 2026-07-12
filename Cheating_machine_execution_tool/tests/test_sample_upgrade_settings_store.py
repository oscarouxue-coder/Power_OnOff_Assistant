import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.sample_upgrade_settings_store import (
    DEFAULT_PARALLEL_COUNT,
    DEFAULT_UPGRADE_EXECUTION_MODE,
    DEFAULT_UPGRADE_MODE,
    DEFAULT_UPGRADE_TRANSFER,
    MAX_PARALLEL_UPGRADES,
    SampleUpgradeSettings,
    SampleUpgradeSettingsStore,
    clamp_parallel_count,
)


class SampleUpgradeSettingsStoreTests(unittest.TestCase):
    def test_load_uses_defaults_when_config_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")

            settings = store.load()

            self.assertEqual(settings.upgrade_mode, DEFAULT_UPGRADE_MODE)
            self.assertEqual(settings.transfer_method, DEFAULT_UPGRADE_TRANSFER)
            self.assertEqual(settings.execution_mode, DEFAULT_UPGRADE_EXECUTION_MODE)
            self.assertFalse(settings.restore_factory)
            self.assertEqual(settings.username, "")
            self.assertEqual(settings.password, "")
            self.assertEqual(settings.firmware_path, "")

    def test_save_and_load_preserves_last_closed_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            saved = SampleUpgradeSettings(
                upgrade_mode="页面升级",
                transfer_method="web打开网关",
                execution_mode="并行（最多 2 台）",
                restore_factory=True,
                username="root",
                password="secret",
                firmware_path=r"F:\firmware\tclinux_allinone",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded, saved)

    def test_save_and_load_preserves_percent_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            saved = SampleUpgradeSettings(
                username="root",
                password="abc%123",
                firmware_path=r"F:\firmware\100%\tclinux_allinone",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.password, "abc%123")
            self.assertEqual(loaded.firmware_path, r"F:\firmware\100%\tclinux_allinone")

    def test_parallel_count_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            saved = SampleUpgradeSettings(parallel_count=6)

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.parallel_count, 6)

    def test_parallel_count_clamps_out_of_range_and_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            for raw, expected in (
                (0, 1),
                (-3, 1),
                (99, MAX_PARALLEL_UPGRADES),
                ("abc", DEFAULT_PARALLEL_COUNT),
                (None, DEFAULT_PARALLEL_COUNT),
            ):
                self.assertEqual(clamp_parallel_count(raw), expected, f"raw={raw!r}")


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.sample_upgrade_settings_store import (
    DEFAULT_PARAMETER_PARALLEL_COUNT,
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
            self.assertEqual(settings.parameter_initial_username, "")
            self.assertEqual(settings.parameter_initial_password, "")

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
                parameter_initial_username="telecomadmin",
                parameter_initial_password="nE7jA%5m",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded, saved)

    def test_save_and_load_preserves_parameter_initial_credentials(self):
        # 写样机参数窗口的「首次登录账号 / 密码」独立 key,与升级超级凭据不混淆。
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            saved = SampleUpgradeSettings(
                username="root",
                password="upgrade-secret",
                parameter_initial_username="telecomadmin",
                parameter_initial_password="nE7jA%5m",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.parameter_initial_username, "telecomadmin")
            self.assertEqual(loaded.parameter_initial_password, "nE7jA%5m")
            # 与升级超级凭据分开存放。
            self.assertEqual(loaded.username, "root")
            self.assertEqual(loaded.password, "upgrade-secret")

    def test_load_missing_parameter_initial_keys_defaults_to_empty(self):
        # 兼容旧 ini(尚未存盘过 parameter_initial_*):缺字段回退空字符串。
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "sample_upgrade_settings.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            parser["sample_upgrade"] = {
                "username": "root",
                "password": "secret",
            }
            config_path.write_text("", encoding="utf-8") if False else None
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)

            loaded = SampleUpgradeSettingsStore(config_path).load()
            self.assertEqual(loaded.parameter_initial_username, "")
            self.assertEqual(loaded.parameter_initial_password, "")

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

    def test_save_and_load_preserves_parameter_clear_and_exit_aging(self):
        # 2026-07-19:写样机参数流水线新增 clear_parameters / exit_aging 两个 bool,
        # 独立存读,与升级 restore_factory / parameter_initial_* 不混淆。
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SampleUpgradeSettingsStore(Path(temp_dir) / "sample_upgrade_settings.ini")
            saved = SampleUpgradeSettings(
                parameter_initial_username="telecomadmin",
                parameter_initial_password="nE7jA%5m",
                parameter_clear_parameters=True,
                parameter_exit_aging=True,
            )

            store.save(saved)
            loaded = store.load()

            self.assertTrue(loaded.parameter_clear_parameters)
            self.assertTrue(loaded.parameter_exit_aging)
            # 升级凭据未被覆盖
            self.assertEqual(loaded.parameter_initial_username, "telecomadmin")
            self.assertEqual(loaded.parameter_initial_password, "nE7jA%5m")

    def test_load_missing_parameter_clear_and_exit_aging_keys_defaults_to_false(self):
        # 兼容旧 ini(尚未存盘过 parameter_clear_*/exit_aging*):缺字段回退到 False,
        # 与既有 parameter_initial_* 的 fallback 策略一致。
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "sample_upgrade_settings.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            parser["sample_upgrade"] = {
                "username": "root",
                "password": "secret",
                "parameter_initial_username": "telecomadmin",
                "parameter_initial_password": "nE7jA%5m",
            }
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)

            loaded = SampleUpgradeSettingsStore(config_path).load()
            self.assertFalse(loaded.parameter_clear_parameters)
            self.assertFalse(loaded.parameter_exit_aging)
            # parameter_initial_* 字段仍能正常读出
            self.assertEqual(loaded.parameter_initial_username, "telecomadmin")
            self.assertEqual(loaded.parameter_initial_password, "nE7jA%5m")

    def test_default_parameter_parallel_count_is_one(self):
        # 2026-07-19 用户要求:写样机参数默认并行数从 2 改为 1。
        # 锁定常量本身,避免后续被改回;同时确认升级窗口的 DEFAULT_PARALLEL_COUNT
        # 仍保持 2,两个默认值不互相污染。
        self.assertEqual(DEFAULT_PARAMETER_PARALLEL_COUNT, 1)
        self.assertEqual(DEFAULT_PARALLEL_COUNT, 2)


if __name__ == "__main__":
    unittest.main()

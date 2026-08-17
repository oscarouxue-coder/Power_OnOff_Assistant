import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.onu_registration_store import (
    DEFAULT_C300_SOURCE_IP,
    DEFAULT_OLT_IP,
    OnuRegistrationConfig,
    OnuRegistrationStore,
)


class OnuRegistrationStoreTests(unittest.TestCase):
    def test_load_uses_default_olt_ip_when_config_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OnuRegistrationStore(Path(temp_dir) / "onu_registration.ini")

            config = store.load()

            self.assertEqual(config.olt_ip, DEFAULT_OLT_IP)
            self.assertEqual(config.source_ip, DEFAULT_C300_SOURCE_IP)
            self.assertEqual(config.source_ip, "172.18.18.40")
            self.assertEqual(config.username, "")
            self.assertEqual(config.password, "")

    def test_save_and_load_preserves_last_closed_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OnuRegistrationStore(Path(temp_dir) / "onu_registration.ini")
            saved = OnuRegistrationConfig(
                olt_ip="172.18.18.200",
                username="admin",
                password="secret",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.olt_ip, saved.olt_ip)
            self.assertEqual(loaded.username, saved.username)
            self.assertEqual(loaded.password, saved.password)
            self.assertEqual(loaded.c300_olt_ip, saved.olt_ip)
            self.assertEqual(loaded.c300_username, saved.username)
            self.assertEqual(loaded.c300_password, saved.password)

    def test_save_and_load_preserves_percent_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OnuRegistrationStore(Path(temp_dir) / "onu_registration.ini")
            saved = OnuRegistrationConfig(
                olt_ip="172.18.18.151",
                username="zte",
                password="abc%123",
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.password, "abc%123")

    def test_save_and_load_preserves_dual_olt_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OnuRegistrationStore(Path(temp_dir) / "onu_registration.ini")
            saved = OnuRegistrationConfig(
                olt_ip="172.18.18.152",
                source_ip="172.33.5.35",
                username="zte",
                password="secret",
                olt_family="C600",
                c300_olt_ip="172.18.18.151",
                c300_source_ip="172.18.18.40",
                c300_username="zte",
                c300_password="zte",
                c600_olt_ip="172.18.18.152",
                c600_source_ip="172.33.5.35",
                c600_username="zte",
                c600_password="secret",
                c600_shelf=1,
                c600_slot=2,
                c600_pon=5,
                c600_onu_id=55,
                c600_onu_type="CXP-55",
                c600_services="1,170\n2,335\n6,600",
                c300_allow_offline_cleanup=True,
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.olt_family, "C600")
            self.assertEqual(loaded.olt_ip, "172.18.18.152")
            self.assertEqual(loaded.source_ip, "172.33.5.35")
            self.assertEqual(loaded.username, "zte")
            self.assertEqual(loaded.password, "secret")
            self.assertEqual(loaded.c600_username, "zte")
            self.assertEqual(loaded.c600_password, "secret")
            self.assertEqual(loaded.c300_source_ip, "172.18.18.40")
            self.assertEqual(loaded.c300_password, "zte")
            self.assertFalse(loaded.c300_allow_offline_cleanup)

    def test_invalid_numeric_and_boolean_values_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "onu_registration.ini"
            path.write_text(
                "[onu_registration]\nc600_onu_id=bad\nc600_sn_bind_both=bad\n"
                "c300_allow_offline_cleanup=bad\n",
                encoding="utf-8",
            )

            loaded = OnuRegistrationStore(path).load()

            self.assertEqual(loaded.c600_onu_id, 1)
            self.assertTrue(loaded.c600_sn_bind_both)
            self.assertFalse(loaded.c300_allow_offline_cleanup)


if __name__ == "__main__":
    unittest.main()

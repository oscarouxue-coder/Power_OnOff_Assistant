import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.onu_registration_store import DEFAULT_OLT_IP, OnuRegistrationConfig, OnuRegistrationStore


class OnuRegistrationStoreTests(unittest.TestCase):
    def test_load_uses_default_olt_ip_when_config_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OnuRegistrationStore(Path(temp_dir) / "onu_registration.ini")

            config = store.load()

            self.assertEqual(config.olt_ip, DEFAULT_OLT_IP)
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

            self.assertEqual(loaded, saved)

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


if __name__ == "__main__":
    unittest.main()

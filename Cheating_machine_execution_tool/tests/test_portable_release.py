import configparser
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.create_portable_config import PORTABLE_CONFIG_NAMES, create_portable_config


class PortableReleaseConfigTests(unittest.TestCase):
    def _write_source_configs(self, source: Path) -> None:
        source.mkdir(parents=True)
        (source / "config.ini").write_text(
            """[config]
test_project = test_project_config.ini
[ui_defaults]
selected_profile = TEST_PROJECT
[dingtalk_config]
dingtalk_flag = 1
webhook = https://example.invalid/current-webhook
secret = current-dingtalk-secret
at_all = 1
[remote_config]
remote_tool_name = current-remote-tool
remote_identification_code = current-remote-id
remote_verification_code = current-remote-code
[Emails]
emails = current@example.invalid
""",
            encoding="utf-8",
        )
        (source / "network_card_ip.ini").write_text(
            """[power_supply]
serial_port = COM102
[channel_8]
adapter_alias = current-vlan-adapter
serial_port = COM13
network_card_ip = 192.0.2.108
""",
            encoding="utf-8",
        )
        (source / "onu_registration.ini").write_text(
            """[onu_registration]
olt_ip = 192.0.2.10
source_ip = 192.0.2.20
username = current-olt-user
password = current-olt-password
olt_family = C600
c300_olt_ip = 192.0.2.30
c300_source_ip = 192.0.2.40
c300_username = current-c300-user
c300_password = current-c300-password
c600_olt_ip = 192.0.2.50
c600_source_ip = 192.0.2.60
c600_username = current-c600-user
c600_password = current-c600-password
c600_onu_id = 55
c600_onu_type = NP7287XGS
c600_real_speed = auto
c600_services = 1,170
""",
            encoding="utf-8",
        )
        (source / "sample_upgrade_settings.ini").write_text(
            """[sample_upgrade]
upgrade_mode = 全包升级
username = current-upgrade-user
password = current-upgrade-password
firmware_path = C:/current-pc/firmware.bin
parameter_initial_username = current-parameter-user
parameter_initial_password = current-parameter-password
parameter_table_path = C:/current-pc/parameters.xlsx
""",
            encoding="utf-8",
        )
        template = """[telnet]
request_url = http://192.168.1.1
port = 23
user = current-dut-user
password = current-dut-password
[order]
echo ready = ready
[connect_wifi]
choose_wireless_card = 1
wireless_card_name = current-wifi-adapter
[project_info]
project_name = current-project
software_version = current-version
internal_software_version = current-internal-version
onu_compile_time = current-compile-time
"""
        (source / "test_project_config.default.ini").write_text(template, encoding="utf-8")
        (source / "test_project_config.ini").write_text(template, encoding="utf-8")

    @staticmethod
    def _load(path: Path) -> configparser.RawConfigParser:
        parser = configparser.RawConfigParser(interpolation=None)
        parser.read(path, encoding="utf-8")
        return parser

    def test_portable_config_removes_secrets_and_machine_bindings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            destination = root / "portable"
            self._write_source_configs(source)

            created = create_portable_config(source, destination)

            self.assertEqual({path.name for path in created}, set(PORTABLE_CONFIG_NAMES))
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                set(PORTABLE_CONFIG_NAMES),
            )
            bundled_text = "\n".join(path.read_text(encoding="utf-8") for path in created)
            for forbidden in (
                "current-webhook",
                "current-dingtalk-secret",
                "current-remote-id",
                "current@example.invalid",
                "current-olt-user",
                "current-olt-password",
                "current-upgrade-user",
                "current-upgrade-password",
                "C:/current-pc",
                "current-dut-user",
                "current-dut-password",
                "current-vlan-adapter",
                "current-wifi-adapter",
                "COM102",
                "COM13",
                "192.0.2.",
                "current-project",
            ):
                self.assertNotIn(forbidden, bundled_text)

            main = self._load(destination / "config.ini")
            self.assertEqual(main.get("dingtalk_config", "dingtalk_flag"), "0")
            self.assertEqual(main.get("dingtalk_config", "webhook"), "")
            self.assertEqual(main.get("remote_config", "remote_identification_code"), "")
            self.assertEqual(main.get("Emails", "emails"), "")

            network = self._load(destination / "network_card_ip.ini")
            self.assertEqual(network.sections(), ["power_supply"])
            self.assertEqual(network.get("power_supply", "serial_port"), "")

            onu = self._load(destination / "onu_registration.ini")
            self.assertEqual(onu.get("onu_registration", "c600_password"), "")
            self.assertEqual(onu.get("onu_registration", "c600_source_ip"), "")
            self.assertEqual(onu.get("onu_registration", "c600_onu_id"), "")
            self.assertEqual(onu.get("onu_registration", "c600_services"), "1,170")

            upgrade = self._load(destination / "sample_upgrade_settings.ini")
            self.assertEqual(upgrade.get("sample_upgrade", "firmware_path"), "")
            self.assertEqual(upgrade.get("sample_upgrade", "parameter_table_path"), "")

            project = self._load(destination / "test_project_config.ini")
            self.assertEqual(project.get("telnet", "user"), "")
            self.assertEqual(project.get("telnet", "password"), "")
            self.assertEqual(project.get("connect_wifi", "wireless_card_name"), "")
            self.assertEqual(project.get("project_info", "project_name"), "")
            self.assertEqual(project.get("order", "echo ready"), "ready")

    def test_destination_cannot_replace_live_source_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "config"
            self._write_source_configs(source)

            with self.assertRaisesRegex(ValueError, "不能与当前运行配置目录相同"):
                create_portable_config(source, source)

    def test_nonempty_destination_is_refused_without_deleting_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            destination = root / "portable"
            self._write_source_configs(source)
            destination.mkdir()
            marker = destination / "keep-me.txt"
            marker.write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "输出目录必须为空"):
                create_portable_config(source, destination)

            self.assertEqual(marker.read_text(encoding="utf-8"), "existing")


class PortableReleaseBuildScriptTests(unittest.TestCase):
    def test_tkinter_hook_uses_runtime_expected_tcl_and_tk_roots(self):
        hook_path = PROJECT_ROOT / "line_check_assistant" / "packaging_hooks" / "hook-_tkinter.py"

        hook_globals = runpy.run_path(str(hook_path))
        datas = hook_globals["datas"]

        self.assertEqual([destination for _source, destination in datas], ["tcl", "tk"])
        self.assertTrue((Path(datas[0][0]) / "init.tcl").is_file())
        self.assertTrue((Path(datas[1][0]) / "tk.tcl").is_file())

    def test_build_script_creates_directory_zip_hash_and_never_launches_exe(self):
        script = (PROJECT_ROOT / "build_line_check_assistant.ps1").read_text(encoding="utf-8")

        self.assertIn("LineCheckAssistant_portable", script)
        self.assertIn("create_portable_config.py", script)
        self.assertIn("Compress-Archive", script)
        self.assertIn("LineCheckAssistant.exe.sha256.txt", script)
        self.assertIn("PORTABLE_README.txt", script)
        self.assertIn("'tcl\\\\init.tcl'", script)
        self.assertIn("'tk\\\\tk.tcl'", script)
        self.assertNotIn("Start-Process", script)


if __name__ == "__main__":
    unittest.main()

import configparser
import os
import runpy
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
    def test_standard_environment_rejects_global_python_or_wrong_platform(self):
        from scripts import check_build_environment as checker
        with patch.object(sys, "platform", "win32"), patch.object(sys, "version_info", (3, 9, 10)), patch.object(sys, "prefix", sys.base_prefix):
            with self.assertRaisesRegex(ValueError, "isolated"):
                checker.check_environment()
        with patch.object(sys, "version_info", (3, 12, 0)):
            with self.assertRaisesRegex(ValueError, "3.9.10"):
                checker.check_environment()

    def test_standard_environment_checks_lock_extras_and_hidden_heavy_modules(self):
        from scripts import check_build_environment as checker
        expected = checker.locked_versions(PROJECT_ROOT)
        installed = [types.SimpleNamespace(metadata={"Name": name}, version=version) for name, version in expected.items()]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
            with patch.object(sys, "platform", "win32"), patch.object(sys, "version_info", (3, 9, 10)), patch.object(sys, "prefix", str(root)), patch.object(checker.importlib.metadata, "distributions", return_value=installed), patch.object(checker.importlib.util, "find_spec", return_value=None) as find_spec:
                self.assertEqual(checker.check_environment()["excluded_modules"], ["numpy", "lxml", "PyQt5"])
                installed[0].version = "0.0.0"
                with self.assertRaisesRegex(ValueError, "dependency drift"):
                    checker.check_environment()
                installed[0].version = expected[checker.normalized(installed[0].metadata["Name"])]
                installed.append(types.SimpleNamespace(metadata={"Name": "unexpected-extra"}, version="1"))
                with self.assertRaisesRegex(ValueError, "Unexpected packages"):
                    checker.check_environment()
                installed.pop()
                find_spec.return_value = object()
                with self.assertRaisesRegex(ValueError, "heavy dependencies"):
                    checker.check_environment()
                find_spec.return_value = None
                (root / "pyvenv.cfg").write_text("include-system-site-packages = true\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "site-packages"):
                    checker.check_environment()

    def test_standard_spec_uses_relocated_paths_and_accepted_slim_profile(self):
        from scripts import check_build_environment as checker
        captured = {}
        def analysis(*args, **kwargs):
            captured["analysis"] = (args, kwargs)
            return types.SimpleNamespace(pure=[], zipped_data=[], scripts=[], binaries=[], zipfiles=[], datas=kwargs["datas"])
        def executable(*args, **kwargs):
            captured["exe"] = kwargs
        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_submodules = lambda name: [name + ".fixture"]
        modules = {name: types.ModuleType(name) for name in ("PyInstaller", "PyInstaller.utils")}
        modules["PyInstaller.utils.hooks"] = hooks
        with tempfile.TemporaryDirectory() as temp:
            relocated = Path(temp) / "工程 副本 with spaces"
            spec_dir = relocated / "line_check_assistant/packaging_specs"
            spec_dir.mkdir(parents=True)
            relocated = relocated.resolve()
            spec_dir = spec_dir.resolve()
            work = relocated / "build/check/LineCheckAssistant"
            spec = spec_dir / "LineCheckAssistant.spec"
            spec.write_bytes((PROJECT_ROOT / "line_check_assistant/packaging_specs/LineCheckAssistant.spec").read_bytes())
            with patch.dict(sys.modules, modules), patch.object(sys, "path", sys.path.copy()), patch.object(checker, "check_environment", return_value={}) as verify:
                runpy.run_path(str(spec), init_globals={"SPECPATH": str(spec_dir), "workpath": str(work), "Analysis": analysis, "PYZ": lambda *a, **k: "pyz", "EXE": executable})
            verify.assert_called_once_with(relocated)
            args, settings = captured["analysis"]
            self.assertEqual(args[0], [str(relocated / "run_line_check_assistant.py")])
            self.assertEqual(settings["pathex"], [str(relocated), str(relocated / "Auto_power_on_off_tool")])
            self.assertEqual(settings["excludes"], ["numpy", "lxml", "PyQt5"])
            self.assertEqual(settings["hookspath"], [str(relocated / "line_check_assistant/packaging_hooks")])
            self.assertIn((str(work / "BUILD_INFO.txt"), "."), settings["datas"])
            self.assertIn((str(relocated / "line_check_assistant/packaging_assets/VERSION_INFO.txt"), "."), settings["datas"])
            self.assertEqual(captured["exe"]["icon"], [str(relocated / "assets/icons/line_check_assistant_network_topology_v1.ico")])
            self.assertFalse(captured["exe"]["console"])
            self.assertFalse(captured["exe"]["upx"])
            self.assertIn("PyQt5", (work / "BUILD_INFO.txt").read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "Windows packaging entry")
    def test_build_rejects_output_or_cleanup_paths_outside_generated_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            outside = Path(temp)
            sentinel = outside / "keep.txt"
            sentinel.write_text("keep existing files", encoding="utf-8")
            for option, message in (("-WorkDirectory", "WorkDirectory must"), ("-OutputDirectory", "OutputDirectory must")):
                with self.subTest(option=option):
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         str(PROJECT_ROOT / "build_line_check_assistant.ps1"), option, str(outside)],
                        cwd=PROJECT_ROOT, capture_output=True, timeout=30,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, (result.stdout + result.stderr).decode("utf-8", errors="replace"))
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep existing files")
                    self.assertEqual(sorted(p.name for p in outside.iterdir()), ["keep.txt"])

    def test_excel_and_real_legacy_imports_work_without_optional_heavy_packages(self):
        # Run fresh so the full suite's cached imports cannot hide a dependency.
        # Neither hardware constructors nor the old GUI are invoked.
        probe = textwrap.dedent(r'''
            import importlib.abc
            import sys
            import tempfile
            from pathlib import Path
            from types import SimpleNamespace

            class BlockOptional(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] in {'numpy', 'lxml', 'PyQt5'}:
                        raise ModuleNotFoundError(fullname)
            sys.meta_path.insert(0, BlockOptional())

            from line_check_assistant.app import main
            from src.core.sample_parameter_table import load_parameter_records, save_parameter_records_xlsx
            from src.models import SampleParameterRecord
            records = [SampleParameterRecord(vlan='vlan101', values={'SN': '001234567890', '2.4G SSID': 'wifi_24_fixture'})]
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'parameters.xlsx'
                save_parameter_records_xlsx(path, records)
                loaded = load_parameter_records(path)
                assert loaded[0].vlan == 'vlan101'
                assert loaded[0].values['SN'] == '001234567890'
                assert loaded[0].values['2.4G SSID'] == 'wifi_24_fixture'
            loaded = load_parameter_records(Path('tests/fixtures/slim_parameters.xls'))
            assert loaded[0].values['SN'] == '001234567890'
            assert loaded[0].values['2.4G SSID'] == 'wifi_24_fixture'
            import openpyxl
            assert not openpyxl.LXML
            assert not openpyxl.compat.numbers.NUMPY

            from src.services.legacy_power_test_service import _install_headless_legacy_stubs
            request = SimpleNamespace(connect_wifi_enable=True, wifi_test_2g_enable=True,
                wifi_test_5g_enable=True, wifi_auth_mode='WPA2-PSK', wifi_cipher='AES',
                product_solution='openwrt', wifi_choose_wireless_card=False,
                wifi_wireless_card_name='')
            _install_headless_legacy_stubs(request)
            sys.path.insert(0, str(Path('Auto_power_on_off_tool').resolve()))
            from test_case.powe_on_off_telnet import PowerOnOffTelnet
            from test_case.power_on_off_ssh import PowerOnOffSsh
            from test_case.wifi_connect_case import OpenWrtGetWifiInfo
            from common.wifi_connect import WifiConnect
            import pywifi
            import comtypes
            import certifi
            import ssl
            import paramiko
            ssl.create_default_context(cafile=certifi.where())
            key = paramiko.RSAKey.generate(1024)
            signature = key.sign_ssh_data(b'slim dependency probe')
            assert key.verify_ssh_sig(b'slim dependency probe', paramiko.Message(signature.asbytes()))
            for worker_type in (PowerOnOffTelnet, PowerOnOffSsh, OpenWrtGetWifiInfo):
                worker = object.__new__(worker_type)
                messages = []
                worker.show_signal[str].connect(messages.append)
                worker.show_signal[str].emit('headless signal ready')
                assert messages == ['headless signal ready']
            assert 'PyQt5.QtWidgets' not in sys.modules
            assert 'Auto_Power_On_Off_Tool' not in sys.modules
            assert 'numpy' not in sys.modules and 'lxml' not in sys.modules
            print('SLIM_SOURCE_PATHS_OK')
        ''')
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SLIM_SOURCE_PATHS_OK", result.stdout)

    def test_tkinter_hook_uses_runtime_expected_tcl_and_tk_roots(self):
        hook_path = PROJECT_ROOT / "line_check_assistant" / "packaging_hooks" / "hook-_tkinter.py"

        hook_globals = runpy.run_path(str(hook_path))
        datas = hook_globals["datas"]

        self.assertEqual([destination for _source, destination in datas], ["tcl", "tk", "_tcl_data", "_tk_data"])
        for source, destination in datas:
            expected = "init.tcl" if destination in ("tcl", "_tcl_data") else "tk.tcl"
            self.assertTrue((Path(source) / expected).is_file())

    def test_build_script_creates_directory_zip_hash_and_never_launches_exe(self):
        script = (PROJECT_ROOT / "build_line_check_assistant.ps1").read_text(encoding="utf-8")
        icon_path = (
            PROJECT_ROOT
            / "assets"
            / "icons"
            / "line_check_assistant_network_topology_v1.ico"
        )

        self.assertTrue(icon_path.is_file())
        self.assertEqual(icon_path.read_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertIn("line_check_assistant_network_topology_v1.ico", script)
        self.assertIn("$specPath", script)
        self.assertIn("prepare_build_environment.ps1", script)
        self.assertLess(script.index('"scripts\\verify_baseline.py"'), script.index("-m PyInstaller"))
        self.assertIn("LineCheckAssistant_portable", script)
        self.assertIn("create_portable_config.py", script)
        self.assertIn("Compress-Archive", script)
        self.assertIn("LineCheckAssistant.exe.sha256.txt", script)
        self.assertIn("LineCheckAssistant_portable.zip.sha256.txt", script)
        self.assertIn("Get-FileHash -LiteralPath $portableZip -Algorithm SHA256", script)
        self.assertIn('-Value "$zipHash *LineCheckAssistant_portable.zip"', script)
        self.assertIn("PORTABLE_README.txt", script)
        self.assertIn("'tcl\\\\init.tcl'", script)
        self.assertIn("'tk\\\\tk.tcl'", script)
        self.assertIn("'_tcl_data\\\\init.tcl'", script)
        self.assertIn("'_tk_data\\\\tk.tcl'", script)
        self.assertNotIn("Start-Process", script)


if __name__ == "__main__":
    unittest.main()

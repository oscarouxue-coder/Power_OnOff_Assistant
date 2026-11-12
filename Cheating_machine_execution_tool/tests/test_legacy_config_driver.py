"""旧业务配置原文读取回归；只访问临时文件，不连接设备。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest


_CONFIG_DRIVER_PATH = (
    Path(__file__).resolve().parents[1]
    / "Auto_power_on_off_tool/config/config_driver.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "_legacy_config_driver_test", _CONFIG_DRIVER_PATH
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
OperationConfig = _MODULE.OperationConfig


class LegacyConfigDriverTests(unittest.TestCase):
    PASSWORDS = ("sample%3n", "sample%%", "%(name)s", "ordinary-password", "")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_profile(self, password, filename="测试方案.ini"):
        path = self.root / filename
        path.write_text(
            "[telnet]\nuser = operator\nname = expanded\n"
            f"password = {password}\n",
            encoding="utf-8",
        )
        return path

    def test_raw_password_can_be_read_without_prior_regular_read(self):
        for password in self.PASSWORDS:
            with self.subTest(password=password):
                path = self.write_profile(password)
                config = OperationConfig()
                self.assertEqual(
                    config.read_ini_raw("telnet", "password", path=str(path)),
                    password,
                )

    def test_raw_password_after_username_read_preserves_literal_characters(self):
        for password in self.PASSWORDS:
            with self.subTest(password=password):
                path = self.write_profile(password)
                config = OperationConfig()
                self.assertEqual(
                    config.read_ini("telnet", "user", path=str(path)), "operator"
                )
                self.assertEqual(
                    config.read_ini_raw("telnet", "password", path=str(path)),
                    password,
                )

    def test_raw_password_follows_requested_profile_after_switch(self):
        first = self.write_profile("first-password", "first.ini")
        second = self.write_profile("second%3n", "second.ini")
        config = OperationConfig()
        config.read_ini("telnet", "user", path=str(first))
        for path, password in (
            (first, "first-password"), (second, "second%3n"),
            (first, "first-password"),
        ):
            with self.subTest(profile=path.name):
                self.assertEqual(
                    config.read_ini_raw("telnet", "password", path=str(path)),
                    password,
                )

    def test_regular_read_keeps_existing_interpolation_behavior(self):
        path = self.write_profile("%(name)s")
        config = OperationConfig()
        self.assertEqual(
            config.read_ini("telnet", "password", path=str(path)), "expanded"
        )


if __name__ == "__main__":
    unittest.main()

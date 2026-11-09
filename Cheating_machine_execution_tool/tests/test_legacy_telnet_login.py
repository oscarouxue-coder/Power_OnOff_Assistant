"""使用真实旧客户端方法和模拟Telnet响应验证登录时序，不构造网络连接。"""
import ast
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call


ROOT = Path(__file__).resolve().parent.parent


class LegacyTelnetLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 旧客户端依赖旧GUI模块；仅提取完整原方法，避免导入时启动日志/硬件依赖。
        path = ROOT / "Auto_power_on_off_tool/clients/telnet_client.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TelnetClient")
        methods = [node for node in client.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"selected_scheme_path", "begin_login"}]
        cls.method_code = compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec")

    def client(self, responses=(), no_auth=0, prompt="#"):
        clock = SimpleNamespace(sleep=Mock(), strftime=Mock(return_value="fixture-time"),
                                localtime=Mock(), time=Mock(return_value=0))
        namespace = {"time": clock}
        exec(self.method_code, namespace)
        context = SimpleNamespace(
            tn=Mock(), logger=Mock(), source="192.0.2.1",
            input_user_flag="login:", input_password_flag="Password:",
            login_success_flag=prompt, telnet_no_user_password_flag=no_auth,
            config_file_path="fixture.ini", cf=Mock(),
        )
        context.tn.read_until.side_effect = responses
        return context, clock, namespace

    def login(self, context, methods):
        with redirect_stdout(io.StringIO()):
            return methods["begin_login"](context, "test-user", "test-password", io.BytesIO())

    def test_config_load_never_reads_deprecated_key(self):
        for old_value in (None, "0", "1", "invalid"):
            with self.subTest(old_value=old_value):
                context, _clock, methods = self.client()
                values = {"input_user_flag": "login:", "input_password_flag": "Password:",
                          "login_success_flag": "#", "command_fail_retry_interval_time": "60",
                          "telnet_no_user_password_flag": "0"}
                if old_value is not None:
                    values["telnet_need_enter_password_flag"] = old_value
                context.cf.read_ini.side_effect = lambda _section, key, **_kw: values[key]
                self.assertTrue(methods["selected_scheme_path"](context))
                self.assertNotIn("telnet_need_enter_password_flag",
                                 [item.args[1] for item in context.cf.read_ini.call_args_list])
                self.assertEqual(context.telnet_no_user_password_flag, 0)

    def test_normal_login_ignores_stale_flag_and_sends_only_credentials(self):
        for old_value in (0, 1, "invalid"):
            with self.subTest(old_value=old_value):
                context, clock, methods = self.client((b"login:", b"Password:", b"#"))
                context.telnet_need_enter_password_flag = old_value
                self.assertTrue(self.login(context, methods))
                self.assertEqual(context.tn.write.call_args_list,
                                 [call(b"test-user\n"), call(b"test-password\n")])
                self.assertEqual(context.tn.read_until.call_args_list,
                                 [call(b"login:", timeout=150), call(b"Password:", timeout=10),
                                  call(b"#", timeout=20)])
                context.tn.read_very_eager.assert_not_called()
                self.assertEqual(clock.sleep.call_args_list, [call(0.5)] * 3)

    def test_no_auth_success_keeps_single_enter_without_credentials(self):
        context, clock, methods = self.client((b"router#",), no_auth=1)
        context.telnet_need_enter_password_flag = 1
        self.assertTrue(self.login(context, methods))
        context.tn.write.assert_called_once_with(b"\n")
        context.tn.read_until.assert_called_once_with(b"#", timeout=3)
        clock.sleep.assert_not_called()

    def test_no_auth_failure_falls_back_without_extra_probe(self):
        context, _clock, methods = self.client((b"banner", b"login:", b"Password:", b"#"), no_auth=1)
        context.telnet_need_enter_password_flag = 1
        self.assertTrue(self.login(context, methods))
        self.assertEqual(context.tn.write.call_args_list,
                         [call(b"\n"), call(b"test-user\n"), call(b"test-password\n")])
        context.tn.read_very_eager.assert_not_called()

    def test_greater_than_prompt_preserves_post_login_command_and_wait(self):
        for command in ("sh", ""):
            with self.subTest(command=command):
                context, clock, methods = self.client((b"login:", b"Password:", b">"), prompt=">")
                context.telnet_need_enter_password_flag = 1
                context.cf.read_ini.return_value = command
                self.assertTrue(self.login(context, methods))
                self.assertEqual(context.tn.write.call_args_list,
                                 [call(b"test-user\n"), call(b"test-password\n"), call(command.encode() + b"\n")])
                self.assertEqual(clock.sleep.call_args_list, [call(0.5)] * 4)

    def test_prompt_failures_do_not_send_later_credentials_or_commands(self):
        for responses, expected in (((b"unexpected",), []),
                                    ((b"login:", b"unexpected"), [call(b"test-user\n")]),
                                    ((b"login:", b"Password:", b"Login incorrect"),
                                     [call(b"test-user\n"), call(b"test-password\n")])):
            with self.subTest(responses=responses):
                context, _clock, methods = self.client(responses)
                context.telnet_need_enter_password_flag = 1
                self.assertFalse(self.login(context, methods))
                self.assertEqual(context.tn.write.call_args_list, expected)


if __name__ == "__main__":
    unittest.main()

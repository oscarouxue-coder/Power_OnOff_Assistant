"""登录后指令确认摘要使用页面快照或实际选定方案，不连接设备。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.pipeline_window import PipelineWindow
from line_check_assistant.test_item_config_store import TelnetSettings
from src.services import telnet_post_login_confirmation_service as confirmation_service
from src.ui.test_item_pretest_controls import PretestControls


def channel() -> ChannelConfig:
    return ChannelConfig(
        "channel_1", vlan_name="vlan101", network_card_ip="192.168.1.101",
        device_manage_ip="192.168.1.1", enabled=True,
    )


def make_tool_root(base: Path, command: str = "busybox sh", flag: str = ">") -> Path:
    tool_root = base / "Auto_power_on_off_tool"
    config_dir = tool_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.ini").write_text(
        "[config]\n默认方案 = test_project_config.ini\n现场方案 = selected.ini\n"
        "[ui_defaults]\ncommunication_method = telnet\ntelnet_enable = 0\n"
        "baud_rate = 9600\nselected_profile = 现场方案\nstartup_time = 0\n"
        "interval_time = 0\nnumber_of_tests = 1\nwait_command_done = 0\n",
        encoding="utf-8",
    )
    (config_dir / "network_card_ip.ini").write_text(
        "[power_supply]\nserial_port = COM3\n", encoding="utf-8",
    )
    (config_dir / "test_project_config.ini").write_text(
        "[telnet]\nlogin_success_flag = >\nlogin_after_input_str = wrong-default\n",
        encoding="utf-8",
    )
    (config_dir / "selected.ini").write_text(
        f"[telnet]\nlogin_success_flag = {flag}\nlogin_after_input_str = {command}\n"
        "[project_info]\nsoftware_version = a\ninternal_software_version = b\nonu_compile_time = c\n",
        encoding="utf-8",
    )
    return tool_root


def pipeline_context(tool_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(), enabled_channels=[channel()], legacy_tool_root=tool_root,
        sample_upgrade_settings=SimpleNamespace(upgrade_mode="页面升级"),
    )


class PretestConfirmationTests(unittest.TestCase):
    def make_controls(self, telnet: TelnetSettings) -> PretestControls:
        request = SimpleNamespace(channels=[channel()], telnet=telnet,
                                  order=SimpleNamespace(items=["first", "second"]))
        with patch("src.ui.test_item_pretest_controls.ttk"):
            return PretestControls(Mock(), capture_request=Mock(return_value=request), log=Mock())

    def declined_confirmation(self, telnet: TelnetSettings) -> str:
        controls = self.make_controls(telnet)
        with patch("src.ui.test_item_pretest_controls.messagebox.askyesno", return_value=False) as confirm, \
             patch("src.ui.test_item_pretest_controls.threading.Thread") as worker:
            controls.start()
        worker.assert_not_called()
        self.assertFalse(controls.running)
        self.assertIn("操作员取消", controls.log.call_args.args[0])
        return confirm.call_args.args[1]

    def test_current_page_command_is_shown_before_worker_start(self):
        text = self.declined_confirmation(TelnetSettings(
            login_success_flag=">", login_after_input_str="busybox sh",
        ))
        self.assertIn("busybox sh", text)
        self.assertIn("等待 1 秒", text)
        self.assertIn("全部 2 条命令", text)
        self.assertIn("未保存的页面内容", text)

    def test_empty_command_explicitly_confirms_enter(self):
        text = self.declined_confirmation(TelnetSettings(
            login_success_flag=">", login_after_input_str="",
        ))
        self.assertIn("仅回车（配置为空）", text)
        self.assertIn("等待 1 秒", text)

    def test_other_success_flag_confirms_skipping(self):
        text = self.declined_confirmation(TelnetSettings(
            login_success_flag="#", login_after_input_str="do-not-send",
        ))
        self.assertIn("跳过", text)
        self.assertNotIn("do-not-send", text)
        self.assertNotIn("等待 1 秒", text)


class LegacyPowerConfirmationServiceTests(unittest.TestCase):
    def test_empty_versions_show_skip_without_login_command(self):
        for value in ("", " \t "):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                tool_root = make_tool_root(Path(temporary))
                path = tool_root / "config/selected.ini"
                path.write_text(
                    "[telnet]\nlogin_success_flag = >\nlogin_after_input_str = must-not-send\n"
                    f"[project_info]\nproject_name = name\nsoftware_version = {value}\n"
                    f"internal_software_version = {value}\nonu_compile_time = {value}\n",
                    encoding="utf-8")
                text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
                self.assertIn("三项版本基准均为空，跳过开始前版本校验", text)
                self.assertNotIn("must-not-send", text)
                self.assertNotIn("等待 1 秒", text)

    def test_partial_versions_describe_missing_fields_and_block_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            (tool_root / "config/selected.ini").write_text(
                "[project_info]\nsoftware_version = a\n", encoding="utf-8")
            text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
        self.assertIn("内部软件版本、ONU 软件编译时间", text)
        self.assertIn("未启动开关机测试", text)
        self.assertNotIn("执行三项版本预检", text)

    def test_selected_profile_is_used_and_configuration_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            before = {p.name: p.read_bytes() for p in (tool_root / "config").iterdir()}
            text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
            after = {p.name: p.read_bytes() for p in (tool_root / "config").iterdir()}
        self.assertIn("现场方案", text)
        self.assertIn("busybox sh", text)
        self.assertIn("等待 1 秒", text)
        self.assertIn("执行三项版本预检", text)
        self.assertNotIn("wrong-default", text)
        self.assertEqual(before, after)

    def test_empty_and_nonmatching_flag_follow_selected_profile(self):
        for command, flag, expected in [("", ">", "仅回车（配置为空）"),
                                        ("do-not-send", "#", "跳过")]:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temporary:
                tool_root = make_tool_root(Path(temporary), command, flag)
                text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
                self.assertIn(expected, text)
                self.assertNotIn("wrong-default", text)
                if flag != ">":
                    self.assertNotIn(command, text)

    def assert_config_failure(self, text: str):
        self.assertIn("配置未能读取", text)
        self.assertIn("版本预检报错并停止", text)
        self.assertIn("不会改用默认", text)
        self.assertNotIn("wrong-default", text)

    def test_missing_selected_profile_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            (tool_root / "config" / "selected.ini").unlink()
            text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
        self.assert_config_failure(text)

    def test_unreadable_profile_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            selected_path = (tool_root / "config" / "selected.ini").resolve()
            original_open = Path.open

            def open_except_selected(path, *args, **kwargs):
                if path == selected_path:
                    raise PermissionError("private-password")
                return original_open(path, *args, **kwargs)

            with patch("pathlib.Path.open", new=open_except_selected):
                text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
        self.assert_config_failure(text)
        self.assertNotIn("private-password", text)

    def test_parse_failure_does_not_expose_configuration_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            (tool_root / "config" / "selected.ini").write_text("private-password", encoding="utf-8")
            text = confirmation_service.describe_legacy_power_telnet_post_login(pipeline_context(tool_root))
        self.assert_config_failure(text)
        self.assertNotIn("private-password", text)


class PipelineConfirmationTests(unittest.TestCase):
    def test_empty_versions_confirm_skip_and_keep_power_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool_root = make_tool_root(Path(temporary))
            (tool_root / "config/selected.ini").write_text("[project_info]\n", encoding="utf-8")
            text = self.confirm_without_starting(pipeline_context(tool_root), {"legacy_power_test"})
        self.assertIn("跳过开始前版本校验", text)
        self.assertIn("下发全通道断电指令", text)
        self.assertNotIn("等待 1 秒", text)

    def confirm_without_starting(self, ctx, selected):
        window = object.__new__(PipelineWindow)
        window.app = ctx.app
        window.window = Mock()
        window._running_thread = None
        window._check_vars = {code: Mock(get=Mock(return_value=True)) for code in selected}
        window._unattended_execution_var = Mock(get=Mock(return_value=False))
        window._build_context = Mock(return_value=ctx)
        window._set_running_ui = Mock()
        statuses = {code: SimpleNamespace(ready=True) for code in selected}
        with patch("line_check_assistant.pipeline_window.compute_all_subtask_statuses", return_value=statuses), \
             patch("line_check_assistant.pipeline_window.messagebox.askyesno", return_value=False) as confirm, \
             patch("line_check_assistant.pipeline_window.threading.Thread") as worker:
            window._on_start()
        worker.assert_not_called()
        window._set_running_ui.assert_not_called()
        window.window.withdraw.assert_not_called()
        return confirm.call_args.args[1]

    def test_legacy_confirmation_includes_selected_profile_command_and_can_cancel(self):
        with tempfile.TemporaryDirectory() as temporary:
            ctx = pipeline_context(make_tool_root(Path(temporary)))
            text = self.confirm_without_starting(ctx, {"legacy_power_test"})
        self.assertIn("开关机版本预检", text)
        self.assertIn("现场方案", text)
        self.assertIn("busybox sh", text)
        self.assertIn("等待 1 秒", text)
        self.assertIn("下发全通道断电指令", text)
        self.assertNotIn("wrong-default", text)

    def test_unselected_legacy_task_does_not_load_or_describe_its_profile(self):
        with patch("line_check_assistant.pipeline_window.describe_legacy_power_telnet_post_login") as describe:
            text = self.confirm_without_starting(pipeline_context(Path("unused")), {"env_check"})
        describe.assert_not_called()
        self.assertNotIn("登录后指令", text)


if __name__ == "__main__":
    unittest.main()

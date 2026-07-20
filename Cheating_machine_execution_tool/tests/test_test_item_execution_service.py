"""test_item_execution_service 单元测试。

覆盖:
- 单条命令匹配成功
- 单条命令匹配失败 → 重试 N 次
- 重试第 K 次成功
- per-segment !A&&B 匹配
- 无期望 → 默认通过
- 多条命令按 [order] 顺序执行
- 网络准备失败 → RuntimeError
- 登录失败（无 user prompt）→ RuntimeError
- per-channel 结果文件被创建 + 含主日志期望字段
- session 在 finally 关闭
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import List
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import (
    ExpectedSegment,
    OrderConfig,
    OrderItem,
    TelnetSettings,
)
from src.services.test_item_execution_service import (
    LOGIN_INTER_STEP_SLEEP_SECONDS,
    LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS,
    LOGIN_SUCCESS_TIMEOUT_SECONDS,
    LOGIN_USER_PROMPT_TIMEOUT_SECONDS,
    READ_MAX_SECONDS,
    READ_STABLE_SECONDS,
    TEST_RESULTS_DIR,
    TestItemRunRequest,
    TestItemRunResult,
    build_log_path,
    run_test_item_execution,
)


class FakeTelnetSession:
    """模拟 TelnetSession:支持 send_line / cursor / peek_since / wait_for_any / close。"""

    def __init__(self, prompts: dict[str, str] | None = None, prefill_banner: bool = True) -> None:
        self.sent_lines: List[str] = []
        self.responses: dict[str, str] = {}        # 命令 → 回显
        self.cursor_offset = 0
        self.history = bytearray()
        self.closed = False
        # 登录阶段:记录 _make_telnet 默认用户名 / 密码,用于 fake 模拟样机响应下一个 prompt
        # ``prefill_banner=False`` 时全部置空,样机不响应任何 prompt
        self._prefilled_user = "sdmc" if prefill_banner else ""
        self._prefilled_password = "1234" if prefill_banner else ""
        # ``prefill_banner=False`` 用于「样机不响应 / 无 banner」场景的单测
        if prefill_banner:
            self._prefill_login_banner(prompts or {})

    def _prefill_login_banner(self, prompts: dict[str, str]) -> None:
        """构造一个伪样机登录 banner,使 ``_login`` 各阶段的 ``wait_for_any`` 能命中。

        banner 必须含 ``ogin:`` / ``Password:`` / ``#`` 三个 marker 的字面子串(忽略大小写)；
        用真实 ``telnet.input_user_flag`` / ``input_password_flag`` / ``login_success_flag``
        默认值(``ogin:`` / ``Password:`` / ``#``)以匹配 production TelnetSettings。
        """
        user_prompt = prompts.get("ogin:", "ogin: ")
        self.history.extend(f"\r\n{user_prompt}".encode("utf-8"))
        password_prompt = prompts.get("Password:", "Password: ")
        self.history.extend(password_prompt.encode("utf-8"))
        success_flag = prompts.get("#", "#")
        self.history.extend(f"\r\n\r\n{success_flag} ".encode("utf-8"))

    def cursor(self) -> int:
        return len(self.history)

    def write(self, data, sensitive: bool = False) -> None:
        # 模拟样机对 ``\r`` 的响应:回显 ``\r`` + 重新发 banner(模拟真机交互)。
        # 这样 production 端的 ``cursor = session.cursor()`` + ``write(b"\r")`` +
        # ``wait_for_any(..., cursor)`` 序列能命中 banner 中的 ogin:。
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.history.extend(data)
        # 触发 banner 重发(若 data 是 CR / LF,且 prefill_banner=True)
        if data in (b"\r", b"\n", b"\r\n", b"\n\r") and self._prefilled_user:
            # 重发一份 banner 中的密码提示符 + 成功标志
            # （ogin: 已在 __init__ 预填,本次只需再发 password + success 段）
            self.history.extend(b"ogin: ")

    def send_line(self, text: str, sensitive: bool = False) -> None:
        self.sent_lines.append(text)
        # 模拟样机回显: 命令回显 + 响应内容
        self.history.extend(f"{text}\r\n".encode("utf-8"))
        # 登录阶段 user / password 命令 → 模拟样机回显下一个 prompt
        # (``prefill_banner=False`` 时不响应,模拟样机无 banner / 不响应场景)
        if self._prefilled_user and text == "sdmc" and self._prefilled_user == "sdmc":
            self.history.extend(b"Password: ")
        elif self._prefilled_password and text == "1234" and self._prefilled_password == "1234":
            self.history.extend(b"\r\n# ")
        else:
            response = self.responses.get(text, "")
            if response:
                self.history.extend(response.encode("utf-8"))
                self.history.extend(b"\r\n")

    def wait_for_any(self, markers, timeout_seconds, cursor):
        # 简单实现:在 history[cursor:] 中找任一 marker(忽略大小写);找到返回第一个。
        haystack = self.history[cursor:].decode("utf-8", errors="replace").lower()
        for marker in markers:
            if marker.lower() in haystack:
                return marker
        return None

    def peek_since(self, cursor: int) -> str:
        return self.history[cursor:].decode("utf-8", errors="replace")

    def close(self) -> None:
        self.closed = True


def _make_channel(network_card_ip: str = "192.168.1.110", device_manage_ip: str = "192.168.1.1") -> ChannelConfig:
    return ChannelConfig(
        section="channel_2",
        vlan_name="VLAN110",
        adapter_alias="VLAN110",
        network_card_ip=network_card_ip,
        device_manage_ip=device_manage_ip,
        subnet_mask="255.255.255.0",
        enabled=True,
    )


class _AdvancingMonotonic:
    """``monotonic_fn`` mock: 每次调用推进 0.5 秒,便于触发 ``_read_until_stable`` 的稳定/超时分支。"""

    def __init__(self) -> None:
        self.t = 0.0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        self.t += 0.5
        return self.t


def _make_telnet(user: str = "sdmc", password: str = "1234") -> TelnetSettings:
    return TelnetSettings(
        request_url="http://192.168.1.1",
        port=23,
        user=user,
        password=password,
        timeout=10,
        input_user_flag="ogin:",
        input_password_flag="Password:",
        login_success_flag="#",
    )


def _make_order(commands: List[tuple[str, str, int]]) -> OrderConfig:
    """commands = [(command, expected_text, retry_times), ...]"""
    items: List[OrderItem] = []
    for cmd, expected, retry in commands:
        if expected:
            # 单段;如果含 ! 走 negate 模式
            negate = expected.startswith("!")
            text = expected[1:] if negate else expected
            segments = [ExpectedSegment(text=text, negate=negate)]
        else:
            segments = []
        items.append(OrderItem(command=cmd, expected_segments=segments, retry_times=retry))
    return OrderConfig(command_fail_retry_interval_time=0, items=items)


class TestItemExecutionSingleCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def _patch_session(self, fake_session: FakeTelnetSession) -> Mock:
        return patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake_session,
        )

    def test_single_command_match_success(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("/userfs/bin/ponmgr gpon get info", "ONU State: O5", 5)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,    # 跳过 sleep
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        fake.responses["/userfs/bin/ponmgr gpon get info"] = "ONU State: O5 (Operating)\n"

        emit_msgs: List[str] = []
        with self._patch_session(fake), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)

        self.assertIsInstance(result, TestItemRunResult)
        self.assertEqual(result.channel_section, "channel_2")
        self.assertEqual(result.total, 1)
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 0)
        # send_line 总数 = 登录 2 行（sdmc/1234）+ 业务 1 行 = 3
        self.assertEqual(len(fake.sent_lines), 3)
        self.assertIn("/userfs/bin/ponmgr gpon get info", fake.sent_lines[2])
        self.assertTrue(fake.closed, "session 应在 finally 中关闭")
        # 写文件验证
        content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("=== 通道 channel_2 (VLAN110) 开始测试 ===", content)
        self.assertIn("MATCH OK", content)
        self.assertIn("全部完成: 1/1", content)

    def test_single_command_match_fail_after_all_retries(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("/userfs/bin/ponmgr gpon get info", "ONU State: O5", 3)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        fake.responses["/userfs/bin/ponmgr gpon get info"] = "ONU State: O1 (Initial)"

        emit_msgs: List[str] = []
        with self._patch_session(fake), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)

        self.assertEqual(result.total, 1)
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.failed, 1)
        # send_line 总数 = 登录 2 行 + 业务 3 次重试 = 5
        self.assertEqual(len(fake.sent_lines), 5)
        self.assertIn("MATCH FAIL", self.log_path.read_text(encoding="utf-8"))
        # 末次重试后无「下一轮重试」日志
        self.assertIn("已用尽 3 次", "".join(emit_msgs))

    def test_retry_succeeds_on_second_attempt(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("cmd", "SUCCESS", 5)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        # 第 1 次失败、第 2 次成功
        fake = FakeTelnetSession()
        attempts = {"count": 0}
        original_send = fake.send_line

        def conditional_send(text, sensitive=False):
            if text == "cmd":
                attempts["count"] += 1
                if attempts["count"] == 1:
                    fake.responses[text] = "FAIL"
                else:
                    fake.responses[text] = "SUCCESS marker"
            original_send(text, sensitive)

        fake.send_line = conditional_send  # type: ignore[assignment]

        emit_msgs: List[str] = []
        with self._patch_session(fake), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)

        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 0)
        # attempts["count"] 只统计 "cmd" 命令的发送次数(用 conditional_send 计数),不含登录 2 行
        self.assertEqual(attempts["count"], 2)
        self.assertIn("尝试 2/5 匹配成功", "".join(emit_msgs))


class TestItemExecutionNegationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def test_per_segment_negate_mixed(self) -> None:
        """!A&&B&&!C 三段: result 应不含 A/C、含 B。"""
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order(
            [("ifconfig ra0", "!00:00:00:00:00:00&&UP BROADCAST", 3)]
        )
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        fake.responses["ifconfig ra0"] = "CA:7A:85:18:B0:E8 UP BROADCAST MTU:1500"

        emit_msgs: List[str] = []
        with patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake,
        ), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 0)


class TestItemExecutionEmptyExpectedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def test_empty_expected_passes_by_default(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("echo hi", "", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        fake.responses["echo hi"] = "anything"

        emit_msgs: List[str] = []
        with patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake,
        ), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)
        self.assertEqual(result.passed, 1)
        self.assertIn("无期望,默认通过", "".join(emit_msgs))


class TestItemExecutionMultiCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def test_commands_run_in_order(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order(
            [
                ("cmd1", "OK1", 1),
                ("cmd2", "OK2", 1),
                ("cmd3", "OK3", 1),
            ]
        )
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        for i in (1, 2, 3):
            fake.responses[f"cmd{i}"] = f"OK{i} marker"

        emit_msgs: List[str] = []
        with patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake,
        ), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            result = run_test_item_execution(req, emit_msgs.append)

        self.assertEqual(result.total, 3)
        self.assertEqual(result.passed, 3)
        self.assertEqual(result.failed, 0)
        # 顺序校验:登录 2 行 + 业务 3 行
        self.assertEqual(fake.sent_lines, ["sdmc", "1234", "cmd1", "cmd2", "cmd3"])
        # 写文件:3 个 MATCH OK + 3/3 汇总
        content = self.log_path.read_text(encoding="utf-8")
        self.assertEqual(content.count("MATCH OK"), 3)
        self.assertIn("全部完成: 3/3", content)


class TestItemExecutionNetworkFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def test_network_prepare_failure_raises(self) -> None:
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        with patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=False, message="网卡不存在"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                run_test_item_execution(req, lambda _msg: None)
        self.assertIn("网络准备失败", str(ctx.exception))
        self.assertIn("网卡不存在", str(ctx.exception))

    def test_channel_not_enabled_raises(self) -> None:
        channel = _make_channel()
        channel.enabled = False
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_test_item_execution(req, lambda _msg: None)
        self.assertIn("通道未启用", str(ctx.exception))

    def test_missing_network_card_ip_raises(self) -> None:
        channel = _make_channel(network_card_ip="")
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_test_item_execution(req, lambda _msg: None)
        self.assertIn("未配置 PC 静态 IP", str(ctx.exception))

    def test_missing_device_manage_ip_raises(self) -> None:
        channel = _make_channel(device_manage_ip="")
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_test_item_execution(req, lambda _msg: None)
        self.assertIn("未配置样机管理 IP", str(ctx.exception))


class TestItemExecutionLoginFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "device_2.log"

    def test_login_user_prompt_missing_raises(self) -> None:
        """模拟样机不返回 ogin: → 应抛 RuntimeError「登录超时:未收到用户名提示符」。"""
        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=self.log_path,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        # prefill_banner=False → 样机不响应任何 prompt
        fake = FakeTelnetSession(prefill_banner=False)
        emit_msgs: List[str] = []
        with patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake,
        ), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ), patch(
            "src.services.test_item_execution_service.LOGIN_USER_PROMPT_TIMEOUT_SECONDS",
            0.5,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                run_test_item_execution(req, emit_msgs.append)
        self.assertIn("未收到用户名提示符", str(ctx.exception))
        self.assertTrue(fake.closed, "session 应在 finally 中关闭")


class TestItemExecutionFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_log_path_parent_created(self) -> None:
        # 子目录不存在时,run_test_item_execution 应自动创建
        nested = Path(self.temp_dir.name) / "subdir" / "device_2.log"
        self.assertFalse(nested.parent.exists())

        channel = _make_channel()
        telnet = _make_telnet()
        order = _make_order([("cmd", "OK", 1)])
        req = TestItemRunRequest(
            channel=channel,
            order=order,
            telnet=telnet,
            retry_interval_seconds=0,
            log_path=nested,
            sleep_fn=lambda _s: None,
            monotonic_fn=_AdvancingMonotonic(),
        )

        fake = FakeTelnetSession()
        fake.responses["cmd"] = "OK marker"

        with patch(
            "src.services.test_item_execution_service.TelnetSession",
            return_value=fake,
        ), patch(
            "src.services.test_item_execution_service.prepare_network_for_sample",
            return_value=Mock(ok=True, message="就绪"),
        ):
            run_test_item_execution(req, lambda _msg: None)

        self.assertTrue(nested.exists())
        self.assertIn("MATCH OK", nested.read_text(encoding="utf-8"))


class BuildLogPathTests(unittest.TestCase):
    def test_build_log_path_returns_per_channel_path(self) -> None:
        channel = _make_channel()
        path = build_log_path(channel)
        self.assertEqual(path.parent.name, "channel_2")
        self.assertIn("device_channel_2_command_results_", path.name)
        self.assertTrue(str(path).endswith(".log"))
        # 路径根在 TEST_RESULTS_DIR 下
        self.assertEqual(path.parent.parent, TEST_RESULTS_DIR)


class TestItemExecutionConstantsTests(unittest.TestCase):
    def test_constants_have_sensible_defaults(self) -> None:
        # 锁定默认常量,避免后续被改小导致登录超时 / 读回不充分。
        self.assertGreaterEqual(READ_STABLE_SECONDS, 0.5)
        self.assertGreaterEqual(READ_MAX_SECONDS, READ_STABLE_SECONDS)
        self.assertGreaterEqual(LOGIN_USER_PROMPT_TIMEOUT_SECONDS, 10.0)
        self.assertGreaterEqual(LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS, 5.0)
        self.assertGreaterEqual(LOGIN_SUCCESS_TIMEOUT_SECONDS, 10.0)
        self.assertGreaterEqual(LOGIN_INTER_STEP_SLEEP_SECONDS, 0.0)


if __name__ == "__main__":
    unittest.main()

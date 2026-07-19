from __future__ import annotations

import os
import re
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import STANDARD_PARAMETER_DEFINITIONS, SampleParameterRecord, SampleParameterWriteRequest
from src.services.sample_parameter_service import (
    preflight_parameter_targets,
    run_parameter_write_pipeline,
    run_single_sample_parameter_write,
)


class FakeSession:
    def __init__(self, mismatch_variable=""):
        self.writes = []
        self.values = {}
        self.last_read = ""
        self.mismatch_variable = mismatch_variable
        self.closed = False

    def cursor(self):
        return len(self.writes)

    def write(self, data, sensitive=False):
        self.writes.append((data, sensitive))

    def send_line(self, text, sensitive=False):
        self.writes.append((text, sensitive))
        match = re.match(r'^ppctl set ([A-Z0-9_]+)="(.*)"$', text)
        if match:
            self.values[match.group(1)] = match.group(2)
        if text.startswith("ppctl get "):
            self.last_read = text.split()[-1]

    def wait_for_any(self, markers, _timeout, _cursor):
        markers = tuple(markers)
        if "#" in markers:
            return "#"
        return markers[0] if markers else None

    def peek_since(self, _cursor):
        value = self.values.get(self.last_read, "")
        if self.last_read == self.mismatch_variable:
            value = "wrong"
        return f"{self.last_read}={value}\n"

    def close(self):
        self.closed = True


class FakeManager:
    def __init__(self, session):
        self.session = session
        self.acquired = []
        self.released = []

    def acquire_control(self, owner, settings, _path):
        self.acquired.append((owner, settings.port))
        return self.session

    def release(self, owner, port):
        self.released.append((owner, port))


def values():
    data = {definition.column: f"value-{index}" for index, definition in enumerate(STANDARD_PARAMETER_DEFINITIONS)}
    data["MAC"] = "02:00:00:00:00:01"
    data["Superuser Password"] = "secret-super"
    data["User Password"] = "secret-user"
    return data


class SampleParameterServiceTests(unittest.TestCase):
    def test_preflight_rejects_duplicate_and_incomplete_records(self):
        record = SampleParameterRecord("vlan101", values(), 2)
        bad_values = dict(values())
        bad_values["MAC"] = "not-a-mac"
        duplicate = SampleParameterRecord("VLAN101", bad_values, 3)
        result = preflight_parameter_targets([record, duplicate], [("vlan101", "COM1"), ("vlan102", "COM2")])

        self.assertFalse(result.ok)
        self.assertTrue(any("重复" in message for message in result.errors))
        self.assertTrue(any("vlan102" in message for message in result.errors))

    def test_write_reads_back_all_values_and_displays_plaintext(self):
        # 操作员要求所有下发/回显一律明文,密码类字段不再走 [敏感内容已隐藏] 脱敏。
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
        messages = []

        result = run_single_sample_parameter_write(request, manager, messages.append, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.written_count, len(STANDARD_PARAMETER_DEFINITIONS))
        self.assertEqual(manager.released, [("sample-parameter:vlan101", "COM1")])
        self.assertTrue(any(text == "ppctl set FACTORY_MODE=0" for text, _ in session.writes))
        # 密码类字段以明文出现在主执行日志
        self.assertTrue(any("secret-super" in message for message in messages))
        self.assertTrue(any("secret-user" in message for message in messages))
        self.assertFalse(any("[敏感内容已隐藏]" in message for message in messages))

    def test_failed_readback_retries_then_reports_failure_and_cleans_up(self):
        session = FakeSession(mismatch_variable="PRODUCT_CLASS")
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())

        result = run_single_sample_parameter_write(request, manager, sleep_fn=lambda _seconds: None)

        self.assertFalse(result.ok)
        self.assertIn("产品名", result.failed_labels)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertEqual(sum(text.startswith('ppctl set PRODUCT_CLASS=') for text in writes), 3)
        self.assertIn("ppctl set FACTORY_MODE=0", writes)

    def test_cancel_before_start_does_not_enter_factory_mode(self):
        session = FakeSession()
        manager = FakeManager(session)
        cancel = threading.Event()
        cancel.set()
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())

        result = run_single_sample_parameter_write(request, manager, cancel_event=cancel, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.cancelled)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertNotIn("ppctl set FACTORY_MODE=1", writes)

    def test_ppctl_clear_runs_after_factory_relogin_not_before(self):
        # 用户纠正:ppctl clear 应该在工厂模式二次登录之后、15 项 set/get 之前,
        # 而不是首次登录之后、进入工厂模式之前。
        # 2026-07-19 起 clear_parameters 默认 False → 本测试需显式传 True 才能
        # 验证 ppctl clear 的下发时机(已不是默认行为)。
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            clear_parameters=True,
        )
        result = run_single_sample_parameter_write(request, manager, sleep_fn=lambda _seconds: None)
        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        # ppctl clear 出现且只出现一次。
        self.assertEqual(writes.count("ppctl clear"), 1)
        clear_index = writes.index("ppctl clear")
        ppctl_set_indices = [
            index for index, text in enumerate(writes)
            if text.startswith("ppctl set ") and not text.startswith("ppctl set FACTORY_MODE=")
        ]
        # 全部 15 项 ppctl set 都在 ppctl clear 之后。
        self.assertTrue(ppctl_set_indices, "应至少出现 1 项 ppctl set")
        self.assertGreater(min(ppctl_set_indices), clear_index)
        # FACTORY_MODE=0 仍位于 ppctl clear 之后(cleanup 在最后)。
        self.assertGreater(writes.index("ppctl set FACTORY_MODE=0"), clear_index)

    def test_factory_session_swap_returns_none_abandons_before_second_login(self):
        # session_swap 返回 None → pipeline 在二次登录前放弃本台。
        # 显式传 clear_parameters=True 以保留"放弃时不发 ppctl clear"的原始测试意图。
        old_session = FakeSession()
        swap_calls: list = []

        def swap(old):
            swap_calls.append(old)
            return None

        cancel = threading.Event()
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            factory_bind_ip="192.168.29.101",
            factory_device_host="192.168.29.1",
            clear_parameters=True,
        )
        messages: list = []
        result = run_parameter_write_pipeline(
            request, old_session, cancel, lambda _seconds: None, messages.append,
            factory_session_swap=swap,
        )
        self.assertFalse(result.ok)
        self.assertIn("工厂模式网络切换失败", result.message)
        self.assertEqual(len(swap_calls), 1)
        self.assertIs(swap_calls[0], old_session)
        # 旧 session 上没有二次登录后的 ppctl clear。
        writes = [text for text, _ in old_session.writes if isinstance(text, str)]
        self.assertNotIn("ppctl clear", writes)

    def test_factory_session_swap_exception_reports_failure(self):
        old_session = FakeSession()

        def swap(_old):
            raise RuntimeError("切换失败演示")

        cancel = threading.Event()
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            factory_bind_ip="192.168.29.101",
            factory_device_host="192.168.29.1",
        )
        messages: list = []
        result = run_parameter_write_pipeline(
            request, old_session, cancel, lambda _seconds: None, messages.append,
            factory_session_swap=swap,
        )
        self.assertFalse(result.ok)
        self.assertIn("工厂模式网络切换异常", result.message)
        self.assertTrue(any("切换失败演示" in message for message in messages))

    def test_factory_session_swap_new_session_is_used_for_second_login(self):
        # swap 返回新 session → pipeline 把局部 session 切换到新 session,
        # 继续二次登录和 15 项写参;finally 清理走新 session。
        # 这里 fake swap 模拟生产 callback:close 旧 session 后返回新 session。
        old_session = FakeSession()
        new_session = FakeSession()
        seen_old: list = []

        def swap(old):
            seen_old.append(old)
            old.close()
            return new_session

        cancel = threading.Event()
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            factory_bind_ip="192.168.29.101",
            factory_device_host="192.168.29.1",
            clear_parameters=True,
        )

        def telnet_factory(_r):
            return old_session

        result = run_single_sample_parameter_write(
            request,
            FakeManager(old_session),
            messages := [],
            None,
            cancel,
            lambda _seconds: None,
            telnet_session_factory=telnet_factory,
            factory_session_swap=swap,
        )

        self.assertTrue(result.ok, result.message)
        self.assertEqual(seen_old, [old_session])
        # 新 session 上有二次登录后的 ppctl clear 和 15 项 set。
        new_writes = [text for text, _ in new_session.writes if isinstance(text, str)]
        self.assertIn("ppctl clear", new_writes)
        self.assertTrue(any(text.startswith("ppctl set ") and not text.startswith("ppctl set FACTORY_MODE=") for text in new_writes))
        # finally 清理(包含 FACTORY_MODE=0 和 firstboot -yr)在新 session 上执行,旧 session 不再被写。
        self.assertIn("ppctl set FACTORY_MODE=0", new_writes)
        self.assertIn("firstboot -yr", new_writes)
        self.assertTrue(old_session.closed)


class _FlakyFakeSession(FakeSession):
    """FakeSession 子类,支持对特定 command 抛异常以模拟连接关闭。

    抛出后,_send_stage 内的 ``session.send_line`` 会立即抛 ``RuntimeError``,
    模拟 ``TelnetSession.write`` 在 ``self._closed=True`` 或 ``sendall`` OSError 时的行为。

    ``fail_on_call_index`` 用于只在第 N 次匹配该子串时抛异常,避免影响
    流水线中更早的同名命令(例如 ``firstboot -yr`` 既有"进入工厂模式"也有
    "退出工厂模式清理"两次,只想让第 2 次失败)。
    """

    def __init__(self, failing_command_substrings=(), fail_on_call_index=None):
        super().__init__()
        self.failing_command_substrings = tuple(failing_command_substrings)
        # 形如 {"firstboot -yr": 2} 表示"firstboot -yr"第 2 次出现时抛;
        # 不在 dict 里的子串永不抛;形如 {"firstboot -yr": 1} 表示第 1 次就抛。
        self.fail_on_call_index = dict(fail_on_call_index or {})
        self._match_counts: dict[str, int] = {}
        self.failed_commands: list[str] = []

    def send_line(self, text, sensitive=False):
        for needle in self.failing_command_substrings:
            if needle in text:
                self._match_counts[needle] = self._match_counts.get(needle, 0) + 1
                target = self.fail_on_call_index.get(needle)
                # 没指定 target → 立刻抛(向后兼容);指定 target → 只在该次抛。
                if target is None or self._match_counts[needle] == target:
                    self.failed_commands.append(text)
                    raise RuntimeError(f"Telnet 连接已关闭:192.168.29.1:23")
                # 还没到目标次数,落到 FakeSession.send_line 正常写。
                break
        super().send_line(text, sensitive=sensitive)


class SampleParameterServiceCleanupFailureTests(unittest.TestCase):
    """退出工厂模式清理失败日志(2026-07-19):两步独立 try/except 后,每一步的
    TX 主程序执行日志必然出现,失败消息明确标识是哪一步触发的连接关闭。"""

    def test_cleanup_emits_both_tx_lines_even_when_firstboot_fails(self):
        # 第 1 步 FACTORY_MODE=0 成功,第 2 步 firstboot -yr 抛 "Telnet 连接已关闭"。
        # 期望主执行日志: TX FACTORY_MODE=0 → TX firstboot -yr → 失败(明确 step 名)
        # → 请人工确认。关键: TX firstboot -yr 必须出现;失败消息不吞掉第 1 步成功上下文。
        # ``firstboot -yr`` 在流水线里出现两次(进入工厂模式 + 退出清理),
        # 用 ``fail_on_call_index=2`` 让第 2 次(清理)失败,避免把入口流程也搞坏。
        session = _FlakyFakeSession(
            failing_command_substrings=("firstboot -yr",),
            fail_on_call_index={"firstboot -yr": 2},
        )
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan112", "COM112", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )
        # 主流程 15 项全部成功(异常只在 finally 清理抛)。
        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertIn("ppctl set FACTORY_MODE=0", writes)
        self.assertIn("firstboot -yr", writes)
        self.assertEqual(session.failed_commands, ["firstboot -yr"])
        # 主执行日志按顺序出现两条 TX:cleanup 的 FACTORY_MODE=0 在 cleanup 的 firstboot -yr 之前。
        # 精确字符串匹配避免与入口阶段的 FACTORY_MODE=1 / firstboot -yr 混淆。
        tx_factory_index = messages.index("vlan112 TX ppctl set FACTORY_MODE=0")
        tx_firstboot_indices = [
            index for index, message in enumerate(messages)
            if message == "vlan112 TX firstboot -yr"
        ]
        self.assertEqual(len(tx_firstboot_indices), 2, messages)
        cleanup_firstboot_index = tx_firstboot_indices[1]
        self.assertGreater(cleanup_firstboot_index, tx_factory_index)
        # 失败日志明确标识为 firstboot -yr 下发失败。
        self.assertTrue(
            any("firstboot -yr 下发失败" in message for message in messages),
            messages,
        )
        self.assertTrue(
            any("请人工确认设备已退出工厂模式" in message for message in messages),
            messages,
        )
        # 成功收尾日志被抑制(因为有失败步骤)。
        self.assertFalse(
            any("已下发退出工厂模式与重启命令" in message for message in messages),
            messages,
        )

    def test_cleanup_reports_factory_mode_failure_when_step_one_fails(self):
        # 第 1 步 FACTORY_MODE=0 立刻抛异常,模拟连接在清理时已被关闭。
        # 期望:第 1 步的 TX 出现 + 第 1 步失败消息;第 2 步 firstboot -yr 仍要尝试
        # 并在主执行日志出现 TX 行(best-effort);firstboot 也失败时,两条失败都用
        # ";" 分隔出现在汇总消息里。
        # ``FACTORY_MODE=0`` 出现一次(只在 cleanup 阶段),``firstboot -yr`` 出现两次
        # (进入工厂 + 退出清理),所以 fail_on_call_index 配成 1 / 2。
        session = _FlakyFakeSession(
            failing_command_substrings=(
                "ppctl set FACTORY_MODE=0",
                "firstboot -yr",
            ),
            fail_on_call_index={
                "ppctl set FACTORY_MODE=0": 1,
                "firstboot -yr": 2,
            },
        )
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan112", "COM112", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )
        self.assertTrue(result.ok, result.message)
        # 两条命令都被尝试(FACTORY_MODE 先,firstboot 后)。
        self.assertEqual(
            session.failed_commands,
            ["ppctl set FACTORY_MODE=0", "firstboot -yr"],
        )
        # 主执行日志里两步的 TX 行都出现,顺序 FACTORY_MODE 在前。
        # 精确字符串匹配避免与入口阶段的 FACTORY_MODE=1 / firstboot -yr 混淆。
        tx_factory_index = messages.index("vlan112 TX ppctl set FACTORY_MODE=0")
        tx_firstboot_indices = [
            index for index, message in enumerate(messages)
            if message == "vlan112 TX firstboot -yr"
        ]
        self.assertEqual(len(tx_firstboot_indices), 2, messages)
        self.assertLess(tx_factory_index, tx_firstboot_indices[1])
        # 失败汇总消息把两条都列出来,用 ";" 分隔,且明确指明是哪一步失败。
        failure_lines = [
            message for message in messages
            if message.startswith("vlan112 写参：退出工厂模式清理失败：")
        ]
        self.assertEqual(len(failure_lines), 1, failure_lines)
        combined = failure_lines[0]
        self.assertIn("FACTORY_MODE=0 下发失败", combined)
        self.assertIn("firstboot -yr 下发失败", combined)
        self.assertIn("；", combined)
        # 仍输出"请人工确认"提示。
        self.assertTrue(
            any("请人工确认设备已退出工厂模式" in message for message in messages),
            messages,
        )

    def test_cleanup_success_log_unchanged_when_both_steps_succeed(self):
        # 成功路径回归:两步都下发成功时,主执行日志必须出现"已下发退出工厂模式与重启命令。"
        # 与"已下发退出工厂模式与重启命令"互斥的失败消息不应出现。
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan112", "COM112", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )
        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertIn("ppctl set FACTORY_MODE=0", writes)
        self.assertIn("firstboot -yr", writes)
        # 成功收尾日志出现。
        self.assertTrue(
            any("已下发退出工厂模式与重启命令" in message for message in messages),
            messages,
        )
        # 失败相关日志不出现。
        self.assertFalse(
            any("退出工厂模式清理失败" in message for message in messages),
            messages,
        )
        self.assertFalse(
            any("请人工确认设备已退出工厂模式" in message for message in messages),
            messages,
        )


class SampleParameterPipelineOptionTests(unittest.TestCase):
    """2026-07-19:流水线新增两个可选行为 —— clear_parameters (ppctl clear) /
    exit_aging (ppctl set AGING_STATE=1),默认关闭。验证默认关闭 / 显式开启 /
    两者组合 / 顺序等行为,确保主执行日志能区分"已下发"与"关闭，跳过"。
    """

    def test_clear_parameters_default_off_does_not_send_ppctl_clear(self):
        """clear_parameters 默认 False → 不发 ppctl clear,主日志出现"关闭，跳过"。"""
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )

        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertNotIn("ppctl clear", writes)
        self.assertTrue(
            any("清空参数：关闭，跳过" in message for message in messages),
            messages,
        )

    def test_clear_parameters_on_sends_ppctl_clear(self):
        """clear_parameters=True → 发 ppctl clear,主日志不再出现"关闭，跳过"。"""
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            clear_parameters=True,
        )
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )

        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertEqual(writes.count("ppctl clear"), 1)
        self.assertFalse(
            any("清空参数：关闭，跳过" in message for message in messages),
            messages,
        )

    def test_exit_aging_on_sends_aging_state_before_clear_and_writes(self):
        """exit_aging=True + clear_parameters=True → 顺序:AGING_STATE → clear → 15 项 set。"""
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest(
            "vlan101", "COM1", "root", "initial-secret", values(),
            clear_parameters=True,
            exit_aging=True,
        )
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )

        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        aging_index = writes.index("ppctl set AGING_STATE=1")
        clear_index = writes.index("ppctl clear")
        ppctl_set_indices = [
            index for index, text in enumerate(writes)
            if text.startswith("ppctl set ") and not text.startswith("ppctl set FACTORY_MODE=")
            and not text.startswith("ppctl set AGING_STATE=")
        ]
        # 退出老化 → 清空 → 15 项写参
        self.assertLess(aging_index, clear_index)
        self.assertTrue(ppctl_set_indices)
        self.assertGreater(min(ppctl_set_indices), clear_index)
        # 退出工厂模式清理仍在最末
        self.assertGreater(writes.index("ppctl set FACTORY_MODE=0"), max(ppctl_set_indices))
        # 主日志出现"已下发退出老化命令"
        self.assertTrue(
            any("已下发退出老化命令" in message for message in messages),
            messages,
        )

    def test_exit_aging_off_skips_aging_state(self):
        """exit_aging 默认 False → 不发 AGING_STATE=1,主日志出现"关闭，跳过"。"""
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )

        self.assertTrue(result.ok, result.message)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertFalse(any("AGING_STATE" in text for text in writes))
        self.assertTrue(
            any("退出老化：关闭，跳过" in message for message in messages),
            messages,
        )

    def test_both_options_off_skips_both_commands(self):
        """两个选项都关闭 → 不发 ppctl clear / AGING_STATE,15 项写参仍全部成功。"""
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
        messages: list = []
        result = run_single_sample_parameter_write(
            request, manager, messages.append, sleep_fn=lambda _seconds: None
        )

        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.written_count, len(STANDARD_PARAMETER_DEFINITIONS))
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertNotIn("ppctl clear", writes)
        self.assertFalse(any("AGING_STATE" in text for text in writes))
        # 两条关闭/跳过日志均出现
        self.assertTrue(any("清空参数：关闭，跳过" in m for m in messages))
        self.assertTrue(any("退出老化：关闭，跳过" in m for m in messages))

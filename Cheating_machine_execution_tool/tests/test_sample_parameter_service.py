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
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
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

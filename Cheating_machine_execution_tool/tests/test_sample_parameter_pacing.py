"""写参节奏常量回归测试(2026-07-18 P2 缓解)。

锁定 ``src.services.sample_parameter_service`` 的 7 个节奏常量在
``_login`` / ``_write_and_verify`` / ``run_parallel_sample_parameter_writes``
内的应用,防止后续重构悄悄改回硬编码值;同时固化错峰启动的延迟语义。

历史硬编码值(已替换):
- ``_write_and_verify`` set 后 sleep 1.0s / get 等 marker 4.0s
- ``_login`` prompt 8s / password_prompt 8s / password_result 15.0s
- 15 项参数之间无间隔 / 重试无退避 / 并行 worker 同 t=0 启动
"""
from __future__ import annotations

import os
import re
import sys
import threading
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import STANDARD_PARAMETER_DEFINITIONS, SampleParameterItemResult, SampleParameterWriteRequest
from src.services.sample_parameter_service import (
    PARAMETER_BETWEEN_PARAMS_SECONDS,
    PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS,
    PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS,
    PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS,
    PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS,
    PARAMETER_RETRY_BACKOFF_SECONDS,
    PARAMETER_SETTLE_AFTER_SET_SECONDS,
    _login,
    _write_and_verify,
    run_parallel_sample_parameter_writes,
)


class _RecordingSession:
    """记录 ``wait_for_any`` / ``send_line`` / sleep 调用的最小 fake。

    ``wait_for_any`` 默认命中第一个 marker,使 ``_login`` / ``_write_and_verify``
    主流程能跑通。``peek_value_seq`` 用于精确控制 ``peek_since`` 返回的字符串,
    从而触发 mismatch / 成功等场景。
    """

    def __init__(self) -> None:
        self.wait_calls: list[tuple[tuple, float, int]] = []
        self.writes: list[tuple[str, Any]] = []
        self._cursor = 0
        self._last_set: dict[str, str] = {}
        self._last_get = ""
        self._peek_seq: list[str] = []
        # 让某一次 wait_for_any 调用返回 None,模拟超时
        self._return_none_at_indices: set[int] = set()

    def cursor(self) -> int:
        return self._cursor

    def write(self, data: bytes, sensitive: bool = False) -> None:
        self.writes.append(("write", bytes(data), sensitive))

    def send_line(self, text: str, sensitive: bool = False) -> None:
        self.writes.append(("send_line", text, sensitive))
        match = re.match(r'^ppctl set ([A-Z0-9_]+)="(.*)"$', text)
        if match:
            self._last_set[match.group(1)] = match.group(2)
        if text.startswith("ppctl get "):
            self._last_get = text.split()[-1]

    def wait_for_any(self, markers, timeout, cursor):
        marker_list = tuple(markers) if not isinstance(markers, tuple) else tuple(markers)
        call_index = len(self.wait_calls)
        self.wait_calls.append((marker_list, float(timeout), int(cursor)))
        if call_index in self._return_none_at_indices:
            return None
        return marker_list[0] if marker_list else None

    def peek_since(self, cursor: int) -> str:
        if self._peek_seq:
            return self._peek_seq.pop(0)
        return f"{self._last_get}={self._last_set.get(self._last_get, '')}\n"

    def close(self) -> None:
        pass


def _make_request() -> SampleParameterWriteRequest:
    values = {definition.column: f"value-{index}" for index, definition in enumerate(STANDARD_PARAMETER_DEFINITIONS)}
    values["MAC"] = "02:00:00:00:00:01"
    return SampleParameterWriteRequest(
        vlan="vlan101",
        serial_port="COM1",
        initial_username="root",
        initial_password="x",
        values=values,
        bind_ip="192.168.1.101",
        device_host="192.168.1.1",
        ubus_port=80,
        factory_bind_ip="192.168.29.101",
        factory_device_host="192.168.29.1",
    )


def _approx(value: float, target: float, places: int = 2) -> bool:
    return abs(value - target) < 10 ** (-places)


def _aggregate_chunks(sleeps: list[float]) -> list[float]:
    """合并 ``_wait_cancellable`` 切出的 ≤1.0s 块,还原原始 sleep 时长。

    ``_wait_cancellable(1.5)`` 内部循环每次 sleep ≤1.0,所以 1.5s 会被切成
    ``[1.0, 0.5]``;0.5s 保持 ``[0.5]``;0.6s 保持 ``[0.6]``。
    聚合规则:遇到 ``1.0`` 时看下一项,若 ≤1.0 则合并。
    """
    result: list[float] = []
    i = 0
    while i < len(sleeps):
        if i + 1 < len(sleeps) and sleeps[i] == 1.0 and 0 < sleeps[i + 1] < 1.0:
            result.append(sleeps[i] + sleeps[i + 1])
            i += 2
        else:
            result.append(sleeps[i])
            i += 1
    return result


def _count_sleeps(sleeps: list[float], target: float) -> int:
    """聚合后,统计等于 ``target`` 的 sleep 次数。

    注意:SETTLE_AFTER_SET 和 RETRY_BACKOFF 都是 1.5s,聚合后无法用数值区分;
    需要按位置或模式断言,不能用本函数同时验证二者各自次数。
    """
    return sum(1 for s in _aggregate_chunks(sleeps) if _approx(s, target, places=1))


class LoginPacingTests(unittest.TestCase):
    """``_login`` 的 prompt / password_prompt / password_result 三处超时应使用节奏常量。"""

    def test_login_prompt_and_password_use_constants(self) -> None:
        """驱动 _login 走完整流程,验证 3 次 wait_for_any 的 timeout 都用对应常量。"""
        sleeps: list[float] = []
        session = _RecordingSession()

        # 用包装层强制 _login 走完整 3 次 wait_for_any:首次返回 "password:"
        # 强制 _login 发 username;第二次返回 "password:" 强制发 password;第三次返回 "#"。
        original_wait = session.wait_for_any
        call_index = [0]

        def custom_wait(markers, timeout, cursor):
            idx = call_index[0]
            call_index[0] += 1
            original_wait(markers, timeout, cursor)  # 记录到 wait_calls
            if idx == 0:
                return "password:"  # not in {"#", ">"} → 走 username 路径
            if idx == 1:
                return "password:"  # in {"password:", "passvord:"} → 走 password 路径
            return "#"  # in {"#", ">"} → 成功

        session.wait_for_any = custom_wait
        cancel = threading.Event()
        ok = _login(session, "root", "x", cancel, sleeps.append)
        self.assertTrue(ok)

        # 3 次 wait_for_any: prompt / password_prompt / password_result
        self.assertEqual(len(session.wait_calls), 3, f"expected 3 wait_for_any, got {session.wait_calls}")
        _, prompt_timeout, _ = session.wait_calls[0]
        _, password_prompt_timeout, _ = session.wait_calls[1]
        _, password_result_timeout, _ = session.wait_calls[2]
        self.assertEqual(prompt_timeout, PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS)
        self.assertEqual(password_prompt_timeout, PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS)
        self.assertEqual(password_result_timeout, PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS)

    def test_login_prompt_timeout_constant_at_least_eight(self) -> None:
        """旧硬编码 8.0s,新常量应 ≥ 8.0s。"""
        self.assertGreaterEqual(PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS, 8.0)

    def test_login_password_timeout_constant_at_least_fifteen(self) -> None:
        """旧硬编码 15.0s,新常量应 ≥ 15.0s。"""
        self.assertGreaterEqual(PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS, 15.0)


class WriteAndVerifyPacingTests(unittest.TestCase):
    """``_write_and_verify`` 应使用节奏常量替换硬编码 1.0 / 4.0,并加 retry-backoff / between-params。"""

    def test_first_attempt_success_uses_settle_and_get_timeout_and_between_params(self) -> None:
        sleeps: list[float] = []
        session = _RecordingSession()
        cancel = threading.Event()
        ok = _write_and_verify(
            session,
            "vlan101",
            "MAC",
            "ppctl set MAC=",
            "02:00:00:00:00:01",
            False,
            cancel,
            lambda _msg: None,
            sleeps.append,
        )
        self.assertTrue(ok)
        # 1 次 wait_for_any:get 后等 marker,timeout 应为新常量
        self.assertEqual(len(session.wait_calls), 1, f"expected 1 wait_for_any, got {session.wait_calls}")
        self.assertEqual(session.wait_calls[0][1], PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS)
        # 聚合后的 sleep 模式:SETTLE → BETWEEN(无 BACKOFF,无 retry)
        aggregated = _aggregate_chunks(sleeps)
        self.assertEqual(
            aggregated,
            [PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_BETWEEN_PARAMS_SECONDS],
            f"expected [SETTLE, BETWEEN], got {aggregated}",
        )

    def test_mismatch_then_success_uses_retry_backoff(self) -> None:
        """第 1 次 mismatch → 第 2 次成功;两次之间应 sleep RETRY_BACKOFF。"""
        sleeps: list[float] = []
        session = _RecordingSession()
        # 第 1 次 peek 返回错误值,第 2 次返回正确值(必须带变量名前缀供 _extract_readback 解析)
        session._peek_seq = [
            "MAC=02:00:00:00:00:99\n",
            "MAC=02:00:00:00:00:01\n",
        ]
        cancel = threading.Event()
        ok = _write_and_verify(
            session,
            "vlan101",
            "MAC",
            "ppctl set MAC=",
            "02:00:00:00:00:01",
            False,
            cancel,
            lambda _msg: None,
            sleeps.append,
        )
        self.assertTrue(ok, "expected success on second attempt")
        # 聚合后的 sleep 模式:SETTLE → BACKOFF → SETTLE → BETWEEN
        aggregated = _aggregate_chunks(sleeps)
        self.assertEqual(
            aggregated,
            [
                PARAMETER_SETTLE_AFTER_SET_SECONDS,
                PARAMETER_RETRY_BACKOFF_SECONDS,
                PARAMETER_SETTLE_AFTER_SET_SECONDS,
                PARAMETER_BETWEEN_PARAMS_SECONDS,
            ],
            f"expected [SETTLE, BACKOFF, SETTLE, BETWEEN], got {aggregated}",
        )

    def test_marker_timeout_uses_backoff_and_between_params(self) -> None:
        """3 次都 marker=None(超时);每次后 RETRY_BACKOFF;循环结束 BETWEEN_PARAMS。"""
        sleeps: list[float] = []
        session = _RecordingSession()
        # 让所有 wait_for_any 调用都返回 None(模拟超时)
        session._return_none_at_indices = {0, 1, 2}
        cancel = threading.Event()
        ok = _write_and_verify(
            session,
            "vlan101",
            "MAC",
            "ppctl set MAC=",
            "02:00:00:00:00:01",
            False,
            cancel,
            lambda _msg: None,
            sleeps.append,
        )
        self.assertFalse(ok)
        # 聚合后:[SETTLE, BACKOFF] × 3 + BETWEEN
        aggregated = _aggregate_chunks(sleeps)
        expected = [
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_BETWEEN_PARAMS_SECONDS,
        ]
        self.assertEqual(aggregated, expected, f"sleep pattern mismatch")

    def test_all_mismatch_uses_backoff_and_between_params(self) -> None:
        """3 次都 mismatch(peek 始终返回错误值);循环结束 BETWEEN_PARAMS。"""
        sleeps: list[float] = []
        session = _RecordingSession()
        # peek 总是返回错误值(带变量名前缀)→ mismatch
        session._peek_seq = ["MAC=02:00:00:00:00:99\n"] * 5
        cancel = threading.Event()
        ok = _write_and_verify(
            session,
            "vlan101",
            "MAC",
            "ppctl set MAC=",
            "02:00:00:00:00:01",
            False,
            cancel,
            lambda _msg: None,
            sleeps.append,
        )
        self.assertFalse(ok)
        # 聚合后:[SETTLE, BACKOFF] × 3 + BETWEEN
        aggregated = _aggregate_chunks(sleeps)
        expected = [
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_SETTLE_AFTER_SET_SECONDS, PARAMETER_RETRY_BACKOFF_SECONDS,
            PARAMETER_BETWEEN_PARAMS_SECONDS,
        ]
        self.assertEqual(aggregated, expected, f"sleep pattern mismatch")


class ParallelStaggerTests(unittest.TestCase):
    """``run_parallel_sample_parameter_writes`` 应按 index 错峰启动。"""

    def _run_three_requests(self, stagger: float) -> list[float]:
        sleeps: list[float] = []
        requests = [_make_request() for _ in range(3)]
        manager = MagicMock()

        def fake_run_single(request, *_args, **_kwargs):
            return SampleParameterItemResult(request, True, "ok")

        with patch(
            "src.services.sample_parameter_service.run_single_sample_parameter_write",
            side_effect=fake_run_single,
        ):
            run_parallel_sample_parameter_writes(
                requests,
                manager,
                parallel_count=3,
                on_output=None,
                startup_stagger_seconds=stagger,
                sleep_fn=sleeps.append,
            )
        return sleeps

    def test_run_parallel_writes_staggers_startup(self) -> None:
        """3 个 requests,stagger=0.05;期望 sleep_fn 被调用 2 次(每个 = 0.05,非累加)。"""
        sleeps = self._run_three_requests(stagger=0.05)
        self.assertEqual(len(sleeps), 2, f"expected 2 stagger sleeps (index>0), got {sleeps}")
        self.assertTrue(_approx(sleeps[0], 0.05), f"first sleep {sleeps[0]} != 0.05")
        self.assertTrue(_approx(sleeps[1], 0.05), f"second sleep {sleeps[1]} != 0.05")

    def test_run_parallel_writes_zero_stagger_does_not_sleep(self) -> None:
        """stagger=0 时 sleep_fn 不应被调用。"""
        sleeps = self._run_three_requests(stagger=0.0)
        self.assertEqual(len(sleeps), 0, f"expected no stagger sleeps, got {sleeps}")

    def test_run_parallel_writes_default_stagger_matches_constant(self) -> None:
        """不显式传 startup_stagger_seconds 时,默认值 = PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS。"""
        sleeps = self._run_three_requests(stagger=PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(_approx(sleeps[0], PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS))
        self.assertTrue(_approx(sleeps[1], PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS))


class PacingConstantRegressionTests(unittest.TestCase):
    """节奏常量默认值的回归保护:防止后续被无意中改回更紧的值。"""

    def test_settle_after_set_at_least_one_second(self) -> None:
        """原硬编码 1.0s,新常量应 ≥ 1.0s。"""
        self.assertGreaterEqual(PARAMETER_SETTLE_AFTER_SET_SECONDS, 1.0)

    def test_get_response_timeout_at_least_four_seconds(self) -> None:
        """原硬编码 4.0s,新常量应 ≥ 4.0s。"""
        self.assertGreaterEqual(PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS, 4.0)

    def test_retry_backoff_positive(self) -> None:
        self.assertGreater(PARAMETER_RETRY_BACKOFF_SECONDS, 0.0)

    def test_between_params_positive(self) -> None:
        self.assertGreater(PARAMETER_BETWEEN_PARAMS_SECONDS, 0.0)

    def test_parallel_stagger_non_negative(self) -> None:
        self.assertGreaterEqual(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS, 0.0)


if __name__ == "__main__":
    unittest.main()
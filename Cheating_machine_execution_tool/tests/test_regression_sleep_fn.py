"""回归:锁住 ``_wait_cancellable`` 在 ``sleep_fn=None`` 时立即报
``'NoneType' object is not callable`` 的契约。

历史 BUG:`_sample_parameter_write_worker` 的 telnet 路径传过 ``sleep_fn=None``,
导致写参流程在 ``_wait_cancellable(FACTORY_REBOOT_WAIT_SECONDS=100, ...)`` 第一轮循环
就抛 ``'NoneType' object is not callable``,被外层 except 接住,finally 又以
``entered_factory=True`` 立即下发 ``ppctl set FACTORY_MODE=0`` 与 ``firstboot -yr``。
"""
from __future__ import annotations

import threading
import unittest

from src.services.sample_parameter_service import _wait_cancellable


class WaitCancellableRegressionTests(unittest.TestCase):
    def test_sleep_fn_none_raises_none_type_not_callable(self):
        """契约:任何 sleep_fn 形参都必须可调用;传 None 时立即报 ``'NoneType' object is not callable``。

        这条断言把 BUG 形态固化:如果以后 caller 误传 ``None``,运行时第一秒就会报错,
        而不是让工厂模式清理在同一个毫秒撞进 finally。
        """
        cancel = threading.Event()
        with self.assertRaisesRegex(TypeError, "NoneType"):
            _wait_cancellable(0.1, cancel, None)

    def test_sleep_fn_callable_runs_through_and_returns_true(self):
        """契约:可调用 sleep_fn 在 cancel 未触发时应返回 True。"""
        cancel = threading.Event()
        sleeps: list[float] = []

        result = _wait_cancellable(0.3, cancel, sleeps.append)

        self.assertTrue(result)
        self.assertGreaterEqual(len(sleeps), 1)
        self.assertLessEqual(sum(sleeps), 0.31)

    def test_sleep_fn_callable_returns_false_on_cancel(self):
        """契约:可调用 sleep_fn,一旦 cancel 触发即刻返回 False,不再 sleep。"""
        cancel = threading.Event()
        cancel.set()
        sleeps: list[float] = []

        result = _wait_cancellable(5.0, cancel, sleeps.append)

        self.assertFalse(result)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()

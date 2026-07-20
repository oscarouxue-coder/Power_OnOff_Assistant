"""「全流程执行」窗口 ``_build_context`` 的回归测试。

2026-07-20 bug:``_build_context`` 用 ``_get_attr(app, "TEST_ITEM_CONFIG_PATH")`` 取配置路径,
但 ``TEST_ITEM_CONFIG_PATH`` 是 ``line_check_assistant.app`` 模块级常量、不在实例属性上,
结果拿到 ``None`` → ``configparser.read(None)`` 抛 ``TypeError: 'NoneType' object is not iterable``。
本测试构造一个不挂 tk 的 ``FakeApp``,模拟真实窗口调用路径,锁定该 bug 不再回归。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


# 把 ``line_check_assistant`` / ``src`` 加进 path,与其它测试一致
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _candidate in (_ROOT, _ROOT / "src"):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


class FakeApp:
    """不带 tk 的最小 LineCheckAssistant 替身。"""

    def __init__(self) -> None:
        # channels 用 MagicMock 模拟 list(只用到 __iter__/len)
        self.channels = []
        self.sample_upgrade_settings = None  # 触发 _build_context 内的 fallback
        self.onu_registration_config = None
        # 不挂 TEST_ITEM_CONFIG_PATH,模拟真实实例(常量在模块上)
        self._serial_log_directory = lambda: None


class BuildContextRegressionTests(unittest.TestCase):
    def test_build_context_does_not_use_getattr_for_module_constant(self) -> None:
        """_build_context 必须从 app 模块取 TEST_ITEM_CONFIG_PATH,不能 ``_get_attr(app, ...)``。

        旧实现 ``_get_attr(app, "TEST_ITEM_CONFIG_PATH")`` 拿到 None,后续 ``configparser.read(None)``
        抛 ``TypeError: 'NoneType' object is not iterable``。
        """
        from line_check_assistant.pipeline_window import PipelineWindow  # noqa: F401

        # 直接 import pipeline_window 的源码并粗略检查关键路径
        # (不实例化 PipelineWindow,因为它要 tk root)
        import line_check_assistant.pipeline_window as pw_mod

        # 1. _get_attr(app, "TEST_ITEM_CONFIG_PATH") 必须不存在于 _build_context
        #    通过源码字符串静态检查(防止以后误回滚)
        import inspect

        source = inspect.getsource(pw_mod.PipelineWindow._build_context)
        self.assertNotIn(
            '_get_attr(app, "TEST_ITEM_CONFIG_PATH")',
            source,
            "_build_context 不能用 _get_attr 拿模块级常量,会拿到 None → configparser 报错",
        )
        # 2. 必须从 line_check_assistant.app 模块导入并直接访问
        self.assertIn("line_check_assistant.app", source)
        self.assertIn("TEST_ITEM_CONFIG_PATH", source)

    def test_compute_subtask_statuses_succeeds_with_minimal_app(self) -> None:
        """真实 _build_context 路径上 compute_all_subtask_statuses 必须不抛。"""
        import line_check_assistant.app as app_module
        from line_check_assistant.onu_registration_store import OnuRegistrationConfig
        from line_check_assistant.pipeline_window import PipelineWindow  # noqa: F401
        from line_check_assistant.sample_upgrade_settings_store import (
            SampleUpgradeSettings,
        )
        from src.services.pipeline_orchestrator import (
            PipelineContext,
            compute_all_subtask_statuses,
        )
        from line_check_assistant.test_item_config_store import TestItemConfigStore

        fake = FakeApp()
        # 构造与 _build_context 完全一致的 PipelineContext(只走模块常量路径)
        ctx = PipelineContext(
            app=fake,
            channels=fake.channels,
            sample_upgrade_settings=SampleUpgradeSettings(),
            onu_registration=OnuRegistrationConfig(),
            test_project_config=TestItemConfigStore(app_module.TEST_ITEM_CONFIG_PATH).load(),
            serial_log_dir=None,
        )
        statuses = compute_all_subtask_statuses(ctx)
        # 6 个子任务都必须有结果
        self.assertEqual(len(statuses), 6)
        for code in (
            "power_cycle",
            "sample_upgrade",
            "sample_parameter_write",
            "onu_registration",
            "serial_terminal",
            "test_item_execution",
        ):
            self.assertIn(code, statuses)
            self.assertIsNotNone(statuses[code].summary)
            self.assertIsInstance(statuses[code].missing, tuple)


if __name__ == "__main__":
    unittest.main()
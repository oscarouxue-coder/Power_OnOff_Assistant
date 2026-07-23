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
    def test_pipeline_confirmation_contains_manual_reboot_guard_for_empty_com(self) -> None:
        """空 COM 的全流程执行必须在启动后台线程前要求操作员确认手动重启。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn("请先手动重启样机", source)
        self.assertIn("确认样机已重启后再点击", source)

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
        # 7 个子任务都必须有结果(2026-07-20 新增 env_check 在首位)
        self.assertEqual(len(statuses), 7)
        for code in (
            "env_check",
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


class OpenNetworkConfigRegressionTests(unittest.TestCase):
    """``app._open_network_config`` 的回归测试。

    2026-07-20 bug:第一次实现 ``_open_network_config()`` 直接调
    ``self.pipeline_window.winfo_exists()`` / ``self.pipeline_window.withdraw()``,
    但 ``PipelineWindow`` 是普通类(持有 ``self.window: Toplevel``),
    ``winfo_exists`` / ``withdraw`` 在 ``Toplevel`` 实例上,在包装器上不存在。
    结果操作员点「环境线路检查」行的「去配置」→ 弹
    ``AttributeError: PipelineWindow object has no attribute 'winfo_exists'``。
    本测试通过源码静态断言 + 用 MagicMock 模拟 wrapper + window,验证:
    ① 必须走 ``pipeline_window.window.winfo_exists()`` 而非包装器
    ② 调 ``_open_network_config`` 时不抛 AttributeError
    """

    def test_open_network_config_delegates_to_window_attribute(self) -> None:
        """源码静态断言:_open_network_config 必须通过 .window 走 Toplevel 方法。"""
        import inspect

        import line_check_assistant.app as app_module

        source = inspect.getsource(app_module.LineCheckAssistant._open_network_config)
        # 关键修复:必须先取 pipeline_window.window 再调 winfo_exists / withdraw
        self.assertIn("pipeline_window.window.winfo_exists", source)
        self.assertIn("pipeline_window.window.withdraw", source)
        # 反向断言:不能直接调包装器(避免回归)
        self.assertNotIn(
            "self.pipeline_window.winfo_exists(",
            source,
            "_open_network_config 不能直接调包装器的 winfo_exists,会抛 AttributeError",
        )
        self.assertNotIn(
            "self.pipeline_window.withdraw(",
            source,
            "_open_network_config 不能直接调包装器的 withdraw,会抛 AttributeError",
        )

    def test_open_network_config_does_not_raise_when_window_exists(self) -> None:
        """用 MagicMock 模拟 pipeline_window(只挂 .window),验证 _open_network_config 不抛。"""
        import line_check_assistant.app as app_module

        # 模拟 LineCheckAssistant 实例的最小骨架(只用到 _open_network_config 内的字段)
        fake_app = MagicMock(spec=["pipeline_window", "deiconify", "lift", "focus_force", "_log"])
        # 模拟 pipeline_window 是 PipelineWindow 包装器,持有 .window
        fake_pipeline_window = MagicMock(spec=["window"])
        fake_pipeline_window.window.winfo_exists.return_value = True
        fake_app.pipeline_window = fake_pipeline_window

        # 直接调 _open_network_config(不实例化 LineCheckAssistant,避免 tk)
        app_module.LineCheckAssistant._open_network_config(fake_app)

        # winfo_exists() 被调一次,withdraw() 被调一次,主界面被拉前台 + log
        fake_pipeline_window.window.winfo_exists.assert_called_once()
        fake_pipeline_window.window.withdraw.assert_called_once()
        fake_app.deiconify.assert_called_once()
        fake_app.lift.assert_called_once()
        fake_app.focus_force.assert_called_once()
        fake_app._log.assert_called_once()
        log_msg = fake_app._log.call_args[0][0]
        self.assertIn("网络配置", log_msg)

    def test_open_network_config_skips_when_window_destroyed(self) -> None:
        """pipeline_window 已销毁时(``winfo_exists()`` 返回 False),不应调 withdraw。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(spec=["pipeline_window", "deiconify", "lift", "focus_force", "_log"])
        fake_pipeline_window = MagicMock(spec=["window"])
        fake_pipeline_window.window.winfo_exists.return_value = False
        fake_app.pipeline_window = fake_pipeline_window

        app_module.LineCheckAssistant._open_network_config(fake_app)

        fake_pipeline_window.window.winfo_exists.assert_called_once()
        fake_pipeline_window.window.withdraw.assert_not_called()  # 已销毁,不调
        fake_app.deiconify.assert_called_once()  # 主界面仍要拉前台
        fake_app._log.assert_called_once()

    def test_open_network_config_handles_none_pipeline_window(self) -> None:
        """pipeline_window 字段为 None 时不应抛。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(spec=["pipeline_window", "deiconify", "lift", "focus_force", "_log"])
        fake_app.pipeline_window = None

        app_module.LineCheckAssistant._open_network_config(fake_app)

        # 不调 window 方法,直接走主界面拉前台 + log
        fake_app.deiconify.assert_called_once()
        fake_app.lift.assert_called_once()
        fake_app._log.assert_called_once()


class StartAllChecksRegressionTests(unittest.TestCase):
    """``app._start_all_checks`` 的回归测试。

    2026-07-20 bug:``_start_all_checks`` 在包装器 ``pipeline_window`` 上直接调
    ``winfo_exists()`` / ``deiconify()`` / ``lift()`` / ``focus_force()``,但这些是
    Toplevel 实例上的方法,不在 ``PipelineWindow`` 包装器上。复现路径:
    ① 操作员首次点「检查并执行测试」→ ``self.pipeline_window = PipelineWindow(self)``
       ② 点「1. 环境线路检查」的「去配置」→ ``_open_network_config`` 调
          ``pipeline_window.window.withdraw()``(隐藏,但 ``self.pipeline_window`` 还在)
       ③ 再次点「检查并执行测试」→ ``self.pipeline_window is not None`` 走「拉前台」分支
          → ``self.pipeline_window.winfo_exists()`` 抛 AttributeError → 整个方法异常退出
          → 窗口没被重新显示 → 「没反应」。
    本测试通过源码静态断言 + MagicMock 模拟验证:
    ① ``_start_all_checks`` 必须通过 ``.window`` 走 Toplevel 方法
    ② 已存在 pipeline_window 包装器时,调用 _start_all_checks 不抛、正确调 deiconify/lift/focus_force
    ③ pipeline_window 为 None 时不抛、走「创建新 PipelineWindow」分支
    """

    def test_start_all_checks_delegates_to_window_attribute(self) -> None:
        """源码静态断言:_start_all_checks 必须通过 .window 走 Toplevel 方法。"""
        import inspect

        import line_check_assistant.app as app_module

        source = inspect.getsource(app_module.LineCheckAssistant._start_all_checks)
        self.assertIn("pipeline_window.window.winfo_exists", source)
        self.assertIn("pipeline_window.window.deiconify", source)
        self.assertIn("pipeline_window.window.lift", source)
        self.assertIn("pipeline_window.window.focus_force", source)
        # 反向断言:不能直接调包装器
        self.assertNotIn(
            "self.pipeline_window.winfo_exists(",
            source,
            "_start_all_checks 不能直接调包装器的 winfo_exists,会抛 AttributeError",
        )
        self.assertNotIn(
            "self.pipeline_window.deiconify(",
            source,
            "_start_all_checks 不能直接调包装器的 deiconify,会抛 AttributeError",
        )

    def test_start_all_checks_deiconifies_when_pipeline_window_exists(self) -> None:
        """已存在 pipeline_window 包装器时,操作员再点「检查并执行测试」应把窗口拉到前台。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(spec=["running", "pipeline_window"])
        fake_app.running = False
        # pipeline_window 包装器只挂 .window(只用到 winfo_exists/deiconify/lift/focus_force)
        fake_pipeline_window = MagicMock(spec=["window"])
        fake_pipeline_window.window.winfo_exists.return_value = True
        fake_app.pipeline_window = fake_pipeline_window

        app_module.LineCheckAssistant._start_all_checks(fake_app)

        # winfo_exists 调 1 次,确认窗口还在 → deiconify/lift/focus_force 各 1 次拉前台
        fake_pipeline_window.window.winfo_exists.assert_called_once()
        fake_pipeline_window.window.deiconify.assert_called_once()
        fake_pipeline_window.window.lift.assert_called_once()
        fake_pipeline_window.window.focus_force.assert_called_once()

    def test_start_all_checks_noop_when_already_running(self) -> None:
        """``self.running`` 为 True 时,_start_all_checks 直接 return,不调 window。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(spec=["running", "pipeline_window"])
        fake_app.running = True
        fake_app.pipeline_window = MagicMock(spec=["window"])

        app_module.LineCheckAssistant._start_all_checks(fake_app)

        # 不调 window 方法
        fake_app.pipeline_window.window.winfo_exists.assert_not_called()
        fake_app.pipeline_window.window.deiconify.assert_not_called()


if __name__ == "__main__":
    unittest.main()

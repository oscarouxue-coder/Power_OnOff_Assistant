"""「全流程执行」窗口构造、确认提示与上下文回归测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


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
        self._serial_log_directory = lambda: None


class BuildContextRegressionTests(unittest.TestCase):
    def test_pipeline_defaults_to_no_selected_subtasks(self) -> None:
        """打开全流程窗口时，7 个子任务必须全部不勾选。"""
        from line_check_assistant.pipeline_window import PipelineWindow
        from src.services.pipeline_orchestrator import SUBTASK_CODES

        self.assertTrue(SUBTASK_CODES)
        self.assertTrue(all(not PipelineWindow._default_checked(code) for code in SUBTASK_CODES))

    def test_pipeline_selection_uses_check_mark(self) -> None:
        """选中态必须显示标准勾号，未选中时保持空框。"""
        from line_check_assistant.pipeline_window import PipelineWindow

        self.assertEqual(PipelineWindow._selection_mark(True), "✓")
        self.assertEqual(PipelineWindow._selection_mark(False), "")

    def test_pipeline_confirmation_contains_manual_reboot_guard_for_empty_com(self) -> None:
        """空 COM 的全流程执行必须在启动后台线程前要求操作员确认手动重启。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn("请先手动重启样机", source)
        self.assertIn("确认样机已重启后再点击", source)

    def test_pipeline_confirmation_warns_legacy_start_all_powers_every_channel_off(self) -> None:
        """子任务7必须在启动前明确提示旧 Start All 的全通道断电动作。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn('"legacy_power_test" in selected', source)
        self.assertIn("危险操作提示：子任务7", source)
        self.assertIn("下发全通道断电指令", source)

    def test_pipeline_refreshes_statuses_after_returning_from_configuration(self) -> None:
        """关闭去配置子窗口并回到全流程窗口时，必须自动刷新缺项状态。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        init_source = inspect.getsource(pw_mod.PipelineWindow.__init__)
        focus_source = inspect.getsource(pw_mod.PipelineWindow._on_focus_in)
        self.assertIn('self.window.bind("<FocusIn>", self._on_focus_in)', init_source)
        self.assertIn("self._refresh_statuses()", focus_source)

    def test_pipeline_provides_manual_status_refresh_button(self) -> None:
        """操作员必须能显式刷新去配置后的必填项状态。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._build)
        self.assertIn('text="刷新状态", command=self._refresh_statuses', source)

    def test_pipeline_stop_button_is_moved_to_main_window(self) -> None:
        """全流程弹窗不再重复创建停止按钮。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._build)
        self.assertNotIn("self._stop_button", source)
        self.assertNotIn("command=self._on_stop", source)

    def test_main_stop_request_uses_existing_orchestrator_stop_event(self) -> None:
        from line_check_assistant.pipeline_window import PipelineWindow

        orchestrator = MagicMock()
        context = SimpleNamespace(
            _orchestrator=orchestrator,
            _stop_requested=False,
            _update_main_power_test_status=MagicMock(),
            _emit_to_main_log=MagicMock(),
        )

        stopped = PipelineWindow.request_stop(context)

        self.assertTrue(stopped)
        self.assertTrue(context._stop_requested)
        orchestrator.request_stop.assert_called_once_with()
        context._update_main_power_test_status.assert_called_once_with("stopping")
        context._emit_to_main_log.assert_called_once()

    def test_pipeline_lifecycle_updates_main_power_test_status(self) -> None:
        """开始、完成和失败路径都必须刷新主界面状态。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        start_source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        complete_source = inspect.getsource(pw_mod.PipelineWindow._on_pipeline_complete)
        failed_source = inspect.getsource(pw_mod.PipelineWindow._on_pipeline_failed)

        self.assertIn('_update_main_power_test_status("running")', start_source)
        self.assertIn("_update_main_power_test_progress(0, 0)", start_source)
        self.assertIn('"stopped" if self._stop_requested else "completed"', complete_source)
        self.assertIn('"stopped" if self._stop_requested else "failed"', failed_source)

    def test_pipeline_start_hides_configuration_window_after_thread_starts(self) -> None:
        """二次确认后必须先启动后台线程，再隐藏全流程配置窗口。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn("self.window.withdraw()", source)
        self.assertLess(source.index("self._running_thread.start()"), source.index("self.window.withdraw()"))
        self.assertIn("全流程配置窗口已自动隐藏", source)

    def test_pipeline_completion_dialogs_use_main_window_as_parent(self) -> None:
        """隐藏配置窗口后，完成和失败提示必须挂到可见主界面。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        complete_source = inspect.getsource(pw_mod.PipelineWindow._on_pipeline_complete)
        failed_source = inspect.getsource(pw_mod.PipelineWindow._on_pipeline_failed)
        self.assertIn("parent=self.app", complete_source)
        self.assertIn("parent=self.app", failed_source)
        self.assertNotIn("parent=self.window", complete_source)
        self.assertNotIn("parent=self.window", failed_source)

    @patch("line_check_assistant.pipeline_window.PipelineOrchestrator")
    def test_pipeline_thread_dispatches_completion_through_main_ui_queue(
        self, orchestrator_class
    ) -> None:
        """隐藏窗口后，完成回调必须走主程序 UI 队列，不能依赖 Toplevel.after。"""
        from line_check_assistant.pipeline_window import PipelineWindow

        results = [MagicMock()]
        orchestrator = orchestrator_class.return_value
        orchestrator.run.return_value = results
        app = SimpleNamespace(
            _invoke_pipeline_ui_action=MagicMock(
                side_effect=lambda action: action()
            )
        )
        context = PipelineWindow.__new__(PipelineWindow)
        context.app = app
        context._stop_requested = False
        context._orchestrator = None
        context._build_context = MagicMock(return_value=MagicMock())
        context._emit_to_main_log = MagicMock()
        context._on_pipeline_complete = MagicMock()
        context._on_pipeline_failed = MagicMock()

        context._run_pipeline_thread({"env_check"})

        app._invoke_pipeline_ui_action.assert_called_once()
        context._on_pipeline_complete.assert_called_once_with(results)
        context._on_pipeline_failed.assert_not_called()
        self.assertIsNone(context._orchestrator)
        source = __import__("inspect").getsource(PipelineWindow._run_pipeline_thread)
        self.assertNotIn("self.window.after", source)

    def test_main_stop_request_is_remembered_during_orchestrator_startup(self) -> None:
        """按钮刚启用但编排器尚未赋值时，停止请求不能丢失。"""
        from line_check_assistant.pipeline_window import PipelineWindow

        running_thread = MagicMock()
        running_thread.is_alive.return_value = True
        context = SimpleNamespace(
            _orchestrator=None,
            _running_thread=running_thread,
            _stop_requested=False,
            _update_main_power_test_status=MagicMock(),
            _emit_to_main_log=MagicMock(),
        )

        stopped = PipelineWindow.request_stop(context)

        self.assertTrue(stopped)
        self.assertTrue(context._stop_requested)
        context._update_main_power_test_status.assert_called_once_with("stopping")

    def test_pipeline_confirmation_uses_actual_prestart_order(self) -> None:
        """确认框必须把已勾选的串口日志显示在实际执行顺序首位。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn("actual_order = execution_order_for(selected)", source)
        self.assertIn("for code in actual_order:", source)
        self.assertIn("全流程开始时提前启动", source)

    def test_pipeline_confirmation_shows_power_to_next_wait_constraint(self) -> None:
        """勾选子任务 1 且有后续子任务时，确认框必须提示中间等待 120 秒。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertIn('"power_cycle" in actual_order', source)
        self.assertIn("子任务1完成后等待 120 秒，再开始后续已勾选子任务", source)

    def test_pipeline_confirmation_does_not_call_numbered_items_pipelines(self) -> None:
        """面向操作员的编号项统一称为子任务，不再显示管道1/后续管道。"""
        import inspect
        import line_check_assistant.pipeline_window as pw_mod

        source = inspect.getsource(pw_mod.PipelineWindow._on_start)
        self.assertNotIn("管道1", source)
        self.assertNotIn("后续已勾选管道", source)
        self.assertIn("子任务1", source)
        self.assertIn("后续已勾选子任务", source)

    def test_build_context_does_not_load_test_item_order_config(self) -> None:
        """移除 `[order]` 子任务后，全流程上下文不得再读取测试项目配置。"""
        import line_check_assistant.pipeline_window as pw_mod
        import inspect

        source = inspect.getsource(pw_mod.PipelineWindow._build_context)
        self.assertNotIn("TEST_ITEM_CONFIG_PATH", source)
        self.assertNotIn("TestItemConfigStore", source)
        self.assertNotIn("test_project_config=", source)

    def test_build_context_prefers_live_upgrade_and_onu_inputs(self) -> None:
        """去配置后，管道必须立即读取窗口当前输入而非启动时缓存。"""
        from line_check_assistant.onu_registration_store import OnuRegistrationConfig
        from line_check_assistant.pipeline_window import PipelineWindow
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings

        fake = FakeApp()
        stale_settings = SampleUpgradeSettings(username="")
        live_settings = SampleUpgradeSettings(username="sdmc", password="secret")
        stale_onu = OnuRegistrationConfig(username="")
        live_onu = OnuRegistrationConfig(username="zte")
        fake.sample_upgrade_settings = stale_settings
        fake.onu_registration_config = stale_onu
        fake._current_sample_upgrade_settings = MagicMock(return_value=live_settings)
        fake._current_onu_registration_config = MagicMock(return_value=live_onu)

        context = PipelineWindow._build_context(SimpleNamespace(app=fake))

        self.assertIs(context.sample_upgrade_settings, live_settings)
        self.assertIs(context.onu_registration, live_onu)
        fake._current_sample_upgrade_settings.assert_called_once_with()
        fake._current_onu_registration_config.assert_called_once_with()

    def test_compute_subtask_statuses_succeeds_with_minimal_app(self) -> None:
        """真实 _build_context 路径上 compute_all_subtask_statuses 必须不抛。"""
        from line_check_assistant.onu_registration_store import OnuRegistrationConfig
        from line_check_assistant.sample_upgrade_settings_store import (
            SampleUpgradeSettings,
        )
        from src.services.pipeline_orchestrator import (
            PipelineContext,
            compute_all_subtask_statuses,
        )
        fake = FakeApp()
        ctx = PipelineContext(
            app=fake,
            channels=fake.channels,
            sample_upgrade_settings=SampleUpgradeSettings(),
            onu_registration=OnuRegistrationConfig(),
            serial_log_dir=None,
        )
        statuses = compute_all_subtask_statuses(ctx)
        # 7 个子任务都必须有结果，且不包含 `[order]` 执行。
        self.assertEqual(len(statuses), 7)
        for code in (
            "env_check",
            "power_cycle",
            "sample_upgrade",
            "sample_parameter_write",
            "onu_registration",
            "serial_terminal",
            "legacy_power_test",
        ):
            self.assertIn(code, statuses)
            self.assertIsNotNone(statuses[code].summary)
            self.assertIsInstance(statuses[code].missing, tuple)
        self.assertNotIn("test_item_execution", statuses)


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

        fake_app = MagicMock(spec=["running", "pipeline_window", "power_test_running"])
        fake_app.running = False
        fake_app.power_test_running = False
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

    def test_start_all_checks_keeps_pipeline_window_hidden_while_running(self) -> None:
        """执行期间再次点击主入口，只提示状态，不重新弹出配置窗口。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(
            spec=["running", "pipeline_window", "power_test_running", "_log"]
        )
        fake_app.running = False
        fake_app.power_test_running = True
        fake_pipeline_window = MagicMock(spec=["window", "is_running"])
        fake_pipeline_window.is_running.return_value = True
        fake_app.pipeline_window = fake_pipeline_window

        app_module.LineCheckAssistant._start_all_checks(fake_app)

        fake_pipeline_window.window.deiconify.assert_not_called()
        fake_pipeline_window.window.lift.assert_not_called()
        fake_pipeline_window.window.focus_force.assert_not_called()
        fake_app._log.assert_called_once()

    def test_start_all_checks_recovers_stale_running_status(self) -> None:
        """线程已结束时不得继续提示“仍在执行”，应恢复状态并重新显示配置窗口。"""
        import line_check_assistant.app as app_module

        fake_app = MagicMock(
            spec=[
                "running",
                "pipeline_window",
                "power_test_running",
                "_set_power_test_status",
                "_log",
            ]
        )
        fake_app.running = False
        fake_app.power_test_running = True
        fake_pipeline_window = MagicMock(spec=["window", "is_running"])
        fake_pipeline_window.is_running.return_value = False
        fake_pipeline_window.window.winfo_exists.return_value = True
        fake_app.pipeline_window = fake_pipeline_window

        app_module.LineCheckAssistant._start_all_checks(fake_app)

        fake_app._set_power_test_status.assert_called_once_with("idle")
        self.assertIn("残留状态恢复为未运行", fake_app._log.call_args.args[0])
        fake_pipeline_window.window.deiconify.assert_called_once_with()

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

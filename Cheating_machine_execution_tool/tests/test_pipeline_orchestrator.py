"""pipeline_orchestrator 单元测试。

覆盖:
- 7 个 sub-task 状态评估(ready / missing / summary)
- run() 先预启动串口日志，其余任务按 1→7 相对顺序执行
- NON_FATAL_SUBTASKS 失败不阻塞后续
- 致命子任务失败 → 抛 PipelineError + 停止后续
- request_stop() 阻止后续子任务
- emit 主日志含「开始 / 结束 子任务」阶段标题
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.onu_registration_store import OnuRegistrationConfig
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
from src.services.pipeline_orchestrator import (
    NON_FATAL_SUBTASKS,
    SUBTASK_CODES,
    SUBTASK_LABELS,
    PipelineContext,
    PipelineError,
    PipelineOrchestrator,
    SubTaskResult,
    SubTaskStatus,
    compute_all_subtask_statuses,
    execution_order_for,
)


def _make_channel(section: str = "channel_2", enabled: bool = True) -> ChannelConfig:
    return ChannelConfig(
        section=section,
        vlan_name="VLAN110",
        adapter_alias="VLAN110",
        network_card_ip="192.168.1.110",
        device_manage_ip="192.168.1.1",
        subnet_mask="255.255.255.0",
        enabled=enabled,
    )


def _make_settings(**overrides) -> SampleUpgradeSettings:
    defaults = dict(
        upgrade_mode="全包升级",
        transfer_method="Tftp Put",
        execution_mode="串行",
        parallel_count=2,
        restore_factory=False,
        username="root",
        password="upgrade-secret",
        firmware_path=r"F:\firmware\tclinux_allinone",
        parameter_initial_username="telecomadmin",
        parameter_initial_password="nE7jA%5m",
        parameter_clear_parameters=False,
        parameter_exit_aging=False,
        power_operation="up",
        parameter_table_path=r"F:\data\params.xlsx",
    )
    defaults.update(overrides)
    return SampleUpgradeSettings(**defaults)


def _make_onu(**overrides) -> OnuRegistrationConfig:
    defaults = dict(
        olt_ip="172.18.18.151",
        source_ip="172.33.5.35",
        username="admin",
        password="olt-secret",
    )
    defaults.update(overrides)
    return OnuRegistrationConfig(**defaults)


def _make_context(**overrides) -> PipelineContext:
    """构造 PipelineContext,app 字段用 MagicMock 替代真实 LineCheckAssistant。"""
    app = MagicMock()
    app.power_serial_var.get.return_value = "COM102"
    app.power_serial_port = "COM102"
    channels = overrides.pop("channels", [_make_channel()])
    return PipelineContext(
        app=app,
        channels=channels,
        sample_upgrade_settings=overrides.pop("settings", _make_settings()),
        onu_registration=overrides.pop("onu", _make_onu()),
        serial_log_dir=overrides.pop("serial_log_dir", None),
        legacy_tool_root=overrides.pop("legacy_tool_root", None),
    )


class ComputeSubTaskStatusTests(unittest.TestCase):
    def test_power_cycle_status_with_complete_config(self) -> None:
        ctx = _make_context()
        status = compute_all_subtask_statuses(ctx)["power_cycle"]
        self.assertTrue(status.ready)
        self.assertEqual(status.missing, ())
        self.assertIn("COM102", status.summary)
        self.assertIn("up", status.summary)

    def test_power_cycle_status_without_com_is_ready_to_skip(self) -> None:
        ctx = _make_context()
        ctx.app.power_serial_var.get.return_value = ""
        status = compute_all_subtask_statuses(ctx)["power_cycle"]
        self.assertTrue(status.ready)
        self.assertEqual(status.missing, ())
        self.assertIn("未选，需手动重启", status.summary)

    def test_power_cycle_without_com_logs_skip_and_continues(self) -> None:
        ctx = _make_context()
        ctx.app.power_serial_var.get.return_value = ""
        messages: List[str] = []

        PipelineOrchestrator(ctx, messages.append)._run_power_cycle()

        self.assertIn("请手动重启样机后，再进行后续子任务", "".join(messages))

    @patch("src.services.power_on_service.power_on_selected_channels")
    @patch("src.services.power_on_service.turn_on_selected_channels")
    def test_power_cycle_up_only_sends_turn_on_commands(self, turn_on, power_cycle) -> None:
        """管道选择上电时只发开启帧，不能走断电再上电的旧接口。"""
        ctx = _make_context(settings=_make_settings(power_operation="up"))
        turn_on.return_value = MagicMock(ok=True, message="程控电源已上电。")

        PipelineOrchestrator(ctx, lambda _message: None)._run_power_cycle()

        turn_on.assert_called_once()
        self.assertEqual(turn_on.call_args.args, ("COM102", [2]))
        self.assertEqual(turn_on.call_args.kwargs["wait_seconds"], 0)
        power_cycle.assert_not_called()

    def test_power_cycle_status_missing_operation(self) -> None:
        ctx = _make_context(settings=_make_settings(power_operation="invalid"))
        status = compute_all_subtask_statuses(ctx)["power_cycle"]
        self.assertFalse(status.ready)
        self.assertIn("上/下电选项", status.missing)

    def test_sample_upgrade_status_complete(self) -> None:
        ctx = _make_context()
        status = compute_all_subtask_statuses(ctx)["sample_upgrade"]
        self.assertTrue(status.ready)
        self.assertEqual(status.missing, ())

    def test_sample_upgrade_status_missing_firmware(self) -> None:
        ctx = _make_context(settings=_make_settings(firmware_path=""))
        status = compute_all_subtask_statuses(ctx)["sample_upgrade"]
        self.assertFalse(status.ready)
        self.assertIn("升级固件路径", status.missing)

    def test_sample_upgrade_status_missing_credentials(self) -> None:
        ctx = _make_context(settings=_make_settings(username="", password=""))
        status = compute_all_subtask_statuses(ctx)["sample_upgrade"]
        self.assertFalse(status.ready)
        self.assertIn("超级用户名", status.missing)
        self.assertIn("超级用户密码", status.missing)

    def test_sample_upgrade_status_page_mode_ok(self) -> None:
        ctx = _make_context(settings=_make_settings(upgrade_mode="页面升级"))
        status = compute_all_subtask_statuses(ctx)["sample_upgrade"]
        self.assertTrue(status.ready)

    def test_sample_parameter_write_status_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            table_path = Path(temp_dir) / "params.xlsx"
            table_path.write_text("dummy", encoding="utf-8")
            ctx = _make_context(settings=_make_settings(parameter_table_path=str(table_path)))
            status = compute_all_subtask_statuses(ctx)["sample_parameter_write"]
            self.assertTrue(status.ready)
            self.assertIn("params.xlsx", status.summary)

    def test_sample_parameter_write_status_missing_table(self) -> None:
        ctx = _make_context(settings=_make_settings(parameter_table_path=""))
        status = compute_all_subtask_statuses(ctx)["sample_parameter_write"]
        self.assertFalse(status.ready)
        self.assertIn("参数表路径", status.missing)

    def test_sample_parameter_write_status_table_file_not_exist(self) -> None:
        ctx = _make_context(settings=_make_settings(parameter_table_path=r"F:\non\existent.xlsx"))
        status = compute_all_subtask_statuses(ctx)["sample_parameter_write"]
        self.assertFalse(status.ready)
        self.assertIn("参数表文件不存在", status.missing)

    def test_onu_registration_status_complete(self) -> None:
        ctx = _make_context()
        status = compute_all_subtask_statuses(ctx)["onu_registration"]
        self.assertTrue(status.ready)

    def test_onu_registration_status_missing_olt_ip(self) -> None:
        ctx = _make_context(onu=_make_onu(olt_ip=""))
        status = compute_all_subtask_statuses(ctx)["onu_registration"]
        self.assertFalse(status.ready)
        self.assertIn("OLT IP", status.missing)

    def test_onu_registration_status_requires_bound_source_ip(self) -> None:
        ctx = _make_context(onu=_make_onu(source_ip=""))
        status = compute_all_subtask_statuses(ctx)["onu_registration"]
        self.assertFalse(status.ready)
        self.assertIn("OLT 源 IP", status.missing)

    def test_serial_terminal_status_with_channels(self) -> None:
        ctx = _make_context(channels=[_make_channel()])
        status = compute_all_subtask_statuses(ctx)["serial_terminal"]
        self.assertTrue(status.ready)
        self.assertIn("1 通道", status.summary)

    def test_serial_terminal_status_no_channels(self) -> None:
        ctx = _make_context(channels=[])
        status = compute_all_subtask_statuses(ctx)["serial_terminal"]
        self.assertFalse(status.ready)
        self.assertIn("已勾选通道", status.missing)

    def test_order_execution_is_not_a_pipeline_subtask(self) -> None:
        """测试项配置保留为编辑器，但不得再出现在全流程状态或调度入口。"""
        import inspect

        statuses = compute_all_subtask_statuses(_make_context())
        source = inspect.getsource(PipelineOrchestrator)

        self.assertNotIn("test_item_execution", statuses)
        self.assertNotIn("_run_test_item_execution", source)

    @patch("src.services.legacy_power_test_service.prepare_legacy_power_test_request")
    def test_legacy_power_test_status_ready(self, prepare_request) -> None:
        prepare_request.return_value = MagicMock(
            communication_method="telnet",
            serial_port="COM102",
            selected_profile="TEST_PROJECT",
            channels=(MagicMock(),),
            number_of_tests=500,
        )
        ctx = _make_context(legacy_tool_root=Path("legacy-tool"))

        status = compute_all_subtask_statuses(ctx)["legacy_power_test"]

        self.assertTrue(status.ready)
        self.assertIn("COM102", status.summary)
        prepare_request.assert_called_once()

    def test_legacy_power_test_status_missing_tool_root(self) -> None:
        status = compute_all_subtask_statuses(_make_context())["legacy_power_test"]
        self.assertFalse(status.ready)
        self.assertIn("旧工具业务目录", status.missing)

    # ---- 环境线路检查(env_check)：当前固定为第 2 个致命步骤 ----

    def test_env_check_status_complete(self) -> None:
        ctx = _make_context()  # _make_channel 已包含完整 VLAN/IP
        status = compute_all_subtask_statuses(ctx)["env_check"]
        self.assertTrue(status.ready)
        self.assertEqual(status.missing, ())
        self.assertIn("1 通道已勾选", status.summary)

    def test_env_check_status_no_enabled_channels(self) -> None:
        ctx = _make_context(channels=[_make_channel(enabled=False)])
        status = compute_all_subtask_statuses(ctx)["env_check"]
        self.assertFalse(status.ready)
        self.assertIn("已勾选通道", status.missing)

    def test_env_check_status_missing_vlan(self) -> None:
        bad = _make_channel()
        bad.vlan_name = ""
        ctx = _make_context(channels=[bad])
        status = compute_all_subtask_statuses(ctx)["env_check"]
        self.assertFalse(status.ready)
        self.assertTrue(any("VLAN" in m for m in status.missing))

    def test_env_check_status_missing_multiple_fields(self) -> None:
        bad = _make_channel()
        bad.vlan_name = ""
        bad.adapter_alias = ""
        bad.network_card_ip = ""
        bad.device_manage_ip = ""
        ctx = _make_context(channels=[bad])
        status = compute_all_subtask_statuses(ctx)["env_check"]
        self.assertFalse(status.ready)
        joined = "".join(status.missing)
        self.assertIn("VLAN", joined)
        self.assertIn("网卡", joined)
        self.assertIn("PC 静态 IP", joined)
        self.assertIn("样机管理 IP", joined)


class PipelineRunOrderTests(unittest.TestCase):
    """验证串口日志预启动、其余任务顺序及非致命失败边界。"""

    @staticmethod
    def _patch_all_subtasks():
        """为每个子任务方法装上 mock,返回 ``(stack, method_mocks)``。

        使用方式::
            stack, method_mocks = PipelineRunOrderTests._patch_all_subtasks()
            with stack:
                orchestrator.run(...)
        """
        from contextlib import ExitStack
        method_mocks = {code: MagicMock() for code in SUBTASK_CODES}
        stack = ExitStack()
        stack.enter_context(
            patch.object(PipelineOrchestrator, "POWER_TO_NEXT_WAIT_SECONDS", 0)
        )
        for code, mock_obj in method_mocks.items():
            stack.enter_context(
                patch.object(PipelineOrchestrator, f"_run_{code}", mock_obj)
            )
        return stack, method_mocks

    def test_run_all_seven_subtasks_in_order(self) -> None:
        ctx = _make_context()
        emit_msgs: List[str] = []
        stack, method_mocks = self._patch_all_subtasks()
        with stack:
            orchestrator = PipelineOrchestrator(ctx, emit_msgs.append)
            results = orchestrator.run(set(SUBTASK_CODES))

        # 每个子任务方法都被调用 1 次
        for code in SUBTASK_CODES:
            method_mocks[code].assert_called_once()
        # 7 个结果都成功
        self.assertEqual(len(results), 7)
        self.assertTrue(all(r.ok for r in results))
        expected_order = [
            "serial_terminal",
            "power_cycle",
            "env_check",
            "sample_upgrade",
            "sample_parameter_write",
            "onu_registration",
            "legacy_power_test",
        ]
        self.assertEqual([result.code for result in results], expected_order)
        # 主日志含「开始 / 结束 子任务」 + 「全流程开始 / 结束」
        self.assertIn("全流程执行开始", "".join(emit_msgs))
        self.assertIn("全流程执行结束", "".join(emit_msgs))
        for code in SUBTASK_CODES:
            self.assertIn(f"开始子任务 {SUBTASK_LABELS[code]}", "".join(emit_msgs))
        self.assertIn("全流程预启动子任务 6. 串口日志", "".join(emit_msgs))

    def test_execution_order_keeps_serial_unselected_tasks_unchanged(self) -> None:
        self.assertEqual(
            execution_order_for({"power_cycle", "env_check", "legacy_power_test"}),
            ("power_cycle", "env_check", "legacy_power_test"),
        )

    def test_power_selected_waits_120_seconds_before_any_next_task(self) -> None:
        ctx = _make_context()
        ctx.stop_event = MagicMock()
        ctx.stop_event.is_set.return_value = False
        ctx.stop_event.wait.return_value = False
        events: List[str] = []

        with patch.object(
            PipelineOrchestrator,
            "_run_power_cycle",
            side_effect=lambda: events.append("power_cycle"),
        ), patch.object(
            PipelineOrchestrator,
            "_run_env_check",
            side_effect=lambda: events.append("env_check"),
        ):
            PipelineOrchestrator(ctx, events.append).run({"power_cycle", "env_check"})

        ctx.stop_event.wait.assert_called_once_with(120.0)
        self.assertLess(events.index("power_cycle"), events.index("env_check"))
        self.assertIn("等待 120 秒后再开始后续子任务", "".join(events))
        self.assertIn("120 秒等待完成", "".join(events))

    def test_power_only_does_not_wait_after_pipeline_finishes(self) -> None:
        ctx = _make_context()
        ctx.stop_event = MagicMock()
        ctx.stop_event.is_set.return_value = False

        with patch.object(PipelineOrchestrator, "_run_power_cycle"):
            PipelineOrchestrator(ctx, lambda _message: None).run({"power_cycle"})

        ctx.stop_event.wait.assert_not_called()

    def test_power_to_next_wait_can_be_stopped(self) -> None:
        ctx = _make_context()
        ctx.stop_event = MagicMock()
        ctx.stop_event.is_set.return_value = False
        ctx.stop_event.wait.return_value = True

        with patch.object(PipelineOrchestrator, "_run_power_cycle") as run_power, patch.object(
            PipelineOrchestrator, "_run_env_check"
        ) as run_next:
            messages: List[str] = []
            PipelineOrchestrator(ctx, messages.append).run({"power_cycle", "env_check"})

        run_power.assert_called_once_with()
        run_next.assert_not_called()
        self.assertIn("等待期间已请求停止", "".join(messages))

    def test_serial_terminal_prestart_is_marshaled_to_tk_ui_thread(self) -> None:
        open_serial = MagicMock()
        invoke_on_ui = MagicMock(side_effect=lambda action: action())
        ctx = _make_context()
        ctx.app = type(
            "SerialApp",
            (),
            {
                "_open_pipeline_serial_logs": open_serial,
                "_invoke_pipeline_ui_action": invoke_on_ui,
            },
        )()

        PipelineOrchestrator(ctx, lambda _message: None)._run_serial_terminal()

        invoke_on_ui.assert_called_once()
        open_serial.assert_called_once()

    def test_run_only_selected_subtasks(self) -> None:
        ctx = _make_context()
        emit_msgs: List[str] = []
        stack, method_mocks = self._patch_all_subtasks()
        with stack:
            orchestrator = PipelineOrchestrator(ctx, emit_msgs.append)
            results = orchestrator.run({"env_check", "power_cycle", "legacy_power_test"})

        # 只调用了选中的 3 个
        method_mocks["env_check"].assert_called_once()
        method_mocks["power_cycle"].assert_called_once()
        method_mocks["legacy_power_test"].assert_called_once()
        self.assertFalse(method_mocks["sample_upgrade"].called)
        self.assertFalse(method_mocks["onu_registration"].called)
        self.assertEqual(len(results), 3)

    def test_fatal_subtask_failure_raises_pipeline_error(self) -> None:
        ctx = _make_context()
        emit_msgs: List[str] = []
        stack, method_mocks = self._patch_all_subtasks()
        with stack:
            method_mocks["sample_upgrade"].side_effect = RuntimeError("升级失败")
            orchestrator = PipelineOrchestrator(ctx, emit_msgs.append)
            with self.assertRaises(PipelineError) as ctx_exc:
                orchestrator.run(set(SUBTASK_CODES))
        self.assertIn("sample_upgrade", str(ctx_exc.exception))
        # 串口日志已预启动，然后 power_cycle / env_check 已执行
        method_mocks["serial_terminal"].assert_called_once()
        method_mocks["env_check"].assert_called_once()
        method_mocks["power_cycle"].assert_called_once()
        # 升级失败后,后续子任务(写参 / ONU / 开关机测试)不执行
        method_mocks["sample_parameter_write"].assert_not_called()
        method_mocks["onu_registration"].assert_not_called()
        method_mocks["legacy_power_test"].assert_not_called()
        # 主日志含失败消息(编号 3 = sample_upgrade)
        self.assertIn("子任务 3. 样机升级 失败", "".join(emit_msgs))
        self.assertIn("全流程执行因失败提前终止", "".join(emit_msgs))

    def test_non_fatal_subtask_failure_continues(self) -> None:
        """「串口日志」失败不阻塞后续。"""
        ctx = _make_context()
        emit_msgs: List[str] = []
        stack, method_mocks = self._patch_all_subtasks()
        with stack:
            method_mocks["serial_terminal"].side_effect = RuntimeError("终端打不开")
            orchestrator = PipelineOrchestrator(ctx, emit_msgs.append)
            # 串口日志失败,7 项全选 → 不应抛 PipelineError
            results = orchestrator.run(set(SUBTASK_CODES))

        # 串口已执行(失败);后续子任务(执行开关机测试)继续
        method_mocks["serial_terminal"].assert_called_once()
        method_mocks["legacy_power_test"].assert_called_once()
        # 串口结果 ok=False
        serial_result = next(r for r in results if r.code == "serial_terminal")
        self.assertFalse(serial_result.ok)
        # 执行开关机测试结果 ok=True
        legacy_result = next(r for r in results if r.code == "legacy_power_test")
        self.assertTrue(legacy_result.ok)

    def test_request_stop_skips_subsequent_subtasks(self) -> None:
        ctx = _make_context()
        emit_msgs: List[str] = []
        orchestrator_ref: List[PipelineOrchestrator] = []
        stack, method_mocks = self._patch_all_subtasks()
        with stack:
            def stop_after_power_cycle() -> None:
                orchestrator_ref[0].request_stop()
            method_mocks["power_cycle"].side_effect = stop_after_power_cycle
            orchestrator_ref.append(PipelineOrchestrator(ctx, emit_msgs.append))
            orchestrator_ref[0].run(set(SUBTASK_CODES))

        # 串口日志先预启动，power_cycle 执行后请求停止；后续全部跳过。
        method_mocks["serial_terminal"].assert_called_once()
        method_mocks["power_cycle"].assert_called_once()
        for code in (
            "env_check",
            "sample_upgrade",
            "sample_parameter_write",
            "onu_registration",
            "legacy_power_test",
        ):
            method_mocks[code].assert_not_called()
        self.assertIn("已请求停止", "".join(emit_msgs))


class SampleUpgradeDispatchTests(unittest.TestCase):
    def test_full_package_upgrade_uses_main_program_unified_serial_entry(self) -> None:
        """Tftp指令 / Tftp Put 必须共用当前存在的主程序入口，再由其内部独立分流。"""
        for transfer_method in ("Tftp指令", "Tftp Put"):
            with self.subTest(transfer_method=transfer_method):
                ctx = _make_context(settings=_make_settings(transfer_method=transfer_method))
                start_serial_upgrade = MagicMock()
                ctx.app = type(
                    "UpgradeApp",
                    (),
                    {"_start_serial_tftp_copy_upgrade": start_serial_upgrade},
                )()
                messages: List[str] = []

                PipelineOrchestrator(ctx, messages.append)._run_sample_upgrade()

                start_serial_upgrade.assert_called_once_with()
                self.assertIn(transfer_method, "".join(messages))

    def test_async_subtasks_use_main_program_completion_bridges(self) -> None:
        """真实主程序有桥接时，管道不能只启动线程就进入下一项。"""
        ctx = _make_context()
        run_upgrade = MagicMock()
        run_parameter_write = MagicMock()
        ctx.app = type(
            "PipelineApp",
            (),
            {
                "_run_pipeline_sample_upgrade": run_upgrade,
                "_run_pipeline_sample_parameter_write": run_parameter_write,
            },
        )()

        orchestrator = PipelineOrchestrator(ctx, lambda _line: None)
        orchestrator._run_sample_upgrade()
        orchestrator._run_sample_parameter_write()

        run_upgrade.assert_called_once_with()
        run_parameter_write.assert_called_once_with()

    def test_unattended_execution_forwards_one_time_confirmation_authorization(self) -> None:
        ctx = _make_context()
        ctx.unattended_execution = True
        run_upgrade = MagicMock()
        run_parameter_write = MagicMock()
        ctx.app = type(
            "PipelineApp",
            (),
            {
                "_run_pipeline_sample_upgrade": run_upgrade,
                "_run_pipeline_sample_parameter_write": run_parameter_write,
            },
        )()

        orchestrator = PipelineOrchestrator(ctx, lambda _line: None)
        orchestrator._run_sample_upgrade()
        orchestrator._run_sample_parameter_write()

        run_upgrade.assert_called_once_with(skip_confirmation=True)
        run_parameter_write.assert_called_once_with(skip_confirmation=True)


class LegacyPowerTestDispatchTests(unittest.TestCase):
    @patch("src.services.legacy_power_test_service.run_legacy_power_test")
    @patch("src.services.legacy_power_test_service.prepare_legacy_power_test_request")
    def test_legacy_power_test_delegates_to_headless_service(
        self,
        prepare_request,
        run_power_test,
    ) -> None:
        prepared = MagicMock()
        prepare_request.return_value = prepared
        run_power_test.return_value = MagicMock(ok=True, detail="完成")
        ctx = _make_context(legacy_tool_root=Path("legacy-tool"))
        ctx.app._invoke_pipeline_ui_action.side_effect = lambda action: action()
        emitted: List[str] = []

        PipelineOrchestrator(ctx, emitted.append)._run_legacy_power_test()

        prepare_request.assert_called_once()
        channels = tuple(prepare_request.call_args.args[1])
        self.assertEqual(channels[0].number, 2)
        self.assertEqual(channels[0].network_card_ip, "192.168.1.110")
        run_power_test.assert_called_once()
        args = run_power_test.call_args.args
        self.assertEqual(args, (prepared, emitted.append, ctx.stop_event))
        progress_callback = run_power_test.call_args.kwargs["on_progress"]
        progress_callback(12, 500)
        ctx.app._set_power_test_progress.assert_called_once_with(12, 500)
        ctx.app._invoke_pipeline_ui_action.assert_called_once()


class SubTaskResultTests(unittest.TestCase):
    def test_subtask_result_ok(self) -> None:
        r = SubTaskResult(code="power_cycle", ok=True)
        self.assertIsNone(r.error)
        self.assertIsNone(r.detail)

    def test_subtask_result_failure(self) -> None:
        r = SubTaskResult(code="power_cycle", ok=False, error="failed")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "failed")


class ConstantsTests(unittest.TestCase):
    def test_subtask_codes_in_order(self) -> None:
        self.assertEqual(
            SUBTASK_CODES,
            (
                "power_cycle",
                "env_check",
                "sample_upgrade",
                "sample_parameter_write",
                "onu_registration",
                "serial_terminal",
                "legacy_power_test",
            ),
        )

    def test_non_fatal_subtasks_contains_only_serial(self) -> None:
        self.assertEqual(NON_FATAL_SUBTASKS, frozenset({"serial_terminal"}))

    def test_subtask_labels_numbering_is_one_to_seven(self) -> None:
        """编号从 1 开始到 7，且 `[order]` 执行不得回到全流程。"""
        expected = {
            "power_cycle": "1. ",
            "env_check": "2. ",
            "sample_upgrade": "3. ",
            "sample_parameter_write": "4. ",
            "onu_registration": "5. ",
            "serial_terminal": "6. ",
            "legacy_power_test": "7. ",
        }
        self.assertNotIn("test_item_execution", SUBTASK_CODES)
        self.assertNotIn("test_item_execution", SUBTASK_LABELS)
        self.assertEqual(set(SUBTASK_LABELS.keys()), set(expected.keys()))
        for code, prefix in expected.items():
            self.assertTrue(
                SUBTASK_LABELS[code].startswith(prefix),
                f"SUBTASK_LABELS[{code!r}] = {SUBTASK_LABELS[code]!r}, 期望以 {prefix!r} 开头",
            )


if __name__ == "__main__":
    unittest.main()

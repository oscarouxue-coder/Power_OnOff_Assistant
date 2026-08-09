"""项目级回归基线检查脚本(Q1=A 的工程兑现)。

封装 `ACCEPTANCE_BASELINE.md §0 / §1.3 / §1.4` 的全部检查,作为提交前必跑的最低门禁
(参见 `AGENTS.md` 规则 13 与 `.claude/skills/line-check-dev/SKILL.md §5 / §11`)。

执行 6 类检查:
1. **py_compile**: 全量 `src/` + `line_check_assistant/` 下的关键模块能编译
2. **compile_inventory**: `src/` / `line_check_assistant/` 的每个 Python 源文件都必须纳入编译清单
3. **unittest**: 全量测试通过,且能解析 `Ran N tests` 行(防止静默 0 项 / 误报 OK)
4. **required_baseline_tests**: 已验收关键行为的指定测试 ID 必须实际执行
5. **must_exist**: §1.3 的 8 条协议不变量必须在指定目录下命中
6. **must_not_exist**: §1.3 / §1.4 的禁止模式(`0.0.0.0` 等)不能在指定文件的**代码行**中出现
   (跳过注释 / 文档字符串,避免反向语义误报)

退出码: 0 全部通过 / 1 任一失败。

设计要点:
- **单一来源**: `MUST_EXIST` / `MUST_NOT_EXIST` / `PY_COMPILE_FILES` 三个常量在本文件;
  `AGENTS.md` 中同名章节是可读副本,改任何一处都必须同步另一处。
- **跨平台**: 纯 Python + 标准库,Windows / Linux / macOS 直接可跑。
- **可测试**: 核心检查函数是纯函数,接受 `project_root: Path`,用 `tempfile.TemporaryDirectory`
  构造临时源码即可单元测试(参见 `tests/test_verify_baseline.py`)。
- **不引入新依赖**: 仅用 `subprocess` / `pathlib` / `re` / `sys`。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple


# 匹配三引号字符串(文档字符串 / 长字符串),用于在 grep 时跳过。
_DOCSTRING_PATTERN = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', re.MULTILINE)


class CheckResult(NamedTuple):
    """单条检查结果。"""

    name: str
    passed: bool
    detail: str = ""

    def render(self) -> str:
        marker = "OK  " if self.passed else "FAIL"
        suffix = f" - {self.detail}" if self.detail else ""
        return f"  [{marker}] {self.name}{suffix}"


# 1. py_compile 文件清单(以 `ACCEPTANCE_BASELINE.md §0` + 当前 `src/` / `line_check_assistant/`
#    下全部 .py 为准;新增 .py 后必须手工补到本列表)。
PY_COMPILE_FILES: tuple[str, ...] = (
    # line_check_assistant 包
    "line_check_assistant/__init__.py",
    "line_check_assistant/app.py",
    "line_check_assistant/config_store.py",
    "line_check_assistant/legacy_ui_defaults_store.py",
    "line_check_assistant/network_ops.py",
    "line_check_assistant/onu_registration_store.py",
    "line_check_assistant/old_tool_automation.py",
    "line_check_assistant/old_tool_config.py",
    "line_check_assistant/packaging_hooks/hook-_tkinter.py",
    "line_check_assistant/packaging_hooks/pre_find_module_path/hook-tkinter.py",
    "line_check_assistant/page_upgrade.py",
    "line_check_assistant/paths.py",
    "line_check_assistant/pipeline_window.py",
    "line_check_assistant/sample_upgrade_settings_store.py",
    "line_check_assistant/serial_ports.py",
    "line_check_assistant/subprocess_window.py",
    "line_check_assistant/test_item_config_store.py",
    # src 包
    "src/__init__.py",
    "src/config.py",
    "src/core/__init__.py",
    "src/ui/serial_terminal.py",
    "src/ui/dut_config_window.py",
    "src/services/pipeline_orchestrator.py",
    "src/services/dut_config_service.py",
    "src/services/dut_advanced_config_service.py",
    "src/services/dut_status_query_service.py",
    "src/services/dut_wan_query_service.py",
    "src/services/legacy_power_test_service.py",
    "src/services/power_on_service.py",
    "src/services/sample_parameter_service.py",
    "src/services/serial_upgrade_service.py",
    "src/services/test_item_execution_service.py",
    "src/core/bind_socket.py",
    "src/core/dut_ubus_config.py",
    "src/core/fuzzy_match_runner.py",
    "src/core/parameter_session.py",
    "src/core/power_supply.py",
    "src/core/sample_parameter_table.py",
    "src/core/serial_transport.py",
    "src/core/telnet_transport.py",
    "src/core/tftp_transport.py",
    "src/core/ubus_enable_telnet.py",
    "src/core/ubus_http_client.py",
    "src/core/wifi_interfaces.py",
    "src/models/sample_parameter_models.py",
    "src/models/dut_config_models.py",
    "src/models/serial_models.py",
    "src/models/__init__.py",
    "src/services/__init__.py",
    "src/ui/__init__.py",
)

# 关键已验收行为的回归用例。全量 unittest 必须实际执行这些 ID，避免测试文件或
# 用例在重构时被静默删除 / 改名而使已验收边界失去保护。
REQUIRED_BASELINE_TEST_IDS: tuple[str, ...] = (
    "test_tftp_transport.TftpTransportTests.test_server_binds_transfer_data_socket_to_listening_vlan_ip",
    "test_tftp_transport.TftpTransportTests.test_upload_binds_requested_source_ip_and_uses_requested_remote_name",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_full_package_upgrade_tftp_put_runs_full_flow_after_power_cycle",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_login_boot_salvages_after_garbled_username_echo",
    "test_power_supply.PowerSupplyTests.test_controller_turns_on_all_requested_channels_one_second_apart_without_powering_off",
    "test_power_supply.PowerSupplyTests.test_empty_power_serial_port_skips_power_operation_without_opening_port",
    "test_sample_parameter_service.SampleParameterPipelineOptionTests.test_clear_parameters_default_off_does_not_send_ppctl_clear",
    "test_sample_parameter_service.SampleParameterPipelineOptionTests.test_both_options_off_skips_both_commands",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_run_all_seven_subtasks_in_order",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_power_selected_waits_120_seconds_before_any_next_task",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_defaults_to_no_selected_subtasks",
    "test_app.CurrentChannelSelectionTests.test_power_test_progress_uses_configured_total_and_clamps_value",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_cycle_progress_uses_slowest_selected_channel",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_cycle_start_confirms_previous_cycle_for_power_only_mode",
    "test_test_item_config_store.TestItemConfigStoreTests.test_save_and_load_round_trip",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_headless_onu_config_uses_all_wifi_profile_fields",
    "test_wifi_interfaces.WifiInterfaceTests.test_names_are_trimmed_deduplicated_and_keep_discovery_order",
    "test_network_ops.PrepareNetworkForSampleTests.test_reads_adapter_enabled_state_and_ipv4_prefix",
    "test_network_ops.PrepareNetworkForSampleTests.test_reuses_ready_adapter_without_enable_or_set",
    "test_network_ops.EnableAdapterTests.test_line_check_enables_adapter_before_setting_ip_and_ping",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_prepare_tftp_network_waits_for_bindable_ip_before_strict_server",
    "test_page_upgrade.PageUpgradeTests.test_single_page_upgrade_prepares_network_on_same_subnet_before_login",
    "test_sample_parameter_app.SampleParameterAppNetworkPreflightTests.test_factory_prepares_network_before_ubus",
    "test_test_item_execution_service.TestItemExecutionSingleCommandTests.test_single_command_match_success",
    "test_dut_config_service.DutConfigServiceTests.test_single_success_prepares_network_enables_ubus_and_probes_port",
    "test_dut_config_service.DutConfigServiceTests.test_batch_stop_does_not_start_later_requests",
    "test_dut_ubus_config.DutUbusConfigTests.test_build_dual_stack_static_ipv4_and_dhcpv6_payload",
    "test_dut_ubus_config.DutUbusConfigTests.test_build_iptv_multicast_vlan_is_optional_and_ignored_by_other_services",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connection_names_filters_non_wan_and_sorts_by_index",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_complete_ipoe_snapshot",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_iptv_multicast_vlan",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_pppoe_dual_stack_static_fields",
    "test_dut_ubus_config.DutUbusConfigTests.test_voice_config_sets_server_account_codecs_and_reads_back",
    "test_dut_ubus_config.DutUbusConfigTests.test_tr069_config_sets_plaintext_credentials_and_verifies_readback",
    "test_dut_ubus_config.DutUbusConfigTests.test_voice_status_query_reads_selected_line_servers_mode_and_codecs",
    "test_dut_ubus_config.DutUbusConfigTests.test_tr069_status_query_maps_management_server_without_manual_inform_action",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_single_wan_success_prepares_network_logs_in_and_closes_client",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_iptv_multicast_vlan_is_optional_but_validated_when_present",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_voice_sip_mode_accepts_imssip_and_rejects_unknown_values",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_single_query_prepares_network_logs_real_get_and_closes_client",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_consecutive_queries_release_previous_device_session",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_common_names_requires_every_target_and_exact_name_match",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_common_details_requires_identical_snapshot_on_every_target",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_single_voice_query_reuses_network_logs_out_and_returns_settings",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_consecutive_status_queries_release_previous_device_session",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_common_settings_requires_every_target_success_and_exact_match",
    "test_telnet_transport.TelnetSessionTests.test_probe_binds_requested_source_ip_and_closes_immediately",
    "test_ubus_enable_telnet.EnableTelnetViaUbusTests.test_operation_logs_include_real_paths_and_plaintext_password",
    "test_ubus_http_client.UbusHttpClientTests.test_logout_releases_device_session_and_clears_local_reference",
    "test_ubus_http_client.UbusHttpClientTests.test_close_best_effort_logs_out_active_session_once",
    "test_app.CurrentChannelSelectionTests.test_dut_config_window_is_extensible_and_dispatches_through_service",
    "test_app.CurrentChannelSelectionTests.test_voice_and_tr069_tabs_query_current_status_and_map_common_values",
    "test_app.CurrentChannelSelectionTests.test_status_display_only_applies_settings_when_batch_has_safe_common_value",
    "test_app.CurrentChannelSelectionTests.test_dut_option_checkbuttons_use_native_checkmark_indicator",
    "test_app.CurrentChannelSelectionTests.test_dut_form_field_names_are_left_aligned_in_every_tab",
    "test_app.CurrentChannelSelectionTests.test_wan_form_rules_hide_irrelevant_fields_and_apply_protocol_mtu",
    "test_app.CurrentChannelSelectionTests.test_wan_address_modes_follow_supported_dual_stack_combinations",
    "test_app.CurrentChannelSelectionTests.test_wan_lan_port_multiselect_maps_masks_and_preserves_non_lan_bits",
    "test_app.CurrentChannelSelectionTests.test_iptv_multicast_vlan_field_is_conditional_and_mapped",
    "test_app.CurrentChannelSelectionTests.test_voice_sip_mode_options_include_ont_imssip_without_removing_existing_modes",
    "test_app.CurrentChannelSelectionTests.test_wan_existing_connections_use_readonly_query_dropdown",
    "test_app.CurrentChannelSelectionTests.test_wan_connection_snapshot_maps_to_current_form_values",
    "test_app.CurrentChannelSelectionTests.test_selecting_existing_wan_replaces_stale_form_values",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_pppoe_static_ipv6_and_invalid_dual_stack_pair_are_rejected",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_confirmation_does_not_call_numbered_items_pipelines",
    "test_pipeline_window.BuildContextRegressionTests.test_main_stop_request_uses_existing_orchestrator_stop_event",
    "test_app.CurrentChannelSelectionTests.test_main_card_shows_power_test_status_and_stop_button",
    "test_app.CurrentChannelSelectionTests.test_power_test_status_styles_are_prominent_and_state_specific",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_start_hides_configuration_window_after_thread_starts",
    "test_app.CurrentChannelSelectionTests.test_main_header_copy_is_removed_and_admin_status_moves_to_toolbar",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_thread_dispatches_completion_through_main_ui_queue",
    "test_pipeline_window.StartAllChecksRegressionTests.test_start_all_checks_recovers_stale_running_status",
    "test_app.CurrentChannelSelectionTests.test_pipeline_serial_logs_show_then_open_all",
    "test_serial_terminal.SerialTerminalPersistenceTests.test_serial_log_path_includes_vlan_port_and_open_date",
    "test_serial_transport.SerialTransportTests.test_log_file_prefixes_every_serial_line_and_joins_split_rx_chunks",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_fatal_subtask_failure_raises_pipeline_error",
    "test_test_item_config_store.TestItemConfigStoreTests.test_save_writes_retry_interval_only_to_legacy_other_config",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_parent_forwards_legacy_logs_and_waits_for_result",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_service_does_not_import_or_construct_old_gui_entry",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_power_frame_is_rendered_in_execution_log_format",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_result_file_success_line_is_forwarded_without_changing_file",
    "test_pipeline_orchestrator.LegacyPowerTestDispatchTests.test_legacy_power_test_delegates_to_headless_service",
)

# 2. 必须命中(§1.3 / §1.4) - (pattern, 搜索目录组)
MUST_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bbfdm.operate", ("src/", "line_check_assistant/")),
    ("tclinux_allinone", ("src/",)),
    ("192.168.1.1", ("src/",)),
    ("vlan_to_serial_port", ("src/", "line_check_assistant/")),
    ("MAX_PARALLEL_UPGRADES = 8", ("src/", "line_check_assistant/")),
    ("clamp_parallel_count", ("src/", "line_check_assistant/")),
    ("source_address=(bind_ip, 0)", ("src/", "line_check_assistant/")),
    ("Device.Firewall.<X_SDMC_>Security.AccessCtrl", ("src/",)),
)

# 3. 必须不出现(§1.3 / §1.4) - (pattern, 限制文件列表)
MUST_NOT_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0.0.0.0", ("src/core/tftp_transport.py", "src/core/telnet_transport.py")),
)


def _glob_py_files(project_root: Path, dirs: Iterable[str]) -> list[Path]:
    """在 `dirs` 下递归收集所有 `.py` 文件。目录不存在时静默跳过。"""
    files: list[Path] = []
    for d in dirs:
        base = project_root / d
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _is_code_line(line: str) -> bool:
    """判断是否为代码行(排除纯注释行)。

    用于 `must_not_exist` 避开反向语义注释(如「不回退 0.0.0.0」)导致的误报。
    """
    return not line.lstrip().startswith("#")


def _strip_docstrings(content: str) -> str:
    """把三引号字符串(文档字符串 / 长字符串)替换为同长度的空白,保留行号。

    行内 `\n` 保留为空行,其余字符替换为空格。这样后续 grep `pattern in content`
    时,文档字符串里出现的禁止字符串(如「不回退 0.0.0.0」)不会触发误报。
    """
    def replace_with_whitespace(match: re.Match) -> str:
        text = match.group(0)
        return "".join("\n" if c == "\n" else " " for c in text)

    return _DOCSTRING_PATTERN.sub(replace_with_whitespace, content)


def _code_lines(content: str) -> list[tuple[int, str]]:
    """返回 (行号 1-based, 行内容) 列表,跳过文档字符串 + 纯注释行。"""
    stripped = _strip_docstrings(content)
    return [
        (idx + 1, line)
        for idx, line in enumerate(stripped.splitlines())
        if _is_code_line(line)
    ]


def run_py_compile(project_root: Path) -> CheckResult:
    """对 `PY_COMPILE_FILES` 全部运行 `python -m py_compile`。"""
    files = [str(project_root / f) for f in PY_COMPILE_FILES]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return CheckResult(
            "py_compile",
            False,
            f"missing files: {', '.join(Path(m).name for m in missing)}",
        )
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", *files],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if proc.returncode == 0:
        return CheckResult("py_compile", True, f"{len(files)} files compiled")
    return CheckResult("py_compile", False, (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "unknown error")


def check_py_compile_inventory(project_root: Path) -> CheckResult:
    """保证新增主程序 Python 文件不会漏出 `PY_COMPILE_FILES`。"""
    discovered = {
        str(path.relative_to(project_root)).replace("\\", "/")
        for path in _glob_py_files(project_root, ("src/", "line_check_assistant/"))
    }
    declared = set(PY_COMPILE_FILES)
    undeclared = sorted(discovered - declared)
    if undeclared:
        return CheckResult(
            "compile_inventory",
            False,
            f"source files missing from PY_COMPILE_FILES: {', '.join(undeclared)}",
        )
    return CheckResult("compile_inventory", True, f"{len(discovered)} source files covered")


def missing_required_baseline_tests(unittest_output: str) -> list[str]:
    """从 verbose unittest 输出中找出未执行的关键回归用例。"""
    executed_test_ids = {
        f"{test_class}.{test_name}"
        for test_name, test_class in re.findall(
            r"(?m)^(test_\w+) \(([\w.]+)\)", unittest_output
        )
    }
    return [
        test_id
        for test_id in REQUIRED_BASELINE_TEST_IDS
        if test_id not in executed_test_ids
    ]


def check_required_baseline_tests(unittest_output: str) -> CheckResult:
    """输出关键已验收行为测试的实际执行结果。"""
    missing = missing_required_baseline_tests(unittest_output)
    if missing:
        return CheckResult(
            "required_baseline_tests",
            False,
            f"not executed: {', '.join(missing)}",
        )
    return CheckResult(
        "required_baseline_tests",
        True,
        f"{len(REQUIRED_BASELINE_TEST_IDS)} required tests executed",
    )


def run_unittest(project_root: Path) -> tuple[CheckResult, str]:
    """运行全量单测，并返回 verbose 输出供关键测试执行检查复用。"""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    output = proc.stdout + proc.stderr
    match = re.search(r"Ran (\d+) tests?", output)
    if proc.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-5:])
        return CheckResult("unittest", False, f"non-zero exit; tail: {tail}"), output
    if match is None:
        return (
            CheckResult(
                "unittest",
                False,
                f"could not parse 'Ran N tests' from output; tail: {output[-200:]}",
            ),
            output,
        )
    return CheckResult("unittest", True, f"Ran {match.group(1)} tests"), output


def check_must_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_EXIST` pattern 是否在指定目录下命中。"""
    results: list[CheckResult] = []
    for pattern, dir_groups in MUST_EXIST:
        files = _glob_py_files(project_root, dir_groups)
        found_in: list[str] = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern in content:
                found_in.append(str(f.relative_to(project_root)))
        if found_in:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=True,
                    detail=f"hit in {found_in[0]}" + (f" (+{len(found_in) - 1})" if len(found_in) > 1 else ""),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=False,
                    detail=f"not found in {','.join(dir_groups)}",
                )
            )
    return results


def check_must_not_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_NOT_EXIST` pattern 是否在限制文件的**代码行**中出现。

    跳过纯注释行(以 `#` 开头)以避免反向语义注释(例如「不回退 0.0.0.0」)误报。
    """
    results: list[CheckResult] = []
    for pattern, file_paths in MUST_NOT_EXIST:
        bad_locations: list[str] = []
        for fp in file_paths:
            full = project_root / fp
            if not full.exists():
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_no, line in _code_lines(content):
                if pattern in line:
                    bad_locations.append(f"{fp}:{line_no}")
                    break  # 每个文件只报一次,避免重复
        if bad_locations:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=False,
                    detail=f"found in code lines: {','.join(bad_locations)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=True,
                    detail=f"absent from code lines of {','.join(file_paths)}",
                )
            )
    return results


def collect_results(project_root: Path) -> list[CheckResult]:
    """串联所有基线检查,返回完整结果列表。"""
    results: list[CheckResult] = []
    results.append(run_py_compile(project_root))
    results.append(check_py_compile_inventory(project_root))
    unittest_result, unittest_output = run_unittest(project_root)
    results.append(unittest_result)
    if unittest_result.passed:
        results.append(check_required_baseline_tests(unittest_output))
    results.extend(check_must_exist(project_root))
    results.extend(check_must_not_exist(project_root))
    return results


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Project root: {project_root}")
    print()

    results = collect_results(project_root)
    for r in results:
        print(r.render())

    print()
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"FAILED: {len(failed)} check(s) failed")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

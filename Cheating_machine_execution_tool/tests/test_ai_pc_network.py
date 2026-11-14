"""目标网卡诊断专项：仅模拟Windows查询，不修改本机网络或访问DUT。"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core import ai_pc_network as network
from src.core.ai_debug_transport import DebugConnectionUnavailable
from src.services.ai_debug_service import DiagnosticToolExecutor, tool_schemas
from src.services.ai_conversation_service import conversation_tools, CHAT_INSTRUCTIONS
from src.services.ai_diagnostic_service import SYSTEM_INSTRUCTIONS
from src.utils.ai_output import format_diagnostic_evidence
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_debug import TARGET


def adapter(name=TARGET.vlan, ip=TARGET.bind_ip, admin=1, operational=1, media=1):
    return {"name": name, "guid": "guid-" + name, "index": 116, "status": "Up",
            "admin_status": admin, "operational_status": operational, "media_state": media,
            "addresses": [{"ip": ip, "prefix": 24, "state": "Preferred"}] if ip else []}


class AssessmentTests(unittest.TestCase):
    def assess(self, *items):
        return network.assess_adapters(TARGET, list(items))

    def test_disabled_adapter_without_ip_is_confirmed_by_admin_state(self):
        result = self.assess(adapter(ip=None, admin=2, operational=2, media=0))
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["match_basis"], "exact_alias")
        self.assertIs(result["source_usable"], False)
        self.assertEqual(result["adapter"]["admin_status"], 2)

    def test_disconnected_link_is_not_disabled_or_definite_source_failure(self):
        result = self.assess(adapter(operational=2, media=2))
        self.assertEqual(result["status"], "link_disconnected")
        self.assertIsNone(result["source_usable"])

    def test_changed_ip_is_source_missing(self):
        result = self.assess(adapter(ip="192.168.1.250"))
        self.assertEqual(result["status"], "source_ip_missing")
        self.assertIs(result["source_usable"], False)

    def test_missing_alias_and_address_are_not_proof_of_disabled_adapter(self):
        result = self.assess(adapter(name="other", ip="192.168.1.250"))
        self.assertEqual(result["status"], "adapter_not_found")
        self.assertNotIn("adapter", result)

    def test_ready_adapter_does_not_assert_dut_reachability(self):
        result = self.assess(adapter())
        self.assertEqual(result["status"], "ready")
        self.assertIs(result["source_usable"], True)
        self.assertIn("尚未验证DUT可达", result["conclusion"])

    def test_operational_down_alone_is_unknown(self):
        result = self.assess(adapter(operational=2))
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["source_usable"])

    def test_unique_source_on_other_alias_is_only_a_candidate(self):
        result = self.assess(adapter(name="renamed"))
        self.assertEqual(result["status"], "identity_unconfirmed")
        self.assertEqual(result["match_basis"], "unique_source_ip_candidate")
        self.assertNotIn("adapter", result)
        self.assertIsNone(result["source_usable"])

    def test_source_on_other_adapter_does_not_override_configured_alias(self):
        result = self.assess(adapter(ip=None, admin=2), adapter(name="other"))
        self.assertEqual(result["status"], "identity_conflict")
        self.assertIsNone(result["source_usable"])

    def test_duplicate_source_or_alias_is_conflict(self):
        for items in ((adapter(), adapter(name="other")), (adapter(), adapter(ip=None))):
            with self.subTest(items=items):
                self.assertEqual(self.assess(*items)["status"], "identity_conflict")

    def test_alias_comparison_is_exact_case_insensitive(self):
        self.assertEqual(self.assess(adapter(name="  " + TARGET.vlan.upper() + "  "))["status"], "ready")
        self.assertEqual(self.assess(adapter(name=TARGET.vlan + "0", ip=None))["status"], "adapter_not_found")

    def test_tentative_source_is_unready_but_deprecated_is_not_assumed_unbindable(self):
        for state, usable in (("Tentative", False), ("Duplicate", False), ("Deprecated", None)):
            item = adapter()
            item["addresses"][0]["state"] = state
            result = self.assess(item)
            self.assertEqual(result["status"], "source_ip_unready")
            self.assertIs(result["source_usable"], usable)

    def test_incomplete_or_invalid_enumeration_never_becomes_not_found(self):
        for value in (None, "broken", [{"name": TARGET.vlan}], [dict(adapter(), index=True)],
                      [dict(adapter(), admin_status="Down")]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                network.assess_adapters(TARGET, value)

    def test_many_addresses_keep_expected_source_in_summary(self):
        item = adapter()
        item["addresses"] = [{"ip": f"10.0.0.{i}", "prefix": 24, "state": "Preferred"}
                             for i in range(1, 150)] + item["addresses"]
        result = self.assess(item)
        brief = result["adapter"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(brief["addresses"][0]["ip"], TARGET.bind_ip)
        self.assertEqual(len(brief["addresses"]), 32)
        self.assertTrue(brief["addresses_truncated"])
        self.assertEqual(brief["address_count"], 150)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.emit = Mock()

    def test_query_failures_keep_unknown_and_explicit_error(self):
        for error in (TimeoutError("timed out"), ValueError("malformed JSON"), OSError("denied")):
            with self.subTest(error=error), patch.object(network, "_query", side_effect=error):
                result = network.read_target_network(TARGET, self.stop, self.emit)
            self.assertEqual(result["status"], "query_failed")
            self.assertIsNone(result["source_usable"])
            self.assertIn(str(error), result["error"])

    def test_read_records_current_time_and_matching_basis(self):
        with patch.object(network, "_query", return_value=[adapter(admin=2)]):
            result = network.read_target_network(TARGET, self.stop, self.emit)
        self.assertEqual(result["status"], "disabled")
        self.assertIn("不代表故障时状态", result["scope"])
        self.assertIn("captured_at", result)
        self.assertTrue(any("匹配=exact_alias" in c.args[0] for c in self.emit.call_args_list))

    def test_cancel_is_not_converted_to_query_failure(self):
        self.stop.set()
        with patch.object(network, "_query") as query, self.assertRaises(InterruptedError):
            network.read_target_network(TARGET, self.stop, self.emit)
        query.assert_not_called()

    def process(self, stdout=b"[]", stderr=b"", code=0):
        process = Mock(returncode=code)
        process.poll.return_value = code
        process.communicate.return_value = (stdout, stderr)
        context = Mock()
        context.__enter__ = Mock(return_value=process)
        context.__exit__ = Mock(return_value=False)
        return process, context

    def test_fixed_read_query_cannot_interpolate_target_or_change_network(self):
        process, context = self.process(json.dumps([adapter()]).encode())
        with patch.object(network.subprocess, "Popen", return_value=context) as popen:
            result = network._query(self.stop, self.emit)
        self.assertEqual(result[0]["name"], TARGET.vlan)
        args = popen.call_args.args[0]
        self.assertEqual(args[-1], network.ADAPTER_QUERY)
        self.assertNotIn(TARGET.bind_ip, network.ADAPTER_QUERY)
        self.assertIn("Get-NetAdapter -IncludeHidden", network.ADAPTER_QUERY)
        self.assertIn("-PolicyStore ActiveStore", network.ADAPTER_QUERY)
        for verb in ("Enable-Net", "Disable-Net", "Set-Net", "New-Net", "Remove-Net"):
            self.assertNotIn(verb, network.ADAPTER_QUERY)
        process.kill.assert_not_called()

    def test_timeout_kills_and_reaps_only_query_process(self):
        process, context = self.process()
        process.poll.return_value = None
        with patch.object(network.subprocess, "Popen", return_value=context), \
             patch.object(network, "QUERY_TIMEOUT", 0), self.assertRaises(TimeoutError):
            network._query(self.stop, self.emit)
        process.kill.assert_called_once()
        process.communicate.assert_called_once()

    def test_cancel_during_query_kills_and_reaps(self):
        process, context = self.process()
        process.poll.return_value = None
        def communicate(**kwargs):
            if "timeout" in kwargs:
                self.stop.set()
                raise subprocess.TimeoutExpired("query", .2)
            return b"", b""
        process.communicate.side_effect = communicate
        with patch.object(network.subprocess, "Popen", return_value=context), self.assertRaises(InterruptedError):
            network._query(self.stop, self.emit)
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_nonzero_empty_or_oversized_output_is_not_empty_enumeration(self):
        for stdout, stderr, code, error in ((b"[]", b"access denied", 1, RuntimeError),
                                           (b"", b"", 0, ValueError),
                                           (b"x" * (network.OUTPUT_LIMIT + 1), b"", 0, ValueError)):
            process, context = self.process(stdout, stderr, code)
            with self.subTest(code=code, size=len(stdout)), \
                 patch.object(network.subprocess, "Popen", return_value=context), self.assertRaises(error):
                network._query(self.stop, self.emit)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.emit = Mock()
        self.factory = Mock()
        self.executor = DiagnosticToolExecutor(TARGET, self.stop, self.emit, Mock(),
            DiagnosticRedactor(("model-auth-key",)), Mock(), Mock(return_value="独立串口现场"),
            transport_factory=self.factory)
        self.disabled = network.assess_adapters(TARGET, [adapter(ip=None, admin=2)])

    def snapshot(self, results=None, summary=None):
        with patch("src.services.ai_debug_service.read_target_network", return_value=summary or self.disabled), \
             patch("src.services.ai_debug_service.platform.platform", return_value="Windows"), \
             patch("src.services.ai_debug_service.subprocess.run",
                   side_effect=results or [Mock(stdout=b"", stderr=b"", returncode=0) for _ in range(3)]):
            return self.executor.execute("read_pc_environment", {})

    def test_snapshot_json_survives_ipv6_flood_and_serialization_escapes(self):
        text = "\x00" * 10000 + "IPv6" * 30000
        result = self.snapshot([Mock(stdout=text.encode(), stderr=b"", returncode=0) for _ in range(3)])
        self.assertLessEqual(len(result["evidence"]), 65536)
        snapshot = json.loads(result["evidence"])
        self.assertEqual(snapshot["target_network"]["status"], "disabled")
        for command in ("ipconfig /all", "route print -4", "netsh wlan show interfaces"):
            self.assertIn(command, snapshot)
            self.assertTrue(snapshot["command_results"][command]["truncated"])
        shown = format_diagnostic_evidence([result])
        self.assertIn("目标网卡管理状态为禁用", shown)

    def test_raw_command_failure_keeps_summary_and_other_outputs(self):
        result = self.snapshot([subprocess.TimeoutExpired("ipconfig", 20),
                                Mock(stdout=b"route", stderr=b"", returncode=0),
                                Mock(stdout=b"", stderr=b"access denied", returncode=1)])
        info = json.loads(result["evidence"])
        self.assertEqual(info["target_network"]["status"], "disabled")
        self.assertEqual(info["route print -4"], "route")
        self.assertIn("error", info["command_results"]["ipconfig /all"])
        self.assertEqual(info["command_results"]["netsh wlan show interfaces"]["error"], "access denied")

    def test_snapshot_filters_model_key_but_keeps_device_credentials(self):
        value = ("model-auth-key " + TARGET.password).encode()
        result = self.snapshot([Mock(stdout=value, stderr=b"", returncode=0) for _ in range(3)])
        self.assertNotIn("model-auth-key", result["evidence"])
        self.assertIn(TARGET.password, result["evidence"])
        json.loads(result["evidence"])

    def test_combined_connection_failure_is_cached_only_after_source_failure(self):
        self.executor.network_summary = self.disabled
        self.factory.return_value.open.side_effect = DebugConnectionUnavailable("Telnet失败；串口失败")
        first = self.executor.execute("read_dut_state", {"category": "system"})
        again = self.executor.execute("capture_packets", {}, deep=True)
        third = self.executor.execute("follow_logs", {}, deep=True)
        self.assertIn("串口失败", first["error"])
        self.assertIn("跳过重复连接", again["error"])
        self.assertIn("首次错误", third["error"])
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(self.executor.execute("read_serial_log", {})["evidence"], "独立串口现场")
        self.factory.return_value.command.assert_not_called()

    def test_refresh_clears_failed_connection_cache_even_when_query_failed(self):
        self.executor.network_summary = self.disabled
        self.factory.return_value.open.side_effect = DebugConnectionUnavailable("both failed")
        self.executor.execute("read_dut_state", {"category": "system"})
        self.snapshot(summary={"query_status": "failed", "source_usable": None, "status": "query_failed"})
        self.executor.execute("read_dut_state", {"category": "system"})
        self.assertEqual(self.factory.call_count, 2)
        self.assertIsNone(self.executor._connection_error)

    def test_unknown_source_and_nonconnection_errors_do_not_cache(self):
        for summary, error in (({"query_status": "failed", "source_usable": False}, DebugConnectionUnavailable("failed")),
                               ({"query_status": "ok", "source_usable": None}, DebugConnectionUnavailable("failed")),
                               (self.disabled, RuntimeError("busy")),
                               (self.disabled, InterruptedError("cancelled"))):
            self.executor.network_summary = summary
            self.factory.return_value.open.side_effect = error
            before = self.factory.call_count
            for _ in range(2):
                with self.assertRaises(type(error)):
                    self.executor._connection()
            self.assertEqual(self.factory.call_count - before, 2)
            self.assertIsNone(self.executor._connection_error)

    def test_independent_serial_connection_can_succeed_despite_disabled_network(self):
        self.executor.network_summary = self.disabled
        self.factory.return_value.kind = "串口"
        self.factory.return_value.command.return_value = "OpenWrt系统信息"
        self.executor.store.pending_recovery.return_value = []
        result = self.executor.execute("read_dut_state", {"category": "system"})
        self.assertIn("OpenWrt", result["evidence"])
        self.assertIsNone(self.executor._connection_error)

    def test_cached_failure_still_honors_stop_and_busy(self):
        self.executor._connection_error = "both failed"
        self.stop.set()
        with self.assertRaises(InterruptedError):
            self.executor._connection()
        self.stop.clear()
        self.executor.busy = Mock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, "目标正在"):
            self.executor._connection()
        self.factory.assert_not_called()

    def test_new_executor_does_not_share_previous_failure(self):
        self.executor._connection_error = "old failure"
        other = DiagnosticToolExecutor(TARGET, self.stop, self.emit, Mock(), DiagnosticRedactor(), Mock(), Mock())
        self.assertIsNone(other._connection_error)
        self.assertIsNone(other.network_summary)

    def test_both_entrypoints_expose_same_tool_without_new_permissions(self):
        automatic = next(t for t in tool_schemas() if t["name"] == "read_pc_environment")
        manual = next(t for t in conversation_tools(True, True) if t["name"] == "read_pc_environment")
        self.assertEqual(automatic, manual)
        self.assertEqual(automatic["parameters"]["properties"], {})
        self.assertNotIn("read_pc_environment", [t["name"] for t in conversation_tools(False, True)])
        for prompt in (SYSTEM_INSTRUCTIONS, CHAT_INSTRUCTIONS):
            self.assertIn("target_network", prompt)
            self.assertIn("故障时", prompt)
            self.assertIn("10049", prompt)


if __name__ == "__main__":
    unittest.main()

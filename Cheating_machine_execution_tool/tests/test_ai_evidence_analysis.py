"""样机稳定性固定材料及真实请求封装离线回归；不连接样机或模型。"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.ai_evidence_analysis import (DUT_INSTRUCTIONS, evidence_body, excerpt_evidence,
                                              match_score, prepare_evidence, query_terms)
from test_ai_core import chat, call
import test_ai_conversation as conversation_fixture
import test_ai_integration as automatic_fixture


def record(text, identifier="e1", source="串口RX", run="r", channel=1, timing="故障时记录"):
    return {"id": identifier, "text": text, "source": source, "run_id": run, "channel": channel,
            "timing": timing, "created": "2026-11-14T10:00:00+08:00"}


class EvidenceTests(unittest.TestCase):
    def prepare(self, items, query="样机卡死重启"):
        return prepare_evidence(items, query, "r", 1)

    def test_first_panic_in_middle_and_latest_recovery_survive_selection(self):
        text = "normal\n" * 2000 + "[125.10] Kernel panic - not syncing: fatal\nCall Trace:\n target_func+0x1/0x2\n" + "normal\n" * 3000
        items = [record(text)] + [record("无关例行信息", str(i)) for i in range(15)] + [record("当前可以登录", "now", "当前查询")]
        result = self.prepare(items)
        self.assertEqual(len(result["evidence"]), 8)
        self.assertIn("Kernel panic", result["evidence"][0]["text"])
        self.assertIn("target_func", result["evidence"][0]["text"])
        self.assertEqual(result["evidence"][-1]["id"], "now")
        self.assertTrue(result["evidence"][0]["truncated"])
        self.assertTrue(result["evidence"][0]["ranges"])
        self.assertLessEqual(len(result["evidence"][0]["text"]), 3500)
        self.assertEqual(result["dut_analysis"]["timeline"][0]["device_relative_time"], "[125.10]")

    def test_earlier_question_relevant_record_is_not_replaced_by_recent_noise(self):
        items = [record("rtl_driver fault code 7788", "relevant", "查询")]
        items += [record("periodic normal", str(i), "查询") for i in range(20)]
        result = self.prepare(items, "rtl_driver 7788")
        self.assertIn("relevant", [item["id"] for item in result["evidence"]])

    def test_repeated_boot_lines_do_not_hide_later_panic_and_stack(self):
        text = "Linux version 4.19.0\n" * 1000 + "Kernel panic - not syncing: late_failure\nCall Trace:\n crash_func+0x1\n" + "normal\n" * 2000
        result = self.prepare([record(text)])
        self.assertIn("crash_func", result["evidence"][0]["text"])
        self.assertTrue(any(item["kind"] == "panic" for item in result["dut_analysis"]["timeline"]))

    def test_global_timeline_cap_preserves_late_crash_after_normal_boot_records(self):
        items = [record("Linux version 4.19.0\n" * 10, str(i)) for i in range(7)]
        items.append(record("Kernel panic - not syncing: last_crash", "crash"))
        result = self.prepare(items)
        self.assertEqual(len(result["dut_analysis"]["timeline"]), 32)
        self.assertTrue(any(item["kind"] == "panic" for item in result["dut_analysis"]["timeline"]))

    def test_first_generic_abnormal_event_survives_many_new_normal_items(self):
        items = [record("环境异常", "first", "测试事件")]
        items += [record("现在正常", str(i), "测试事件") for i in range(30)]
        self.assertEqual(self.prepare(items)["evidence"][0]["id"], "first")

    def test_other_run_and_channel_never_appear(self):
        result = self.prepare([record("Kernel panic old", "old", run="old"),
                               record("Kernel panic other", "other", channel=2), record("当前材料")])
        self.assertEqual(result["selection"]["excluded"], 2)
        self.assertEqual([item["id"] for item in result["evidence"]], ["e1"])
        self.assertEqual(result["dut_analysis"]["timeline"], [])

    def test_normal_power_cycle_is_an_operation_clue_not_a_crash(self):
        result = self.prepare([record("通道1开始下电\n通道1上电成功\n程控电源 COM101 通道 [1] 操作:上电\n程控电源已直接上电：COM101，通道 1。\nU-Boot 2020.01\nLinux version 4.19.0")])
        kinds = {item["kind"] for item in result["dut_analysis"]["timeline"]}
        self.assertEqual(kinds, {"power_record", "boot"})
        self.assertEqual(sum(item["kind"] == "power_record" for item in result["dut_analysis"]["timeline"]), 4)
        self.assertFalse(any("未找到计划" in gap for gap in result["dut_analysis"]["gaps"]))
        self.assertNotIn("root_cause", result["dut_analysis"])

    def test_oom_without_boot_does_not_assert_system_restarted(self):
        result = self.prepare([record("Out of memory: Killed process 987 (app)\n服务继续工作")])
        self.assertEqual({item["kind"] for item in result["dut_analysis"]["timeline"]}, {"oom"})
        self.assertTrue(any("未找到启动序列" in gap for gap in result["dut_analysis"]["gaps"]))
        self.assertIn("OOM不等于整机重启", DUT_INSTRUCTIONS)

    def test_watchdog_initialization_is_not_a_fault_but_timeout_is_a_clue(self):
        result = self.prepare([record("watchdog: initialized\nwatchdog: timeout detected")])
        hits = result["dut_analysis"]["timeline"]
        self.assertEqual(len(hits), 1)
        self.assertIn("timeout", hits[0]["quote"])
        self.assertIn("watchdog记录不等于已确认复位", DUT_INSTRUCTIONS)

    def test_boot_interruption_reports_last_observed_phase_without_inventing_failure(self):
        result = self.prepare([record("U-Boot 2019.07\nStarting kernel ...")])
        self.assertEqual([item["kind"] for item in result["dut_analysis"]["timeline"]], ["boot", "boot"])
        self.assertNotIn("confirmed", json.dumps(result))
        self.assertTrue(any("计划上下电" in gap for gap in result["dut_analysis"]["gaps"]))

    def test_missing_serial_and_network_failure_do_not_prove_hang_or_reboot(self):
        result = self.prepare([record("目标串口未打开，无实时串口输出", source="read_serial_log"),
                               record("Ping超时", "ping", "当前网络查询")])
        self.assertTrue(any("缺少可用串口" in gap for gap in result["dut_analysis"]["gaps"]))
        self.assertEqual(result["dut_analysis"]["timeline"], [])
        self.assertIn("串口无输出不能单独证明卡死", DUT_INSTRUCTIONS)
        self.assertIn("网络失联不能单独证明重启", DUT_INSTRUCTIONS)

    def test_empty_serial_and_failed_read_are_not_available_serial_evidence(self):
        for raw in ("", json.dumps({"tool": "read_serial_log", "error": "not available"})):
            result = self.prepare([record(raw, source="read_serial_log")])
            self.assertTrue(any("缺少可用串口" in gap for gap in result["dut_analysis"]["gaps"]))

    def test_serial_side_channel_can_be_recognized_without_calling_it_a_new_capture(self):
        result = self.prepare([record("[串口RX] app heartbeat", source="本次测试旁路日志")])
        self.assertFalse(any("缺少可用串口" in gap for gap in result["dut_analysis"]["gaps"]))

    def test_network_loss_with_live_serial_does_not_create_crash_signal(self):
        result = self.prepare([record("Ping超时", "ping", "网络查询"), record("app heartbeat running")])
        self.assertFalse(any("缺少可用串口" in gap for gap in result["dut_analysis"]["gaps"]))
        self.assertEqual(result["dut_analysis"]["timeline"], [])

    def test_clock_fields_and_historical_timing_are_separate(self):
        item = record("2026-11-14_09:01:02 RX [13.000] Kernel panic - not syncing: fatal", timing="历史导入，时间待核对")
        hit = self.prepare([item])["dut_analysis"]["timeline"][0]
        self.assertEqual(hit["log_time"], "2026-11-14_09:01:02")
        self.assertEqual(hit["device_relative_time"], "[13.000]")
        self.assertEqual(hit["recorded_at"], item["created"])
        self.assertEqual(hit["timing"], item["timing"])

    def test_json_tool_body_is_unwrapped_for_line_references(self):
        raw = json.dumps({"tool": "read_dut_state", "evidence": "before\nOops: fatal\nafter"})
        result = self.prepare([record(raw, source="工具/read_dut_state")])
        self.assertEqual(result["dut_analysis"]["timeline"][0]["line"], 2)
        self.assertEqual(result["evidence"][0]["text"], raw)
        self.assertEqual(evidence_body(json.dumps({"result": {"stdout": "raw"}})), "raw")

    def test_timeline_and_excerpts_are_bounded_under_repeated_boot_output(self):
        items = [record(("Linux version 4.19.0\n" * 100) + "Kernel panic - not syncing: end", str(i)) for i in range(20)]
        result = self.prepare(items)
        self.assertLessEqual(len(result["dut_analysis"]["timeline"]), 32)
        self.assertGreater(result["dut_analysis"]["timeline_omitted"], 0)
        self.assertTrue(any(item["kind"] == "panic" for item in result["dut_analysis"]["timeline"]))

    def test_plain_small_evidence_and_model_credential_material_are_not_rewritten(self):
        text = "IP=192.168.1.1 username=root password=device-secret"
        result = excerpt_evidence(text, "卡死")
        self.assertEqual(result["text"], text)
        self.assertFalse(result["truncated"])

    def test_explicit_search_can_reach_later_text_after_many_crash_signals(self):
        text = ("Kernel panic - not syncing: fault\n" + "x\n" * 1000) * 10
        text += "needle_requested_here\n" + "y\n" * 1000
        result = excerpt_evidence(text, "needle_requested_here", 2000, prefer_query=True)
        self.assertIn("needle_requested_here", result["text"])

    def test_long_command_output_keeps_failure_and_dispatch_status(self):
        raw = json.dumps({"status": "failed", "result": {"stdout": "normal\n" * 5000,
                         "stderr": "operation failed", "exit_code": 1, "dispatched": True, "truncated": False}})
        result = excerpt_evidence(raw, "卡死", 2000)
        self.assertEqual(result["source_status"]["status"], "failed")
        self.assertEqual(result["source_status"]["result"]["exit_code"], 1)
        self.assertEqual(result["source_status"]["result"]["stderr"], "operation failed")
        self.assertTrue(result["source_status"]["result"]["dispatched"])

    def test_no_material_emits_skip_and_missing_information(self):
        logs = []
        result = prepare_evidence([], "卡死", "r", 1, logs.append)
        self.assertIn("跳过", logs[-1])
        self.assertTrue(result["dut_analysis"]["gaps"])

    def test_question_terms_match_chinese_and_stability_aliases(self):
        terms = query_terms("为什么样机突然重启了？错误码10049")
        self.assertGreater(match_score("reboot reason: watchdog", terms), 0)
        self.assertGreater(match_score("源IP无效 10049", terms), 0)
        self.assertEqual(match_score("普通资料", query_terms("分析本次异常")), 0)


class ConversationIntegrationTests(unittest.TestCase):
    setUp = conversation_fixture.ConversationTests.setUp
    stop_services = conversation_fixture.ConversationTests.stop_services
    send = conversation_fixture.ConversationTests.send

    def test_chat_request_contains_middle_panic_recovery_and_evidence_references(self):
        text = "normal\n" * 2000 + "Kernel panic - not syncing: fault\nCall Trace:\n driver_xyz+0x10\n" + "normal\n" * 3000
        evidence_id = self.service.add_evidence(self.id, "串口故障原文", text, "故障时")
        self.service.add_evidence(self.id, "当前查询", "现在可以登录", "本轮当前查询")
        self.send("刚才卡死重启了，分析原因")
        info = json.loads(self.requests[-1]["messages"][1]["content"])
        self.assertIn("Kernel panic", json.dumps(info, ensure_ascii=False))
        self.assertIn(evidence_id, [item["evidence_id"] for item in info["dut_analysis"]["timeline"]])
        self.assertIn("现在可以登录", json.dumps(info, ensure_ascii=False))
        self.assertEqual(next(item for item in self.store.chat_evidence(self.id) if item["id"] == evidence_id)["text"], text)
        self.assertTrue(any("[AI证据] 完成" in line for line in self.logs))

    def test_new_long_tool_output_keeps_panic_for_next_request_and_raw_storage(self):
        text = "normal\n" * 2000 + "Kernel panic - not syncing: driver_failure\n" + "normal\n" * 3000
        self.diag.serial_read = lambda target: text
        self.responses.extend([chat("", [call("read_serial_log")]), chat("需要继续核对调用栈")])
        self.send("样机卡死了")
        payload = self.requests[-1]
        tool = json.loads(next(item["content"] for item in payload["messages"] if item["role"] == "tool"))
        self.assertIn("driver_failure", tool["text"])
        self.assertTrue(tool["truncated"])
        info = json.loads(payload["messages"][1]["content"])
        self.assertTrue(any(item["kind"] == "panic" for item in info["dut_analysis"]["timeline"]))
        self.assertTrue(any(text in item["text"] or "driver_failure" in item["text"] for item in self.store.chat_evidence(self.id)))
        self.assertEqual(len(self.requests), 2)

    def test_chinese_evidence_search_ranks_relevant_middle_and_excludes_other_scope(self):
        evidence_id = self.service.add_evidence(self.id, "故障日志", "x\n" * 6000 + "样机突然重启\nKernel panic - not syncing: fatal" + "y\n" * 6000)
        foreign = record("样机突然重启 Kernel panic", "foreign", run="other")
        self.store.add_chat_evidence(self.id, foreign)
        result = self.service.search(self.id, "为什么样机重启")
        self.assertEqual(result["evidence"][0]["id"], evidence_id)
        self.assertIn("Kernel panic", result["evidence"][0]["text"])
        self.assertEqual(result["matched"], 1)

    def test_model_key_filtered_but_device_credentials_preserved_in_new_context(self):
        self.service.add_evidence(self.id, "串口", "Kernel panic - not syncing: model-secret password=device-password")
        self.send("分析卡死")
        payload = json.dumps(self.requests[-1], ensure_ascii=False)
        self.assertNotIn("model-secret", payload)
        self.assertIn("device-password", payload)


class AutomaticIntegrationTests(unittest.TestCase):
    setUp = automatic_fixture.ServiceTests.setUp
    stop_service = automatic_fixture.ServiceTests.stop_service
    finish = automatic_fixture.ServiceTests.finish

    def test_automatic_request_and_report_preserve_panic_outside_original_tail(self):
        text = "before\n" * 300 + "Kernel panic - not syncing: early_failure\nCall Trace:\n foo+0x1\n" + "after\n" * 15000
        self.service.trigger.append(1, text)
        self.service.serial_read = lambda target: "目标串口未打开，无实时串口输出"
        identifier = self.service.submit("样机重启", 1, "question")
        self.finish()
        info = json.loads(self.requests[0][2].request.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertIn("early_failure", info["recent_log"])
        self.assertTrue(any(item["kind"] == "panic" for item in info["dut_analysis"]["timeline"]))
        report = self.store.report(identifier)
        self.assertIn("dut_analysis", report)
        self.assertIn(text, report["evidence"])

    def test_automatic_followup_tool_returns_updated_dut_index(self):
        client = self.service.client_factory(self.profile, "test-key", self.service.redactor)
        client.session.request.side_effect = [automatic_fixture.FakeResponse(chat("", [call("read_serial_log")])),
                                              automatic_fixture.FakeResponse(chat("需要核对固件和符号"))]
        self.service.client_factory = lambda *args: client
        self.service.serial_read = lambda target: "Oops: fatal\nCall Trace:\n foo+0x1"
        self.service.submit("卡死", 1)
        self.finish()
        payload = client.session.request.call_args.kwargs["json"]
        tool = json.loads(next(item["content"] for item in payload["messages"] if item["role"] == "tool"))
        self.assertTrue(any(item["kind"] == "oops" for item in tool["dut_analysis"]["timeline"]))

    def test_knowledge_returns_only_matching_manual_sections_and_active_cases(self):
        path = Path(self.temp.name) / "manual.md"
        path.write_text("# 无关说明\n窗口颜色\n# 重启排查\nKernel panic调用栈\n# 其它\n打印表格", encoding="utf-8")
        self.service.manual_path = path
        case = self.store.confirm_case("r", "重启", "Kernel panic", "处理", "复测", "固件A")
        text = self.service._knowledge("为什么样机重启")
        self.assertIn("重启排查", text)
        self.assertNotIn("窗口颜色", text)
        self.assertIn('"id": ' + str(case), text)
        self.store.update_case_state(case)
        self.assertEqual(self.store.cases("样机重启"), [])
        self.assertIn("未找到相关章节", self.service._knowledge("unmatched_778899"))
        self.assertNotIn("打印表格", self.service._knowledge("unmatched_778899"))


if __name__ == "__main__":
    unittest.main()

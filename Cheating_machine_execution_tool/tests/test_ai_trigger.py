from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.ai_diagnostics import DiagnosticEvent, DebugTriggerPolicy
from src.services.ai_trigger_service import DiagnosticTrigger
from src.services.ai_event_adapter import PowerDiagnosticEvents


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.trigger = DiagnosticTrigger(DebugTriggerPolicy(channels=(1, 2)), lambda: self.now)
        self.trigger.enabled = True
        self.trigger.start("run")

    def event(self, attempt, **values):
        return replace(DiagnosticEvent("run", 1, "wifi", "error", "扫描失败", cycle=1,
                                      attempt=str(attempt), band="5G", feature="wifi"), **values)

    def test_third_distinct_attempt_triggers_and_fourth_escalates(self):
        self.assertIsNone(self.trigger.observe(self.event(1)))
        self.assertIsNone(self.trigger.observe(self.event(2)))
        self.assertEqual(self.trigger.observe(self.event(3)).level, "light")
        self.assertEqual(self.trigger.observe(self.event(4)).level, "deep")

    def test_final_failure_triggers_immediately_and_can_bypass_cooldown(self):
        self.assertEqual(self.trigger.observe(self.event("final", status="failed")).level, "deep")
        self.assertIsNone(self.trigger.observe(self.event("final", status="failed")))

    def test_final_failure_bypasses_cooldown_even_when_deep_disabled(self):
        self.trigger.policy = replace(self.trigger.policy, deep_enabled=False)
        for i in (1, 2, 3):
            self.trigger.observe(self.event(i))
        self.assertIsNotNone(self.trigger.observe(self.event("final", status="failed")))

    def test_duplicate_attempt_never_counts_again_even_after_cooldown(self):
        for i in (1, 2, 3):
            self.trigger.observe(self.event(i))
        self.now = 100
        self.assertIsNone(self.trigger.observe(self.event(3, detail="同次尝试另一摘要")))

    def test_success_resets_and_new_cycle_resume_and_run_do_not_mix(self):
        for i in (1, 2):
            self.trigger.observe(self.event(i))
        self.trigger.observe(self.event("ok", status="success"))
        self.assertIsNone(self.trigger.observe(self.event(3)))
        self.assertIsNone(self.trigger.observe(self.event(4, cycle=2)))
        self.trigger.reset_channel(1)
        self.assertIsNone(self.trigger.observe(self.event(5, cycle=2)))
        self.assertIsNone(self.trigger.observe(self.event(6, run_id="old")))

    def test_channels_stages_and_bands_are_isolated(self):
        for event in (self.event(1), self.event(2, channel=2), self.event(3, stage="ping"), self.event(4, band="2.4G")):
            self.assertIsNone(self.trigger.observe(event))

    def test_stop_wait_skip_and_untrusted_text_never_trigger(self):
        for status in ("cancelled", "stopped", "waiting", "skipped", "info"):
            self.assertIsNone(self.trigger.observe(self.event(1, status=status)))
        self.assertIsNone(self.trigger.observe(self.event(1, trusted=False, status="failed")))

    def test_manual_monitor_and_channel_feature_filter(self):
        self.trigger.enabled = False
        self.assertIsNone(self.trigger.observe(self.event(1, status="failed")))
        self.trigger.enabled = True
        self.assertIsNone(self.trigger.observe(self.event(1, status="failed", channel=3)))
        self.trigger.policy = replace(self.trigger.policy, features=("power",))
        self.assertIsNone(self.trigger.observe(self.event(1, status="failed")))

    def test_literal_keywords_and_error_codes(self):
        self.trigger.policy = replace(self.trigger.policy, keywords=("a.*b",), error_codes=("10054",))
        self.assertIsNone(self.trigger.observe(self.event(1, detail="acb")))
        self.assertIsNotNone(self.trigger.observe(self.event(2, detail="a.*b")))
        self.trigger.reset_channel(1)
        self.assertIsNotNone(self.trigger.observe(self.event(1, error_code="10054")))

    def test_context_time_and_byte_bounds(self):
        self.trigger.append(1, "old")
        self.now = 121
        self.trigger.append(1, "new")
        self.assertEqual(self.trigger.context(1), "new")
        self.trigger.append(1, "中" * (2 * 1024 * 1024))
        self.assertLessEqual(len(self.trigger.context(1).encode()), 2 * 1024 * 1024)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = PowerDiagnosticEvents()

    def log(self, text):
        return self.adapter.consume("r", {"type": "log", "message": text, "attempt": 0})

    def test_credentials_and_injected_keywords_are_not_events(self):
        for text in ("[WiFi测试] 通道1 第1轮 WiFi信息：SSID=失败 password=error", "随意日志：失败error", "[AI诊断] reboot"):
            self.assertEqual(self.log(text), [])

    def test_same_attempt_failure_and_waiting_produce_only_one_event(self):
        first = self.log("[WiFi测试] 通道1 第1轮 5G 第1/4次扫描失败：错误码=10054")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].attempt, "0:1")
        self.assertEqual(first[0].band, "5G")
        self.assertEqual(self.log("[WiFi测试] 通道1 第1轮 5G 等待10秒后重试"), [])

    def test_outdated_cycle_is_ignored(self):
        self.log("[WiFi测试] 通道1 第2轮 5G 第1/4次扫描失败：失败")
        self.assertEqual(self.log("[WiFi测试] 通道1 第1轮 5G 第2/4次扫描失败：失败"), [])

    def test_only_channel_result_marks_final_failure(self):
        event = self.log("[WiFi测试] 通道1 第1轮 5G 失败：第4次尝试用尽")[0]
        self.assertEqual(event.status, "error")
        final = self.adapter.consume("r", {"type": "channel_result", "channel": 1, "ok": False})[0]
        self.assertEqual(final.status, "failed")
        cancelled = self.adapter.consume("r", {"type": "channel_result", "channel": 1, "ok": False, "cancelled": True})[0]
        self.assertEqual(cancelled.status, "cancelled")

    def test_command_retries_use_attempt_and_command_stage(self):
        result = self.log("通道 1 执行指令：cat /proc/version，在第3次时出现错误；准备第4/4次验证")
        self.assertEqual(result[0].feature, "telnet")
        self.assertEqual(result[0].attempt, "0:3")

    def test_telnet_login_retries_have_numbered_identity(self):
        result = self.log("通道 2 第 3 次连接telnet 失败，等待10s再连接一次；")
        self.assertEqual(result[0].stage, "telnet_login")
        self.assertEqual(result[0].attempt, "0:3")

    def test_environment_ping_uses_explicit_business_result(self):
        result = self.adapter.consume("r", {"type": "diagnostic_event", "channel": 1,
            "stage": "environment_ping", "feature": "ping", "status": "failed", "detail": "设备无回复"})
        self.assertEqual(result[0].feature, "ping")
        self.assertEqual(result[0].status, "failed")


if __name__ == "__main__":
    unittest.main()

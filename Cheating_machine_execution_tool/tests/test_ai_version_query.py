"""Version routing + real capability/job integration, isolated model and DUT."""
from dataclasses import asdict, replace
from pathlib import Path
import queue
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_ai_conversation as fixture
from test_ai_core import chat, call
from test_ai_debug import TARGET
from line_check_assistant.test_item_config_store import TelnetSettings
from src.models.ai_permissions import FULL
from src.models.ai_actions import ActionAssessment
from src.models.capabilities import CapabilityAuthority, fingerprint
from src.services.ai_capability_adapter import AiCapabilityAdapter
from src.services.ai_version_query_service import version_route, version_selection
from src.services.capability_service import CapabilityService
from src.services.device_project_info_service import DeviceProjectInfo

MODULE = "src.services.capability_device_services."


class VersionRouteTests(unittest.TestCase):
    targets = tuple(replace(TARGET, channel=n) for n in (1, 2, 3))

    def test_clear_requests_skip_model_and_preserve_order(self):
        examples = {"当前3台样机的系统软件版本分别是？": [1, 2, 3],
                    "顺序查询一下当前3台样机的系统软件版本": [1, 2, 3],
                    "查询一下通道1样机的系统软件版本": [1],
                    "读取通道3、1的软件版本": [3, 1],
                    "查看所有样机版本": [1, 2, 3], "查询已勾选设备固件版本": [1, 2, 3]}
        for text, channels in examples.items():
            with self.subTest(text=text):
                selected, clarification = version_selection(text, None, self.targets)
                self.assertEqual(selected, channels)
                self.assertFalse(clarification)
                self.assertEqual(version_route(text, None, self.targets)["workflow"], "business")

    def test_ambiguous_counts_invalid_duplicates_and_missing_targets_clarify(self):
        for text in ("查询2台样机版本", "查询通道4版本", "查询通道1、1版本", "查询版本"):
            with self.subTest(text=text):
                self.assertEqual(version_route(text, None, self.targets)["intent"], "clarify")
        self.assertEqual(version_route("查询所有设备版本", None, ())["intent"], "clarify")

    def test_compound_historical_and_unrelated_text_never_shortcuts(self):
        for text in ("不要查询版本", "查询版本后重启", "分析昨天的版本日志", "版本为什么不一致", "通道123版本",
                     "执行 cat /etc/config/deviceinfo 查询版本", "升级全部样机版本", "这三台是不是同一个版本", "版本为什么？"):
            with self.subTest(text=text):
                self.assertIsNone(version_route(text, None, self.targets))

    def test_current_scope_is_reused_but_fresh_is_not_an_operation(self):
        current = dict(scope="device", target=asdict(self.targets[1]))
        self.assertEqual(version_selection("查询版本", current, self.targets)[0], [2])
        self.assertIsNone(version_route("查询版本", current, self.targets, fresh=True))
        current = dict(scope="batch", batch_targets=[asdict(t) for t in self.targets[1:]])
        self.assertEqual(version_selection("查询软件版本", current, self.targets)[0], [2, 3])


class VersionQueryTests(unittest.TestCase):
    stop_services = fixture.ConversationTests.stop_services

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.targets = tuple(replace(TARGET, channel=n, port="COM" + str(n), bind_ip="192.168.1." + str(20+n)) for n in (1, 2, 3))
        self.diag.configure(self.profile, self.targets)
        self.store.set_setting("chat_permission_mode", FULL)
        self.snapshot = dict(channels=[dict(section="channel_"+str(t.channel), vlan_name="vlan"+str(20+t.channel),
            adapter_alias="vlan"+str(20+t.channel), serial_port=t.port, network_card_ip=t.bind_ip,
            device_manage_ip=t.host, enabled=True) for t in self.targets], upgrade_settings={}, power_serial_port="")
        self.capabilities = CapabilityService(Path(self.temp.name)/"business", Mock(), lambda: self.snapshot,
            emit=self.logs.append, tool_root=Path(self.temp.name), enabled_modules={"devices"})
        self.service.capabilities = AiCapabilityAdapter(self.service, self.capabilities)
        self.addCleanup(self.close_capabilities)
        self.config_patch = patch(MODULE+"TestItemConfigStore.load", return_value=SimpleNamespace(telnet=TelnetSettings(password="login-only-secret")))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.seen = []

    def close_capabilities(self):
        self.stop_services()
        self.capabilities.jobs.begin_close()
        until = time.monotonic()+4
        while not self.capabilities.jobs.idle and time.monotonic()<until:
            time.sleep(.01)
        self.assertTrue(self.capabilities.jobs.idle)
        self.capabilities.jobs.close()

    def device(self, request, emit):
        self.seen.append(request.bind_ip)
        return DeviceProjectInfo("S"+request.bind_ip.rsplit('.', 1)[1], "T1", "synthetic time")

    def query(self, text="当前3台样机的系统软件版本分别是？", **kwargs):
        result = self.service.router.send(text, self.profile, **kwargs)
        self.service.jobs.join()
        return result["identifier"]

    def record(self, identifier):
        return self.store.chat(identifier)["version_query"]

    def test_three_same_ip_devices_one_job_and_only_one_model_explanation(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        self.assertEqual(self.seen, [t.bind_ip for t in self.targets])
        self.assertEqual(self.record(identifier)["state"], "completed")
        self.assertEqual(self.record(identifier)["summary"], "completed")
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(self.requests[0].get("tools"))
        self.assertNotIn("login-only-secret", str(self.requests[0]))
        self.assertLess(len(str(self.requests[0])), 4000)
        messages = self.store.chat_items(identifier)
        result_index = next(i for i,m in enumerate(messages) if m.get("kind", "").endswith(":result"))
        self.assertTrue(any(m["role"] == "assistant" for m in messages[result_index+1:]))
        self.assertEqual(self.store.chat(identifier)["status"], "可继续")

    def test_single_target_does_not_expand_to_all(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query("查询一下通道2样机的系统软件版本")
        self.assertEqual(self.seen, [self.targets[1].bind_ip])
        self.assertEqual(self.record(identifier)["channels"], [2])

    def test_one_failure_continues_and_preserves_real_results(self):
        def device(request, emit):
            if request.bind_ip == self.targets[1].bind_ip:
                self.seen.append(request.bind_ip)
                raise RuntimeError("synthetic login failure")
            return self.device(request, emit)
        with patch(MODULE+"query_device_project_info", side_effect=device):
            identifier = self.query()
        self.assertEqual(len(self.seen), 3)
        job = self.capabilities.jobs.status(self.record(identifier)["job_id"], self.service.capabilities.authority(identifier))
        self.assertEqual(job["state"], "failed")
        self.assertEqual([i["status"] for i in job["result"]["items"]], ["succeeded", "failed", "succeeded"])
        text = next(m["text"] for m in self.store.chat_items(identifier) if m.get("kind", "").endswith(":result"))
        self.assertIn("synthetic login failure", text)
        self.assertIn("S23", text)

    def test_target_change_halts_remaining_without_using_new_source(self):
        def device(request, emit):
            value = self.device(request, emit)
            self.snapshot["channels"][1]["network_card_ip"] = "192.168.1.99"
            return value
        with patch(MODULE+"query_device_project_info", side_effect=device):
            identifier = self.query()
        self.assertEqual(len(self.seen), 1)
        job = self.capabilities.jobs.status(self.record(identifier)["job_id"], self.service.capabilities.authority(identifier))
        self.assertEqual([i["status"] for i in job["result"]["items"]], ["succeeded", "not_executed", "not_executed"])

    def test_stopping_model_does_not_cancel_admitted_job_or_hide_results(self):
        started, release = threading.Event(), threading.Event()
        def device(request, emit):
            started.set()
            self.assertTrue(release.wait(3))
            return self.device(request, emit)
        with patch(MODULE+"query_device_project_info", side_effect=device):
            result = self.service.router.send("查询全部样机版本", self.profile)
            identifier = result["identifier"]
            try:
                self.assertTrue(started.wait(2))
                self.service.stop(identifier)
            finally:
                release.set()
            self.service.jobs.join()
        self.assertEqual(len(self.seen), 3)
        self.assertEqual(self.record(identifier)["summary"], "skipped")
        self.assertEqual(len(self.requests), 0)
        self.assertTrue(any(m.get("kind", "").endswith(":result") for m in self.store.chat_items(identifier)))

    def test_summary_failure_never_changes_query_result_or_requeries(self):
        self.responses.append(RuntimeError("synthetic model failure"))
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        self.assertEqual(len(self.seen), 3)
        self.assertEqual(self.record(identifier)["summary"], "failed")
        self.assertEqual(self.store.chat(identifier)["status"], "可继续")

    def test_model_explanation_cannot_call_tools(self):
        self.responses.append(chat("", [call("query_device_version", dict(channel_ids=[1]))]))
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        self.assertEqual(self.record(identifier)["summary"], "failed")
        self.assertEqual(len(self.seen), 3)

    def test_recovery_only_reads_original_job_and_deduplicates_projection(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        before = len(self.store.chat_items(identifier))
        record = self.record(identifier)
        self.store.update_chat(identifier, version_query=dict(record, state="waiting"))
        with patch.object(self.capabilities, "execute", side_effect=AssertionError("must not replay")):
            self.service.version_queries.restore_after = 0
            self.service.version_queries.recover()
        self.assertEqual(len(self.store.chat_items(identifier)), before)
        self.assertEqual(self.record(identifier)["summary"], "skipped")
        self.assertEqual(len(self.requests), 1)

    def test_recovery_covers_admission_ack_loss_without_job_id(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        record = self.record(identifier)
        self.store.update_chat(identifier, version_query=dict(record, job_id="", state="submitting"))
        self.service.version_queries.restore_after = 0
        with patch.object(self.capabilities, "execute", side_effect=AssertionError("must not replay")):
            self.service.version_queries.recover()
        self.assertEqual(self.record(identifier)["job_id"], record["job_id"])

    def test_read_only_lookup_is_scoped_to_original_principal_and_operation(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        authority = self.service.capabilities.authority(identifier, self.record(identifier)["operation_id"])
        self.assertIsNotNone(self.capabilities.jobs.find("device.version", authority))
        self.assertIsNone(self.capabilities.jobs.find("device.version", replace(authority, principal="other")))
        self.assertIsNone(self.capabilities.jobs.find("device.version", replace(authority, operation_id="other")))

    def test_count_mismatch_clarifies_without_a_device_or_model_call(self):
        with patch(MODULE+"query_device_project_info", side_effect=AssertionError("no device")):
            identifier = self.query("查询2台样机版本")
        self.assertNotIn("version_query", self.store.chat(identifier))
        self.assertEqual(self.requests, [])

    def test_feishu_and_dingtalk_sources_use_same_job_and_original_identity(self):
        for kind in ("feishu", "dingtalk"):
            source = dict(kind=kind, robot="robot", corp="corp", group="group", sender="member", nickname="synthetic", chat_type="group")
            with self.subTest(kind=kind), patch(MODULE+"query_device_project_info", side_effect=self.device), \
                    patch.object(self.service, "_review_action", return_value=ActionAssessment("ordinary", "fixed version query")):
                identifier = self.query("读取通道1、3软件版本", source=source)
                self.assertEqual(self.record(identifier)["state"], "completed")
                self.assertEqual(self.store.chat(identifier)["source"]["kind"], kind)
                job = self.capabilities.jobs.status(self.record(identifier)["job_id"], self.service.capabilities.authority(identifier))
                self.assertEqual(job["request"]["arguments"]["channel_ids"], [1, 3])

    def test_ask_mode_requires_approval_before_any_device_call(self):
        self.store.set_setting("chat_permission_mode", "ask")
        with patch(MODULE+"query_device_project_info", side_effect=self.device), \
                patch.object(self.service, "_review_action", return_value=ActionAssessment("ordinary", "fixed query")):
            identifier = self.service.router.send("查询全部样机版本", self.profile)["identifier"]
            until = time.monotonic()+3
            actions = []
            while time.monotonic()<until:
                actions = self.store.actions(identifier, ("waiting_approval",))
                if actions:
                    break
                time.sleep(.01)
            self.assertEqual(self.seen, [])
            self.assertEqual(len(actions), 1)
            action = actions[0]
            self.service.actions.decide(identifier, action["id"], action["fingerprint"], True)
            self.service.jobs.join()
        self.assertEqual(len(self.seen), 3)

    def test_explicit_business_cancel_stops_remaining_targets(self):
        started, release = threading.Event(), threading.Event()
        def device(request, emit):
            started.set()
            self.assertTrue(release.wait(3))
            return self.device(request, emit)
        with patch(MODULE+"query_device_project_info", side_effect=device):
            identifier = self.service.router.send("查询全部样机版本", self.profile)["identifier"]
            try:
                self.assertTrue(started.wait(2))
                until = time.monotonic()+2
                while not self.record(identifier).get("job_id") and time.monotonic()<until:
                    time.sleep(.005)
                self.capabilities.jobs.cancel(self.record(identifier)["job_id"], self.service.capabilities.authority(identifier))
            finally:
                release.set()
            self.service.jobs.join()
        self.assertEqual(len(self.seen), 1)
        job = self.capabilities.jobs.status(self.record(identifier)["job_id"], self.service.capabilities.authority(identifier))
        self.assertEqual(job["state"], "stopped")
        self.assertEqual([row["status"] for row in job["result"]["items"]], ["succeeded", "not_executed", "not_executed"])

    def test_missing_original_job_is_not_resubmitted_on_recovery(self):
        self.store.update_chat(self.id, version_query=dict(operation_id="missing", channels=[1], state="submitting"))
        with patch.object(self.capabilities, "execute", side_effect=AssertionError("must not replay")):
            self.service.version_queries.recover()
        self.assertEqual(self.record(self.id)["state"], "not_found")

    def test_job_lookup_handles_an_admitted_operation_with_missing_ack(self):
        original = self.service.capabilities.execute
        def missing_ack(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertIn("job_id", result)
            return dict(status="unknown", dispatched=False)
        with patch(MODULE+"query_device_project_info", side_effect=self.device), \
                patch.object(self.service.capabilities, "execute", side_effect=missing_ack):
            identifier = self.query()
        self.assertEqual(len(self.seen), 3)
        self.assertEqual(self.record(identifier)["state"], "completed")

    def test_unknown_job_recovers_successful_rows_from_durable_events(self):
        with patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        job_id = self.record(identifier)["job_id"]
        with self.capabilities.jobs.lock, self.capabilities.jobs.db:
            self.capabilities.jobs.db.execute("UPDATE jobs SET state='unknown',result='null' WHERE id=?", (job_id,))
            events = self.capabilities.jobs.db.execute("SELECT id FROM job_events WHERE job_id=? AND stage='version_item' ORDER BY id", (job_id,)).fetchall()
            self.capabilities.jobs.db.executemany("DELETE FROM job_events WHERE id=?", events[1:])
        with patch.object(self.service.version_queries, "_message") as publish:
            result = self.service.version_queries._observe(identifier, job_id, self.service.capabilities.authority(identifier))
        self.assertEqual(result["state"], "unknown")
        self.assertEqual([row["status"] for row in result["items"]], ["succeeded", "unknown", "unknown"])
        self.assertIn("S21", publish.call_args[0][3])
        self.assertIn("待核实", publish.call_args[0][3])

    def test_failed_queue_admission_restores_previous_business_turn(self):
        self.store.update_chat(self.id, capability_turn="previous-turn")
        with patch.object(self.service.jobs, "put_nowait", side_effect=queue.Full), self.assertRaises(queue.Full):
            self.service.send(self.id, "查询版本")
        self.assertEqual(self.store.chat(self.id)["capability_turn"], "previous-turn")
        self.assertNotIn(self.id, self.capabilities.metrics.turns)
        self.assertEqual(self.seen, [])

    def test_endpoint_change_after_last_permission_check_is_rejected_at_admission(self):
        execute = self.capabilities.execute
        def changed(capability, arguments, authority):
            self.snapshot["channels"][0]["network_card_ip"] = "192.168.1.99"
            return execute(capability, arguments, authority)
        with patch.object(self.capabilities, "execute", side_effect=changed), \
                patch(MODULE+"query_device_project_info", side_effect=self.device):
            identifier = self.query()
        self.assertEqual(self.seen, [])
        self.assertEqual(self.record(identifier)["state"], "not_admitted")
        self.assertTrue(any("原会话快照" in m["text"] for m in self.store.chat_items(identifier)))


if __name__ == "__main__":
    unittest.main()

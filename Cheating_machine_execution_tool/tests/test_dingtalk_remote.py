"""离线钉钉项目接入回归；网络、模型和危险命令均隔离。"""
from dataclasses import asdict, replace
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.dingtalk_stream import DingTalkStream, InstanceLease, valid_session_url, send_session_text
from src.models.dingtalk_remote import RemoteMessage, command, BOT_TOPIC
from src.models.ai_actions import ActionAssessment
from src.models.ai_permissions import ASK, AUTO, FULL
from src.services.ai_project_store import initialize_project, project_directory
from src.services.ai_store import DiagnosticStore
from src.services.dingtalk_remote_store import RemoteConfigStore, RemoteMailbox
from src.services.dingtalk_remote_service import DingTalkRemoteService, split_text
from test_ai_core import FakeCipher
from test_ai_debug import TARGET
import test_ai_conversation as fixture


def incoming(text="通道1 检查断网", **extra):
    return dict(msgId="message1", conversationId="group1", senderCorpId="corp1", senderId="user1",
                senderNick="工程师", robotCode="robot1", conversationType="2", isInAtList=True,
                msgtype="text", text={"content": text}, **extra)


def configured(config):
    return dict(config.load(), isolated=True, enabled=True, client_id="app1", client_secret="app-secret",
                robot_code="robot1", group="group1", corp="corp1", group_name="测试群",
                webhook="https://oapi.dingtalk.com/robot/send?access_token=notification-secret", secret="sign-secret")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = RemoteConfigStore(self.root, directory=self.root, cipher=FakeCipher())

    def test_config_secrets_are_encrypted_and_round_trip(self):
        values = configured(self.config)
        self.config.save(values)
        raw = self.config.path.read_text(encoding="utf-8")
        for key in ("client_secret", "webhook", "secret"):
            self.assertNotIn(values[key], raw)
        self.assertEqual(self.config.load(), values)

    def test_invalid_or_other_user_cipher_does_not_fallback_to_plaintext(self):
        self.config.path.write_text('{"encrypted":"bad"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "无法读取"):
            self.config.load()

    def test_enabling_requires_binding_and_credentials(self):
        with self.assertRaises(ValueError):
            self.config.save(dict(self.config.load(), enabled=True))

    def test_project_identity_uses_directory_and_is_stable(self):
        self.assertEqual(project_directory(self.root), project_directory(self.root / "."))
        self.assertNotEqual(project_directory(self.root), project_directory(self.root / "other"))

    def test_initialize_copies_models_only_and_is_idempotent(self):
        legacy = self.root / "legacy"
        store = DiagnosticStore(legacy, FakeCipher())
        from src.models.ai_diagnostics import ProviderProfile
        profile = store.save_profile(ProviderProfile(model="offline"), "old-key")
        store.set_setting("selected_profile", profile.id)
        store.set_setting("chat_permission_mode", FULL)
        store.create_chat(dict(id="old", created="2026", title="旧会话"))
        store.append_chat("old", dict(role="user", text="旧问题"))
        store.save_report("old-report", {"text": "旧报告"})
        store.close()
        original = (legacy / "diagnostics.sqlite3").read_bytes()
        target = self.root / "new"
        initialize_project(target, legacy / "diagnostics.sqlite3", FakeCipher())
        initialize_project(target, legacy / "diagnostics.sqlite3", FakeCipher())
        new = DiagnosticStore(target, FakeCipher())
        try:
            self.assertEqual(new.key(new.profiles()[0]), "old-key")
            self.assertEqual(new.setting("selected_profile"), profile.id)
            self.assertEqual(new.setting("chat_permission_mode", AUTO), AUTO)
            self.assertEqual(new.chats(), [])
            self.assertEqual(new.reports(), [])
        finally:
            new.close()
        with closing(sqlite3.connect((legacy / "diagnostics.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as old:
            message = old.execute("SELECT payload FROM chat_messages WHERE session_id=?", ("old",)).fetchone()
            self.assertEqual(json.loads(message[0])["text"], "旧问题")
            self.assertEqual(old.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)
        self.assertEqual(original, (legacy / "diagnostics.sqlite3").read_bytes())

    def test_configure_updates_notification_webhook_preserving_flags_and_other_sections(self):
        path = self.root / "config.ini"
        path.write_text("[dingtalk_config]\ndingtalk_flag=1\nat_all=1\nwebhook=old\nsecret=old\n"
                        "[other]\nkeep=value\n", encoding="utf-8")
        values = configured(self.config)
        with patch("src.services.ai_project_store.initialize_project"):
            result = self.config.configure(values, path)
        self.assertFalse(result["enabled"])
        self.assertFalse(result["group"])
        raw = path.read_text(encoding="utf-8")
        self.assertIn("dingtalk_flag=1", raw)
        self.assertIn("at_all=1", raw)
        self.assertIn("keep=value", raw)
        self.assertIn("notification-secret", raw)

    def test_configure_rejects_unsafe_webhook_before_writing(self):
        values = configured(self.config)
        values["webhook"] = "https://attacker.test/robot/send?access_token=secret"
        with self.assertRaises(ValueError):
            self.config.configure(values, self.root / "config.ini")
        self.assertFalse(self.config.path.exists())

    def test_notification_write_failure_rolls_back_both_configurations(self):
        values = configured(self.config)
        self.config.save(dict(values, enabled=False))
        previous = self.config.path.read_bytes()
        path = self.root / "config.ini"
        original = b"[dingtalk_config]\nwebhook=old\nsecret=old\n"
        path.write_bytes(original)
        def fail(_values):
            path.write_text("partial", encoding="utf-8")
            raise OSError("disk error")
        with patch("src.services.ai_project_store.initialize_project"), \
             patch("src.services.message_push_config_service.MessagePushConfigService.save", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "已回退"):
                self.config.configure(values, path)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.config.path.read_bytes(), previous)

    def test_mailbox_deduplicates_and_never_replays_after_restart(self):
        box = RemoteMailbox(self.root)
        message = RemoteMessage.parse(incoming(sessionWebhook="temporary-secret"))
        self.assertTrue(box.admit(message))
        self.assertFalse(box.admit(message))
        self.assertEqual(box.next()["webhook"], "")
        box.close()
        reopened = RemoteMailbox(self.root)
        try:
            self.assertIsNone(reopened.next())
            self.assertFalse(reopened.admit(message))
            self.assertNotIn(b"temporary-secret", (self.root / "dingtalk.sqlite3").read_bytes())
        finally:
            reopened.close()

    def test_full_inbox_does_not_ack_as_admitted(self):
        box = RemoteMailbox(self.root)
        try:
            box.admit(RemoteMessage.parse(incoming()), limit=1)
            data = incoming()
            data["msgId"] = "second"
            with self.assertRaises(RuntimeError):
                box.admit(RemoteMessage.parse(data), limit=1)
        finally:
            box.close()


class ProtocolTests(unittest.TestCase):
    def test_parse_identity_and_control_grammar(self):
        value = RemoteMessage.parse(incoming())
        self.assertEqual((value.id, value.group, value.corp, value.sender, value.robot),
                         ("message1", "group1", "corp1", "user1", "robot1"))
        self.assertEqual(command("通道3 检查断网"), ("通道", (3, "检查断网")))
        self.assertEqual(command("批准 abc123"), ("批准", "ABC123"))
        self.assertEqual(command("请批准 abc123")[0], "问题")

    def test_rejects_private_non_at_non_text_or_missing_identity(self):
        for field, value in (("conversationType", "1"), ("isInAtList", False),
                             ("msgtype", "picture"), ("senderId", ""), ("robotCode", "")):
            data = incoming()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                RemoteMessage.parse(data)

    def test_ack_only_after_admission_and_retry_on_storage_failure(self):
        receive = Mock()
        stream = DingTalkStream("app", "secret", receive, Mock())
        frame = dict(type="CALLBACK", headers=dict(messageId="frame1", topic=BOT_TOPIC),
                     data=json.dumps(incoming()))
        ack, disconnect = stream.frame(frame)
        receive.assert_called_once()
        self.assertEqual(ack["code"], 200)
        self.assertEqual(ack["headers"]["messageId"], "frame1")
        self.assertFalse(disconnect)
        receive.side_effect = RuntimeError("db full")
        self.assertEqual(stream.frame(frame)[0]["code"], 500)

    def test_system_ping_echoes_opaque_and_disconnect_is_recognized(self):
        stream = DingTalkStream("app", "secret", Mock(), Mock())
        frame = dict(type="SYSTEM", headers=dict(messageId="id", topic="ping"), data='{"opaque":"nonce"}')
        ack, disconnect = stream.frame(frame)
        self.assertEqual(json.loads(ack["data"]), {"opaque": "nonce"})
        self.assertFalse(disconnect)
        frame["headers"]["topic"] = "disconnect"
        self.assertTrue(stream.frame(frame)[1])

    def test_stream_connect_stop_and_no_credential_logging(self):
        events = []
        stream = None
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def recv(self, **kwargs):
                return json.dumps(dict(type="SYSTEM", headers=dict(messageId="id", topic="disconnect"), data="{}"))
            def send(self, text):
                stream.begin_close()
        connector = Mock(return_value=Socket())
        stream = DingTalkStream("app", "secret", Mock(), events.append,
            opener=Mock(return_value=dict(endpoint="wss://wss-open-connection.dingtalk.com/connect", ticket="ticket-secret")),
            connector=connector)
        stream.start()
        stream.thread.join(3)
        self.assertTrue(stream.idle)
        self.assertIn("已连接", events)
        self.assertNotIn("ticket-secret", str(events))
        self.assertNotIn("secret", str(events))

    def test_session_url_validation_and_error_does_not_expose_secret(self):
        self.assertTrue(valid_session_url("https://oapi.dingtalk.com/robot/sendBySession?session=demo"))
        for value in ("http://oapi.dingtalk.com/robot/sendBySession?session=x",
                      "https://oapi.dingtalk.com.attacker.test/robot/sendBySession?session=x"):
            self.assertFalse(valid_session_url(value))
        with patch("src.core.dingtalk_stream.post_json", return_value={"errcode": 1}):
            with self.assertRaisesRegex(RuntimeError, "未接受"):
                send_session_text("https://oapi.dingtalk.com/robot/sendBySession?session=demo", "reply")

    @unittest.skipUnless(os.name == "nt", "Windows named mutex")
    def test_same_instance_or_application_cannot_connect_twice(self):
        name = "test:" + self.id() + str(time.time_ns())
        first, second = InstanceLease(name), InstanceLease(name)
        first.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "另一进程"):
                second.acquire()
        finally:
            first.close()
        second.acquire()
        second.close()

    def test_unicode_split_respects_byte_boundary(self):
        text = "中文🙂" * 1000
        chunks = split_text(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(part.encode("utf-8")) <= 1800 for part in chunks))


class RemoteConversationTests(unittest.TestCase):
    stop_services = fixture.ConversationTests.stop_services

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.project = Path(self.temp.name) / "test_project_config.ini"
        self.project.write_text("[project_info]\nproject_name=项目A\n", encoding="utf-8")
        remote_dir = Path(self.temp.name) / "remote"
        self.config = RemoteConfigStore(self.temp.name, directory=remote_dir, cipher=FakeCipher())
        self.config.save(configured(self.config))
        self.transport = Mock(idle=False)
        self.remote = DingTalkRemoteService(self.service, self.config, self.project,
            transport_factory=Mock(return_value=self.transport), lease_factory=Mock(return_value=Mock()),
            autostart=False)
        self.addCleanup(self.close_remote)
        self.message = RemoteMessage.parse(incoming())

    def close_remote(self):
        self.remote.begin_close()
        for thread in (self.remote.worker, self.remote.sender_thread):
            if thread.ident is not None:
                thread.join(4)
                self.assertFalse(thread.is_alive())
        self.remote.close()

    def dispatch(self, text):
        self.remote._dispatch(replace(self.message, text=text))
        self.service.jobs.join()
        return list(self.remote.mailbox.routes().values())[-1][0]

    def test_remote_default_is_auto_even_when_desktop_remembers_other_modes(self):
        for mode in (ASK, FULL):
            self.store.set_setting("chat_permission_mode", mode)
            identifier = self.dispatch("新会话")
            self.assertEqual(self.store.chat(identifier)["permission_mode"], AUTO)

    def test_same_sender_followup_and_new_session_preserve_history(self):
        first = self.dispatch("检查断网")
        second = self.dispatch("网线已排除，继续检查")
        self.assertEqual(first, second)
        self.assertEqual(self.store.chat(first)["source"]["sender"], "user1")
        self.assertNotEqual(first, self.dispatch("新会话"))
        self.assertTrue(self.store.chat_items(first))

    def test_pc_target_status_and_reply_use_original_scope_label(self):
        decision = dict(intent="switch", scope="pc", channel=None, question="检查电脑", clarification="")
        with patch.object(self.service.router, "_resolve", return_value=decision):
            identifier = self.dispatch("只查这台电脑网络")
        self.assertEqual(self.store.chat(identifier)["scope"], "pc")
        self.remote._dispatch(replace(self.message, text="状态"))
        self.remote._publish()
        replies = [str(item) for item in list(self.remote.outbox.queue)]
        self.assertTrue(any("本机电脑" in text for text in replies))
        self.assertFalse(any("通道本机电脑" in text for text in replies))
        self.assertEqual(self.store.chat(identifier)["permission_mode"], AUTO)

    def test_new_session_keeps_background_route_and_does_not_stop_old_round(self):
        first = self.dispatch("通道1 检查")
        stopped = threading.Event()
        self.service.running[first] = stopped
        try:
            second = self.dispatch("新会话")
            self.assertNotEqual(first, second)
            self.assertFalse(stopped.is_set())
            self.assertTrue({first, second} <= {r[0] for r in self.remote.mailbox.routes().values()})
        finally:
            self.service.running.pop(first, None)

    def test_members_and_channels_are_isolated(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        self.remote._dispatch(replace(self.message, text="检查"))
        general = self.store.chat(self.service.router.current(dict(kind="dingtalk", robot=self.message.robot,
            corp=self.message.corp, group=self.message.group, sender=self.message.sender)))
        self.assertEqual(general["scope"], "general")
        self.assertIn("指定通道", self.store.chat_items(general["id"])[-1]["text"])
        first = self.dispatch("通道1 检查")
        second = self.dispatch("通道2 检查")
        self.assertNotEqual(first, second)
        self.message = replace(self.message, sender="user2")
        third = self.dispatch("通道1 检查")
        self.assertNotIn(third, (first, second))

    def test_other_group_corp_robot_disabled_and_duplicate_are_not_admitted(self):
        for field in ("conversationId", "senderCorpId", "robotCode"):
            data = incoming()
            data[field] = "other"
            self.remote.receive(data)
        self.assertIsNone(self.remote.mailbox.next())
        self.remote.receive(incoming())
        self.remote.receive(incoming())
        self.assertIsNotNone(self.remote.mailbox.next())
        self.assertIsNone(self.remote.mailbox.next())
        self.remote.config["enabled"] = False
        data = incoming()
        data["msgId"] = "new"
        self.remote.receive(data)
        self.assertIsNone(self.remote.mailbox.next())

    def test_binding_requires_local_confirmation_and_expires(self):
        self.remote.config["enabled"] = False
        code = self.remote.begin_binding()
        self.remote.receive(incoming("绑定 " + code, conversationTitle="目标群"))
        candidate = self.remote.snapshot()["candidate"]
        self.assertEqual(candidate["name"], "目标群")
        self.assertFalse(self.remote.config["enabled"])
        self.remote.confirm_binding(candidate)
        self.assertEqual(self.config.load()["group"], "group1")
        with self.assertRaises(ValueError):
            self.remote.confirm_binding(candidate)
        self.transport.idle = True
        self.remote.begin_binding()
        self.remote.binding_deadline = 0
        with self.assertRaises(ValueError):
            self.remote.confirm_binding(candidate)

    def test_project_header_and_credentials_are_filtered_only_at_group_outlet(self):
        self.remote.reply(self.message, "model-secret app-secret sign-secret " + TARGET.password, 1)
        _, text = self.remote.outbox.get_nowait()
        self.assertIn("项目A", text)
        self.assertIn("通道1", text)
        for value in ("model-secret", "app-secret", "sign-secret", TARGET.password):
            if value:
                self.assertNotIn(value, text)

    def test_password_boolean_flags_do_not_corrupt_ips_or_approval_codes(self):
        config = self.project.parent / "config.ini"
        config.write_text("[telnet]\ntelnet_input_password_flag=1\npassword_enable=0\n"
                          "telnet_password_str=sample-device-secret\n", encoding="utf-8")
        text = self.remote._sanitize("10.0.1.1 批准 A01B23 sample-device-secret")
        self.assertIn("10.0.1.1", text)
        self.assertIn("批准 A01B23", text)
        self.assertNotIn("sample-device-secret", text)

    def test_independent_subscription_does_not_consume_workbench_notifications(self):
        identifier = self.dispatch("检查")
        self.assertFalse(self.remote.updates.empty())
        self.assertFalse(self.service.updates.empty())
        self.remote._publish()
        self.assertFalse(self.service.updates.empty())
        self.assertGreater(self.remote.outbox.qsize(), 1)
        old_count = self.remote.outbox.qsize()
        self.remote._publish()
        self.assertEqual(self.remote.outbox.qsize(), old_count)

    def test_target_model_or_batch_change_creates_new_valid_session(self):
        first = self.dispatch("检查")
        self.context.observe(dict(type="diagnostic_start", run_id="new-run"))
        second = self.dispatch("继续检查")
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.chat(second)["run_id"], "new-run")

    def test_busy_message_is_not_queued_and_stop_keeps_test_running(self):
        identifier = self.dispatch("检查")
        stop = threading.Event()
        self.service.running[identifier] = stop
        try:
            with self.assertRaisesRegex(ValueError, "未排队"):
                self.remote._dispatch(replace(self.message, text="再检查"))
            self.remote._dispatch(replace(self.message, text="停止"))
            self.assertTrue(stop.is_set())
        finally:
            self.service.running.pop(identifier, None)

    def prepare_action(self):
        identifier = self.dispatch("检查")
        stop = threading.Event()
        self.service.running[identifier] = stop
        action = self.service.actions._prepare(identifier, "run_local_command", {"command": "Restart-Computer"})
        from src.models.ai_actions import action_fingerprint
        self.store.change_action(action["id"], ("reviewing",), "waiting_approval",
            assessment=asdict(ActionAssessment("dangerous", "会重启电脑")))
        # 没有执行线程或真实命令；批准仅验证现有状态机。
        self.remote._publish_approval(identifier, self.message)
        token = next(iter(self.remote.tokens))
        self.addCleanup(lambda: self.service.running.pop(identifier, None))
        return identifier, action, token

    def test_only_requester_can_approve_and_audit_keeps_identity(self):
        identifier, action, token = self.prepare_action()
        with self.assertRaisesRegex(ValueError, "不属于"):
            self.remote._decide(replace(self.message, sender="user2"), token, True)
        self.remote._decide(self.message, token, True)
        saved = self.store.action(action["id"])
        self.assertEqual(saved["state"], "approved")
        self.assertEqual(saved["approval_source"], "dingtalk")
        self.assertIn("user1", saved["operator_identity"])
        with self.assertRaises(ValueError):
            self.remote._decide(self.message, token, True)

    def test_local_and_remote_approval_cannot_both_succeed(self):
        identifier, action, token = self.prepare_action()
        self.service.actions.decide(identifier, action["id"], action["fingerprint"], True)
        with self.assertRaises(ValueError):
            self.remote._decide(self.message, token, True)

    def test_expiry_rejects_action_and_parameter_change_invalidates_token(self):
        identifier, action, token = self.prepare_action()
        self.store.change_action(action["id"], ("waiting_approval",), "waiting_approval", params={"command": "changed"})
        with self.assertRaisesRegex(ValueError, "变化"):
            self.remote._decide(self.message, token, True)
        self.remote.tokens[token]["expires"] = 0
        with self.assertRaisesRegex(ValueError, "过期"):
            self.remote._decide(self.message, token, True)

    def test_disabling_cancels_pending_and_revokes_tokens(self):
        identifier, action, token = self.prepare_action()
        self.remote.enable(False)
        self.assertTrue(self.service.running[identifier].is_set())
        self.assertEqual(self.store.action(action["id"])["state"], "cancelled")
        self.assertFalse(self.remote.tokens)
        self.assertTrue(self.remote.outbox.empty())

    def test_disabling_stops_even_when_configuration_cannot_be_saved(self):
        identifier, action, token = self.prepare_action()
        with patch.object(self.config, "save", side_effect=OSError("read only")):
            with self.assertRaisesRegex(ValueError, "本进程已停用"):
                self.remote.enable(False)
        self.assertFalse(self.remote.config["enabled"])
        self.assertTrue(self.service.running[identifier].is_set())
        self.assertFalse(self.remote.tokens)

    def test_changed_robot_cannot_reuse_old_full_session_or_reply_context(self):
        identifier = self.dispatch("检查")
        self.service.permissions.select(identifier, FULL, confirmed=True)
        self.remote.config["robot_code"] = "robot2"
        self.message = replace(self.message, robot="robot2")
        replacement = self.dispatch("继续检查")
        self.assertNotEqual(identifier, replacement)
        self.assertEqual(self.store.chat(replacement)["permission_mode"], AUTO)

    def test_expired_approval_rejects_unchanged_action(self):
        identifier, action, token = self.prepare_action()
        self.remote.tokens[token]["expires"] = 0
        self.remote._expire()
        self.assertEqual(self.store.action(action["id"])["state"], "rejected")
        self.assertFalse(self.remote.tokens)

    def test_stream_to_model_to_reply_duplicate_message_executes_once(self):
        sent = []
        self.remote.sender = lambda webhook, secret, text, **kwargs: sent.append(text)
        self.remote.send_interval = .001
        self.remote.worker.start()
        self.remote.sender_thread.start()
        self.remote.transport = Mock(idle=False)
        self.remote.transport.begin_close.side_effect = lambda: setattr(self.remote.transport, "idle", True)
        self.remote.receive(incoming())
        self.remote.receive(incoming())
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not any("根据已有证据" in s for s in sent):
            time.sleep(.02)
        self.assertTrue(any("根据已有证据" in s for s in sent), sent)
        self.assertEqual(len(self.requests), 1)

    def test_reply_failure_never_repeats_model_or_tools(self):
        self.remote.sender = Mock(side_effect=RuntimeError("network failure"))
        self.remote.send_interval = .001
        self.remote.transport = Mock(idle=False)
        self.remote.transport.begin_close.side_effect = lambda: setattr(self.remote.transport, "idle", True)
        self.remote.worker.start()
        self.remote.sender_thread.start()
        self.remote.receive(incoming())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any("群回复发送失败" in s for s in self.logs):
            time.sleep(.02)
        self.remote.receive(incoming())
        self.service.jobs.join()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(any("群回复发送失败" in s for s in self.logs))

    @patch("src.services.ai_action_service.run_local_command")
    def test_remote_approval_dispatches_real_action_chain_exactly_once(self, execute):
        identifier = self.dispatch("检查")
        stop, result = threading.Event(), []
        self.service.running[identifier] = stop
        execute.return_value = dict(status="completed", exit_code=0, process_cleanup_confirmed=True)
        executor = Mock(transport=None)
        def run():
            try:
                result.append(self.service.actions.execute(identifier, "run_local_command", {"command": "Restart-Computer"},
                    TARGET, stop, executor, Mock(return_value=ActionAssessment("dangerous", "会重启电脑"))))
            except Exception as exc:
                result.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        def cleanup():
            stop.set()
            thread.join(4)
            self.service.running.pop(identifier, None)
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.store.actions(identifier, ("waiting_approval",)):
            time.sleep(.01)
        self.assertTrue(self.store.actions(identifier, ("waiting_approval",)))
        execute.assert_not_called()
        self.remote._publish_approval(identifier, self.message)
        token = next(iter(self.remote.tokens))
        self.remote._decide(self.message, token, True)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        execute.assert_called_once()
        self.assertEqual(result[0]["action_state"], "succeeded")
        with self.assertRaises(ValueError):
            self.remote._decide(self.message, token, True)


class SetupWindowTests(unittest.TestCase):
    def test_setup_native_checkbutton_and_module_theme_vista_clam(self):
        import gc
        import tkinter as tk
        from tkinter import ttk
        from src.ui.dingtalk_setup_window import DingTalkSetupWindow
        from tk_test_windows import OffscreenTkWindows
        with tempfile.TemporaryDirectory() as temporary, OffscreenTkWindows() as windows:
            gc.collect()
            root = tk.Tk()
            try:
                for theme in ("vista", "clam"):
                    ttk.Style(root).theme_use(theme)
                    config = RemoteConfigStore(temporary, directory=temporary, cipher=FakeCipher())
                    dialog = DingTalkSetupWindow(root, config, lambda: None, {}, Mock(), Path(temporary) / "config.ini")
                    root.update_idletasks()
                    checkboxes = [w for w in dialog.window.winfo_children() if isinstance(w, tk.Checkbutton)]
                    self.assertEqual(len(checkboxes), 1)
                    self.assertFalse(dialog.enabled.get())
                    self.assertEqual(dialog.window.cget("background"), "#eef2f5")
                    self.assertEqual(dialog.variables["client_secret"].get(), "")
                    dialog.close()
                windows.assert_offscreen()
            finally:
                root.destroy()
                gc.collect()

    @unittest.skipUnless(os.name == "nt", "Windows project guard")
    def test_hidden_controller_is_project_scoped_guarded_before_database_and_closes(self):
        import gc
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from src.ui.ai_assistant_controller import AiAssistantController
        from tk_test_windows import OffscreenTkWindows
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temporary) / "user")}), OffscreenTkWindows():
            gc.collect()
            root = tk.Tk()
            controller = None
            other = None
            try:
                project = Path(temporary) / "project.ini"
                project.write_text("[project_info]\nproject_name=offline\n", encoding="utf-8")
                config = RemoteConfigStore(temporary, directory=Path(temporary) / "ai", cipher=FakeCipher())
                config.save(dict(config.load(), isolated=True))
                terminal = SimpleNamespace(ai_debug_cancel=None, diagnostic_observer=None)
                args = (root, terminal, Mock(), lambda: (TARGET,), lambda target: False, lambda: "", Mock(), None)
                with patch("src.services.dingtalk_remote_store.RemoteConfigStore", return_value=config):
                    controller = AiAssistantController(*args, app_dir=temporary, project_config_path=project)
                    self.assertIsNone(controller.dialog.window)
                    self.assertEqual(controller.service.store.directory, config.directory)
                    with patch("src.services.ai_store.DiagnosticStore") as create_database:
                        with self.assertRaisesRegex(RuntimeError, "另一进程"):
                            AiAssistantController(*args, app_dir=temporary, project_config_path=project)
                        create_database.assert_not_called()
                second_config = RemoteConfigStore(temporary, directory=Path(temporary) / "second-ai", cipher=FakeCipher())
                second_config.save(dict(second_config.load(), isolated=True))
                with patch("src.services.dingtalk_remote_store.RemoteConfigStore", return_value=second_config):
                    second_terminal = SimpleNamespace(ai_debug_cancel=None, diagnostic_observer=None)
                    second_args = (root, second_terminal, Mock(), lambda: (TARGET,), lambda target: False, lambda: "", Mock(), None)
                    other = AiAssistantController(*second_args, app_dir=Path(temporary) / "second", project_config_path=project)
                controller.service.store.set_setting("isolation_probe", "first-project")
                self.assertIsNone(other.service.store.setting("isolation_probe"))
                self.assertIsNot(controller.conversation, other.conversation)
                identifier = controller.service.confirm_case("r", "共用标题", "实际原因", "处理", "复测", "范围")
                self.assertEqual(other.service.store.cases()[0]["id"], identifier)
                self.assertIsNotNone(controller.service.store.case_store)
                self.assertIsNotNone(other.service.store.case_store)
                self.assertEqual(other.service.store.case_store.directory,
                                 Path(temporary) / "user" / "LineCheckAssistant" / "case_library")
                controller._refresh_remote_targets()
                self.assertEqual(tuple(controller.service.targets), (TARGET.channel,))
                for theme in ("vista", "clam"):
                    with self.subTest(theme=theme):
                        ttk.Style(root).theme_use(theme)
                        controller.dialog.open()
                        controller.dialog.window.geometry("940x660")
                        root.update()
                        toolbar = controller.dialog.workspace.winfo_children()[0]
                        self.assertEqual([w.cget("text") for w in toolbar.winfo_children()
                                          if isinstance(w, ttk.Button)], ["诊断报告", "自动监控"])
                        self.assertFalse(any(isinstance(w, ttk.Menubutton) for w in toolbar.winfo_children()))
                        sessions = controller.dialog.chat_panel.sessions
                        self.assertEqual([w.cget("text") for w in sessions.master.winfo_children()
                                          if isinstance(w, ttk.Button)], ["刷新会话", "管理会话"])
                        self.assertEqual([controller.dialog.book.tab(t, "text")
                                          for t in controller.dialog.book.tabs()],
                                         ["排障工作台", "模型接入", "已确认案例", "远程管理"])
                        controller.dialog.hide()
            finally:
                for instance in (controller, other):
                    if instance is not None:
                        deadline = time.monotonic() + 4
                        while not instance.prepare_app_close() and time.monotonic() < deadline:
                            root.update()
                            time.sleep(.01)
                        self.assertTrue(instance.closed)
                root.destroy()
                gc.collect()


if __name__ == "__main__":
    unittest.main()

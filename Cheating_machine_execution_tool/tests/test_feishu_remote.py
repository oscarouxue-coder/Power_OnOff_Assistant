"""离线飞书接入回归；网络、模型和设备命令均为测试替身。"""
import asyncio
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.feishu_client import FeishuApi, post_payload
from src.core.feishu_stream import FeishuStream, FeishuInstanceLease
from src.models.ai_actions import ActionAssessment
from src.models.ai_permissions import ASK, AUTO, FULL
from src.models.feishu_remote import FeishuMessage, command
from src.services.feishu_notifications import FeishuNotificationService, TestNotificationProxy
from src.services.feishu_remote_store import FeishuConfigStore, FeishuMailbox
from src.services.feishu_remote_service import FeishuRemoteService
from src.services.feishu_output import POST_BYTE_LIMIT, reply_posts
from src.services.ai_record_titles import AiRecordTitles
from test_ai_core import FakeCipher
from test_ai_debug import TARGET
import test_ai_conversation as fixture


def incoming(text="检查断网", *, kind="group", identifier="message1", user="user1", chat=None, tenant="tenant1", app="cli_app1"):
    return dict(schema="2.0", header=dict(event_type="im.message.receive_v1", event_id="event-id",
        app_id=app, tenant_key=tenant), event=dict(sender=dict(sender_type="user", tenant_key=tenant,
        sender_id=dict(open_id=user)), message=dict(message_id=identifier,
        chat_id=chat or ("group1" if kind == "group" else "direct1"), chat_type=kind, message_type="text",
        content=json.dumps({"text": ("@_user_1 " if kind == "group" else "") + text}),
        mentions=[dict(key="@_user_1", id=dict(open_id="bot1"), mentioned_type="bot")])))


def configured(config, **extra):
    return dict(config.load(), isolated=True, app_id="cli_app1", app_secret="app-secret",
                group="group1", corp="tenant1", group_name="测试群", **extra)


def post_text(post):
    return "".join(node["text"] for row in post["zh_cn"]["content"] for node in row)


class ReplyFormatTests(unittest.TestCase):
    def test_ping_reply_has_separate_title_and_native_markdown(self):
        text = ("**结论：通道1连通正常，4个Ping包全部收到。**\n\n"
                "- 出口：有线 `VLAN116`，源IP `192.168.1.116/24`\n"
                "- Ping结果：发送4包，收到4包，0丢包\n\n本轮仅验证了ICMP连通性。")
        posts = reply_posts("chat1", "项目：项目A | 通道1 | 成员A", text, markdown=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["zh_cn"]["title"], "项目：项目A | 通道1 | 成员A")
        self.assertEqual(posts[0]["zh_cn"]["content"], [[dict(tag="md", text=text)]])

    def test_status_uses_native_markdown_by_default(self):
        text = '**状态**：可继续\n\n**权限**：帮我批准'
        post = reply_posts("chat1", "项目A", text)[0]
        self.assertEqual(post["zh_cn"]["content"], [[dict(tag="md", text=text)]])

    def test_code_payload_survives_multiple_posts_and_fence_like_content(self):
        code = ('  路径 = "C:\\配置\\a.ini"\r\n\r\n\t# **原文** `不渲染`\r\n```\r\n' * 450)
        posts = reply_posts("chat1", "项目A", "**结果**\n\n````ini\r\n" + code + "````\r\n后续说明",
                            markdown=True)
        self.assertGreater(len(posts), 1)
        nodes = [node for post in posts for row in post["zh_cn"]["content"] for node in row]
        self.assertEqual("".join(n["text"] for n in nodes if n["tag"] == "code_block"), code)
        self.assertEqual(nodes[0], dict(tag="md", text="**结果**\n\n"))
        self.assertEqual(nodes[-1], dict(tag="md", text="后续说明"))
        for index, post in enumerate(posts):
            self.assertEqual(post["zh_cn"]["title"], f"[{index + 1}/{len(posts)}] 项目A")
            self.assertLessEqual(len(json.dumps(post_payload("chat1", post, "0" * 32)).encode()), POST_BYTE_LIMIT)

    def test_unclosed_fence_is_literal_and_matching_close_is_whole_line(self):
        text = "前文\n~~~json\n{\"a\": 1}\n~~~ trailing\n~~\n~~~\n```\n**未闭合原文**"
        post = reply_posts("chat1", "项目A", text, markdown=True)[0]
        nodes = [row[0] for row in post["zh_cn"]["content"]]
        self.assertEqual(nodes[1], dict(tag="code_block", language="JSON", text='{\"a\": 1}\n~~~ trailing\n~~\n'))
        self.assertEqual(nodes[2], dict(tag="text", text="```\n**未闭合原文**"))

    def test_serialized_size_accounts_for_unicode_escapes_and_oversized_lines(self):
        for text in ('第一段\n\n' * 3000, '路径😀中文"\\\t' * 3500):
            with self.subTest(paragraphs="\n" in text):
                posts = reply_posts("chat1", "项目：型号😀", text, markdown=True)
                self.assertGreater(len(posts), 1)
                self.assertEqual("".join(post_text(post) for post in posts), text)
                for post in posts:
                    size = len(json.dumps(post_payload("chat1", post, "0" * 32)).encode("utf-8"))
                    self.assertLessEqual(size, POST_BYTE_LIMIT)

    def test_oversized_metadata_fails_without_truncating_it(self):
        with self.assertRaisesRegex(ValueError, "标题过长"):
            reply_posts("chat1", "项目" * 5000, "正文")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = FeishuConfigStore(self.root, directory=self.root, cipher=FakeCipher())

    def test_defaults_off_and_secret_encrypted_round_trip(self):
        self.assertFalse(self.config.load()["enabled"])
        self.assertFalse(self.config.load()["push_enabled"])
        self.config.save(configured(self.config))
        self.assertNotIn("app-secret", self.config.path.read_text(encoding="utf-8"))
        self.assertEqual(self.config.load()["app_secret"], "app-secret")

    def test_bad_cipher_fails_closed_without_plaintext_fallback(self):
        self.config.path.write_text('{"encrypted":"bad","app_secret":"private"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "无法读取") as error:
            self.config.load()
        self.assertNotIn("private", str(error.exception))

    def test_group_and_notification_require_binding_but_p2p_does_not(self):
        values = dict(self.config.load(), app_id="cli_app1", app_secret="secret")
        for key in ("group_enabled", "push_enabled"):
            with self.assertRaisesRegex(ValueError, "群绑定"):
                self.config.save(dict(values, **{key: True}))
        self.config.save(dict(values, p2p_enabled=True))
        self.assertTrue(self.config.load()["enabled"])

    def test_configure_blank_secret_preserves_value_and_app_change_resets_binding(self):
        self.config.save(configured(self.config))
        with patch("src.services.feishu_remote_store.initialize_project") as initialize:
            saved = self.config.configure(dict(app_id="cli_app1", app_secret=""))
            self.assertEqual(saved["app_secret"], "app-secret")
            self.assertEqual(saved["group"], "group1")
            changed = self.config.configure(dict(app_id="cli_app2", app_secret="new-secret"))
        self.assertFalse(changed["group"])
        self.assertFalse(changed["corp"])
        self.assertFalse(changed["enabled"])
        self.assertGreater(changed["push_revision"], saved["push_revision"])
        self.assertEqual(initialize.call_count, 2)

    def test_credentials_cannot_change_while_enabled_or_notification_enabled(self):
        for key in ("p2p_enabled", "push_enabled"):
            self.config.save(configured(self.config, **{key: True}))
            with self.assertRaisesRegex(ValueError, "先关闭"):
                self.config.configure(dict(app_id="cli_app2", app_secret="new"))

    def test_invalid_config_does_not_write(self):
        for values in ({"app_id": "http://bad", "app_secret": "secret"},
                       {"app_id": "cli_good", "app_secret": "secret\nprivate"}):
            with self.assertRaises(ValueError):
                self.config.configure(values)
        self.assertFalse(self.config.path.exists())

    def test_atomic_save_failure_preserves_previous_file(self):
        self.config.save(configured(self.config))
        original = self.config.path.read_bytes()
        with patch("src.services.feishu_remote_store.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.config.save(dict(self.config.load(), app_secret="changed"))
        self.assertEqual(self.config.path.read_bytes(), original)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_mailbox_dedup_and_restart_do_not_replay_pending_operations(self):
        mailbox = FeishuMailbox(self.root)
        message = FeishuMessage.parse(incoming(), "cli_app1", "bot1")
        self.assertTrue(mailbox.admit(message))
        self.assertFalse(mailbox.admit(message))
        mailbox.close()
        mailbox = FeishuMailbox(self.root)
        try:
            self.assertIsNone(mailbox.next())
            self.assertFalse(mailbox.admit(message))
        finally:
            mailbox.close()


class MessageTests(unittest.TestCase):
    def test_group_mention_removed_and_dm_needs_no_mention(self):
        self.assertEqual(FeishuMessage.parse(incoming(), "cli_app1", "bot1").text, "检查断网")
        data = incoming(kind="p2p")
        data["event"]["message"]["mentions"] = []
        self.assertEqual(FeishuMessage.parse(data, "cli_app1", "bot1").chat_type, "p2p")

    def test_other_bot_unmentioned_bot_sender_and_wrong_application_rejected(self):
        for change in ("bot", "mention", "application", "tenant", "type", "missing", "malformed"):
            data = incoming()
            if change == "bot":
                data["event"]["sender"]["sender_type"] = "bot"
            elif change == "mention":
                data["event"]["message"]["mentions"][0]["id"]["open_id"] = "other-bot"
            elif change == "application":
                data["header"]["app_id"] = "other-app"
            elif change == "tenant":
                data["event"]["sender"]["tenant_key"] = "external"
            elif change == "type":
                data["event"]["message"]["message_type"] = "image"
            elif change == "missing":
                del data["event"]["sender"]["sender_id"]
            else:
                data["event"]["message"]["content"] = "not-json"
            with self.subTest(change=change), self.assertRaises(ValueError):
                FeishuMessage.parse(data, "cli_app1", "bot1")

    def test_only_exact_control_commands_are_accepted(self):
        self.assertEqual(command("批准 A01B23"), ("批准", "A01B23"))
        self.assertEqual(command("通道3 检查"), ("通道", (3, "检查")))
        self.assertEqual(command("模型说批准 A01B23")[0], "问题")


class ApiTests(unittest.TestCase):
    def response(self, body, status=200):
        return Mock(status_code=status, json=Mock(return_value=body))

    def test_token_cached_and_requests_have_bounded_timeout_no_redirects(self):
        request = Mock(side_effect=[self.response(dict(code=0, tenant_access_token="token-secret", expire=7200)),
                                    self.response(dict(code=0)), self.response(dict(code=0))])
        api = FeishuApi("cli_app1", "app-secret", requester=request)
        api.send_text("chat1", 'hello <at user_id="all">everyone</at>', "fixed-id")
        api.send_text("chat1", "second")
        self.assertEqual(request.call_count, 3)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 10)
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertTrue(call.args[1].startswith("https://open.feishu.cn/"))
        payload = request.call_args_list[1].kwargs["json"]
        self.assertEqual(payload["uuid"], "fixed-id")
        self.assertNotIn("<at ", payload["content"])

    def test_http_and_platform_errors_do_not_disclose_credentials(self):
        for response in (self.response(dict(code=123, msg="private-token")),
                         self.response(dict(code=0), status=302),
                         self.response(dict(code="0"))):
            with self.subTest(response=response):
                api = FeishuApi("cli_app1", "app-secret", requester=Mock(return_value=response))
                with self.assertRaises(RuntimeError) as error:
                    api.token()
                self.assertNotIn("private-token", str(error.exception))

    def test_post_serialization_blocks_mentions_without_mutating_input(self):
        request = Mock(side_effect=[self.response(dict(code=0, tenant_access_token="token", expire=7200)),
                                    self.response(dict(code=0))])
        api = FeishuApi("cli_app1", "app-secret", requester=request)
        source = '**结论** <AT\nuser_id="all">所有人</at> <at\tuser_id="user1">人员</at>'
        post = {"zh_cn": dict(title="项目A", content=[[dict(tag="md", text=source)]])}
        api.send_post("direct1", post, "fixed-id")
        payload = request.call_args.kwargs["json"]
        self.assertEqual((payload["receive_id"], payload["msg_type"], payload["uuid"]),
                         ("direct1", "post", "fixed-id"))
        self.assertEqual(post_text(post), source)
        body = post_text(json.loads(payload["content"]))
        self.assertNotRegex(body, r"(?i)<at\b")
        self.assertIn("**结论**", body)
        self.assertEqual(request.call_args.kwargs["timeout"], 10)
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_oversized_post_rejected_before_any_network_request(self):
        request = Mock()
        api = FeishuApi("cli_app1", "app-secret", requester=request)
        with self.assertRaisesRegex(ValueError, "回复过长"):
            api.send_post("chat1", {"zh_cn": dict(content=[[dict(tag="md", text="中文" * 5000)]])})
        request.assert_not_called()

    def test_expired_token_refreshes_and_bot_identity_is_trusted_api_result(self):
        now = [0]
        request = Mock(side_effect=[self.response(dict(code=0, tenant_access_token="one", expire=120)),
                                    self.response(dict(code=0, bot=dict(open_id="bot1"))),
                                    self.response(dict(code=0, tenant_access_token="two", expire=120))])
        api = FeishuApi("cli_app1", "secret", requester=request, clock=lambda: now[0])
        self.assertEqual(api.bot_id(), "bot1")
        now[0] = 61
        self.assertEqual(api.token(), "two")

    def test_rejected_token_refreshes_on_next_request_without_replaying_send(self):
        request = Mock(side_effect=[self.response(dict(code=0, tenant_access_token="one", expire=7200)),
                                    self.response(dict(code=99991663)),
                                    self.response(dict(code=0, tenant_access_token="two", expire=7200)),
                                    self.response(dict(code=0))])
        api = FeishuApi("cli_app1", "secret", requester=request)
        with self.assertRaises(RuntimeError):
            api.send_text("chat1", "first")
        self.assertEqual(request.call_count, 2)
        api.send_text("chat1", "second")
        self.assertEqual(request.call_count, 4)
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer two")


class NotificationTests(unittest.TestCase):
    def setUp(self):
        StoreTests.setUp(self)
        self.config.save(configured(self.config, push_enabled=True))
        self.project = self.root / "test_project_config.ini"
        self.project.write_text("[project_info]\nproject_name=已保存项目\n", encoding="utf-8")
        self.sent, self.logs = [], []
        api = Mock()
        api.send_text.side_effect = lambda chat, text, identifier=None: self.sent.append((chat, text))
        self.notifier = FeishuNotificationService(self.config, self.project, self.logs.append,
                                                 api_factory=Mock(return_value=api), autostart=False)
        self.addCleanup(self.close_notifier)

    def close_notifier(self):
        self.notifier.begin_close()
        if self.notifier.thread.ident is not None:
            self.notifier.thread.join(4)
        self.assertTrue(self.notifier.idle)

    def send_queued(self):
        job = self.notifier.queue.get_nowait()
        try:
            self.notifier._send(job)
        finally:
            self.notifier.queue.task_done()

    def test_proxy_preserves_original_return_and_never_copies_old_body(self):
        original = Mock()
        original.webhook_send_message.return_value = "original-error"
        events = []
        proxy = TestNotificationProxy(original, events.append)
        proxy.set_channel(3)
        self.assertEqual(proxy.webhook_send_message("device", "private-code remote-password", 0), "original-error")
        original.webhook_send_message.assert_called_once_with("device", "private-code remote-password", 0)
        self.assertEqual(events[0]["channel"], 3)
        self.assertNotIn("private", str(events))

    def test_disabled_dingtalk_or_failed_dingtalk_does_not_block_feishu_event(self):
        original = Mock()
        original.webhook_send_message.side_effect = RuntimeError("dingtalk failed")
        proxy = TestNotificationProxy(original, self.notifier.enqueue)
        proxy.set_channel(2)
        with self.assertRaises(RuntimeError):
            proxy.webhook_send_message("device", "private", 1)
        self.send_queued()
        self.assertIn("通道2", self.sent[0][1])

    def test_only_saved_project_channel_and_result_sent_no_remote_credentials(self):
        self.assertTrue(self.notifier.enqueue(dict(id="one", channel=4, normal=False,
            message="remote_tool password=private-client-code")))
        self.send_queued()
        self.assertEqual(self.sent[0][0], "group1")
        self.assertIn("已保存项目", self.sent[0][1])
        self.assertIn("通道4", self.sent[0][1])
        self.assertIn("异常", self.sent[0][1])
        self.assertNotIn("private-client-code", self.sent[0][1])

    def test_duplicate_event_sends_once(self):
        self.assertTrue(self.notifier.enqueue(dict(id="same")))
        self.assertFalse(self.notifier.enqueue(dict(id="same")))
        self.send_queued()
        self.assertEqual(len(self.sent), 1)

    def test_independent_notification_switch_and_explicit_test_bypass(self):
        self.config.save(dict(self.config.load(), push_enabled=False))
        self.assertFalse(self.notifier.enqueue(dict(id="auto")))
        self.assertTrue(self.notifier.enqueue(dict(id="test"), test=True))
        self.send_queued()
        self.assertIn("测试消息", self.sent[0][1])

    def test_disable_reenable_discards_queued_old_notification(self):
        self.notifier.enqueue(dict(id="old"))
        config = self.config.load()
        self.config.save(dict(config, push_revision=config["push_revision"] + 2))
        self.send_queued()
        self.assertEqual(self.sent, [])

    def test_missing_saved_project_prevents_network(self):
        self.project.write_text("[project_info]\nproject_name=\n", encoding="utf-8")
        self.notifier.enqueue(dict(id="empty"))
        with self.assertRaises(ValueError):
            self.send_queued()
        self.assertFalse(self.sent)

    def test_proxy_channel_context_is_thread_local(self):
        original = Mock()
        barrier = threading.Barrier(2)
        events = []
        proxy = TestNotificationProxy(original, events.append)
        def worker(number):
            proxy.set_channel(number)
            barrier.wait()
            proxy.webhook_send_message("device", "result")
        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertEqual({event["channel"] for event in events}, {1, 2})

    def test_in_process_disable_blocks_automatic_queue_even_if_disk_still_enabled(self):
        self.assertTrue(self.notifier.enqueue(dict(id="old")))
        self.notifier.set_auto_blocked(True)
        self.assertFalse(self.notifier.enqueue(dict(id="new")))
        self.send_queued()
        self.assertEqual(self.sent, [])
        self.assertTrue(self.config.load()["push_enabled"])


class ConversationTests(unittest.TestCase):
    stop_services = fixture.ConversationTests.stop_services

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.project = Path(self.temp.name) / "test_project_config.ini"
        self.project.write_text("[project_info]\nproject_name=项目A\n", encoding="utf-8")
        self.config = FeishuConfigStore(self.temp.name, directory=Path(self.temp.name) / "remote", cipher=FakeCipher())
        self.config.save(configured(self.config, group_enabled=True, p2p_enabled=True))
        self.transport = SimpleNamespace(idle=False, stop=threading.Event())
        self.transport.begin_close = lambda: setattr(self.transport, "idle", True)
        self.transport.start = lambda: None
        self.api = Mock()
        self.remote = FeishuRemoteService(self.service, self.config, self.project,
            transport_factory=Mock(return_value=self.transport), lease_factory=Mock(return_value=Mock()),
            api_factory=Mock(return_value=self.api), autostart=False)
        self.addCleanup(self.close_remote)
        self.message = FeishuMessage.parse(incoming(), "cli_app1", "bot1")

    def close_remote(self):
        self.remote.begin_close()
        for thread in (self.remote.worker, self.remote.sender_thread):
            if thread.ident is not None:
                thread.join(4)
                self.assertFalse(thread.is_alive())
        self.remote.close()

    def dispatch(self, text, message=None):
        message = message or self.message
        self.remote._dispatch(replace(message, text=text, generation=self.remote.generations[message.chat_type]))
        self.service.jobs.join()
        return self.remote._existing(message, self.remote._selected(message))

    def prepare_action(self):
        identifier = self.dispatch("检查")
        self.service.running[identifier] = threading.Event()
        action = self.service.actions._prepare(identifier, "run_local_command", {"command": "Restart-Computer"})
        self.store.change_action(action["id"], ("reviewing",), "waiting_approval",
                                 assessment=asdict(ActionAssessment("dangerous", "会重启电脑")))
        self.remote._publish_approval(identifier, self.message)
        token = next(iter(self.remote.tokens))
        self.addCleanup(lambda: self.service.running.pop(identifier, None))
        return identifier, action, token

    def test_new_remote_session_full_even_desktop_ask_and_sources_visible(self):
        self.store.set_setting("chat_permission_mode", ASK)
        identifier = self.dispatch("检查")
        session = self.store.chat(identifier)
        self.assertEqual(session["permission_mode"], FULL)
        self.assertEqual(self.service.permissions.status(identifier)["mode"], FULL)
        self.assertEqual(session["source"]["kind"], "feishu")
        self.assertIn("飞书 / 群聊", AiRecordTitles(self.store, self.logs.append).chat_entries([session])[0]["origin"])

    def test_dm_group_member_channel_and_app_routing_are_independent(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        first = self.dispatch("通道1 检查")
        dm = replace(self.message, chat_type="p2p", group="direct1")
        direct = self.dispatch("通道1 检查", dm)
        second = self.dispatch("通道2 检查")
        member = self.dispatch("通道1 检查", replace(self.message, sender="user2"))
        self.assertEqual(len({first, direct, second, member}), 4)
        self.assertEqual(self.store.chat(direct)["source"]["chat_type"], "p2p")

    def test_followup_reuses_session_and_batch_change_starts_new_session(self):
        first = self.dispatch("检查")
        self.assertEqual(first, self.dispatch("继续检查"))
        self.context.observe(dict(type="diagnostic_start", run_id="new-run"))
        self.assertNotEqual(first, self.dispatch("继续检查"))

    def test_pc_target_status_and_reply_keep_source_scope(self):
        decision = dict(intent="switch", scope="pc", channel=None, question="检查电脑", clarification="")
        with patch.object(self.service.router, "_resolve", return_value=decision):
            identifier = self.dispatch("只查这台电脑网络")
        self.assertEqual(self.store.chat(identifier)["scope"], "pc")
        self.remote._dispatch(replace(self.message, text="状态", generation=self.remote.generations[self.message.chat_type]))
        self.remote._publish()
        replies = [str(item) for item in list(self.remote.outbox.queue)]
        self.assertTrue(any("本机电脑" in text for text in replies))
        self.assertFalse(any("通道本机电脑" in text for text in replies))

    def test_new_session_retains_background_publishing_route(self):
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

    def test_multiple_targets_require_explicit_channel(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        self.remote._dispatch(self.message)
        identifier = self.remote._existing(self.message, None)
        self.assertEqual(self.store.chat(identifier)["scope"], "general")
        self.assertIn("指定通道", self.store.chat_items(identifier)[-1]["text"])

    def test_other_group_tenant_and_duplicates_are_not_admitted(self):
        self.remote.receive(incoming(chat="other"), "bot1")
        self.remote.receive(incoming(tenant="other"), "bot1")
        self.assertIsNone(self.remote.mailbox.next())
        self.remote.receive(incoming(), "bot1")
        self.remote.receive(incoming(), "bot1")
        self.assertIsNotNone(self.remote.mailbox.next())
        self.assertIsNone(self.remote.mailbox.next())

    def test_dm_all_application_users_need_no_individual_pairing(self):
        self.remote.receive(incoming(kind="p2p", user="new-member"), "bot1")
        payload = self.remote.mailbox.next()
        self.assertEqual(payload["sender"], "new-member")
        self.assertEqual(payload["chat_type"], "p2p")

    def test_p2p_only_config_pins_first_trusted_enterprise(self):
        self.remote.config.update(corp="", group="", group_enabled=False)
        self.remote.receive(incoming(kind="p2p"), "bot1")
        self.assertEqual(self.config.load()["corp"], "tenant1")
        self.remote.receive(incoming(kind="p2p", tenant="other", identifier="new"), "bot1")
        self.assertIsNotNone(self.remote.mailbox.next())
        self.assertIsNone(self.remote.mailbox.next())

    def test_binding_requires_local_confirmation_and_expiry(self):
        self.remote.config.update(group_enabled=False, push_enabled=False)
        code = self.remote.begin_binding()
        self.remote.receive(incoming("绑定 " + code), "bot1")
        candidate = self.remote.snapshot()["candidate"]
        self.remote.confirm_binding(candidate)
        self.assertEqual(self.config.load()["group"], "group1")
        with self.assertRaises(ValueError):
            self.remote.confirm_binding(candidate)
        self.remote.binding_code, self.remote.candidate, self.remote.binding_deadline = "expired", candidate, 0
        with self.assertRaises(ValueError):
            self.remote.confirm_binding(candidate)

    def test_stale_queued_command_cannot_execute_after_disable_reenable(self):
        self.remote.receive(incoming(), "bot1")
        payload = self.remote.mailbox.next()
        self.remote.enable("group", False)
        self.remote.enable("group", True)
        with patch.object(self.service, "send") as send:
            self.remote._dispatch(FeishuMessage(**payload))
        send.assert_not_called()

    def test_deleted_history_does_not_block_reenable(self):
        identifier = self.dispatch("检查")
        self.remote.enable("group", False)
        self.store.delete_chats((identifier,))
        self.remote.enable("group", True)
        self.assertTrue(self.remote.config["group_enabled"])

    def test_notification_disable_takes_effect_in_memory_if_save_fails(self):
        self.remote.config["push_enabled"] = True
        with patch.object(self.config, "save", side_effect=OSError("readonly")):
            with self.assertRaisesRegex(ValueError, "本进程"):
                self.remote.set_push_enabled(False)
        self.assertFalse(self.remote.config["push_enabled"])

    def test_disabling_group_preserves_direct_conversations_and_dingtalk(self):
        group = self.dispatch("检查")
        direct = self.dispatch("检查", replace(self.message, chat_type="p2p", group="direct1"))
        group_stop, direct_stop = threading.Event(), threading.Event()
        self.service.running.update({group: group_stop, direct: direct_stop})
        try:
            self.remote.enable("group", False)
            self.assertTrue(group_stop.is_set())
            self.assertFalse(direct_stop.is_set())
            self.assertTrue(self.remote.config["p2p_enabled"])
        finally:
            self.service.running.pop(group, None)
            self.service.running.pop(direct, None)

    def test_stop_keeps_project_testing_and_busy_question_not_queued(self):
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

    def test_approval_bound_to_sender_chat_and_platform_and_once_only(self):
        _, action, token = self.prepare_action()
        for message in (replace(self.message, sender="user2"), replace(self.message, chat_type="p2p"),
                        replace(self.message, robot="other-app")):
            with self.assertRaises(ValueError):
                self.remote._decide(message, token, True)
        self.remote._decide(self.message, token, True)
        saved = self.store.action(action["id"])
        self.assertEqual(saved["state"], "approved")
        self.assertEqual(saved["approval_source"], "feishu")
        with self.assertRaises(ValueError):
            self.remote._decide(self.message, token, True)

    def test_fingerprint_change_and_expired_token_cannot_approve_revised_action(self):
        identifier, action, token = self.prepare_action()
        self.store.change_action(action["id"], ("waiting_approval",), "waiting_approval", params={"command": "changed"})
        with self.assertRaisesRegex(ValueError, "变化"):
            self.remote._decide(self.message, token, True)
        self.remote.tokens[token]["expires"] = 0
        with self.assertRaisesRegex(ValueError, "过期"):
            self.remote._decide(self.message, token, True)

    def test_expired_unchanged_approval_rejects_original_action(self):
        _, action, token = self.prepare_action()
        self.remote.tokens[token]["expires"] = 0
        self.remote._expire()
        self.assertEqual(self.store.action(action["id"])["state"], "rejected")

    def test_local_and_remote_cannot_approve_same_action_twice(self):
        identifier, action, token = self.prepare_action()
        self.service.actions.decide(identifier, action["id"], action["fingerprint"], True)
        with self.assertRaises(ValueError):
            self.remote._decide(self.message, token, True)

    def test_reply_destination_and_external_credential_filter(self):
        config = self.project.parent / "config.ini"
        config.write_text("[telnet]\ntelnet_input_password_flag=1\npassword=sample-secret\n"
                          "remote_verification_code=remote-secret\n", encoding="utf-8")
        dm = replace(self.message, chat_type="p2p", group="direct1")
        self.assertTrue(self.remote.reply(dm, "10.0.1.1 批准 A01B23 model-secret app-secret sample-secret remote-secret " + TARGET.password, 1))
        message, post, _ = self.remote.outbox.get_nowait()
        text = json.dumps(post, ensure_ascii=False)
        self.assertEqual(message.group, "direct1")
        for secret in ("model-secret", "app-secret", "sample-secret", "remote-secret", TARGET.password):
            if secret:
                self.assertNotIn(secret, text)
        self.assertIn("10.0.1.1", text)
        self.assertIn("批准 A01B23", text)

    def test_plain_recovery_skipped_and_cursor_advanced_without_changing_history(self):
        identifier = self.dispatch("检查")
        key = next(k for k, value in self.remote.mailbox.routes().items() if value[0] == identifier)
        self.remote.mailbox.route(key, identifier, len(self.store.chat_items(identifier)))
        self.service.message(identifier, "system", "  本轮恢复状态：无临时修改\n", "recovery")
        before = self.store.chat_items(identifier)
        with patch.object(self.remote, "reply") as reply:
            self.remote._publish()
            self.remote._publish()
        reply.assert_not_called()
        self.assertEqual(self.remote.mailbox.routes()[key][1], len(before))
        self.assertEqual(self.store.chat_items(identifier), before)

    def test_recovery_warnings_errors_and_assistant_quotes_are_still_published(self):
        identifier = self.dispatch("检查")
        key = next(k for k, value in self.remote.mailbox.routes().items() if value[0] == identifier)
        self.remote.mailbox.route(key, identifier, len(self.store.chat_items(identifier)))
        records = [("system", "recovery", text) for text in (
            "本轮恢复状态：已恢复，临时文件已清理", "本轮恢复状态：恢复失败", "本轮恢复状态：恢复待完成",
            "本轮恢复状态：固定采集：无临时修改；本轮通用操作的实际变更不自动回滚，结果待核实的操作须人工核对。")]
        records.extend([("assistant", "text", "本轮恢复状态：无临时修改"),
                        ("system", "error", "本轮恢复状态：无临时修改")])
        for role, kind, text in records:
            self.service.message(identifier, role, text, kind)
        with patch.object(self.remote, "reply", return_value=True) as reply:
            self.remote._publish()
        self.assertEqual([call.args[1] for call in reply.call_args_list], [r[2] for r in records])

    def test_status_and_approval_are_formatted_and_preserve_exact_parameters(self):
        identifier, action, token = self.prepare_action()
        posts = []
        while not self.remote.outbox.empty():
            posts.append(self.remote.outbox.get_nowait()[1])
        approval = next(post for post in posts if "需要你批准" in post_text(post))
        nodes = [row[0] for row in approval["zh_cn"]["content"]]
        params = next(n for n in nodes if n["tag"] == "code_block")
        self.assertEqual(json.loads(params["text"]), action["params"])
        self.assertEqual(params["language"], "JSON")
        self.assertIn("**原因**：会重启电脑", post_text(approval))
        self.assertIn("**批准 " + token + "**", post_text(approval))
        self.assertIn("**拒绝 " + token + "**", post_text(approval))
        self.assertIn("仅发起人有效，十分钟内单次使用。", post_text(approval))
        self.remote._dispatch(replace(self.message, text="状态"))
        status = self.remote.outbox.get_nowait()[1]
        self.assertIn("**状态**：", post_text(status))
        self.assertIn("**权限**：", post_text(status))
        self.assertEqual(status["zh_cn"]["content"][0][0]["tag"], "md")

    def test_full_queue_rejects_all_parts_and_old_generation_is_not_sent(self):
        self.remote.outbox = queue.Queue(maxsize=1)
        self.assertFalse(self.remote.reply(self.message, "中文" * 5000, 1, markdown=True))
        self.assertTrue(self.remote.outbox.empty())
        self.assertTrue(self.remote.reply(self.message, "**结论**", 1, markdown=True))
        self.remote.generations["group"] += 1
        self.remote.sender_thread.start()
        self.remote.outbox.join()
        self.api.send_post.assert_not_called()

    def test_stream_model_reply_duplicate_receipt_executes_once(self):
        self.remote.transport = self.transport
        self.remote.send_interval = .001
        self.remote.worker.start()
        self.remote.sender_thread.start()
        self.remote.receive(incoming(), "bot1")
        self.remote.receive(incoming(), "bot1")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not any("根据已有证据" in str(c) for c in self.api.send_post.call_args_list):
            time.sleep(.02)
        self.assertTrue(any("根据已有证据" in str(c) for c in self.api.send_post.call_args_list))
        self.assertEqual(len(self.requests), 2)  # 一次路由识别、一次排障；重复回调均不重放。

    def test_send_failure_never_replays_model_or_tools(self):
        self.api.send_post.side_effect = RuntimeError("network")
        self.remote.transport = self.transport
        self.remote.send_interval = .001
        self.remote.worker.start()
        self.remote.sender_thread.start()
        self.remote.receive(incoming(), "bot1")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any("回复发送失败" in text for text in self.logs):
            time.sleep(.02)
        self.remote.receive(incoming(), "bot1")
        self.service.jobs.join()
        self.assertEqual(len(self.requests), 2)  # 回复失败不重做路由或排障。
        self.assertTrue(any("回复发送失败" in text for text in self.logs))

    @patch("src.services.ai_action_service.run_local_command")
    def test_actual_action_chain_requires_approval_and_executes_exactly_once(self, execute):
        identifier = self.dispatch("检查")
        self.service.permissions.select(identifier, AUTO)
        stop, result = threading.Event(), []
        self.service.running[identifier] = stop
        execute.return_value = dict(status="completed", exit_code=0, process_cleanup_confirmed=True)
        def run():
            try:
                result.append(self.service.actions.execute(identifier, "run_local_command", {"command": "Restart-Computer"},
                    TARGET, stop, Mock(transport=None), Mock(return_value=ActionAssessment("dangerous", "会重启电脑"))))
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

    @patch("src.services.ai_action_service.run_local_command")
    def test_default_full_group_and_direct_skip_review_with_separate_grants(self, execute):
        execute.return_value = dict(status="completed", exit_code=0, process_cleanup_confirmed=True)
        grants = set()
        for message in (self.message, replace(self.message, chat_type="p2p", group="direct1")):
            identifier = self.dispatch("检查", message)
            grants.add(self.service.permissions.status(identifier)["grant_id"])
            review = Mock(side_effect=AssertionError("默认完全访问不应调用独立审查"))
            stop = threading.Event()
            self.service.running[identifier] = stop
            try:
                result = self.service.actions.execute(identifier, "run_local_command", {"command": "Restart-Computer"},
                    TARGET, stop, Mock(transport=None), review)
            finally:
                self.service.running.pop(identifier, None)
            self.assertEqual(result["action_state"], "succeeded")
            review.assert_not_called()
        self.assertEqual(len(grants), 2)
        self.assertNotIn("", grants)
        self.assertEqual(execute.call_count, 2)

    def test_dingtalk_and_feishu_share_workbench_but_not_sessions_or_approval_tokens(self):
        import test_dingtalk_remote as ding
        store = ding.RemoteConfigStore(self.temp.name, directory=self.config.directory, cipher=FakeCipher())
        store.save(ding.configured(store))
        remote = ding.DingTalkRemoteService(self.service, store, self.project, autostart=False,
                                            lease_factory=Mock(return_value=Mock()))
        try:
            identifier = self.dispatch("检查")
            message = ding.RemoteMessage.parse(ding.incoming())
            remote._dispatch(message)
            self.service.jobs.join()
            other = list(remote.mailbox.routes().values())[-1][0]
            self.assertIs(remote.conversation, self.remote.conversation)
            self.assertNotEqual(identifier, other)
            self.assertEqual(self.store.chat(other)["source"]["kind"], "dingtalk")
            _, _, token = self.prepare_action()
            with self.assertRaises(ValueError):
                remote._decide(message, token, True)
            self.remote.enable("group", False)
            self.assertTrue(remote.config["enabled"])
        finally:
            remote.begin_close()
            remote.close()


class IntegrationTests(unittest.TestCase):
    def test_notification_event_reaches_main_service_without_ai_or_model(self):
        from line_check_assistant.app import LineCheckAssistant
        from src.services.legacy_power_test_service import run_legacy_power_test, prepare_legacy_power_test_request, LegacyPowerChannel
        import test_legacy_power_test_service as legacy
        class Process(legacy._CompletedProcess):
            def start(self):
                self.args[1].put(dict(type="test_notification", id="notice1", channel=2, normal=True))
                self.args[1].put(dict(type="result", ok=True, detail="original-result"))
                self._alive = False
        class Context(legacy._FakeProcessContext):
            def Process(self, **kwargs):
                return Process(**kwargs)
        notifier = Mock()
        app = SimpleNamespace(_feishu_notification_service=lambda: notifier)
        def observer(event):
            if event.get("type") == "test_notification":
                LineCheckAssistant._observe_ai_power_event(app, event)
        with tempfile.TemporaryDirectory() as directory:
            root = legacy._write_config_tree(Path(directory))
            request = prepare_legacy_power_test_request(root, (LegacyPowerChannel(2, "192.168.1.102"),))
            result = run_legacy_power_test(request, Mock(), legacy._FakeEvent(), process_context=Context(),
                                           diagnostic_observer=observer)
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "original-result")
        self.assertEqual(notifier.enqueue.call_count, 1)
        self.assertEqual(notifier.enqueue.call_args.args[0]["channel"], 2)
        self.assertFalse(hasattr(app, "ai_assistant"))

    def test_feishu_only_hidden_controller_shares_project_store_and_waits_for_both_platforms(self):
        import os
        import tkinter as tk
        from tk_test_windows import OffscreenTkWindows
        from src.ui.ai_assistant_controller import AiAssistantController
        from src.services.dingtalk_remote_store import RemoteConfigStore
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "user")}), OffscreenTkWindows():
            root = tk.Tk()
            controller = None
            project = Path(directory) / "project.ini"
            project.write_text("[project_info]\nproject_name=offline\n", encoding="utf-8")
            config = FeishuConfigStore(directory, directory=Path(directory) / "ai", cipher=FakeCipher())
            config.save(configured(config))
            ding = RemoteConfigStore(directory, directory=config.directory, cipher=FakeCipher())
            try:
                with patch("src.services.feishu_remote_store.FeishuConfigStore", return_value=config), \
                     patch("src.services.dingtalk_remote_store.RemoteConfigStore", return_value=ding):
                    terminal = SimpleNamespace(ai_debug_cancel=None, diagnostic_observer=None)
                    args = (root, terminal, Mock(), lambda: (TARGET,), lambda _target: False, lambda: "", Mock(), None)
                    controller = AiAssistantController(*args, app_dir=directory, project_config_path=project)
                    self.assertIsNone(controller.dialog.window)
                    self.assertEqual(controller.service.store.directory, config.directory)
                    self.assertIs(controller.remote.conversation, controller.feishu_remote.conversation)
                    with patch("src.services.ai_store.DiagnosticStore") as database:
                        with self.assertRaisesRegex(RuntimeError, "另一进程"):
                            AiAssistantController(*args, app_dir=directory, project_config_path=project)
                        database.assert_not_called()
                    controller._refresh_remote_targets()
                    self.assertEqual(tuple(controller.service.targets), (TARGET.channel,))
            finally:
                if controller is not None:
                    deadline = time.monotonic() + 4
                    while not controller.prepare_app_close() and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    self.assertTrue(controller.closed)
                    self.assertTrue(controller.remote.idle)
                    self.assertTrue(controller.feishu_remote.idle)
                root.destroy()

    def test_setup_native_switches_theme_secret_and_single_chat_confirmation(self):
        import tkinter as tk
        from tkinter import ttk
        from tk_test_windows import OffscreenTkWindows
        from src.ui.feishu_setup_window import FeishuSetupWindow
        with tempfile.TemporaryDirectory() as directory, OffscreenTkWindows() as windows:
            root = tk.Tk()
            try:
                config = FeishuConfigStore(directory, directory=directory, cipher=FakeCipher())
                config.save(configured(config))
                runtime = Mock(config=config.load())
                runtime.snapshot.return_value = dict(status="未启用", candidate=None, binding=False)
                notifier = Mock(busy=False, last_result="尚未试发")
                for theme in ("vista", "clam"):
                    ttk.Style(root).theme_use(theme)
                    dialog = FeishuSetupWindow(root, config, lambda: runtime, notifier, Mock())
                    root.update_idletasks()
                    self.assertEqual(dialog.window.cget("background"), "#eef2f5")
                    checks = [w for w in dialog.window.winfo_children() if isinstance(w, tk.Checkbutton)]
                    self.assertEqual(len(checks), 3)
                    self.assertEqual(dialog.variables["app_secret"].get(), "")
                    self.assertTrue(all(not var.get() for var in dialog.switches.values()))
                    with patch("src.ui.feishu_setup_window.messagebox.askyesno", return_value=False) as confirm:
                        checks[1].invoke()
                        self.assertIn("所有企业成员", confirm.call_args.args[1])
                        runtime.enable.assert_not_called()
                        self.assertFalse(dialog.switches["p2p"].get())
                    with patch("src.ui.feishu_setup_window.messagebox.askyesno", return_value=True):
                        checks[1].invoke()
                        runtime.enable.assert_called_with("p2p", True)
                    runtime.enable.reset_mock()
                    dialog.test()
                    notifier.enqueue.assert_called_with({}, test=True)
                    dialog.close()
                windows.assert_offscreen()
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()

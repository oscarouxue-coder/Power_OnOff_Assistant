"""流式回复离线回归；平台HTTP、模型和设备均使用替身。"""
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_reply_cards import CardRejected, CardUnavailable, CardStopped, FeishuReplyCard, DingTalkReplyCard
from src.services.ai_reply_stream_service import ReplyStreamService, card_segment
from src.services.dingtalk_remote_store import RemoteConfigStore
from src.services.feishu_output import sanitize
from src.utils.ai_redaction import hold_secret_prefix
import test_ai_conversation as fixtures
import test_ai_chat_presentation as ui_fixtures
import test_feishu_remote as feishu_fixtures
import test_dingtalk_remote as dingtalk_fixtures
from test_ai_core import FakeCipher, FakeResponse, chat


def snapshot(text, state="generating", identifier="reply1"):
    return dict(role="assistant", kind="stream" if state == "generating" else "text", text=text,
                reply_id=identifier, stream_state=state)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.mailbox = SimpleNamespace(db=self.db, lock=threading.RLock())
        self.card = Mock()
        self.card.create.side_effect = lambda message, title, text, key: {"key": key}
        self.clock = Mock(return_value=10)
        self.allowed = Mock(return_value=True)
        self.send, self.emit = Mock(), Mock()
        self.factory = Mock(return_value=self.card)
        self.publisher = self.make_publisher()
        self.message = SimpleNamespace(group="group")

    def make_publisher(self):
        return ReplyStreamService(self.mailbox, self.factory, self.allowed,
            lambda text, **kwargs: text, self.send, self.emit, clock=self.clock)

    def offer(self, text, state="generating", identifier="reply1"):
        return self.publisher.offer("session", self.message, snapshot(text, state, identifier), "项目 | 成员", 2)

    def test_partial_visible_before_final_and_final_is_not_sent_twice(self):
        self.assertFalse(self.offer("首段"))
        self.publisher.tick()
        self.card.update.assert_called_once_with({"key": self.card.create.call_args.args[-1]}, "首段", False, failed=False)
        self.offer("首段结尾", "completed")
        self.publisher.tick()
        self.assertTrue(self.offer("首段结尾", "completed"))
        self.publisher.tick()
        self.assertEqual(self.card.create.call_count, 1)
        self.assertEqual(self.card.update.call_count, 2)
        self.assertEqual(self.card.update.call_args.args[1:3], ("首段结尾", True))
        self.send.assert_not_called()

    def test_updates_coalesce_and_are_limited_to_once_a_second(self):
        self.offer("一")
        self.publisher.tick()
        self.clock.return_value = 10.2
        self.offer("一二")
        self.offer("一二三")
        self.publisher.tick()
        self.assertEqual(self.card.update.call_count, 1)
        self.clock.return_value = 11.1
        self.publisher.tick()
        self.assertEqual(self.card.update.call_args.args[1], "一二三")
        self.clock.return_value = 12.2
        self.publisher.tick()
        self.assertEqual(self.card.update.call_count, 2)

    def test_late_draft_cannot_replace_final(self):
        self.offer("最终内容", "completed")
        self.offer("早期草稿")
        self.publisher.tick()
        self.assertEqual(self.card.update.call_args.args[1:3], ("最终内容", True))

    def test_final_bypasses_update_throttle(self):
        self.offer("正在生成")
        self.publisher.tick()
        self.offer("已完成", "completed")
        self.publisher.tick()
        self.assertEqual(self.card.update.call_count, 2)

    def test_known_rejection_falls_back_once_on_completion(self):
        self.card.create.side_effect = CardUnavailable("未配置模板")
        self.offer("草稿")
        self.publisher.tick()
        self.send.assert_not_called()
        self.offer("完整正文", "completed")
        self.publisher.tick()
        self.assertEqual(self.send.call_args.args[2], "完整正文")
        self.assertTrue(self.offer("完整正文", "completed"))
        self.publisher.tick()
        self.send.assert_called_once()

    def test_final_only_json_response_also_uses_card_and_never_retries_model(self):
        self.offer("完整JSON正文", "completed")
        self.publisher.tick()
        self.card.create.assert_called_once()
        self.assertEqual(self.card.update.call_args.args[2], True)

    def test_unknown_delivery_is_never_retried_or_downgraded(self):
        self.card.create.side_effect = TimeoutError()
        self.offer("正文")
        self.publisher.tick()
        self.assertTrue(self.offer("完整正文", "completed"))
        self.publisher.tick()
        self.card.create.assert_called_once()
        self.send.assert_not_called()
        self.assertEqual(self.publisher._row("reply1")[0], "unknown")

    def test_update_unknown_does_not_create_second_message(self):
        self.offer("草稿")
        self.publisher.tick()
        self.card.update.side_effect = TimeoutError()
        self.offer("最终", "completed")
        self.publisher.tick()
        self.assertTrue(self.offer("最终", "completed"))
        self.assertEqual(self.card.create.call_count, 1)
        self.send.assert_not_called()

    def test_failed_fallback_is_not_looped(self):
        self.card.create.side_effect = CardRejected("权限不足")
        self.send.side_effect = CardRejected("完整回复也被拒绝")
        self.offer("最终", "completed")
        self.publisher.tick()
        self.publisher.tick()
        self.publisher.tick()
        self.send.assert_called_once()
        self.assertEqual(self.publisher._row("reply1")[0], "unknown")

    def test_restart_marks_active_card_unknown_and_does_not_replay(self):
        self.offer("草稿")
        self.publisher.tick()
        other = self.make_publisher()
        self.assertTrue(other.offer("session", self.message, snapshot("最终", "completed"), "标题", 2))
        other.tick()
        self.assertEqual(self.card.create.call_count, 1)
        self.send.assert_not_called()

    def test_disable_or_generation_change_blocks_updates(self):
        self.offer("草稿")
        self.allowed.return_value = False
        self.publisher.tick()
        self.card.create.assert_not_called()
        self.assertEqual(self.publisher._row("reply1")[0], "skipped")

    def test_cancelled_partial_is_finalized_as_failed(self):
        self.offer("部分正文")
        self.publisher.tick()
        self.offer("部分正文\n[回复未完成，已取消]", "cancelled")
        self.publisher.tick()
        self.assertEqual(self.card.update.call_args.kwargs, {"failed": True})
        self.assertTrue(self.card.update.call_args.args[2])

    def test_failure_marker_cannot_release_held_credential_prefix(self):
        def sanitize(text, *, streaming=False):
            return hold_secret_prefix(text, ["device-secret"]) if streaming else text
        self.publisher.sanitize = sanitize
        self.offer("密码device-\n\n[回复未完成，生成失败]", "failed")
        self.publisher.tick()
        sent = self.card.update.call_args.args[1]
        self.assertNotIn("device-", sent)
        self.assertIn("回复未完成", sent)

    def test_long_reply_freezes_segments_and_preserves_every_character(self):
        text = '中文😀\\"\n' * 1500
        self.offer(text, "completed")
        for _ in range(30):
            self.publisher.tick()
            if not self.publisher.pending:
                break
        parts = [c.args[1] for c in self.card.update.call_args_list]
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(c.args[2] for c in self.card.update.call_args_list))
        self.assertEqual(self.publisher._row("reply1")[0], "done")

    def test_nine_minute_card_rollover_does_not_duplicate_frozen_text(self):
        self.offer("已有正文")
        self.publisher.tick()
        self.clock.return_value = 551
        self.publisher.tick()
        self.assertTrue(self.card.update.call_args.args[2])
        self.clock.return_value = 553
        self.publisher.tick()
        self.assertEqual(self.card.create.call_count, 1)
        self.offer("已有正文后续", "completed")
        self.publisher.tick()
        self.assertEqual(self.card.create.call_count, 2)
        self.assertEqual(self.card.update.call_args.args[1], "后续")

    def test_sanitization_failure_never_sends_raw_text(self):
        self.publisher.sanitize = Mock(side_effect=ValueError("不允许外发"))
        self.offer("private-secret")
        self.publisher.tick()
        self.card.create.assert_not_called()
        self.send.assert_not_called()
        self.assertNotIn("private-secret", str(self.emit.call_args_list))

    def test_close_rejection_after_final_content_does_not_duplicate_answer(self):
        def update(handle, text, final, **kwargs):
            handle["final_text_accepted"] = True
            raise CardRejected("状态关闭被拒绝")
        self.card.update.side_effect = update
        self.offer("完整正文", "completed")
        self.publisher.tick()
        self.assertEqual(self.publisher._row("reply1")[0], "done")
        self.send.assert_not_called()


class CardAdapterTests(unittest.TestCase):
    def test_feishu_card_lifecycle_and_strictly_increasing_sequence(self):
        api, guard, emit = Mock(), Mock(return_value=True), Mock()
        api._authorized.side_effect = [{"data": {"card_id": "card1"}}, {"data": {"message_id": "message1"}}, {}, {}, {}]
        card = FeishuReplyCard(api, guard, emit)
        handle = card.create(SimpleNamespace(group="chat1"), "标题", "首段", "id1")
        card.update(handle, "首段", False)
        card.update(handle, "完整正文", True)
        calls = api._authorized.call_args_list
        body = json.loads(calls[0].args[2]["data"])
        self.assertTrue(body["config"]["streaming_mode"])
        self.assertEqual(calls[1].args[2]["msg_type"], "interactive")
        self.assertEqual([c.args[2]["sequence"] for c in calls[2:]], [1, 2, 3])
        self.assertEqual(json.loads(calls[-1].args[2]["settings"]), {"streaming_mode": False})

    def test_feishu_create_entity_failure_is_safe_to_fallback(self):
        api = Mock()
        api._authorized.side_effect = TimeoutError()
        with self.assertRaises(CardUnavailable):
            FeishuReplyCard(api, lambda: True, Mock()).create(SimpleNamespace(group="chat"), "标题", "正文", "id")
        api._authorized.assert_called_once()

    def test_feishu_delivery_timeout_is_unknown(self):
        api = Mock()
        api._authorized.side_effect = [{"data": {"card_id": "card"}}, TimeoutError()]
        with self.assertRaises(TimeoutError):
            FeishuReplyCard(api, lambda: True, Mock()).create(SimpleNamespace(group="chat"), "标题", "正文", "id")

    def test_guard_rechecked_between_entity_create_and_delivery(self):
        api = Mock()
        api._authorized.return_value = {"data": {"card_id": "card"}}
        with self.assertRaises(CardStopped):
            FeishuReplyCard(api, Mock(side_effect=[True, False]), Mock()).create(SimpleNamespace(group="chat"), "标题", "正文", "id")
        api._authorized.assert_called_once()

    def test_dingtalk_uses_template_full_updates_and_token_cache(self):
        response = Mock(status_code=200)
        response.json.side_effect = [{"accessToken": "hidden-token", "expireIn": 7200}, {}, {}, {}, {}]
        request = Mock(return_value=response)
        emit = Mock()
        card = DingTalkReplyCard(dict(client_id="app", client_secret="private-secret", robot_code="robot", ai_card_template_id="template.schema"),
                                lambda: True, emit, {}, requester=request)
        handle = card.create(SimpleNamespace(group="group"), "项目 | 用户", "正文", "id")
        card.update(handle, "正文", False)
        card.update(handle, "最终正文", True)
        calls = request.call_args_list
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(c.kwargs["allow_redirects"] is False for c in calls))
        self.assertTrue(all(c.kwargs["timeout"] == 10 for c in calls))
        self.assertEqual(calls[1].kwargs["json"]["cardTemplateId"], "template.schema")
        self.assertNotIn("atUserIds", calls[1].kwargs["json"]["imGroupOpenDeliverModel"])
        self.assertEqual(calls[-2].kwargs["json"]["key"], "msgContent")
        self.assertTrue(calls[-2].kwargs["json"]["isFull"])
        self.assertTrue(calls[-2].kwargs["json"]["isFinalize"])
        self.assertEqual(calls[-1].kwargs["json"]["cardData"]["cardParamMap"]["flowStatus"], "3")
        self.assertNotIn("hidden-token", str(emit.call_args_list))
        self.assertNotIn("private-secret", str(emit.call_args_list))
        self.assertEqual(response.close.call_count, 5)

    def test_dingtalk_missing_template_does_not_call_network(self):
        request = Mock()
        card = DingTalkReplyCard({}, lambda: True, Mock(), {}, requester=request)
        with self.assertRaises(CardUnavailable):
            card.create(SimpleNamespace(group="g"), "标题", "正文", "id")
        request.assert_not_called()

    def test_dingtalk_permission_rejection_and_timeout_are_distinct(self):
        for failure, expected in ((Mock(status_code=403), CardRejected), (TimeoutError(), RuntimeError)):
            requester = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
            card = DingTalkReplyCard({}, lambda: True, Mock(), {}, requester=requester)
            with self.assertRaises(expected):
                card.request("PUT", "/v1.0/card/streaming", {})
            requester.assert_called_once()


class ConversationStreamTests(unittest.TestCase):
    setUp = fixtures.ConversationTests.setUp
    stop_services = fixtures.ConversationTests.stop_services

    def stream_response(self, *, fail=False, cancelled=False):
        entered, release = threading.Event(), threading.Event()
        response = FakeResponse({})
        def content(size):
            self.assertEqual(size, 1)
            yield ('data: ' + json.dumps({"choices": [{"delta": {"content": "首段中文"}}]}, ensure_ascii=False) + '\n\n').encode()
            entered.set()
            if not release.wait(5):
                raise ValueError("测试等待超时")
            if fail:
                raise ValueError("模拟断流")
            yield b'data: {"choices":[{"delta":{"content":" ending"}}]}\n\n'
            yield b'data: [DONE]\n\n'
        response.iter_content = content
        return response, entered, release

    def test_regular_chat_streams_before_completion_and_persists_once(self):
        response, entered, release = self.stream_response()
        self.responses.append(response)
        try:
            self.service.send(self.id, "普通问题", diagnosis_only=False)
            self.assertTrue(entered.wait(5))
            draft = self.service.draft_message(self.id)
            self.assertEqual(draft["text"], "首段中文")
            self.assertFalse(any(m["role"] == "assistant" for m in self.store.chat_items(self.id)))
            self.assertTrue(self.requests[-1]["stream"])
        finally:
            release.set()
        self.service.jobs.join()
        replies = [m for m in self.store.chat_items(self.id) if m["role"] == "assistant"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["text"], "首段中文 ending")
        self.assertEqual(replies[0]["reply_id"], draft["reply_id"])
        self.assertEqual(replies[0]["stream_state"], "completed")
        self.assertIsNone(self.service.draft_message(self.id))
        self.assertEqual(len(self.requests), 1)

    def test_broken_stream_partial_is_display_only(self):
        self.check_incomplete(fail=True)

    def test_cancelled_stream_partial_is_display_only(self):
        self.check_incomplete(cancelled=True)

    def test_missing_canonical_text_does_not_leave_remote_card_generating(self):
        original = self.diag.client_factory
        def factory(*args):
            client = original(*args)
            complete = client.complete_stream
            def streamed(*args, **kwargs):
                kwargs["on_text"]("已生成但最终响应丢失的正文")
                return complete(*args, **kwargs)
            client.complete_stream = streamed
            return client
        self.diag.client_factory = factory
        self.responses.append(chat(""))
        self.service.send(self.id, "问题", diagnosis_only=False)
        self.service.jobs.join()
        partials = [m for m in self.store.chat_items(self.id) if m.get("kind") == "incomplete"]
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0]["stream_state"], "failed")
        self.assertIsNone(self.service.draft_message(self.id))

    def check_incomplete(self, fail=False, cancelled=False):
        response, entered, release = self.stream_response(fail=fail)
        self.responses.append(response)
        try:
            self.service.send(self.id, "问题", diagnosis_only=False)
            self.assertTrue(entered.wait(5))
            if cancelled:
                self.service.stop(self.id)
        finally:
            release.set()
        self.service.jobs.join()
        partials = [m for m in self.store.chat_items(self.id) if m.get("kind") == "incomplete"]
        self.assertEqual(len(partials), 1)
        self.assertIn("回复未完成", partials[0]["text"])
        self.assertEqual(partials[0]["stream_state"], "cancelled" if cancelled else "failed")
        self.assertNotIn("首段中文", json.dumps(self.store.chat_items(self.id, group=True), ensure_ascii=False))
        self.assertFalse(self.store.actions(self.id))
        self.assertIsNone(self.service.draft_message(self.id))
        self.assertEqual(len(self.requests), 1)


class CredentialAndConfigTests(unittest.TestCase):
    def test_cross_chunk_known_credentials_are_withheld(self):
        self.assertEqual(hold_secret_prefix("输出private-", ["private-secret"]), "输出")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.ini"
            path.write_text("[device]\npassword=device-pass\n", encoding="utf-8")
            self.assertEqual(sanitize("密码device-", path, streaming=True), "密码")
            self.assertNotIn("device-pass", sanitize("密码device-pass完成", path, streaming=True))
            self.assertEqual(sanitize("普通尾部dev", path), "普通尾部dev")

    def test_legacy_config_default_and_template_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            config = RemoteConfigStore(directory, directory, FakeCipher())
            self.assertEqual(config.load()["ai_card_template_id"], "")
            values = dict(config.load(), ai_card_template_id="my-template.schema")
            config.save(values)
            self.assertEqual(config.load()["ai_card_template_id"], "my-template.schema")

    def test_segment_serialization_stays_bounded(self):
        for text in ('😀中文\\"\n' * 3000, "a" * 50000):
            segment = card_segment(text)
            self.assertLessEqual(len(json.dumps(segment)) - 2, 12000)
            self.assertTrue(text.startswith(segment))


class UiStreamTests(unittest.TestCase):
    setUp = ui_fixtures.ChatPresentationTests.setUp
    tearDown = ui_fixtures.ChatPresentationTests.tearDown
    wait_route = ui_fixtures.ChatPresentationTests.wait_route

    def test_only_active_draft_is_replaced_and_final_appears_once(self):
        self.messages.append(dict(role="user", kind="text", text="历史消息", created=self.time))
        draft = dict(snapshot("正在生成"), created=self.time)
        self.service.draft_message.return_value = draft
        self.panel.render()
        self.panel.output.tag_add("sel", "2.0", "2.2")
        selection = self.panel.output.tag_ranges("sel")
        self.service.draft_message.return_value = dict(draft, text="正在生成更多内容")
        with patch.object(self.panel.output, "delete", wraps=self.panel.output.delete) as delete:
            self.panel.render()
            self.assertNotEqual(delete.call_args.args[0], "1.0")
        self.assertEqual(self.panel.output.tag_ranges("sel"), selection)
        final = dict(draft, kind="text", text="最终正文", stream_state="completed")
        self.messages.append(final)
        self.service.draft_message.return_value = None
        self.panel.render()
        content = self.panel.output.get("1.0", "end")
        self.assertEqual(content.count("最终正文"), 1)
        self.assertIn("历史消息", content)
        self.assertNotIn("正在生成", content)

    def test_switching_session_does_not_append_previous_draft(self):
        self.service.draft_message.return_value = dict(snapshot("会话一正文"), created=self.time)
        self.panel.render()
        self.panel.selected = "s2"
        self.service.draft_message.return_value = dict(snapshot("会话二正文", identifier="reply2"), created=self.time)
        self.panel.render()
        self.assertNotIn("会话一正文", self.panel.output.get("1.0", "end"))
        self.assertIn("会话二正文", self.panel.output.get("1.0", "end"))


class FeishuBridgeTests(unittest.TestCase):
    setUp = feishu_fixtures.ConversationTests.setUp
    close_remote = feishu_fixtures.ConversationTests.close_remote
    stop_services = fixtures.ConversationTests.stop_services
    dispatch = feishu_fixtures.ConversationTests.dispatch

    def test_group_and_direct_final_cards_are_correlated_and_not_duplicated(self):
        for kind in ("group", "p2p"):
            message = replace(self.message, chat_type=kind, group="group1" if kind == "group" else "direct1")
            identifier = self.dispatch("检查", message=message)
            self.api._authorized.side_effect = [{"data": {"card_id": "c"}}, {"data": {"message_id": "m"}}, {}, {}]
            before = self.api._authorized.call_count
            self.remote._publish()
            self.remote.reply_streams.tick()
            self.remote._publish()
            self.remote.reply_streams.tick()
            self.assertEqual(self.api._authorized.call_count - before, 4)
            final = next(m for m in self.store.chat_items(identifier) if m.get("reply_id"))
            self.assertEqual(self.remote.reply_streams._row(final["reply_id"])[0], "done")
            self.api.send_post.assert_not_called()

    def test_card_permission_missing_sends_original_post_once(self):
        identifier = self.dispatch("检查")
        self.api._authorized.side_effect = CardRejected("没有卡片权限")
        self.remote._publish()
        self.remote.reply_streams.tick()
        self.remote.reply_streams.tick()
        self.remote._publish()
        self.remote.reply_streams.tick()
        self.api.send_post.assert_called_once()
        final = next(m for m in self.store.chat_items(identifier) if m.get("reply_id"))
        self.assertIn(final["text"], feishu_fixtures.post_text(self.api.send_post.call_args.args[1]))

    def test_generation_revocation_blocks_queued_card(self):
        self.dispatch("检查")
        self.remote._publish()
        self.remote.generations["group"] += 1
        self.remote.reply_streams.tick()
        self.api._authorized.assert_not_called()

    def test_partial_card_uses_existing_source_and_external_secret_filter(self):
        identifier = self.remote._session(self.message, fixtures.TARGET.channel)
        self.service._draft(identifier, "正文app-sec")
        draft = self.service.draft_message(identifier)
        self.api._authorized.side_effect = [{"data": {"card_id": "c"}}, {"data": {"message_id": "m"}}, {}]
        self.remote._publish()
        self.remote.reply_streams.tick()
        calls = self.api._authorized.call_args_list
        self.assertNotIn("app-sec", str(calls))
        self.assertEqual(calls[1].args[2]["receive_id"], "group1")
        self.assertEqual(self.remote.reply_streams._row(draft["reply_id"])[0], "active")


class DingTalkBridgeTests(unittest.TestCase):
    setUp = dingtalk_fixtures.RemoteConversationTests.setUp
    close_remote = dingtalk_fixtures.RemoteConversationTests.close_remote
    stop_services = fixtures.ConversationTests.stop_services
    dispatch = dingtalk_fixtures.RemoteConversationTests.dispatch

    def test_legacy_no_template_falls_back_once(self):
        self.remote.sender = Mock()
        self.remote.session_sender = Mock()
        self.dispatch("检查")
        self.remote._publish()
        self.remote.reply_streams.tick()
        self.remote.reply_streams.tick()
        self.remote._publish()
        self.remote.reply_streams.tick()
        self.remote.sender.assert_called_once()
        self.remote.session_sender.assert_not_called()

    def test_card_final_not_sent_through_webhook_again(self):
        card = Mock()
        card.create.return_value = {"outTrackId": "card"}
        self.remote._stream_card = Mock(return_value=card)
        self.remote.reply_streams.card_factory = self.remote._stream_card
        self.remote.sender = Mock()
        self.dispatch("检查")
        self.remote._publish()
        self.remote.reply_streams.tick()
        self.remote._publish()
        self.remote.reply_streams.tick()
        card.create.assert_called_once()
        card.update.assert_called_once()
        self.assertTrue(card.update.call_args.args[2])
        self.remote.sender.assert_not_called()

    def test_rebinding_cannot_send_card_to_old_group(self):
        self.remote.sender = Mock()
        self.remote.reply_streams.card_factory = Mock()
        self.dispatch("检查")
        self.remote._publish()
        self.remote.config["group"] = "another-group"
        self.remote.reply_streams.tick()
        self.remote.reply_streams.card_factory.assert_not_called()
        self.remote.sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()

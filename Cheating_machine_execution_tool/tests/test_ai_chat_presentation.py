"""对话显示专项：真实Tk、模拟只读数据，无API/设备或真实用户数据库。"""
import copy
import gc
import queue
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ui.ai_chat_panel import AiChatPanel, format_chat_time


class TimeDisplayTests(unittest.TestCase):
    def test_iso_offsets_fraction_and_legacy_times_preserve_clock_value(self):
        for value in ("2026-11-11T23:38:41+08:00", "2026-11-11T23:38:41.123456+08:00",
                      "2026-11-11T23:38:41", "2026-11-11 23:38:41", "2026-11-11T23:38:41Z",
                      "2026-11-11T23:38:41-05:00"):
            with self.subTest(value=value):
                self.assertEqual(format_chat_time(value), "2026-11-11 23:38:41")

    def test_invalid_historical_time_is_not_guessed(self):
        for value in ("", "历史时间未知", "2026-99-11T23:38:41+08:00"):
            self.assertEqual(format_chat_time(value), value)


class ChatPresentationTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.root = tk.Tk()
        self.root.geometry("1040x760")
        self.time = "2026-11-11T23:38:41+08:00"
        self.messages = []
        self.session = {"id": "s1", "created": self.time, "title": "显示验证", "status": "可继续",
                        "run_id": "fixture", "target": {"channel": 1},
                        "profile": {"provider": "测试", "model": "fixture", "base_url": "https://example.test"}}
        self.items = [{"id": "evidence1", "created": self.time, "timing": "测试记录",
                       "source": "fixture.log", "text": "证据原文\n原始时间：" + self.time}]
        self.store = Mock()
        self.store.chats.return_value = [self.session]
        self.store.chat.return_value = self.session
        self.store.chat_items.side_effect = lambda _id: self.messages
        self.store.chat_evidence.return_value = self.items
        self.service = Mock(store=self.store, lock=threading.RLock(), running={})
        self.service.collection_status.return_value = {"enabled": False, "capable": True, "reason": "历史批次仅分析留存材料"}
        self.service.context_status.return_value = {"capacity": 1048576, "source": "模型接口（缓存）",
                                                  "max_output": 4096, "snapshot": {}, "stale": False}
        self.owner = Mock(window=self.root, background_color="#eef2f5", targets=())
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        self.panel = AiChatPanel(frame, self.owner, self.service)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()
        del self.panel, self.owner, self.root
        gc.collect()

    def add(self, role, text, kind="text"):
        self.messages.append({"role": role, "text": text, "kind": kind, "created": self.time})

    def rendered(self):
        self.panel.render()
        self.root.update_idletasks()
        return self.panel.output.get("1.0", "end-1c")

    def test_default_collection_buttons_without_status_banner_and_minimum_layout(self):
        def widgets(widget):
            return [widget] + [item for child in widget.winfo_children() for item in widgets(child)]

        def assert_no_status_banner():
            labels = [str(w.cget("text")) for w in widgets(self.panel.parent) if isinstance(w, ttk.Label)]
            for fragment in ("批次：", "默认允许主动采集", "有效会话开放", "真实诊断信息",
                             "模型API密钥", "目标已变更", "选择目标并新建会话"):
                self.assertFalse(any(fragment in text for text in labels), fragment)
            self.assertIs(self.panel.parent.winfo_children()[2], self.panel.context_status)

        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                self.root.geometry("940x660")
                other = dict(self.session, id="s2", target={"channel": 2})
                self.store.chats.return_value = [self.session, other]
                self.store.chat.side_effect = {"s1": self.session, "s2": other}.__getitem__
                self.panel.selected = "s1"
                self.service.collection_status.return_value = {
                    "enabled": True, "capable": True, "reason": "默认允许主动采集"}
                self.panel.refresh()
                self.root.update()
                assert_no_status_banner()
                items = [w for w in widgets(self.panel.parent) if isinstance(w, ttk.Button)]
                titles = [b.cget("text") for b in items]
                self.assertNotIn("授权本次会话", titles)
                self.assertNotIn("结束授权", titles)
                self.assertIn("停止本轮排查", titles)
                for widget in items + [self.panel.context_status, self.panel.context_status.status_label,
                                       self.panel.context_status.progress,
                                       self.panel.input, self.panel.output]:
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreater(widget.winfo_height(), 1)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         self.root.winfo_rooty() + self.root.winfo_height())
                self.service.collection_status.return_value = {
                    "enabled": False, "capable": True, "reason": "目标已变更，仅分析留存材料"}
                self.service.updates.get_nowait.side_effect = queue.Empty
                self.panel.poll()
                assert_no_status_banner()
                self.panel.sessions.current(self.panel.ids.index("s2"))
                self.panel.choose()
                self.assertEqual(self.panel.selected, "s2")
                assert_no_status_banner()
                self.store.chats.return_value = []
                self.panel.refresh()
                self.assertEqual(self.panel.selected, "")
                assert_no_status_banner()
                self.assertEqual(self.panel.context_status.status_text.get(),
                                 "上下文容量：选择会话后显示 ｜ 待下一次请求更新")
                self.service.send.assert_not_called()

    def test_metadata_time_format_and_body_storage_remain_exact(self):
        original = "设备返回：\n  第一行\n\n路径 C:\\logs\\dut.log\n原文时间 " + self.time
        self.add("assistant", original)
        before = copy.deepcopy((self.messages, self.session, self.items))
        text = self.rendered()
        self.assertTrue(text.startswith("AI · 2026-11-11 23:38:41\n"))
        self.assertIn(original, text)
        self.assertTrue(self.panel.sessions["values"][0].startswith("2026-11-11 23:38:41 |"))
        self.panel.evidence()
        window = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        def texts(widget):
            return ([widget] if isinstance(widget, tk.Text) else []) + [t for c in widget.winfo_children() for t in texts(c)]
        evidence_text = texts(window)[0].get("1.0", "end-1c")
        self.assertIn("[evidence1] 2026-11-11 23:38:41 |", evidence_text)
        self.assertIn(self.items[0]["text"], evidence_text)
        self.assertEqual((self.messages, self.session, self.items), before)
        self.store.update_chat.assert_not_called()
        self.store.append_chat.assert_not_called()

    def test_semantic_colors_fonts_and_selection_priority(self):
        for role, kind, style in (("user", "text", "user"), ("assistant", "text", "assistant"),
                                  ("system", "progress", "system"), ("assistant", "question", "question"),
                                  ("system", "error", "error")):
            self.add(role, "内容：" + style, kind)
        self.rendered()
        for style in ("user", "assistant", "system", "question", "error"):
            self.assertTrue(self.panel.output.tag_ranges("message_" + style))
            self.assertTrue(self.panel.output.tag_ranges("header_" + style))
            self.assertTrue(self.panel.output.tag_ranges("body_" + style))
        for style, color in (("user", "#1d4ed8"), ("assistant", "#0f766e"),
                             ("question", "#a16207"), ("error", "#b42318")):
            self.assertEqual(self.panel.output.tag_cget("header_" + style, "foreground"), color)
        self.assertIn("11", self.panel.output.tag_cget("body_assistant", "font"))
        self.assertIn("10", self.panel.output.tag_cget("body_system", "font"))
        self.assertIn("9", self.panel.output.tag_cget("message_time", "font"))
        self.assertEqual(self.panel.output.tag_names()[-1], "sel")
        self.assertEqual(str(self.panel.output.cget("state")), "disabled")

    def test_normal_ai_text_is_not_colored_as_error_based_on_words(self):
        self.add("assistant", "本次失败仅为假设，仍需要证据。")
        self.rendered()
        self.assertTrue(self.panel.output.tag_ranges("body_assistant"))
        self.assertFalse(self.panel.output.tag_ranges("body_error"))

    def test_only_system_capacity_messages_are_hidden_and_storage_is_unchanged(self):
        self.add("system", "上下文容量：1048576 Token，来源=缓存", "context")
        self.add("assistant", "上下文容量：这段是AI正文", "context")
        self.add("user", "上下文容量：这段是用户问题")
        self.add("system", "本次请求省略较早3轮原文", "context")
        self.add("system", "上下文预算不足", "error")
        before = copy.deepcopy(self.messages)
        text = self.rendered()
        self.assertNotIn("来源=缓存", text)
        self.assertIn("这段是AI正文", text)
        self.assertIn("这段是用户问题", text)
        self.assertIn("省略较早3轮", text)
        self.assertIn("上下文预算不足", text)
        self.assertEqual(self.messages, before)
        self.store.update_chat.assert_not_called()

    def test_usage_only_refresh_does_not_rewrite_body_or_follow_unsent_input(self):
        for i in range(35):
            self.add("assistant", f"记录{i}\n" + "日志原文 " * 35)
        self.rendered()
        self.panel.output.yview_moveto(.25)
        self.panel.output.tag_add("sel", "2.0", "2.6")
        self.root.update_idletasks()
        top = self.panel.output.index("@0,0")
        selected = self.panel.output.get("sel.first", "sel.last")
        self.service.context_status.return_value["snapshot"] = {
            "state": "completed", "basis": "reply", "source": "api",
            "input_tokens": 200, "output_tokens": 10, "total_tokens": 210}
        with patch.object(self.panel.output, "delete", wraps=self.panel.output.delete) as delete:
            self.panel.render()
            self.root.update_idletasks()
            delete.assert_not_called()
            self.panel.input.insert("1.0", "尚未发送的长草稿" * 100)
            self.panel.render()
            delete.assert_not_called()
        self.assertIn("当前上下文用量：210", self.panel.context_status.status_text.get())
        self.assertEqual(self.panel.output.index("@0,0"), top)
        self.assertEqual(self.panel.output.get("sel.first", "sel.last"), selected)
        self.service.send.assert_not_called()

    def test_new_messages_preserve_reading_anchor_and_selected_body(self):
        for i in range(35):
            self.add("assistant", f"节点{i}\n" + "长篇分析与日志原文 " * 35)
        self.rendered()
        self.panel.output.yview_moveto(0.25)
        self.root.update_idletasks()
        top = self.panel.output.index("@0,0")
        self.panel.output.tag_add("sel", "2.0", "2.8")
        selected = self.panel.output.get("sel.first", "sel.last")
        self.add("system", "新采集结果", "progress")
        self.rendered()
        self.assertEqual(self.panel.output.index("@0,0"), top)
        self.assertEqual(self.panel.output.get("sel.first", "sel.last"), selected)
        self.assertLess(self.panel.output.yview()[1], 0.98)

    def test_bottom_follows_and_waiting_question_remains_answerable(self):
        for i in range(20):
            self.add("assistant", f"分析{i}\n" + "日志细节 " * 40)
        self.rendered()
        self.panel.output.see("end")
        self.root.update_idletasks()
        self.add("assistant", "请确认LOS灯状态。", "question")
        self.session["status"] = "等待你回复"
        self.service.running["s1"] = threading.Event()
        self.rendered()
        self.assertGreaterEqual(self.panel.output.yview()[1], 0.98)
        self.assertIn("请确认LOS灯状态。", self.panel.output.get("1.0", "end-1c"))
        self.assertIn("disabled", self.panel.send_button.state())
        self.service.running.clear()
        self.rendered()
        self.assertNotIn("disabled", self.panel.send_button.state())
        self.assertTrue(self.panel.output.tag_ranges("body_question"))

    def test_switching_history_does_not_keep_other_session_selection(self):
        self.add("user", "第一会话正文")
        self.rendered()
        self.panel.output.tag_add("sel", "2.0", "2.5")
        self.panel.selected = "s2"
        self.messages[:] = [{"role": "assistant", "text": "第二会话内容", "kind": "text", "created": "未知时间"}]
        text = self.rendered()
        self.assertFalse(self.panel.output.tag_ranges("sel"))
        self.assertIn("AI · 未知时间", text)
        self.assertNotIn("第一会话正文", text)


if __name__ == "__main__":
    unittest.main()

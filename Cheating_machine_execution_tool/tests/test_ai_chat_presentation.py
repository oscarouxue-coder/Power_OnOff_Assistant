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
from src.models.ai_diagnostics import ProviderProfile


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
        self.service = Mock(store=self.store, lock=threading.RLock(), running={}, executors={})
        self.service.permissions.status.return_value = {"mode": "auto_review"}
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
        self.root.update()
        return self.panel.output.get("1.0", "end-1c")

    def press_input_key(self, sequence):
        self.session["profile"].setdefault("id", "keyboard-fixture")
        self.owner.service.profile = ProviderProfile(**self.session["profile"])
        self.root.update()
        self.panel.input.focus_force()
        self.root.update()
        self.panel.input.event_generate(sequence)
        self.root.update()

    def test_enter_sends_once_and_does_not_insert_newline(self):
        labels = [str(widget.cget("text")) for widget in self.panel.input.master.winfo_children()
                  if isinstance(widget, ttk.Label)]
        self.assertNotIn("Enter发送，Alt+Enter换行", labels)
        self.panel.input.insert("1.0", "检查当前连接")
        self.press_input_key("<Return>")
        self.service.send.assert_called_once_with("s1", "检查当前连接")
        self.service.answer_question.assert_not_called()
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")

    def test_composer_buttons_share_one_row_without_static_hints_in_both_themes(self):
        approval = self.panel.action_approval
        row = self.panel.send_button.master
        composer = self.panel.input.master
        buttons = [widget for widget in row.winfo_children() if isinstance(widget, ttk.Button)]
        buttons.append(approval.button)
        self.assertEqual([button.cget("text") for button in buttons],
                         ["发送 / 回答问题", "停止本轮排查", "导入文本日志", "查看证据", "查看待确认操作"])
        self.assertIs(approval.master, row)
        self.assertEqual(composer.pack_slaves(), [self.panel.input, row])
        self.assertEqual(approval.winfo_children(), [approval.button])
        self.assertEqual(row.pack_slaves(), buttons[:-1] + [approval, self.panel.permission_control])
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                self.root.geometry("940x660")
                self.service.actions.pending.return_value = None
                approval.show("s1")
                self.root.update()
                choice = self.panel.permission_control.choice
                self.assertEqual(choice.get(), "帮我批准")
                self.assertTrue(choice.winfo_viewable())
                self.assertGreaterEqual(choice.winfo_rootx(), approval.button.winfo_rootx() + approval.button.winfo_width())
                self.assertLessEqual(choice.winfo_rootx() + choice.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                self.assertIn("disabled", approval.button.state())
                for index, button in enumerate(buttons):
                    self.assertTrue(button.winfo_viewable())
                    self.assertAlmostEqual(button.winfo_rooty() + button.winfo_height() / 2,
                                           buttons[0].winfo_rooty() + buttons[0].winfo_height() / 2,
                                           delta=1)
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                         self.root.winfo_rooty() + self.root.winfo_height())
                    if index:
                        self.assertGreaterEqual(button.winfo_rootx(),
                                                buttons[index - 1].winfo_rootx() + buttons[index - 1].winfo_width())
                self.service.actions.pending.return_value = {"id": "fixture-action"}
                approval.show("s1")
                self.assertNotIn("disabled", approval.button.state())
                approval.show("")
                self.assertIn("disabled", approval.button.state())

    def test_alt_enter_inserts_one_newline_at_cursor_without_sending(self):
        self.panel.input.insert("1.0", "第一行第二行")
        self.panel.input.mark_set("insert", "1.3")
        self.press_input_key("<Alt-Return>")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "第一行\n第二行")
        self.assertEqual(self.panel.input.index("insert"), "2.0")
        self.service.send.assert_not_called()
        self.service.answer_question.assert_not_called()
        self.owner.refresh_targets.assert_not_called()

    def test_alt_enter_replaces_selection_with_one_newline(self):
        self.panel.input.insert("1.0", "保留选中内容末尾")
        self.panel.input.tag_add("sel", "1.2", "1.6")
        self.panel.input.mark_set("insert", "end-1c")
        self.press_input_key("<Alt-Return>")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "保留\n末尾")
        self.assertEqual(self.panel.input.index("insert"), "2.0")
        self.assertFalse(self.panel.input.tag_ranges("sel"))
        self.service.send.assert_not_called()
        self.service.answer_question.assert_not_called()

    def test_enter_sends_complete_multiline_message(self):
        self.panel.input.insert("1.0", "第一行第二行\n\n  保留缩进\n")
        self.panel.input.mark_set("insert", "1.3")
        self.press_input_key("<Alt-Return>")
        self.press_input_key("<Return>")
        self.service.send.assert_called_once_with("s1", "第一行\n第二行\n\n  保留缩进\n")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")

    def test_enter_send_failure_preserves_draft_without_extra_newline(self):
        original = "待重试的问题\n补充现象"
        self.panel.input.insert("1.0", original)
        failure = ValueError("本轮正在执行，请稍后重试")
        self.service.send.side_effect = failure
        self.press_input_key("<Return>")
        self.service.send.assert_called_once_with("s1", original)
        self.owner._error.assert_called_once_with(failure)
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), original)

    def test_enter_answers_pending_question_once(self):
        self.session["pending"] = {"id": "question1"}
        self.panel.input.insert("1.0", "LOS灯未亮")
        self.press_input_key("<Return>")
        self.service.answer_question.assert_called_once_with("s1", "LOS灯未亮")
        self.service.send.assert_not_called()
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")

    def test_control_enter_and_send_button_remain_compatible(self):
        self.panel.input.insert("1.0", "旧快捷键")
        self.press_input_key("<Control-Return>")
        self.service.send.assert_called_once_with("s1", "旧快捷键")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")
        self.service.send.reset_mock()
        self.panel.input.insert("1.0", "点击发送")
        self.panel.send_button.invoke()
        self.service.send.assert_called_once_with("s1", "点击发送")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")

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
                                       self.panel.status_output,
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
        for style in ("user", "assistant", "question"):
            self.assertTrue(self.panel.output.tag_ranges("message_" + style))
            self.assertTrue(self.panel.output.tag_ranges("header_" + style))
            self.assertTrue(self.panel.output.tag_ranges("body_" + style))
        for style in ("system", "error"):
            self.assertFalse(self.panel.output.tag_ranges("message_" + style))
        self.assertEqual(self.panel.status_output.cget("foreground"), "#b42318")
        self.assertIn("内容：error", self.panel.status_output.get("1.0", "end-1c"))
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

    def test_markdown_only_formats_ai_and_questions_without_writing_history(self):
        source = "## 修改结果\n- **项目**：`NP7287XGS`\n```ini\n  name = NP7287XGS\n```"
        self.add("user", source)
        self.add("assistant", source)
        self.add("assistant", "**请确认** `LOS` 状态", "question")
        self.add("assistant", "**错误**：`连接失败`", "error")
        before = copy.deepcopy(self.messages)
        text = self.rendered()
        self.assertEqual(text.count(source), 1)
        self.assertIn("修改结果\n• 项目：NP7287XGS\n  name = NP7287XGS", text)
        self.assertIn("请确认 LOS 状态", text)
        self.assertTrue(self.panel.output.tag_ranges("body_question"))
        self.assertTrue(self.panel.output.tag_ranges("body_error"))
        self.assertEqual(self.messages, before)
        self.store.append_chat.assert_not_called()
        self.store.update_chat.assert_not_called()
        self.panel.revision = None
        self.assertEqual(self.rendered(), text)

    def test_new_ai_markdown_message_preserves_history_selection_anchor_and_draft(self):
        for number in range(30):
            self.add("assistant", f"## 记录{number}\n- **路径** `C:/配置/test.ini`\n" + "诊断内容 " * 50)
        self.rendered()
        self.panel.output.yview_moveto(.25)
        self.panel.output.tag_add("sel", "3.0", "3.8")
        self.panel.input.insert("1.0", "保留草稿")
        self.root.update_idletasks()
        top = self.panel.output.index("@0,0")
        selected = self.panel.output.get("sel.first", "sel.last")
        self.add("assistant", "## 最新结果\n- **完成** `查询`")
        self.rendered()
        self.assertEqual(self.panel.output.index("@0,0"), top)
        self.assertEqual(self.panel.output.get("sel.first", "sel.last"), selected)
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "保留草稿")

    def test_system_messages_move_to_status_and_capacity_stays_hidden_without_storage_changes(self):
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
        self.assertNotIn("省略较早3轮", text)
        self.assertNotIn("上下文预算不足", text)
        self.assertEqual(self.panel.session_status.full_text,
                         "状态 · 2026-11-11 23:38:41\n上下文预算不足")
        self.add("system", "上下文容量：另一条旧容量提示", "context")
        self.rendered()
        self.assertNotIn("另一条旧容量提示", self.panel.status_output.get("1.0", "end-1c"))
        self.messages.pop()
        self.assertEqual(self.messages, before)
        self.store.update_chat.assert_not_called()
        self.store.append_chat.assert_not_called()

    def test_latest_system_status_replaces_each_category_and_ai_questions_stay_in_body(self):
        self.add("user", "开始排障")
        self.add("assistant", "请确认LOS灯状态。", "question")
        for kind, text in (("text", "会话已创建；发送问题后按需采集。"),
                           ("progress", "正在采集：read_dut_state"),
                           ("recovery", "本轮恢复状态：恢复待完成"),
                           ("recovery", "固定采集：无临时修改；本轮通用操作的实际变更不自动回滚"),
                           ("text", "已导入文本材料：fixture.log"),
                           ("context", "本次请求省略较早3轮原文"),
                           ("error", "请求失败：测试错误"),
                           ("recovery", "本轮恢复状态：已恢复，临时文件已清理")):
            with self.subTest(kind=kind, text=text):
                self.add("system", text, kind)
                before = copy.deepcopy(self.messages)
                body = self.rendered()
                self.assertIn("开始排障", body)
                self.assertIn("请确认LOS灯状态。", body)
                self.assertTrue(self.panel.output.tag_ranges("body_question"))
                self.assertNotIn(text, body)
                self.assertEqual(self.panel.session_status.full_text,
                                 "状态 · 2026-11-11 23:38:41\n" + text)
                self.assertEqual(self.panel.status_output.cget("foreground"),
                                 "#b42318" if kind == "error" else "#174b80")
                self.assertEqual(self.messages, before)

    def test_status_only_updates_preserve_body_draft_selection_and_running_button(self):
        for i in range(35):
            self.add("assistant", f"记录{i}\n" + "日志原文 " * 35)
        self.rendered()
        self.panel.output.yview_moveto(.25)
        self.panel.output.tag_add("sel", "2.0", "2.6")
        self.panel.input.insert("1.0", "尚未发送的草稿")
        self.root.update_idletasks()
        top = self.panel.output.index("@0,0")
        selected = self.panel.output.get("sel.first", "sel.last")
        with patch.object(self.panel.output, "delete", wraps=self.panel.output.delete) as delete:
            self.add("system", "正在采集：read_dut_state", "progress")
            self.session["status"] = "排查中"
            self.service.running["s1"] = threading.Event()
            self.service.collection_status.return_value["reason"] = "目标已变更，仅分析材料"
            self.rendered()
            self.assertIn("disabled", self.panel.send_button.state())
            self.add("system", "本轮恢复状态：无临时修改", "recovery")
            self.service.running.clear()
            self.session["status"] = "可继续"
            self.rendered()
            self.assertNotIn("disabled", self.panel.send_button.state())
            delete.assert_not_called()
        self.assertEqual(self.panel.output.index("@0,0"), top)
        self.assertEqual(self.panel.output.get("sel.first", "sel.last"), selected)
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "尚未发送的草稿")
        self.service.send.assert_not_called()

    def test_status_switch_reopen_empty_and_legacy_records(self):
        self.add("system", "第一会话恢复待完成", "recovery")
        self.messages[0].pop("kind")  # 旧记录缺少kind仍能显示。
        self.messages[0]["created"] = "历史时间未知"
        self.rendered()
        original = self.panel.session_status.full_text
        self.assertEqual(original, "状态 · 历史时间未知\n第一会话恢复待完成")
        second = [{"role": "system", "kind": "progress", "text": "第二会话采集中", "created": self.time}]
        self.store.chat_items.side_effect = {"s1": self.messages, "s2": second, "s3": []}.__getitem__
        self.panel.selected = "s2"
        self.rendered()
        self.assertIn("第二会话采集中", self.panel.status_output.get("1.0", "end-1c"))
        self.panel.selected = "s3"
        self.rendered()
        self.assertEqual(self.panel.status_output.get("1.0", "end-1c"), "状态 ｜ 暂无状态")
        self.panel.selected = ""
        self.rendered()
        self.assertEqual(self.panel.status_output.get("1.0", "end-1c"), "状态 ｜ 请选择会话")
        frame = ttk.Frame(self.root)
        reopened = AiChatPanel(frame, self.owner, self.service)
        self.assertEqual(reopened.selected, "s1")
        self.assertEqual(reopened.session_status.full_text, original)
        frame.destroy()
        self.store.append_chat.assert_not_called()
        self.store.update_chat.assert_not_called()

    def test_status_single_line_emphasis_ellipsis_and_minimum_layout_in_both_themes(self):
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                self.root.geometry("940x660")
                self.add("system", "短状态", "progress")
                self.rendered()
                self.root.update()
                status = self.panel.status_output
                short_height = status.winfo_height()
                self.assertIn("状态 · 23:38:41 ｜ 短状态", status.get("1.0", "end-1c"))
                self.assertNotIn("2026-11-11", status.get("1.0", "end-1c"))
                self.assertEqual(status.cget("highlightthickness"), 0)
                self.assertEqual(status.cget("borderwidth"), 0)
                self.assertEqual(self.panel.session_status.body_font.actual("size"), 11)
                self.assertEqual(self.panel.session_status.body_font.actual("weight"), "bold")
                self.assertEqual(self.panel.session_status.time_font.actual("size"), 9)
                self.add("system", "\n".join("长状态原文 " * 15 for _ in range(30)), "error")
                self.rendered()
                self.root.update()
                self.assertEqual(status.winfo_height(), short_height)
                self.assertEqual(status.cget("height"), 1)
                self.assertEqual(status.cget("wrap"), "none")
                self.assertEqual(str(status.cget("state")), "disabled")
                self.assertEqual(status.cget("background"), "#eef2f5")
                self.assertEqual(status.cget("highlightthickness"), 0)
                displayed = status.get("1.0", "end-1c")
                self.assertNotIn("\n", displayed)
                self.assertTrue(displayed.endswith("…"))
                self.assertFalse(any(isinstance(w, ttk.Scrollbar) for w in status.master.winfo_children()))
                status.tag_add("sel", "1.0", "1.2")
                self.assertEqual(status.get("sel.first", "sel.last"), "状态")
                with patch.object(status, "delete", wraps=status.delete) as delete:
                    self.rendered()
                    delete.assert_not_called()
                self.assertEqual(status.get("sel.first", "sel.last"), "状态")
                row = status.master.master
                new_button = next(w for w in row.winfo_children()
                                  if isinstance(w, ttk.Button) and w.cget("text") == "新会话")
                self.assertGreaterEqual(status.winfo_rootx(), new_button.winfo_rootx() + new_button.winfo_width())
                controls_height = max(w.winfo_reqheight() for w in row.winfo_children()
                                      if w is not status.master)
                self.assertLessEqual(status.master.winfo_height(), controls_height)
                self.assertEqual(row.winfo_height(), controls_height)
                self.assertGreater(status.winfo_width(), 100)
                for widget in (status, self.panel.input, self.panel.send_button, self.panel.context_status,
                               self.panel.output):
                    self.assertTrue(widget.winfo_viewable())
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         self.root.winfo_rooty() + self.root.winfo_height())

    def test_status_resize_recomputes_ellipsis_and_keeps_full_original(self):
        self.add("system", "逐字核对原始状态中文ABCDE" * 25, "recovery")
        self.rendered()
        self.root.update()
        component = self.panel.session_status
        original = component.full_text
        wide = self.panel.status_output.get("1.0", "end-1c")
        self.root.geometry("700x660")
        self.root.update()
        narrow = self.panel.status_output.get("1.0", "end-1c")
        self.assertLess(len(narrow), len(wide))
        self.assertTrue(narrow.endswith("…"))
        self.assertEqual(component.full_text, original)
        self.root.geometry("1040x760")
        self.root.update()
        self.assertEqual(self.panel.status_output.get("1.0", "end-1c"), wide)

    def test_status_hover_does_not_open_popup_schedule_jobs_or_change_focus(self):
        original = "original status " * 100
        self.add("system", original, "error")
        self.rendered()
        component = self.panel.session_status
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                # Let native window activation settle before checking hover focus.
                self.root.after(100, self.root.quit)
                self.root.mainloop()
                self.panel.input.focus_force()
                self.root.update()
                before_focus = self.root.focus_get()
                self.assertIs(before_focus, self.panel.input)
                before_children = component.winfo_children()
                before_text = self.panel.status_output.get("1.0", "end-1c")
                self.assertEqual(self.panel.status_output.bind("<Enter>"), "")
                self.assertEqual(self.panel.status_output.bind("<Leave>"), "")
                with patch("src.ui.ai_chat_status.tk.Toplevel", wraps=tk.Toplevel) as popup, \
                        patch.object(component, "after", wraps=component.after) as after:
                    self.panel.status_output.event_generate("<Enter>")
                    self.root.after(450, self.root.quit)
                    self.root.mainloop()
                    self.panel.status_output.event_generate("<Leave>")
                    self.root.update()
                    popup.assert_not_called()
                    after.assert_not_called()
                self.assertEqual(component.winfo_children(), before_children)
                self.assertEqual(self.root.focus_get(), before_focus)
                self.assertEqual(self.panel.status_output.get("1.0", "end-1c"), before_text)
                self.assertEqual(self.messages[-1]["text"], original)

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

"""对话排障页：收集输入、显示持久化会话及service异步进度。"""
from dataclasses import asdict
from datetime import datetime
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.services.ai_store import profile_fingerprint
from src.models.ai_diagnostics import ProviderProfile
from src.ui.module_theme import apply_module_theme
from src.ui.ai_context_status import AiContextStatus


CHAT_FONT = "Microsoft YaHei UI"
# 标题色、消息底色、正文色；仅作用于对话记录，不改全局主题。
MESSAGE_COLORS = {
    "user": ("#1d4ed8", "#eff6ff", "#17202a"),
    "assistant": ("#0f766e", "#edf8f5", "#17202a"),
    "system": ("#65717f", "#f3f5f7", "#65717f"),
    "question": ("#a16207", "#f8f0dd", "#17202a"),
    "error": ("#b42318", "#fbe9e7", "#b42318"),
}


def format_chat_time(value):
    """仅格式化界面时间；保留原时钟值，不转换时区或改写存储。"""
    if not isinstance(value, str):
        return str(value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


class AiChatPanel:
    def __init__(self, parent, owner, service):
        self.parent, self.owner, self.service = parent, owner, service
        self.selected = ""
        self.revision = None
        self.ids = []
        self.targets = ()
        self.session_manager = None
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="排障会话").pack(side="left")
        self.sessions = ttk.Combobox(row, state="readonly", width=65)
        self.sessions.pack(side="left", fill="x", expand=True, padx=6)
        self.sessions.bind("<<ComboboxSelected>>", self.choose)
        ttk.Button(row, text="刷新", command=self.refresh).pack(side="left")
        ttk.Button(row, text="管理会话", command=self.manage_sessions).pack(side="left", padx=(6, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="目标").pack(side="left")
        self.target_choice = ttk.Combobox(row, state="readonly", width=24)
        self.target_choice.pack(side="left", padx=6)
        for title, action in (("新会话", self.new), ("从当前报告新建", self.from_report)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=3)
        self.status = tk.StringVar(parent, value="选择目标并新建会话；有效会话默认允许主动采集。")
        ttk.Label(parent, textvariable=self.status, wraplength=960).pack(fill="x", pady=5)
        self.context_status = AiContextStatus(parent)
        self.context_status.pack(fill="x", pady=(0, 5))
        # 先预留底部输入/操作区，最小窗口下由聊天正文承担高度收缩。
        composer = ttk.Frame(parent)
        composer.pack(side="bottom", fill="x")
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.output = tk.Text(body, state="disabled", wrap="word", height=16,
                              font=(CHAT_FONT, 11), background="#ffffff", foreground="#17202a",
                              padx=8, pady=8, selectbackground="#cbdff5", selectforeground="#17202a")
        self._configure_message_tags()
        self.output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)
        self.input = tk.Text(composer, height=4, wrap="word", font=(CHAT_FONT, 11), padx=8, pady=6)
        self.input.pack(fill="x", pady=6)
        self.input.bind("<Control-Return>", lambda event: self.send())
        row = ttk.Frame(composer)
        row.pack(fill="x")
        self.send_button = ttk.Button(row, text="发送 / 回答问题", command=self.send)
        self.send_button.pack(side="left")
        for title, action in (("停止本轮排查", self.stop), ("导入文本日志", self.import_text), ("查看证据", self.evidence)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=5)
        ttk.Label(composer, text="Ctrl+Enter发送。保持现有挂测规则；你决定何时停测。AI无法确认的现场会主动询问，未答不推测。",
                  wraplength=960).pack(anchor="w", pady=5)
        self.refresh()

    def _configure_message_tags(self):
        for kind, (heading, background, foreground) in MESSAGE_COLORS.items():
            size = 10 if kind == "system" else 11
            self.output.tag_configure("message_" + kind, background=background,
                                      lmargin1=12, lmargin2=12, rmargin=12)
            self.output.tag_configure("header_" + kind, foreground=heading,
                                      font=(CHAT_FONT, size, "bold"), spacing1=8)
            self.output.tag_configure("body_" + kind, foreground=foreground,
                                      font=(CHAT_FONT, size), spacing1=3, spacing2=3, spacing3=5)
        self.output.tag_configure("message_time", foreground="#65717f", font=(CHAT_FONT, 9))
        self.output.tag_configure("message_gap", font=(CHAT_FONT, 4), spacing3=6)
        self.output.tag_raise("sel")

    def error(self, exc):
        self.owner._error(exc)

    def refresh_targets(self):
        number = self.targets[self.target_choice.current()].channel if 0 <= self.target_choice.current() < len(self.targets) else None
        self.targets = tuple(self.owner.targets)
        self.target_choice["values"] = [f"通道{t.channel} | {t.vlan} | {t.port}" for t in self.targets]
        if number is not None:
            index = next((i for i, t in enumerate(self.targets) if t.channel == number), -1)
        elif self.selected:
            snapshot = self.service.store.chat(self.selected)["target"]
            index = next((i for i, t in enumerate(self.targets) if asdict(t) == snapshot), -1)
        else:
            index = 0 if self.targets else -1
        if index >= 0:
            self.target_choice.current(index)
        else:
            self.target_choice.set("历史目标（仅分析留存材料）")

    def refresh(self):
        rows = self.service.store.chats()
        self.ids = [row["id"] for row in rows]
        if self.selected and self.selected not in self.ids:
            self.selected = ""
            self.revision = None
            self.input.delete("1.0", "end")
        self.sessions["values"] = [f"{format_chat_time(r['created'])} | {r['title']} | {r['profile']['model']} | {r['status']}" for r in rows]
        if self.selected in self.ids:
            self.sessions.current(self.ids.index(self.selected))
        elif self.ids:
            self.sessions.current(0)
            self.choose()
            return
        else:
            self.sessions.set("")
        self.render()

    def manage_sessions(self):
        if self.session_manager is not None and self.session_manager.window.winfo_exists():
            self.session_manager.window.deiconify()
            self.session_manager.window.lift()
            self.session_manager.refresh()
            return
        from src.ui.ai_session_manager import AiSessionManager
        self.session_manager = AiSessionManager(self.owner.window, self.service, self.selected,
                                               self.refresh, self.owner.background_color)

    def choose(self, event=None):
        if 0 <= self.sessions.current() < len(self.ids):
            self.selected = self.ids[self.sessions.current()]
            session = self.service.store.chat(self.selected)
            index = next((i for i, t in enumerate(self.targets) if asdict(t) == session["target"]), -1)
            if index >= 0:
                self.target_choice.current(index)
            else:
                self.target_choice.set("历史目标（仅分析留存材料）")
            self.revision = None
            self.render()

    def new(self, report=None):
        try:
            number = self.targets[self.target_choice.current()].channel if 0 <= self.target_choice.current() < len(self.targets) else None
            self.owner.refresh_targets()
            index = next((i for i, t in enumerate(self.targets) if t.channel == number), -1)
            if index < 0:
                raise ValueError("请选择已配置目标；刷新后目标必须仍存在")
            self.target_choice.current(index)
            self.selected = self.service.create_session(self.targets[index], self.owner.service.profile, report=report)
            self.revision = None
            self.refresh()
            return self.selected
        except Exception as exc:
            self.error(exc)
            return None

    def from_report(self):
        report = self.owner.reports.get(self.owner.selected_report)
        if report is None:
            self.error(ValueError("请先在诊断与监控页选择历史报告"))
            return
        self.new(report)

    def send(self):
        try:
            if not self.selected and not self.new():
                return "break"
            self.owner.refresh_targets()
            session = self.service.store.chat(self.selected)
            current = self.owner.service.profile
            index = self.target_choice.current()
            if (not current or profile_fingerprint(current) != profile_fingerprint(
                    ProviderProfile(**session["profile"]))
                    or (0 <= index < len(self.targets) and asdict(self.targets[index]) != session["target"])):
                if not self.new():
                    return "break"
            text = self.input.get("1.0", "end-1c")
            if self.service.store.chat(self.selected).get("pending"):
                self.service.answer_question(self.selected, text)
            else:
                self.service.send(self.selected, text)
            self.input.delete("1.0", "end")
            self.render()
        except Exception as exc:
            self.error(exc)
        return "break"

    def stop(self):
        if self.selected:
            self.service.stop(self.selected)

    def import_text(self):
        if not self.selected and not self.new():
            return
        path = filedialog.askopenfilename(parent=self.owner.window, title="导入排障文本材料",
                                         filetypes=[("文本日志", "*.txt *.log *.csv *.json *.md")])
        if path:
            try:
                self.service.import_text(self.selected, path)
                self.render()
            except Exception as exc:
                self.error(exc)

    def evidence(self):
        if not self.selected:
            return
        window = tk.Toplevel(self.owner.window)
        window.title("当前会话留存证据")
        window.geometry("920x620")
        from tkinter.scrolledtext import ScrolledText
        output = ScrolledText(window, wrap="word", font=(CHAT_FONT, 11), padx=12, pady=10)
        output.pack(fill="both", expand=True, padx=10, pady=10)
        for item in self.service.store.chat_evidence(self.selected):
            output.insert("end", f"[{item['id'][:12]}] {format_chat_time(item['created'])} | {item['timing']}\n{item['source']}\n{item['text']}\n\n")
        output.configure(state="disabled")
        apply_module_theme(window, self.owner.background_color)

    def render(self):
        if not self.selected:
            self.context_status.show()
            self.revision = None
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            self.output.configure(state="disabled")
            self.status.set("选择目标并新建会话；有效会话默认允许主动采集。")
            self.send_button.configure(state="normal")
            return
        session = self.service.store.chat(self.selected)
        # 用量单独刷新；不将快照加入正文revision，避免破坏阅读位置和选区。
        self.context_status.show(self.service.context_status(self.selected))
        messages = self.service.store.chat_items(self.selected)
        collection = self.service.collection_status(self.selected)
        with self.service.lock:
            running = self.selected in self.service.running
        revision = (self.selected, len(messages), session["status"], collection["reason"], running)
        if revision == self.revision:
            return
        same_session = self.revision is not None and self.revision[0] == self.selected
        self.revision = revision
        self.status.set(f"批次：{session['run_id']} | 通道{session['target']['channel']} | {session['profile']['provider']}/{session['profile']['model']} | "
                        f"{session['status']} | {collection['reason']}\n"
                        f"真实诊断信息（含材料中的账号、密码）将发送至{session['profile']['provider']} / "
                        f"{session['profile']['base_url']}；模型API密钥仅用于认证。")
        at_end = self.output.yview()[1] > 0.98
        top_index = self.output.index("@0,0")
        selection = tuple(str(index) for index in self.output.tag_ranges("sel")) if same_session else ()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        labels = {"user": "你", "assistant": "AI", "system": "状态"}
        for message in messages:
            role = message["role"]
            kind = message.get("kind", "text")
            if role == "system" and kind == "context" and message["text"].startswith("上下文容量："):
                continue
            style = kind if kind in ("question", "error") else (role if role in MESSAGE_COLORS else "system")
            start = self.output.index("end-1c")
            self.output.insert("end", f"{labels.get(role, role)} · ", ("header_" + style,))
            self.output.insert("end", format_chat_time(message["created"]) + "\n", ("message_time",))
            self.output.insert("end", message["text"] + "\n", ("body_" + style,))
            self.output.tag_add("message_" + style, start, "end-1c")
            self.output.insert("end", "\n", ("message_gap",))
        if len(selection) == 2:
            self.output.tag_add("sel", *selection)
        self.output.configure(state="disabled")
        if not same_session or at_end:
            self.output.see("end")
        else:
            self.output.yview(top_index)
        self.send_button.configure(state="disabled" if running else "normal")

    def poll(self):
        changed = False
        for _ in range(80):
            try:
                self.service.updates.get_nowait()
                changed = True
            except queue.Empty:
                break
        if changed:
            self.refresh()
            if self.session_manager is not None and self.session_manager.window.winfo_exists():
                self.session_manager.refresh()
        else:
            # 模型能力/目标可能在别页更新，无新消息时也刷新实时采集状态。
            self.render()

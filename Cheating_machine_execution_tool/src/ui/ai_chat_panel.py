"""对话排障页：收集输入、显示持久化会话及service异步进度。"""
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.ui.module_theme import apply_module_theme
from src.ui.ai_context_status import AiContextStatus
from src.ui.ai_action_approval import AiActionApproval
from src.ui.ai_permission_control import AiPermissionControl
from src.ui.ai_chat_status import AiChatStatus
from src.ui.ai_chat_markdown import configure_markdown_tags, insert_markdown
from src.services.ai_record_titles import AiRecordTitles
from src.ui.ai_record_presentation import AiRecordActions, record_labels
from src.models.ai_session_scope import target_label
from src.ui.ai_diagnostic_task_control import DiagnosticTaskControl


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
        self.route_results = queue.Queue()
        self.routing = False
        self.route_generation = 0
        self.active_route = None
        self.local_echoes = []
        self.record_titles = AiRecordTitles(service.store, service.emit)
        self.record_entries = {}
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="排障会话").pack(side="left")
        self.sessions = ttk.Combobox(row, state="readonly", width=65)
        self.sessions.pack(side="left", fill="x", expand=True, padx=6)
        self.sessions.bind("<<ComboboxSelected>>", self.choose)
        self.record_actions = AiRecordActions(self.sessions, "chat", self.record_titles,
            lambda: self.record_entries.get(self.selected), self.names_changed, self.owner.background_color)
        ttk.Button(row, text="刷新会话", command=self.refresh).pack(side="left")
        ttk.Button(row, text="管理会话", command=self.manage_sessions).pack(side="left", padx=(6, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        # 直接设置标签颜色，保留模块主题下当前目标的局部强调。
        self.current_target = ttk.Label(row, text="普通问答", font=(CHAT_FONT, 11, "bold"),
                                        background="#dbeafe", foreground="#174b80", padding=(8, 4))
        self.current_target.pack(side="left", padx=6)
        self.session_status = AiChatStatus(row, background=self.owner.background_color, font_family=CHAT_FONT)
        self.session_status.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.status_output = self.session_status.output
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
        self.input.bind("<Return>", lambda event: self.send())
        self.input.bind("<Alt-Return>", self._insert_newline)
        self.input.bind("<Control-Return>", lambda event: self.send())
        row = ttk.Frame(composer)
        row.pack(fill="x")
        self.send_button = ttk.Button(row, text="发送 / 回答问题", command=self.send)
        self.send_button.pack(side="left")
        self.task_control = DiagnosticTaskControl(self)
        for title, action in (("停止本轮排查", self.stop), ("导入文本日志", self.import_text)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=5)
        self.action_approval = AiActionApproval(row, self.service, self.owner.background_color)
        self.action_approval.pack(side="left", padx=5)
        self.permission_control = AiPermissionControl(row, self.service)
        self.permission_control.pack(side="left", padx=(3, 0))
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
        configure_markdown_tags(self.output, CHAT_FONT)
        self.output.tag_raise("sel")

    def error(self, exc):
        self.owner._error(exc)

    def refresh_targets(self):
        self.targets = tuple(self.owner.targets)

    def refresh(self):
        rows = [row for row in self.service.store.chats() if not row.get("batch_parent")]
        self.ids = [row["id"] for row in rows]
        removed = bool(self.selected and self.selected not in self.ids)
        if removed:
            self.selected = ""
            self.revision = None
            self.input.delete("1.0", "end")
        entries = self.record_titles.chat_entries(rows)
        self.record_entries = {entry["id"]: entry for entry in entries}
        self.record_actions.hide()
        self.sessions["values"] = record_labels(entries)
        if self.selected in self.ids:
            self.sessions.current(self.ids.index(self.selected))
        elif not self.routing and self.service.router.current() in self.ids:
            self.sessions.current(self.ids.index(self.service.router.current()))
            self.choose()
            return
        elif removed and self.ids:
            self.sessions.current(0)
            self.choose()
            return
        else:
            self.sessions.set("")
        self.render()

    def names_changed(self):
        self.refresh()
        if self.session_manager is not None and self.session_manager.window.winfo_exists():
            self.session_manager.refresh()

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
            self.route_generation += 1
            self.selected = self.ids[self.sessions.current()]
            self.service.router.select(self.selected)
            self.revision = None
            self.render()

    def new(self, report=None, target=None):
        """兼容调用入口；设备必须显式传入目标，界面不再默认选第一通道。"""
        if self.routing:
            self.service.emit("新会话已跳过：正在识别上一条消息，请稍后重试")
            return None
        try:
            if target is None and report is None:
                identifier = self.service.create_blank_session(self.owner.service.profile)
            else:
                self.owner.refresh_targets()
                if target is not None and target not in self.targets:
                    raise ValueError("目标已变化或未配置")
                identifier = self.service.create_session(target, self.owner.service.profile, report=report,
                    scope="device" if target else "general")
            self.service.router.select(identifier)
            self.route_generation += 1
            self.selected = identifier
            self.revision = None
            self.refresh()
            self.input.focus_set()
            return self.selected
        except Exception as exc:
            self.error(exc)
            return None

    def _insert_newline(self, event=None):
        selection = self.input.tag_ranges("sel")
        if selection:
            self.input.mark_set("insert", selection[0])
            self.input.delete(*selection)
        self.input.insert("insert", "\n")
        self.input.see("insert")
        return "break"

    def send(self):
        try:
            if self.routing:
                return "break"
            text = self.input.get("1.0", "end-1c")
            if not text.strip():
                raise ValueError("请输入问题或切换目标的要求")
            if len(text.strip()) > 32768:
                raise ValueError("请输入1至32768字符；较长日志请导入文本材料")
            profile = self.owner.service.profile
            if not profile or not profile.model.strip():
                raise ValueError("请先保存并选择模型配置")
            self.route_generation += 1
            generation = self.route_generation
            message = dict(role="user", kind="text", text=self.service.redactor.text(text),
                           created=datetime.now().astimezone().isoformat(), local_echo=generation)
            echo = dict(generation=generation, origin=self.selected, original=text,
                        message=message, binding=None, error=None, diagnosis_only=self.task_control.enabled)
            # 重试替换同一条失败回显；界面投影不提前写入未知目标的会话。
            replaced = [item for item in self.local_echoes
                        if item["origin"] == self.selected and item["original"] == text]
            self.local_echoes = [item for item in self.local_echoes if item not in replaced]
            self.local_echoes.append(echo)
            self.active_route = generation
            self.routing = True
            self.input.delete("1.0", "end")
            self.send_button.configure(state="disabled")
            # 只追加本条，避免发送回调查询数据库或重绘整段历史。
            self.output.configure(state="normal")
            for item in replaced:
                ranges = self.output.tag_ranges("local_echo_" + str(item["generation"]))
                for index in range(len(ranges) - 2, -1, -2):
                    self.output.delete(ranges[index], ranges[index + 1])
            self._insert_message(message)
            self.output.configure(state="disabled")
            self.output.see("end")
            # 先让Tk绘制回显，再在主线程收集目标、启动后台识别。
            self.parent.after_idle(lambda: self.parent.after(0, self._start_route, echo, profile))
        except Exception as exc:
            self.error(exc)
        return "break"

    def _start_route(self, echo, profile):
        generation = echo["generation"]
        try:
            if generation != self.route_generation:
                raise InterruptedError("本条发送已取消")
            self.owner.refresh_targets()

            def selected(identifier):
                # 此回调在后台运行；在用户消息入库前记录边界，不访问Tk。
                count = sum(m["role"] == "user" for m in self.service.store.chat_items(identifier))
                self.route_results.put((generation, "selected", (identifier, count), None))

            def run():
                try:
                    result = self.service.router.send(echo["original"], profile, selected=echo["origin"],
                        guard=lambda: generation == self.route_generation, on_selected=selected,
                        diagnosis_only=echo.get("diagnosis_only", False))
                    self.route_results.put((generation, "finished", result, None))
                except Exception as exc:
                    self.route_results.put((generation, "finished", None, exc))
            threading.Thread(target=run, name="ai-local-session-route", daemon=True).start()
        except Exception as exc:
            self.route_results.put((generation, "finished", None, exc))

    def _echo_messages(self, messages):
        projection = []
        for echo in self.local_echoes:
            if echo["origin"] != self.selected:
                continue
            binding = echo["binding"]
            persisted = echo.get("persisted", binding is not None and binding[0] == self.selected
                                 and sum(m["role"] == "user" for m in messages) > binding[1])
            if not persisted:
                projection.append(echo["message"])
            if echo["error"]:
                projection.append(dict(role="system", kind="error", text=echo["error"],
                                       created=echo["message"]["created"], local_echo=echo["generation"]))
        return projection

    def stop(self):
        self.route_generation += 1
        self.service.router.cancel_source()
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

    def _show_status(self, message=None):
        """仅投影当前会话的最新系统消息；不改原始记录或聊天正文。"""
        created = format_chat_time(message.get("created", "")) if message else ""
        self.session_status.show(self.selected, message, created)

    def render(self):
        self.current_target.configure(text=target_label(self.service.store.chat(self.selected)) if self.selected else "普通问答")
        self.action_approval.show(self.selected)
        self.permission_control.show(self.selected)
        if not self.selected:
            self.context_status.show()
            self._show_status()
            messages = []
        else:
            # 用量和系统状态独立刷新；不加入正文revision，避免破坏阅读位置和选区。
            self.context_status.show(self.service.context_status(self.selected))
            messages = self.service.store.chat_items(self.selected)
            latest_status = next((message for message in reversed(messages) if message["role"] == "system"
                                  and not (message.get("kind") == "context"
                                           and message["text"].startswith("上下文容量："))), None)
            self._show_status(latest_status)
        echoes = self._echo_messages(messages)
        messages = [message for message in messages if message["role"] != "system"] + echoes
        draft = self.service.draft_message(self.selected) if self.selected else None
        if isinstance(draft, dict) and isinstance(draft.get("text"), str) and draft["text"]:
            messages.append(draft)
        self.send_button.configure(state="disabled" if self.routing else "normal", text=self.task_control.label())
        revision = (self.selected, tuple((m["role"], m.get("kind", "text"), m["created"], m["text"])
                                         for m in messages))
        if revision == self.revision:
            return
        same_session = self.revision is not None and self.revision[0] == self.selected
        previous_revision = self.revision
        self.revision = revision
        at_end = self.output.yview()[1] > 0.98
        top_index = self.output.index("@0,0")
        selection = tuple(str(index) for index in self.output.tag_ranges("sel")) if same_session else ()
        self.output.configure(state="normal")
        tail = getattr(self, "_stream_tail", None)
        incremental = (same_session and tail and messages and messages[-1].get("reply_id") == tail[0]
                       and len(previous_revision[1]) == len(revision[1])
                       and previous_revision[1][:-1] == revision[1][:-1])
        if incremental:
            self.output.delete(tail[1], "end-1c")
            pending = messages[-1:]
        else:
            self.output.delete("1.0", "end")
            pending = messages
        self._stream_tail = None
        for message in pending:
            if message.get("reply_id") and message.get("kind") == "stream":
                self._stream_tail = (message["reply_id"], self.output.index("end-1c"))
            self._insert_message(message)
        if len(selection) == 2:
            self.output.tag_add("sel", *selection)
        self.output.configure(state="disabled")
        if not same_session or at_end:
            self.output.see("end")
        else:
            self.output.yview(top_index)

    def _insert_message(self, message):
        labels = {"user": "你", "assistant": "AI", "system": "状态"}
        role = message["role"]
        kind = message.get("kind", "text")
        style = kind if kind in ("question", "error") else (role if role in MESSAGE_COLORS else "system")
        start = self.output.index("end-1c")
        self.output.insert("end", f"{labels.get(role, role)} · ", ("header_" + style,))
        self.output.insert("end", format_chat_time(message["created"]) + "\n", ("message_time",))
        if role == "assistant":
            insert_markdown(self.output, message["text"], "body_" + style)
        else:
            self.output.insert("end", message["text"] + "\n", ("body_" + style,))
        self.output.tag_add("message_" + style, start, "end-1c")
        self.output.insert("end", "\n", ("message_gap",))
        if "local_echo" in message:
            self.output.tag_add("local_echo_" + str(message["local_echo"]), start, "end-1c")

    def poll(self):
        while True:
            try:
                generation, kind, result, error = self.route_results.get_nowait()
            except queue.Empty:
                break
            if generation != self.active_route:
                continue
            echo = next(item for item in self.local_echoes if item["generation"] == generation)
            if kind == "selected":
                echo["binding"] = result
                continue
            self.active_route = None
            self.routing = False
            if error is not None:
                # 固定失败时的入库结果；后续其它问题不能让失败原文误消失。
                binding = echo["binding"]
                try:
                    echo["persisted"] = bool(binding and sum(m["role"] == "user" for m in
                        self.service.store.chat_items(binding[0])) > binding[1])
                except ValueError:
                    echo["persisted"] = False
                echo["error"] = "发送未完成：" + self.service.redactor.text(str(error))
                if self.selected == echo["origin"] and not self.input.get("1.0", "end-1c"):
                    self.input.insert("1.0", echo["original"])
                if generation == self.route_generation and not isinstance(error, InterruptedError):
                    self.error(error)
            else:
                self.local_echoes.remove(echo)
                if generation == self.route_generation:
                    self.selected = result["identifier"]
            self.refresh()
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
            # 无新消息时也独立刷新上下文用量、系统状态和运行按钮。
            self.render()

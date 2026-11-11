"""对话排障页：收集输入、显示持久化会话及service异步进度。"""
from dataclasses import asdict
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.services.ai_store import profile_fingerprint
from src.models.ai_diagnostics import ProviderProfile
from src.ui.module_theme import apply_module_theme


class AiChatPanel:
    def __init__(self, parent, owner, service):
        self.parent, self.owner, self.service = parent, owner, service
        self.selected = ""
        self.revision = None
        self.ids = []
        self.targets = ()
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="排障会话").pack(side="left")
        self.sessions = ttk.Combobox(row, state="readonly", width=65)
        self.sessions.pack(side="left", fill="x", expand=True, padx=6)
        self.sessions.bind("<<ComboboxSelected>>", self.choose)
        ttk.Button(row, text="刷新", command=self.refresh).pack(side="left")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="目标").pack(side="left")
        self.target_choice = ttk.Combobox(row, state="readonly", width=24)
        self.target_choice.pack(side="left", padx=6)
        for title, action in (("新会话", self.new), ("授权本次会话", self.authorize),
                              ("结束授权", self.revoke), ("从当前报告新建", self.from_report)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=3)
        self.status = tk.StringVar(parent, value="选择目标并新建会话；主动采集需一次授权。")
        ttk.Label(parent, textvariable=self.status, wraplength=960).pack(fill="x", pady=5)
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.output = tk.Text(body, state="disabled", wrap="word", height=16)
        self.output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)
        self.input = tk.Text(parent, height=4, wrap="word")
        self.input.pack(fill="x", pady=6)
        self.input.bind("<Control-Return>", lambda event: self.send())
        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.send_button = ttk.Button(row, text="发送 / 回答问题", command=self.send)
        self.send_button.pack(side="left")
        for title, action in (("停止本轮排查", self.stop), ("导入文本日志", self.import_text), ("查看证据", self.evidence)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=5)
        ttk.Label(parent, text="Ctrl+Enter发送。保持现有挂测规则；你决定何时停测。AI无法确认的现场会主动询问，未答不推测。",
                  wraplength=960).pack(anchor="w", pady=5)
        self.refresh()

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
        self.sessions["values"] = [f"{r['created']} | {r['title']} | {r['profile']['model']} | {r['status']}" for r in rows]
        if self.selected in self.ids:
            self.sessions.current(self.ids.index(self.selected))
        elif self.ids:
            self.sessions.current(0)
            self.selected = self.ids[0]
        self.render()

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

    def authorize(self):
        try:
            if not self.selected and not self.new():
                return
            session = self.service.store.chat(self.selected)
            target, profile = session["target"], session["profile"]
            self.owner.refresh_targets()
            if not any(asdict(item) == target for item in self.targets):
                raise ValueError("历史目标已变更或不在当前目标中，仅可分析留存材料；请为当前目标新建会话")
            if self.service.authorized(self.selected):
                return
            if messagebox.askyesno("授权本次对话排障",
                    f"目标：通道{target['channel']} / {target['vlan']} / {target['host']} / {target['port']}\n"
                    f"接收方：{profile['provider']} / {profile['base_url']}\n\n"
                    "本次会话允许AI连续登录查询、限定出口Ping、抓包、日志跟踪及受控临时Debug，并在结束时恢复。\n"
                    "真实诊断信息（含材料中的账号、密码）将发送至上述服务；模型API密钥只用于认证。\n"
                    "不允许AI重启、上下电、升级、恢复出厂或配置修复；不抢占挂测资源。\n"
                    "授权在程序重启、新批次或结束授权后失效。是否授权？", parent=self.owner.window):
                self.service.authorize(self.selected)
                self.render()
        except Exception as exc:
            self.error(exc)

    def revoke(self):
        if self.selected:
            self.service.revoke(self.selected)
            self.render()

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
        output = ScrolledText(window, wrap="word")
        output.pack(fill="both", expand=True, padx=10, pady=10)
        for item in self.service.store.chat_evidence(self.selected):
            output.insert("end", f"[{item['id'][:12]}] {item['created']} | {item['timing']}\n{item['source']}\n{item['text']}\n\n")
        output.configure(state="disabled")
        apply_module_theme(window, self.owner.background_color)

    def render(self):
        if not self.selected:
            return
        session = self.service.store.chat(self.selected)
        messages = self.service.store.chat_items(self.selected)
        active = self.service.authorized(self.selected)
        with self.service.lock:
            running = self.selected in self.service.running
        revision = (self.selected, len(messages), session["status"], active, running)
        if revision == self.revision:
            return
        self.revision = revision
        self.status.set(f"批次：{session['run_id']} | 通道{session['target']['channel']} | {session['profile']['provider']}/{session['profile']['model']} | "
                        f"{session['status']} | {'已授权主动采集' if active else '仅分析已有材料'}")
        at_end = self.output.yview()[1] > 0.98
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        labels = {"user": "你", "assistant": "AI", "system": "状态"}
        for message in messages:
            self.output.insert("end", f"{labels.get(message['role'], message['role'])} · {message['created']}\n{message['text']}\n\n")
        self.output.configure(state="disabled")
        if at_end:
            self.output.see("end")
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

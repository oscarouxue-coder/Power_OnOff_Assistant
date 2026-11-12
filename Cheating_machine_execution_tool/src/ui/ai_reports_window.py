"""诊断报告查看与显式接手入口；刷新不抢选或触发模型请求。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent
from src.utils.ai_output import format_diagnostic_evidence


class AiReportsWindow:
    def __init__(self, owner):
        self.owner = owner
        self.window = None
        self.selected = ""
        self.reports = {}
        self.ids = []
        self.created = {}
        self.shown = None

    def open(self):
        self.ensure_window()
        self.reload()
        self.window.deiconify()
        self.window.lift()
        self.owner.report_status.set("")

    def ensure_window(self):
        if self.window is not None and self.window.winfo_exists():
            return
        self.window = tk.Toplevel(self.owner.window)
        self.window.withdraw()
        self.window.title("诊断报告")
        self.window.geometry("920x620")
        self.window.minsize(760, 480)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)
        parent = ttk.Frame(self.window, padding=12)
        parent.pack(fill="both", expand=True)
        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.choice = ttk.Combobox(row, state="readonly")
        self.choice.pack(side="left", fill="x", expand=True)
        self.choice.bind("<<ComboboxSelected>>", self.choose)
        ttk.Button(row, text="刷新报告", command=self.reload).pack(side="left", padx=(6, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=8)
        self.continue_button = ttk.Button(row, text="继续排查", command=self.continue_chat)
        self.continue_button.pack(side="left")
        self.case_button = ttk.Button(row, text="从此报告新建案例", command=self.new_case)
        self.case_button.pack(side="left", padx=6)
        self.legacy_target = ttk.Combobox(row, state="readonly", width=29)
        self.legacy_target.pack(side="left", padx=6)
        self.legacy_target.set("旧报告接手时请选择同通道当前目标")
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.output = tk.Text(body, wrap="word", state="disabled", height=12)
        self.output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)
        apply_module_theme(self.window, self.owner.background_color)
        center_toplevel_on_parent(self.window, self.owner.window)

    def reload(self):
        rows = self.owner.service.store.reports()
        # 最近100份之外的正在阅读报告仍留在列表，不被新报告挤走。
        if self.selected and self.selected not in {row[0] for row in rows}:
            try:
                payload = self.owner.service.store.report(self.selected)
                rows.append((self.selected, self.created.get(self.selected, ""), payload))
            except ValueError:
                pass
        self.created = {row[0]: row[1] for row in rows}
        self.ids = [row[0] for row in rows]
        self.reports = {row[0]: row[2] for row in rows}
        if self.window is None or not self.window.winfo_exists():
            return
        self.choice["values"] = [f"{created} | 通道{p.get('channel')} | {p.get('provider')} | {p.get('status')}"
                                 for _, created, p in rows]
        if self.selected not in self.reports:
            self.selected = self.ids[0] if self.ids else ""
        if self.selected:
            self.choice.current(self.ids.index(self.selected))
        else:
            self.choice.set("")
        self.render()

    def choose(self, _event=None):
        index = self.choice.current()
        if 0 <= index < len(self.ids):
            self.selected = self.ids[index]
            self.render()

    def render(self):
        payload = self.reports.get(self.selected)
        same = self.shown is not None and self.shown[0] == self.selected
        text = (str(payload.get("report", "")) + "\n\n本地证据：\n" +
                format_diagnostic_evidence(payload.get("evidence", ""))) if payload is not None else "暂无诊断报告。"
        state = (self.selected, text)
        if self.shown != state:
            top = self.output.index("@0,0")
            selection = tuple(str(i) for i in self.output.tag_ranges("sel")) if same else ()
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            self.output.insert("end", text)
            if len(selection) == 2:
                self.output.tag_add("sel", *selection)
            self.output.configure(state="disabled")
            self.output.yview(top if same else "1.0")
            self.shown = state
        self.continue_button.configure(state="normal" if payload and self.owner.chat_panel else "disabled")
        self.case_button.configure(state="normal" if payload else "disabled")
        old_target = self.legacy_target.get()
        self.legacy_targets = tuple(t for t in self.owner.targets if payload and t.channel == payload.get("channel"))
        values = [f"通道{t.channel} | {t.vlan} | {t.port} | {t.host}" for t in self.legacy_targets]
        self.legacy_target["values"] = values
        self.legacy_target.configure(state="readonly" if payload and not payload.get("target") else "disabled")
        if not same or old_target not in values:
            self.legacy_target.set("旧报告接手时请选择同通道当前目标")

    def continue_chat(self):
        try:
            self.owner.refresh_targets()
            payload = self.reports.get(self.selected)
            if payload is None:
                raise ValueError("请选择诊断报告")
            target, confirmed = None, False
            if not payload.get("target"):
                index = self.legacy_target.current()
                if not 0 <= index < len(self.legacy_targets):
                    raise ValueError("旧报告缺少目标快照，请明确选择同通道当前目标")
                target = self.legacy_targets[index]
                confirmed = messagebox.askyesno("关联旧报告材料", "旧报告没有完整目标快照，不能仅按通道号确认是同一设备。\n"
                    f"将报告作为历史材料关联至：通道{target.channel} / {target.vlan} / {target.port} / {target.host}？\n"
                    "保留原报告批次；本操作不会发起采集，后续发送按会话实时资格执行。",
                    parent=self.window, default="no")
                if not confirmed:
                    return
            self.owner.continue_report(self.selected, target, confirmed)
        except Exception as exc:
            self.owner._error(exc)

    def new_case(self):
        self.owner.case_from_report(self.selected)

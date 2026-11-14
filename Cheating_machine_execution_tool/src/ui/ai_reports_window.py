"""诊断报告查看与显式接手入口；刷新不抢选或触发模型请求。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.module_theme import apply_module_theme
from src.ui.ai_report_manager import AiReportManager
from src.ui.ai_report_target_dialog import AiReportTargetDialog
from src.ui.ai_chat_markdown import configure_markdown_tags, insert_markdown
from src.ui.window_paint import center_toplevel_on_parent
from src.utils.ai_output import format_diagnostic_evidence
from src.services.ai_record_titles import AiRecordTitles
from src.ui.ai_record_presentation import AiRecordActions, record_labels


REPORT_FONT = "Microsoft YaHei UI"
REPORT_SECTIONS = frozenset(("已观察事实", "证据引用", "原因假设", "建议检查步骤", "缺失信息", "临时操作恢复状态"))


class AiReportsWindow:
    def __init__(self, owner):
        self.owner = owner
        self.window = None
        self.selected = ""
        self.reports = {}
        self.ids = []
        self.created = {}
        self.shown = None
        self.manager = None
        self.record_titles = AiRecordTitles(owner.service.store, owner.service.emit)
        self.record_entries = {}

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
        self.record_actions = AiRecordActions(self.choice, "report", self.record_titles,
            lambda: self.record_entries.get(self.selected), self.names_changed, self.owner.background_color)
        ttk.Button(row, text="刷新报告", command=self.reload).pack(side="left", padx=(6, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=8)
        self.continue_button = ttk.Button(row, text="继续排查", command=self.continue_chat)
        self.continue_button.pack(side="left")
        self.case_button = ttk.Button(row, text="从此报告新建案例", command=self.new_case)
        self.case_button.pack(side="left", padx=6)
        self.delete_button = ttk.Button(row, text="删除报告…", command=self.manage_reports)
        self.delete_button.pack(side="left")
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.output = tk.Text(body, wrap="word", state="disabled", height=12,
                              font=(REPORT_FONT, 11), background="#ffffff", foreground="#17202a",
                              padx=8, pady=8, selectbackground="#cbdff5", selectforeground="#17202a")
        self._configure_report_tags()
        self.output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)
        apply_module_theme(self.window, self.owner.background_color)
        center_toplevel_on_parent(self.window, self.owner.window)

    def _configure_report_tags(self):
        for name, background in (("analysis", "#edf8f5"), ("evidence", "#f3f5f7")):
            self.output.tag_configure("report_" + name, background=background,
                                      lmargin1=12, lmargin2=12, rmargin=12)
        self.output.tag_configure("report_body", font=(REPORT_FONT, 11),
                                  spacing1=3, spacing2=3, spacing3=5)
        self.output.tag_configure("report_heading", font=(REPORT_FONT, 12, "bold"),
                                  foreground="#0f766e", spacing1=8, spacing3=6)
        self.output.tag_configure("report_evidence_body", font=("Consolas", 11),
                                  spacing1=2, spacing2=3, spacing3=4)
        self.output.tag_configure("report_evidence_heading", foreground="#65717f")
        self.output.tag_configure("report_gap", font=(REPORT_FONT, 4), spacing3=6)
        configure_markdown_tags(self.output, REPORT_FONT)

    def _insert_report(self, report, evidence):
        self.output.insert("end", "诊断分析\n", ("report_analysis", "report_heading"))
        start = self.output.index("end-1c")
        insert_markdown(self.output, report, "report_body")
        end = self.output.index("end-1c")
        self.output.tag_add("report_analysis", start, end)
        # 旧报告可能只有纯文本章节名；仅标记独立标题，不解释证据或代码内的同名行。
        for number, line in enumerate(self.output.get(start, end).split("\n")):
            if line.strip().rstrip(":：") not in REPORT_SECTIONS:
                continue
            index = self.output.index(f"{start}+{number}lines")
            content = self.output.index(f"{index}+{len(line) - len(line.lstrip())}chars")
            if not {"md_code", "md_inline_code", "md_h1", "md_h2"}.intersection(self.output.tag_names(content)):
                self.output.tag_add("md_h2", index, f"{index} lineend")
        self.output.insert("end", "\n", ("report_gap",))
        self.output.insert("end", "本地证据：\n",
                           ("report_evidence", "report_heading", "report_evidence_heading"))
        self.output.insert("end", evidence, ("report_evidence", "report_evidence_body"))

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
        entries = self.record_titles.report_entries(rows)
        self.record_entries = {entry["id"]: entry for entry in entries}
        self.record_actions.hide()
        self.choice["values"] = record_labels(entries)
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
        report = str(payload.get("report", "")) if payload is not None else None
        evidence = format_diagnostic_evidence(payload.get("evidence", "")) if payload is not None else None
        state = (self.selected, report, evidence)
        if self.shown != state:
            top = self.output.index("@0,0")
            selection = tuple(str(i) for i in self.output.tag_ranges("sel")) if same else ()
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            if payload is None:
                self.output.insert("end", "暂无诊断报告。", ("report_body",))
            else:
                self._insert_report(report, evidence)
            if len(selection) == 2:
                self.output.tag_add("sel", *selection)
            self.output.configure(state="disabled")
            self.output.yview(top if same else "1.0")
            self.shown = state
        self.continue_button.configure(state="normal" if payload and self.owner.chat_panel else "disabled")
        self.case_button.configure(state="normal" if payload else "disabled")
        self.delete_button.configure(state="normal" if self.ids else "disabled")

    def continue_chat(self):
        # 模态选择/确认期间主线程仍会处理报告通知；固定本次接手来源。
        report_id = self.selected
        try:
            self.owner.refresh_targets()
            payload = self.reports.get(report_id)
            if payload is None:
                raise ValueError("请选择诊断报告")
            target, confirmed = None, False
            if not payload.get("target"):
                targets = tuple(t for t in self.owner.targets if t.channel == payload.get("channel"))
                if not targets:
                    raise ValueError("旧报告缺少目标快照，当前无可关联的同通道设备；仍可查看报告")
                self.owner.service.emit(f"[AI报告] 报告{report_id}缺少目标快照，等待选择同通道当前设备")
                target = AiReportTargetDialog(self.window, targets, self.owner.background_color).show()
                if target is None:
                    self.owner.service.emit(f"[AI报告] 报告{report_id}已取消选择设备，未创建会话")
                    return
                confirmed = messagebox.askyesno("关联旧报告材料", "旧报告没有完整目标快照，不能仅按通道号确认是同一设备。\n"
                    f"将报告作为历史材料关联至：通道{target.channel} / {target.vlan} / {target.port} / {target.host}？\n"
                    "保留原报告批次；本操作不会发起采集，后续发送按会话实时资格执行。",
                    parent=self.window, default="no")
                if not confirmed:
                    self.owner.service.emit(f"[AI报告] 报告{report_id}已取消关联，未创建会话")
                    return
                self.owner.service.emit(f"[AI报告] 报告{report_id}已确认关联通道{target.channel} / "
                                        f"{target.vlan} / {target.port} / {target.host}")
            self.owner.continue_report(report_id, target, confirmed)
        except Exception as exc:
            self.owner.service.emit(f"[AI报告] 报告{report_id}继续排查未完成：{exc}")
            self.owner._error(exc)

    def new_case(self):
        self.owner.case_from_report(self.selected)

    def names_changed(self):
        self.reload()
        if self.manager is not None and self.manager.window.winfo_exists():
            self.manager.refresh()
        if self.owner.chat_panel:
            self.owner.chat_panel.refresh()

    def manage_reports(self):
        if self.manager is not None and self.manager.window.winfo_exists():
            self.manager.refresh()
            self.manager.window.deiconify()
            self.manager.window.lift()
            return
        self.manager = AiReportManager(self.window, self.owner.service, self.selected,
                                       self.reports_deleted, self.owner.background_color)

    def reports_deleted(self):
        self.reload()
        if self.owner.chat_panel:
            self.owner.chat_panel.refresh()
        if not self.ids:
            self.owner.report_status.set("")

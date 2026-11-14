"""报告批量管理：展示全部历史、捕获确认名单，删除交给service。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.ai_chat_panel import format_chat_time
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent
from src.services.ai_record_titles import AiRecordTitles
from src.ui.ai_record_presentation import AiRecordActions, short_title


class AiReportManager:
    def __init__(self, parent, service, selected, on_changed, background):
        self.service, self.on_changed = service, on_changed
        self.rows = {}
        self.deleting = False
        self.record_titles = AiRecordTitles(service.store, service.emit)
        self.record_entries = {}
        self.window = tk.Toplevel(parent)
        self.window.title("管理诊断报告")
        self.window.geometry("940x520")
        self.window.minsize(760, 420)
        self.window.transient(parent)
        body = ttk.Frame(self.window, padding=10)
        body.pack(fill="both", expand=True)
        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        columns = ("title", "created", "channel", "provider", "model", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        for key, title, width in zip(columns, ("主题", "创建时间", "通道", "厂商", "模型", "报告状态"),
                                     (220, 165, 65, 100, 150, 170)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=60, stretch=key in ("title", "model", "status"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.selection_changed)
        self.record_actions = AiRecordActions(self.tree, "report", self.record_titles,
            lambda: self.record_entries.get(self.tree.selection()[0])
                    if len(self.tree.selection()) == 1 and not self.deleting else None,
            self.renamed, background,
            hovered=lambda event: self.record_entries.get(self.tree.identify_row(event.y)))
        self.status = tk.StringVar(self.window)
        ttk.Label(body, textvariable=self.status).pack(anchor="w", pady=8)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        for text, command in (("全选", self.select_all), ("取消选择", self.deselect), ("刷新", self.refresh)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 6))
        self.delete_button = ttk.Button(buttons, text="删除选中", command=self.delete_selected)
        self.delete_button.pack(side="left", padx=(0, 6))
        self.clear_button = ttk.Button(buttons, text="清空全部", command=self.clear_all)
        self.clear_button.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="关闭", command=self.window.destroy).pack(side="right")
        self.refresh()
        if selected in self.rows:
            self.tree.selection_set(selected)
            self.tree.see(selected)
        self.selection_changed()
        apply_module_theme(self.window, background)
        center_toplevel_on_parent(self.window, parent)

    def refresh(self):
        selection = self.tree.selection()
        rows = self.service.store.reports(limit=None)
        busy = self.service.report_deletion_busy_ids()
        self.rows = {identifier: (created, payload) for identifier, created, payload in rows}
        self.record_entries = {entry["id"]: entry for entry in self.record_titles.report_entries(rows)}
        self.record_actions.hide()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for identifier, created, payload in rows:
            status = "排队 / 生成 / 清理中（不可删除）" if identifier in busy else payload.get("status", "")
            self.tree.insert("", "end", iid=identifier,
                             values=(short_title(self.record_entries[identifier]["title"]), format_chat_time(created),
                             payload.get("channel", ""), payload.get("provider", ""),
                             payload.get("model", ""), status))
        self.tree.selection_set([identifier for identifier in selection if identifier in self.rows])
        self.selection_changed()

    def renamed(self):
        self.on_changed()
        self.refresh()

    def selection_changed(self, event=None):
        self.delete_button.configure(state="normal" if self.tree.selection() and not self.deleting else "disabled")
        self.clear_button.configure(state="normal" if self.rows and not self.deleting else "disabled")
        self.status.set(f"共 {len(self.rows)} 份报告，已选 {len(self.tree.selection())} 份")

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
        self.selection_changed()

    def deselect(self):
        self.tree.selection_remove(self.tree.selection())
        self.selection_changed()

    def delete_selected(self):
        self._delete(tuple(self.tree.selection()))

    def clear_all(self):
        # 固定点击时名单，确认期间新增报告不纳入本次清空。
        self._delete(tuple(self.rows))

    def _delete(self, identifiers):
        if self.deleting or not identifiers:
            return
        summaries = []
        for identifier in identifiers[:12]:
            created, payload = self.rows[identifier]
            summaries.append(f"{self.record_entries[identifier]['title']} | {format_chat_time(created)} | 通道{payload.get('channel', '')} | "
                             f"{payload.get('provider', '')} / {payload.get('model', '')} | {identifier}")
        preview = "\n".join(summaries)
        if len(identifiers) > 12:
            preview += f"\n……另有 {len(identifiers) - 12} 份报告"
        self.deleting = True
        self.selection_changed()
        try:
            if not messagebox.askyesno("永久删除诊断报告",
                    f"确定永久删除以下 {len(identifiers)} 份报告？\n\n{preview}\n\n"
                    "报告将永久删除，无法撤销。\n"
                    "会话及已留存材料、已确认案例及修订、原始日志和模型配置保留。\n"
                    "任何选中报告仍在排队、生成或清理时，本次全部不删除。",
                    parent=self.window, icon="warning", default=messagebox.NO):
                return
            try:
                count = self.service.delete_reports(identifiers)
            except Exception as exc:
                messagebox.showerror("删除报告未完成", str(exc), parent=self.window)
                self.status.set("删除失败，本次全部未删除；可刷新后重试")
                return
            self.on_changed()
            self.refresh()
            self.status.set(f"已删除 {count} 份，跳过已不存在 {len(identifiers) - count} 份；剩余 {len(self.rows)} 份")
        finally:
            self.deleting = False
            if self.window.winfo_exists():
                self.delete_button.configure(state="normal" if self.tree.selection() else "disabled")
                self.clear_button.configure(state="normal" if self.rows else "disabled")

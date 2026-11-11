"""排障会话管理窗口：仅收集选择、确认并调用删除service。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.ai_chat_panel import format_chat_time
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class AiSessionManager:
    def __init__(self, parent, service, selected, on_changed, background):
        self.service, self.on_changed = service, on_changed
        self.rows = {}
        self.deleting = False
        self.window = tk.Toplevel(parent)
        self.window.title("管理排障会话")
        self.window.geometry("940x520")
        self.window.minsize(760, 420)
        self.window.transient(parent)
        body = ttk.Frame(self.window, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="按 Ctrl / Shift 多选；正在排查的会话需先停止并等待后台清理结束。").pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        columns = ("created", "title", "channel", "model", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        for key, title, width in zip(columns, ("创建时间", "标题", "通道", "模型", "当前状态"),
                                     (165, 200, 65, 160, 210)):
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
        rows = self.service.store.chats()
        with self.service.lock:
            busy = set(self.service.running) | set(self.service.executors)
        self.rows = {row["id"]: row for row in rows}
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in rows:
            status = "排查 / 排队 / 清理中（不可删除）" if row["id"] in busy else row["status"]
            self.tree.insert("", "end", iid=row["id"], values=(format_chat_time(row["created"]),
                             row["title"], row["target"]["channel"], row["profile"]["model"], status))
        self.tree.selection_set([identifier for identifier in selection if identifier in self.rows])
        self.selection_changed()

    def selection_changed(self, event=None):
        self.delete_button.configure(state="normal" if self.tree.selection() and not self.deleting else "disabled")
        self.clear_button.configure(state="normal" if self.rows and not self.deleting else "disabled")
        self.status.set(f"共 {len(self.rows)} 个会话，已选 {len(self.tree.selection())} 个")

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
        self.selection_changed()

    def deselect(self):
        self.tree.selection_remove(self.tree.selection())
        self.selection_changed()

    def delete_selected(self):
        self._delete(tuple(self.tree.selection()))

    def clear_all(self):
        # 捕获点击时的列表；确认期间新建的会话不纳入本次清空。
        self._delete(tuple(self.rows))

    def _delete(self, identifiers):
        if self.deleting or not identifiers:
            return
        summaries = [f"{format_chat_time(self.rows[i]['created'])} | {self.rows[i]['title']} | "
                     f"通道{self.rows[i]['target']['channel']} | {self.rows[i]['profile']['model']}"
                     for i in identifiers]
        preview = "\n".join(summaries[:12])
        if len(summaries) > 12:
            preview += f"\n……另有 {len(summaries) - 12} 个会话"
        self.deleting = True
        self.selection_changed()
        try:
            if not messagebox.askyesno("永久删除排障会话",
                    f"确定永久删除以下 {len(identifiers)} 个会话？\n\n{preview}\n\n"
                    "会话、聊天记录、模型上下文和留存证据将永久删除，无法撤销。\n"
                    "原始日志/导入文件、抓包文件、诊断报告及已确认案例保留。\n"
                    "任何选中会话仍在排查或清理时，本次全部不删除。",
                    parent=self.window, icon="warning", default=messagebox.NO):
                return
            try:
                count = self.service.delete_sessions(identifiers)
            except Exception as exc:
                messagebox.showerror("删除会话未完成", str(exc), parent=self.window)
                return
            self.on_changed()
            self.refresh()
            self.status.set(f"已删除 {count} 个会话；剩余 {len(self.rows)} 个")
        finally:
            self.deleting = False
            if self.window.winfo_exists():
                self.delete_button.configure(state="normal" if self.tree.selection() else "disabled")
                self.clear_button.configure(state="normal" if self.rows else "disabled")

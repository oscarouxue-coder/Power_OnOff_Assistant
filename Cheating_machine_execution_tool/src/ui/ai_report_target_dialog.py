"""旧报告接手时按需选择目标；只收集输入，不创建会话或采集。"""
import tkinter as tk
from tkinter import ttk

from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class AiReportTargetDialog:
    def __init__(self, parent, targets, background):
        self.targets = tuple(targets)
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("选择旧报告关联设备")
        self.window.geometry("720x300")
        self.window.minsize(620, 260)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", self.cancel)
        body = ttk.Frame(self.window, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="旧报告缺少完整目标信息，请选择同通道当前设备：").pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(body)
        columns = ("channel", "vlan", "port", "host")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for key, title, width in zip(columns, ("通道", "VLAN", "串口", "IP / 主机"), (70, 130, 100, 260)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, stretch=key == "host")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        for index, target in enumerate(self.targets):
            self.tree.insert("", "end", iid=str(index),
                             values=(target.channel, target.vlan, target.port, target.host))
        self.tree.bind("<<TreeviewSelect>>", self.selection_changed)
        buttons = ttk.Frame(body)
        # 先给底部操作留出空间，列表再填满余下区域。
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        table.pack(fill="both", expand=True)
        self.cancel_button = ttk.Button(buttons, text="取消", command=self.cancel, default="active")
        self.cancel_button.pack(side="right")
        self.choose_button = ttk.Button(buttons, text="选择设备", command=self.choose, state="disabled")
        self.choose_button.pack(side="right", padx=(0, 8))
        self.cancel_button.bind("<Return>", self.cancel)
        self.choose_button.bind("<Return>", self.choose)
        apply_module_theme(self.window, background)
        center_toplevel_on_parent(self.window, parent)

    def selection_changed(self, _event=None):
        self.choose_button.configure(state="normal" if self.tree.selection() else "disabled")

    def choose(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        self.result = self.targets[int(selected[0])]
        self.window.destroy()

    def cancel(self, _event=None):
        self.window.destroy()

    def show(self):
        self.window.deiconify()
        self.window.wait_visibility()
        self.window.grab_set()
        self.cancel_button.focus_set()
        self.window.wait_window()
        return self.result

"""已注册 ONU 的原生多选列表与批量危险确认。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.ui.module_theme import MODULE_BACKGROUND, apply_module_theme


class RegisteredOnuList(tk.Frame):
    def __init__(self, master, on_selection_changed=lambda: None, actions_parent=None):
        super().__init__(master, background=MODULE_BACKGROUND)
        self.on_selection_changed = lambda: None
        self.rows = []
        self.enabled = True
        self.finished = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        toolbar = tk.Frame(self, background=MODULE_BACKGROUND)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        button_bar = actions_parent if actions_parent is not None else toolbar
        self.select_all_button = ttk.Button(button_bar, text="全选", command=lambda: self.select_all(True))
        self.select_all_button.pack(side="left", padx=(6, 0))
        self.clear_button = ttk.Button(button_bar, text="取消全选", command=lambda: self.select_all(False))
        self.clear_button.pack(side="left", padx=6)
        self.count_var = tk.StringVar(self, value="已选 0 / 0 台")
        tk.Label(toolbar, textvariable=self.count_var, background=MODULE_BACKGROUND).pack(side="right")
        self.canvas = tk.Canvas(self, background=MODULE_BACKGROUND, highlightthickness=0, height=180)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.body = tk.Frame(self.canvas, background=MODULE_BACKGROUND)
        self.window_id = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.set_candidates(())
        self.on_selection_changed = on_selection_changed

    def _resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        for _candidate, _variable, check, result in self.rows:
            check.configure(wraplength=max(120, event.width - 24), justify="left")
            result.configure(wraplength=max(120, event.width - 16))

    def _wheel(self, event):
        if self.canvas.bbox("all") and self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def set_candidates(self, candidates):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.rows = []
        self.finished = False
        for candidate in candidates:
            variable = tk.BooleanVar(self, value=False)
            text = candidate.display_text + ("  SN:未确认" if not candidate.serial_number else "")
            check = tk.Checkbutton(self.body, text=text, variable=variable,
                                   command=self._changed, anchor="w", selectcolor="#ffffff",
                                   background=MODULE_BACKGROUND, activebackground=MODULE_BACKGROUND,
                                   wraplength=max(120, self.canvas.winfo_width() - 24), justify="left", pady=0)
            check.pack(fill="x", anchor="w")
            result = tk.Label(self.body, text="", anchor="w", justify="left", background=MODULE_BACKGROUND,
                              wraplength=max(120, self.canvas.winfo_width() - 16))
            check.bind("<MouseWheel>", self._wheel)
            result.bind("<MouseWheel>", self._wheel)
            self.rows.append((candidate, variable, check, result))
        self.canvas.yview_moveto(0)
        self.set_enabled(self.enabled)
        self._changed()

    def selected(self):
        return tuple(candidate for candidate, variable, _check, _result in self.rows if variable.get())

    def _changed(self):
        self.count_var.set(f"已选 {len(self.selected())} / {len(self.rows)} 台")
        self.on_selection_changed()

    def select_all(self, selected):
        if not self.enabled or self.finished:
            return
        for _candidate, variable, _check, _result in self.rows:
            variable.set(selected)
        self._changed()

    def set_enabled(self, enabled):
        self.enabled = enabled
        state = "normal" if enabled and not self.finished and self.rows else "disabled"
        self.select_all_button.configure(state=state)
        self.clear_button.configure(state=state)
        for _candidate, _variable, check, _result in self.rows:
            check.configure(state=state)

    def show_results(self, batch_result):
        results = {item.candidate: item for item in batch_result.items}
        for candidate, variable, _check, result in self.rows:
            variable.set(False)
            item = results.get(candidate)
            if item:
                label, color = {"success": ("成功", "#18703b"), "failed": ("失败", "#b42318"),
                                "not_executed": ("未执行", "#946200")}[item.status]
                result.configure(text=f"{label}：{item.message}", foreground=color)
                result.pack(after=_check, fill="x", anchor="w", padx=(24, 0))
        self.finished = True
        self.set_enabled(True)
        self._changed()


def confirm_batch_delete(parent, family, connection, pon_interface, candidates):
    """可滚动完整名单；默认取消，只有明确点击确认才开始删除。"""
    dialog = tk.Toplevel(parent)
    dialog.title("确认删除选中 ONU（危险）")
    dialog.geometry("820x520")
    dialog.minsize(650, 400)
    dialog.transient(parent)
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(0, weight=1)
    frame = tk.Frame(dialog)
    frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 0))
    text = tk.Text(frame, wrap="word", height=8, font=("Microsoft YaHei UI", 10))
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.insert("1.0", "\n".join(f"{index}. {candidate.display_text}" +
                                ("  SN:未确认（将跳过删除）" if not candidate.serial_number else "")
                                for index, candidate in enumerate(candidates, 1)))
    text.configure(state="disabled")
    answer = False

    def finish(confirmed=False):
        nonlocal answer
        answer = confirmed
        dialog.destroy()

    buttons = tk.Frame(dialog)
    buttons.grid(row=1, column=0, sticky="ew", padx=12, pady=12)
    cancel = ttk.Button(buttons, text="取消", command=finish)
    cancel.pack(side="right")
    ttk.Button(buttons, text="确认删除", style="Danger.TButton", command=lambda: finish(True)).pack(side="right", padx=8)
    dialog.protocol("WM_DELETE_WINDOW", finish)
    dialog.bind("<Escape>", lambda _event: finish())
    dialog.bind("<Return>", lambda _event: finish())
    apply_module_theme(dialog)
    dialog.grab_set()
    cancel.focus_set()
    parent.wait_window(dialog)
    return answer

"""共用旧库的只读历史入口，无模型、工具、恢复或编辑入口。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.services.ai_project_store import legacy_records
from src.ui.module_theme import apply_module_theme


def open_legacy_history(parent):
    try:
        records = legacy_records()
    except Exception:
        messagebox.showerror("旧AI历史", "旧历史读取失败，请检查数据库访问权限。", parent=parent)
        return
    window = tk.Toplevel(parent)
    window.title("旧AI历史（只读）")
    window.geometry("960x650")
    choice = ttk.Combobox(window, state="readonly", values=[r[0] for r in records])
    choice.pack(fill="x", padx=12, pady=10)
    frame = ttk.Frame(window)
    frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    body = tk.Text(frame, wrap="word", state="disabled")
    scroll = ttk.Scrollbar(frame, command=body.yview)
    body.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    body.pack(fill="both", expand=True)

    def show(_event=None):
        index = choice.current()
        body.configure(state="normal")
        body.delete("1.0", "end")
        body.insert("1.0", records[index][1] if index >= 0 else "旧库没有会话、报告或案例")
        body.configure(state="disabled")

    choice.bind("<<ComboboxSelected>>", show)
    if records:
        choice.current(0)
    show()
    apply_module_theme(window)

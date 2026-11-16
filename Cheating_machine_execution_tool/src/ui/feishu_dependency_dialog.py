"""Two explicit local choices; dismissing never installs or restarts."""
import tkinter as tk
from tkinter import ttk

from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class MissingFeishuSdkDialog:
    def __init__(self, parent):
        self.install = False
        self.window = tk.Toplevel(parent)
        self.window.title("飞书接入未完成")
        self.window.transient(parent)
        self.window.resizable(False, False)
        ttk.Label(self.window, text="缺少飞书SDK，飞书接入暂不可用。\n是否安装项目规定的依赖并重启程序？",
                  padding=20, justify="left").pack(fill="x")
        buttons = ttk.Frame(self.window, padding=(16, 0, 16, 16))
        buttons.pack(fill="x")
        self.install_button = ttk.Button(buttons, text="安装并重启", command=self.accept)
        self.install_button.pack(side="left", padx=(0, 12))
        self.ok_button = ttk.Button(buttons, text="确定", command=self.dismiss)
        self.ok_button.pack(side="right")
        self.window.protocol("WM_DELETE_WINDOW", self.dismiss)
        self.window.bind("<Escape>", lambda event: self.dismiss())
        self.window.bind("<Return>", lambda event: self.accept() if self.window.focus_get() == self.install_button else self.dismiss())
        apply_module_theme(self.window)
        center_toplevel_on_parent(self.window, parent)

    def accept(self):
        self.install = True
        self.window.destroy()

    def dismiss(self):
        self.window.destroy()

    def show(self):
        previous = self.window.grab_current()
        self.window.grab_set()
        self.ok_button.focus_set()
        self.window.wait_window()
        if previous is not None and previous.winfo_exists():
            previous.grab_set()
        return self.install

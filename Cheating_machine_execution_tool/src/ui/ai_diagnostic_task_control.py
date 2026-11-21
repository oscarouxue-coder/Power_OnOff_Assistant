"""发送按钮的按需诊断模式菜单；任务执行仍由service负责。"""
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from src.models.ai_diagnostics import diagnostic_progress_text
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class DiagnosticTaskControl:
    def __init__(self, panel):
        self.panel = panel
        self.window = None
        self.enabled = panel.service.store.setting("continuous_diagnosis", False) is True
        self.menu = tk.Menu(panel.send_button, tearoff=False)
        self.menu.add_command(label="新会话", command=self.new_session)
        self.menu.add_separator()
        self.menu.add_command(label="切换为常规对话（沿用操作权限）", command=lambda: self.changed(False))
        self.menu.add_command(label="切换为连续诊断（仅定位与建议）", command=lambda: self.changed(True))
        self.menu.add_separator()
        self.menu.add_command(label="查看本会话排查进展", command=self.show_progress)
        self.capability_manager = None
        if getattr(panel.service, "capabilities", None) is not None:
            self.menu.add_separator()
            self.menu.add_command(label="业务任务与受控扩展…", command=self.show_capabilities)
        panel.send_button.bind("<Button-3>", self.popup)
        panel.send_button.bind("<Alt-Down>", self.popup)

    def popup(self, event):
        self.menu.entryconfigure(0, state="disabled" if self.panel.routing else "normal")
        button = self.panel.send_button
        x, y = button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
        if getattr(event, "num", None) == 3:
            x, y = event.x_root, event.y_root
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()
        return "break"

    def new_session(self):
        return self.panel.new()

    def show_capabilities(self):
        from src.ui.capability_management import CapabilityManagement
        if self.capability_manager is None:
            self.capability_manager = CapabilityManagement(self.panel)
        self.capability_manager.open()

    def changed(self, enabled):
        self.enabled = enabled
        self.panel.service.store.set_setting("continuous_diagnosis", enabled)
        self.panel.service.emit("本地发送模式：" + ("连续诊断，仅定位和建议" if enabled else "常规对话，沿用现有操作权限"))
        self.panel.render()

    def show_progress(self):
        panel = self.panel
        if not panel.selected:
            return
        session = panel.service.store.chat(panel.selected)
        if self.window is None or not self.window.winfo_exists():
            self.window = tk.Toplevel(panel.owner.window)
            self.window.title("连续诊断进展")
            self.window.geometry("760x480")
            self.window.minsize(560, 300)
            self.output = ScrolledText(self.window, wrap="word", font=("Microsoft YaHei UI", 11), padx=12, pady=10)
            self.output.pack(fill="both", expand=True, padx=10, pady=10)
            apply_module_theme(self.window, panel.owner.background_color)
            center_toplevel_on_parent(self.window, panel.owner.window)
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", diagnostic_progress_text(session))
        self.output.configure(state="disabled")
        self.window.deiconify()
        self.window.lift()

    def label(self):
        return "发送连续诊断 ▾" if self.enabled else "发送 / 回答问题 ▾"

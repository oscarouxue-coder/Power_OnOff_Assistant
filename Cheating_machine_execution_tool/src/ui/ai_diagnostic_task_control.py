"""发送按钮的按需诊断模式菜单；任务执行仍由service负责。"""
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class DiagnosticTaskControl:
    def __init__(self, panel):
        self.panel = panel
        self.window = None
        self.enabled = panel.service.store.setting("continuous_diagnosis", False) is True
        self.menu = tk.Menu(panel.send_button, tearoff=False)
        self.menu.add_command(label="切换为常规对话（沿用操作权限）", command=lambda: self.changed(False))
        self.menu.add_command(label="切换为连续诊断（仅定位与建议）", command=lambda: self.changed(True))
        self.menu.add_separator()
        self.menu.add_command(label="查看本会话排查进展", command=self.show_progress)
        panel.send_button.bind("<Button-3>", self.popup)
        panel.send_button.bind("<Alt-Down>", self.popup)

    def popup(self, event):
        button = self.panel.send_button
        x, y = button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
        if getattr(event, "num", None) == 3:
            x, y = event.x_root, event.y_root
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()
        return "break"

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
        memory = session.get("diagnostic_task", {})
        lines = ["目标：" + memory.get("goal", "本会话尚未开始连续诊断"), "状态：" + session.get("status", "无")]
        labels = {"pending": "待检查", "in_progress": "检查中", "completed": "已检查"}
        lines += [labels.get(s["status"], s["status"]) + "：" + s["text"] for s in memory.get("steps", [])]
        lines += ["取证：" + c["tool"] + " ｜ " + c["evidence_id"] + ("（失败/受阻）" if c["failed"] else "")
                  for c in memory.get("checks", [])]
        lines += ["观察笔记（须核对证据）：" + f["observation"] + " ｜ " + f["evidence_id"] for f in memory.get("findings", [])]
        if memory.get("reason"):
            lines.append("结束原因：" + memory["reason"])
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
        self.output.insert("1.0", "\n".join(lines))
        self.output.configure(state="disabled")
        self.window.deiconify()
        self.window.lift()

    def label(self):
        return "发送连续诊断 ▾" if self.enabled else "发送 / 回答问题 ▾"

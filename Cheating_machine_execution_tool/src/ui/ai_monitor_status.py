"""自动监控状态投影与主界面局部布局；不执行任务或改变监控策略。"""
from tkinter import ttk

from src.models.ai_diagnostics import MonitorStatus


def monitor_presentation(status):
    if not status.enabled:
        text, color = (("已关闭，收尾中", "#a16207") if status.queued + status.running + status.cleaning
                       else ("已关闭", "#65717f"))
    elif status.waiting_approval:
        text, color = f"待批准（{status.waiting_approval}）", "#a16207"
    elif status.running:
        text, color = "诊断中", "#1d4ed8"
    elif status.cleaning:
        text, color = "收尾中", "#a16207"
    elif status.queued:
        text, color = "诊断排队中", "#a16207"
    elif status.run_active:
        text, color = "监控中", "#047857"
    else:
        text, color = "已开启，待测试", "#047857"
    return "AI自动监控：" + text, color


class AiMonitorStatusRow(ttk.Frame):
    """三个状态始终并排；窄窗口按各列宽度折行，避免长停止提示挤掉AI状态。"""
    def __init__(self, parent, font_family):
        super().__init__(parent, style="Surface.TFrame")
        self.ai_label = ttk.Label(self, width=1, font=(font_family, 10), background="#ffffff")
        self.show(MonitorStatus())

    def attach(self, power_label, progress_label):
        self.power_label, self.progress_label = power_label, progress_label
        self.labels = (self.power_label, self.ai_label, self.progress_label)
        for column, label in enumerate(self.labels):
            self.columnconfigure(column, weight=1, uniform="status")
            label.configure(width=1)
            label.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 12, 0))
            label.bind("<Configure>", lambda event, widget=label: widget.configure(
                wraplength=max(1, event.width - (28 if widget is self.power_label else 2))))

    def show(self, status):
        text, color = monitor_presentation(status)
        self.ai_label.configure(text=text, foreground=color)

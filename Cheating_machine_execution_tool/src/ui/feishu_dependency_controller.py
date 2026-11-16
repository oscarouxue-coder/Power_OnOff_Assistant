"""Main-thread repair adapter, modal progress and application lifecycle callbacks."""
from pathlib import Path
import os
import queue
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from src.models.dependency_repair import RepairResult
from src.services.adapter_rename_service import adapter_rename_is_busy
from src.services.feishu_dependency_repair import FeishuDependencyRepair
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


def repair_host_busy(app):
    """Read existing activity without invoking stop/cancel/close callbacks."""
    values = vars(app)
    if (values.get('_app_closing') or adapter_rename_is_busy(app)
            or any(v for k, v in values.items() if isinstance(v, bool) and (k == 'running' or k.endswith('_running')))
            or values.get('_project_info_query_count', 0)):
        return True
    if any(worker.is_alive() for worker in values.get('_background_workers', ())):
        return True
    run = values.get('_sample_upgrade_run')
    if run is not None and not run.finished:
        return True
    pipeline = values.get('_pipeline_ui')
    if pipeline is not None and not pipeline.idle():
        return True
    updates = values.get('app_update_dialog')
    if updates is not None and updates.jobs:
        return True
    notifications = values.get('feishu_notifications')
    if notifications is not None and notifications.busy:
        return True
    assistant = values.get('ai_assistant')
    if assistant is not None:
        if not assistant.service.idle or assistant.dialog.background:
            return True
        capabilities = getattr(assistant, 'capabilities', None)
        if capabilities is not None and not capabilities.jobs.idle:
            return True
        with assistant.service.lock:
            if (assistant.service.stops or assistant.service.monitor.running or assistant.service.monitor.executors
                    or any(getattr(executor, 'transport', None) is not None for executor in assistant.service.executors.values())):
                return True
    return False


class FeishuDependencyController:
    def __init__(self, app, root, gate):
        self.app, self.root = app, Path(root)
        self.service = FeishuDependencyRepair(root, gate)
        self.window = None
        self.restart_requested = False
        # sys.argv contains business arguments after debugpy has selected the entry.
        self.arguments = list(sys.argv[1:])
        self.cwd = os.getcwd()

    @property
    def prevents_close(self):
        return self.service.gate.active and not self.restart_requested

    def start(self):
        if self.service.gate.active:
            if self.window is not None:
                self.window.lift()
            return
        self.app._log('[飞书依赖] 操作员选择安装并重启，开始预检')
        try:
            self.service.start(lambda: repair_host_busy(self.app))
        except Exception as exc:
            self.app._log('[飞书依赖] 预检跳过：' + str(exc))
            messagebox.showwarning('暂不能安装飞书SDK', str(exc), parent=self.app)
            return
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = tk.Toplevel(self.app)
        self.window.title('安装飞书SDK')
        self.window.transient(self.app)
        self.window.geometry('560x200')
        self.window.resizable(False, False)
        self.status = tk.StringVar(self.window, '正在准备飞书SDK安装…')
        ttk.Label(self.window, textvariable=self.status, wraplength=510, justify='left', padding=18).pack(fill='both', expand=True)
        self.buttons = ttk.Frame(self.window, padding=12)
        self.buttons.pack(fill='x')
        self.window.protocol('WM_DELETE_WINDOW', self.dismiss)
        apply_module_theme(self.window)
        center_toplevel_on_parent(self.window, self.app, window_width=560, window_height=200)
        self.window.grab_set()
        self.app.after(100, self.poll)

    def dismiss(self):
        if self.prevents_close:
            messagebox.showinfo('正在安装飞书SDK', '请等待安装结束，当前不会退出程序。', parent=self.window)
            return
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def poll(self):
        result = None
        for _ in range(64):
            try:
                event = self.service.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, RepairResult):
                result = event
            else:
                self.app._log(str(event))
                self.status.set(str(event))
        if result is None:
            self.app.after(100, self.poll)
            return
        # The result is enqueued just before thread exit. Keep ownership until it exits.
        if self.service.busy:
            self.service.events.put(result)
            self.app.after(100, self.poll)
            return
        self.status.set(result.message)
        if not result.ok:
            self.service.release()
            self.app._log('[飞书依赖] 安装/验证失败：' + result.message + '；未自动重启，可点击重试')
            ttk.Button(self.buttons, text='重试', command=self.start).pack(side='left')
            ttk.Button(self.buttons, text='关闭', command=self.dismiss).pack(side='right')
            return
        self.app._log('[飞书依赖] 验证成功，等待原程序安全退出后重新启动；不重放飞书操作')
        self.restart_requested = True
        self.dismiss()
        self.app._on_app_close()
        if not vars(self.app).get('_app_closing', False):
            # An existing editor vetoed close before lifecycle shutdown began.
            self.restart_requested = False
            self.service.release()
            messagebox.showwarning('重启未完成', '安装已完成，窗口暂不能关闭，请处理当前窗口后手动重启程序。', parent=self.app)

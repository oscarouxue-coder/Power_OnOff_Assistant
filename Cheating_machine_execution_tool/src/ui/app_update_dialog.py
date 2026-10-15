"""软件检查更新与下载窗口；后台仅调用 service，Tk 操作只在主线程执行。"""
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import StringVar, Text, Toplevel, filedialog, messagebox, ttk

from src.models.app_update import AppUpdateProgress, UpdateProgressStage
from src.services.app_update_service import AppUpdateCancelled, AppUpdateError, AppUpdateService
from src.ui.window_paint import center_toplevel_on_parent


MANUAL_UPDATE_HINT = (
    "请在测试结束并退出旧版后，将 ZIP 完整解压到新目录。"
    "先备份旧目录的 Auto_power_on_off_tool/config，再按说明迁移本机配置；"
    "不要用新包的默认配置覆盖原配置。"
)


def format_bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MB"


def arrange_update_toolbar(toolbar, commands, actions) -> None:
    """新增更新入口后，窄窗口将右侧操作换行，避免遮住原有控件。"""
    toolbar.columnconfigure(0, weight=1)
    commands.grid(row=0, column=0, sticky="w")
    actions.grid(row=0, column=1, sticky="e")

    def arrange(_event=None):
        narrow = toolbar.winfo_width() - 24 < commands.winfo_reqwidth() + actions.winfo_reqwidth()
        row = 1 if narrow else 0
        if int(actions.grid_info()["row"]) != row:
            actions.grid(row=row, column=0 if narrow else 1,
                         columnspan=2 if narrow else 1, sticky="e",
                         pady=(8, 0) if narrow else 0)

    toolbar.bind("<Configure>", arrange, add="+")
    actions.bind("<Configure>", arrange, add="+")


@dataclass
class _UpdateTask:
    kind: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    results: queue.Queue = field(default_factory=queue.Queue)
    progress: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    thread: threading.Thread | None = None

    def report_progress(self, value: AppUpdateProgress) -> None:
        # 只保留最新进度，快速下载不积压数万个 UI 消息。
        try:
            self.progress.get_nowait()
        except queue.Empty:
            pass
        try:
            self.progress.put_nowait(value)
        except queue.Full:
            pass


class AppUpdateDialog:
    def __init__(self, parent, current_version, *, log, service_factory=AppUpdateService):
        self.parent = parent
        self.current_version = current_version
        self.log = log  # 主程序传入线程安全的 log_queue.put。
        self.service_factory = service_factory
        self.toolbar_button = None
        self.window = None
        self.task = None
        self.jobs = []
        self.poll_id = None
        self.shutdown_id = None
        self.shutting_down = False
        self.update = None
        self.saved_path = None

    def bind_button(self, button) -> None:
        self.toolbar_button = button

    def _toolbar(self, checking=False) -> None:
        if self.toolbar_button is not None:
            self.toolbar_button.configure(
                text="正在检查…" if checking else "检查更新",
                state="disabled" if checking or self.task is not None or self.shutting_down else "normal",
            )

    def open(self) -> None:
        if self.shutting_down:
            return
        if self.window is not None:
            self.window.deiconify()
            self.window.lift()
            return
        self.update = None
        self.saved_path = None
        self.window = Toplevel(self.parent)
        self.window.title("检查更新")
        self.window.geometry("660x540")
        self.window.minsize(560, 470)
        self.window.protocol("WM_DELETE_WINDOW", self.close_window)
        content = ttk.Frame(self.window, padding=18)
        content.pack(fill="both", expand=True)
        self.summary = StringVar(master=self.window, value=f"当前版本：{self.current_version}")
        summary_label = ttk.Label(content, textvariable=self.summary, wraplength=600, justify="left")
        summary_label.pack(anchor="w", fill="x")
        ttk.Label(content, text="更新说明").pack(anchor="w", pady=(14, 6))
        notes_frame = ttk.Frame(content)
        notes_frame.pack(fill="both", expand=True)
        self.notes = Text(notes_frame, wrap="word", height=10, state="disabled", font=("Microsoft YaHei UI", 10))
        scrollbar = ttk.Scrollbar(notes_frame, orient="vertical", command=self.notes.yview)
        self.notes.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.notes.pack(side="left", fill="both", expand=True)
        self.status = StringVar(master=self.window, value="")
        status_label = ttk.Label(content, textvariable=self.status, wraplength=600, justify="left")
        status_label.pack(anchor="w", fill="x", pady=(12, 6))
        self.progress_bar = ttk.Progressbar(content, maximum=100, value=0)
        self.progress_bar.pack(fill="x")
        hint_label = ttk.Label(content, text=MANUAL_UPDATE_HINT, wraplength=600, justify="left")
        hint_label.pack(anchor="w", fill="x", pady=12)
        def wrap_labels(event):
            for label in (summary_label, status_label, hint_label):
                label.configure(wraplength=max(1, event.width - 36))
        content.bind("<Configure>", wrap_labels)
        actions = ttk.Frame(content)
        actions.pack(fill="x")
        self.close_button = ttk.Button(actions, text="关闭", command=self.close_window)
        self.close_button.pack(side="right")
        self.action_button = ttk.Button(actions, text="重新检查", command=self.check)
        self.action_button.pack(side="right", padx=8)
        center_toplevel_on_parent(self.window, self.parent, window_width=660, window_height=540)
        self.check()

    def _set_notes(self, text) -> None:
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def check(self) -> None:
        if self.task is not None or self.shutting_down or self.window is None:
            return
        self.update = None
        self.saved_path = None
        self.summary.set(f"当前版本：{self.current_version}")
        self._set_notes("")
        self.status.set("正在检查最新正式版本…")
        self.progress_bar.configure(value=0)
        self.action_button.configure(state="disabled")
        self.close_button.configure(text="取消", command=self.close_window)
        self.log(f"[检查更新] 开始手动检查，当前版本 {self.current_version}。")
        self._start_task("check")

    def download(self) -> None:
        if self.task is not None or self.update is None or self.shutting_down:
            return
        path = filedialog.asksaveasfilename(
            parent=self.window, title="保存新版本便携包",
            initialfile=f"LineCheckAssistant_portable_{self.update.latest_version}.zip",
            defaultextension=".zip", filetypes=[("ZIP 压缩包", "*.zip")],
            confirmoverwrite=False,
        )
        if not path:
            self.log("[检查更新] 已跳过下载：未选择保存位置。")
            return
        destination = Path(path)
        overwrite = destination.exists()
        if overwrite and not messagebox.askyesno(
            "确认覆盖文件", f"文件已存在：\n{destination}\n\n是否在下载并校验成功后覆盖该文件？", parent=self.window,
        ):
            self.log("[检查更新] 已跳过下载：取消覆盖已有文件。")
            return
        self.status.set("正在下载更新包…")
        self.progress_bar.configure(value=0)
        self.action_button.configure(state="disabled")
        self.close_button.configure(text="取消", command=self.cancel_download)
        self.log(f"[检查更新] 开始下载 {self.update.latest_version}。")
        self._start_task("download", self.update, destination, overwrite)

    def _start_task(self, kind, *args) -> None:
        task = _UpdateTask(kind)
        self.task = task
        self.jobs = [job for job in self.jobs if job.thread is not None and job.thread.is_alive()]
        self.jobs.append(task)
        self._toolbar(checking=kind == "check")
        task.thread = threading.Thread(target=self._worker, args=(task, args), daemon=True, name=f"app-update-{kind}")
        try:
            task.thread.start()
        except Exception as exc:
            task.results.put(("error", f"无法启动更新线程：{exc}"))
        self.poll_id = self.parent.after(80, lambda: self._poll(task))

    def _worker(self, task, args) -> None:
        # worker 不调用 Tk / after / 弹窗；service 每次单独创建，不共享 HTTP 会话。
        service = None
        try:
            service = self.service_factory()
            if task.kind == "check":
                value = service.check_for_update(self.current_version, task.cancelled, log=self.log)
                detail = f"发现新版 {value.latest_version}" if value.update_available else f"当前已是最新版本（远端 {value.latest_version}）"
            else:
                update, destination, overwrite = args
                value = service.download_update(update, destination, task.cancelled, task.report_progress, overwrite=overwrite, log=self.log)
                detail = f"下载成功，SHA256 校验通过：{value}"
            outcome = ("success", value)
            self.log(f"[检查更新] {detail}。")
        except AppUpdateCancelled as exc:
            outcome = ("cancelled", str(exc))
            self.log(f"[检查更新] 操作已取消：{exc}")
        except Exception as exc:
            detail = str(exc) if isinstance(exc, AppUpdateError) else f"更新操作异常：{exc}"
            outcome = ("error", detail)
            self.log(f"[检查更新] 失败：{detail}")
        finally:
            if service is not None:
                try:
                    service.close()
                except Exception as exc:
                    self.log(f"[检查更新] 关闭网络会话异常：{exc}")
        task.results.put(outcome)

    def _poll(self, task) -> None:
        if self.shutting_down or self.task is not task or self.window is None:
            return
        self.poll_id = None
        try:
            value = task.progress.get_nowait()
        except queue.Empty:
            pass
        else:
            total = value.total_bytes
            percent = min(100, value.completed_bytes * 100 / total) if total else 0
            phase = "正在校验 SHA256" if value.stage is UpdateProgressStage.VERIFYING else "正在下载"
            count = f"{format_bytes(value.completed_bytes)} / {format_bytes(total)}（{percent:.1f}%）" if total else format_bytes(value.completed_bytes)
            if not task.cancelled.is_set():
                self.status.set(f"{phase}：{count}")
            self.progress_bar.configure(value=percent)
        try:
            outcome, payload = task.results.get_nowait()
        except queue.Empty:
            self.poll_id = self.parent.after(80, lambda: self._poll(task))
            return
        self.task = None
        self._toolbar()
        self.close_button.configure(text="关闭", command=self.close_window, state="normal")
        self.action_button.configure(state="normal")
        if outcome != "success":
            self.status.set(payload)
            self.action_button.configure(text="重新下载" if self.update is not None else "重新检查", command=self.download if self.update is not None else self.check)
        elif task.kind == "check":
            self.update = payload if payload.update_available else None
            self.summary.set(f"当前版本：{payload.current_version}    最新版本：{payload.latest_version}\n发布日期：{payload.published_at or '未提供'}")
            self._set_notes(payload.release_notes or "此版本未填写更新说明。")
            if payload.update_available:
                self.status.set(f"发现新版本，便携包大小：{format_bytes(payload.package_asset.size)}。是否下载？")
                self.action_button.configure(text="下载", command=self.download)
                self.close_button.configure(text="暂不下载")
            else:
                self.status.set("当前已是最新版本，无需更新。")
                self.action_button.configure(text="重新检查", command=self.check)
        else:
            self.saved_path = payload
            self.status.set(f"下载成功，SHA256 校验通过。\n保存位置：{payload}")
            self.progress_bar.configure(value=100)
            self.action_button.configure(text="打开所在文件夹", command=self.open_folder)

    def cancel_download(self) -> None:
        if self.task is not None:
            self.task.cancelled.set()
            self.log("[检查更新] 已请求取消下载，等待当前网络读取结束并清理临时文件。")
            self.status.set("正在取消，等待当前网络读取结束并清理临时文件…")
            self.close_button.configure(state="disabled")

    def open_folder(self) -> None:
        if self.saved_path is None:
            return
        try:
            os.startfile(str(self.saved_path.parent))
        except OSError as exc:
            self.log(f"[检查更新] 打开下载目录失败：{exc}")
            messagebox.showerror("无法打开目录", str(exc), parent=self.window)
        else:
            self.log(f"[检查更新] 已打开下载目录：{self.saved_path.parent}")

    def close_window(self) -> None:
        if self.task is not None:
            self.task.cancelled.set()
            self.log("[检查更新] 关闭窗口，已请求取消本次操作。")
        elif self.window is not None and self.update is not None and self.saved_path is None:
            self.log("[检查更新] 已跳过下载：暂不下载。")
        self.task = None  # 老任务仅清理自己的文件，不再操作新窗口。
        if self.poll_id is not None:
            self.parent.after_cancel(self.poll_id)
            self.poll_id = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
        self._toolbar()

    def prepare_app_close(self, on_ready) -> bool:
        """退出前异步等待取消与临时文件收尾，避免进程退出杀死下载线程。"""
        self.shutting_down = True
        self.close_window()
        for job in self.jobs:
            job.cancelled.set()
        if not any(job.thread is not None and job.thread.is_alive() for job in self.jobs):
            return True
        if self.shutdown_id is None:
            self.log("[检查更新] 正在收尾更新任务，完成后退出程序。")
            self.shutdown_id = self.parent.after(80, lambda: self._wait_for_close(on_ready))
        return False

    def _wait_for_close(self, on_ready) -> None:
        self.shutdown_id = None
        if any(job.thread is not None and job.thread.is_alive() for job in self.jobs):
            self.shutdown_id = self.parent.after(80, lambda: self._wait_for_close(on_ready))
        else:
            on_ready()

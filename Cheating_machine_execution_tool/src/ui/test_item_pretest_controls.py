"""测试项页预备测试按钮及后台任务生命周期。"""
from __future__ import annotations

import queue
import threading
from tkinter import messagebox, ttk

from src.services.test_item_pretest_service import run_pretest


class PretestControls:
    def __init__(self, parent, *, capture_request, log, is_busy=lambda: False):
        self.parent = parent
        self.capture_request = capture_request
        self.log = log
        self.is_busy = is_busy
        self.running = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.frame = ttk.Frame(parent, style="App.TFrame")
        self.frame.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(
            self.frame, text="执行全部命令（预备测试）", command=self.start,
            style="Primary.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            self.frame, text="停止执行", command=self.stop, state="disabled",
            style="Secondary.TButton",
        )
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Label(self.frame, text="每条仅执行一次；过程和结果保存到主界面日志。",).pack(side="left", padx=(12, 0))

    def start(self):
        if self.running:
            return
        if self.is_busy():
            messagebox.showwarning("暂不能预备测试", "已有设备任务正在执行，请结束后再启动预备测试。", parent=self.parent)
            return
        try:
            request = self.capture_request()
        except Exception as exc:
            self.log(f"[预备测试] 启动失败：{exc}", "error")
            messagebox.showwarning("预备测试配置不完整", str(exc), parent=self.parent)
            return
        targets = "\n".join(
            f"• {c.section} / {c.vlan_name or c.adapter_alias}：{c.network_card_ip} → {c.device_manage_ip}:{request.telnet.port}"
            for c in request.channels
        )
        if not messagebox.askyesno(
            "确认执行预备测试",
            f"将使用当前页面内容，按顺序执行全部 {len(request.order.items)} 条命令，每条仅一次。\n"
            f"目标通道：\n{targets}\n\n"
            "将按通道配置准备网卡并登录设备，命令可能修改设备状态。\n"
            "使用未保存的页面内容，但不会自动保存配置。是否执行？",
            parent=self.parent,
        ):
            self.log("[预备测试] 操作员取消，跳过执行。", "warning")
            return
        self.running = True
        self.cancel = threading.Event()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.log(f"[预备测试] 已确认执行目标：\n{targets}", "")
        try:
            threading.Thread(target=self._worker, args=(request,), daemon=True).start()
        except Exception as exc:
            self.log(f"[预备测试] 启动失败：{exc}", "error")
            self._finish()
            return
        self.parent.after(50, self._poll)

    def _worker(self, request):
        try:
            run_pretest(request, self.cancel, lambda text, tag: self.events.put((text, tag)))
        except Exception as exc:
            self.events.put((f"[预备测试] 执行失败：{exc}", "error"))
        finally:
            self.events.put(None)

    def _poll(self):
        for _ in range(100):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event is None:
                self._finish()
                return
            self.log(*event)
        self.parent.after(50, self._poll)

    def _finish(self):
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def stop(self):
        if self.running:
            self.cancel.set()
            self.stop_button.configure(state="disabled")
            self.log("[预备测试] 已请求停止，不再下发后续命令；等待当前连接或网络操作退出。", "warning")

    def can_close(self):
        if not self.running:
            return True
        self.stop()
        messagebox.showinfo("正在停止预备测试", "正在停止并保存剩余日志，请任务结束后再关闭窗口。", parent=self.parent)
        return False

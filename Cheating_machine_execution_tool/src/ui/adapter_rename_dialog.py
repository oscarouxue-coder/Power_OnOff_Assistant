"""网卡名称修改的确认、输入和后台任务窗口。"""
from __future__ import annotations

import queue
import threading
from tkinter import StringVar, Toplevel, messagebox, ttk

from src.models.network_adapter import AdapterRenameResult
from src.services.adapter_rename_service import (
    ADAPTER_NAME_HINT, AdapterRenameService, rename_unavailable_reason, validate_adapter_name,
)
from src.ui.window_paint import center_toplevel_on_parent


def offer_adapter_rename(parent, *, section, old_name, is_busy, on_success, log):
    log(f"[网卡重命名] {section} 选择的网卡 {old_name} 不是以数字结尾，已撤销本次选择。")
    if not messagebox.askyesno(
        "是否修改网卡名称？",
        f"网卡“{old_name}”不是以数字结尾，无法自动生成 PC 静态 IP。\n"
        "建议改为 VLAN101、以太网101 等数字结尾的名称，末尾数字范围为 2–254（非网关地址）。\n\n"
        "是否由软件协助修改 Windows 网卡名称？选择“是”后可输入新名称并确认修改。",
        parent=parent,
    ):
        log("[网卡重命名] 操作员取消建议，跳过修改，保留原选择与配置。")
        return None
    log(f"[网卡重命名] 操作员接受建议，准备输入 {old_name} 的新名称。")
    reason = rename_unavailable_reason(busy=is_busy())
    if reason:
        log(f"[网卡重命名] 跳过修改：{reason}")
        messagebox.showwarning("暂不能修改网卡名称", reason, parent=parent)
        return None
    return AdapterRenameDialog(
        parent, old_name=old_name, is_busy=is_busy, on_success=on_success, log=log,
    )


class AdapterRenameDialog:
    def __init__(self, parent, *, old_name, is_busy, on_success, log, service=None):
        self.parent = parent
        self.old_name = old_name
        self.is_busy = is_busy
        self.on_success = on_success
        self.log = log
        self.service = service or AdapterRenameService()
        self.running = False
        self.uncertain = False
        self.events = queue.Queue()
        self.window = Toplevel(parent)
        self.window.withdraw()
        self.window.title("修改网卡名称")
        self.window.transient(parent)
        self.window.resizable(False, False)
        body = ttk.Frame(self.window, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"当前网卡：{old_name}", wraplength=460).pack(anchor="w")
        ttk.Label(body, text=ADAPTER_NAME_HINT, wraplength=460, justify="left").pack(anchor="w", pady=(10, 6))
        self.name_var = StringVar(master=self.window, value="")
        self.entry = ttk.Entry(body, textvariable=self.name_var, width=48)
        self.entry.pack(fill="x")
        self.status_var = StringVar(master=self.window, value="确认修改将更改 Windows 网卡名称。")
        ttk.Label(body, textvariable=self.status_var, wraplength=460).pack(anchor="w", pady=10)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.submit_button = ttk.Button(buttons, text="确认修改", command=self.submit)
        self.submit_button.pack(side="right")
        self.cancel_button = ttk.Button(buttons, text="取消", command=self.close)
        self.cancel_button.pack(side="right", padx=8)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Return>", lambda _event: self.submit())
        self.window.bind("<Escape>", lambda _event: self.close())
        center_toplevel_on_parent(self.window, parent)
        self.window.deiconify()
        self.window.grab_set()
        self.entry.focus_set()

    def submit(self):
        if self.running or self.uncertain:
            return
        try:
            new_name = validate_adapter_name(self.name_var.get())
            reason = rename_unavailable_reason(busy=self.is_busy())
            if reason:
                raise ValueError(reason)
        except ValueError as exc:
            self.status_var.set(str(exc))
            self.log(f"[网卡重命名] 输入/前置校验失败：{exc}；未下发修改命令。")
            return
        self.pending_name = new_name
        self.log(f"[网卡重命名] 操作员确认修改：{self.old_name} → {new_name}")
        self.running = True
        self.entry.configure(state="disabled")
        self.submit_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.status_var.set("正在修改并核实网卡名称，请等待……")
        try:
            threading.Thread(target=self._worker, args=(new_name,), daemon=True).start()
        except Exception as exc:
            self._finish(AdapterRenameResult(False, f"启动修改任务失败：{exc}"))
            return
        self.window.after(50, self._poll)

    def _worker(self, new_name):
        try:
            result = self.service.rename(
                self.old_name, new_name,
                emit=lambda line: self.events.put(("log", line)),
            )
        except Exception as exc:
            result = AdapterRenameResult(False, f"重命名任务异常：{exc}。请核实系统网卡名称后刷新。", uncertain=True)
        self.events.put(("result", result))

    def _poll(self):
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "result":
                self._finish(value)
                return
            self.log(value)
        self.window.after(50, self._poll)

    def _finish(self, result):
        self.running = False
        self.uncertain = result.uncertain
        if result.ok:
            # 回调在 Tk 主线程同步引用、刷新和保存；此时模态窗口仍持有 grab。
            try:
                warning = self.on_success(self.pending_name, result)
            except Exception as exc:
                warning = f"网卡已重命名，但界面或配置同步失败：{exc}。请核实配置后重新保存。"
                self.log(f"[网卡重命名] {warning}")
            self.window.destroy()
            if warning:
                messagebox.showwarning("网卡已重命名", warning, parent=self.parent)
            else:
                messagebox.showinfo("修改网卡名称成功", result.message, parent=self.parent)
            return
        self.status_var.set(result.message)
        self.log(f"[网卡重命名] {result.message}")
        self.cancel_button.configure(state="normal", text="关闭" if result.uncertain else "取消")
        if not result.uncertain:
            self.entry.configure(state="normal")
            self.submit_button.configure(state="normal")
            self.entry.focus_set()
        messagebox.showwarning("修改网卡名称未完成", result.message, parent=self.window)

    def can_close(self):
        if self.running:
            self.status_var.set("正在修改并核实网卡名称，请等待完成后关闭。")
            return False
        return True

    def close(self):
        if self.can_close():
            self.log("[网卡重命名] 操作员关闭名称输入窗口，未再下发修改命令。")
            self.window.destroy()

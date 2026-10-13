"""ONU 确认页的逐目标命令编辑器；仅在 Tk 主线程收集和展示输入。"""
from __future__ import annotations

from tkinter import StringVar, Text, messagebox, ttk

from src.services.onu_command_edit_service import OnuCommandEditError, OnuCommandEditService


def command_plan_summary(plan) -> str:
    request = plan.request
    services = "、".join(f"{item.service_id}/{item.vlan}" for item in request.services)
    return (
        f"SN {request.onu.serial_number} / {request.onu.pon_interface} / ONU ID {request.onu_id}："
        f"{'已编辑' if plan.edited else '生成命令'}，类型模板 {request.onu_type}，"
        f"T-CONT {request.tcont_id}/{request.tcont_profile}，ServiceID/VLAN {services}"
    )


class OnuCommandEditor:
    def __init__(self, parent, *, on_ready_changed, log, height=8):
        self.parent = parent
        self.on_ready_changed = on_ready_changed
        self.log = log
        self.service = OnuCommandEditService()
        self.requests = ()
        self.originals = ()
        self.drafts = []
        self.plans = None
        self.validated_texts = ()
        self.current_index = 0
        self.busy = False
        self.updating = False
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self.target_var = StringVar(master=parent)
        self.target_combo = ttk.Combobox(
            self.frame, textvariable=self.target_var, state="disabled", width=68,
        )
        self.target_combo.grid(row=0, column=0, sticky="ew")
        self.target_combo.bind("<<ComboboxSelected>>", self._switch_target)
        ttk.Label(
            self.frame,
            text="命令仅本批有效；保留目标及命令顺序，关联业务命令需一致修改。空行和整行 # 注释不下发。",
            wraplength=880,
        ).grid(row=1, column=0, sticky="w", pady=(4, 4))
        self.text = Text(
            self.frame, height=height, font=("Consolas", 10), wrap="none",
            state="disabled", undo=True,
        )
        self.text.grid(row=2, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        vertical.grid(row=2, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        horizontal.grid(row=3, column=0, sticky="ew")
        self.text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.text.bind("<<Modified>>", self._on_modified)
        actions = ttk.Frame(self.frame)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.validate_button = ttk.Button(
            actions, text="校验编辑", command=self.validate, state="disabled",
            style="Secondary.TButton",
        )
        self.validate_button.pack(side="left")
        self.restore_button = ttk.Button(
            actions, text="恢复生成命令", command=self.restore, state="disabled",
            style="Secondary.TButton",
        )
        self.restore_button.pack(side="left", padx=(8, 0))
        self.status_var = StringVar(master=parent, value="请先生成命令预览。")
        ttk.Label(self.frame, textvariable=self.status_var, wraplength=880).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0),
        )
        self.write_note_var = StringVar(master=parent)
        ttk.Label(self.frame, textvariable=self.write_note_var, wraplength=880).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0),
        )

    def load_requests(self, requests, *, write_note=""):
        requests = tuple(requests)
        plans = tuple(self.service.build_default(request) for request in requests)
        self.requests = requests
        self.originals = tuple("\n".join(plan.commands) for plan in plans)
        self.drafts = list(self.originals)
        self.plans = plans
        self.validated_texts = tuple(self.drafts)
        self.current_index = 0
        self.target_combo.configure(values=tuple(
            f"{i}. SN {request.onu.serial_number} / {request.onu.pon_interface} / ONU ID {request.onu_id}"
            for i, request in enumerate(requests, 1)
        ))
        self.write_note_var.set(write_note)
        if requests:
            self.target_combo.current(0)
        self._display_current()
        self.set_busy(False)
        self._show_validated()

    def clear(self):
        self.requests = ()
        self.originals = ()
        self.drafts = []
        self.plans = None
        self.validated_texts = ()
        self.current_index = 0
        self.target_combo.configure(values=(), state="disabled")
        self.target_var.set("")
        self.write_note_var.set("")
        self._display_current()
        self.set_busy(False)
        self.status_var.set("参数或目标已变化，请重新生成命令预览。")
        self.on_ready_changed(False)

    def _stash_current(self):
        if self.drafts:
            self.drafts[self.current_index] = self.text.get("1.0", "end-1c")

    def _display_current(self):
        self.updating = True
        try:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            if self.drafts:
                self.text.insert("1.0", self.drafts[self.current_index])
            self.text.edit_reset()
            self.text.edit_modified(False)
            self.text.configure(state="disabled" if self.busy or not self.drafts else "normal")
        finally:
            self.updating = False

    def _switch_target(self, _event=None):
        if self.busy or not self.drafts:
            return
        self._stash_current()
        if tuple(self.drafts) != self.validated_texts:
            self._mark_pending()
        self.current_index = self.target_combo.current()
        self._display_current()

    def _on_modified(self, _event=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self.updating or self.busy or not self.drafts:
            return
        self._stash_current()
        if tuple(self.drafts) != self.validated_texts:
            self._mark_pending()

    def _mark_pending(self):
        was_ready = self.plans is not None
        self.plans = None
        self.status_var.set("待校验：编辑内容尚未确认，请点击“校验编辑”。")
        self.on_ready_changed(False)
        if was_ready:
            self.log("命令编辑待校验，已禁用开始注册；尚未连接 OLT")

    def _show_validated(self):
        edited = sum(plan.edited for plan in self.plans or ())
        count = sum(len(plan.commands) for plan in self.plans or ())
        self.status_var.set(f"校验通过：{len(self.plans or ())} 个目标，{count} 条命令，{edited} 个目标已编辑。")
        self.on_ready_changed(bool(self.plans))

    def validate(self):
        if self.busy or not self.requests:
            return False
        self._stash_current()
        plans = []
        for index, (request, text) in enumerate(zip(self.requests, self.drafts)):
            try:
                plans.append(self.service.prepare(request, text))
            except ValueError as exc:
                self.plans = None
                self.current_index = index
                self.target_combo.current(index)
                self._display_current()
                if isinstance(exc, OnuCommandEditError):
                    line = max(1, exc.line_number)
                    self.text.tag_remove("sel", "1.0", "end")
                    self.text.tag_add("sel", f"{line}.0", f"{line}.end")
                    self.text.see(f"{line}.0")
                    self.text.focus_set()
                self.status_var.set(f"校验失败：{exc}")
                self.on_ready_changed(False)
                self.log(f"命令编辑校验失败：{exc}；未连接 OLT")
                return False
        self.plans = tuple(plans)
        self.validated_texts = tuple(self.drafts)
        self._show_validated()
        self.log(f"命令编辑{self.status_var.get()}；尚未连接 OLT")
        return True

    def capture_plans(self):
        """确认前同步读 Text，防止尚未处理的 Modified 事件绕过校验。"""
        self._stash_current()
        if tuple(self.drafts) != self.validated_texts or not self.plans:
            self._mark_pending()
            raise ValueError("编辑内容尚未校验，请先点击“校验编辑”；参数或目标变化后需重新生成预览")
        return self.plans

    def restore(self):
        if self.busy or not self.drafts:
            return
        self._stash_current()
        index = self.current_index
        if self.drafts[index] != self.originals[index] and not messagebox.askyesno(
            "恢复生成命令", "将放弃当前目标的命令编辑，恢复本次生成的内容。是否继续？", parent=self.parent,
        ):
            self.log("操作员取消恢复生成命令，保留当前编辑")
            return
        self.drafts[index] = self.originals[index]
        self._display_current()
        self._mark_pending()
        self.log("已恢复当前目标的生成命令；其它目标编辑保留")
        self.validate()

    def set_busy(self, busy):
        self.busy = bool(busy)
        active = bool(self.requests) and not self.busy
        self.target_combo.configure(state="readonly" if active else "disabled")
        self.text.configure(state="normal" if active else "disabled")
        for button in (self.validate_button, self.restore_button):
            button.configure(state="normal" if active else "disabled")

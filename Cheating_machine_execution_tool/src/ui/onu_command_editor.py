"""ONU 确认页的批量只读预览；保留原组件入口供主窗口调用。"""
from __future__ import annotations

from tkinter import StringVar, Text, ttk

from src.services.onu_command_edit_service import OnuCommandEditService


def command_plan_summary(plan) -> str:
    request = plan.request
    services = "、".join(
        f"{item.service_id}/{item.vlan}" if item.vlan == item.effective_network_vlan
        else f"{item.service_id}/ONU VLAN{item.vlan} ↔ 网络 VLAN{item.effective_network_vlan}"
        for item in request.services
    )
    return (
        f"SN {request.onu.serial_number} / {request.onu.pon_interface} / ONU ID {request.onu_id}："
        f"生成命令，类型模板 {request.onu_type}，"
        f"T-CONT {request.tcont_id}/{request.tcont_profile}，ServiceID/VLAN {services}"
    )


class OnuCommandEditor:
    """兼容既有类名；确认页不再收集或执行可编辑文本。"""

    def __init__(self, parent, *, on_ready_changed, log, height=8):
        self.parent = parent
        self.on_ready_changed = on_ready_changed
        self.log = log
        self.service = OnuCommandEditService()
        self.requests = ()
        self.plans = None
        self.busy = False
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        ttk.Label(
            self.frame,
            text="命令预览只读，可选择并复制；需要修改时请返回“2. 配置业务”，然后重新生成预览。",
            wraplength=880,
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.text = Text(
            self.frame, height=height, font=("Consolas", 10), wrap="none", state="disabled",
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.write_note_var = StringVar(master=parent)
        ttk.Label(self.frame, textvariable=self.write_note_var, wraplength=880).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0),
        )

    def load_requests(self, requests, *, write_note=""):
        requests = tuple(requests)
        plans = tuple(self.service.build_default(request) for request in requests)
        self.requests = requests
        self.plans = plans or None
        self.write_note_var.set(write_note)
        self._display_current()
        self.set_busy(False)
        self.on_ready_changed(bool(plans))

    def clear(self):
        self.requests = ()
        self.plans = None
        self.write_note_var.set("")
        self._display_current()
        self.set_busy(False)
        self.on_ready_changed(False)

    def _preview_text(self):
        if not self.plans:
            return ""
        if len(self.plans) == 1:
            return "\n".join(self.plans[0].commands)
        return "\n\n".join(
            f"# {index}. SN {plan.request.onu.serial_number} / "
            f"{plan.request.onu.pon_interface} / ONU ID {plan.request.onu_id}\n"
            + "\n".join(plan.commands)
            for index, plan in enumerate(self.plans, 1)
        )

    def _display_current(self):
        self.text.configure(state="normal")
        try:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", self._preview_text())
        finally:
            self.text.configure(state="disabled")

    def capture_plans(self):
        """执行只使用生成的不可变计划；展示被意外改写时拒绝确认。"""
        if not self.plans:
            raise ValueError("命令预览已失效，请重新生成命令预览")
        expected = self._preview_text()
        if self.text.get("1.0", "end-1c") != expected:
            self.clear()
            self.log("只读命令预览与生成快照不一致，已拒绝执行；未连接 OLT")
            raise ValueError("命令预览与生成快照不一致，请重新生成命令预览")
        return self.plans

    def set_busy(self, busy):
        self.busy = bool(busy)
        self.text.configure(state="disabled")

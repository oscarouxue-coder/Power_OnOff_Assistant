"""自动监控设置窗口；仅收集策略输入，不拥有诊断任务。"""
from dataclasses import asdict
import tkinter as tk
from tkinter import messagebox, ttk

from src.models.ai_diagnostics import DebugTriggerPolicy
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class AiMonitorWindow:
    def __init__(self, owner):
        self.owner, self.service = owner, owner.service
        self.window = None
        policy = self.service.store.setting("trigger_policy", {})
        self.enabled = tk.BooleanVar(owner.window, value=False)
        self.threshold = tk.StringVar(owner.window, value=str(policy.get("threshold", 3)))
        self.cooldown = tk.StringVar(owner.window, value=str(policy.get("cooldown", 60)))
        self.deep = tk.BooleanVar(owner.window, value=policy.get("deep_enabled", True))
        self.channels = tk.StringVar(owner.window)
        self.keywords = tk.StringVar(owner.window, value=";".join(policy.get("keywords", [])))
        self.codes = tk.StringVar(owner.window, value=";".join(policy.get("error_codes", [])))
        self.features = {code: tk.BooleanVar(owner.window, value=code in policy.get(
            "features", ["power", "telnet", "wifi", "ping"])) for code in ("power", "telnet", "wifi", "ping")}
        self.status = tk.StringVar(owner.window)
        self.update_status()

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            return
        self.window = tk.Toplevel(self.owner.window)
        self.window.title("自动监控")
        self.window.geometry("820x520")
        self.window.minsize(760, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)
        parent = ttk.Frame(self.window, padding=12)
        parent.pack(fill="both", expand=True)
        tk.Checkbutton(parent, text="启用本次自动监控", variable=self.enabled,
                       command=self.changed).pack(anchor="w")
        ttk.Label(parent, text="监控范围独立于当前聊天目标；关闭监控取消诊断任务，原测试及聊天继续。",
                  wraplength=720).pack(anchor="w", pady=8)
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="连续异常次数").pack(side="left")
        ttk.Spinbox(row, from_=1, to=20, width=5, textvariable=self.threshold).pack(side="left", padx=6)
        ttk.Label(row, text="冷却（秒）").pack(side="left", padx=(12, 0))
        ttk.Spinbox(row, from_=1, to=3600, width=6, textvariable=self.cooldown).pack(side="left", padx=6)
        tk.Checkbutton(row, text="允许按条件深入采集", variable=self.deep).pack(side="left", padx=12)
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=6)
        for code, title in (("power", "开关机"), ("telnet", "Telnet"), ("wifi", "WiFi"), ("ping", "Ping")):
            tk.Checkbutton(row, text=title, variable=self.features[code]).pack(side="left")
        for title, variable in (("监控通道（逗号分隔，空为全部当前目标）", self.channels),
                                ("额外触发关键词（分号分隔）", self.keywords), ("错误码（分号分隔）", self.codes)):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=6)
            ttk.Label(row, text=title).pack(anchor="w")
            ttk.Entry(row, textvariable=variable).pack(fill="x", pady=(3, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="应用监控设置", command=self.apply).pack(side="left")
        ttk.Label(parent, textvariable=self.status, wraplength=720).pack(anchor="w")
        apply_module_theme(self.window, self.owner.background_color)
        center_toplevel_on_parent(self.window, self.owner.window)

    def policy(self):
        channels = tuple(int(x.strip()) for x in self.channels.get().split(",") if x.strip()) or tuple(
            t.channel for t in self.owner.targets)
        threshold, cooldown = int(self.threshold.get()), int(self.cooldown.get())
        if not 1 <= threshold <= 20 or not 1 <= cooldown <= 3600 or not set(channels) <= {
                t.channel for t in self.owner.targets}:
            raise ValueError("请检查通道范围、异常阈值（1–20）和冷却（1–3600秒）")
        return DebugTriggerPolicy(channels, tuple(k for k, v in self.features.items() if v.get()), threshold,
            cooldown, tuple(x.strip() for x in self.keywords.get().split(";") if x.strip()),
            tuple(x.strip() for x in self.codes.get().split(";") if x.strip()), self.deep.get())

    def apply(self):
        # 已启用时重新确认范围后应用；取消或输入失败不关闭原有监控。
        self.changed(applying=True)

    def changed(self, applying=False):
        was_enabled = bool(self.service.trigger.enabled)
        try:
            if self.enabled.get() or applying:
                self.owner.refresh_targets()
                policy = self.policy()
                if not policy.channels or self.service.profile is None:
                    raise ValueError("请先保存接入配置并选择目标通道")
                if self.enabled.get() and not messagebox.askyesno(
                        "启用本次AI诊断", "本次允许对所选目标登录查询，并按触发条件进行临时Debug采集。\n"
                        "始终禁止AI重启、上下电、升级和恢复出厂。\n监控通道：" +
                        ", ".join(map(str, policy.channels)) + "\n真实诊断信息（含材料中的账号、密码）将发送至：" +
                        self.service.profile.provider + " / " + self.service.profile.base_url,
                        parent=self.window or self.owner.window):
                    self.enabled.set(was_enabled)
                    return
                self.service.store.set_setting("trigger_policy", asdict(policy))
                self.service.configure(self.service.profile, self.owner.targets, policy)
                self.service.emit("[AI监控] 已应用设置：通道=" + ",".join(map(str, policy.channels)) +
                                  f"，连续异常={policy.threshold}，冷却={policy.cooldown}秒")
            if not applying or self.enabled.get():
                self.service.enable_monitor(self.enabled.get())
        except Exception as exc:
            self.enabled.set(was_enabled)
            self.owner._error(exc)
        finally:
            self.update_status()

    def update_status(self):
        self.owner.monitor_status.set("自动监控：" + ("已开启" if self.enabled.get() else "关闭"))
        policy = self.service.trigger.policy
        self.status.set("生效范围：" + (", ".join(map(str, policy.channels)) or "尚未应用") +
                        "；修改后点击“应用监控设置”。关闭窗口保留当前监控状态。")

"""自动监控设置窗口；仅收集策略输入，不拥有诊断任务。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.models.ai_diagnostics import DebugTriggerPolicy
from src.models.ai_permissions import FULL, PERMISSION_LABELS, normalize_permission
from src.ui.ai_action_approval import AiActionApproval
from src.ui.module_theme import apply_module_theme
from src.ui.ai_monitor_status import monitor_presentation
from src.ui.window_paint import center_toplevel_on_parent


class AiMonitorWindow:
    def __init__(self, owner):
        self.owner, self.service = owner, owner.service
        self.window = None
        policy = self.service.store.setting("trigger_policy", {})
        self._legacy_deep_enabled = policy.get("deep_enabled", True)
        self.enabled = tk.BooleanVar(owner.window, value=False)
        self.threshold = tk.StringVar(owner.window, value=str(policy.get("threshold", 3)))
        self.cooldown = tk.StringVar(owner.window, value=str(policy.get("cooldown", 60)))
        self.permission = tk.StringVar(owner.window, value=PERMISSION_LABELS[normalize_permission(self.service.monitor.mode)])
        self.permission_dirty = False
        self.permission_choice = None
        self.approval = None
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
        self.permission_choice = ttk.Combobox(row, width=9, state="readonly", textvariable=self.permission,
                                             values=list(PERMISSION_LABELS.values()))
        self.permission_choice.pack(side="left", padx=12)
        self.permission_choice.bind("<<ComboboxSelected>>", self._permission_selected)
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
        self.status_label = ttk.Label(parent, textvariable=self.status, wraplength=720)
        self.status_label.pack(anchor="w")
        self.status_label.bind("<Button-1>", self.open_pending)
        self.approval = AiActionApproval(parent, self.service.monitor, self.owner.background_color, show_button=False)
        apply_module_theme(self.window, self.owner.background_color)
        center_toplevel_on_parent(self.window, self.owner.window)
        self.update_status()

    def _permission_selected(self, event=None):
        self.permission_dirty = True

    def open_pending(self, event=None):
        try:
            action = self.service.monitor.pending()
            if action is None:
                return
            self.open()
            self.approval.show(action["session_id"])
            self.approval.open()
        except Exception as exc:
            self.owner._error(exc)

    def policy(self):
        channels = tuple(int(x.strip()) for x in self.channels.get().split(",") if x.strip()) or tuple(
            t.channel for t in self.owner.targets)
        threshold, cooldown = int(self.threshold.get()), int(self.cooldown.get())
        if not 1 <= threshold <= 20 or not 1 <= cooldown <= 3600 or not set(channels) <= {
                t.channel for t in self.owner.targets}:
            raise ValueError("请检查通道范围、异常阈值（1–20）和冷却（1–3600秒）")
        return DebugTriggerPolicy(channels, tuple(k for k, v in self.features.items() if v.get()), threshold,
            cooldown, tuple(x.strip() for x in self.keywords.get().split(";") if x.strip()),
            tuple(x.strip() for x in self.codes.get().split(";") if x.strip()), self._legacy_deep_enabled)

    def apply(self):
        # 已启用时重新确认范围后应用；取消或输入失败不关闭原有监控。
        self.changed(applying=True)

    def changed(self, applying=False):
        was_enabled = bool(self.service.trigger.enabled)
        try:
            if self.enabled.get() or applying:
                snapshot = self.service.monitor_status()
                if snapshot.queued + snapshot.running + snapshot.cleaning:
                    raise ValueError("监控任务仍在排队、运行、待批准或清理，请关闭监控并等待结束后应用设置")
                self.owner.refresh_targets()
                policy = self.policy()
                mode = next(key for key, label in PERMISSION_LABELS.items() if label == self.permission.get())
                if not policy.channels or self.service.profile is None:
                    raise ValueError("请先保存接入配置并选择目标通道")
                targets = [t for t in self.owner.targets if t.channel in policy.channels]
                scope = "\n".join(f"通道{t.channel} | {t.vlan} | {t.port} | {t.bind_ip} → {t.host}:{t.telnet_port}"
                                  for t in targets)
                details = ("允许AI诊断本次异常、执行必要修复并验证恢复。\n权限：" + PERMISSION_LABELS[mode] +
                           "\n监控目标：\n" + scope + "\n模型：" + self.service.profile.model + "\n")
                if mode == FULL:
                    details += ("\n本次监控允许本机PowerShell、文件读取/覆盖及当前目标样机命令；包括登录、升级、重启、"
                                "恢复出厂、供电控制、系统/网络/驱动修改及删除，不再逐项确认，也不调用独立模型风险审查。\n"
                                "继承当前Windows账号权限，不自动提权；目标和占用保护、停止保留，通用命令不是系统沙箱。\n"
                                "关闭监控、主动停止任务、重启程序、目标/模型/批次变化后授权失效。"
                                "保留权限选择；重新启用时校验授权，旧操作不重放。\n")
                else:
                    details += "首次登录和危险或不明操作须具体批准；请求批准模式下通用操作也逐项确认。\n"
                if self.enabled.get() and not messagebox.askyesno(
                        "授权本次监控完全访问" if mode == FULL else "启用本次AI诊断", details +
                        "\n真实诊断信息（含材料中的账号、密码）将发送至：" +
                        self.service.profile.provider + " / " + self.service.profile.base_url,
                        parent=self.window or self.owner.window, default="no"):
                    self.enabled.set(was_enabled)
                    return
                self.service.monitor.apply(self.service.profile, self.owner.targets, policy, mode,
                                           self.enabled.get(), confirmed=self.enabled.get())
            else:
                self.service.enable_monitor(False)
        except Exception as exc:
            self.enabled.set(was_enabled)
            self.owner._error(exc)
        finally:
            self.permission_dirty = False
            self.update_status()

    def update_status(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.service.monitor_status()
        text, color = monitor_presentation(snapshot)
        if self.enabled.get() != snapshot.enabled:
            self.enabled.set(snapshot.enabled)
        if self.owner.monitor_status.get() != text:
            self.owner.monitor_status.set(text)
        label = getattr(self.owner, "monitor_status_label", None)
        if label is not None and label.winfo_exists():
            label.configure(foreground=color, cursor="hand2" if snapshot.waiting_approval else "")
            label.bind("<Button-1>", self.open_pending)
        busy = snapshot.queued + snapshot.running + snapshot.cleaning
        mode = normalize_permission(self.service.monitor.mode)
        if not self.permission_dirty:
            self.permission.set(PERMISSION_LABELS[mode])
        if self.permission_choice is not None:
            self.permission_choice.configure(state="disabled" if busy else "readonly")
        policy = self.service.trigger.policy
        self.status.set("生效范围：" + (", ".join(map(str, policy.channels)) or "尚未应用") +
                        "；权限：" + PERMISSION_LABELS[mode] +
                        ("；有待批准操作，点击此处核对并处理。" if snapshot.waiting_approval else
                         "；修改后点击“应用监控设置”。关闭窗口保留当前监控状态。"))
        if hasattr(self, "status_label"):
            self.status_label.configure(cursor="hand2" if snapshot.waiting_approval else "")
        if self.approval is not None and self.approval.identifier:
            self.approval.show(self.approval.identifier)

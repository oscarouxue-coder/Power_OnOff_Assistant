"""飞书接入设置；界面仅收集输入、显示动态状态并调用service。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.module_theme import apply_module_theme


class FeishuSetupWindow:
    def __init__(self, parent, config_store, runtime_provider, notifications, emit, *, embedded=False):
        self.config_store, self.runtime_provider = config_store, runtime_provider
        self.notifications, self.emit = notifications, emit
        self.saved = config_store.load()
        self.window = tk.Frame(parent) if embedded else tk.Toplevel(parent)
        self.dialog_parent = self.window.winfo_toplevel()
        self._paused, self._disposed = False, False
        if not embedded:
            self.window.title("飞书 AI 接入")
            self.window.geometry("800x380")
            self.window.minsize(660, 350)
        self.window.columnconfigure(1, weight=1)
        self.variables = {}
        for row, (key, title) in enumerate((("app_id", "App ID"), ("app_secret", "App Secret（留空保留）"))):
            self.variables[key] = tk.StringVar(self.window, self.saved[key] if key != "app_secret" else "")
            ttk.Label(self.window, text=title).grid(row=row, column=0, sticky="w", padx=12, pady=10)
            ttk.Entry(self.window, textvariable=self.variables[key], show="*" if key == "app_secret" else "").grid(
                row=row, column=1, sticky="ew", padx=12, pady=10)
        self.switches = {}
        for row, (kind, label) in enumerate((("group", "启用指定群 AI 排障"),
                                           ("p2p", "启用单聊 AI 排障"), ("push", "启用飞书测试通知")), 2):
            variable = tk.BooleanVar(self.window, self.saved[kind + "_enabled"])
            self.switches[kind] = variable
            tk.Checkbutton(self.window, text=label, variable=variable,
                           command=lambda k=kind: self.toggle(k)).grid(row=row, column=0, columnspan=2,
                                                                     sticky="w", padx=12, pady=5)
        toolbar = ttk.Frame(self.window)
        toolbar.grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=12)
        ttk.Button(toolbar, text="保存应用配置", command=self.save).pack(side="left", padx=(0, 8))
        self.bind_button = ttk.Button(toolbar, text="绑定群…", command=self.bind)
        self.bind_button.pack(side="left", padx=(0, 8))
        self.menu = tk.Menu(self.window, tearoff=False)
        self.menu.add_command(label="发送飞书测试消息", command=self.test)
        self.menu.add_command(label="取消当前群绑定申请", command=self.cancel_binding)
        more = ttk.Button(toolbar, text="更多操作 ▾")
        more.configure(command=lambda: self.menu.tk_popup(more.winfo_rootx(), more.winfo_rooty() + more.winfo_height()))
        more.pack(side="left")
        self.status = tk.StringVar(self.window)
        ttk.Label(self.window, textvariable=self.status, wraplength=750, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        self.code, self.after_id = "", None
        def bind_menu(widget):
            widget.bind("<Button-3>", lambda event: self.menu.tk_popup(event.x_root, event.y_root), add="+")
            for child in widget.winfo_children():
                if not isinstance(child, tk.Menu):
                    bind_menu(child)
        if embedded:
            bind_menu(self.window)
        else:
            self.window.bind("<Button-3>", lambda event: self.menu.tk_popup(event.x_root, event.y_root))
        if not embedded:
            self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._on_destroy, add="+")
        apply_module_theme(self.dialog_parent)
        self.poll()

    def runtime(self):
        runtime = self.runtime_provider()
        if runtime is None:
            raise ValueError("请先保存应用配置并重启程序，再绑定群或启用飞书排障")
        return runtime

    def error(self, exc):
        self.status.set(str(exc))
        messagebox.showerror("飞书接入未完成", str(exc), parent=self.dialog_parent)

    def save(self):
        try:
            runtime = self.runtime_provider()
            if self.notifications.busy:
                raise ValueError("请等待飞书通知发送结束后再保存凭据")
            if runtime and (runtime.config["enabled"] or runtime.config["push_enabled"]
                            or (runtime.transport and not runtime.transport.idle)
                            or any(s in runtime.conversation.running for s in runtime.sessions)):
                raise ValueError("请先关闭飞书排障和通知、取消绑定申请，并等待后台清理后再保存")
            config = self.config_store.configure({key: var.get() for key, var in self.variables.items()})
            if runtime:
                runtime.update_config(config)
            self.saved = config
            self.variables["app_secret"].set("")
            self.emit("[飞书接入] 应用凭据已加密保存；项目AI数据已初始化，原钉钉配置保持")
            self.status.set("已保存，可绑定群或启用单聊" if runtime else "已保存。请重启程序后绑定群或启用单聊。")
            messagebox.showinfo("配置已保存", self.status.get(), parent=self.dialog_parent)
        except Exception as exc:
            self.error(exc)

    def bind(self):
        try:
            runtime = self.runtime()
            candidate = runtime.snapshot()["candidate"]
            if candidate:
                if messagebox.askyesno("确认飞书群绑定", "仅接受以下群的@消息，并将测试通知发送到此群：\n"
                        + candidate["name"] + "\n群ID：" + candidate["group"] + "\n是否绑定？",
                        parent=self.dialog_parent, default="no"):
                    runtime.confirm_binding(candidate)
                    self.code = ""
                    self.saved = self.config_store.load()
            else:
                self.code = runtime.begin_binding()
                self.status.set("请在目标群@本应用机器人发送：绑定 " + self.code + "（五分钟内有效）")
        except Exception as exc:
            self.error(exc)

    def cancel_binding(self):
        try:
            self.runtime().cancel_binding()
            self.code = ""
        except Exception as exc:
            self.error(exc)

    def toggle(self, kind):
        try:
            runtime = self.runtime()
            enabled = self.switches[kind].get()
            if enabled and kind != "push":
                audience = ("已绑定群的所有成员可通过@本机器人" if kind == "group" else
                            "本飞书自建应用可用范围内的所有企业成员均可通过单聊")
                destination = "已绑定群" if kind == "group" else "发起人的原单聊"
                if not messagebox.askyesno("启用飞书AI排障", audience + "调用当前项目AI排障工具。\n\n"
                        "默认完全访问；当前目标内的本机命令、文件读写及设备操作跳过独立审查和常规逐项批准。"
                        "工具可访问本机命令、文件和当前项目目标，本机操作可能影响其它项目。\n"
                        "包括登录、升级、重启、恢复出厂及系统/网络修改；占用保护和停止保留。"
                        "回复会发送到" + destination + "；本地可降低会话权限。\n是否启用？",
                        parent=self.dialog_parent, default="no"):
                    self.switches[kind].set(False)
                    return
            if kind == "push":
                if not enabled:
                    self.notifications.set_auto_blocked(True)
                runtime.set_push_enabled(enabled)
                if enabled:
                    self.notifications.set_auto_blocked(False)
            else:
                runtime.enable(kind, enabled)
            self.saved = self.config_store.load()
        except Exception as exc:
            runtime = self.runtime_provider()
            self.switches[kind].set(bool(runtime.config[kind + "_enabled"]) if runtime else False)
            self.error(exc)

    def test(self):
        if self.notifications.busy:
            self.status.set("飞书通知正在发送，请等待后再试发")
            return
        if not self.notifications.enqueue({}, test=True):
            self.status.set(self.notifications.last_result)

    def poll(self):
        self.after_id = None
        if self._paused or self._disposed:
            return
        runtime = self.runtime_provider()
        if runtime:
            snapshot = runtime.snapshot()
            for kind, variable in self.switches.items():
                variable.set(runtime.config[kind + "_enabled"])
            self.bind_button.configure(text="确认绑定" if snapshot["candidate"] else "绑定群…")
            if snapshot["candidate"]:
                self.status.set("已收到绑定申请：" + snapshot["candidate"]["name"] + "；点击确认绑定")
            elif self.code and snapshot["binding"]:
                self.status.set("请在目标群@本机器人发送：绑定 " + self.code + "；" + snapshot["status"])
            elif self.code:
                self.code = ""
                self.status.set("群绑定已结束或过期，请重新绑定")
            else:
                self.status.set(snapshot["status"] + " | " + (runtime.config["group_name"] or "尚未绑定群")
                                + "\n" + self.notifications.last_result)
        elif not self.status.get():
            self.status.set("保存应用配置后重启程序；使用企业自建应用机器人")
        self.after_id = self.window.after(300, self.poll)

    def suspend(self, cancel_binding=False):
        self._paused = True
        if self.after_id:
            try:
                self.window.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if not cancel_binding:
            return
        runtime = self.runtime_provider()
        if self.code and runtime:
            try:
                runtime.cancel_binding()
                self.emit("[飞书接入] 界面关闭，已取消未完成群绑定")
            except Exception:
                self.emit("[飞书接入] 取消群绑定失败，请重新打开远程管理检查状态（凭据省略）")
        self.code = ""

    def resume(self):
        if not self._disposed and self.after_id is None:
            self._paused = False
            self.poll()

    def _on_destroy(self, event):
        if event.widget is self.window:
            self.suspend()
            self._disposed = True

    def close(self):
        self.suspend(cancel_binding=True)
        self.window.destroy()

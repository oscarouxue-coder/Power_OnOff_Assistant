"""钉钉应用/群绑定界面；网络接收与排障全部由service持有。"""
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.module_theme import apply_module_theme


class DingTalkSetupWindow:
    def __init__(self, parent, config_store, runtime_provider, push_values, emit, push_config_path, on_saved=lambda config: None):
        self.config_store, self.runtime_provider, self.emit = config_store, runtime_provider, emit
        self.push_config_path, self.on_saved = push_config_path, on_saved
        self.window = tk.Toplevel(parent)
        self.window.title("钉钉 AI 接入")
        self.window.geometry("840x430")
        self.window.minsize(680, 420)
        self.window.columnconfigure(1, weight=1)
        try:
            self.saved = config_store.load()
        except ValueError as exc:
            messagebox.showerror("配置读取失败", str(exc), parent=self.window)
            self.window.destroy()
            return
        values = dict(self.saved)
        values["client_secret"] = ""
        if not values["webhook"]:
            values["webhook"], values["secret"] = push_values.get("webhook", ""), push_values.get("secret", "")
        self.variables = {}
        for row, (key, title) in enumerate((("client_id", "Client ID / AppKey"),
                ("client_secret", "Client Secret（留空保留）"), ("robot_code", "Robot Code"),
                ("webhook", "应用机器人群 Webhook"), ("secret", "群 Webhook 加签密钥"))):
            self.variables[key] = tk.StringVar(self.window, values[key])
            ttk.Label(self.window, text=title).grid(row=row, column=0, sticky="w", padx=12, pady=8)
            ttk.Entry(self.window, textvariable=self.variables[key],
                      show="*" if key in ("client_secret", "secret") else "").grid(
                          row=row, column=1, sticky="ew", padx=12, pady=8)
        self.enabled = tk.BooleanVar(self.window, self.saved["enabled"])
        tk.Checkbutton(self.window, text="启用指定群 AI 排障", variable=self.enabled,
                       command=self.toggle).grid(row=5, column=0, columnspan=2, sticky="w", padx=12)
        toolbar = ttk.Frame(self.window)
        toolbar.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        for text, action in (("保存应用配置", self.save), ("开始绑定群", self.bind),
                             ("确认绑定", self.confirm), ("取消绑定", self.cancel_binding)):
            ttk.Button(toolbar, text=text, command=action).pack(side="left", padx=(0, 8))
        self.status = tk.StringVar(self.window)
        self.status_label = ttk.Label(self.window, textvariable=self.status, wraplength=780)
        self.status_label.grid(row=7, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        self.code = ""
        self.candidate = None
        self.after_id = None
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        apply_module_theme(self.window)
        self.poll()

    def runtime(self):
        runtime = self.runtime_provider()
        if runtime is None:
            raise ValueError("请保存应用配置并重启程序，再打开本窗口绑定群")
        return runtime

    def error(self, exc):
        self.status.set(str(exc))
        messagebox.showerror("钉钉接入未完成", str(exc), parent=self.window)

    def save(self):
        try:
            runtime = self.runtime_provider()
            if runtime and (runtime.config["enabled"] or (runtime.transport and not runtime.transport.idle)
                            or any(s in runtime.conversation.running for s in runtime.sessions)):
                raise ValueError("请先停用接入，等待连接和排障清理后再保存")
            values = {key: var.get().strip() for key, var in self.variables.items()}
            config = self.config_store.configure(values, self.push_config_path)
            self.saved = config
            self.variables["client_secret"].set("")
            if runtime:
                runtime.config = config
            self.on_saved(config)
            self.emit("[钉钉接入] 应用配置已加密保存；项目AI数据已初始化，旧库保留")
            self.status.set("已保存，可开始绑定群" if runtime else "已保存。请重启程序后绑定群；旧AI历史保持只读可查。")
            messagebox.showinfo("配置已保存", self.status.get(), parent=self.window)
        except Exception as exc:
            self.error(exc)

    def bind(self):
        try:
            self.code = self.runtime().begin_binding()
            self.candidate = None
            self.status.set("请在目标群@本应用机器人发送：绑定 " + self.code + "（五分钟内有效）")
        except Exception as exc:
            self.error(exc)

    def confirm(self):
        try:
            runtime = self.runtime()
            candidate = runtime.snapshot()["candidate"]
            if not candidate:
                raise ValueError("尚未收到当前绑定码，请先在目标群发送绑定消息")
            if not messagebox.askyesno("确认群绑定", f"项目仅接受以下群消息：\n{candidate['name']}\n"
                    f"群ID：{candidate['group']}\n是否绑定？", parent=self.window, default="no"):
                return
            runtime.confirm_binding(candidate)
            self.saved = self.config_store.load()
            self.code = ""
            self.status.set("已绑定：" + self.saved["group_name"] + "；勾选启用后生效")
        except Exception as exc:
            self.error(exc)

    def cancel_binding(self):
        try:
            runtime = self.runtime()
            if runtime.config["enabled"]:
                raise ValueError("接入已启用，请使用上方勾选框停用；此按钮只取消正在进行的绑定")
            runtime.enable(False)
            self.code = ""
            self.status.set("已取消绑定，等待连接结束")
        except Exception as exc:
            self.error(exc)

    def toggle(self):
        try:
            runtime = self.runtime()
            enabled = self.enabled.get()
            if enabled and not messagebox.askyesno("启用群内AI排障",
                    f"群：{runtime.config.get('group_name', '')}\n\n"
                    "允许本群所有成员通过@该应用机器人调用当前项目AI排障工具，"
                    "默认帮我批准，普通操作独立审查后自动执行；危险或不明操作须具体批准。\n\n"
                    "工具可访问本机命令、文件及当前项目目标；本机系统操作可能影响同机其它项目。"
                    "排障回复会发送到本群。本地可为会话授权完全访问。\n是否启用？",
                    parent=self.window, default="no"):
                self.enabled.set(False)
                return
            runtime.enable(enabled)
            self.saved = self.config_store.load()
        except Exception as exc:
            self.enabled.set(False)
            self.error(exc)

    def poll(self):
        runtime = self.runtime_provider()
        if runtime:
            snapshot = runtime.snapshot()
            self.enabled.set(snapshot["enabled"])
            self.candidate = snapshot["candidate"]
            if self.candidate:
                self.status.set("已收到绑定申请：" + self.candidate["name"] + "；请点击确认绑定")
            elif self.code and snapshot["binding"]:
                self.status.set("请在目标群@机器人发送：绑定 " + self.code + "；" + snapshot["status"])
            elif self.code:
                self.status.set("绑定码已过期，请重新开始绑定")
            else:
                self.status.set(snapshot["status"] + " | " + (runtime.config.get("group_name") or "尚未绑定群"))
        self.after_id = self.window.after(300, self.poll)

    def close(self):
        runtime = self.runtime_provider()
        if self.code and runtime is not None and not runtime.config["enabled"]:
            try:
                runtime.enable(False)
            except Exception:
                self.emit("[钉钉接入] 取消绑定时设置保存失败，本进程已停止绑定")
        if self.after_id:
            self.window.after_cancel(self.after_id)
        self.window.destroy()

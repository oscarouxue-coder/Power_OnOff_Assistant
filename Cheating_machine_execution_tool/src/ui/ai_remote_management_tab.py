"""AI助手的远程管理子页签；表单按需装配，后台服务由主程序持有。"""
from tkinter import ttk

from src.ui.module_theme import apply_module_theme


class RemoteManagementTab:
    def __init__(self, parent, dingtalk_factory, feishu_factory, emit):
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.book = ttk.Notebook(self.frame)
        self.book.pack(fill="both", expand=True)
        self.emit = emit
        self.factories = {"dingtalk": dingtalk_factory, "feishu": feishu_factory}
        self.panels, self.hosts, self.errors = {}, {}, {}
        for platform, title in (("dingtalk", "钉钉"), ("feishu", "飞书")):
            host = ttk.Frame(self.book, padding=10)
            self.book.add(host, text=title)
            self.hosts[platform] = host
        self.book.select(self.hosts["dingtalk"])

    def activate(self):
        for platform, factory in self.factories.items():
            if platform not in self.panels:
                host = self.hosts[platform]
                for widget in host.winfo_children():
                    widget.destroy()
                try:
                    panel = factory(host)
                    if not panel.window.winfo_exists():
                        raise RuntimeError("接入表单未创建")
                    panel.window.pack(fill="both", expand=True)
                    self.panels[platform] = panel
                    self.errors.pop(platform, None)
                except Exception:
                    for widget in host.winfo_children():
                        widget.destroy()
                    title = "钉钉" if platform == "dingtalk" else "飞书"
                    error = title + "接入配置加载失败，请检查配置和访问权限；重新进入远程管理可重试。"
                    self.errors[platform] = error
                    ttk.Label(host, text=error, wraplength=780).pack(anchor="w")
                    self.emit("[" + title + "接入] 配置表单加载失败（凭据省略）")
                    continue
            self.panels[platform].resume()
        apply_module_theme(self.frame.winfo_toplevel())

    def select_platform(self, platform):
        self.book.select(self.hosts[platform])

    def suspend(self, cancel_binding=False):
        for platform, panel in self.panels.items():
            try:
                panel.suspend(cancel_binding=cancel_binding)
            except Exception:
                title = "钉钉" if platform == "dingtalk" else "飞书"
                self.emit("[" + title + "接入] 界面收尾失败，请检查远程管理状态（凭据省略）")

    def dispose(self):
        self.suspend()

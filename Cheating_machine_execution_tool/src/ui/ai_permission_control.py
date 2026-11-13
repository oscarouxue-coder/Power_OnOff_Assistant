"""权限选择与完全访问确认；不执行工具、不判断操作风险。"""
from tkinter import ttk, messagebox

from src.models.ai_permissions import AUTO, FULL, PERMISSION_LABELS


class AiPermissionControl(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent)
        self.service = service
        self.identifier = ""
        self.choice = ttk.Combobox(self, width=9, state="disabled", values=list(PERMISSION_LABELS.values()))
        self.choice.set(PERMISSION_LABELS[AUTO])
        self.choice.pack(side="left")
        self.choice.bind("<<ComboboxSelected>>", self.select)

    def show(self, identifier=""):
        self.identifier = identifier
        mode = self.service.permissions.status(identifier)["mode"] if identifier else AUTO
        self.choice.set(PERMISSION_LABELS[mode])
        busy = identifier in self.service.running or identifier in self.service.executors
        self.choice.configure(state="readonly" if identifier and not busy else "disabled")

    def select(self, event=None):
        identifier = self.identifier
        if not identifier:
            return
        try:
            mode = next(key for key, label in PERMISSION_LABELS.items() if label == self.choice.get())
            confirmed = False
            if mode == FULL:
                target = self.service.store.chat(identifier)["target"]
                confirmed = messagebox.askyesno(
                    "启用本会话完全访问", "允许AI在本会话用户目标范围内自动执行本机命令、读取/覆盖文件及当前样机命令。\n\n"
                    f"当前目标：通道{target['channel']} | {target['vlan']} | {target['port']}\n"
                    f"{target['bind_ip']} → {target['host']}:{target['telnet_port']}\n\n"
                    "包括设备登录、升级、重启、恢复出厂、供电控制、系统重启、网络/驱动修改及删除操作，"
                    "不再逐项确认，也不调用独立模型风险审查。\n\n"
                    "使用当前Windows账号权限；通用命令不构成系统沙箱。目标/占用保护及停止保留；"
                    "停止、重启或目标/模型/批次变化后授权失效。是否授权？",
                    parent=self.winfo_toplevel(), default="no")
                if not confirmed:
                    self.service.emit(f"会话{identifier[:8]}取消完全访问授权，保留原权限")
                    return
            self.service.permissions.select(identifier, mode, confirmed=confirmed)
        except Exception as exc:
            self.service.emit("权限切换失败：" + self.service.redactor.text(str(exc)))
            messagebox.showerror("权限切换未完成", str(exc), parent=self.winfo_toplevel())
        finally:
            self.show(identifier)

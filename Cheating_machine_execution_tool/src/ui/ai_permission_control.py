"""权限选择与完全访问确认；不执行工具、不判断操作风险。"""
from tkinter import ttk, messagebox

from src.models.ai_permissions import FULL, PERMISSION_LABELS
from src.models.ai_session_scope import target_label, session_scope


class AiPermissionControl(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent)
        self.service = service
        self.identifier = ""
        self.choice = ttk.Combobox(self, width=9, state="disabled", values=list(PERMISSION_LABELS.values()))
        self.choice.set(PERMISSION_LABELS[FULL])
        self.choice.pack(side="left")
        self.choice.bind("<<ComboboxSelected>>", self.select)

    def show(self, identifier=""):
        self.identifier = identifier
        permission = self.service.permissions.status(identifier) if identifier else {}
        mode = permission.get("preferred_mode", permission.get("mode", FULL))
        self.choice.set(PERMISSION_LABELS[mode])
        busy = identifier in self.service.running or identifier in self.service.executors
        general = identifier and session_scope(self.service.store.chat(identifier)) == "general"
        self.choice.configure(state="readonly" if identifier and not busy and not general else "disabled")

    def select(self, event=None):
        identifier = self.identifier
        if not identifier:
            return
        try:
            mode = next(key for key, label in PERMISSION_LABELS.items() if label == self.choice.get())
            confirmed = False
            if mode == FULL:
                session = self.service.store.chat(identifier)
                target = session["target"]
                description = (f"通道{target['channel']} | {target['vlan']} | {target['port']}\n"
                    f"{target['bind_ip']} → {target['host']}:{target['telnet_port']}" if target else target_label(session))
                batch = session_scope(session) == "batch"
                if batch:
                    description = "\n".join(f"通道{t['channel']} | {t['vlan']} | {t['port']} | {t['bind_ip']} → {t['host']}" for t in session["batch_targets"])
                capability = "本机命令、读取/覆盖文件及所列样机命令" if target or batch else "本机命令及读取/覆盖本机文件"
                risks = ("设备登录、升级、重启、恢复出厂、供电控制、系统重启、网络/驱动修改及删除操作"
                         if target or batch else "系统重启、网络/驱动修改及删除操作")
                source = session.get("source") or {}
                origin = (f"钉钉会话发起人：{source.get('nickname', '')}\n"
                          "授权后该成员在本会话内发来的目标将按完全访问执行，回复会发送到已绑定群。\n\n"
                          if source.get("kind") == "dingtalk" else "")
                if source.get("kind") == "feishu":
                    destination = "发起人的原单聊" if source.get("chat_type") == "p2p" else "已绑定群"
                    origin = (f"飞书会话发起人：{source.get('sender', '')}\n"
                              f"聊天ID：{source.get('group', '')}\n"
                              f"授权后该成员在本会话内发来的目标将按完全访问执行，回复发送到{destination}。\n\n")
                lifecycle = ("停止、重启或目标/模型/批次变化后授权失效。" +
                             ("需重新选择并确认。" if source.get("kind") == "dingtalk" else
                              "保留权限选择；有效会话初始化或再次发送问题时重新校验授权，旧操作不重放。"))
                confirmed = messagebox.askyesno(
                    "启用本会话完全访问", f"允许AI在本会话用户目标范围内自动执行{capability}。\n\n"
                    + origin + f"当前目标：{description}\n\n" +
                    f"包括{risks}，"
                    "不再逐项确认，也不调用独立模型风险审查。\n\n"
                    "使用当前Windows账号权限；通用命令不构成系统沙箱。目标/占用保护及停止保留；"
                    + lifecycle + "是否授权？",
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

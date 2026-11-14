"""AI记录列表的主题、详情、按需重命名交互。"""
from collections import Counter
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from src.services.ai_record_titles import clean_title
from src.ui.module_theme import apply_module_theme


def record_time(value, compact=False):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.strftime("%m-%d %H:%M:%S" if compact else "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def short_title(value):
    title = clean_title(value)
    return title if len(title) <= 24 else title[:24] + "…"


def record_labels(entries):
    labels = []
    for entry in entries:
        channel = f"通道{entry['channel']}"
        if entry.get("cycle"):
            channel += f"·第{entry['cycle']}轮"
        labels.append(f"{short_title(entry['title'])} | {channel} | "
                      f"{record_time(entry['created'], compact=True)} | {entry['status']}")
    counts = Counter(labels)
    result = []
    for entry, label in zip(entries, labels):
        if counts[label] > 1:
            # 相同前缀的ID逐步扩展，保证碰撞记录仍有不同的可见标识。
            peers = [item['id'] for item, text in zip(entries, labels) if text == label]
            length = 8
            while length < len(entry['id']) and any(
                    peer != entry['id'] and peer[:length] == entry['id'][:length] for peer in peers):
                length += 1
            label += f" | {entry['id'][:length]}"
        result.append(label)
    return result


def record_detail(entry):
    if not entry:
        return ""
    return (f"{entry['title']}\n通道：{entry['channel']}\n"
            f"时间：{record_time(entry['created'])}\n"
            f"模型：{entry['provider']} / {entry['model']}\n"
            f"状态：{entry['status']}\nID：{entry['id']}")


class RecordTitleDialog(simpledialog.Dialog):
    def __init__(self, parent, initial, background):
        self.initial, self.background = initial, background
        super().__init__(parent, title="重命名")

    def body(self, master):
        ttk.Label(master, text="名称").pack(side="left", padx=(0, 6))
        self.entry = ttk.Entry(master, width=48)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.insert(0, self.initial)
        self.entry.selection_range(0, "end")
        return self.entry

    def buttonbox(self):
        box = ttk.Frame(self)
        box.pack(fill="x", padx=10, pady=10)
        ttk.Button(box, text="保存", command=self.ok).pack(side="left", padx=5)
        ttk.Button(box, text="取消", command=self.cancel).pack(side="left", padx=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        apply_module_theme(self, self.background)

    def validate(self):
        if not 1 <= len(clean_title(self.entry.get())) <= 80:
            messagebox.showerror("名称无效", "名称须为1至80字", parent=self)
            return False
        return True

    def apply(self):
        self.result = clean_title(self.entry.get())


class AiRecordActions:
    """下拉框操作当前记录；表格仅单选可重命名，悬停按所在行显示详情。"""
    def __init__(self, widget, kind, titles, current, changed, background, hovered=None):
        self.widget, self.kind, self.titles = widget, kind, titles
        self.current, self.changed, self.background = current, changed, background
        self.hovered = hovered
        self.job = self.popup = None
        self.hover_id = None
        self.menu = tk.Menu(widget, tearoff=False)
        noun = "会话" if kind == "chat" else "报告"
        self.menu.add_command(label="重命名当前" + noun, command=self.rename)
        widget.bind("<Button-3>", self.show_menu, add="+")
        widget.bind("<Motion>", self.schedule, add="+")
        for event in ("<Leave>", "<ButtonPress-1>", "<Unmap>", "<Destroy>", "<<ComboboxSelected>>"):
            widget.bind(event, self.hide, add="+")

    def show_menu(self, event):
        self.hide()
        self.menu.entryconfigure(0, state="normal" if self.current() else "disabled")
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def rename(self):
        self.hide()
        entry = self.current()
        if not entry:
            return
        # 模态窗口期间允许后台刷新，保存时仍使用打开弹窗时的记录ID。
        identifier = entry["id"]
        dialog = RecordTitleDialog(self.widget.winfo_toplevel(), entry["title"], self.background)
        if dialog.result is None:
            self.titles.emit(f"[AI列表] {self.kind} {identifier} 已取消重命名")
            return
        try:
            self.titles.rename(self.kind, identifier, dialog.result)
        except Exception as exc:
            messagebox.showerror("重命名未完成", str(exc), parent=self.widget.winfo_toplevel())
            return
        self.changed()

    def schedule(self, event):
        entry = self.hovered(event) if self.hovered else self.current()
        identifier = entry["id"] if entry else None
        if identifier == self.hover_id:
            return
        self.hide()
        self.hover_id = identifier
        if entry:
            self.job = self.widget.after(500, lambda: self.show_detail(identifier))

    def show_detail(self, identifier):
        self.job = None
        if not self.widget.winfo_viewable():
            return
        entry = self.current()
        if self.hovered:
            # 表格悬停的行可与选中行不同，重新按当前指针位置读取。
            event = type("Pointer", (), {"y": self.widget.winfo_pointery() - self.widget.winfo_rooty()})()
            entry = self.hovered(event)
        if not entry or entry["id"] != identifier:
            return
        self.popup = tk.Toplevel(self.widget)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        tk.Label(self.popup, text=record_detail(entry), justify="left", wraplength=560,
                 background="#fffbe6", foreground="#17202a", relief="solid", borderwidth=1,
                 padx=8, pady=6).pack()
        self.popup.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth() - self.popup.winfo_reqwidth())
        y = min(self.widget.winfo_rooty() + self.widget.winfo_height() + 4,
                self.widget.winfo_screenheight() - self.popup.winfo_reqheight())
        self.popup.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.popup.deiconify()

    def hide(self, _event=None):
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.popup is not None:
            popup, self.popup = self.popup, None
            popup.destroy()
        self.hover_id = None

"""On-demand local operator view for independent jobs and reviewed templates."""
import getpass
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

from src.models.capabilities import CapabilityAuthority
from src.ui.module_theme import apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent


class CapabilityManagement:
    def __init__(self, panel):
        self.panel = panel
        self.runtime = panel.service.capabilities.service
        self.window, self.poll_id = None, None

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.refresh()
            if self.poll_id is None:
                self.poll_id = self.window.after(500, self.poll)
            return
        self.window = tk.Toplevel(self.panel.owner.window)
        self.window.title("业务任务与受控扩展")
        self.window.geometry("920x520")
        self.window.minsize(700, 400)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        book = ttk.Notebook(self.window)
        book.pack(fill="both", expand=True, padx=12, pady=12)
        jobs, templates = ttk.Frame(book), ttk.Frame(book)
        book.add(jobs, text="业务任务")
        book.add(templates, text="受控扩展")
        self.jobs = ttk.Treeview(jobs, columns=("capability", "state", "stage"), show="tree headings")
        self.jobs.heading("#0", text="任务编号（右键操作）")
        for key, name in (("capability", "业务能力"), ("state", "状态"), ("stage", "当前阶段")):
            self.jobs.heading(key, text=name)
        self.jobs.pack(fill="both", expand=True)
        self.job_menu = tk.Menu(self.jobs, tearoff=False)
        for name, action in (("查看详情", self.detail), ("请求安全停止", self.cancel), ("核实未知结果…", self.reconcile)):
            self.job_menu.add_command(label=name, command=action)
        self.jobs.bind("<Button-3>", lambda event: self.popup(self.jobs, self.job_menu, event))
        self.templates = ttk.Treeview(templates, columns=("version", "enabled", "uses"), show="tree headings")
        self.templates.heading("#0", text="模板（右键导入/启停）")
        for key, name in (("version", "版本"), ("enabled", "启用"), ("uses", "已执行次数")):
            self.templates.heading(key, text=name)
        self.templates.pack(fill="both", expand=True)
        self.template_menu = tk.Menu(self.templates, tearoff=False)
        for name, action in (("导入并审阅模板…", self.import_template), ("停用/撤销", lambda: self.enable(False)),
                             ("恢复已审阅模板", lambda: self.enable(True))):
            self.template_menu.add_command(label=name, command=action)
        self.templates.bind("<Button-3>", lambda event: self.popup(self.templates, self.template_menu, event))
        ttk.Button(self.window, text="刷新", command=self.refresh).pack(anchor="e", padx=12, pady=(0, 10))
        apply_module_theme(self.window)
        center_toplevel_on_parent(self.window, self.panel.owner.window)
        self.refresh()
        self.poll_id = self.window.after(500, self.poll)

    @staticmethod
    def popup(tree, menu, event):
        item = tree.identify_row(event.y)
        if item:
            tree.selection_set(item)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def refresh(self):
        selection = self.jobs.selection()
        with self.runtime.jobs.lock:
            rows = list(self.runtime.jobs.db.execute("SELECT id,capability,state,stage FROM jobs ORDER BY created DESC LIMIT 200"))
        self.jobs.delete(*self.jobs.get_children())
        for identifier, capability, state, stage in rows:
            self.jobs.insert("", "end", iid=identifier, text=identifier[:12], values=(capability, state, stage))
        if selection and self.jobs.exists(selection[0]):
            self.jobs.selection_set(selection[0])
        selected = self.templates.selection()
        self.templates.delete(*self.templates.get_children())
        for row in self.runtime.extensions.list():
            self.templates.insert("", "end", iid=row["id"], text=row["id"], values=(row["version"], "是" if row["enabled"] else "否", row["uses"]))
        if selected and self.templates.exists(selected[0]):
            self.templates.selection_set(selected[0])

    def poll(self):
        self.poll_id = None
        if self.window is not None and self.window.winfo_exists() and self.window.state() != "withdrawn":
            self.refresh()
            self.poll_id = self.window.after(500, self.poll)

    def authority(self, identifier):
        with self.runtime.jobs.lock:
            row = self.runtime.jobs._row(identifier)
        # This method is called by actual local controls, never by model tools.
        return CapabilityAuthority(row["principal"], "local-operator", "local-control", tuple(
            row["request"].get("arguments", {}).get("channel_ids", ())), source="gui", mode="full_access", grant_id="local-control", approved=True)

    def selected_job(self):
        selected = self.jobs.selection()
        if not selected:
            raise ValueError("请先选择任务")
        return selected[0]

    def detail(self):
        try:
            identifier = self.selected_job()
            value = self.runtime.jobs.status(identifier, self.authority(identifier))
            self.show_text("业务任务详情", json.dumps(value, ensure_ascii=False, indent=2))
        except Exception as exc:
            messagebox.showerror("查看失败", str(exc), parent=self.window)

    def cancel(self):
        try:
            identifier = self.selected_job()
            self.runtime.jobs.cancel(identifier, self.authority(identifier))
            self.refresh()
        except Exception as exc:
            messagebox.showerror("停止失败", str(exc), parent=self.window)

    def reconcile(self):
        try:
            identifier = self.selected_job()
            status = self.runtime.jobs.status(identifier, self.authority(identifier))
            if status["state"] != "unknown":
                raise ValueError("只处理已现场核实的未知任务")
            outcome = simpledialog.askstring("核实结果", "输入 succeeded / failed / not_executed；仅填写已经现场核实的结果", parent=self.window)
            if outcome is None:
                return
            evidence = simpledialog.askstring("核实依据", "填写现场核实依据（保留原记录，不自动重试）", parent=self.window)
            if evidence and messagebox.askyesno("确认现场核实", f"任务 {identifier[:12]}\n结果：{outcome}\n依据：{evidence}\n\n仅解除未知状态，不执行设备操作。", parent=self.window):
                self.runtime.jobs.resolve_unknown(identifier, self.authority(identifier), outcome, evidence)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("核实失败", str(exc), parent=self.window)

    def show_text(self, title, text):
        window = tk.Toplevel(self.window)
        window.title(title)
        window.geometry("820x540")
        view = ScrolledText(window, wrap="word", font=("Consolas", 10))
        view.pack(fill="both", expand=True, padx=12, pady=12)
        view.insert("1.0", text)
        view.configure(state="disabled")
        apply_module_theme(window)
        center_toplevel_on_parent(window, self.window)
        return window

    def import_template(self):
        path = filedialog.askopenfilename(parent=self.window, title="导入待审阅模板", filetypes=[("JSON模板", "*.json")])
        if not path:
            return
        try:
            from pathlib import Path
            if Path(path).stat().st_size > 1024 * 1024:
                raise ValueError("模板超过1MiB")
            manifest = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            review = self.runtime.extensions.review(manifest)
            window = self.show_text("本地审阅受控扩展", json.dumps(review, ensure_ascii=False, indent=2))
            accepted = tk.BooleanVar(window, value=False)
            tk.Checkbutton(window, text="已审阅执行内容、代码哈希、参数约束和资源范围", variable=accepted).pack(anchor="w", padx=12)
            def approve():
                if not accepted.get():
                    return
                try:
                    self.runtime.extensions.approve(manifest, review["reviewed_sha256"], getpass.getuser())
                    window.destroy()
                    self.refresh()
                except Exception as exc:
                    messagebox.showerror("登记失败", str(exc), parent=window)
            ttk.Button(window, text="批准并登记此版本", command=approve).pack(anchor="e", padx=12, pady=10)
            apply_module_theme(window)
        except Exception as exc:
            messagebox.showerror("模板无效", str(exc), parent=self.window)

    def enable(self, enabled):
        try:
            selected = self.templates.selection()
            if not selected:
                return
            self.runtime.extensions.set_enabled(selected[0], enabled, getpass.getuser())
            self.refresh()
        except Exception as exc:
            messagebox.showerror("模板状态未更改", str(exc), parent=self.window)

    def hide(self):
        if self.poll_id is not None:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        if self.window is not None:
            self.window.withdraw()

    def close(self):
        self.hide()
        if self.window is not None:
            self.window.destroy()
            self.window = None

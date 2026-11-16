"""Local forms for instance pairing and an application-owned gateway. No device I/O."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.services.remote_gateway_store import validate_pairing_scopes
from src.services.remote_instance_management import read_startup
from src.ui.module_theme import apply_module_theme


class MultiInstanceTab:
    def __init__(self, parent, service):
        self.service = service
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.book = ttk.Notebook(self.frame)
        self.book.pack(fill="both", expand=True)
        self.instance_page = ttk.Frame(self.book, padding=8)
        self.gateway_page = ttk.Frame(self.book, padding=8)
        self.book.add(self.instance_page, text="本机实例")
        self.book.add(self.gateway_page, text="统一网关")
        self.events = queue.Queue()
        self.busy = self.active = self.disposed = False
        self.after_id = None
        self.revision = 0
        self.scopes = []
        self.rows = {}
        self.code_expires = 0
        self.buttons = []
        self.instance_status = tk.StringVar(self.frame)
        self.gateway_status = tk.StringVar(self.frame)
        self.result = tk.StringVar(self.frame)
        self.variables = {}
        self.gateway_vars = {}
        self.channels = {}
        self.capability_ids = []
        self.loaded = False
        self.loaded_slot = None
        self._instance_form()
        self._gateway_form()
        ttk.Label(self.frame, textvariable=self.result, wraplength=960).pack(fill="x", pady=(4, 0))
        apply_module_theme(self.frame.winfo_toplevel())

    def _entry(self, parent, row, label, variable, *, show=None, width=62):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        entry = ttk.Entry(parent, textvariable=variable, width=width, **({"show": show} if show else {}))
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        return entry

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=(0, 6))
        self.buttons.append(button)
        return button

    def _changed(self, *_):
        self.revision += 1

    def _instance_form(self):
        page = self.instance_page
        ttk.Label(page, textvariable=self.instance_status, wraplength=960).pack(fill="x", pady=(0, 6))
        form = ttk.Frame(page)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for key, default in (("mode", "普通直接接入"), ("slot", "1"), ("name", ""), ("url", ""), ("code", "")):
            self.variables[key] = tk.StringVar(page, default)
            self.variables[key].trace_add("write", self._changed)
        ttk.Label(form, text="下次启动模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.variables["mode"], values=("普通直接接入", "统一网关接入"), state="readonly").grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="实例槽位").grid(row=1, column=0, sticky="w")
        slot = ttk.Combobox(form, textvariable=self.variables["slot"], values=tuple(map(str, range(1, 65))), state="readonly", width=8)
        self.slot_choice = slot
        slot.grid(row=1, column=1, sticky="w", pady=3)
        slot.bind("<<ComboboxSelected>>", self._load_slot)
        self._entry(form, 2, "配对名称", self.variables["name"])
        self._entry(form, 3, "网关地址", self.variables["url"])
        self._entry(form, 4, "一次性配对码", self.variables["code"], show="•")
        self.variables["vpn"] = tk.BooleanVar(page, False)
        self.variables["vpn"].trace_add("write", self._changed)
        tk.Checkbutton(form, text="已使用受保护的VPN网络", variable=self.variables["vpn"]).grid(row=5, column=1, sticky="w")
        self.scope_summary = tk.StringVar(page)
        scope_area = ttk.Frame(page)
        scope_area.pack(fill="x", pady=5)
        self.scope_text = tk.Text(scope_area, height=3, wrap="word", state="disabled")
        self.scope_text.pack(side="left", fill="x", expand=True)
        scroll = ttk.Scrollbar(scope_area, command=self.scope_text.yview)
        scroll.pack(side="right", fill="y")
        self.scope_text.configure(yscrollcommand=scroll.set)
        self.scope_summary.trace_add("write", self._scope_text_changed)
        channels = ttk.LabelFrame(page, text="允许通道", padding=4)
        channels.pack(fill="x")
        for number in range(1, 17):
            variable = self.channels[number] = tk.BooleanVar(page, False)
            variable.trace_add("write", self._changed)
            tk.Checkbutton(channels, text=str(number), variable=variable).grid(row=(number - 1) // 8, column=(number - 1) % 8, sticky="w", padx=12)
        capabilities = ttk.LabelFrame(page, text="允许业务能力", padding=4)
        capabilities.pack(fill="both", expand=True, pady=6)
        self.capabilities = tk.Listbox(capabilities, selectmode="multiple", exportselection=False, height=7)
        self.capabilities.pack(side="left", fill="both", expand=True)
        self.capabilities.bind("<<ListboxSelect>>", self._changed)
        scrollbar = ttk.Scrollbar(capabilities, command=self.capabilities.yview)
        scrollbar.pack(side="right", fill="y")
        self.capabilities.configure(yscrollcommand=scrollbar.set)
        actions = ttk.Frame(page)
        actions.pack(fill="x")
        self._button(actions, "配对", self._pair)
        self._button(actions, "保存启动配置", self._save_instance)
        self._button(actions, "重新读取槽位", self._load_slot)

    def _gateway_form(self):
        page = self.gateway_page
        ttk.Label(page, textvariable=self.gateway_status).pack(fill="x", pady=(0, 4))
        form = ttk.Frame(page)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for key, default in (("host", "127.0.0.1"), ("port", "18761"), ("certificate", ""), ("private_key", "")):
            self.gateway_vars[key] = tk.StringVar(page, default)
        self._entry(form, 0, "监听地址", self.gateway_vars["host"])
        self._entry(form, 1, "端口", self.gateway_vars["port"])
        for row, key, label in ((2, "certificate", "WSS证书"), (3, "private_key", "私钥文件")):
            self._entry(form, row, label, self.gateway_vars[key])
            ttk.Button(form, text="选择…", command=lambda k=key: self._choose_file(k)).grid(row=row, column=2, padx=(5, 0))
        options = ttk.Frame(page)
        options.pack(fill="x", pady=3)
        for key, label in (("vpn", "已使用受保护的VPN网络"), ("dingtalk", "钉钉"), ("feishu", "飞书")):
            self.gateway_vars[key] = tk.BooleanVar(page, False)
            tk.Checkbutton(options, text=label, variable=self.gateway_vars[key]).pack(side="left", padx=(0, 8))
        scopes = ttk.LabelFrame(page, text="配对允许范围", padding=4)
        scopes.pack(fill="x", pady=3)
        self.scope_list = ttk.Treeview(scopes, columns=("platform", "chat", "members"), show="headings", height=2, selectmode="browse")
        for key, title in (("platform", "平台 / 会话类型"), ("chat", "聊天ID"), ("members", "允许成员ID")):
            self.scope_list.heading(key, text=title)
            self.scope_list.column(key, width=150 if key == "platform" else 300, stretch=True)
        self.scope_list.pack(fill="x")
        scope_actions = ttk.Frame(scopes)
        scope_actions.pack(fill="x", pady=(3, 0))
        self._button(scope_actions, "添加范围", self._add_scope)
        self._button(scope_actions, "编辑范围", self._edit_scope)
        self._button(scope_actions, "移除范围", self._remove_scope)
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=4)
        self._button(actions, "保存网关配置", self._save_gateway)
        self._button(actions, "启动网关", self._start_gateway)
        self._button(actions, "停止网关", self._stop_gateway)
        self._button(actions, "生成配对码", self._create_code)
        self.pairing_code = tk.StringVar(page)
        code_row = ttk.Frame(page)
        code_row.pack(fill="x")
        ttk.Label(code_row, text="配对码").pack(side="left", padx=(0, 8))
        ttk.Entry(code_row, textvariable=self.pairing_code, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(code_row, text="复制", command=self._copy_code).pack(side="left", padx=(5, 0))
        instances = ttk.LabelFrame(page, text="已登记实例", padding=4)
        instances.pack(fill="both", expand=True, pady=(5, 0))
        self.instance_list = ttk.Treeview(instances, columns=("name", "id", "state", "seen"), show="headings", height=4, selectmode="browse")
        for key, title, width in (("name", "名称", 230), ("id", "实例ID", 180), ("state", "状态", 90), ("seen", "最后心跳", 150)):
            self.instance_list.heading(key, text=title)
            self.instance_list.column(key, width=width, stretch=True)
        self.instance_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(instances, command=self.instance_list.yview)
        scroll.pack(side="right", fill="y")
        self.instance_list.configure(yscrollcommand=scroll.set)
        self.menu = tk.Menu(self.frame, tearoff=False)
        self.menu.add_command(label="查看详情", command=self._details)
        self.menu.add_command(label="复制实例ID", command=self._copy_id)
        self.menu.add_separator()
        self.menu.add_command(label="撤销实例接入…", command=self._revoke)
        self.instance_list.bind("<Button-3>", self._popup)
        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(3, 0))
        self._button(bottom, "刷新实例", self._refresh_instances)
        menu_button = ttk.Menubutton(bottom, text="操作", menu=self.menu)
        menu_button.pack(side="left")

    def _scope_text_changed(self, *_):
        self.scope_text.configure(state="normal")
        self.scope_text.delete("1.0", "end")
        self.scope_text.insert("1.0", self.scope_summary.get())
        self.scope_text.configure(state="disabled")

    def _choose_file(self, key):
        path = filedialog.askopenfilename(parent=self.frame.winfo_toplevel(), title="选择证书或私钥文件")
        if path:
            self.gateway_vars[key].set(path)

    def _submit(self, operation, done=None, message="操作完成"):
        if self.busy or self.disposed or self.service.closing:
            return
        self.busy = True
        self.slot_choice.configure(state="disabled")
        for button in self.buttons:
            button.configure(state="disabled")
        self.result.set("处理中…")
        def work():
            try:
                value = operation()
                self.events.put((True, value, done, message))
            except Exception as exc:
                # No arbitrary transport/platform exception text reaches UI/logs.
                safe = str(exc) if type(exc) is ValueError and str(exc).startswith(("请", "该", "所选", "网关", "配对", "程序", "平台", "实例", "统一", "多实例", "WSS", "跨网", "非TLS", "必须", "全群", "不支持")) else "操作失败，请检查配置、实例占用和访问权限（凭据省略）"
                self.service.emit("[多实例管理] " + safe)
                self.events.put((False, safe, None, ""))
        threading.Thread(target=work, name="multi-instance-form", daemon=True).start()

    def _load_slot(self, _event=None):
        number, revision = int(self.variables["slot"].get()), self.revision
        if self.busy:
            return
        self.loaded_slot = None
        self._submit(lambda: self.service.slot(number),
                     lambda value: self._show_slot(value) if revision == self.revision else None,
                     "槽位已读取")

    def _show_slot(self, value):
        self.loaded_slot = value["slot"]
        for key in ("url", "name", "vpn"):
            self.variables[key].set(value[key])
        self.variables["code"].set("")
        for number, variable in self.channels.items():
            variable.set(number in value["channel_ids"])
        self.capabilities.selection_clear(0, "end")
        for index, identifier in enumerate(self.capability_ids):
            if identifier in value["capability_ids"]:
                self.capabilities.selection_set(index)
        scope_text = "；".join(s["platform"] + "/" + s["chat"] + " 成员：" + ",".join(s["members"]) for s in value["scopes"])
        self.scope_summary.set(("实例ID：" + value["instance_id"] + ("（待下次启动生效）" if value["pending"] else "") + "\n" + scope_text) if value["paired"] else "该槽位尚未配对")

    def _pair(self):
        values = {key: v.get() for key, v in self.variables.items()}
        if int(values["slot"]) != self.loaded_slot:
            self.result.set("请先重新读取所选槽位，核对实例范围后再配对")
            return
        revision = self.revision
        self._submit(lambda: self.service.pair(int(values["slot"]), values["url"].strip(), values["name"].strip(), values["vpn"], values["code"]),
                     lambda value: self._pair_done(value, revision, values["code"]), "配对成功；请核对允许范围并保存启动配置")

    def _pair_done(self, value, revision, submitted_code):
        if revision == self.revision:
            self._show_slot(value)
        elif self.variables["code"].get() == submitted_code:
            self.variables["code"].set("")

    def _save_instance(self):
        mode = "gateway" if self.variables["mode"].get() == "统一网关接入" else "direct"
        number, url, vpn = int(self.variables["slot"].get()), self.variables["url"].get().strip(), self.variables["vpn"].get()
        if mode == "gateway" and number != self.loaded_slot:
            self.result.set("请先重新读取所选槽位，核对实例范围后再保存")
            return
        channels = [n for n, v in self.channels.items() if v.get()]
        capabilities = [self.capability_ids[i] for i in self.capabilities.curselection()]
        if mode == "gateway" and not messagebox.askyesno("确认本地接入范围", "槽位：" + str(number) + "\n通道：" + ",".join(map(str, channels)) +
                "\n能力：" + ",".join(capabilities) + "\n保存后下次启动生效；远程新会话仍需本地批准。", parent=self.frame.winfo_toplevel()):
            return
        self._submit(lambda: self.service.save_instance(mode, number, url, vpn, channels, capabilities), message="启动配置已保存，下次启动整个程序生效")

    def _scope_values(self):
        return dict(host=self.gateway_vars["host"].get().strip(), port=int(self.gateway_vars["port"].get()),
                    vpn=self.gateway_vars["vpn"].get(), certificate=self.gateway_vars["certificate"].get().strip(),
                    private_key=self.gateway_vars["private_key"].get().strip(),
                    platforms=[p for p in ("dingtalk", "feishu") if self.gateway_vars[p].get()])

    def _save_gateway(self):
        try:
            config = self._scope_values()
        except ValueError:
            self.result.set("端口须为1至65535的整数")
            return
        scopes = json.loads(json.dumps(self.scopes))
        self._submit(lambda: self.service.save_gateway(config, scopes), message="网关配置已保存，重新启动网关后生效")

    def _start_gateway(self):
        self._submit(self.service.start_gateway, message="已按保存配置启动网关")

    def _stop_gateway(self):
        if messagebox.askyesno("停止统一网关", "停止接收和转发消息？远端已准入业务继续执行。", parent=self.frame.winfo_toplevel()):
            self._submit(self.service.stop_gateway, message="网关已停止")

    def _create_code(self):
        self._submit(self.service.create_pairing, self._show_code, "已按保存范围生成配对码，5分钟有效、单次使用")

    def _show_code(self, code):
        self.pairing_code.set(code)
        self.code_expires = time.monotonic() + 300

    def _copy_code(self):
        if self.pairing_code.get() and time.monotonic() < self.code_expires:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(self.pairing_code.get())

    def _add_scope(self):
        self._scope_editor()

    def _edit_scope(self):
        selected = self.scope_list.selection()
        if selected:
            self._scope_editor(int(selected[0]))

    def _scope_editor(self, index=None):
        if self.busy or self.disposed:
            return
        value = self.scopes[index] if index is not None else dict(platform="feishu", robot="", corp="", chat_type="group", chat="", members=[])
        dialog = tk.Toplevel(self.frame)
        dialog.title("配对允许范围")
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        form = ttk.Frame(dialog, padding=12)
        form.pack(fill="both", expand=True)
        variables = {key: tk.StringVar(dialog, ",".join(item) if key == "members" else item) for key, item in value.items()}
        for row, (key, label) in enumerate((("platform", "平台"), ("robot", "机器人ID"), ("corp", "企业ID"), ("chat_type", "会话类型"), ("chat", "聊天ID"), ("members", "成员ID（逗号分隔）"))):
            if key in ("platform", "chat_type"):
                ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
                ttk.Combobox(form, textvariable=variables[key], values=("dingtalk", "feishu") if key == "platform" else ("group", "p2p"), state="readonly").grid(row=row, column=1, sticky="ew")
            else:
                self._entry(form, row, label, variables[key], width=50)
        def fill():
            try:
                bound = self.service.bound_scope(variables["platform"].get())
                for key in ("robot", "corp", "chat"):
                    if not variables[key].get():
                        variables[key].set(bound[key])
            except Exception:
                messagebox.showerror("读取失败", "请先在远程管理配置并绑定机器人。", parent=dialog)
        def save():
            candidate = {key: variable.get().strip() for key, variable in variables.items()}
            candidate["members"] = [m.strip() for m in candidate["members"].replace("，", ",").split(",") if m.strip()]
            try:
                validate_pairing_scopes([candidate])
                if candidate["members"] == ["*"] and not messagebox.askyesno("确认全群范围", "允许此聊天中的所有成员配对调用？\n聊天ID：" + candidate["chat"], parent=dialog):
                    return
            except ValueError as exc:
                messagebox.showerror("范围无效", str(exc), parent=dialog)
                return
            if index is None:
                self.scopes.append(candidate)
            else:
                self.scopes[index] = candidate
            self._render_scopes()
            dialog.destroy()
        actions = ttk.Frame(form)
        actions.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="w")
        ttk.Button(actions, text="回填已有绑定", command=fill).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="确定", command=save).pack(side="left")
        apply_module_theme(dialog)

    def _remove_scope(self):
        selected = self.scope_list.selection()
        if selected and not self.busy:
            del self.scopes[int(selected[0])]
            self._render_scopes()

    def _render_scopes(self):
        self.scope_list.delete(*self.scope_list.get_children())
        for index, scope in enumerate(self.scopes):
            self.scope_list.insert("", "end", iid=str(index), values=(scope["platform"] + "/" + scope["chat_type"], scope["chat"], ",".join(scope["members"])))

    def _refresh_instances(self):
        self._submit(self.service.host.instances, self._render_instances, "实例列表已刷新")

    def _render_instances(self, rows):
        selected = self.instance_list.selection()
        self.rows = {row["instance_id"]: row for row in rows}
        self.instance_list.delete(*self.instance_list.get_children())
        for row in rows:
            seen = time.strftime("%m-%d %H:%M:%S", time.localtime(row["seen"])) if row["seen"] else "—"
            self.instance_list.insert("", "end", iid=row["instance_id"], values=(row["name"], row["instance_id"][:8], row["state"], seen))
        if selected and selected[0] in self.rows:
            self.instance_list.selection_set(selected[0])

    def _popup(self, event):
        row = self.instance_list.identify_row(event.y)
        if row:
            self.instance_list.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _selected(self):
        selected = self.instance_list.selection()
        return self.rows.get(selected[0]) if selected else None

    def _details(self):
        value = self._selected()
        if value:
            messagebox.showinfo("实例详情", json.dumps(value, ensure_ascii=False, indent=2), parent=self.frame.winfo_toplevel())

    def _copy_id(self):
        value = self._selected()
        if value:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(value["instance_id"])

    def _revoke(self):
        value = self._selected()
        if value and messagebox.askyesno("撤销实例接入", "撤销 " + value["name"] + "\n" + value["instance_id"] + " 的远程接入？\n保留原任务记录，不取消已准入业务。", parent=self.frame.winfo_toplevel()):
            identifier = value["instance_id"]
            self._submit(lambda: self.service.revoke(identifier), message="指定实例接入已撤销，请刷新列表")

    def activate(self):
        if self.disposed:
            return
        self.active = True
        if not self.loaded:
            try:
                try:
                    startup = read_startup(self.service.app_dir)
                except (ValueError, OSError):
                    startup = dict(mode="direct", slot=1)
                    self.result.set("启动配置读取失败；请重新选择接入模式并保存，当前接入不会自动切换")
                self.variables["mode"].set("统一网关接入" if startup["mode"] == "gateway" else "普通直接接入")
                self.variables["slot"].set(str(startup["slot"]))
                value = self.service.gateway_config()
                for key in ("host", "port", "vpn", "certificate", "private_key"):
                    self.gateway_vars[key].set(value[key])
                for platform in ("dingtalk", "feishu"):
                    self.gateway_vars[platform].set(platform in value["platforms"])
                self.scopes = value.get("scopes", [])
                self._render_scopes()
                rows = self.service.capabilities()
                self.capability_ids = [row["capability_id"] for row in rows]
                for row in rows:
                    self.capabilities.insert("end", row["capability_id"] + "  " + row["name"])
                self.loaded = True
                self._load_slot()
            except Exception:
                self.result.set("配置读取失败，请检查本机配置与访问权限")
        if self.after_id is None:
            self._poll()

    def _poll(self):
        self.after_id = None
        if self.disposed or not self.active:
            return
        while True:
            try:
                ok, value, callback, message = self.events.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            self.slot_choice.configure(state="readonly")
            for button in self.buttons:
                button.configure(state="normal")
            if ok:
                if callback is not None:
                    callback(value)
                self.result.set(message)
            else:
                self.result.set(value)
        state = self.service.status()
        self.instance_status.set("当前运行：" + ("统一接入启动失败，请保存配置后重新启动" if state["current_mode"] == "error" else "统一接入 / 槽位 " + str(state["current_slot"]) +
            " / " + ("已连接" if state["connected"] else "等待连接") + "\n启动ID：" + state["run_id"] if state["current_mode"] == "gateway" else "普通直接接入"))
        self.gateway_status.set("网关状态：" + state["gateway_state"])
        if self.code_expires and time.monotonic() >= self.code_expires:
            self.pairing_code.set("")
            self.code_expires = 0
        self.after_id = self.frame.after(250, self._poll)

    def suspend(self):
        self.active = False
        if self.after_id is not None:
            self.frame.after_cancel(self.after_id)
            self.after_id = None

    def dispose(self):
        self.suspend()
        self.disposed = True
        self.variables["code"].set("")
        self.pairing_code.set("")

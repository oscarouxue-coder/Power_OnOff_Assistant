"""AI 独立窗口；输入/显示和异步任务回调，设备执行位于service/core。"""
from __future__ import annotations

from dataclasses import replace
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import PROVIDERS, ProviderProfile, DebugTriggerPolicy
from src.services.ai_store import profile_fingerprint
from src.services.ai_context_budget import context_capacity, refresh_model_context
from src.ui.window_paint import center_toplevel_on_parent
from src.ui.module_theme import apply_module_theme, MODULE_BACKGROUND
from src.utils.ai_output import format_diagnostic_evidence


class AiDiagnosticsWindow:
    def __init__(self, master, service, targets_provider, background=MODULE_BACKGROUND, foreground="#17202a", conversation=None):
        self.master, self.service, self.targets_provider = master, service, targets_provider
        self.background_color, self.foreground_color = background, foreground
        self.window = None
        self.profile = ProviderProfile()
        self.selected_report = ""
        self.selected_case = None
        self.background = set()
        self.background_stops = set()
        self.events = queue.Queue()
        self.reports = {}
        self._poll_id = None
        self.new_profile_mode = True
        self.conversation = conversation
        self.chat_panel = None

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            return
        self.window = tk.Toplevel(self.master)
        self.window.configure(background=self.background_color)
        self.window.title("AI 诊断助手")
        self.window.geometry("1080x780")
        self.window.minsize(940, 660)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        book = ttk.Notebook(self.window)
        book.pack(fill="both", expand=True, padx=10, pady=10)
        connection, diagnosis, cases = (ttk.Frame(book, padding=10) for _ in range(3))
        for frame, title in ((connection, "模型接入"), (diagnosis, "诊断与监控"), (cases, "已确认案例")):
            book.add(frame, text=title)
        self._connection_tab(connection)
        self._diagnosis_tab(diagnosis)
        self._cases_tab(cases)
        if self.conversation is not None:
            from src.ui.ai_chat_panel import AiChatPanel
            chat = ttk.Frame(book, padding=10)
            book.insert(0, chat, text="对话排障")
            self.chat_panel = AiChatPanel(chat, self, self.conversation)
            book.select(chat)
        self._apply_theme()
        center_toplevel_on_parent(self.window, self.master)
        self._reload_profiles()
        self.refresh_targets()
        self._reload_reports()
        self._reload_cases()
        if self._poll_id is None:
            self._poll()

    def _apply_theme(self):
        """窗口局部样式与测试项配置共用配色，不修改全局主题。"""
        apply_module_theme(self.window, self.background_color)

    def _connection_tab(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 12))
        self.profile_choice = ttk.Combobox(toolbar, state="readonly", width=42)
        self.profile_choice.pack(side="left")
        self.profile_choice.bind("<<ComboboxSelected>>", self._choose_profile)
        for title, action in (("新增配置", self._new_profile), ("复制配置", self._copy_profile), ("删除配置", self._delete_profile)):
            ttk.Button(toolbar, text=title, command=action).pack(side="left", padx=5)
        form = ttk.Frame(parent)
        form.pack(fill="x")
        self.vars = {key: tk.StringVar(self.window) for key in
                     ("name", "provider", "base_url", "protocol", "model", "timeout", "max_output", "context_tokens", "key")}
        labels = (("name", "配置名称"), ("provider", "模型厂商"), ("base_url", "API 地址"),
                  ("protocol", "接口协议"), ("model", "模型 ID"), ("timeout", "请求超时（秒）"),
                  ("max_output", "最大输出 Token"), ("context_tokens", "上下文上限 Token（留空自动）"),
                  ("key", "API 密钥（留空保留）"))
        for index, (key, title) in enumerate(labels):
            ttk.Label(form, text=title).grid(row=index, column=0, sticky="w", pady=6)
            if key in ("provider", "protocol", "model"):
                values = tuple(PROVIDERS) if key == "provider" else (("chat_completions", "responses") if key == "protocol" else ())
                widget = ttk.Combobox(form, textvariable=self.vars[key], values=values,
                                      state="normal" if key == "model" else "readonly")
                if key == "provider":
                    widget.bind("<<ComboboxSelected>>", self._provider_changed)
                if key == "model":
                    self.model_choice = widget
            else:
                widget = ttk.Entry(form, textvariable=self.vars[key], show="*" if key == "key" else "")
            widget.grid(row=index, column=1, sticky="ew", padx=10, pady=6)
        form.columnconfigure(1, weight=1)
        self.context_status = tk.StringVar(self.window)
        ttk.Label(parent, textvariable=self.context_status, wraplength=900).pack(anchor="w", pady=(4, 0))
        for key in ("base_url", "model", "context_tokens"):
            self.vars[key].trace_add("write", self._update_context_status)
        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=14)
        for title, action in (("保存并选择", self._save), ("刷新模型", self._models), ("测试连接与工具能力", self._test)):
            ttk.Button(buttons, text=title, command=action).pack(side="left", padx=(0, 8))
        self.connection_status = tk.StringVar(self.window, value="未配置；密钥按Windows当前用户加密保存")
        ttk.Label(parent, textvariable=self.connection_status, wraplength=900).pack(anchor="w", pady=10)
        ttk.Label(parent, text="每次诊断固定使用启动时的厂商和模型；切换对下一次生效。\n模型列表不可用时可手填ID。不同区域的服务地址和密钥请按对应厂商账号配置。",
                  wraplength=900).pack(anchor="w", pady=10)

    def _diagnosis_tab(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text="本次目标").pack(side="left")
        self.channel_choice = ttk.Combobox(row, state="readonly", width=30)
        self.channel_choice.pack(side="left", padx=8)
        ttk.Button(row, text="刷新目标", command=self.refresh_targets).pack(side="left")
        self.monitor = tk.BooleanVar(self.window, value=False)
        tk.Checkbutton(row, text="启用本次自动监控", variable=self.monitor, command=self._monitor_changed).pack(side="left", padx=12)
        policy = self.service.store.setting("trigger_policy", {})
        options = ttk.Frame(parent)
        options.pack(fill="x", pady=8)
        self.threshold = tk.StringVar(self.window, value=str(policy.get("threshold", 3)))
        self.cooldown = tk.StringVar(self.window, value=str(policy.get("cooldown", 60)))
        ttk.Label(options, text="连续异常次数").pack(side="left")
        ttk.Spinbox(options, from_=1, to=20, width=5, textvariable=self.threshold).pack(side="left", padx=5)
        ttk.Label(options, text="冷却（秒）").pack(side="left", padx=(12, 0))
        ttk.Spinbox(options, from_=1, to=3600, width=6, textvariable=self.cooldown).pack(side="left", padx=5)
        self.deep = tk.BooleanVar(self.window, value=policy.get("deep_enabled", True))
        tk.Checkbutton(options, text="允许按条件深入采集", variable=self.deep).pack(side="left", padx=12)
        filters = ttk.Frame(parent)
        filters.pack(fill="x")
        self.features = {}
        for code, title in (("power", "开关机"), ("telnet", "Telnet"), ("wifi", "WiFi"), ("ping", "Ping")):
            variable = tk.BooleanVar(self.window, value=code in policy.get("features", ["power", "telnet", "wifi", "ping"]))
            self.features[code] = variable
            tk.Checkbutton(filters, text=title, variable=variable).pack(side="left")
        ttk.Label(filters, text="监控通道（逗号分隔，空为全部当前目标）").pack(side="left", padx=5)
        self.channel_filter = tk.StringVar(self.window)
        ttk.Entry(filters, textvariable=self.channel_filter, width=22).pack(side="left", fill="x", expand=True)
        self.keywords = tk.StringVar(self.window, value=";".join(policy.get("keywords", [])))
        self.codes = tk.StringVar(self.window, value=";".join(policy.get("error_codes", [])))
        for title, variable in (("额外触发关键词（分号分隔）", self.keywords), ("错误码（分号分隔）", self.codes)):
            frame = ttk.Frame(parent)
            frame.pack(fill="x", pady=3)
            ttk.Label(frame, text=title, width=30).pack(side="left")
            ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True)
        self.question = tk.Text(parent, height=3, wrap="word")
        self.question.pack(fill="x", pady=8)
        self.question.insert("1.0", "请分析当前目标的异常原因，并指出还需要哪些证据。")
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        for title, action in (("仅问答/分析已有材料", lambda: self._submit(False)),
                              ("诊断并按需采集", lambda: self._submit(True)),
                              ("停止AI采集", self._cancel), ("刷新报告", self._reload_reports)):
            ttk.Button(actions, text=title, command=action).pack(side="left", padx=(0, 7))
        self.report_choice = ttk.Combobox(parent, state="readonly")
        self.report_choice.pack(fill="x", pady=8)
        self.report_choice.bind("<<ComboboxSelected>>", self._choose_report)
        self.output = tk.Text(parent, wrap="word", state="disabled", height=12)
        self.output.pack(fill="both", expand=True)

    def _cases_tab(self, parent):
        self.case_list = ttk.Treeview(parent, columns=("id", "title", "active"), show="headings", height=6)
        for name, title, width in (("id", "编号", 60), ("title", "案例标题", 600), ("active", "参与检索", 100)):
            self.case_list.heading(name, text=title)
            self.case_list.column(name, width=width)
        self.case_list.pack(fill="x")
        self.case_list.bind("<<TreeviewSelect>>", self._choose_case)
        self.case_fields = {}
        for name, title in (("title", "标题"), ("cause", "已确认实际原因"), ("solution", "处理方法"),
                            ("verification", "复测结果"), ("scope", "适用范围/设备版本")):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=6)
            ttk.Label(row, text=title, width=22).pack(side="left")
            variable = tk.StringVar(self.window)
            self.case_fields[name] = variable
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=10)
        for title, action in (("从当前报告新建", self._new_case), ("人工确认/保存修订", self._confirm_case),
                              ("停用/启用", self._toggle_case), ("删除案例", self._delete_case)):
            ttk.Button(row, text=title, command=action).pack(side="left", padx=(0, 8))
        ttk.Label(parent, text="只有人工确认的实际原因和复测结果才参与后续检索。AI猜测、重试自行恢复不等于根因已确认。",
                  wraplength=900).pack(anchor="w", pady=10)

    def _error(self, exc):
        self.service.emit("[AI界面] 操作失败：" + str(exc))
        messagebox.showerror("AI 诊断助手", self.service.redactor.text(str(exc)), parent=self.window)

    def _fill_profile(self, profile):
        self.profile = profile
        for key, variable in self.vars.items():
            variable.set("" if key == "key" or (key == "context_tokens" and not profile.context_tokens)
                         else str(getattr(profile, key)))
        self.connection_status.set(profile.capability)
        self._update_context_status()

    def _update_context_status(self, *_args):
        try:
            raw = self.vars["context_tokens"].get().strip()
            capacity_value = int(raw) if raw else 0
            if raw and capacity_value <= 0:
                raise ValueError("上下文上限须为正整数，留空表示自动识别")
            profile = replace(self.profile, base_url=self.vars["base_url"].get().strip(),
                              model=self.vars["model"].get().strip(), context_tokens=capacity_value)
            capacity = context_capacity(self.service.store, profile)
            text = (f"上下文：{capacity.tokens} Token；来源：{capacity.source}；输入用量为保守估算"
                    if capacity.tokens else "上下文：未知容量，使用最近50轮 / 100000字符；可手填Token上限")
        except (ValueError, TypeError):
            text = "上下文：请填写有效API地址；Token上限须为正整数或留空自动识别"
        self.context_status.set(text)

    def _reload_profiles(self, selected=None):
        self.profiles = self.service.store.profiles()
        self.profile_choice["values"] = [f"{p.name} | {p.provider} | {p.model}" for p in self.profiles]
        wanted = selected or self.service.store.setting("selected_profile", "")
        index = next((i for i, p in enumerate(self.profiles) if p.id == wanted), 0 if self.profiles else None)
        if index is not None:
            self.new_profile_mode = False
            self.profile_choice.current(index)
            self._fill_profile(self.profiles[index])
            self.service.profile = self.profile
        elif not self.profiles:
            self._fill_profile(ProviderProfile())

    def _choose_profile(self, _event=None):
        index = self.profile_choice.current()
        if index >= 0:
            self.new_profile_mode = False
            self._fill_profile(self.profiles[index])
            self.service.configure(self.profile, self.targets)
            self.service.store.set_setting("selected_profile", self.profile.id)
            self.service.store.set_setting("last_profile:" + self.profile.provider, self.profile.id)

    def _new_profile(self):
        self.new_profile_mode = True
        self.profile_choice.set("")
        self._fill_profile(ProviderProfile())

    def _copy_profile(self):
        from uuid import uuid4
        self.profile_choice.set("")
        self.new_profile_mode = True
        self._fill_profile(replace(self.profile, id=uuid4().hex, name=self.profile.name + " 副本",
                                   capability="未验证", tested_fingerprint=""))

    def _provider_changed(self, _event=None):
        provider = self.vars["provider"].get()
        address, protocol = PROVIDERS[provider]
        if not self.new_profile_mode:
            if provider == self.profile.provider:
                return
            saved = [p for p in self.service.store.profiles() if p.provider == provider]
            wanted = self.service.store.setting("last_profile:" + provider)
            if saved:
                chosen = next((p for p in saved if p.id == wanted), saved[0])
                self._reload_profiles(chosen.id)
                self.service.configure(chosen, self.targets)
                self.service.store.set_setting("selected_profile", chosen.id)
                return
            self.profile_choice.set("")
            self._fill_profile(ProviderProfile(name=provider + " 接入", provider=provider,
                                              base_url=address, protocol=protocol))
        self.vars["base_url"].set(address)
        self.vars["protocol"].set(protocol)
        self.vars["model"].set("")
        self.vars["context_tokens"].set("")
        self.vars["key"].set("")
        self.model_choice["values"] = ()

    def _save(self):
        try:
            values = {key: variable.get().strip() for key, variable in self.vars.items() if key != "key"}
            values["timeout"], values["max_output"] = int(values["timeout"]), int(values["max_output"])
            raw_context = values["context_tokens"]
            values["context_tokens"] = int(raw_context) if raw_context else 0
            if raw_context and values["context_tokens"] <= 0:
                raise ValueError("上下文上限须为正整数，留空表示自动识别")
            key = self.vars["key"].get().strip() or None
            self.service.redactor.add_secrets((key,))
            self.profile = self.service.store.save_profile(replace(self.profile, **values), key)
            self.service.configure(self.profile, self.targets)
            self.service.store.set_setting("selected_profile", self.profile.id)
            self.service.store.set_setting("last_profile:" + self.profile.provider, self.profile.id)
            self._reload_profiles(self.profile.id)
            self.service.emit("[AI配置] 接入配置已保存：" + self.profile.name + " / " + self.profile.provider)
            return self.profile
        except Exception as exc:
            self._error(exc)
            return None

    def _delete_profile(self):
        if messagebox.askyesno("删除接入配置", "删除当前配置及其加密密钥？", parent=self.window):
            self.service.store.delete_profile(self.profile.id)
            self.service.profile = None
            self._reload_profiles()

    def _background(self, kind, operation):
        stop = threading.Event()
        def run():
            try:
                self.events.put((kind, operation(stop)))
            except Exception as exc:
                self.events.put(("error", self.service.redactor.text(str(exc))))
            finally:
                self.background_stops.discard(stop)
                self.background.discard(threading.current_thread())
        thread = threading.Thread(target=run, name="ai-configuration-check", daemon=True)
        self.background.add(thread)
        self.background_stops.add(stop)
        thread.start()

    def _models(self):
        profile = self._save()
        if profile is None:
            return
        try:
            key = self.service.store.key(profile)
        except Exception as exc:
            self._error(exc)
            return
        def fetch(stop):
            client = DiagnosticModelClient(profile, key, self.service.redactor)
            try:
                return profile, refresh_model_context(self.service.store, client, stop)
            finally:
                client.close()
        self.connection_status.set("正在刷新模型，仍可手填模型ID…")
        self._background("models", fetch)

    def _test(self):
        profile = self._save()
        if profile is None:
            return
        if not profile.model.strip():
            self._error(ValueError("请先选择或填写模型ID"))
            return
        try:
            key = self.service.store.key(profile)
        except Exception as exc:
            self._error(exc)
            return
        def test(stop):
            client = DiagnosticModelClient(profile, key, self.service.redactor)
            try:
                capability, detail = client.test_connection(stop)
                return profile, capability, detail
            finally:
                client.close()
        self.connection_status.set("正在使用无项目资料的样例验证…")
        self._background("capability", test)

    def refresh_targets(self):
        try:
            self.targets = tuple(self.targets_provider())
            self.channel_choice["values"] = [f"通道{t.channel} | {t.vlan} | {t.port}" for t in self.targets]
            if self.targets and self.channel_choice.current() < 0:
                self.channel_choice.current(0)
            if self.service.profile is not None:
                self.service.configure(self.service.profile, self.targets)
            if self.chat_panel is not None:
                self.chat_panel.refresh_targets()
        except Exception as exc:
            self.targets = ()
            self.service.emit("[AI配置] 目标刷新失败：" + str(exc))

    def _policy(self):
        channels = tuple(int(x.strip()) for x in self.channel_filter.get().split(",") if x.strip()) or tuple(t.channel for t in self.targets)
        threshold, cooldown = int(self.threshold.get()), int(self.cooldown.get())
        if not 1 <= threshold <= 20 or not 1 <= cooldown <= 3600 or not set(channels) <= {t.channel for t in self.targets}:
            raise ValueError("请检查通道范围、异常阈值（1–20）和冷却（1–3600秒）")
        return DebugTriggerPolicy(channels, tuple(k for k, v in self.features.items() if v.get()), threshold,
            cooldown, tuple(x.strip() for x in self.keywords.get().split(";") if x.strip()),
            tuple(x.strip() for x in self.codes.get().split(";") if x.strip()), self.deep.get())

    def _monitor_changed(self):
        try:
            if self.monitor.get():
                self.refresh_targets()
                policy = self._policy()
                if not policy.channels or self.service.profile is None:
                    raise ValueError("请先保存接入配置并选择目标通道")
                if not messagebox.askyesno("启用本次AI诊断", "本次允许对所选目标登录查询，并按触发条件进行临时Debug采集。\n始终禁止AI重启、上下电、升级和恢复出厂。\n真实诊断信息（含材料中的账号、密码）将发送至：" + self.service.profile.provider + " / " + self.service.profile.base_url,
                                          parent=self.window):
                    self.monitor.set(False)
                    return
                from dataclasses import asdict
                self.service.trigger.policy = policy
                self.service.store.set_setting("trigger_policy", asdict(policy))
            self.service.enable_monitor(self.monitor.get())
        except Exception as exc:
            self.monitor.set(False)
            self._error(exc)

    def _submit(self, active):
        try:
            index = self.channel_choice.current()
            if not 0 <= index < len(self.targets):
                raise ValueError("请选择目标通道")
            number = self.targets[index].channel
            self.refresh_targets()
            index = next((i for i, target in enumerate(self.targets) if target.channel == number), -1)
            if index < 0:
                raise ValueError("目标通道已变更，请重新选择")
            self.channel_choice.current(index)
            question = self.question.get("1.0", "end-1c").strip()
            if not question:
                raise ValueError("请填写问题")
            if active and not messagebox.askyesno("诊断采集确认", "允许对当前目标按需登录查询？\nTelnet优先，连接不可用时回退目标串口；不允许AI重启DUT。", parent=self.window):
                return
            self.service.submit(question, self.targets[index].channel, "light" if active else "question")
            self._show_text("已提交；诊断结果保存在本机报告中。")
        except Exception as exc:
            self._error(exc)

    def _cancel(self):
        self.service.cancel()
        self.service.emit("[AI诊断] 已请求停止，正在完成必要清理，原测试继续")

    def _show_text(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", text)
        self.output.configure(state="disabled")

    def _reload_reports(self):
        rows = self.service.store.reports()
        self.report_ids = [row[0] for row in rows]
        self.reports = {row[0]: row[2] for row in rows}
        self.report_choice["values"] = [f"{created} | 通道{payload.get('channel')} | {payload.get('provider')} | {payload.get('status')}" for _, created, payload in rows]
        if rows:
            self.report_choice.current(0)
            self._choose_report()

    def _choose_report(self, _event=None):
        index = self.report_choice.current()
        if index >= 0:
            self.selected_report = self.report_ids[index]
            payload = self.reports[self.selected_report]
            self._show_text(str(payload.get("report", "")) + "\n\n本地证据：\n"
                            + format_diagnostic_evidence(payload.get("evidence", "")))

    def _reload_cases(self):
        for item in self.case_list.get_children():
            self.case_list.delete(item)
        self.cases = {row["id"]: row for row in self.service.store.cases(include_inactive=True)}
        for row in self.cases.values():
            self.case_list.insert("", "end", iid=str(row["id"]), values=(row["id"], row["title"], "是" if row["active"] else "否"))

    def _choose_case(self, _event=None):
        selected = self.case_list.selection()
        if selected:
            self.selected_case = int(selected[0])
            row = self.cases[self.selected_case]
            for key, variable in self.case_fields.items():
                variable.set(row[key])

    def _new_case(self):
        self.selected_case = None
        for variable in self.case_fields.values():
            variable.set("")

    def _confirm_case(self):
        try:
            if not messagebox.askyesno("人工确认案例", "确认这些字段是实际核实的原因、处理和复测结果，而非AI猜测？", parent=self.window):
                return
            self.service.confirm_case(self.selected_report, **{k: v.get() for k, v in self.case_fields.items()}, case_id=self.selected_case)
            self._reload_cases()
        except Exception as exc:
            self._error(exc)

    def _toggle_case(self):
        if self.selected_case is not None:
            self.service.store.update_case_state(self.selected_case)
            self._reload_cases()

    def _delete_case(self):
        if self.selected_case is not None and messagebox.askyesno("删除案例", "删除该案例及修订记录？", parent=self.window):
            self.service.store.update_case_state(self.selected_case, delete=True)
            self.selected_case = None
            self._reload_cases()

    def _poll(self):
        self._poll_id = None
        if self.chat_panel is not None:
            self.chat_panel.poll()
        for _ in range(40):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.connection_status.set("配置异常：" + value + "；模型列表失败时仍可手填ID")
                self.service.emit("[AI配置] " + value)
            elif kind == "models":
                requested, models = value
                if requested.id == self.profile.id and requested.base_url == self.vars["base_url"].get().strip().rstrip("/"):
                    self.model_choice["values"] = tuple(item["id"] for item in models)
                    self.connection_status.set("模型列表及容量已刷新；不会自动切换当前模型")
            elif kind == "capability":
                profile, capability, detail = value
                current = next((p for p in self.service.store.profiles() if p.id == profile.id), None)
                if current and profile_fingerprint(current) == profile_fingerprint(profile):
                    verified = replace(current, capability=capability, tested_fingerprint=profile_fingerprint(current))
                    self.service.store.save_profile(verified)
                    if current.id == self.profile.id:
                        self._reload_profiles(current.id)
                        self.service.configure(verified, self.targets)
                    self.connection_status.set(capability + "：" + detail)
                    self.service.emit("[AI配置] " + capability + "：" + detail)
        for _ in range(40):
            try:
                kind, payload = self.service.updates.get_nowait()
            except queue.Empty:
                break
            if kind == "report":
                self._reload_reports()
            elif kind == "monitor_off":
                self.monitor.set(False)
                self.service.emit("[AI监控] " + payload)
            elif kind == "warning":
                self.service.emit("[AI监控] " + payload)
        if self.window is not None and self.window.winfo_exists():
            self._update_context_status()
            self._poll_id = self.master.after(100, self._poll)

    def hide(self):
        self.window.withdraw()

    def begin_close(self):
        for stop in tuple(self.background_stops):
            stop.set()

"""AI 独立窗口；输入/显示和异步任务回调，设备执行位于service/core。"""
from __future__ import annotations

from dataclasses import replace
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import PROVIDERS, ProviderProfile
from src.services.ai_store import profile_fingerprint
from src.services.ai_context_budget import context_capacity, refresh_model_context
from src.ui.window_paint import center_toplevel_on_parent
from src.ui.module_theme import apply_module_theme, MODULE_BACKGROUND
from src.ui.ai_monitor_window import AiMonitorWindow
from src.ui.ai_reports_window import AiReportsWindow


class AiDiagnosticsWindow:
    def __init__(self, master, service, targets_provider, background=MODULE_BACKGROUND, foreground="#17202a", conversation=None):
        self.master, self.service, self.targets_provider = master, service, targets_provider
        self.background_color, self.foreground_color = background, foreground
        self.window = None
        self.profile = ProviderProfile()
        self.case_report_id = ""
        self.selected_case = None
        self.background = set()
        self.background_stops = set()
        self.events = queue.Queue()
        self.targets = ()
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
        self.book = book
        workspace, connection, cases = (ttk.Frame(book, padding=10) for _ in range(3))
        self.workspace, self.cases_tab = workspace, cases
        for frame, title in ((workspace, "排障工作台"), (connection, "模型接入"), (cases, "已确认案例")):
            book.add(frame, text=title)
        self.monitor_status = tk.StringVar(self.window, value="自动监控：关闭")
        self.report_status = tk.StringVar(self.window)
        self.monitor_panel = AiMonitorWindow(self)
        self.reports_panel = AiReportsWindow(self)
        toolbar = ttk.Frame(workspace)
        toolbar.pack(fill="x", pady=(0, 5))
        ttk.Button(toolbar, text="自动监控", command=self.monitor_panel.open).pack(side="left")
        ttk.Label(toolbar, textvariable=self.monitor_status).pack(side="left", padx=8)
        ttk.Button(toolbar, text="诊断报告", command=self.reports_panel.open).pack(side="left", padx=4)
        ttk.Label(toolbar, textvariable=self.report_status).pack(side="left", padx=8)
        ttk.Button(toolbar, text="刷新目标", command=self.refresh_targets).pack(side="right")
        self._connection_tab(connection)
        self._cases_tab(cases)
        if self.conversation is not None:
            from src.ui.ai_chat_panel import AiChatPanel
            self.chat_panel = AiChatPanel(workspace, self, self.conversation)
        else:
            ttk.Label(workspace, text="对话服务未连接；仍可查看监控设置和报告。").pack(anchor="w")
        book.select(workspace)
        self._apply_theme()
        center_toplevel_on_parent(self.window, self.master)
        self._reload_profiles()
        self.refresh_targets()
        self.reports_panel.reload()
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

    def _cases_tab(self, parent):
        self.case_source = tk.StringVar(self.window, value="未关联报告")
        ttk.Label(parent, textvariable=self.case_source).pack(anchor="w", pady=(0, 6))
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
        for title, action in (("新建案例", self._new_case), ("人工确认/保存修订", self._confirm_case),
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
            if self.service.profile is not None:
                self.service.configure(self.service.profile, self.targets)
            if self.chat_panel is not None:
                self.chat_panel.refresh_targets()
        except Exception as exc:
            self.targets = ()
            self.service.emit("[AI配置] 目标刷新失败：" + str(exc))

    def continue_report(self, report_id, target=None, legacy_confirmed=False):
        if self.chat_panel is None:
            raise ValueError("对话服务未连接")
        self.refresh_targets()
        identifier = self.conversation.create_session_from_report(
            report_id, self.service.profile, target=target, legacy_confirmed=legacy_confirmed)
        self.chat_panel.selected = identifier
        self.chat_panel.revision = None
        self.chat_panel.refresh()
        # 显式选择新会话的目标；历史目标不套用之前的目标下拉选择。
        self.chat_panel.choose()
        self.book.select(self.workspace)
        self.window.deiconify()
        self.window.lift()
        return identifier

    def case_from_report(self, report_id):
        try:
            self.service.store.report(report_id)
            self._new_case()
            self.case_report_id = report_id
            self.case_source.set("来源报告：" + report_id)
            self.service.emit("[AI案例] 从报告新建草稿：" + report_id)
            self.book.select(self.cases_tab)
            self.window.deiconify()
            self.window.lift()
        except Exception as exc:
            self._error(exc)

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
            self.case_report_id = row["report_id"] or ""
            self.case_source.set("来源报告：" + self.case_report_id if self.case_report_id else "未关联报告")
            for key, variable in self.case_fields.items():
                variable.set(row[key])

    def _new_case(self):
        self.case_list.selection_remove(*self.case_list.selection())
        self.selected_case = None
        self.case_report_id = ""
        self.case_source.set("未关联报告")
        for variable in self.case_fields.values():
            variable.set("")

    def _confirm_case(self):
        try:
            if not messagebox.askyesno("人工确认案例", "确认这些字段是实际核实的原因、处理和复测结果，而非AI猜测？", parent=self.window):
                return
            self.service.confirm_case(self.case_report_id, **{k: v.get() for k, v in self.case_fields.items()}, case_id=self.selected_case)
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
                self.reports_panel.reload()
                self.report_status.set("报告有更新")
            elif kind == "monitor_off":
                self.monitor_panel.enabled.set(False)
                self.monitor_panel.update_status()
                self.service.emit("[AI监控] " + payload)
            elif kind == "warning":
                self.service.emit("[AI监控] " + payload)
        if self.window is not None and self.window.winfo_exists():
            self._update_context_status()
            self._poll_id = self.master.after(100, self._poll)

    def hide(self):
        for panel in (self.monitor_panel, self.reports_panel):
            if panel.window is not None and panel.window.winfo_exists():
                panel.window.withdraw()
        self.window.withdraw()

    def begin_close(self):
        for stop in tuple(self.background_stops):
            stop.set()

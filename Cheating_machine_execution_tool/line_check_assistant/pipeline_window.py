"""「全流程执行」窗口 UI(2026-07-20 新增)。

主界面「检查并执行测试」按钮按下后,弹出本窗口,操作员可勾选 7 个子任务(自动上/下电
/ 环境线路检查 / 样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 执行开关机测试),每行右侧展示「必填项当前
状态」(就绪 / 缺项),「去配置」按钮跳到主程序对应子窗口;底部「开始执行」若勾选
串口日志则先预启动终端，其余子任务按 1→7 相对顺序串行执行,任一失败(串口日志除外)→ 整个全流程停止。

入口:主程序 ``LineCheckAssistant._start_all_checks`` 改为 ``_open_pipeline_window``,
构造 ``PipelineWindow(self)`` 后自动弹窗。

依赖:
- ``src/services/pipeline_orchestrator.py`` ``PipelineContext`` / ``PipelineOrchestrator`` /
  ``compute_all_subtask_statuses``
- 主程序 ``LineCheckAssistant`` 实例(app parameter)用于:读各 store / 弹子窗口 /
  调既有 ``_start_*`` 方法 / 主执行日志 ``self._log``。
"""
from __future__ import annotations

import threading
from tkinter import BooleanVar, Canvas, Checkbutton, Frame, Label, StringVar, Toplevel, messagebox, ttk
from typing import Any, Callable, Dict, List, Set

from src.services.pipeline_orchestrator import (
    NON_FATAL_SUBTASKS,
    SUBTASK_CODES,
    SUBTASK_CONFIG_TARGETS,
    SUBTASK_LABELS,
    PipelineContext,
    PipelineError,
    PipelineOrchestrator,
    SubTaskResult,
    SubTaskStatus,
    compute_all_subtask_statuses,
    execution_order_for,
)
from src.ui.window_paint import center_toplevel_on_parent


COLOR_BG = "#f4f6fa"
COLOR_SURFACE = "#ffffff"
COLOR_TEXT = "#1f2933"
COLOR_MUTED = "#52606d"
COLOR_BORDER = "#cbd2d9"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_DARK = "#1d4ed8"
COLOR_SUCCESS = "#0f766e"
COLOR_SUCCESS_BG = "#ccfbf1"
COLOR_DANGER = "#b91c1c"
COLOR_DANGER_BG = "#fee2e2"


class PipelineWindow:
    """全流程执行窗口(2026-07-20)。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.window: Toplevel = Toplevel(app)
        self.window.title("全流程执行")
        # 7 行选择框、无人值守授权和底部按钮需要至少 ~780px 高度。
        self.window.geometry("920x800")
        self.window.minsize(880, 780)
        self.window.configure(background=COLOR_BG)
        # 状态变量
        self._check_vars: Dict[str, BooleanVar] = {}
        self._selection_indicators: Dict[str, Canvas] = {}
        self._status_labels: Dict[str, Label] = {}
        self._status_summary_vars: Dict[str, StringVar] = {}
        self._status_missing_vars: Dict[str, StringVar] = {}
        self._orchestrator: PipelineOrchestrator | None = None
        self._running_thread: threading.Thread | None = None
        self._stop_requested = False
        # 仅当前窗口、本次启动有效；关闭窗口或流程结束后不会持久化此授权。
        self._unattended_execution_var = BooleanVar(value=False)

        self._build()
        self._refresh_statuses()
        # 从「去配置」打开的子窗口返回时，立即用当前输入刷新缺项状态。
        self.window.bind("<FocusIn>", self._on_focus_in)
        # 操作员关闭窗口时若正在跑,提示
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        center_toplevel_on_parent(self.window, app)

    # -- UI 构建 --------------------------------------------------------

    def _build(self) -> None:
        content = Frame(self.window, padx=20, pady=18, background=COLOR_BG)
        content.pack(fill="both", expand=True)

        Label(
            content,
            text="全流程执行",
            font=("Microsoft YaHei UI", 18, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(anchor="w")
        Label(
            content,
            text=(
                "勾选需要执行的子任务;必填项未就绪时整行红字提示,可点「去配置」"
                "跳到对应子窗口填写。若勾选串口日志，将在全流程开始时先打开；"
                "其余子任务按 1→7 相对顺序串行执行,"
                "任一失败(串口日志除外)将停止整个全流程。"
            ),
            background=COLOR_BG,
            foreground=COLOR_MUTED,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        # 7 行子任务
        rows = Frame(content, background=COLOR_BG)
        rows.pack(fill="both", expand=True)
        for index, code in enumerate(SUBTASK_CODES):
            self._build_row(rows, code, index)

        unattended_row = Frame(content, background=COLOR_BG)
        unattended_row.pack(fill="x", pady=(2, 0))
        Checkbutton(
            unattended_row,
            text="本次无人值守（总确认后跳过样机升级、写参的子任务确认）",
            variable=self._unattended_execution_var,
            selectcolor="#ffffff",
            background=COLOR_BG,
            activebackground=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(side="left")
        Label(
            unattended_row,
            text="不包含 ONU 注册；预检、失败和停止仍会终止后续致命任务。",
            background=COLOR_BG,
            foreground=COLOR_MUTED,
        ).pack(side="left", padx=(10, 0))

        # 底部按钮
        button_bar = Frame(content, background=COLOR_BG)
        button_bar.pack(fill="x", side="bottom", pady=(12, 0))
        self._start_button = ttk.Button(
            button_bar, text="开始执行", command=self._on_start, style="Primary.TButton"
        )
        self._start_button.pack(side="right", padx=(8, 0))
        ttk.Button(
            button_bar, text="刷新状态", command=self._refresh_statuses, style="Secondary.TButton"
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            button_bar, text="取消", command=self._on_close, style="Secondary.TButton"
        ).pack(side="right", padx=(0, 8))

    @staticmethod
    def _selection_mark(selected: bool) -> str:
        """选中时显示标准勾选标记，未选中时保持空框。"""
        return "✓" if selected else ""

    @staticmethod
    def _default_checked(_code: str) -> bool:
        """全流程窗口首次打开时不自动选择任何子任务。"""
        return False

    def _draw_selection_indicator(self, code: str) -> None:
        """按当前 BooleanVar 重绘 14px 选择框。"""
        indicator = self._selection_indicators[code]
        mark = self._selection_mark(self._check_vars[code].get())
        indicator.delete("all")
        indicator.create_rectangle(
            0,
            0,
            13,
            13,
            fill=COLOR_SURFACE,
            outline="#000000",
        )
        if mark:
            indicator.create_text(
                6.5,
                6.5,
                text=mark,
                fill="#000000",
                font=("Segoe UI Symbol", 10, "bold"),
            )

    def _toggle_subtask(self, code: str) -> None:
        """点击小选择框或任务标题时切换选择状态。"""
        var = self._check_vars[code]
        var.set(not var.get())
        self._draw_selection_indicator(code)
        self._refresh_statuses()

    def _build_row(self, parent: Frame, code: str, index: int) -> None:
        """单行:勾选框 + label + summary + missing + 去配置 按钮。

        布局(2026-07-20 按用户反馈调整):summary(黑字)与 missing(红字)互换行——
          第 0 行: missing 红字(若有)　　—— 提示更醒目
          第 1 行: summary 描述　　　　　 —— 详细参数放次行
        """
        row = Frame(parent, background=COLOR_SURFACE, padx=10, pady=8, relief="solid", borderwidth=1)
        row.pack(fill="x", pady=(0, 6))

        # 所有子任务都由操作员按本次测试需要明确选择，避免打开窗口后误执行。
        var = BooleanVar(value=self._default_checked(code))
        self._check_vars[code] = var

        selector = Frame(row, background=COLOR_SURFACE)
        selector.grid(row=0, column=0, sticky="w", padx=(0, 10))
        indicator = Canvas(
            selector,
            width=14,
            height=14,
            background=COLOR_SURFACE,
            highlightthickness=0,
            cursor="hand2",
        )
        indicator.grid(row=0, column=0, padx=(0, 4))
        self._selection_indicators[code] = indicator
        self._draw_selection_indicator(code)
        title = Label(
            selector,
            text=SUBTASK_LABELS[code],
            background=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            cursor="hand2",
        )
        title.grid(row=0, column=1, sticky="w")
        indicator.bind("<Button-1>", lambda _event, c=code: self._toggle_subtask(c))
        title.bind("<Button-1>", lambda _event, c=code: self._toggle_subtask(c))

        # 缺项(红字)在上、summary(黑字)在下一行(用户 2026-07-20 反馈:红字提示更醒目)
        summary_var = StringVar(value="(计算中...)")
        missing_var = StringVar(value="")
        self._status_summary_vars[code] = summary_var
        self._status_missing_vars[code] = missing_var
        Label(
            row, textvariable=missing_var, background=COLOR_SURFACE,
            foreground=COLOR_DANGER, font=("Microsoft YaHei UI", 9, "bold"),
        ).grid(row=0, column=1, sticky="w")
        Label(
            row, textvariable=summary_var, background=COLOR_SURFACE,
            foreground=COLOR_TEXT, font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        # 去配置按钮
        config_method = SUBTASK_CONFIG_TARGETS.get(code, "")
        ttk.Button(
            row, text="去配置", command=lambda m=config_method: self._open_config(m),
            style="Secondary.TButton",
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(10, 0))

        row.columnconfigure(1, weight=1)

    def _open_config(self, method_name: str) -> None:
        """跳到主程序的子窗口方法(去配置按钮)。"""
        method = getattr(self.app, method_name, None)
        if not callable(method):
            messagebox.showwarning(
                "未找到配置入口",
                f"主程序未实现 {method_name},请直接编辑对应 ini 文件。",
                parent=self.window,
            )
            return
        try:
            method()
        except Exception as exc:  # noqa: BLE001 - 子窗口弹出异常需捕获
            messagebox.showerror(
                "打开配置窗口失败",
                f"{method_name} 失败:{exc}",
                parent=self.window,
            )

    # -- 状态刷新 -------------------------------------------------------

    def _on_focus_in(self, _event=None) -> None:
        """重新回到全流程窗口时，刷新刚在子窗口修改的配置状态。"""
        if not (self._running_thread and self._running_thread.is_alive()):
            self._refresh_statuses()

    def _refresh_statuses(self) -> None:
        """按当前 store / main UI 状态刷新每行就绪 / 缺项。"""
        try:
            ctx = self._build_context()
        except Exception as exc:  # noqa: BLE001 - 状态计算失败也要继续展示
            for code in SUBTASK_CODES:
                self._status_summary_vars[code].set("(无法计算状态)")
                self._status_missing_vars[code].set(f"错误:{exc}")
            return
        statuses = compute_all_subtask_statuses(ctx)
        for code, status in statuses.items():
            self._update_status_row(code, status)

    def _update_status_row(self, code: str, status: SubTaskStatus) -> None:
        self._status_summary_vars[code].set(status.summary)
        if status.missing:
            self._status_missing_vars[code].set("缺: " + "、".join(status.missing))
        else:
            self._status_missing_vars[code].set("")

    def _build_context(self, unattended_execution: bool = False) -> PipelineContext:
        """构造 PipelineContext，并优先读取各配置窗口中的当前输入。"""
        app = self.app
        channels = _get_attr(app, "channels", [])
        # 升级窗口编辑的是 Tk 变量；不能只读启动时加载的缓存，否则界面已填的
        # 超级用户名 / 密码 / 固件路径会被管道误判为缺失。
        current_settings = _get_attr(app, "_current_sample_upgrade_settings", None)
        settings = current_settings() if callable(current_settings) else _get_attr(app, "sample_upgrade_settings", None)
        if settings is None:
            from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
            settings = SampleUpgradeSettings()
        # ONU 窗口同样优先读当前输入，避免保存延迟造成管道状态滞后。
        current_onu = _get_attr(app, "_current_onu_registration_config", None)
        onu = current_onu() if callable(current_onu) else _get_attr(app, "onu_registration_config", None)
        if onu is None:
            from line_check_assistant.onu_registration_store import OnuRegistrationConfig
            onu = OnuRegistrationConfig()
        import line_check_assistant.app as _app_module
        return PipelineContext(
            app=app,
            channels=channels,
            sample_upgrade_settings=settings,
            onu_registration=onu,
            serial_log_dir=_get_attr(app, "_serial_log_directory", lambda: None)(),
            legacy_tool_root=_app_module.APP_DIR / "Auto_power_on_off_tool",
            unattended_execution=unattended_execution,
        )

    # -- 开始 / 停止 -----------------------------------------------------

    def _on_start(self) -> None:
        if self._running_thread and self._running_thread.is_alive():
            return
        selected = {code for code, var in self._check_vars.items() if var.get()}
        if not selected:
            messagebox.showwarning("未选择子任务", "请至少勾选一个子任务后再开始执行。", parent=self.window)
            return
        # 校验就绪
        unattended_execution = bool(self._unattended_execution_var.get())
        ctx = self._build_context(unattended_execution=unattended_execution)
        statuses = compute_all_subtask_statuses(ctx)
        not_ready = [code for code in selected if not statuses[code].ready]
        if not_ready:
            missing_lines: List[str] = []
            for code in not_ready:
                missing_lines.append(
                    f"  - {SUBTASK_LABELS[code]}:缺 {', '.join(statuses[code].missing)}"
                )
            if unattended_execution:
                messagebox.showwarning(
                    "无人值守不可用",
                    "以下已勾选子任务存在必填项缺失。无人值守不会在启动后等待人工处理，请先完成配置：\n"
                    + "\n".join(missing_lines),
                    parent=self.window,
                )
                return
            proceed = messagebox.askyesno(
                "必填项未就绪",
                "以下子任务必填项未就绪,继续执行可能失败:\n"
                + "\n".join(missing_lines)
                + "\n\n是否仍要继续?",
                parent=self.window,
            )
            if not proceed:
                return
        # 二次确认
        confirm_lines: List[str] = []
        actual_order = execution_order_for(selected)
        for code in actual_order:
            suffix = "（全流程开始时提前启动）" if code == "serial_terminal" else ""
            confirm_lines.append(f"  ✓ {SUBTASK_LABELS[code]}{suffix}")
        power_to_next_wait_note = ""
        if "power_cycle" in actual_order and actual_order.index("power_cycle") + 1 < len(actual_order):
            power_to_next_wait_note = "\n\n执行约束：子任务1完成后等待 120 秒，再开始后续已勾选子任务。"
        power_var = _get_attr(ctx.app, "power_serial_var", None)
        power_serial_port = power_var.get().strip() if power_var is not None and hasattr(power_var, "get") else ""
        requires_manual_reboot = "power_cycle" in selected or (
            "sample_upgrade" in selected and ctx.sample_upgrade_settings.upgrade_mode == "全包升级"
        )
        manual_reboot_note = ""
        if requires_manual_reboot and not power_serial_port:
            if unattended_execution:
                messagebox.showwarning(
                    "无人值守不可用",
                    "全包升级未选择程控电源 COM 口，需要操作员手动重启样机。"
                    "请配置程控电源后再启用本次无人值守。",
                    parent=self.window,
                )
                return
            manual_reboot_note = (
                "\n\n未选择程控电源 COM 口。请先手动重启样机，"
                "确认样机已重启后再点击“是”继续；程序不会向任何 COM 口下发上下电指令。"
            )
        legacy_power_note = ""
        if "legacy_power_test" in selected:
            legacy_power_note = (
                "\n\n危险操作提示：子任务7会复用旧 Start All 业务；初始化时先向程控电源"
                "下发全通道断电指令，再启动新工具当前勾选的通道。"
            )
        unattended_note = self._unattended_confirmation_note(
            ctx, selected, unattended_execution
        )
        proceed = messagebox.askyesno(
            "确认全流程执行",
            "将按以下实际顺序执行勾选的子任务:\n"
            + "\n".join(confirm_lines)
            + power_to_next_wait_note
            + manual_reboot_note
            + legacy_power_note
            + unattended_note
            + "\n\n是否继续?",
            parent=self.window,
        )
        if not proceed:
            return
        # 锁定按钮
        self._stop_requested = False
        self._set_running_ui(True)
        self._update_main_power_test_progress(0, 0)
        self._update_main_power_test_status("running")
        # 启动后台线程
        self._running_thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(selected, unattended_execution),
            daemon=True,
            name="pipeline-orchestrator",
        )
        self._running_thread.start()
        self.window.withdraw()
        self._emit_to_main_log(
            "[全流程] 已开始后台执行，全流程配置窗口已自动隐藏；请在主界面查看状态或停止。"
            + (" 本次无人值守已授权升级和写参跳过子任务确认。" if unattended_execution else "")
        )

    def _run_pipeline_thread(self, selected: Set[str], unattended_execution: bool = False) -> None:
        try:
            ctx = self._build_context(unattended_execution=unattended_execution)
            orchestrator = PipelineOrchestrator(ctx, self._emit_to_main_log)
            self._orchestrator = orchestrator
            if self._stop_requested:
                orchestrator.request_stop()
            results = orchestrator.run(selected)
            self._invoke_on_main_thread(
                lambda completed_results=results: self._on_pipeline_complete(
                    completed_results
                )
            )
        except PipelineError as exc:
            self._invoke_on_main_thread(
                lambda error=exc: self._on_pipeline_failed(error)
            )
        except Exception as exc:  # noqa: BLE001 - 后台线程异常需兜底
            self._invoke_on_main_thread(
                lambda error=exc: self._on_pipeline_failed(error)
            )
        finally:
            self._orchestrator = None

    @staticmethod
    def _unattended_confirmation_note(
        ctx: PipelineContext, selected: Set[str], unattended_execution: bool
    ) -> str:
        """返回一次性无人值守授权的完整风险摘要。"""
        if not unattended_execution:
            return ""
        details: List[str] = [
            "\n\n本次无人值守授权：仅跳过下列已勾选子任务的二次确认；预检、失败、停止不会自动继续。"
        ]
        settings = ctx.sample_upgrade_settings
        if "sample_upgrade" in selected:
            transfer = (
                f" / {settings.transfer_method}"
                if settings.upgrade_mode == "全包升级"
                else ""
            )
            details.append(
                "- 样机升级："
                f"{settings.upgrade_mode}{transfer}，固件 {settings.firmware_path or '未填写'}，"
                f"并行数 {settings.parallel_count}，恢复出厂 "
                f"{'开启' if settings.restore_factory else '关闭'}。"
            )
        if "sample_parameter_write" in selected:
            details.append(
                "- 写样机参数："
                f"参数表 {settings.parameter_table_path or '未填写'}，"
                f"并行数 {settings.parameter_parallel_count}，清空参数 "
                f"{'开启' if settings.parameter_clear_parameters else '关闭'}，退出老化 "
                f"{'开启' if settings.parameter_exit_aging else '关闭'}。"
            )
        return "\n".join(details)

    def _invoke_on_main_thread(self, action) -> None:
        """通过主程序既有 UI 队列执行 Tk 回调，兼容不带队列的最小测试替身。"""
        invoke = getattr(self.app, "_invoke_pipeline_ui_action", None)
        if callable(invoke):
            invoke(action)
            return
        action()

    def is_running(self) -> bool:
        """返回后台全流程线程的真实存活状态。"""
        return bool(self._running_thread and self._running_thread.is_alive())

    def _on_pipeline_complete(self, results: List[SubTaskResult]) -> None:
        self._set_running_ui(False)
        self._update_main_power_test_status(
            "stopped" if self._stop_requested else "completed"
        )
        n_ok = sum(1 for r in results if r.ok)
        n_fail = sum(1 for r in results if not r.ok)
        failed_codes = [SUBTASK_LABELS[r.code] for r in results if not r.ok]
        if n_fail == 0:
            messagebox.showinfo(
                "全流程执行完成",
                f"全部 {n_ok} 个勾选子任务执行完成。",
                parent=self.app,
            )
        else:
            messagebox.showwarning(
                "全流程执行部分失败",
                f"成功:{n_ok};失败:{n_fail}\n失败项:{', '.join(failed_codes)}",
                parent=self.app,
            )
        self._refresh_statuses()

    def _on_pipeline_failed(self, exc: Exception) -> None:
        self._set_running_ui(False)
        self._update_main_power_test_status(
            "stopped" if self._stop_requested else "failed"
        )
        messagebox.showerror(
            "全流程执行失败",
            f"全流程异常终止:{exc}",
            parent=self.app,
        )
        self._refresh_statuses()

    def request_stop(self) -> bool:
        """供主界面停止按钮调用；返回是否已向当前编排器发出停止请求。"""
        if self._orchestrator is None:
            if self._running_thread is None or not self._running_thread.is_alive():
                return False
        else:
            self._orchestrator.request_stop()
        self._stop_requested = True
        self._update_main_power_test_status("stopping")
        self._emit_to_main_log(
            "[主界面] 用户点击「停止测试」；全流程将在当前子任务安全退出后终止"
        )
        return True

    def _on_close(self) -> None:
        if self._running_thread and self._running_thread.is_alive():
            if not messagebox.askyesno(
                "全流程执行正在进行",
                "全流程仍在运行,确认关闭窗口?操作员在主程序后台线程可能继续运行。",
                parent=self.window,
            ):
                return
            self.request_stop()
        if hasattr(self.app, "pipeline_window"):
            self.app.pipeline_window = None
        self.window.destroy()

    # -- 辅助 -----------------------------------------------------------

    def _emit_to_main_log(self, line: str) -> None:
        """emit 回调:把编排器日志投到主程序 log_queue(由 app._drain_log_queue 拉取到 log_text)。"""
        if hasattr(self.app, "log_queue"):
            self.app.log_queue.put(line)

    def _set_running_ui(self, running: bool) -> None:
        # 切换按钮状态
        if running:
            self._start_button.configure(state="disabled")
            for var in self._check_vars.values():
                # 锁定勾选状态
                pass
        else:
            self._start_button.configure(state="normal")

    def _update_main_power_test_status(self, status: str) -> None:
        setter = getattr(self.app, "_set_power_test_status", None)
        if callable(setter):
            setter(status)

    def _update_main_power_test_progress(self, completed: int, total: int) -> None:
        setter = getattr(self.app, "_set_power_test_progress", None)
        if callable(setter):
            setter(completed, total)


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


__all__ = ["PipelineWindow"]

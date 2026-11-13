"""「全流程执行」窗口 UI(2026-07-20 新增)。

主界面「检查并执行测试」按钮按下后,弹出本窗口,操作员可勾选 3 个子任务(环境线路检查
/ 串口日志 / 执行开关机测试),每行右侧展示「必填项当前
状态」(就绪 / 缺项),「去配置」按钮跳到主程序对应子窗口;底部「开始执行」若勾选
串口日志则先预启动终端，再按顺序执行环境线路检查和开关机测试,任一失败(串口日志除外)→ 整个全流程停止。

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
from copy import deepcopy
import queue
from tkinter import BooleanVar, Checkbutton, Frame, Label, StringVar, Toplevel, messagebox, ttk
from typing import Any, Callable, Dict, List, Set

from src.services.pipeline_orchestrator import (
    NON_FATAL_SUBTASKS,
    SUBTASK_CONFIG_TARGETS,
    SUBTASK_LABELS as ORCHESTRATOR_SUBTASK_LABELS,
    PipelineContext,
    PipelineError,
    PipelineOrchestrator,
    SubTaskResult,
    SubTaskStatus,
    _power_channel_number,
    compute_all_subtask_statuses,
    execution_order_for,
)
from src.services.telnet_post_login_confirmation_service import (
    describe_legacy_power_telnet_post_login,
)
from src.ui.module_theme import MODULE_BACKGROUND, apply_module_theme
from src.ui.window_paint import center_toplevel_on_parent
from src.ui.tk_lifecycle import TkScope
from src.services.pipeline_runtime import PipelineClient, PipelineLogSink, run_pipeline


# 窗口入口仅保留三项，编排器原任务代码及其它能力继续兼容。
WINDOW_SUBTASK_CODES = ("env_check", "serial_terminal", "legacy_power_test")
WINDOW_SUBTASK_LABELS = {
    "env_check": "1. 环境线路检查",
    "serial_terminal": "2. 串口日志（全流程期间持续记录）",
    "legacy_power_test": "3. 执行开关机测试",
}

COLOR_BG = MODULE_BACKGROUND
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
        self._scope = TkScope()
        self._closed = False
        self._run = None
        self.window: Toplevel = Toplevel(app)
        self.window.title("全流程执行")
        # 三项任务使用紧凑最小尺寸，仍通过原有入口恢复及保存窗口宽高。
        window_width, window_height = app._restore_module_window_size(
            self.window, "pipeline"
        )
        self.window.minsize(880, 520)
        self.window.configure(background=COLOR_BG)
        # 状态变量
        self._check_vars: Dict[str, BooleanVar] = {}
        self._selection_controls: Dict[str, Checkbutton] = {}
        self._status_labels: Dict[str, Label] = {}
        self._status_summary_vars: Dict[str, StringVar] = {}
        self._status_missing_vars: Dict[str, StringVar] = {}
        self._orchestrator: PipelineOrchestrator | None = None
        self._running_thread: threading.Thread | None = None
        self._stop_requested = False

        self._build()
        apply_module_theme(self.window, COLOR_BG)
        self._refresh_statuses()
        # 从「去配置」打开的子窗口返回时，立即用当前输入刷新缺项状态。
        self.window.bind("<FocusIn>", self._on_focus_in)
        # 操作员关闭窗口时若正在跑,提示
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        center_toplevel_on_parent(
            self.window, app, window_width=window_width, window_height=window_height
        )

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

        # 仅显示本窗口允许选择的三项子任务
        rows = Frame(content, background=COLOR_BG)
        rows.pack(fill="both", expand=True)
        for index, code in enumerate(WINDOW_SUBTASK_CODES):
            self._build_row(rows, code, index)

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
    def _default_checked(_code: str) -> bool:
        """全流程窗口首次打开时不自动选择任何子任务。"""
        return False

    def _build_row(self, parent: Frame, code: str, index: int) -> None:
        """单行:勾选框 + label + summary + missing + 去配置 按钮。

        布局(2026-07-20 按用户反馈调整):summary(黑字)与 missing(红字)互换行——
          第 0 行: missing 红字(若有)　　—— 提示更醒目
          第 1 行: summary 描述　　　　　 —— 详细参数放次行
        """
        row = Frame(parent, background=COLOR_SURFACE, padx=10, pady=8, relief="solid", borderwidth=1)
        row.pack(fill="x", pady=(0, 6))

        # 所有子任务都由操作员按本次测试需要明确选择，避免打开窗口后误执行。
        var = self._scope.variable(BooleanVar, row, value=self._default_checked(code))
        self._check_vars[code] = var

        selector = Checkbutton(
            row,
            text=WINDOW_SUBTASK_LABELS[code],
            variable=var,
            command=self._refresh_statuses,
            selectcolor=COLOR_SURFACE,
            background=COLOR_BG,
            activebackground=COLOR_BG,
            foreground=COLOR_TEXT,
            anchor="w",
        )
        selector.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self._selection_controls[code] = selector

        # 缺项(红字)在上、summary(黑字)在下一行(用户 2026-07-20 反馈:红字提示更醒目)
        summary_var = self._scope.variable(StringVar, row, value="(计算中...)")
        missing_var = self._scope.variable(StringVar, row, value="")
        self._status_summary_vars[code] = summary_var
        self._status_missing_vars[code] = missing_var
        Label(
            row, textvariable=missing_var, background=COLOR_SURFACE,
            foreground=COLOR_DANGER, font=("Microsoft YaHei UI", 9, "bold"),
            wraplength=360, justify="left",
        ).grid(row=0, column=1, sticky="w")
        Label(
            row, textvariable=summary_var, background=COLOR_SURFACE,
            foreground=COLOR_TEXT, font=("Microsoft YaHei UI", 9),
            wraplength=680, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

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
            for code in WINDOW_SUBTASK_CODES:
                self._status_summary_vars[code].set("(无法计算状态)")
                self._status_missing_vars[code].set(f"错误:{exc}")
            return
        statuses = compute_all_subtask_statuses(ctx, WINDOW_SUBTASK_CODES)
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
        scope = getattr(self, '_scope', None)
        if scope is not None:
            scope.check()
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
        ui = self.app.__dict__.get('_pipeline_ui')
        if ui is not None and not ui.idle():
            messagebox.showwarning('全流程正在收尾', '请等待上一次后台任务安全退出后再开始。', parent=self.window)
            return
        prepare_ai = getattr(self.app, "_prepare_ai_for_device_action", None)
        if callable(prepare_ai) and prepare_ai() is False:
            return
        session = getattr(self.app, 'power_test_resume_session', None)
        if session is not None and session.is_recovering:
            messagebox.showwarning('通道续跑进行中', '请等待续跑结束或停止后再启动全流程。', parent=self.window)
            return
        if self._running_thread and self._running_thread.is_alive():
            return
        selected = {
            code for code in WINDOW_SUBTASK_CODES
            if code in self._check_vars and self._check_vars[code].get()
        }
        if not selected:
            messagebox.showwarning("未选择子任务", "请至少勾选一个子任务后再开始执行。", parent=self.window)
            return
        # 校验就绪
        ctx = self._build_context()
        statuses = compute_all_subtask_statuses(ctx, WINDOW_SUBTASK_CODES)
        not_ready = [code for code in selected if not statuses[code].ready]
        if not_ready:
            missing_lines: List[str] = []
            for code in not_ready:
                missing_lines.append(
                    f"  - {WINDOW_SUBTASK_LABELS[code]}:缺 {', '.join(statuses[code].missing)}"
                )
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
            confirm_lines.append(f"  ✓ {WINDOW_SUBTASK_LABELS[code]}{suffix}")
            if code == "serial_terminal":
                confirm_lines.append(f"    {statuses[code].summary}")
        subtask_interval_note = ""
        if len(actual_order) > 1:
            subtask_interval_note = "\n\n执行约束：串口日志预启动和环境线路检查完成后不等待，直接进入下一个已选子任务。"
        legacy_power_note = ""
        if "legacy_power_test" in selected:
            selected_power_channels = list(dict.fromkeys(
                _power_channel_number(channel.section) for channel in ctx.enabled_channels
            ))
            legacy_power_note = (
                "\n\n危险操作提示：执行开关机测试会复用旧 Start All 业务；初始化仅断电已勾选通道："
                f"{selected_power_channels}，逐通道下发关闭帧后再启动测试。"
                "\n开关机版本预检："
                + describe_legacy_power_telnet_post_login(ctx)
            )
        proceed = messagebox.askyesno(
            "确认全流程执行",
            "将按以下实际顺序执行勾选的子任务:\n"
            + "\n".join(confirm_lines)
            + subtask_interval_note
            + legacy_power_note
            + "\n\n是否继续?",
            parent=self.window,
        )
        if not proceed:
            return
        # 锁定按钮
        previous_session = getattr(self.app, 'power_test_resume_session', None)
        if previous_session is not None:
            previous_session.stop()
            self.app.power_test_resume_session = None
        self._stop_requested = False
        self._set_running_ui(True)
        self._update_main_power_test_progress(0, 0)
        self._update_main_power_test_status("running")
        # Snapshot once on Tk; the worker never receives this window or app.
        from src.ui.pipeline_ui import PipelineUiController
        ui = self.app.__dict__.get('_pipeline_ui')
        if ui is None:
            ui = self.app._pipeline_ui = PipelineUiController(self.app)
        run = ui.channel.new_run()
        self._run = run
        power_var = getattr(self.app, 'power_serial_var', None)
        power_port = power_var.get() if power_var is not None else getattr(self.app, 'power_serial_port', '')
        selected_onus = getattr(self.app, '_selected_unregistered_onus', None)
        client = PipelineClient(ui.channel, run, str(power_port),
                                deepcopy(selected_onus() if callable(selected_onus) else ()),
                                bool(getattr(self.app, 'onu_preview_ready', False)))
        ctx.app = client
        ctx.channels = deepcopy(ctx.channels)
        ctx.sample_upgrade_settings = deepcopy(ctx.sample_upgrade_settings)
        ctx.onu_registration = deepcopy(ctx.onu_registration)
        ctx.stop_event = run.stop
        emit = PipelineLogSink(getattr(self.app, 'log_queue', queue.Queue()),
                               [(ORCHESTRATOR_SUBTASK_LABELS[code], label)
                                for code, label in WINDOW_SUBTASK_LABELS.items()])
        self._running_thread = threading.Thread(
            target=run_pipeline,
            args=(ctx, selected, ui.channel, run, emit),
            daemon=True,
            name="pipeline-orchestrator",
        )
        ui.register(self, run, self._running_thread)
        self._running_thread.start()
        self.window.withdraw()
        self._emit_to_main_log(
            "[全流程] 已开始后台执行，全流程配置窗口已自动隐藏；请在主界面查看状态或停止。"
        )

    def is_running(self) -> bool:
        """返回后台全流程线程的真实存活状态。"""
        run = getattr(self, '_run', None)
        pending_cleanup = run is not None and any(not item['event'].is_set() for item in run.subtasks.values())
        return bool((self._running_thread and self._running_thread.is_alive()) or pending_cleanup)

    def _on_pipeline_complete(self, results: List[SubTaskResult]) -> None:
        if getattr(self, '_closed', False):
            return
        self._set_running_ui(False)
        self._update_main_power_test_status(
            "stopped" if self._stop_requested else "completed"
        )
        if self._stop_requested:
            messagebox.showinfo("全流程已停止", "当前子任务已安全退出，后续子任务未执行。", parent=self.app)
            self._refresh_statuses()
            return
        n_ok = sum(1 for r in results if r.ok)
        n_fail = sum(1 for r in results if not r.ok)
        failed_codes = [WINDOW_SUBTASK_LABELS[r.code] for r in results if not r.ok]
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
        if getattr(self, '_closed', False):
            return
        self._set_running_ui(False)
        self._update_main_power_test_status(
            "stopped" if self._stop_requested else "failed"
        )
        if "legacy_power_test" in str(exc):
            summary_builder = getattr(self.app, "_power_test_channel_result_summary", None)
            summary = summary_builder() if callable(summary_builder) else ""
            if summary:
                messagebox.showwarning(
                    "开关机测试完成（存在失败）",
                    summary,
                    parent=self.app,
                )
                self._refresh_statuses()
                return
        messagebox.showerror(
            "全流程执行失败",
            f"全流程异常终止:{exc}",
            parent=self.app,
        )
        self._refresh_statuses()

    def request_stop(self) -> bool:
        """供主界面停止按钮调用；返回是否已向当前编排器发出停止请求。"""
        if self._orchestrator is None:
            if not PipelineWindow.is_running(self):
                return False
        else:
            self._orchestrator.request_stop()
        self._stop_requested = True
        run = getattr(self, '_run', None)
        if run is not None:
            run.cancel()
            for code, name in (('sample_parameter_write', 'parameter_cancel_event'), ('onu_registration', 'onu_cancel_event')):
                if code in run.subtasks:
                    stop = self.app.__dict__.get(name)
                    if stop is not None:
                        stop.set()
        stop_upgrade = getattr(getattr(self, "app", None), "_stop_sample_upgrade", None)
        if callable(stop_upgrade):
            stop_upgrade(from_pipeline=True)
        self._update_main_power_test_status("stopping")
        self._emit_to_main_log(
            "[主界面] 用户点击「停止测试」；全流程将在当前子任务安全退出后终止"
        )
        return True

    def _on_close(self) -> None:
        if self.is_running():
            if not messagebox.askyesno(
                "全流程执行正在进行",
                "全流程仍在运行,确认关闭窗口?操作员在主程序后台线程可能继续运行。",
                parent=self.window,
            ):
                return
            self.request_stop()
        if hasattr(self.app, "pipeline_window"):
            self.app.pipeline_window = None
        self.app._remember_module_window_size(self.window, "pipeline")
        self._dispose()

    def _dispose(self):
        if self._closed:
            return
        self._scope.check()
        self._closed = True
        if self._run is not None:
            if (not self._run.finished.is_set()
                    or any(not item['event'].is_set() for item in self._run.subtasks.values())):
                self._run.cancel()
            self._run.detached = True
        self.window.unbind('<FocusIn>')
        self.window.destroy()
        self._scope.release()
        for mapping in (self._check_vars, self._status_summary_vars, self._status_missing_vars,
                        self._selection_controls, self._status_labels):
            mapping.clear()
        self._start_button = None
        self._orchestrator = None
        self.window = None
        self.app = None

    # -- 辅助 -----------------------------------------------------------

    def _emit_to_main_log(self, line: str) -> None:
        """emit 回调:把编排器日志投到主程序 log_queue(由 app._drain_log_queue 拉取到 log_text)。"""
        # 编排器保留七项兼容编号；当前窗口日志使用三项展示编号。
        for code, label in WINDOW_SUBTASK_LABELS.items():
            line = line.replace(ORCHESTRATOR_SUBTASK_LABELS[code], label)
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

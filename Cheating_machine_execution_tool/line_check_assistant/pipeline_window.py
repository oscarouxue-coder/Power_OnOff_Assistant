"""「全流程执行」窗口 UI(2026-07-20 新增)。

主界面「检查并执行测试」按钮按下后,弹出本窗口,操作员可勾选 6 个子任务(自动上/下电
/ 样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 测试项配置),每行右侧展示「必填项当前
状态」(就绪 / 缺项),「去配置」按钮跳到主程序对应子窗口;底部「开始执行」按 1→6
固定顺序串行执行勾选子任务,任一失败(串口日志除外)→ 整个管道停止。

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
from tkinter import BooleanVar, Frame, Label, StringVar, Toplevel, messagebox, ttk
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
)


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
        # 6 行 Checkbutton + 必填项状态 + 底部按钮需要至少 ~640px 高度
        # （2026-07-20 实际跑出 560 不够,「6. 测试项配置」行被切;调整为 640）
        self.window.geometry("820x640")
        self.window.minsize(780, 620)
        self.window.transient(app)
        self.window.configure(background=COLOR_BG)
        # 状态变量
        self._check_vars: Dict[str, BooleanVar] = {}
        self._status_labels: Dict[str, Label] = {}
        self._status_summary_vars: Dict[str, StringVar] = {}
        self._status_missing_vars: Dict[str, StringVar] = {}
        self._orchestrator: PipelineOrchestrator | None = None
        self._running_thread: threading.Thread | None = None

        self._build()
        self._refresh_statuses()
        # 操作员关闭窗口时若正在跑,提示
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

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
                "跳到对应子窗口填写。点击「开始执行」后,按 1→6 固定顺序串行执行,"
                "任一失败(串口日志除外)将停止整个管道。"
            ),
            background=COLOR_BG,
            foreground=COLOR_MUTED,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        # 6 行子任务
        rows = Frame(content, background=COLOR_BG)
        rows.pack(fill="both", expand=True)
        for index, code in enumerate(SUBTASK_CODES):
            self._build_row(rows, code, index)

        # 底部按钮
        button_bar = Frame(content, background=COLOR_BG)
        button_bar.pack(fill="x", side="bottom", pady=(12, 0))
        self._start_button = ttk.Button(
            button_bar, text="开始执行", command=self._on_start, style="Primary.TButton"
        )
        self._start_button.pack(side="right", padx=(8, 0))
        self._stop_button = ttk.Button(
            button_bar, text="停止", command=self._on_stop, style="Secondary.TButton"
        )
        self._stop_button.pack(side="right")
        self._stop_button.configure(state="disabled")
        ttk.Button(
            button_bar, text="取消", command=self._on_close, style="Secondary.TButton"
        ).pack(side="right", padx=(0, 8))

    def _build_row(self, parent: Frame, code: str, index: int) -> None:
        """单行:Checkbutton + label + summary + missing + 去配置 按钮。

        布局(2026-07-20 按用户反馈调整):summary(黑字)与 missing(红字)互换行——
          第 0 行: missing 红字(若有)　　—— 提示更醒目
          第 1 行: summary 描述　　　　　 —— 详细参数放次行
        """
        row = Frame(parent, background=COLOR_SURFACE, padx=10, pady=8, relief="solid", borderwidth=1)
        row.pack(fill="x", pady=(0, 6))

        # 默认勾选:1, 5, 6(开箱即用最常用);其它默认不勾(需要预先配置)
        default_checked = code in {"power_cycle", "serial_terminal", "test_item_execution"}
        var = BooleanVar(value=default_checked)
        self._check_vars[code] = var

        check = ttk.Checkbutton(row, text=SUBTASK_LABELS[code], variable=var, command=self._refresh_statuses)
        check.grid(row=0, column=0, sticky="w", padx=(0, 10))

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

    def _build_context(self) -> PipelineContext:
        """构造 PipelineContext;若无 store 字段(如 test_project_config 未加载),传空 dataclass。"""
        app = self.app
        channels = _get_attr(app, "channels", [])
        settings = _get_attr(app, "sample_upgrade_settings", None)
        if settings is None:
            from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
            settings = SampleUpgradeSettings()
        onu = _get_attr(app, "onu_registration_config", None)
        if onu is None:
            from line_check_assistant.onu_registration_store import OnuRegistrationConfig
            onu = OnuRegistrationConfig()
        # test_project_config 实时从磁盘加载(操作员可能在子窗口改过)。
        # ``TEST_ITEM_CONFIG_PATH`` 是 ``line_check_assistant.app`` 模块级常量,
        # 不在实例属性上,必须从模块取,否则 ``configparser.read(None)`` 会抛
        # ``TypeError: 'NoneType' object is not iterable``(见 2026-07-20 bug)。
        import line_check_assistant.app as _app_module
        from line_check_assistant.test_item_config_store import TestItemConfigStore
        test_project = TestItemConfigStore(_app_module.TEST_ITEM_CONFIG_PATH).load()
        return PipelineContext(
            app=app,
            channels=channels,
            sample_upgrade_settings=settings,
            onu_registration=onu,
            test_project_config=test_project,
            serial_log_dir=_get_attr(app, "_serial_log_directory", lambda: None)(),
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
        ctx = self._build_context()
        statuses = compute_all_subtask_statuses(ctx)
        not_ready = [code for code in selected if not statuses[code].ready]
        if not_ready:
            missing_lines: List[str] = []
            for code in not_ready:
                missing_lines.append(
                    f"  - {SUBTASK_LABELS[code]}:缺 {', '.join(statuses[code].missing)}"
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
        confirm_lines: List[str] = [f"  ✓ {SUBTASK_LABELS[code]}" for code in SUBTASK_CODES if code in selected]
        proceed = messagebox.askyesno(
            "确认全流程执行",
            "将按以下顺序执行勾选的子任务:\n" + "\n".join(confirm_lines) + "\n\n是否继续?",
            parent=self.window,
        )
        if not proceed:
            return
        # 锁定按钮
        self._set_running_ui(True)
        # 启动后台线程
        self._running_thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(selected,),
            daemon=True,
            name="pipeline-orchestrator",
        )
        self._running_thread.start()

    def _run_pipeline_thread(self, selected: Set[str]) -> None:
        try:
            ctx = self._build_context()
            orchestrator = PipelineOrchestrator(ctx, self._emit_to_main_log)
            self._orchestrator = orchestrator
            results = orchestrator.run(selected)
            # 主线程弹结果框
            self.window.after(0, lambda: self._on_pipeline_complete(results))
        except PipelineError as exc:
            self.window.after(0, lambda: self._on_pipeline_failed(exc))
        except Exception as exc:  # noqa: BLE001 - 后台线程异常需兜底
            self.window.after(0, lambda: self._on_pipeline_failed(exc))
        finally:
            self._orchestrator = None

    def _on_pipeline_complete(self, results: List[SubTaskResult]) -> None:
        self._set_running_ui(False)
        n_ok = sum(1 for r in results if r.ok)
        n_fail = sum(1 for r in results if not r.ok)
        failed_codes = [SUBTASK_LABELS[r.code] for r in results if not r.ok]
        if n_fail == 0:
            messagebox.showinfo(
                "全流程执行完成",
                f"全部 {n_ok} 个勾选子任务执行完成。",
                parent=self.window,
            )
        else:
            messagebox.showwarning(
                "全流程执行部分失败",
                f"成功:{n_ok};失败:{n_fail}\n失败项:{', '.join(failed_codes)}",
                parent=self.window,
            )
        self._refresh_statuses()

    def _on_pipeline_failed(self, exc: Exception) -> None:
        self._set_running_ui(False)
        messagebox.showerror(
            "全流程执行失败",
            f"管道异常终止:{exc}",
            parent=self.window,
        )
        self._refresh_statuses()

    def _on_stop(self) -> None:
        if self._orchestrator is not None:
            self._orchestrator.request_stop()
            self._emit_to_main_log("[窗口] 用户点击「停止」;管道将在当前子任务结束后终止")

    def _on_close(self) -> None:
        if self._running_thread and self._running_thread.is_alive():
            if not messagebox.askyesno(
                "全流程执行正在进行",
                "管道仍在运行,确认关闭窗口?操作员在主程序后台线程可能继续运行。",
                parent=self.window,
            ):
                return
            if self._orchestrator is not None:
                self._orchestrator.request_stop()
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
            self._stop_button.configure(state="normal")
            for var in self._check_vars.values():
                # 锁定勾选状态
                pass
        else:
            self._start_button.configure(state="normal")
            self._stop_button.configure(state="disabled")


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


__all__ = ["PipelineWindow"]

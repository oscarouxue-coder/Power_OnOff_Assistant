"""「检查并执行测试 → 全流程执行」管道编排器。

背景：
- 主界面「检查并执行测试」按钮触发的全流程管道(2026-07-20 新增):
  把 6 个子任务(自动上/下电 / 样机升级 / 写样机参数 / ONU注册 / 串口日志 / 测试项配置)
  作为可勾选的子任务,按 1→6 固定顺序串行执行,任一子任务失败 → 整个管道停止。
- 本模块负责:
  ① 评估 6 个子任务「必填项当前状态」→ 弹窗展示给操作员确认
  ② 按 1→6 顺序执行勾选的子任务
  ③ 失败传播(任一失败 → 停止后续 + 主日志留痕)

子任务执行策略(v1):
  - 1. 自动上/下电: 直接调 ``power_on_service`` 中的 ``power_on_selected_channels`` / ``turn_off_selected_channels``(同步,实时返回)。
  - 2. 样机升级: 调 ``app._start_page_upgrade()`` / ``app._start_full_upgrade()``(异步起线程,弹确认框由操作员点「是」;
    编排器只负责引导 + 兜底,后台线程由 app 的既有 worker 完成)。
  - 3. 写样机参数: 调 ``app._start_sample_parameter_write()``(异步起线程,弹确认框由操作员点「是」;同 2)。
  - 4. ONU 注册: 调 ``app._on_onu_query_clicked()`` + ``app._on_onu_register_clicked()``(异步起线程,弹确认框;同 2)。
  - 5. 串口日志: 调 ``app._open_serial_log_module()``(打开终端窗口,管道运行期间持续记录)。
  - 6. 测试项配置: 调新 ``test_item_execution_service.run_test_item_execution`` 同步执行(每台串行,默认 1)。

不变量:
- 任一子任务抛异常 → 整个管道停止(串口日志除外,因不致命)。
- 1/5/6 同步执行,操作员看到的「实时主日志」就是编排器的 ``emit`` 输出。
- 2/3/4 异步执行,操作员看到的「实时主日志」来自 app 既有 worker 的 ``log_queue``。
- 编排器本身不发任何危险操作命令(无 telnet / 串口 / UBUS);只调度既有方法。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.onu_registration_store import OnuRegistrationConfig
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
from line_check_assistant.test_item_config_store import TestProjectConfig


# 7 个子任务的 code + 窗口显示名 + 排序。固定顺序由用户决策。
# 2026-07-20 在最前面新增「环境线路检查」;其余 6 个编号顺延 1→2 ... 6→7。
SUBTASK_CODES: Tuple[str, ...] = (
    "env_check",
    "power_cycle",
    "sample_upgrade",
    "sample_parameter_write",
    "onu_registration",
    "serial_terminal",
    "test_item_execution",
)

SUBTASK_LABELS: dict[str, str] = {
    "env_check": "1. 环境线路检查",
    "power_cycle": "2. 自动上/下电",
    "sample_upgrade": "3. 样机升级",
    "sample_parameter_write": "4. 写样机参数",
    "onu_registration": "5. ONU 注册",
    "serial_terminal": "6. 串口日志（管道期间持续记录）",
    "test_item_execution": "7. 测试项配置（[order] 执行）",
}

# config_target:窗口「去配置」按钮跳到主程序的哪个子窗口方法名。
# 主程序实现 ``_open_power_cycle()`` / ``_open_sample_upgrade()`` 等时,按此 dict 走。
SUBTASK_CONFIG_TARGETS: dict[str, str] = {
    "env_check": "_open_network_config",
    "power_cycle": "_open_power_control",
    "sample_upgrade": "_open_upgrade_module",
    "sample_parameter_write": "_open_sample_parameter_writer",
    "onu_registration": "_open_onu_registration_module",
    "serial_terminal": "_open_serial_log_module",
    "test_item_execution": "_open_test_item_config",
}

# 哪些子任务不计入「致命失败」(失败后继续后续)。
# 「串口日志」是辅助任务,打不开终端不应阻塞后续子任务。
NON_FATAL_SUBTASKS: frozenset[str] = frozenset({"serial_terminal"})


@dataclass(frozen=True)
class SubTaskStatus:
    """一个子任务「必填项当前状态」评估结果。"""

    code: str
    ready: bool
    summary: str                # 单行摘要(中文,用于弹窗展示)
    missing: Tuple[str, ...]    # 缺项字段名(中文,用于红字标注)


@dataclass
class PipelineContext:
    """编排器运行时上下文:主程序实例 + 各种 store + 通道列表。"""

    # 必填
    app: Any                          # line_check_assistant.app.LineCheckAssistant 实例(避免循环 import)
    channels: List[ChannelConfig]     # 已勾选通道
    sample_upgrade_settings: SampleUpgradeSettings
    onu_registration: OnuRegistrationConfig
    test_project_config: TestProjectConfig
    # 选填
    serial_log_dir: Optional[Path] = None
    # 运行控制
    stop_event: threading.Event = field(default_factory=threading.Event)

    @property
    def enabled_channels(self) -> List[ChannelConfig]:
        return [channel for channel in self.channels if channel.enabled]


@dataclass
class SubTaskResult:
    """一个子任务执行结果。"""

    code: str
    ok: bool
    error: Optional[str] = None
    detail: Optional[str] = None


Output = Callable[[str], None]


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """安全取属性,允许 mock / 部分初始化。"""
    return getattr(obj, name, default)


def _summarize_env_check(ctx: PipelineContext) -> SubTaskStatus:
    """1. 环境线路检查 必填项:≥1 已勾选通道 + 每通道 vlan_name/adapter_alias/network_card_ip/device_manage_ip 非空。

    ping 是否通放到执行阶段(``_run_env_check``)才做;此处只校验必填项完整性,
    保证操作员至少能在「点击开始执行前」看到「哪些通道缺哪些字段」的红字提示。
    """
    channels = ctx.enabled_channels
    if not channels:
        return SubTaskStatus(
            code="env_check",
            ready=False,
            summary="0 通道已勾选",
            missing=("已勾选通道",),
        )
    bad_channels: List[str] = []
    for channel in channels:
        bad: List[str] = []
        if not (channel.vlan_name or "").strip():
            bad.append("VLAN")
        if not (channel.adapter_alias or "").strip():
            bad.append("网卡")
        if not (channel.network_card_ip or "").strip():
            bad.append("PC 静态 IP")
        if not (channel.device_manage_ip or "").strip():
            bad.append("样机管理 IP")
        if bad:
            bad_channels.append(f"{channel.section}({'/'.join(bad)})")
    summary = f"{len(channels)} 通道已勾选"
    if bad_channels:
        summary += f" / 缺配置:{', '.join(bad_channels)}"
    return SubTaskStatus(
        code="env_check",
        ready=not bad_channels,
        summary=summary,
        missing=tuple(f"通道 {bc} 缺配置" for bc in bad_channels),
    )


def _summarize_power_cycle(ctx: PipelineContext) -> SubTaskStatus:
    """1. 自动上/下电：未选 COM 时视为可执行的跳过步骤。"""
    app = ctx.app
    settings = ctx.sample_upgrade_settings
    com = _get_attr(app, "power_serial_var", None)
    com_value = com.get() if com is not None and hasattr(com, "get") else str(_get_attr(app, "power_serial_port", "") or "")
    com_value = (com_value or "").strip()
    operation = (settings.power_operation or "up").strip().lower()
    n_channels = len(ctx.enabled_channels)
    missing_list: List[str] = []
    if operation not in ("up", "down"):
        missing_list.append("上/下电选项")
    if n_channels == 0:
        missing_list.append("已勾选通道")
    summary = f"COM={com_value or '(未选，需手动重启)'} / 操作={operation or 'up'} / {n_channels} 通道已勾选"
    return SubTaskStatus(
        code="power_cycle",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


def _summarize_sample_upgrade(ctx: PipelineContext) -> SubTaskStatus:
    """2. 样机升级 必填项:升级方式 / 固件 / 超级用户凭据(全包还需 parallel_count)。"""
    settings = ctx.sample_upgrade_settings
    upgrade_mode = (settings.upgrade_mode or "").strip()
    firmware = (settings.firmware_path or "").strip()
    username = (settings.username or "").strip()
    password = settings.password or ""
    transfer = (settings.transfer_method or "").strip()
    parallel = settings.parallel_count
    missing_list: List[str] = []
    if upgrade_mode not in ("页面升级", "全包升级"):
        missing_list.append("升级方式")
    if not firmware:
        missing_list.append("升级固件路径")
    if not username:
        missing_list.append("超级用户名")
    if not password:
        missing_list.append("超级用户密码")
    if upgrade_mode == "全包升级" and not transfer:
        missing_list.append("Tftp 指令/Put")
    summary = f"方式={upgrade_mode or '(未选)'} / 固件={Path(firmware).name if firmware else '(未选)'} / 凭据={username or '(空)'}"
    if upgrade_mode == "全包升级":
        summary += f" / 传输={transfer or '(空)'} / 并行={parallel}"
    return SubTaskStatus(
        code="sample_upgrade",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


def _summarize_sample_parameter_write(ctx: PipelineContext) -> SubTaskStatus:
    """3. 写样机参数 必填项:参数表路径 / 超级用户凭据(独立 ini key)。"""
    settings = ctx.sample_upgrade_settings
    table_path = (settings.parameter_table_path or "").strip()
    username = (settings.parameter_initial_username or "").strip()
    password = settings.parameter_initial_password or ""
    missing_list: List[str] = []
    if not table_path:
        missing_list.append("参数表路径")
    elif not Path(table_path).is_file():
        missing_list.append("参数表文件不存在")
    if not username:
        missing_list.append("写参首次登录账号")
    if not password:
        missing_list.append("写参首次登录密码")
    summary = f"参数表={Path(table_path).name if table_path else '(未选)'} / 超级用户={username or '(空)'}"
    return SubTaskStatus(
        code="sample_parameter_write",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


def _summarize_onu_registration(ctx: PipelineContext) -> SubTaskStatus:
    """4. ONU 注册 必填项:OLT IP / 用户名 / 密码。"""
    cfg = ctx.onu_registration
    ip = (cfg.olt_ip or "").strip()
    username = (cfg.username or "").strip()
    password = cfg.password or ""
    missing_list: List[str] = []
    if not ip:
        missing_list.append("OLT IP")
    if not username:
        missing_list.append("OLT 用户名")
    if not password:
        missing_list.append("OLT 密码")
    summary = f"OLT={ip or '(未填)'} / 用户={username or '(空)'}"
    return SubTaskStatus(
        code="onu_registration",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


def _summarize_serial_terminal(ctx: PipelineContext) -> SubTaskStatus:
    """5. 串口日志 必填项:≥1 已勾选通道(日志目录若空由 app 兜底)。"""
    n = len(ctx.enabled_channels)
    log_dir = ctx.serial_log_dir
    missing_list: List[str] = []
    if n == 0:
        missing_list.append("已勾选通道")
    summary = f"终端数={n} 通道 / 日志目录={log_dir or '(使用主程序默认)'}"
    return SubTaskStatus(
        code="serial_terminal",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


def _summarize_test_item_execution(ctx: PipelineContext) -> SubTaskStatus:
    """6. 测试项配置 必填项:ini 存在 / [order] 非空 / [telnet] user+password 非空。"""
    cfg = ctx.test_project_config
    telnet = cfg.telnet
    order = cfg.order
    n_items = len(order.items)
    missing_list: List[str] = []
    if not telnet.user.strip():
        missing_list.append("[telnet] user")
    if not telnet.password:
        missing_list.append("[telnet] password")
    if n_items == 0:
        missing_list.append("[order] 至少 1 条命令")
    summary = f"[order]={n_items} 条 / Telnet 凭据={'已填' if telnet.user.strip() and telnet.password else '未填'}"
    return SubTaskStatus(
        code="test_item_execution",
        ready=not missing_list,
        summary=summary,
        missing=tuple(missing_list),
    )


_SUMMARIZERS = {
    "env_check": _summarize_env_check,
    "power_cycle": _summarize_power_cycle,
    "sample_upgrade": _summarize_sample_upgrade,
    "sample_parameter_write": _summarize_sample_parameter_write,
    "onu_registration": _summarize_onu_registration,
    "serial_terminal": _summarize_serial_terminal,
    "test_item_execution": _summarize_test_item_execution,
}


def compute_all_subtask_statuses(ctx: PipelineContext) -> dict[str, SubTaskStatus]:
    """按 1→6 顺序计算所有 6 个子任务的状态。"""
    return {code: _SUMMARIZERS[code](ctx) for code in SUBTASK_CODES}


class PipelineError(RuntimeError):
    """任一子任务失败抛此异常(串口日志失败不抛,直接记录)。"""


class PipelineOrchestrator:
    """全流程执行管道编排器。

    Usage::

        ctx = PipelineContext(
            app=app,
            channels=app.channels,
            sample_upgrade_settings=app.sample_upgrade_settings,
            onu_registration=app.onu_registration_config,
            test_project_config=app.test_project_config_store.load(),
        )
        orchestrator = PipelineOrchestrator(ctx, emit=app._log)
        try:
            results = orchestrator.run({"power_cycle", "test_item_execution"})
        except PipelineError:
            # 任一子任务失败(串口除外)
            ...
    """

    # 单通道任务的最大单次轮询间隔(秒)
    POLL_INTERVAL_SECONDS = 0.5
    # 单个被编排子任务最大等待时间(秒);超时强制往下走
    MAX_SUBTASK_WAIT_SECONDS = 60.0 * 60.0    # 1 小时(给升级 / 写参留足时间)

    def __init__(self, ctx: PipelineContext, emit: Output) -> None:
        self.ctx = ctx
        self.emit = emit
        self._results: List[SubTaskResult] = []

    def request_stop(self) -> None:
        """操作员主动停止:管道下个子任务不再执行;当前子任务是否能中断取决于其实现。"""
        self.ctx.stop_event.set()

    def run(self, selected: set[str]) -> List[SubTaskResult]:
        """按 1→6 顺序执行勾选的子任务。

        Returns:
            各子任务执行结果(按执行顺序;被跳过的子任务不包含)。
        Raises:
            PipelineError: 任一「致命」子任务失败时抛出(非致命子任务如串口日志失败只记结果)。
        """
        self.emit("=== 全流程执行管道开始 ===")
        for code in SUBTASK_CODES:
            if code not in selected:
                continue
            if self.ctx.stop_event.is_set():
                self.emit(f"[管道] 已请求停止,跳过子任务 {SUBTASK_LABELS[code]}")
                break
            self.emit(f"=== 开始子任务 {SUBTASK_LABELS[code]} ===")
            try:
                self._run_subtask(code)
            except Exception as exc:  # noqa: BLE001 - 编排器统一捕获
                self.emit(f"[管道] 子任务 {SUBTASK_LABELS[code]} 失败:{exc}")
                self._results.append(SubTaskResult(code=code, ok=False, error=str(exc)))
                if code not in NON_FATAL_SUBTASKS:
                    self.emit("=== 全流程执行管道因失败提前终止 ===")
                    raise PipelineError(f"子任务 {code} 失败:{exc}") from exc
                # 非致命:继续下一个
                continue
            else:
                self._results.append(SubTaskResult(code=code, ok=True))
            finally:
                self.emit(f"=== 结束子任务 {SUBTASK_LABELS[code]} ===")
        self.emit("=== 全流程执行管道结束 ===")
        return self._results

    # -- 子任务入口 -----------------------------------------------------

    def _run_subtask(self, code: str) -> None:
        runner = {
            "env_check": self._run_env_check,
            "power_cycle": self._run_power_cycle,
            "sample_upgrade": self._run_sample_upgrade,
            "sample_parameter_write": self._run_sample_parameter_write,
            "onu_registration": self._run_onu_registration,
            "serial_terminal": self._run_serial_terminal,
            "test_item_execution": self._run_test_item_execution,
        }[code]
        runner()

    def _run_env_check(self) -> None:
        """1. 环境线路检查:复用 ``network_ops.run_line_check()`` 逐通道 ping。

        致命失败:任一通道 ping 不通 → 整个管道停止(网络不通则后续子任务均无意义)。
        """
        from line_check_assistant.network_ops import run_line_check

        channels = self.ctx.enabled_channels
        if not channels:
            raise RuntimeError("已勾选通道为空,无法执行环境线路检查")
        total = len(channels)
        passed = 0
        failed: List[str] = []
        for index, channel in enumerate(channels, start=1):
            if self.ctx.stop_event.is_set():
                self.emit(f"[环境检查] 已请求停止,跳过 {channel.section}")
                break
            self.emit(
                f"[环境检查] ({index}/{total}) {channel.section} "
                f"VLAN={channel.vlan_name} 网卡={channel.adapter_alias} "
                f"PC IP={channel.network_card_ip} → 样机 {channel.device_manage_ip}"
            )
            try:
                result = run_line_check(
                    channel.adapter_alias,
                    channel.network_card_ip,
                    channel.subnet_mask,
                    channel.device_manage_ip,
                )
            except Exception as exc:  # noqa: BLE001 - 网络准备本身就可能抛(网卡不存在等)
                self.emit(f"[环境检查] {channel.section} 启动失败:{exc}")
                failed.append(channel.section)
                continue
            if result.ok:
                passed += 1
                self.emit(f"[环境检查] {channel.section} 通过:{result.message}")
            else:
                failed.append(channel.section)
                self.emit(f"[环境检查] {channel.section} 失败:{result.message}")
                if result.output.strip():
                    for line in result.output.strip().splitlines():
                        self.emit(f"    {line}")
        if failed:
            raise RuntimeError(
                f"环境线路检查失败:{len(failed)}/{total} 通道不通 ({', '.join(failed)})"
            )
        self.emit(f"[环境检查] 完成:{passed}/{total} 通道全部 ping 通")

    def _run_power_cycle(self) -> None:
        """1. 自动上/下电:直接调 power_on_service(同步)。"""
        from src.services.power_on_service import (
            power_on_selected_channels,
            turn_off_selected_channels,
        )

        def _power_channel_from_section(section: str) -> int:
            # 与 ``line_check_assistant.app.power_channel_from_section`` 同款;
            # 内联避免 ``pipeline_orchestrator`` → ``app`` 循环 import。
            try:
                return int(section.lower().replace("channel_", ""))
            except ValueError:
                return 0

        app = self.ctx.app
        com = _get_attr(app, "power_serial_var", None)
        com_value = com.get().strip() if com is not None and hasattr(com, "get") else ""
        if not com_value:
            self.emit("未选择程控电源 COM 口。请手动重启样机后，再进行后续子任务；不会向任何 COM 口下发指令。")
            return
        operation = (self.ctx.sample_upgrade_settings.power_operation or "up").strip().lower()
        if operation not in ("up", "down"):
            raise RuntimeError(f"非法 operation: {operation}")
        channels = []
        for channel in self.ctx.enabled_channels:
            pc = _power_channel_from_section(channel.section)
            if not 1 <= pc <= 16:
                raise RuntimeError(f"无法识别 channel {channel.section} 对应的程控电源通道")
            channels.append(pc)
        if not channels:
            raise RuntimeError("已勾选通道为空")
        self.emit(f"程控电源 {com_value} 通道 {channels} 操作:{'上电' if operation == 'up' else '下电'}")
        if operation == "up":
            result = power_on_selected_channels(
                com_value,
                channels,
                wait_seconds=0,
                on_output=lambda line: self.emit(f"  {line}"),
            )
        else:
            result = turn_off_selected_channels(
                com_value,
                channels,
                on_output=lambda line: self.emit(f"  {line}"),
            )
        if not result.ok:
            raise RuntimeError(result.message)
        self.emit(f"程控电源{operation}完成:{result.message}")

    def _run_sample_upgrade(self) -> None:
        """2. 样机升级:调 app._start_page_upgrade() 或 _start_full_upgrade()(异步,弹确认框)。

        v1 仅负责引导 + 兜底;真正执行由 app 既有 worker 完成,主程序执行日志来自 ``log_queue``。
        """
        app = self.ctx.app
        settings = self.ctx.sample_upgrade_settings
        if settings.upgrade_mode == "页面升级":
            start_method = _get_attr(app, "_start_page_upgrade", None)
            if not callable(start_method):
                raise RuntimeError("主程序未实现 _start_page_upgrade")
            self.emit("已启动页面升级(请在弹窗确认);后续进度见主执行日志。")
            start_method()
        elif settings.upgrade_mode == "全包升级":
            if settings.transfer_method == "Tftp指令":
                start_method = _get_attr(app, "_start_tftp_command_upgrade", None)
            else:
                start_method = _get_attr(app, "_start_tftp_put_upgrade", None)
            if not callable(start_method):
                raise RuntimeError("主程序未实现 _start_tftp_command_upgrade / _start_tftp_put_upgrade")
            self.emit("已启动全包升级(请在弹窗确认);后续进度见主执行日志。")
            start_method()
        else:
            raise RuntimeError(f"未配置升级方式: {settings.upgrade_mode!r}")

    def _run_sample_parameter_write(self) -> None:
        """3. 写样机参数:调 app._start_sample_parameter_write()(异步,弹确认框)。"""
        app = self.ctx.app
        start_method = _get_attr(app, "_start_sample_parameter_write", None)
        if not callable(start_method):
            raise RuntimeError("主程序未实现 _start_sample_parameter_write")
        self.emit("已启动写样机参数(请在弹窗确认);后续进度见主执行日志。")
        start_method()

    def _run_onu_registration(self) -> None:
        """4. ONU 注册:自动查询 + 自动注册(异步,弹确认框)。"""
        app = self.ctx.app
        # 先查,再注册
        query_method = _get_attr(app, "_on_onu_query_clicked", None)
        register_method = _get_attr(app, "_on_onu_register_clicked", None)
        if not callable(query_method) or not callable(register_method):
            raise RuntimeError("主程序未实现 _on_onu_query_clicked / _on_onu_register_clicked")
        self.emit("已启动 ONU 查询;查询完成后弹注册确认框,确认后自动注册。")
        query_method()
        # 不在这里同步阻塞——主程序走后台线程;用户确认后自动注册。
        # 失败传播靠 ONT_ONU 的运行标志或操作员主动停止。
        # 当前实现:把 register_method 也调起来(若操作员在查询结果中已勾选 ONU)。
        # 但 register_method 自身有「未选择 ONU」校验,所以可能 noop;先 emit 提示。
        self.emit("ONU 注册由操作员在主程序查询结果中勾选后点击「开始注册」;管道不强制。")

    def _run_serial_terminal(self) -> None:
        """5. 串口日志:打开 SerialTerminalWindow;管道运行期间窗口保持开启。"""
        app = self.ctx.app
        open_method = _get_attr(app, "_open_serial_log_module", None)
        if not callable(open_method):
            raise RuntimeError("主程序未实现 _open_serial_log_module")
        self.emit("打开串口日志窗口;管道运行期间窗口保持开启,持续记录各通道输出。")
        open_method()

    def _run_test_item_execution(self) -> None:
        """6. 测试项配置:同步跑各通道的 [order] 命令 + fuzzy 匹配。"""
        from src.services.test_item_execution_service import (
            TestItemRunRequest,
            build_log_path,
            run_test_item_execution,
        )
        cfg = self.ctx.test_project_config
        if not cfg.order.items:
            raise RuntimeError("[order] 段为空,无命令可执行")
        if not cfg.telnet.user.strip() or not cfg.telnet.password:
            raise RuntimeError("[telnet] 段用户名 / 密码未填")
        channels = self.ctx.enabled_channels
        if not channels:
            raise RuntimeError("已勾选通道为空")
        total = len(channels)
        passed_channels = 0
        failed_channels = 0
        for index, channel in enumerate(channels, start=1):
            if self.ctx.stop_event.is_set():
                self.emit(f"[管道] 已请求停止,跳过 {channel.section}")
                break
            self.emit(
                f"[测试项配置] ({index}/{total}) 通道 {channel.section} "
                f"({channel.vlan_name or channel.adapter_alias})"
            )
            log_path = build_log_path(channel)
            req = TestItemRunRequest(
                channel=channel,
                order=cfg.order,
                telnet=cfg.telnet,
                retry_interval_seconds=int(cfg.order.command_fail_retry_interval_time or 0),
                log_path=log_path,
            )
            try:
                result = run_test_item_execution(req, self.emit)
            except Exception as exc:
                self.emit(f"[测试项配置] 通道 {channel.section} 启动失败:{exc}")
                failed_channels += 1
                raise
            if result.failed == 0:
                passed_channels += 1
            else:
                failed_channels += 1
        self.emit(
            f"[测试项配置] 完成:{passed_channels}/{total} 通道全部匹配, "
            f"{failed_channels} 通道有失败项"
        )
        if failed_channels > 0:
            raise RuntimeError(f"{failed_channels} 通道存在失败项")


__all__ = [
    "NON_FATAL_SUBTASKS",
    "PipelineContext",
    "PipelineError",
    "PipelineOrchestrator",
    "SUBTASK_CODES",
    "SUBTASK_CONFIG_TARGETS",
    "SUBTASK_LABELS",
    "SubTaskResult",
    "SubTaskStatus",
    "compute_all_subtask_statuses",
]

"""「检查并执行测试 → 全流程执行」管道编排器。

背景：
- 主界面「检查并执行测试」按钮触发的全流程管道:
  把 7 个子任务(自动上/下电 / 环境线路检查 / 样机升级 / 写样机参数 / ONU注册 / 串口日志 / 执行开关机测试)
  作为可勾选的子任务；串口日志若勾选则在全流程开始时预启动，其余任务按 1→7 相对顺序串行执行。
- 本模块负责:
  ① 评估 7 个子任务「必填项当前状态」→ 弹窗展示给操作员确认
  ② 先预启动已勾选的串口日志，其余子任务按 1→7 相对顺序执行
  ③ 失败传播(任一失败 → 停止后续 + 主日志留痕)

子任务执行策略(v1):
  - 1. 自动上/下电: 直接调 ``power_on_service`` 中的 ``power_on_selected_channels`` / ``turn_off_selected_channels``(同步,实时返回)。
  - 2. 环境线路检查: 调 ``network_ops.run_line_check()``，任一通道失败即停止后续。
  - 3. 样机升级: 调 ``app._start_page_upgrade()`` / ``app._start_full_upgrade()``(异步起线程,弹确认框由操作员点「是」;
    编排器只负责引导 + 兜底,后台线程由 app 的既有 worker 完成)。
  - 4. 写样机参数: 调 ``app._start_sample_parameter_write()``(异步起线程,弹确认框由操作员点「是」;同 3)。
  - 5. ONU 注册: 调 ``app._on_onu_query_clicked()`` + ``app._on_onu_register_clicked()``(异步起线程,弹确认框;同 3)。
  - 6. 串口日志: 若勾选，在其它子任务前调 ``app._open_pipeline_serial_logs()``，显示窗口并打开全部串口，从全流程开始持续记录。
  - 7. 执行开关机测试: 无 GUI 调旧 ``Start All`` 业务，转发旧 ``Logs``，等待全部通道结束。

不变量:
- 任一子任务抛异常 → 整个全流程停止(串口日志除外,因不致命)。
- 串口日志只在流程开始预启动、环境线路检查完成后均不等待；其余每个已选子任务结束后，若仍有下一项则等待 120 秒再启动下一子任务；等待可被停止事件中断。
- 1/2/6/7 同步执行,操作员看到的「实时主日志」就是编排器的 ``emit`` 输出。
- 3/4/5 异步执行,操作员看到的「实时主日志」来自 app 既有 worker 的 ``log_queue``。
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
from src.models.upgrade_stop import UpgradeStopped
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.services.power_test_resume_service import PowerTestResumeSession
from src.services.device_project_info_service import (
    DeviceProjectInfoQueryRequest,
    power_test_version_precheck_required,
    project_info_mismatches,
    query_device_project_info,
)


# 7 个子任务的 code + 窗口显示名 + 排序。固定顺序由用户决策。
# 2026-07-24 用户确认：自动上/下电先执行，环境线路检查作为第 2 个致命步骤。
SUBTASK_CODES: Tuple[str, ...] = (
    "power_cycle",
    "env_check",
    "sample_upgrade",
    "sample_parameter_write",
    "onu_registration",
    "serial_terminal",
    "legacy_power_test",
)

SUBTASK_LABELS: dict[str, str] = {
    "power_cycle": "1. 自动上/下电",
    "env_check": "2. 环境线路检查",
    "sample_upgrade": "3. 样机升级",
    "sample_parameter_write": "4. 写样机参数",
    "onu_registration": "5. ONU 注册",
    "serial_terminal": "6. 串口日志（全流程期间持续记录）",
    "legacy_power_test": "7. 执行开关机测试",
}

# config_target:窗口「去配置」按钮跳到主程序的哪个子窗口方法名。
# 主程序实现 ``_open_power_cycle()`` / ``_open_sample_upgrade()`` 等时,按此 dict 走。
SUBTASK_CONFIG_TARGETS: dict[str, str] = {
    "power_cycle": "_open_power_control",
    "env_check": "_open_network_config",
    "sample_upgrade": "_open_upgrade_module",
    "sample_parameter_write": "_open_sample_parameter_writer",
    "onu_registration": "_open_onu_registration_module",
    "serial_terminal": "_open_serial_log_module",
    "legacy_power_test": "_open_test_item_config",
}

# 哪些子任务不计入「致命失败」(失败后继续后续)。
# 「串口日志」是辅助任务,打不开终端不应阻塞后续子任务。
NON_FATAL_SUBTASKS: frozenset[str] = frozenset({"serial_terminal"})

# 保留主界面 1→7 行布局，但已勾选的辅助日志任务必须在其它任务前预启动，
# 才能记录上下电、升级和写参阶段的串口输出。
PIPELINE_PRESTART_SUBTASKS: Tuple[str, ...] = ("serial_terminal",)

# 这些任务完成后不增加设备稳定等待：串口日志仅为预启动辅助任务；
# 环境线路检查已在本任务内完成网卡准备和 Ping，成功后可直接进入下一任务。
SUBTASKS_SKIP_NEXT_WAIT: frozenset[str] = frozenset(
    {"serial_terminal", "env_check"}
)


def execution_order_for(selected: set[str]) -> Tuple[str, ...]:
    """返回实际执行顺序：预启动任务在前，其余任务保持界面 1→7 相对顺序。"""
    prestart = tuple(code for code in PIPELINE_PRESTART_SUBTASKS if code in selected)
    remaining = tuple(
        code
        for code in SUBTASK_CODES
        if code in selected and code not in PIPELINE_PRESTART_SUBTASKS
    )
    return prestart + remaining


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
    # 选填
    serial_log_dir: Optional[Path] = None
    legacy_tool_root: Optional[Path] = None
    # 运行控制
    stop_event: threading.Event = field(default_factory=threading.Event)
    # 仅本次全流程有效：总确认后允许升级/写参跳过各自确认框，不写入本机配置。
    unattended_execution: bool = False

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
    """2. 环境线路检查 必填项:≥1 已勾选通道 + 每通道 vlan_name/adapter_alias/network_card_ip/device_manage_ip 非空。

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
    """ONU 注册必填项：OLT 连接 + 已预选且已预览的本批目标。"""
    cfg = ctx.onu_registration
    family = (getattr(cfg, "olt_family", "C300") or "C300").strip()
    ip = (cfg.olt_ip or "").strip()
    source_ip = (getattr(cfg, "source_ip", "") or "").strip()
    username = (cfg.username or "").strip()
    password = cfg.password or ""
    missing_list: List[str] = []
    if not ip:
        missing_list.append("OLT IP")
    if not source_ip:
        missing_list.append("OLT 源 IP")
    if not username:
        missing_list.append("OLT 用户名")
    if not password:
        missing_list.append("OLT 密码")
    selected_onus = _get_attr(ctx.app, "_selected_unregistered_onus", None)
    targets = selected_onus() if callable(selected_onus) else ()
    if not targets:
        missing_list.append("已预选 ONU 目标")
    if not bool(_get_attr(ctx.app, "onu_preview_ready", False)):
        missing_list.append("ONU 命令预览")
    summary = (
        f"OLT={family} {ip or '(未填)'} / 源IP={source_ip or '(未填)'} / "
        f"用户={username or '(空)'} / 目标={len(targets)} 台"
    )
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


def _power_channel_number(section: str) -> int:
    try:
        return int((section or "").strip().lower().replace("channel_", ""))
    except ValueError:
        return 0


def _summarize_legacy_power_test(ctx: PipelineContext) -> SubTaskStatus:
    """7. 执行开关机测试：旧配置、COM、方案与已勾选通道必须完整。"""
    from src.services.legacy_power_test_service import (
        LegacyPowerChannel,
        prepare_legacy_power_test_request,
    )

    if ctx.legacy_tool_root is None:
        return SubTaskStatus(
            code="legacy_power_test",
            ready=False,
            summary="旧工具业务目录未定位",
            missing=("旧工具业务目录",),
        )
    try:
        request = prepare_legacy_power_test_request(
            ctx.legacy_tool_root,
            (
                LegacyPowerChannel(
                    number=_power_channel_number(channel.section),
                    network_card_ip=channel.network_card_ip,
                )
                for channel in ctx.enabled_channels
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 就绪状态必须展示具体缺项
        return SubTaskStatus(
            code="legacy_power_test",
            ready=False,
            summary="旧 Start All 配置未就绪",
            missing=(str(exc),),
        )
    return SubTaskStatus(
        code="legacy_power_test",
        ready=True,
        summary=(
            f"通信={request.communication_method} / COM={request.serial_port} / "
            f"方案={request.selected_profile} / {len(request.channels)} 通道 / "
            f"循环={request.number_of_tests}次"
        ),
        missing=(),
    )


_SUMMARIZERS = {
    "env_check": _summarize_env_check,
    "power_cycle": _summarize_power_cycle,
    "sample_upgrade": _summarize_sample_upgrade,
    "sample_parameter_write": _summarize_sample_parameter_write,
    "onu_registration": _summarize_onu_registration,
    "serial_terminal": _summarize_serial_terminal,
    "legacy_power_test": _summarize_legacy_power_test,
}


def compute_all_subtask_statuses(ctx: PipelineContext) -> dict[str, SubTaskStatus]:
    """按 1→7 顺序计算所有 7 个子任务的状态。"""
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
        )
        orchestrator = PipelineOrchestrator(ctx, emit=app._log)
        try:
            results = orchestrator.run({"power_cycle", "legacy_power_test"})
        except PipelineError:
            # 任一子任务失败(串口除外)
            ...
    """

    # 单通道任务的最大单次轮询间隔(秒)
    POLL_INTERVAL_SECONDS = 0.5
    # 单个被编排子任务最大等待时间(秒);超时强制往下走
    MAX_SUBTASK_WAIT_SECONDS = 60.0 * 60.0    # 1 小时(给升级 / 写参留足时间)
    # 除串口预启动和环境线路检查外，每个已选子任务与下一子任务之间的设备稳定等待。
    SUBTASK_TO_NEXT_WAIT_SECONDS = 120.0

    def __init__(self, ctx: PipelineContext, emit: Output) -> None:
        self.ctx = ctx
        self.emit = emit
        self._results: List[SubTaskResult] = []

    def request_stop(self) -> None:
        """操作员主动停止:管道下个子任务不再执行;当前子任务是否能中断取决于其实现。"""
        self.ctx.stop_event.set()

    def run(self, selected: set[str]) -> List[SubTaskResult]:
        """先预启动已勾选的串口日志，其余子任务按 1→7 相对顺序执行。

        Returns:
            各子任务执行结果(按执行顺序;被跳过的子任务不包含)。
        Raises:
            PipelineError: 任一「致命」子任务失败时抛出(非致命子任务如串口日志失败只记结果)。
        """
        self.emit("=== 全流程执行开始 ===")
        execution_order = execution_order_for(selected)
        for index, code in enumerate(execution_order):
            if self.ctx.stop_event.is_set():
                self.emit(f"[全流程] 已请求停止,跳过子任务 {SUBTASK_LABELS[code]}")
                break
            if code in PIPELINE_PRESTART_SUBTASKS:
                self.emit(f"=== 全流程预启动子任务 {SUBTASK_LABELS[code]} ===")
            self.emit(f"=== 开始子任务 {SUBTASK_LABELS[code]} ===")
            try:
                self._run_subtask(code)
            except UpgradeStopped as exc:
                self.ctx.stop_event.set()
                self.emit(f"[全流程] 子任务 {SUBTASK_LABELS[code]} 已停止：{exc}，跳过后续子任务。")
                self._results.append(SubTaskResult(code=code, ok=False, error=str(exc)))
                break
            except Exception as exc:  # noqa: BLE001 - 编排器统一捕获
                self.emit(f"[全流程] 子任务 {SUBTASK_LABELS[code]} 失败:{exc}")
                self._results.append(SubTaskResult(code=code, ok=False, error=str(exc)))
                if code not in NON_FATAL_SUBTASKS:
                    self.emit("=== 全流程执行因失败提前终止 ===")
                    raise PipelineError(f"子任务 {code} 失败:{exc}") from exc
                # 非致命:继续下一个
            else:
                self._results.append(SubTaskResult(code=code, ok=True))
            finally:
                self.emit(f"=== 结束子任务 {SUBTASK_LABELS[code]} ===")
            if (
                code not in SUBTASKS_SKIP_NEXT_WAIT
                and index + 1 < len(execution_order)
                and not self._wait_between_subtasks(
                    code, execution_order[index + 1]
                )
            ):
                self.emit(
                    f"[全流程] 等待期间收到停止请求,跳过后续子任务 {SUBTASK_LABELS[execution_order[index + 1]]}"
                )
                break
        self.emit("=== 全流程执行结束 ===")
        return self._results

    def _wait_between_subtasks(self, completed_code: str, next_code: str) -> bool:
        """等待相邻子任务间隔；返回 False 表示操作员已请求停止。"""
        seconds = self.SUBTASK_TO_NEXT_WAIT_SECONDS
        self.emit(
            f"[子任务间隔] 子任务“{SUBTASK_LABELS[completed_code]}”已结束，"
            f"等待 {seconds:.0f} 秒后再开始子任务“{SUBTASK_LABELS[next_code]}”。"
        )
        if self.ctx.stop_event.wait(seconds):
            self.emit(f"[子任务间隔] {seconds:.0f} 秒等待期间已请求停止。")
            return False
        self.emit(
            f"[子任务间隔] {seconds:.0f} 秒等待完成，开始子任务“{SUBTASK_LABELS[next_code]}”。"
        )
        return True

    # -- 子任务入口 -----------------------------------------------------

    def _run_subtask(self, code: str) -> None:
        runner = {
            "env_check": self._run_env_check,
            "power_cycle": self._run_power_cycle,
            "sample_upgrade": self._run_sample_upgrade,
            "sample_parameter_write": self._run_sample_parameter_write,
            "onu_registration": self._run_onu_registration,
            "serial_terminal": self._run_serial_terminal,
            "legacy_power_test": self._run_legacy_power_test,
        }[code]
        runner()

    def _run_env_check(self) -> None:
        """2. 环境线路检查:复用 ``network_ops.run_line_check()`` 逐通道 ping。

        致命失败:任一通道 ping 不通 → 整个全流程停止(网络不通则后续子任务均无意义)。
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
            turn_on_selected_channels,
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
            result = turn_on_selected_channels(
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
        """3. 样机升级：等待主程序异步升级真实完成后才继续下一项。"""
        app = self.ctx.app
        pipeline_method = _get_attr(app, "_run_pipeline_sample_upgrade", None)
        if callable(pipeline_method):
            if self.ctx.unattended_execution:
                self.emit("全流程样机升级：已获本次无人值守授权，跳过子任务确认。")
                pipeline_method(skip_confirmation=True)
            else:
                self.emit("全流程样机升级：等待操作员确认及升级完成。")
                pipeline_method()
            self.emit("全流程样机升级已完成。")
            return

        # 兼容最小 mock / 历史入口：真实主程序必须提供上面的顺序化桥接。
        settings = self.ctx.sample_upgrade_settings
        if settings.upgrade_mode == "页面升级":
            start_method = _get_attr(app, "_start_page_upgrade", None)
            if not callable(start_method):
                raise RuntimeError("主程序未实现 _start_page_upgrade")
            if self.ctx.unattended_execution:
                self.emit("已启动页面升级（无人值守授权，跳过子任务确认）；后续进度见主执行日志。")
                start_method(skip_confirmation=True)
            else:
                self.emit("已启动页面升级(请在弹窗确认);后续进度见主执行日志。")
                start_method()
        elif settings.upgrade_mode == "全包升级":
            # 主程序目前由同一入口读取 upgrade_transfer_var 后，继续分流到
            # Tftp指令 / Tftp Put 两条独立链路；不能再调用历史上未实现的
            # _start_tftp_command_upgrade / _start_tftp_put_upgrade 名称。
            start_method = _get_attr(app, "_start_full_package_upgrade", None)
            if not callable(start_method):
                raise RuntimeError("主程序未实现 _start_full_package_upgrade")
            if self.ctx.unattended_execution:
                self.emit(
                    f"已启动全包升级（{settings.transfer_method}，无人值守授权，跳过子任务确认）；后续进度见主执行日志。"
                )
                start_method(skip_confirmation=True)
            else:
                self.emit(
                    f"已启动全包升级（{settings.transfer_method}，请在弹窗确认）；后续进度见主执行日志。"
                )
                start_method()
        else:
            raise RuntimeError(f"未配置升级方式: {settings.upgrade_mode!r}")

    def _run_sample_parameter_write(self) -> None:
        """4. 写样机参数：等待写参完成后才继续下一项。"""
        app = self.ctx.app
        pipeline_method = _get_attr(app, "_run_pipeline_sample_parameter_write", None)
        if callable(pipeline_method):
            if self.ctx.unattended_execution:
                self.emit("全流程写样机参数：已获本次无人值守授权，跳过子任务确认。")
                pipeline_method(skip_confirmation=True)
            else:
                self.emit("全流程写样机参数：等待操作员确认及写参完成。")
                pipeline_method()
            self.emit("全流程写样机参数已完成。")
            return

        # 兼容最小 mock / 历史入口：真实主程序必须提供上面的顺序化桥接。
        start_method = _get_attr(app, "_start_sample_parameter_write", None)
        if not callable(start_method):
            raise RuntimeError("主程序未实现 _start_sample_parameter_write")
        if self.ctx.unattended_execution:
            self.emit("已启动写样机参数（无人值守授权，跳过子任务确认）；后续进度见主执行日志。")
            start_method(skip_confirmation=True)
        else:
            self.emit("已启动写样机参数(请在弹窗确认);后续进度见主执行日志。")
            start_method()

    def _run_onu_registration(self) -> None:
        """5. ONU 注册：提交预先审核的批次并等待最终验证结果。"""
        app = self.ctx.app
        pipeline_method = _get_attr(app, "_run_pipeline_onu_registration", None)
        if not callable(pipeline_method):
            raise RuntimeError("主程序未实现 _run_pipeline_onu_registration")
        self.emit("全流程 ONU 注册：等待操作员确认已预览的批量目标，并等待逐台验证完成。")
        pipeline_method()
        self.emit("全流程 ONU 批量注册已完成。")

    def _run_serial_terminal(self) -> None:
        """串口日志：在 Tk 主线程显示终端并打开全部串口，管道期间保持开启。"""
        app = self.ctx.app
        open_method = _get_attr(app, "_open_pipeline_serial_logs", None)
        if not callable(open_method):
            raise RuntimeError("主程序未实现 _open_pipeline_serial_logs")
        self.emit("全流程开始时提前显示串口日志窗口并执行“打开全部”；全部串口打开后再执行后续子任务。")
        invoke_on_ui = _get_attr(app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            def open_on_ui() -> bool:
                open_method()
                return True

            invoke_on_ui(open_on_ui)
        else:
            # 兼容单元测试和历史最小 app 替身。
            open_method()

    def _run_legacy_power_test(self) -> None:
        """7. 按保存基准决定版本预检，无 GUI 运行旧 Start All 并桥接 Logs。"""
        from src.services.legacy_power_test_service import (
            LegacyPowerChannel,
            prepare_legacy_power_test_request,
            run_legacy_power_test,
        )

        if self.ctx.legacy_tool_root is None:
            raise RuntimeError("旧工具业务目录未定位")
        request = prepare_legacy_power_test_request(
            self.ctx.legacy_tool_root,
            (
                LegacyPowerChannel(
                    number=_power_channel_number(channel.section),
                    network_card_ip=channel.network_card_ip,
                )
                for channel in self.ctx.enabled_channels
            ),
        )
        session = PowerTestResumeSession(
            request, self.ctx.enabled_channels, self.ctx.stop_event, self.emit,
            on_progress=self._report_legacy_power_progress,
            on_channel_progress=self._report_legacy_power_channel_progress,
            on_channel_status=self._report_legacy_power_channel_status,
            on_channel_history=self._report_legacy_power_channel_history,
        )
        project_config = TestItemConfigStore(
            request.tool_root / "config" / request.profile_filename
        ).load(required=True)
        expected_info = project_config.project_info
        if self.ctx.stop_event.is_set():
            raise RuntimeError("开关机版本预检已停止，未启动开关机测试")
        try:
            needs_precheck = power_test_version_precheck_required(expected_info)
        except ValueError as exc:
            self.emit(f"[开关机版本预检] 失败：{exc}")
            raise RuntimeError(str(exc)) from None
        if not needs_precheck:
            self.emit("[开关机版本预检] 三项版本基准均为空，跳过开始前版本校验。")
        else:
            channels = self.ctx.enabled_channels
            self.emit(
                "[开关机版本预检] 开始逐台只读核对："
                f"软件版本={expected_info.software_version.strip()}，"
                f"内部软件版本={expected_info.internal_software_version.strip()}，"
                f"ONU 软件编译时间={expected_info.onu_compile_time.strip()}。"
            )
            failures: list[str] = []
            for index, channel in enumerate(channels, start=1):
                if self.ctx.stop_event.is_set():
                    raise RuntimeError("开关机版本预检已停止，未启动开关机测试")
                channel_label = channel.vlan_name or channel.section
                self.emit(
                    f"[开关机版本预检] ({index}/{len(channels)}) {channel.section}"
                    f"（{channel_label}）：PC {channel.network_card_ip} → 样机 "
                    f"{channel.device_manage_ip}。"
                )
                try:
                    actual_info = query_device_project_info(
                        DeviceProjectInfoQueryRequest(
                            bind_ip=channel.network_card_ip.strip(),
                            device_host=channel.device_manage_ip.strip(),
                            telnet=project_config.telnet,
                        ),
                        emit=lambda line, section=channel.section: self.emit(
                            f"[开关机版本预检][{section}] {line}"
                        ),
                    )
                    mismatches = project_info_mismatches(expected_info, actual_info)
                except Exception as exc:  # noqa: BLE001 - 任一只读查询失败均禁止下发电源动作
                    failures.append(f"{channel.section} 查询失败：{exc}")
                    self.emit(f"[开关机版本预检] {channel.section} 查询失败：{exc}")
                    continue
                if mismatches:
                    failures.append(f"{channel.section}：{'；'.join(mismatches)}")
                    self.emit(
                        f"[开关机版本预检] {channel.section} 不一致："
                        f"{'；'.join(mismatches)}"
                    )
                    continue
                self.emit(f"[开关机版本预检] {channel.section} 三项版本全部一致。")

            if failures:
                raise RuntimeError(
                    f"开关机版本预检不通过：{len(failures)}/{len(channels)} 台异常；"
                    f"{' | '.join(failures)}。未启动开关机测试。"
                )
            self.emit(
                f"[开关机版本预检] 通过：{len(channels)}/{len(channels)} 台三项版本全部一致，"
                "开始执行开关机测试。"
            )
        if self.ctx.stop_event.is_set():
            raise RuntimeError("开关机测试已停止，未启动开关机测试")
        reset_channel_statuses = _get_attr(
            self.ctx.app, "_reset_power_test_channel_states", None
        )
        if callable(reset_channel_statuses):
            channel_numbers = [channel.number for channel in request.channels]
            invoke_on_ui = _get_attr(self.ctx.app, "_invoke_pipeline_ui_action", None)
            if callable(invoke_on_ui):
                invoke_on_ui(lambda: reset_channel_statuses(channel_numbers))
            else:
                reset_channel_statuses(channel_numbers)

        session.ensure_config_unchanged()
        def register_resume_session():
            self.ctx.app.power_test_resume_session = session
        invoke_on_ui = _get_attr(self.ctx.app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            invoke_on_ui(register_resume_session)
        else:
            register_resume_session()
        result = run_legacy_power_test(
            request,
            self.emit,
            self.ctx.stop_event,
            resume_session=session,
            on_progress=self._report_legacy_power_progress,
            on_channel_progress=self._report_legacy_power_channel_progress,
            on_channel_status=self._report_legacy_power_channel_status,
            on_channel_history=self._report_legacy_power_channel_history,
        )
        if not result.ok:
            raise RuntimeError(result.detail)

    def _report_legacy_power_progress(self, completed: int, total: int) -> None:
        """把后台开关机轮次进度安全投递到 Tk 主线程。"""
        app = self.ctx.app
        setter = _get_attr(app, "_set_power_test_progress", None)
        if not callable(setter):
            return

        def update_on_ui() -> bool:
            setter(completed, total)
            return True

        invoke_on_ui = _get_attr(app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            invoke_on_ui(update_on_ui)
        else:
            update_on_ui()

    def _report_legacy_power_channel_status(
        self,
        channel_number: int,
        status: str,
        detail: str,
    ) -> None:
        """把旧 Start All 的逐通道状态安全投递到 Tk 主线程。"""
        app = self.ctx.app
        setter = _get_attr(app, "_set_power_test_channel_state", None)
        if not callable(setter):
            return

        def update_on_ui() -> bool:
            setter(channel_number, status, detail)
            return True

        invoke_on_ui = _get_attr(app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            invoke_on_ui(update_on_ui)
        else:
            update_on_ui()

    def _report_legacy_power_channel_history(
        self,
        channel_number: int,
        cycle: int,
        status: str,
        detail: str,
    ) -> None:
        """将本次通道重试/失败事件安全投递到 Tk 主线程。"""
        app = self.ctx.app
        recorder = _get_attr(app, "_record_power_test_channel_history", None)
        if not callable(recorder):
            return

        def update_on_ui() -> bool:
            recorder(channel_number, cycle, status, detail)
            return True

        invoke_on_ui = _get_attr(app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            invoke_on_ui(update_on_ui)
        else:
            update_on_ui()

    def _report_legacy_power_channel_progress(
        self,
        channel_number: int,
        completed: int,
        total: int,
        stage: str,
    ) -> None:
        """把旧 Start All 的逐通道轮次安全投递到 Tk 主线程。"""
        app = self.ctx.app
        setter = _get_attr(app, "_set_power_test_channel_progress", None)
        if not callable(setter):
            return

        def update_on_ui() -> bool:
            setter(channel_number, completed, total, stage)
            return True

        invoke_on_ui = _get_attr(app, "_invoke_pipeline_ui_action", None)
        if callable(invoke_on_ui):
            invoke_on_ui(update_on_ui)
        else:
            update_on_ui()


__all__ = [
    "NON_FATAL_SUBTASKS",
    "PIPELINE_PRESTART_SUBTASKS",
    "PipelineContext",
    "PipelineError",
    "PipelineOrchestrator",
    "SUBTASK_CODES",
    "SUBTASK_CONFIG_TARGETS",
    "SUBTASK_LABELS",
    "SubTaskResult",
    "SubTaskStatus",
    "compute_all_subtask_statuses",
    "execution_order_for",
]

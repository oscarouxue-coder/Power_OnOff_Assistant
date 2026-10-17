"""按开关机测试实际选定方案生成登录后命令的确认摘要。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.services.legacy_power_test_service import (
    LegacyPowerChannel,
    prepare_legacy_power_test_request,
)
from src.services.telnet_post_login_service import describe_telnet_post_login
from src.services.device_project_info_service import power_test_version_precheck_required

if TYPE_CHECKING:
    from src.services.pipeline_orchestrator import PipelineContext


def describe_legacy_power_telnet_post_login(ctx: PipelineContext) -> str:
    """只读复用运行时方案选择；加载失败时不以默认命令代替实际配置。"""
    from src.services.pipeline_orchestrator import _power_channel_number

    try:
        if ctx.legacy_tool_root is None:
            raise ValueError("旧工具目录未定位")
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
        profile_path = request.tool_root / "config" / request.profile_filename
        config = TestItemConfigStore(profile_path).load(required=True)
    except Exception:  # 不在确认框泄露可能包含凭据的 INI 解析异常原文。
        return (
            "登录后命令配置未能读取；开关机测试将按现有版本预检报错并停止，"
            "不会改用默认登录后命令。"
        )
    try:
        needs_precheck = power_test_version_precheck_required(config.project_info)
    except ValueError as exc:
        return f"方案 {request.selected_profile}：{exc} 未启动开关机测试。"
    if not needs_precheck:
        return (
            f"方案 {request.selected_profile}：三项版本基准均为空，跳过开始前版本校验。"
            "不执行预检登录及版本查询。"
        )
    return (
        f"方案 {request.selected_profile}：执行三项版本预检；"
        f"{describe_telnet_post_login(config.telnet)}"
    )


__all__ = ["describe_legacy_power_telnet_post_login"]

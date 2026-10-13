"""按开关机测试实际选定方案生成登录后命令的确认摘要。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.services.legacy_power_test_service import (
    LegacyPowerChannel,
    prepare_legacy_power_test_request,
)
from src.services.telnet_post_login_service import describe_telnet_post_login

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
        # Store.load 历史上允许缺文件回退默认值。确认摘要必须先确认可读，
        # 才能描述将下发的实际命令；这里不创建、修改文件或连接设备。
        with profile_path.open("r", encoding="utf-8") as profile_file:
            profile_file.read()
        config = TestItemConfigStore(profile_path).load()
        if not profile_path.is_file():
            raise FileNotFoundError("选定测试方案已不存在")
    except Exception:  # 不在确认框泄露可能包含凭据的 INI 解析异常原文。
        return (
            "登录后命令配置未能读取；开关机测试将按现有版本预检报错并停止，"
            "不会改用默认登录后命令。"
        )
    return f"方案 {request.selected_profile}：{describe_telnet_post_login(config.telnet)}"


__all__ = ["describe_legacy_power_telnet_post_login"]

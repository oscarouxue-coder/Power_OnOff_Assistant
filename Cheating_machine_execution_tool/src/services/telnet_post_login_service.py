"""按测试项配置下发 Telnet 登录后的单条指令。"""
from __future__ import annotations

from typing import Callable

from line_check_assistant.test_item_config_store import TelnetSettings


POST_LOGIN_WAIT_SECONDS = 1.0
Output = Callable[[str], None]


def describe_telnet_post_login(telnet: TelnetSettings) -> str:
    """供确认摘要说明本次登录后的实际下发行为。"""
    if telnet.login_success_flag != ">":
        return "登录后指令：跳过（登录成功提示符不是 >）。"
    command = (telnet.login_after_input_str or "").strip()
    action = command if command else "仅回车（配置为空）"
    return f"登录后指令：{action}；成功提示符为 > 时下发一次，随后等待 1 秒。"


def run_telnet_post_login(
    session,
    telnet: TelnetSettings,
    emit: Output,
    sleep_fn: Callable[[float], None],
) -> None:
    """成功提示符严格为 > 时发送一次；不判断是否已进入 Shell。"""
    if telnet.login_success_flag != ">":
        emit("[Telnet 登录后] 登录成功提示符不是 >，跳过登录后指令。")
        return
    command = (telnet.login_after_input_str or "").strip()
    action = command if command else "仅回车（配置为空）"
    emit(f"[Telnet 登录后] 准备下发：{action}")
    try:
        session.send_line(command, sensitive=False)
    except (OSError, RuntimeError):
        emit("[Telnet 登录后] 下发失败，停止后续操作。")
        raise
    emit(f"[Telnet 登录后] 已下发：{action}；等待 1 秒。")
    sleep_fn(POST_LOGIN_WAIT_SECONDS)
    emit("[Telnet 登录后] 缓冲等待完成，继续后续操作。")


__all__ = ["describe_telnet_post_login", "run_telnet_post_login"]

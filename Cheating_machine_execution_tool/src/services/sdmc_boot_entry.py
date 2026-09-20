"""独立的免凭据 SDMC Boot 进入流程。"""
import time
import re
from line_check_assistant.network_ops import CommandResult


def boot_prompt_from_output(output):
    """Only prompt lines count; boot hash/partition diagnostics are not prompts."""
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output).replace("\r", "\n")
    for line in reversed(output.splitlines()):
        match = re.fullmatch(r"\s*(=>|ecnt>|u-boot>|#|>)\s*(?:sdmc\s*)?", line, re.I)
        if match:
            return match.group(1).lower()
    return None


def enter_sdmc_boot(session, cancel, on_output, *, timeout_seconds=600, clock=time.monotonic):
    """只观察本轮新数据；每秒发送 sdmc + CR，命中提示即停止。"""
    markers = ("=>", "ecnt>", "u-boot>", "#", ">")
    cursor = session.cursor()
    deadline = clock() + timeout_seconds
    on_output("开始 SDMC 进入 Boot：每 1 秒发送 sdmc + 回车，跳过 Boot 账号密码登录。")

    def read_prompt():
        marker = boot_prompt_from_output(session.peek_since(cursor))
        if marker in ("#", ">"):
            # A split '## Checking ...' must not pass when only its first '#'
            # has arrived. Give the short, ambiguous prompt a stability window.
            session.wait_for_any(("\n", "\r"), min(0.1, max(0, deadline - clock())), session.cursor())
            marker = boot_prompt_from_output(session.peek_since(cursor))
        return marker

    try:
        while not cancel.is_set() and clock() < deadline:
            marker = read_prompt()
            if marker:
                on_output(f"SDMC 进入 Boot 成功，命中提示符：{marker}")
                return CommandResult(True, "SDMC 进入 Boot 成功。")
            session.write(b"sdmc\r")
            on_output("TX sdmc [回车]")
            next_send = min(clock() + 1.0, deadline)
            while not cancel.is_set():
                remaining = next_send - clock()
                if remaining <= 0:
                    break
                # Poll only new bytes, but parse the accumulated text so split
                # prompts still match and old diagnostic '#' cannot busy-loop.
                poll_cursor = session.cursor()
                session.wait_for_any(markers, min(0.1, remaining), poll_cursor)
                marker = read_prompt()
                if marker:
                    on_output(f"SDMC 进入 Boot 成功，命中提示符：{marker}")
                    return CommandResult(True, "SDMC 进入 Boot 成功。")
    except Exception as exc:
        result = CommandResult(False, f"SDMC 进入 Boot 串口异常：{exc}")
    else:
        result = CommandResult(False, "SDMC 进入 Boot 已取消。" if cancel.is_set()
                               else f"SDMC 进入 Boot 超时（{timeout_seconds:g} 秒）。")
    on_output(result.message)
    return result

"""独立的免凭据 SDMC Boot 进入流程。"""
import time
from line_check_assistant.network_ops import CommandResult


def enter_sdmc_boot(session, cancel, on_output, *, timeout_seconds=600, clock=time.monotonic):
    """只观察本轮新数据；每秒发送 sdmc + CR，命中提示即停止。"""
    markers = ("=>", "ecnt>", "u-boot>", "#", ">")
    cursor = session.cursor()
    deadline = clock() + timeout_seconds
    on_output("开始 SDMC 进入 Boot：每 1 秒发送 sdmc + 回车，跳过 Boot 账号密码登录。")
    try:
        while not cancel.is_set() and clock() < deadline:
            marker = session.wait_for_any(markers, 0, cursor)
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
                marker = session.wait_for_any(markers, min(0.1, remaining), cursor)
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

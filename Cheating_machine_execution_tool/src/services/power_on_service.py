from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from line_check_assistant.network_ops import CommandResult
from src.core.power_supply import POWER_SUPPLY_BAUDRATE, ProgrammablePowerSupply, SerialFactory, channel_power_frame


def power_on_selected_channels(
    serial_port: str,
    channels: Iterable[int],
    *,
    wait_seconds: float = 0,
    on_output: Callable[[str], None] | None = None,
    on_channel_powered: Callable[[int], None] | None = None,
    serial_factory: SerialFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> CommandResult:
    """直接按旧工具协议上电指定通道，不启动 Auto_Power_On_Off_Tool GUI。"""

    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    started_at = monotonic_fn()
    try:
        selected_channels = list(channels)
        if not selected_channels:
            raise ValueError("至少需要选择一个程控电源通道。")
        for channel in selected_channels:
            channel_power_frame(channel, True)
        options = {
            "baudrate": POWER_SUPPLY_BAUDRATE,
            "sleep_fn": sleep_fn,
            "on_output": emit,
        }
        if serial_factory is not None:
            options["serial_factory"] = serial_factory
        with ProgrammablePowerSupply(serial_port, **options) as supply:
            selected = supply.power_on_channels(selected_channels, on_channel_powered=on_channel_powered)
        remaining = max(0.0, float(wait_seconds) - (monotonic_fn() - started_at))
        if remaining:
            emit(f"程控电源指令已完成，继续等待样机启动：{remaining:.1f} 秒。")
            sleep_fn(remaining)
        channel_text = "、".join(str(channel) for channel in selected)
        return CommandResult(True, f"程控电源已直接上电：{serial_port.upper()}，通道 {channel_text}。")
    except Exception as exc:
        return CommandResult(False, f"程控电源直接上电失败：{exc}")


def turn_on_selected_channels(
    serial_port: str,
    channels: Iterable[int],
    *,
    wait_seconds: float = 0,
    on_output: Callable[[str], None] | None = None,
    on_channel_powered: Callable[[int], None] | None = None,
    serial_factory: SerialFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    """间隔开启指定通道，不执行断电或单通道关闭。"""
    return _set_selected_channels_power(
        serial_port,
        channels,
        powered_on=True,
        wait_seconds=wait_seconds,
        on_output=on_output,
        on_channel_powered=on_channel_powered,
        serial_factory=serial_factory,
        sleep_fn=sleep_fn,
    )


def turn_off_selected_channels(
    serial_port: str,
    channels: Iterable[int],
    *,
    on_output: Callable[[str], None] | None = None,
    serial_factory: SerialFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:
    """间隔关闭指定通道，不执行全断电。"""
    return _set_selected_channels_power(
        serial_port,
        channels,
        powered_on=False,
        on_output=on_output,
        serial_factory=serial_factory,
        sleep_fn=sleep_fn,
    )


def _set_selected_channels_power(
    serial_port: str,
    channels: Iterable[int],
    *,
    powered_on: bool,
    wait_seconds: float = 0,
    on_output: Callable[[str], None] | None = None,
    on_channel_powered: Callable[[int], None] | None = None,
    serial_factory: SerialFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandResult:

    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    try:
        selected_channels = list(channels)
        if not selected_channels:
            raise ValueError("至少需要选择一个程控电源通道。")
        for channel in selected_channels:
            channel_power_frame(channel, powered_on)
        options = {
            "baudrate": POWER_SUPPLY_BAUDRATE,
            "sleep_fn": sleep_fn,
            "on_output": emit,
        }
        if serial_factory is not None:
            options["serial_factory"] = serial_factory
        with ProgrammablePowerSupply(serial_port, **options) as supply:
            if powered_on:
                selected = supply.turn_on_channels(selected_channels, on_channel_powered=on_channel_powered)
            else:
                selected = supply.turn_off_channels(selected_channels)
        startup_wait = max(0.0, float(wait_seconds))
        if startup_wait:
            emit(f"全部{'开启' if powered_on else '关闭'}指令已完成，继续等待：{startup_wait:.1f} 秒。")
            sleep_fn(startup_wait)
        channel_text = "、".join(str(channel) for channel in selected)
        action = "上电" if powered_on else "下电"
        return CommandResult(True, f"程控电源已{action}：{serial_port.upper()}，通道 {channel_text}。")
    except Exception as exc:
        action = "上电" if powered_on else "下电"
        return CommandResult(False, f"程控电源{action}失败：{exc}")

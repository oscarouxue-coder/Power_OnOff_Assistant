from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from typing import Protocol

import serial


POWER_SUPPLY_BAUDRATE = 19200
POWER_ON_FRAME_INTERVAL_SECONDS = 1
ALL_CHANNELS_OFF_FRAME = bytes((0x55, 0x00, 0xAD, 0x00, 0x00, 0xAD))


class SerialPort(Protocol):
    def write(self, data: bytes) -> int:
        ...

    def close(self) -> None:
        ...


SerialFactory = Callable[..., SerialPort]
OutputCallback = Callable[[str], None]
ChannelPoweredCallback = Callable[[int], None]


class PowerSupplyError(RuntimeError):
    """程控电源串口通信失败。"""


def channel_power_frame(channel: int, powered_on: bool) -> bytes:
    """返回旧 Auto_Power_On_Off_Tool 使用的单通道开关帧。"""
    if not 1 <= channel <= 16:
        raise ValueError(f"程控电源通道必须在 1-16：{channel}")
    command = 0xA0 if powered_on else 0xA1
    checksum = (0xA1 if powered_on else 0xA0) ^ channel
    return bytes((0x55, 0x01, command, 0x00, channel, checksum))


class ProgrammablePowerSupply:
    """无界面程控电源控制器，协议与旧 Auto_Power_On_Off_Tool 保持一致。"""

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = POWER_SUPPLY_BAUDRATE,
        serial_factory: SerialFactory = serial.Serial,
        sleep_fn: Callable[[float], None] = time.sleep,
        on_output: OutputCallback | None = None,
    ) -> None:
        normalized_port = port.strip().upper()
        if not re.fullmatch(r"COM\d+", normalized_port):
            raise ValueError(f"程控电源串口格式不正确：{port}")
        if baudrate <= 0:
            raise ValueError(f"程控电源波特率必须为正数：{baudrate}")
        self.port = normalized_port
        self.baudrate = baudrate
        self._serial_factory = serial_factory
        self._sleep = sleep_fn
        self._on_output = on_output
        self._serial: SerialPort | None = None

    def __enter__(self) -> "ProgrammablePowerSupply":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            self._serial = self._serial_factory(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,
                write_timeout=2,
            )
        except Exception as exc:
            raise PowerSupplyError(f"打开程控电源串口 {self.port} 失败：{exc}") from exc
        self._emit(f"已打开程控电源串口：{self.port}，{self.baudrate} 8N1。")

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
            self._emit(f"已关闭程控电源串口：{self.port}。")
        finally:
            self._serial = None

    def power_on_channels(
        self,
        channels: Iterable[int],
        *,
        on_channel_powered: ChannelPoweredCallback | None = None,
    ) -> list[int]:
        selected = _normalize_channels(channels)
        self.open()
        self._write_frame(ALL_CHANNELS_OFF_FRAME, "关闭全部程控电源通道")
        self._sleep(0.5)
        for channel in selected:
            self._write_frame(channel_power_frame(channel, False), f"关闭通道 {channel}")
            self._sleep(1.5)
            self._write_frame(channel_power_frame(channel, True), f"开启通道 {channel}")
            if on_channel_powered:
                on_channel_powered(channel)
            # 与旧工具 PowerOnOff.power_on() 的 3 秒稳定等待保持一致。
            self._sleep(3)
        return selected

    def turn_on_channels(
        self,
        channels: Iterable[int],
        *,
        on_channel_powered: ChannelPoweredCallback | None = None,
    ) -> list[int]:
        """仅开启指定通道，不发送任何关闭或全断电指令。"""
        return self._set_channels_power(channels, powered_on=True, on_channel_powered=on_channel_powered)

    def turn_off_channels(self, channels: Iterable[int]) -> list[int]:
        """仅关闭指定通道，不发送全断电指令。"""
        return self._set_channels_power(channels, powered_on=False)

    def _set_channels_power(
        self,
        channels: Iterable[int],
        *,
        powered_on: bool,
        on_channel_powered: ChannelPoweredCallback | None = None,
    ) -> list[int]:
        selected = _normalize_channels(channels)
        self.open()
        for index, channel in enumerate(selected):
            if index:
                self._sleep(POWER_ON_FRAME_INTERVAL_SECONDS)
            action = "开启" if powered_on else "关闭"
            self._write_frame(channel_power_frame(channel, powered_on), f"{action}通道 {channel}")
            if powered_on and on_channel_powered:
                on_channel_powered(channel)
        return selected

    def _write_frame(self, frame: bytes, action: str) -> None:
        if self._serial is None:
            raise PowerSupplyError("程控电源串口未打开。")
        try:
            written = self._serial.write(frame)
        except Exception as exc:
            raise PowerSupplyError(f"{action}失败：{exc}") from exc
        if written != len(frame):
            raise PowerSupplyError(f"{action}写入不完整：期望 {len(frame)} 字节，实际 {written} 字节。")
        self._emit(f"{action}：{' '.join(f'{value:02X}' for value in frame)}")

    def _emit(self, message: str) -> None:
        if self._on_output:
            self._on_output(message)


def _normalize_channels(channels: Iterable[int]) -> list[int]:
    selected: list[int] = []
    for channel in channels:
        if not isinstance(channel, int) or isinstance(channel, bool) or not 1 <= channel <= 16:
            raise ValueError(f"程控电源通道必须在 1-16：{channel}")
        if channel not in selected:
            selected.append(channel)
    if not selected:
        raise ValueError("至少需要选择一个程控电源通道。")
    return selected

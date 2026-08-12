from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SerialSettings:
    port: str
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 0.1
    write_timeout: float = 2.0
    xonxoff: bool = False
    rtscts: bool = False
    dsrdtr: bool = False


@dataclass(frozen=True)
class SerialEvent:
    port: str
    direction: str
    data: bytes
    text: str
    sensitive: bool = False


@dataclass(frozen=True)
class FullPackageUpgradeRequest:
    vlan: str
    server_interface: str
    tftp_server_ip: str
    firmware_path: Path
    power_serial_port: str
    final_username: str
    final_password: str
    restore_factory: bool = False
    transfer_method: str = "Tftp指令"
    power_channel: int = 0
    serial_port: str = ""

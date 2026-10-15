"""网卡重命名使用的身份与结果。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterIdentity:
    alias: str
    interface_guid: str
    status: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.alias} [{self.status}]" if self.status else self.alias


@dataclass(frozen=True)
class AdapterRenameResult:
    ok: bool
    message: str
    adapters: tuple[AdapterIdentity, ...] = ()
    # 下发后无法回读身份时，不允许操作员盲目重复下发。
    uncertain: bool = False

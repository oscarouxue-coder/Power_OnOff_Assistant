"""显式批量删除的不可变逐台结果，不与批量注册的停止策略混用。"""
from __future__ import annotations

from dataclasses import dataclass

from src.models.onu_registration_models import OnuOperationResult, RegisteredOnu


@dataclass(frozen=True)
class OnuDeleteItemResult:
    candidate: RegisteredOnu
    status: str  # success / failed / not_executed
    message: str
    operation: OnuOperationResult | None = None


@dataclass(frozen=True)
class OnuBatchDeleteResult:
    items: tuple[OnuDeleteItemResult, ...]

    @property
    def ok(self) -> bool:
        return bool(self.items) and all(item.status == "success" for item in self.items)

    @property
    def message(self) -> str:
        counts = {status: sum(item.status == status for item in self.items)
                  for status in ("success", "failed", "not_executed")}
        return (f"批量删除结束：成功 {counts['success']} 台，失败 {counts['failed']} 台，"
                f"未执行 {counts['not_executed']} 台（未执行 write）")

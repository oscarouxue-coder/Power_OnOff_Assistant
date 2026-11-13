"""当前 PON 显式删除：逐台独立会话，目标失败继续，通信失败或停止结束。"""
from __future__ import annotations

import re
import threading
from typing import Callable, Sequence

from src.models.onu_batch_delete import OnuBatchDeleteResult, OnuDeleteItemResult
from src.models.onu_registration_models import OltConnection, RegisteredOnu
from src.services.onu_registration_service import OnuRegistrationService


class OnuBatchDeleteService:
    def __init__(self, logger: Callable[[str], None] | None = None,
                 registration_service: OnuRegistrationService | None = None):
        self.logger = logger or (lambda _text: None)
        self.registration_service = registration_service or OnuRegistrationService(logger=self.logger)

    @staticmethod
    def validate_targets(family: str, pon_interface: str,
                         candidates: Sequence[RegisteredOnu]) -> str:
        prefix = {"C300": ("gpon-olt_", "gpon-onu_"), "C600": ("gpon_olt-", "gpon_onu-")}.get(family)
        if not prefix:
            return "不支持的 OLT 型号"
        match = re.fullmatch(re.escape(prefix[0]) + r"([1-9]\d*)/([1-9]\d*)/([1-9]\d*)", pon_interface)
        if not match or any(int(value) > 64 for value in match.groups()):
            return "批量删除 PON 接口非法"
        if not candidates:
            return "请先选择要删除的 ONU"
        interfaces = set()
        for candidate in candidates:
            expected = prefix[1] + "/".join(match.groups()) + f":{candidate.onu_id}"
            if (candidate.family != family or candidate.pon_interface != pon_interface
                    or not isinstance(candidate.onu_id, int) or isinstance(candidate.onu_id, bool)
                    or candidate.onu_id < 1 or candidate.onu_interface != expected):
                return f"删除目标型号、PON、接口或 ONU ID 不一致：{candidate.onu_interface}"
            if candidate.onu_interface in interfaces:
                return f"删除目标重复：{candidate.onu_interface}"
            interfaces.add(candidate.onu_interface)
        return ""

    def delete(self, family: str, connection: OltConnection, pon_interface: str,
               candidates: Sequence[RegisteredOnu],
               cancel_event: threading.Event | None = None) -> OnuBatchDeleteResult:
        targets = tuple(candidates)
        cancel = cancel_event or threading.Event()
        log = lambda message: self.logger(f"[ONU注册][{family}][批量删除] {message}")
        error = self.validate_targets(family, pon_interface, targets) or "；".join(connection.validate())
        log(f"开始：OLT {connection.host}，源 IP {connection.source_ip}，PON {pon_interface}，共 {len(targets)} 台")
        results = []
        halt_reason = error
        if error:
            log(f"预检失败，整批不执行：{error}")
        for index, candidate in enumerate(targets, 1):
            if cancel.is_set():
                halt_reason = halt_reason or "操作员已停止"
            if halt_reason:
                item = OnuDeleteItemResult(candidate, "not_executed", halt_reason)
            elif not candidate.serial_number.strip():
                item = OnuDeleteItemResult(candidate, "failed", "缺少 SN，跳过删除；请重新查询补齐身份")
            else:
                log(f"[{index}/{len(targets)}] 开始 {candidate.display_text}")
                try:
                    operation = self.registration_service.delete_registered_onu(family, connection, candidate, cancel)
                    message = operation.message
                    if operation.outcome_uncertain:
                        message += "；结果待核实，请重新查询，禁止自动重试"
                    item = OnuDeleteItemResult(candidate, "success" if operation.ok else "failed", message, operation)
                    if operation.error_kind in ("transport", "cancelled", "unexpected"):
                        halt_reason = operation.message
                except Exception as exc:
                    # 未分类的程序错误不能当作普通目标失败继续下发。
                    halt_reason = f"批量删除异常，结果待核实：{exc}"
                    item = OnuDeleteItemResult(candidate, "failed", halt_reason)
            results.append(item)
            label = {"success": "成功", "failed": "失败", "not_executed": "未执行"}[item.status]
            log(f"[{index}/{len(targets)}] {candidate.onu_interface} {label}：{item.message}")
        result = OnuBatchDeleteResult(tuple(results))
        log(result.message)
        return result

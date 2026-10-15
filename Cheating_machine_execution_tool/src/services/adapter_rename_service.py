"""网卡名称校验、身份复核与通道引用同步。"""
from __future__ import annotations

import re
import subprocess

from line_check_assistant.network_ops import adapter_alias_from_display, is_admin, is_windows, static_ip_for_vlan
from src.core.network_adapter import read_adapter_identities, rename_adapter, rename_adapter_command
from src.core.serial_transport import vlan_to_serial_port
from src.models.network_adapter import AdapterRenameResult


ADAPTER_NAME_HINT = "新名称须以 2–254 的数字结尾（非网关地址），例如 VLAN101、以太网101。"


def adapter_has_numeric_suffix(display_name: str) -> bool:
    return bool(re.search(r"\d+$", adapter_alias_from_display(display_name)))


def validate_adapter_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("请输入新网卡名称。")
    if any(ord(char) < 32 for char in name) or any(char in name for char in '\\/:*?"<>|'):
        raise ValueError("网卡名称不能包含控制字符或 \\ / : * ? \" < > |。")
    # 重命名使用 2–254；不接受网卡列表的显示状态后缀。
    match = re.search(r"\d+$", name)
    if not match:
        raise ValueError("新网卡名称必须以数字结尾，例如 VLAN101、以太网101。")
    if not 2 <= int(match.group()) <= 254:
        raise ValueError("新网卡名称末尾数字必须在 2–254 之间。")
    return name


def rename_unavailable_reason(*, busy: bool = False) -> str:
    if busy:
        return "已有测试、升级、写参或网络查询任务正在执行，请结束后再修改网卡名称。"
    if not is_windows():
        return "网卡重命名仅支持 Windows 10/11。"
    if not is_admin():
        return "修改网卡名称需要管理员权限，请以管理员身份重新运行软件。"
    return ""


def adapter_rename_is_busy(app) -> bool:
    flags = (
        "running", "power_on_running", "power_test_running", "parameter_write_running",
        "sample_upgrade_running", "dut_config_running", "onu_telnet_test_running",
        "onu_query_running", "onu_template_query_running", "onu_cleanup_query_running",
        "onu_register_running", "onu_save_olt_running", "onu_manage_query_running",
        "onu_manage_delete_running", "_project_info_query_count",
    )
    if any(bool(getattr(app, name, False)) for name in flags):
        return True
    if bool(getattr(getattr(app, "test_item_pretest_controls", None), "running", False)):
        return True
    if bool(getattr(getattr(app, "power_test_resume_session", None), "is_recovering", False)):
        return True
    pipeline = getattr(app, "pipeline_window", None)
    return bool(pipeline is not None and pipeline.is_running())


class AdapterRenameService:
    def __init__(self, *, reader=None, renamer=None, availability=None):
        self.reader = reader or read_adapter_identities
        self.renamer = renamer or rename_adapter
        self.availability = availability or rename_unavailable_reason

    def rename(self, old_name: str, new_name: str, emit=lambda _line: None) -> AdapterRenameResult:
        old_name = adapter_alias_from_display(old_name)
        try:
            new_name = validate_adapter_name(new_name)
            reason = self.availability()
            if reason:
                raise ValueError(reason)
            emit(f"[网卡重命名] 开始检查：{old_name} → {new_name}")
            before = self.reader()
            targets = [a for a in before if a.alias.casefold() == old_name.casefold()]
            if len(targets) != 1:
                raise ValueError("原网卡不存在或不唯一，请刷新网卡后重新选择。")
            target = targets[0]
            if any(a.alias.casefold() == new_name.casefold() for a in before):
                raise ValueError(f"网卡名称已存在：{new_name}，请使用其它名称。")
            emit(f"[网卡重命名] 已确认目标身份：{target.interface_guid}")
        except Exception as exc:
            message = f"修改网卡名称失败：{exc}"
            emit(f"[网卡重命名] {message}；未下发修改命令。")
            return AdapterRenameResult(False, message)

        command_error = ""
        emit(f"[网卡重命名] 实际命令：{subprocess.list2cmdline(rename_adapter_command(target.alias, new_name))}")
        try:
            self.renamer(target.alias, new_name)
        except Exception as exc:
            command_error = str(exc)
            emit(f"[网卡重命名] 命令异常：{exc}；先核实结果，不重复下发。")
        try:
            after = self.reader()
            identities = [a for a in after if a.interface_guid == target.interface_guid]
            names = [a for a in after if a.alias.casefold() == new_name.casefold()]
            if len(identities) == 1 and identities[0].alias == new_name and len(names) == 1:
                message = f"网卡已重命名：{target.alias} → {new_name}，同一网卡身份回读确认成功。"
                emit(f"[网卡重命名] {message}")
                return AdapterRenameResult(True, message, after)
            if len(identities) == 1 and identities[0].alias == target.alias:
                message = f"修改网卡名称失败：{command_error or '回读发现原网卡名称未改变'}"
                emit(f"[网卡重命名] {message}；保留原配置。")
                return AdapterRenameResult(False, message, after)
            raise RuntimeError("目标网卡身份或名称与预期不一致")
        except Exception as exc:
            message = f"无法确认网卡重命名结果：{exc}。请在 Windows 网络连接中核实实际名称，再刷新网卡；不要重复提交。"
            emit(f"[网卡重命名] {message}")
            return AdapterRenameResult(False, message, uncertain=True)


def synchronize_channel_adapter_names(channels, selected_section: str, old_name: str, new_name: str) -> None:
    """只更新名称引用及派生 PC IP，不改变勾选、COM 或其它配置。"""
    old_key = adapter_alias_from_display(old_name).casefold()
    for channel in channels:
        selected = channel.section == selected_section
        vlan_matches = adapter_alias_from_display(channel.vlan_name).casefold() == old_key
        adapter_matches = adapter_alias_from_display(channel.adapter_alias).casefold() == old_key
        if (selected or vlan_matches or adapter_matches) and not (channel.serial_port or "").strip():
            # 历史配置无显式 COM 时，保留改名前已经显示/使用的有效映射，
            # 避免改名后因 VLAN 尾号或前缀变化而换串口。
            try:
                channel.serial_port = vlan_to_serial_port(adapter_alias_from_display(channel.vlan_name or channel.adapter_alias))
            except ValueError:
                pass
        if selected or vlan_matches:
            channel.vlan_name = new_name
        if selected or adapter_matches:
            channel.adapter_alias = new_name
        if selected or vlan_matches or adapter_matches:
            try:
                channel.network_card_ip = static_ip_for_vlan(channel.vlan_name, channel.device_manage_ip)
            except ValueError:
                channel.network_card_ip = ""

"""Shared data-only upgrade dispatch. Four existing engines remain independent."""
from dataclasses import asdict
from pathlib import Path
import ipaddress
import re

from line_check_assistant.network_ops import adapter_alias_from_display, static_ip_for_vlan
from line_check_assistant.page_upgrade import PageUpgradeRequest, run_page_upgrade_batch
from line_check_assistant.sample_upgrade_settings_store import clamp_parallel_count
from src.models.boot_entry import BOOT_ENTRY_OPTIONS, BOOT_ENTRY_LOGIN
from src.models.capabilities import CapabilityError, object_schema
from src.models.serial_models import FullPackageUpgradeRequest
from src.models.upgrade_stop import UpgradeStoppedResult
from src.services.serial_upgrade_service import run_parallel_tftp_command_upgrades, run_parallel_tftp_put_upgrades
from src.services.web_gateway_upgrade_service import run_parallel_web_gateway_upgrades, TRANSFER_WEB_GATEWAY, validate_web_target


UPGRADE_SCHEMA = object_schema({
    "channel_ids": dict(type="array", minItems=1, maxItems=16, uniqueItems=True,
                        items=dict(type="integer", minimum=1, maximum=16)),
    "firmware_path": dict(type="string", minLength=1, maxLength=4096),
    "upgrade_type": dict(type="string", enum=["全包升级", "页面升级"]),
    "transfer_method": dict(type="string", enum=["Tftp指令", "Tftp Put", TRANSFER_WEB_GATEWAY]),
    "boot_entry_method": dict(type="string", enum=list(BOOT_ENTRY_OPTIONS)),
    "restore_factory": dict(type="boolean"),
    "parallel_count": dict(type="integer", minimum=1, maximum=8),
}, ("channel_ids", "firmware_path", "upgrade_type"))


def normalized_upgrade_arguments(arguments):
    from src.models.capabilities import validate_schema
    validate_schema(arguments, UPGRADE_SCHEMA)
    args = dict(arguments)
    args["firmware_path"] = str(Path(args["firmware_path"]).expanduser().resolve())
    args.setdefault("restore_factory", False)
    args.setdefault("parallel_count", 2)
    if args["upgrade_type"] == "全包升级":
        args.setdefault("transfer_method", "Tftp Put")
        args.setdefault("boot_entry_method", BOOT_ENTRY_LOGIN)
    elif "transfer_method" in args or "boot_entry_method" in args:
        raise CapabilityError("invalid_parameters", "页面升级不接受全包的传输或 Boot 参数")
    return args


def build_upgrade_requests(arguments, snapshot):
    args = normalized_upgrade_arguments(arguments)
    indexed = {int(c["section"].rsplit("_", 1)[1]): c for c in snapshot["channels"]}
    settings = snapshot["upgrade_settings"]
    requests = []
    for number in args["channel_ids"]:
        channel = indexed.get(number)
        if not channel or not channel.get("enabled", True):
            raise CapabilityError("invalid_target", f"通道{number}不存在或未启用")
        alias = adapter_alias_from_display(channel.get("vlan_name") or channel.get("adapter_alias", "")).strip()
        if not alias:
            raise CapabilityError("invalid_target", f"通道{number}未配置网卡")
        common = dict(vlan=alias.lower() if alias.lower().startswith('vlan') else alias, username=settings.get("username", "").strip(),
                      password=settings.get("password", "").strip(), firmware_path=Path(args["firmware_path"]),
                      restore_factory=args["restore_factory"])
        if args["upgrade_type"] == "页面升级":
            bind_ip = channel.get("network_card_ip", "").strip()
            host = channel.get("device_manage_ip", "").strip() or snapshot.get("device_ip", "")
            if not bind_ip and host:
                bind_ip = static_ip_for_vlan(alias, host)
            if not bind_ip or not host:
                raise CapabilityError("invalid_target", "页面升级缺少源 IP 或样机管理地址")
            ipaddress.IPv4Address(bind_ip)
            ipaddress.IPv4Address(host)
            requests.append(PageUpgradeRequest(**common, bind_ip=bind_ip, device_ip=host,
                adapter_alias=channel.get("adapter_alias") or alias, subnet_mask=channel.get("subnet_mask") or "255.255.255.0"))
        else:
            is_web = args['transfer_method'] == TRANSFER_WEB_GATEWAY
            suffix = re.search(r"(\d+)$", alias)
            if not is_web and (not suffix or not 1 <= int(suffix[1]) <= 254):
                raise CapabilityError("invalid_target", "全包升级网卡名称尾号须为1至254")
            port = channel.get("serial_port", "").strip().upper()
            if not port:
                from src.core.serial_transport import vlan_to_serial_port
                port = vlan_to_serial_port(alias.lower())
            power = snapshot.get("power_serial_port", "").upper()
            if port == power:
                raise CapabilityError("port_conflict", "样机串口与程控电源串口冲突")
            web_device = snapshot.get('device_ip', '').strip() if is_web else ''
            web_source = channel.get('network_card_ip', '').strip() if is_web else ''
            web_mask = channel.get('subnet_mask') or '255.255.255.0'
            if is_web:
                validate_web_target(web_source, web_device, web_mask)
            requests.append(FullPackageUpgradeRequest(vlan=alias.lower(), server_interface=alias,
                tftp_server_ip='' if is_web else "192.168.1." + str(int(suffix[1])), firmware_path=common["firmware_path"],
                power_serial_port=power, final_username=common["username"], final_password=common["password"],
                restore_factory=common["restore_factory"], transfer_method=args["transfer_method"],
                power_channel=number, serial_port=port, boot_entry_method=args["boot_entry_method"],
                web_device_ip=web_device, web_source_ip=web_source,
                web_subnet_mask=web_mask if is_web else "255.255.255.0"))
    return requests


from src.services.physical_resource_guards import guard_upgrade


@guard_upgrade
def dispatch_upgrade(requests, manager, *, parallel_count=2, on_output=None,
                     on_session_ready=None, on_item_started=None, on_item_complete=None, stop_control=None,
                     engines=None):
    """Called by both GUI and Agent; never imports a window or invokes GUI callbacks."""
    if not requests:
        raise ValueError("升级目标为空")
    if isinstance(requests[0], PageUpgradeRequest):
        if not all(isinstance(r, PageUpgradeRequest) for r in requests):
            raise ValueError("升级批次类型不一致")
        engine = (engines or {}).get("页面升级", run_page_upgrade_batch)
        options = {"max_workers": min(clamp_parallel_count(parallel_count), len(requests))} if parallel_count is not None else {}
        return engine(requests, **options,
            on_output=on_output, on_item_complete=on_item_complete,
            **({"stop_control": stop_control} if stop_control is not None else {}))
    method = requests[0].transfer_method
    if any(r.transfer_method != method for r in requests):
        raise ValueError("升级批次传输方式不一致")
    available = {"Tftp指令": run_parallel_tftp_command_upgrades, "Tftp Put": run_parallel_tftp_put_upgrades,
                 TRANSFER_WEB_GATEWAY: run_parallel_web_gateway_upgrades}
    available.update(engines or {})
    if method not in available:
        raise ValueError("未支持的升级方式")
    return available[method](requests, manager, max_workers=min(clamp_parallel_count(parallel_count), len(requests)),
        on_output=on_output, on_session_ready=on_session_ready, on_item_started=on_item_started,
        on_item_complete=on_item_complete, **({"stop_control": stop_control} if stop_control is not None else {}))


def upgrade_result(items):
    results = []
    for item in items:
        raw = item.result
        state = "skipped" if isinstance(raw, UpgradeStoppedResult) and raw.skipped else (
            "stopped" if isinstance(raw, UpgradeStoppedResult) else "succeeded" if raw.ok else "failed")
        if state == 'stopped' and '结果待确认' in raw.message:
            state = 'unknown'
        results.append(dict(vlan=item.request.vlan, state=state, message=raw.message))
    state = 'unknown' if any(r['state'] == 'unknown' for r in results) else "stopped" if any(r["state"] in ("stopped", "skipped") for r in results) else (
        "succeeded" if results and all(r["state"] == "succeeded" for r in results) else "failed")
    return dict(ok=state == "succeeded", state=state, items=results,
                verification="原业务流程结果；未额外登录回读版本")

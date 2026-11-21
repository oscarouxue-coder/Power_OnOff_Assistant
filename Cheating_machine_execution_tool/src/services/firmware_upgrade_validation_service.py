"""Non-destructive preflight; compatibility declarations are host-owned, hash-bound facts."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import shutil
import threading
import uuid

from src.models.capabilities import CapabilityError, fingerprint
from src.services.firmware_upgrade_service import build_upgrade_requests, normalized_upgrade_arguments


def inspect_upgrade_network(requests, emit=lambda line: None):
    """Current adapter identities and duplicate addresses; actual bind is rechecked by the engine."""
    import socket
    from src.core.ai_pc_network import _query, _normalize
    adapters = _normalize(_query(threading.Event(), emit))
    problems = []
    for request in requests:
        alias = getattr(request, "server_interface", getattr(request, "adapter_alias", ""))
        matches = [a for a in adapters if a["name"].casefold() == alias.casefold()]
        if len(matches) != 1:
            problems.append("目标网卡不存在或身份不唯一：" + alias)
            continue
        source = getattr(request, "tftp_server_ip", getattr(request, "bind_ip", ""))
        if getattr(request, "transfer_method", "") == "web打开网关":
            source = request.web_source_ip
        holders = [a for a in adapters if any(v["ip"] == source for v in a["addresses"])]
        if any(a["guid"] != matches[0]["guid"] for a in holders):
            problems.append("升级源IP同时属于其它网卡：" + source)
        if any(v["state"].casefold() == "duplicate" for a in holders for v in a["addresses"] if v["ip"] == source):
            problems.append("升级源IP存在重复地址状态：" + source)
        # Same-subnet adapters alone are not proof of a routing conflict. Exact source binding remains mandatory.
        if holders and getattr(request, "transfer_method", "") == "Tftp指令":
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                try:
                    probe.bind((source, 69))
                except OSError:
                    problems.append("TFTP源地址/69端口当前无法绑定：" + source)
    return problems


def file_information(path):
    path = Path(path)
    if not path.is_file():
        raise CapabilityError("firmware_not_found", "固件不是可读取的普通文件")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise CapabilityError("firmware_changed", "读取时固件已变化")
    if not after.st_size or path.suffix.lower() in (".py", ".ps1", ".bat", ".cmd", ".exe", ".txt", ".lnk"):
        raise CapabilityError("invalid_firmware", "空文件或已知非固件文件类型")
    return dict(path=str(path.resolve()), size=after.st_size, sha256=digest.hexdigest(),
                format="未自动判定；不能根据文件名推断适配")


class FirmwareUpgradeValidation:
    def __init__(self, manager, snapshot, directory, network_check=lambda requests: [], emit=lambda line: None):
        self.manager, self.snapshot, self.directory = manager, snapshot, Path(directory)
        self.network_check, self.emit = network_check, emit
        self.lock = threading.RLock()
        self.pending, self.confirmed = {}, {}

    @staticmethod
    def binding(arguments, snapshot, info):
        targets = [dict(c) for c in snapshot["channels"]
                   if int(c["section"].rsplit("_", 1)[1]) in arguments["channel_ids"]]
        return fingerprint(dict(arguments=arguments, targets=targets, sha256=info["sha256"],
                                power=snapshot.get("power_serial_port", ""), device_ip=snapshot.get('device_ip', ''),
                                credential_profile=fingerprint(snapshot.get('upgrade_settings', {}))))

    def confirm(self, principal, code):
        """Only the host's exact user-response/local confirmation path may call this."""
        with self.lock:
            value = self.pending.pop((principal, code.strip()), None)
            if value is None:
                raise CapabilityError("confirmation_invalid", "适配确认编号无效、身份不匹配或已经使用")
            self.confirmed[(principal, value)] = True
            while len(self.confirmed) > 256:
                self.confirmed.pop(next(iter(self.confirmed)))
        self.emit("[升级预检] 操作员已明确确认固件适配；绑定目标与SHA256")

    def validate(self, arguments, authority, *, require_confirmation=True, local_manual_restart=False):
        args = normalized_upgrade_arguments(arguments)
        authority.check(args["channel_ids"])
        snapshot = self.snapshot()
        manual_required = args["upgrade_type"] == "全包升级" and not snapshot.get("power_serial_port")
        if local_manual_restart:
            if authority.source != "gui":
                raise CapabilityError("source_forbidden", "人工重启续接只供本机升级窗口")
            if not manual_required:
                raise CapabilityError("target_changed", "程控电源或升级模式已变化，请重新预检")
        requests = build_upgrade_requests(args, snapshot)
        info = file_information(args["firmware_path"])
        binding = self.binding(args, snapshot, info)
        for request in requests:
            port = getattr(request, "serial_port", "")
            if port:
                state = self.manager.diagnostic_state(port)
                if state.get("control_owner") or state.get("closing_in_program"):
                    raise CapabilityError("serial_busy", f"串口 {port} 当前存在控制者或尚未完成关闭")
        problems = self.network_check(requests)
        if problems:
            raise CapabilityError("network_conflict", "升级网络预检未通过", problems=problems)
        if manual_required and not local_manual_restart:
            raise CapabilityError("manual_restart_required", "未配置程控电源，需要人工重启配合；不会擅自选择电源串口")
        with self.lock:
            confirmed = (authority.principal, binding) in self.confirmed
            if require_confirmation and not confirmed:
                existing = next((code for (who, code), value in self.pending.items()
                                 if who == authority.principal and value == binding), None)
                code = existing or uuid.uuid4().hex[:8]
                self.pending[(authority.principal, code)] = binding
                while len(self.pending) > 256:
                    self.pending.pop(next(iter(self.pending)))
                raise CapabilityError("compatibility_confirmation_required",
                    "缺少可信适配元数据，请明确确认目标型号与本固件适配", firmware=info,
                    channel_ids=args["channel_ids"], confirmation="确认固件适配 " + code,
                    notice="确认目标版本不等于已验证型号适配；只接受本任务真实用户的确认")
        resources = ["device-business"]  # Keep existing conservative whole-device admission initially.
        for number, request in zip(args["channel_ids"], requests):
            resources.extend(("channel:" + str(number), "adapter:" + getattr(request, "server_interface", getattr(request, "adapter_alias", "")).casefold()))
            if getattr(request, "serial_port", ""):
                resources.append("serial:" + request.serial_port.upper())
            if getattr(request, "power_serial_port", ""):
                resources.append("power:" + request.power_serial_port.upper())
        return dict(arguments=args, snapshot=snapshot, requests=requests, firmware=info,
                    binding=binding, resources=resources)

    def pin(self, validated):
        """Copy to a private content-addressed artifact and verify what the engine will send."""
        info = validated["firmware"]
        destination = self.directory / "firmware" / info["sha256"] / Path(info["path"]).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            shutil.copyfile(info["path"], temporary)
            if file_information(temporary)["sha256"] != info["sha256"]:
                raise CapabilityError("firmware_changed", "预检后固件内容已变化，未升级")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        from dataclasses import replace
        return [replace(r, firmware_path=destination) for r in validated["requests"]]

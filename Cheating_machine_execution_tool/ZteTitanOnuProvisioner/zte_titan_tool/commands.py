import re
from typing import Iterable, List

from .models import OnuProvisionConfig


CLI_ERROR_RE = re.compile(
    r"%Error|Invalid input detected|Ambiguous command|Incomplete command|"
    r"permission denied|access denied|authentication failed",
    re.IGNORECASE,
)


def build_discovery_command(shelf: int, slot: int, pon: int) -> str:
    return (
        f"show pon onu uncfg gpon_olt-{shelf}/{slot}/{pon} "
        "sn model speed-mode"
    )


def build_precheck_command(config: OnuProvisionConfig) -> str:
    return f"show running-config-interface {config.olt_interface}"


def build_provision_commands(config: OnuProvisionConfig) -> List[str]:
    commands = [
        "configure terminal",
        f"interface {config.olt_interface}",
        (
            f"onu {config.onu_id} type {config.onu_type} "
            f"sn {config.serial_number}"
        ),
        "exit",
        f"interface {config.onu_interface}",
    ]
    if config.real_speed != "auto":
        commands.append(f"real-speed {config.real_speed}")
    commands.extend(
        [
            f"tcont {config.tcont_id} profile {config.tcont_profile}",
        ]
    )
    if config.sn_bind_both:
        commands.append("sn-bind enable both")
    commands.extend(
        [
            f"gemport {config.gemport_id} tcont {config.tcont_id}",
            "exit",
            f"pon-onu-mng {config.onu_interface}",
        ]
    )
    commands.extend(
        f"service {item.service_id} gemport {config.gemport_id} vlan {item.vlan}"
        for item in config.services
    )
    commands.extend(["exit", f"interface {config.vport_interface}"])
    commands.extend(
        (
            f"service-port {item.service_id} user-vlan {item.vlan} "
            f"vlan {item.vlan}"
        )
        for item in config.services
    )
    commands.extend(["exit", "end"])
    return commands


def build_verify_commands(config: OnuProvisionConfig) -> List[str]:
    return [
        f"show collection pon-onu {config.onu_interface} config",
        f"show service-port interface {config.onu_interface}",
        f"show gpon onu detail-info {config.onu_interface}",
    ]


def contains_cli_error(output: str) -> bool:
    return bool(CLI_ERROR_RE.search(output))


def format_preview(commands: Iterable[str]) -> str:
    return "\n".join(commands)

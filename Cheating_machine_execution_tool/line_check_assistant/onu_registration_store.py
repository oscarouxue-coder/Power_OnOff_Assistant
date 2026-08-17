from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OLT_IP = "172.18.18.151"
DEFAULT_OLT_SOURCE_IP = "172.33.5.35"
DEFAULT_C600_SERVICES = "1,170\n2,171\n3,172\n4,173\n5,335\n6,600\n7,50\n8,151\n9,150"
ONU_REGISTRATION_SECTION = "onu_registration"


@dataclass
class OnuRegistrationConfig:
    olt_ip: str = DEFAULT_OLT_IP
    username: str = ""
    password: str = ""
    olt_family: str = "C300"
    source_ip: str = DEFAULT_OLT_SOURCE_IP
    c600_shelf: int = 1
    c600_slot: int = 1
    c600_pon: int = 5
    c600_onu_id: int = 1
    c600_onu_type: str = "CXP-55"
    c600_real_speed: str = "xgspon"
    c600_tcont_id: int = 1
    c600_tcont_profile: str = "CXP-55"
    c600_gemport_id: int = 1
    c600_vport_id: int = 1
    c600_sn_bind_both: bool = True
    c600_services: str = DEFAULT_C600_SERVICES
    c300_allow_offline_cleanup: bool = False


class OnuRegistrationStore:
    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> OnuRegistrationConfig:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")

        def read_int(name: str, fallback: int) -> int:
            try:
                return parser.getint(ONU_REGISTRATION_SECTION, name, fallback=fallback)
            except (ValueError, configparser.Error):
                return fallback

        def read_bool(name: str, fallback: bool) -> bool:
            try:
                return parser.getboolean(ONU_REGISTRATION_SECTION, name, fallback=fallback)
            except (ValueError, configparser.Error):
                return fallback

        return OnuRegistrationConfig(
            olt_ip=parser.get(ONU_REGISTRATION_SECTION, "olt_ip", fallback=DEFAULT_OLT_IP).strip() or DEFAULT_OLT_IP,
            username=parser.get(ONU_REGISTRATION_SECTION, "username", fallback=""),
            password=parser.get(ONU_REGISTRATION_SECTION, "password", fallback=""),
            olt_family=parser.get(ONU_REGISTRATION_SECTION, "olt_family", fallback="C300").strip() or "C300",
            source_ip=parser.get(ONU_REGISTRATION_SECTION, "source_ip", fallback=DEFAULT_OLT_SOURCE_IP).strip() or DEFAULT_OLT_SOURCE_IP,
            c600_shelf=read_int("c600_shelf", 1),
            c600_slot=read_int("c600_slot", 1),
            c600_pon=read_int("c600_pon", 5),
            c600_onu_id=read_int("c600_onu_id", 1),
            c600_onu_type=parser.get(ONU_REGISTRATION_SECTION, "c600_onu_type", fallback="CXP-55"),
            c600_real_speed=parser.get(ONU_REGISTRATION_SECTION, "c600_real_speed", fallback="xgspon"),
            c600_tcont_id=read_int("c600_tcont_id", 1),
            c600_tcont_profile=parser.get(ONU_REGISTRATION_SECTION, "c600_tcont_profile", fallback="CXP-55"),
            c600_gemport_id=read_int("c600_gemport_id", 1),
            c600_vport_id=read_int("c600_vport_id", 1),
            c600_sn_bind_both=read_bool("c600_sn_bind_both", True),
            c600_services=parser.get(ONU_REGISTRATION_SECTION, "c600_services", fallback=DEFAULT_C600_SERVICES),
            c300_allow_offline_cleanup=read_bool("c300_allow_offline_cleanup", False),
        )

    def save(self, config: OnuRegistrationConfig) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser[ONU_REGISTRATION_SECTION] = {
            "olt_ip": (config.olt_ip or DEFAULT_OLT_IP).strip() or DEFAULT_OLT_IP,
            "username": config.username or "",
            "password": config.password or "",
            "olt_family": config.olt_family or "C300",
            "source_ip": (config.source_ip or DEFAULT_OLT_SOURCE_IP).strip() or DEFAULT_OLT_SOURCE_IP,
            "c600_shelf": str(config.c600_shelf),
            "c600_slot": str(config.c600_slot),
            "c600_pon": str(config.c600_pon),
            "c600_onu_id": str(config.c600_onu_id),
            "c600_onu_type": config.c600_onu_type,
            "c600_real_speed": config.c600_real_speed,
            "c600_tcont_id": str(config.c600_tcont_id),
            "c600_tcont_profile": config.c600_tcont_profile,
            "c600_gemport_id": str(config.c600_gemport_id),
            "c600_vport_id": str(config.c600_vport_id),
            "c600_sn_bind_both": "true" if config.c600_sn_bind_both else "false",
            "c600_services": config.c600_services,
            "c300_allow_offline_cleanup": "true" if config.c300_allow_offline_cleanup else "false",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)

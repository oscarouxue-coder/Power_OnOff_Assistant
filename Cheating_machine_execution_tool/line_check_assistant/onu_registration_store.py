from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_C300_OLT_IP = "172.18.18.151"
DEFAULT_C300_SOURCE_IP = "172.18.18.40"
DEFAULT_C600_OLT_IP = "172.18.18.152"
DEFAULT_C600_SOURCE_IP = "172.33.5.35"
# 保留旧导入名，默认型号仍为 C300。
DEFAULT_OLT_IP = DEFAULT_C300_OLT_IP
DEFAULT_OLT_SOURCE_IP = DEFAULT_C300_SOURCE_IP
DEFAULT_C600_SERVICES = "1,170\n2,171\n3,172\n4,173\n5,335\n6,600\n7,50\n8,151\n9,150"
DEFAULT_C300_SERVICES = "1,200\n2,46\n3,335\n4,600\n5,171\n6,172"
ONU_REGISTRATION_SECTION = "onu_registration"


@dataclass
class OnuRegistrationConfig:
    olt_ip: str = DEFAULT_OLT_IP
    username: str = ""
    password: str = ""
    olt_family: str = "C300"
    source_ip: str = DEFAULT_OLT_SOURCE_IP
    c300_olt_ip: str = DEFAULT_C300_OLT_IP
    c300_source_ip: str = DEFAULT_C300_SOURCE_IP
    c300_username: str = ""
    c300_password: str = ""
    c600_olt_ip: str = DEFAULT_C600_OLT_IP
    c600_source_ip: str = DEFAULT_C600_SOURCE_IP
    c600_username: str = ""
    c600_password: str = ""
    c600_shelf: int = 1
    c600_slot: int = 1
    c600_pon: int = 5
    c600_onu_id: int = 1
    c600_onu_type: str = "CXP-55"
    c600_real_speed: str = "auto"
    c600_tcont_id: int = 1
    c600_tcont_profile: str = "WT-10G"
    c600_gemport_id: int = 1
    c600_vport_id: int = 1
    c600_sn_bind_both: bool = True
    c600_services: str = DEFAULT_C600_SERVICES
    c300_shelf: int = 1
    c300_slot: int = 2
    c300_pon: int = 1
    c300_onu_id: int = 1
    c300_onu_type: str = "SD-41"
    c300_tcont_id: int = 1
    c300_tcont_profile: str = "1G"
    c300_services: str = DEFAULT_C300_SERVICES
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

        family = parser.get(ONU_REGISTRATION_SECTION, "olt_family", fallback="C300").strip() or "C300"
        if family not in {"C300", "C600"}:
            family = "C300"
        legacy_olt_ip = parser.get(ONU_REGISTRATION_SECTION, "olt_ip", fallback=DEFAULT_OLT_IP).strip()
        legacy_source_ip = parser.get(ONU_REGISTRATION_SECTION, "source_ip", fallback=DEFAULT_OLT_SOURCE_IP).strip()
        legacy_username = parser.get(ONU_REGISTRATION_SECTION, "username", fallback="")
        legacy_password = parser.get(ONU_REGISTRATION_SECTION, "password", fallback="")

        def profile_text(name: str, profile_family: str, fallback: str) -> str:
            if parser.has_option(ONU_REGISTRATION_SECTION, name):
                return parser.get(ONU_REGISTRATION_SECTION, name, fallback=fallback).strip()
            if family == profile_family:
                legacy = {
                    "olt_ip": legacy_olt_ip,
                    "source_ip": legacy_source_ip,
                    "username": legacy_username,
                    "password": legacy_password,
                }[name.split("_", 1)[1]]
                return legacy or fallback
            return fallback

        c300_olt_ip = profile_text("c300_olt_ip", "C300", DEFAULT_C300_OLT_IP)
        c300_source_ip = profile_text("c300_source_ip", "C300", DEFAULT_C300_SOURCE_IP)
        c300_username = profile_text("c300_username", "C300", "")
        c300_password = profile_text("c300_password", "C300", "")
        c600_olt_ip = profile_text("c600_olt_ip", "C600", DEFAULT_C600_OLT_IP)
        c600_source_ip = profile_text("c600_source_ip", "C600", DEFAULT_C600_SOURCE_IP)
        c600_username = profile_text("c600_username", "C600", "")
        c600_password = profile_text("c600_password", "C600", "")
        active = (
            (c300_olt_ip, c300_source_ip, c300_username, c300_password)
            if family == "C300"
            else (c600_olt_ip, c600_source_ip, c600_username, c600_password)
        )

        return OnuRegistrationConfig(
            olt_ip=active[0],
            username=active[2],
            password=active[3],
            olt_family=family,
            source_ip=active[1],
            c300_olt_ip=c300_olt_ip,
            c300_source_ip=c300_source_ip,
            c300_username=c300_username,
            c300_password=c300_password,
            c600_olt_ip=c600_olt_ip,
            c600_source_ip=c600_source_ip,
            c600_username=c600_username,
            c600_password=c600_password,
            c600_shelf=read_int("c600_shelf", 1),
            c600_slot=read_int("c600_slot", 1),
            c600_pon=read_int("c600_pon", 5),
            c600_onu_id=read_int("c600_onu_id", 1),
            c600_onu_type=parser.get(ONU_REGISTRATION_SECTION, "c600_onu_type", fallback="CXP-55"),
            c600_real_speed=parser.get(ONU_REGISTRATION_SECTION, "c600_real_speed", fallback="auto"),
            c600_tcont_id=read_int("c600_tcont_id", 1),
            c600_tcont_profile=parser.get(ONU_REGISTRATION_SECTION, "c600_tcont_profile", fallback="WT-10G"),
            c600_gemport_id=read_int("c600_gemport_id", 1),
            c600_vport_id=read_int("c600_vport_id", 1),
            c600_sn_bind_both=read_bool("c600_sn_bind_both", True),
            c600_services=parser.get(ONU_REGISTRATION_SECTION, "c600_services", fallback=DEFAULT_C600_SERVICES),
            c300_shelf=read_int("c300_shelf", 1),
            c300_slot=read_int("c300_slot", 2),
            c300_pon=read_int("c300_pon", 1),
            c300_onu_id=read_int("c300_onu_id", 1),
            c300_onu_type=parser.get(ONU_REGISTRATION_SECTION, "c300_onu_type", fallback="SD-41"),
            c300_tcont_id=read_int("c300_tcont_id", 1),
            c300_tcont_profile=parser.get(ONU_REGISTRATION_SECTION, "c300_tcont_profile", fallback="1G"),
            c300_services=parser.get(ONU_REGISTRATION_SECTION, "c300_services", fallback=DEFAULT_C300_SERVICES),
            # 危险删除授权不跨窗口、不跨程序启动持久化。
            c300_allow_offline_cleanup=False,
        )

    def save(self, config: OnuRegistrationConfig) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        c300_profile = {
            "olt_ip": config.c300_olt_ip,
            "source_ip": config.c300_source_ip,
            "username": config.c300_username,
            "password": config.c300_password,
        }
        c600_profile = {
            "olt_ip": config.c600_olt_ip,
            "source_ip": config.c600_source_ip,
            "username": config.c600_username,
            "password": config.c600_password,
        }
        active_profile = c300_profile if config.olt_family == "C300" else c600_profile
        active_profile.update(
            {
                "olt_ip": config.olt_ip,
                "source_ip": config.source_ip,
                "username": config.username,
                "password": config.password,
            }
        )
        parser[ONU_REGISTRATION_SECTION] = {
            "olt_ip": (config.olt_ip or DEFAULT_OLT_IP).strip() or DEFAULT_OLT_IP,
            "username": config.username or "",
            "password": config.password or "",
            "olt_family": config.olt_family or "C300",
            "source_ip": (config.source_ip or DEFAULT_OLT_SOURCE_IP).strip() or DEFAULT_OLT_SOURCE_IP,
            "c300_olt_ip": (c300_profile["olt_ip"] or DEFAULT_C300_OLT_IP).strip() or DEFAULT_C300_OLT_IP,
            "c300_source_ip": (c300_profile["source_ip"] or DEFAULT_C300_SOURCE_IP).strip() or DEFAULT_C300_SOURCE_IP,
            "c300_username": c300_profile["username"] or "",
            "c300_password": c300_profile["password"] or "",
            "c600_olt_ip": (c600_profile["olt_ip"] or DEFAULT_C600_OLT_IP).strip() or DEFAULT_C600_OLT_IP,
            "c600_source_ip": (c600_profile["source_ip"] or DEFAULT_C600_SOURCE_IP).strip() or DEFAULT_C600_SOURCE_IP,
            "c600_username": c600_profile["username"] or "",
            "c600_password": c600_profile["password"] or "",
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
            "c300_shelf": str(config.c300_shelf),
            "c300_slot": str(config.c300_slot),
            "c300_pon": str(config.c300_pon),
            "c300_onu_id": str(config.c300_onu_id),
            "c300_onu_type": config.c300_onu_type,
            "c300_tcont_id": str(config.c300_tcont_id),
            "c300_tcont_profile": config.c300_tcont_profile,
            "c300_services": config.c300_services,
            "c300_allow_offline_cleanup": "false",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)

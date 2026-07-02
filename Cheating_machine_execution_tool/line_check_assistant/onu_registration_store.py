from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OLT_IP = "172.18.18.151"
ONU_REGISTRATION_SECTION = "onu_registration"


@dataclass
class OnuRegistrationConfig:
    olt_ip: str = DEFAULT_OLT_IP
    username: str = ""
    password: str = ""


class OnuRegistrationStore:
    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> OnuRegistrationConfig:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")

        return OnuRegistrationConfig(
            olt_ip=parser.get(ONU_REGISTRATION_SECTION, "olt_ip", fallback=DEFAULT_OLT_IP).strip() or DEFAULT_OLT_IP,
            username=parser.get(ONU_REGISTRATION_SECTION, "username", fallback=""),
            password=parser.get(ONU_REGISTRATION_SECTION, "password", fallback=""),
        )

    def save(self, config: OnuRegistrationConfig) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser[ONU_REGISTRATION_SECTION] = {
            "olt_ip": (config.olt_ip or DEFAULT_OLT_IP).strip() or DEFAULT_OLT_IP,
            "username": config.username or "",
            "password": config.password or "",
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)

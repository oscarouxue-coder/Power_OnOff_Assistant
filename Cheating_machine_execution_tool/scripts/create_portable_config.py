"""Create a sanitized runtime configuration set for the portable release.

The source configuration directory is treated as a schema/template only.  Values
that identify the current PC, contain credentials, or point at local files are
removed before anything is copied into ``dist``.
"""
from __future__ import annotations

import argparse
import configparser
from pathlib import Path


PORTABLE_CONFIG_NAMES: tuple[str, ...] = (
    "config.ini",
    "network_card_ip.ini",
    "onu_registration.ini",
    "sample_upgrade_settings.ini",
    "test_project_config.default.ini",
    "test_project_config.ini",
)


def _new_parser() -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    return parser


def _read_ini(path: Path) -> configparser.RawConfigParser:
    if not path.is_file():
        raise FileNotFoundError(f"缺少便携版配置模板：{path}")
    parser = _new_parser()
    with path.open("r", encoding="utf-8-sig") as stream:
        parser.read_file(stream)
    return parser


def _write_ini(parser: configparser.RawConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        parser.write(stream, space_around_delimiters=True)


def _set_if_present(
    parser: configparser.RawConfigParser,
    section: str,
    option: str,
    value: str,
) -> None:
    if parser.has_option(section, option):
        parser.set(section, option, value)


def _sanitize_main_config(source: Path, destination: Path) -> None:
    parser = _read_ini(source)
    _set_if_present(parser, "dingtalk_config", "dingtalk_flag", "0")
    _set_if_present(parser, "dingtalk_config", "webhook", "")
    _set_if_present(parser, "dingtalk_config", "secret", "")
    _set_if_present(parser, "dingtalk_config", "at_all", "0")
    _set_if_present(parser, "remote_config", "remote_tool_name", "")
    _set_if_present(parser, "remote_config", "remote_identification_code", "")
    _set_if_present(parser, "remote_config", "remote_verification_code", "")
    _set_if_present(parser, "Emails", "emails", "")
    _write_ini(parser, destination)


def _write_empty_network_config(destination: Path) -> None:
    parser = _new_parser()
    parser.add_section("power_supply")
    parser.set("power_supply", "serial_port", "")
    _write_ini(parser, destination)


def _sanitize_onu_config(source: Path, destination: Path) -> None:
    parser = _read_ini(source)
    for option in (
        "olt_ip",
        "source_ip",
        "username",
        "password",
        "c300_olt_ip",
        "c300_source_ip",
        "c300_username",
        "c300_password",
        "c600_olt_ip",
        "c600_source_ip",
        "c600_username",
        "c600_password",
    ):
        _set_if_present(parser, "onu_registration", option, "")
    # ONU ID is a per-operation value and must not be inherited from this PC.
    _set_if_present(parser, "onu_registration", "c600_onu_id", "")
    _write_ini(parser, destination)


def _sanitize_upgrade_config(source: Path, destination: Path) -> None:
    parser = _read_ini(source)
    for option in (
        "username",
        "password",
        "firmware_path",
        "parameter_initial_username",
        "parameter_initial_password",
        "parameter_table_path",
    ):
        _set_if_present(parser, "sample_upgrade", option, "")
    _write_ini(parser, destination)


def _sanitize_test_project(source: Path, destination: Path) -> None:
    parser = _read_ini(source)
    for option in ("user", "password"):
        _set_if_present(parser, "telnet", option, "")
    _set_if_present(parser, "connect_wifi", "choose_wireless_card", "0")
    _set_if_present(parser, "connect_wifi", "wireless_card_name", "")
    for option in (
        "project_name",
        "software_version",
        "internal_software_version",
        "onu_compile_time",
    ):
        _set_if_present(parser, "project_info", option, "")
    _write_ini(parser, destination)


def create_portable_config(source_dir: Path, destination_dir: Path) -> tuple[Path, ...]:
    """Create all runtime INIs required by a portable release.

    The caller must provide a new or empty output directory.  Refusing a
    non-empty directory avoids both stale machine-specific files and broad
    recursive deletion in this standalone helper.
    """
    source_dir = source_dir.resolve()
    destination_dir = destination_dir.resolve()
    if source_dir == destination_dir:
        raise ValueError("便携版配置输出目录不能与当前运行配置目录相同")

    if destination_dir.exists():
        if not destination_dir.is_dir():
            raise ValueError(f"便携版配置输出路径不是目录：{destination_dir}")
        if any(destination_dir.iterdir()):
            raise ValueError(f"便携版配置输出目录必须为空：{destination_dir}")
    else:
        destination_dir.mkdir(parents=True)

    _sanitize_main_config(source_dir / "config.ini", destination_dir / "config.ini")
    _write_empty_network_config(destination_dir / "network_card_ip.ini")
    _sanitize_onu_config(
        source_dir / "onu_registration.ini",
        destination_dir / "onu_registration.ini",
    )
    _sanitize_upgrade_config(
        source_dir / "sample_upgrade_settings.ini",
        destination_dir / "sample_upgrade_settings.ini",
    )

    template_source = source_dir / "test_project_config.default.ini"
    _sanitize_test_project(
        template_source,
        destination_dir / "test_project_config.default.ini",
    )
    _sanitize_test_project(
        template_source,
        destination_dir / "test_project_config.ini",
    )

    created = tuple(destination_dir / name for name in PORTABLE_CONFIG_NAMES)
    missing = [str(path) for path in created if not path.is_file()]
    if missing:
        raise RuntimeError("便携版配置生成不完整：" + "、".join(missing))
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 LineCheckAssistant 便携版脱敏配置")
    parser.add_argument("--source", required=True, type=Path, help="当前配置模板目录")
    parser.add_argument("--destination", required=True, type=Path, help="便携版配置输出目录")
    args = parser.parse_args()
    created = create_portable_config(args.source, args.destination)
    print(f"Created {len(created)} sanitized configuration files: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

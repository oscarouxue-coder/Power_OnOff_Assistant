"""Inspect a PyInstaller package and portable ZIP without launching the EXE."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import sys
import zipfile

from PyInstaller.archive.readers import CArchiveReader


REQUIRED_MODULES = (
    "line_check_assistant.app",
    "src.services.legacy_power_test_service",
    "src.services.power_test_resume_service",
    "src.services.serial_upgrade_service",
    "src.services.web_gateway_upgrade_service",
    "src.core.sample_parameter_table",
    "test_case.powe_on_off_telnet",
    "test_case.power_on_off_ssh",
    "test_case.wifi_connect_case",
    "common.wifi_connect",
    "requests_toolbelt.adapters.source",
    "paramiko", "paramiko.transport", "ping3", "pywifi", "pywifi._wifiutil_win",
    # pywifi uses comtypes.GUID. comtypes.gen is an optional namespace created
    # dynamically by comtypes.client, so a fresh build need not contain it.
    "comtypes", "comtypes.GUID", "comtypes.client", "configobj", "psutil",
    "serial", "serial.serialwin32", "tftpy", "openpyxl", "xlrd", "tkinter",
)
REQUIRED_FILES = (
    "tcl/init.tcl", "tk/tk.tcl", "_tcl_data/init.tcl", "_tk_data/tk.tcl",
    "VERSION_INFO.txt", "BUILD_INFO.txt", "python39.dll", "_socket.pyd",
    "_ssl.pyd", "_ctypes.pyd", "tcl86t.dll", "tk86t.dll", "certifi/cacert.pem",
)


def inspect_archive(exe: Path, excluded: list[str]) -> dict:
    archive = CArchiveReader(str(exe))
    modules = archive.open_embedded_archive("PYZ-00.pyz").toc
    names = {name.replace("\\", "/") for name in archive.toc}
    missing = sorted(set(REQUIRED_MODULES) - modules.keys())
    missing += sorted(set(REQUIRED_FILES) - names)
    if missing:
        raise ValueError("Missing required archive entries: " + ", ".join(missing))
    if not any("pyi_rth__tkinter" in n for n in names):
        raise ValueError("Missing Tkinter runtime hook")
    for prefix in ("cryptography/hazmat/bindings/_rust", "bcrypt/_bcrypt", "nacl/_sodium", "psutil/_psutil_windows"):
        if not any(n.startswith(prefix) and n.endswith(".pyd") for n in names):
            raise ValueError("Missing required native dependency: " + prefix)
    source_root = Path(__file__).resolve().parents[1]
    expected_version = (source_root / "line_check_assistant/packaging_assets/VERSION_INFO.txt").read_bytes()
    if archive.extract("VERSION_INFO.txt") != expected_version:
        raise ValueError("Embedded VERSION_INFO.txt differs from the source version")
    for package in excluded:
        prefix = package.lower()
        unwanted = [n for n in modules if n.lower() == prefix or n.lower().startswith(prefix + ".")]
        unwanted += [n for n in names if n.lower() == prefix or n.lower().startswith((prefix + "/", prefix + ".", prefix + ".libs/"))]
        if package == "numpy":
            unwanted += [n for n in names if "openblas" in n.lower()]
        if unwanted:
            raise ValueError("Excluded dependency still bundled: " + ", ".join(sorted(set(unwanted))))
    groups: dict[str, int] = {}
    for name, entry in archive.toc.items():
        group = name.replace("\\", "/").split("/")[0]
        groups[group] = groups.get(group, 0) + entry[1]
    return {
        "exe_bytes": exe.stat().st_size,
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "archive_entries": len(archive.toc),
        "python_modules": len(modules),
        "excluded_modules": excluded,
        "largest_compressed_groups": dict(sorted(groups.items(), key=lambda pair: pair[1], reverse=True)[:20]),
        "required_modules": list(REQUIRED_MODULES),
        "required_files": list(REQUIRED_FILES),
    }


def inspect_portable(exe: Path, portable_zip: Path) -> dict:
    root = "LineCheckAssistant_portable/"
    required = {
        root + name for name in (
            "LineCheckAssistant.exe", "LineCheckAssistant.exe.sha256.txt",
            "VERSION_INFO.txt", "BUILD_INFO.txt", "PORTABLE_README.txt", "THIRD_PARTY_NOTICES.md",
        )
    }
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.create_portable_config import PORTABLE_CONFIG_NAMES

    required.update(root + "Auto_power_on_off_tool/config/" + name for name in PORTABLE_CONFIG_NAMES)
    with zipfile.ZipFile(portable_zip) as bundle:
        bad = bundle.testzip()
        if bad:
            raise ValueError("ZIP CRC failure: " + bad)
        if not required.issubset(bundle.namelist()):
            raise ValueError("Incomplete portable ZIP: " + ", ".join(sorted(required - set(bundle.namelist()))))
        expected = hashlib.sha256(exe.read_bytes()).hexdigest()
        if hashlib.sha256(bundle.read(root + "LineCheckAssistant.exe")).hexdigest() != expected:
            raise ValueError("Portable EXE differs from the standalone EXE")
        if bundle.read(root + "LineCheckAssistant.exe.sha256.txt").decode("ascii").split()[0].lower() != expected:
            raise ValueError("Portable EXE checksum mismatch")
    actual = hashlib.sha256(portable_zip.read_bytes()).hexdigest()
    if Path(str(portable_zip) + ".sha256.txt").read_text(encoding="ascii").split()[0].lower() != actual:
        raise ValueError("Portable ZIP checksum mismatch")
    if Path(str(exe) + ".sha256.txt").read_text(encoding="ascii").split()[0].lower() != expected:
        raise ValueError("Standalone EXE checksum mismatch")
    return {"zip_bytes": portable_zip.stat().st_size, "zip_sha256": actual, "zip_crc": "passed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    report = inspect_archive(args.exe, args.exclude)
    report.update(inspect_portable(args.exe, args.zip))
    report.update({
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "build_dependencies": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
        "exe_launched": False,
        "acceptance": "Archive/source checks only; target Windows and real-device verification pending.",
    })
    path = args.exe.parent / "PACKAGING_REPORT.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PACKAGE_ARCHIVE_OK exe={report['exe_bytes']} zip={report['zip_bytes']} report={path}")


if __name__ == "__main__":
    main()

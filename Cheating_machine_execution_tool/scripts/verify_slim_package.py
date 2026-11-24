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
    "src.services.ai_case_store",
    "line_check_assistant.app",
    "src.ui.application_icon",
    "src.services.dingtalk_remote_service", "src.core.dingtalk_stream",
    "src.services.feishu_remote_service", "src.services.feishu_notifications",
    "src.ui.feishu_setup_window", "src.core.feishu_stream", "src.core.feishu_client",
    "lark_oapi.ws.client", "lark_oapi.ws.pb.pbbp2_pb2", "httpx", "Crypto.Cipher.AES",
    "websockets.sync.client",
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
TK_ICON_RELATIVE_PATH = "assets/icons/DUTPilot-01-tk.ico"
REQUIRED_FILES = (
    "CONFIRMED_CASES.json",
    TK_ICON_RELATIVE_PATH,
    "tcl/init.tcl", "tk/tk.tcl", "_tcl_data/init.tcl", "_tk_data/tk.tcl",
    "VERSION_INFO.txt", "BUILD_INFO.txt", "python39.dll", "_socket.pyd",
    "_ssl.pyd", "_ctypes.pyd", "tcl86t.dll", "tk86t.dll", "certifi/cacert.pem",
)
REQUIRED_QT_MODULES = (
    'src.ui.qt.application', 'src.ui.qt.workspace_controller', 'src.ui.qt.project_detail',
    'src.services.qt_workspace_adapter', 'src.services.qt_execution_adapter',
    'src.services.workspace_service', 'src.services.legacy_power_test_service',
    'src.services.power_test_resume_service', 'src.services.serial_upgrade_service',
    'src.services.web_gateway_upgrade_service', 'src.core.sample_parameter_table',
    'test_case.powe_on_off_telnet', 'test_case.power_on_off_ssh',
    'test_case.wifi_connect_case', 'common.wifi_connect',
    'serial', 'serial.serialwin32', 'paramiko', 'tftpy', 'openpyxl', 'xlrd',
)
QT_ICON_RELATIVE_PATH = 'assets/icons/DUTPilot-01.ico'
REQUIRED_QT_FILES = (
    'PySide6/plugins/platforms/qwindows.dll', 'PySide6/QtCore.pyd',
    'PySide6/QtGui.pyd', 'PySide6/QtWidgets.pyd',
    'PySide6/Qt6Core.dll', 'PySide6/Qt6Gui.dll', 'PySide6/Qt6Widgets.dll',
    'python39.dll', '_socket.pyd', '_ssl.pyd', '_ctypes.pyd', 'certifi/cacert.pem',
    'qt_licenses/GPL-3.0-only.txt', 'qt_licenses/LGPL-3.0-only.txt', 'qt_licenses/QT-SOURCES.md',
    'qt_licenses/PySide6-Essentials/LicenseRef-Qt-Commercial.txt',
    'qt_licenses/shiboken6/LicenseRef-Qt-Commercial.txt',
    QT_ICON_RELATIVE_PATH,
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
    icon_name = TK_ICON_RELATIVE_PATH
    # Use the archive's original key (Windows may use backslashes).
    icon_key = next(name for name in archive.toc if name.replace("\\", "/") == icon_name)
    if archive.extract(icon_key) != (source_root / icon_name).read_bytes():
        raise ValueError("Embedded application icon differs from the source icon")
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
    root = "DUTPilot_portable/"
    required = {
        root + name for name in (
            "DUTPilot.exe", "DUTPilot.exe.sha256.txt",
            "VERSION_INFO.txt", "BUILD_INFO.txt", "PORTABLE_README.txt", "THIRD_PARTY_NOTICES.md",
            "CONFIRMED_CASES.json",
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
        if hashlib.sha256(bundle.read(root + "DUTPilot.exe")).hexdigest() != expected:
            raise ValueError("Portable EXE differs from the standalone EXE")
        if bundle.read(root + "DUTPilot.exe.sha256.txt").decode("ascii").split()[0].lower() != expected:
            raise ValueError("Portable EXE checksum mismatch")
    actual = hashlib.sha256(portable_zip.read_bytes()).hexdigest()
    if Path(str(portable_zip) + ".sha256.txt").read_text(encoding="ascii").split()[0].lower() != actual:
        raise ValueError("Portable ZIP checksum mismatch")
    if Path(str(exe) + ".sha256.txt").read_text(encoding="ascii").split()[0].lower() != expected:
        raise ValueError("Standalone EXE checksum mismatch")
    return {"zip_bytes": portable_zip.stat().st_size, "zip_sha256": actual, "zip_crc": "passed"}


def inspect_qt_imports(files: dict) -> dict:
    """Resolve direct and delay-loaded Qt libraries inside the portable layout."""
    import pefile

    available = {name.casefold() for name in files}
    imports = {}
    missing = []
    tables = ('IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT')
    for name, path in sorted(files.items()):
        if not name.startswith(('PySide6/', 'shiboken6/')) or path.suffix.lower() not in ('.dll', '.pyd'):
            continue
        with pefile.PE(str(path), fast_load=True) as image:
            image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY[table] for table in tables])
            deps = sorted({row.dll.decode('ascii') for table in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                           for row in getattr(image, table, ()) if row.dll.lower().startswith(b'qt6')})
        imports[name] = deps
        for dll in deps:
            # Qt's DLL directory and the importing image's own directory are
            # available at runtime. A similarly named file elsewhere is insufficient.
            locations = (str(Path(name).with_name(dll).as_posix()), 'PySide6/' + dll, dll)
            if not any(location.casefold() in available for location in locations):
                missing.append(f'{name} -> {dll}')
    if missing:
        raise ValueError('Unresolved portable Qt DLL imports: ' + ', '.join(missing))
    return imports


def inspect_qt_directory(exe: Path, portable_zip: Path, excluded: list[str]) -> dict:
    import pefile

    archive = CArchiveReader(str(exe))
    modules = archive.open_embedded_archive('PYZ-00.pyz').toc
    directory = exe.parent
    files = {path.relative_to(directory).as_posix(): path for path in directory.rglob('*') if path.is_file()}
    missing = sorted(set(REQUIRED_QT_MODULES) - modules.keys()) + sorted(set(REQUIRED_QT_FILES) - files.keys())
    if missing:
        raise ValueError('Qt package is missing required entries: ' + ', '.join(missing))
    qt_imports = inspect_qt_imports(files)
    if not {'run_dutpilot_qt', 'pyi_rth_pyside6'}.issubset(archive.toc):
        raise ValueError('Qt entry point or PyInstaller runtime hook is missing')

    package_names = {name.replace('/', '.').lower() for name in (*modules, *files)}
    unwanted = {name for name in package_names if any(name == prefix.lower() or name.startswith(prefix.lower() + '.')
                for prefix in excluded) or 'openblas' in name}
    if unwanted:
        raise ValueError('Excluded dependency still bundled: ' + ', '.join(sorted(unwanted)))

    with pefile.PE(str(exe)) as image:
        if image.FILE_HEADER.Machine != 0x8664 or image.OPTIONAL_HEADER.Subsystem != 2:
            raise ValueError('The Qt entry is not a Windows x64 GUI executable')
        version = getattr(image, 'VS_FIXEDFILEINFO', ())
        if not version or (version[0].ProductVersionMS, version[0].ProductVersionLS) != (0x00010003, 0):
            raise ValueError('Windows product version differs from 1.3.0')
        if not {3, 14}.issubset({entry.id for entry in image.DIRECTORY_ENTRY_RESOURCE.entries}):
            raise ValueError('The Windows executable icon resources are missing')

    source = Path(__file__).resolve().parents[1]
    if (directory / 'VERSION_INFO.txt').read_bytes() != (
            source / 'line_check_assistant/packaging_assets/QT_VERSION_INFO.txt').read_bytes():
        raise ValueError('Qt validation version information differs from the source')
    icon = QT_ICON_RELATIVE_PATH
    if files[icon].read_bytes() != (source / icon).read_bytes():
        raise ValueError('Qt application icon differs from the source')
    with zipfile.ZipFile(portable_zip) as bundle:
        root = 'DUTPilot_portable/'
        zipped = [name.removeprefix(root) for name in bundle.namelist() if not name.endswith('/')]
        if sorted(zipped) != sorted(files):
            raise ValueError('Qt ZIP and portable directory file lists differ')
        for name, path in files.items():
            if hashlib.sha256(bundle.read(root + name)).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise ValueError('Qt ZIP entry differs from the portable file: ' + name)
    return dict(exe_bytes=exe.stat().st_size, exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                archive_entries=len(archive.toc), python_modules=len(modules), windows_gui_x64=True,
                product_version='1.3.0', directory_files=len(files), qt_zip_files_match=True,
                qt_libraries=sorted(name for name in files if name.startswith('PySide6/') and name.endswith('.dll')),
                required_modules=list(REQUIRED_QT_MODULES), required_files=list(REQUIRED_QT_FILES), qt_imports=qt_imports,
                excluded_modules=excluded)


def inspect_case_snapshot(exe: Path, portable_zip: Path, snapshot: Path, *, gui="Tk") -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.services.ai_case_store import SNAPSHOT_NAME, validate_snapshot
    expected = snapshot.read_bytes()
    payload = validate_snapshot(json.loads(expected.decode("utf-8")))
    bundled = ((exe.parent / SNAPSHOT_NAME).read_bytes() if gui == 'Qt'
               else CArchiveReader(str(exe)).extract(SNAPSHOT_NAME))
    if bundled != expected:
        if gui == 'Qt':
            raise ValueError("Qt directory case snapshot differs from the build snapshot")
        raise ValueError("Embedded case snapshot differs from the build snapshot")
    with zipfile.ZipFile(portable_zip) as bundle:
        if bundle.read("DUTPilot_portable/" + SNAPSHOT_NAME) != expected:
            raise ValueError("Portable case snapshot differs from the build snapshot")
    return {"case_count": len(payload["cases"]),
            "case_revision_count": sum(len(row["revisions"]) for row in payload["cases"]),
            "case_snapshot_sha256": hashlib.sha256(expected).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--case-snapshot", required=True, type=Path)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--gui", choices=("Tk", "Qt"), default="Tk")
    args = parser.parse_args()
    report = (inspect_qt_directory(args.exe, args.zip, args.exclude) if args.gui == 'Qt'
              else inspect_archive(args.exe, args.exclude))
    report.update(inspect_portable(args.exe, args.zip))
    report.update(inspect_case_snapshot(args.exe, args.zip, args.case_snapshot, gui=args.gui))
    report.update({
        "gui": args.gui,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "build_dependencies": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
        "exe_launched": False,
        "acceptance": "Archive/source checks only; target Windows and real-device verification pending.",
    })
    path = (args.zip.parent if args.gui == 'Qt' else args.exe.parent) / "PACKAGING_REPORT.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PACKAGE_ARCHIVE_OK exe={report['exe_bytes']} zip={report['zip_bytes']} report={path}")


if __name__ == "__main__":
    main()

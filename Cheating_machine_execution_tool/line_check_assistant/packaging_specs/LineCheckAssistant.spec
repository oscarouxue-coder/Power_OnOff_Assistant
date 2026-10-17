# -*- mode: python ; coding: utf-8 -*-
# Standard entry: build_line_check_assistant.ps1 (environment + baseline + ZIP).
from datetime import date
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(project_root))
from scripts.check_build_environment import EXCLUDED_MODULES, check_environment

check_environment(project_root)
build_info = Path(workpath) / "BUILD_INFO.txt"
build_info.parent.mkdir(parents=True, exist_ok=True)
build_info.write_text(
    "LineCheckAssistant standard slim packaging\n"
    f"Build date: {date.today().isoformat()}\n"
    "Toolchain: CPython 3.9.10 x64 / PyInstaller 5.10.1; requirements-build.txt\n"
    "Change: isolated dependency packaging; application business code is unchanged.\n"
    f"Excluded optional modules: {', '.join(EXCLUDED_MODULES)}\n"
    "Archive/environment evidence: PACKAGING_REPORT.json beside the EXE.\n"
    "2026-10-17 profile: project owner confirmed normal operation on another PC.\n"
    "Each new build still needs its applicable target/device verification.\n"
    "Do not launch a new EXE on the packaging PC. Keep the previous package for rollback.\n",
    encoding="utf-8",
)

hiddenimports = ['requests_toolbelt.adapters.source', 'paramiko', 'ping3', 'pywifi', 'configobj', 'psutil', 'test_case.powe_on_off_telnet', 'test_case.power_on_off_ssh']
hiddenimports += collect_submodules('tftpy')
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('xlrd')


block_cipher = None


a = Analysis(
    [str(project_root / 'run_line_check_assistant.py')],
    pathex=[str(project_root), str(project_root / 'Auto_power_on_off_tool')],
    binaries=[],
    datas=[(str(project_root / 'line_check_assistant/packaging_assets/VERSION_INFO.txt'), '.'), (str(build_info), '.')],
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / 'line_check_assistant/packaging_hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDED_MODULES),
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LineCheckAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / 'assets/icons/line_check_assistant_network_topology_v1.ico')],
)

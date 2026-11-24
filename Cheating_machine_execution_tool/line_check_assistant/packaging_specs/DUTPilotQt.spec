# -*- mode: python ; coding: utf-8 -*-
# Windows directory package invoked by build_line_check_assistant.ps1 -Gui Qt.
from datetime import date
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(project_root))
from scripts.check_build_environment import EXCLUDED_MODULES, check_environment
from src.services.ai_case_store import validate_snapshot

check_environment(project_root, gui='Qt')
case_snapshot = Path(os.environ['LINECHECK_CASE_SNAPSHOT'])
validate_snapshot(json.loads(case_snapshot.read_text(encoding='utf-8')))
assets = project_root / 'line_check_assistant/packaging_assets'
icon = project_root / 'assets/icons/DUTPilot-01.ico'
build_info = Path(workpath) / 'BUILD_INFO.txt'
build_info.parent.mkdir(parents=True, exist_ok=True)
build_info.write_text(
    'DUTPilot V1.3.0 PySide6 workspace\n'
    f'Build date: {date.today().isoformat()}\n'
    'Toolchain: CPython 3.9.10 x64 / PyInstaller 5.10.1 / Qt for Python 6.8.3\n'
    'Dependency locks: requirements-build.txt and requirements-qt.txt\n'
    'Archive and ZIP verification: PACKAGING_REPORT.json beside the portable directory.\n',
    encoding='utf-8',
)
license_data = [(str(assets / 'qt_licenses'), 'qt_licenses')]
for name in ('PySide6-Essentials', 'shiboken6'):
    package = distribution(name)
    record = next(file for file in package.files if file.name == 'LicenseRef-Qt-Commercial.txt')
    license_data.append((str(package.locate_file(record)), 'qt_licenses/' + name))

hidden = ['requests_toolbelt.adapters.source', 'paramiko', 'ping3', 'pywifi', 'configobj', 'psutil',
          'test_case.powe_on_off_telnet', 'test_case.power_on_off_ssh',
          'lark_oapi.ws.client', 'lark_oapi.api.im.v1', 'httpcore._backends.sync']
for name in ('tftpy', 'openpyxl', 'xlrd'):
    hidden.extend(collect_submodules(name))

a = Analysis(
    [str(project_root / 'run_dutpilot_qt.py')],
    pathex=[str(project_root), str(project_root / 'Auto_power_on_off_tool')],
    binaries=[],
    datas=[(str(build_info), '.'), (str(case_snapshot), '.'),
           (str(project_root / 'line_check_assistant_README.md'), '.'),
           (str(icon), 'assets/icons'),
           (str(icon.with_name('menu-chevron.svg')), 'assets/icons'),
           (str(icon.with_name('menu-chevron-disabled.svg')), 'assets/icons')] + license_data,
    hiddenimports=hidden,
    hookspath=[str(project_root / 'line_check_assistant/packaging_hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDED_MODULES),
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DUTPilot',
          debug=False, strip=False, upx=False, console=False,
          icon=str(icon), version=str(assets / 'QT_PE_VERSION.txt'))
# Essentials includes two Addons plugin stubs even when their implementing
# libraries are absent. Keep either plugin if a future locked build includes
# its implementation. All shipped plugins must pass the PE import check.
addon_plugins = {
    'pyside6/plugins/imageformats/qpdf.dll': 'pyside6/qt6pdf.dll',
    'pyside6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll': 'pyside6/qt6virtualkeyboard.dll',
}
destinations = {Path(name).as_posix().casefold() for name, _, _ in a.binaries}
unusable_plugins = {plugin for plugin, library in addon_plugins.items() if library not in destinations}
binaries = [entry for entry in a.binaries if Path(entry[0]).as_posix().casefold() not in unusable_plugins]
coll = COLLECT(exe, binaries, a.zipfiles, a.datas, strip=False, upx=False, name='DUTPilot_portable')

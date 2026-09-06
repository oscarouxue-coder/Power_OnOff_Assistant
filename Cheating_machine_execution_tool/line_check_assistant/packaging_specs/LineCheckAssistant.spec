# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['requests_toolbelt.adapters.source', 'paramiko', 'ping3', 'pywifi', 'configobj', 'psutil', 'test_case.powe_on_off_telnet', 'test_case.power_on_off_ssh']
hiddenimports += collect_submodules('tftpy')
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('xlrd')


block_cipher = None


a = Analysis(
    ['..\\..\\run_line_check_assistant.py'],
    pathex=['.\\Auto_power_on_off_tool'],
    binaries=[],
    datas=[('F:\\Aouxue\\Power_OnOff_Assistant\\Cheating_machine_execution_tool\\line_check_assistant\\packaging_assets\\VERSION_INFO.txt', '.')],
    hiddenimports=hiddenimports,
    hookspath=['F:\\Aouxue\\Power_OnOff_Assistant\\Cheating_machine_execution_tool\\line_check_assistant\\packaging_hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['F:\\Aouxue\\Power_OnOff_Assistant\\Cheating_machine_execution_tool\\assets\\icons\\line_check_assistant_network_topology_v1.ico'],
)

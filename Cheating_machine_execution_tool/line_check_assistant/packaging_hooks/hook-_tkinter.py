from pathlib import Path
import sys
import _tkinter


_tcl_root = Path(sys.base_prefix) / "tcl"
datas = [
    # PyInstaller 5.10.1's pyi_rth__tkinter runtime hook reads these exact
    # unversioned destinations from sys._MEIPASS. Keep them for the accepted
    # 5.x packaging contract; modern destinations alone break that runtime.
    (str(_tcl_root / f"tcl{_tkinter.TCL_VERSION}"), "tcl"),
    (str(_tcl_root / f"tk{_tkinter.TK_VERSION}"), "tk"),
    # PyInstaller 6 uses these roots. Retain both layouts for the accepted
    # 5.x packaging contract and for the current 6.x runtime hook.
    (str(_tcl_root / f"tcl{_tkinter.TCL_VERSION}"), "_tcl_data"),
    (str(_tcl_root / f"tk{_tkinter.TK_VERSION}"), "_tk_data"),
]

for source, _destination in datas:
    if not Path(source).is_dir():
        raise FileNotFoundError(f"Tkinter build data directory not found: {source}")

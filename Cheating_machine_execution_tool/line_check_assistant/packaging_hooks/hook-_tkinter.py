from pathlib import Path
import sys
import _tkinter


_tcl_root = Path(sys.base_prefix) / "tcl"
datas = [
    # PyInstaller 5.10.1's pyi_rth__tkinter runtime hook reads these exact
    # unversioned destinations from sys._MEIPASS.  Using the historical
    # _tcl_data/_tk_data names packages the files but makes every frozen Tk
    # application fail before main() with "Tcl data directory ... not found".
    (str(_tcl_root / f"tcl{_tkinter.TCL_VERSION}"), "tcl"),
    (str(_tcl_root / f"tk{_tkinter.TK_VERSION}"), "tk"),
]

for source, _destination in datas:
    if not Path(source).is_dir():
        raise FileNotFoundError(f"Tkinter build data directory not found: {source}")

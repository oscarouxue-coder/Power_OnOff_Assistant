def pre_find_module_path(hook_api):
    # The local Python can import tkinter even when PyInstaller's Tcl probe fails.
    # Keep tkinter discoverable; hook-_tkinter.py supplies its runtime data files.
    return None

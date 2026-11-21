"""Keep Tk form values stable and route their mouse wheel to the containing page."""
import tkinter as tk


def _scroll_form(event):
    parent = event.widget.master
    while parent is not None and not isinstance(parent, (tk.Tk, tk.Toplevel)):
        if isinstance(parent, tk.Canvas) and parent.cget("yscrollcommand"):
            parent.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        parent = parent.master


def configure_form_wheel(widget):
    root = widget._root()
    if not vars(root).get("_form_wheel_configured"):
        for kind in ("TCombobox", "TSpinbox"):
            root.bind_class(kind, "<MouseWheel>", _scroll_form)
        root._form_wheel_configured = True

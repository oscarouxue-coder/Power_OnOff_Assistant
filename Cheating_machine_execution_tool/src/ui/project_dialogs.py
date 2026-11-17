"""Existing message-box semantics, with the owning project in managed titles."""
from tkinter import messagebox as _native


def __getattr__(name):
    # Preserve native constants such as CANCEL and any unchanged public helper.
    return getattr(_native, name)


def _call(name, title=None, message=None, **kwargs):
    parent = kwargs.get('parent')
    seen = set()
    while parent is not None and id(parent) not in seen:
        seen.add(id(parent))
        context = vars(parent).get('project_context')
        if context is not None:
            title = (title or '') + ' · ' + context.identity.name
            break
        parent = vars(parent).get('master')
    return getattr(_native, name)(title, message, **kwargs)


def showinfo(title=None, message=None, **kwargs):
    return _call('showinfo', title, message, **kwargs)


def showwarning(title=None, message=None, **kwargs):
    return _call('showwarning', title, message, **kwargs)


def showerror(title=None, message=None, **kwargs):
    return _call('showerror', title, message, **kwargs)


def askyesno(title=None, message=None, **kwargs):
    return _call('askyesno', title, message, **kwargs)


def askyesnocancel(title=None, message=None, **kwargs):
    return _call('askyesnocancel', title, message, **kwargs)


def askokcancel(title=None, message=None, **kwargs):
    return _call('askokcancel', title, message, **kwargs)

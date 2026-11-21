"""Compatibility exports, loaded only when the corresponding UI is requested.

Qt pages can import this package without loading the Tk window implementations.
Existing ``from src.ui import SerialTerminalWindow`` callers retain their API.
"""
from importlib import import_module

__all__ = [
    "DutConfigWindow",
    "MODULE_WINDOW_SIZE_STATE_PATH",
    "SerialTerminalWindow",
    "clamp_module_window_size",
    "load_module_window_size",
    "save_module_window_size",
]


def __getattr__(name):
    modules = {'SerialTerminalWindow': 'serial_terminal', 'DutConfigWindow': 'dut_config_window'}
    if name not in __all__:
        raise AttributeError(name)
    module = modules.get(name, 'window_size_state')
    value = getattr(import_module('.' + module, __name__), name)
    globals()[name] = value
    return value

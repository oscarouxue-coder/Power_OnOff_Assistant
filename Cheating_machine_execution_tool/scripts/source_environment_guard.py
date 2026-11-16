"""Standard-library-only guard before source imports during environment repair."""
import ctypes
import hashlib
import os
from pathlib import Path
import sys


def repair_identity(prefix=None):
    return 'feishu-sdk-repair:' + str(Path(sys.prefix if prefix is None else prefix).resolve()).casefold()


def ensure_source_environment_available(prefix=None):
    if os.name != 'nt' or getattr(sys, 'frozen', False):
        return
    name = 'Local\\LineCheckDingTalk_' + hashlib.sha256(repair_identity(prefix).encode()).hexdigest()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    ctypes.set_last_error(0)
    handle = kernel.OpenMutexW(0x00100000, False, name)
    if handle:
        kernel.CloseHandle(handle)
        raise RuntimeError('当前Python环境正在安装飞书SDK，请等待安装结束后再启动程序。')
    if ctypes.get_last_error() != 2:  # ERROR_FILE_NOT_FOUND: no repair owns this environment.
        raise RuntimeError('无法核对当前Python环境的安装保护，请检查权限后重试。')

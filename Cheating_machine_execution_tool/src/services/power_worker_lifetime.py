"""Check a managed power worker's lifetime without controlling the process or any device."""
import ctypes
import json
import multiprocessing
import os
from pathlib import Path
import sys
import uuid

import psutil

from src.models.capabilities import CapabilityError
from src.models.project import PROJECT_FILE


POWER_JOB_IDS = frozenset(('aging.start', 'aging.resume', 'pipeline.start'))
ACTIVE = '原开关机子进程仍在运行，退出前不能解除保护'
UNVERIFIED = '原开关机子进程存活状态暂时无法核实，保护已保留'
_child_handle = None


def _event_name(project_id):
    return 'Global\\DUTPilotPowerWorker_' + uuid.UUID(project_id).hex


def _kernel():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def publish_power_worker(tool_root):
    """Called inside the dedicated child, before the serial port or any device action."""
    parent = multiprocessing.parent_process()
    if parent is None or os.name != 'nt':
        return
    run = tool_root.parent
    if run.parent.name != 'runs' or not (run.parent.parent / PROJECT_FILE).is_file():
        return
    record = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    descriptor = json.loads((run.parent.parent / PROJECT_FILE).read_text(encoding='utf-8'))
    if record['run_id'] != run.name or record['project_id'] != descriptor['project_id']:
        raise ValueError('项目任务快照与运行标识不一致')
    # Every original/resumed child holds its own reference until Windows closes
    # the process. Neither a crashed parent nor another project's review owns it.
    kernel = _kernel()
    handle = kernel.CreateEventW(None, True, False, _event_name(record['project_id']))
    if not handle:
        raise OSError('无法登记开关机子进程，本次未启动设备操作')
    if not parent.is_alive():
        kernel.CloseHandle(handle)
        raise RuntimeError('原操作进程在子进程登记前已退出，本次未启动设备操作')
    global _child_handle
    _child_handle = handle


def _legacy_worker_notice(context):
    """Older builds already run their multiprocessing worker in its project tool directory."""
    names = {'python.exe', 'pythonw.exe', 'dutpilot.exe', 'linecheckassistant.exe', Path(sys.executable).name.casefold()}
    unsure = False
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').casefold() not in names or process.pid == os.getpid():
            continue
        try:
            if '--multiprocessing-fork' not in process.cmdline():
                continue
            working = Path(process.cwd())
            if working.name.casefold() != 'auto_power_on_off_tool':
                continue
            if (working.parent == context.working_root or
                    working.parent.parent in (context.root / 'runs', context.root / 'revisions')):
                return ACTIVE + f'（PID {process.pid}）'
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
        except (psutil.AccessDenied, OSError):
            unsure = True
    return UNVERIFIED if unsure else ''


def power_worker_notice(context):
    if context is None or os.name != 'nt':
        return ''
    try:
        kernel = _kernel()
        handle = kernel.OpenEventW(0x00100000, False, _event_name(context.identity.project_id))
        if handle:
            kernel.CloseHandle(handle)
            return ACTIVE
        if ctypes.get_last_error() != 2:  # ERROR_FILE_NOT_FOUND means no surviving handle.
            return UNVERIFIED
        return _legacy_worker_notice(context)
    except (OSError, ValueError, psutil.Error):
        return UNVERIFIED


def guard_power_worker_review(context):
    notice = power_worker_notice(context)
    if notice:
        raise CapabilityError('power_worker_unverified', notice)

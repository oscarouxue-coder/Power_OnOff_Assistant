"""Restart source entry once, only after the previous process really exits."""
import os
from pathlib import Path
import subprocess
import sys

from src.core.feishu_dependency_install import subprocess_environment


def restart_command(root, arguments=None):
    root = Path(root).resolve()
    entry = root / "run_line_check_assistant.py"
    if getattr(sys, "frozen", False) or not entry.is_file():
        raise RuntimeError("源码重启入口不可用，请手动重新启动程序")
    return [sys.executable, str(entry)] + list(sys.argv[1:] if arguments is None else arguments)


def launch_restart_helper(root, arguments=None, popen=subprocess.Popen, cwd=None):
    import psutil
    command = restart_command(root, arguments)
    helper = Path(root).resolve() / "scripts" / "restart_source_after_exit.py"
    if not helper.is_file():
        raise RuntimeError("缺少安全重启助手，请手动重新启动程序")
    return popen([sys.executable, "-B", str(helper), str(os.getpid()), str(psutil.Process().create_time()),
                  os.getcwd() if cwd is None else str(cwd)] + command, env=subprocess_environment(),
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def wait_and_restart(pid, created, cwd, command, process_factory=None, popen=subprocess.Popen):
    import psutil
    process_factory = process_factory or psutil.Process
    if len(command) < 2 or not Path(command[0]).is_absolute() or not Path(command[1]).is_file():
        raise RuntimeError("重启命令无效，请手动重新启动程序")
    try:
        previous = process_factory(int(pid))
        if previous.create_time() == float(created):
            previous.wait(timeout=120)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        raise RuntimeError("原程序尚未退出，未启动第二个实例；请关闭原程序后手动启动") from None
    return popen(command, cwd=cwd, env=subprocess_environment())

"""Start the DUTPilot Qt workspace or an explicitly selected preview."""
import argparse
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys


def report_startup_error(message):
    if sys.stderr is None and os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, '暂不能启动 DUTPilot', 0x10)
    else:
        print(message, file=sys.stderr)


def start_with_qt_environment(arguments):
    if getattr(sys, 'frozen', False):
        report_startup_error('Qt 运行库缺失。请将完整的 DUTPilot 便携 ZIP 解压到新目录后启动。')
        return 2
    local = os.environ.get('LOCALAPPDATA')
    if local:
        executable = 'pythonw.exe' if Path(sys.executable).name.lower() == 'pythonw.exe' else 'python.exe'
        python = Path(local) / 'LineCheckAssistant' / 'qt-dev-py39' / 'Scripts' / executable
        if python.is_file() and python.resolve() != Path(sys.executable).resolve():
            try:
                return subprocess.call([str(python), str(Path(__file__).resolve()), *arguments])
            except OSError as error:
                report_startup_error(str(error))
    setup = Path(__file__).resolve().parent / 'scripts' / 'setup_qt_environment.ps1'
    report_startup_error(f'请在 PowerShell 执行以下命令准备 Qt 环境，再重新启动：\n'
                         f'powershell -NoProfile -ExecutionPolicy Bypass -File "{setup}" -WithBusinessDependencies')
    return 2


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description='DUTPilot Qt 工作台')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='使用明确标记的演示数据，不连接硬件或写项目')
    mode.add_argument('--showcase', action='store_true', help='打开独立的 GUI 组件展示页')
    mode.add_argument('--visual-preview', action='store_true', help='比较工作台改版前后的模拟界面')
    mode.add_argument('--workspace', action='store_true', help='打开多项目工作台')
    parser.add_argument('--project-peers', type=Path, metavar='JSON', help='以已配置的可信实例按项目路由群消息')
    parser.add_argument('project', nargs='?', help='显式打开原项目文件或项目目录，不自动恢复任务')
    parser.add_argument('--gateway-slot', type=int, help='显式启用已配对并在本地允许的统一接入槽位 1 至 64')
    parser.add_argument('--legacy-single-project', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.legacy_single_project:
        report_startup_error('单项目入口已停用。请启动 Qt 工作台，在项目菜单打开项目或选择「导入旧配置目录…」。')
        return 2
    if args.gateway_slot is not None and not 1 <= args.gateway_slot <= 64:
        parser.error('统一接入槽位须为1至64')
    if (args.demo or args.showcase or args.visual_preview) and (args.project or args.project_peers or args.gateway_slot is not None):
        parser.error('项目路径、网关槽位和群消息路由仅适用于工作台')
    from scripts.source_environment_guard import ensure_source_environment_available
    try:
        ensure_source_environment_available()
    except RuntimeError as error:
        report_startup_error(str(error))
        return 1
    try:
        from src.ui.qt.application import run_demo, run_showcase, run_visual_preview, run_workspace
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith(('PySide6', 'shiboken6')):
            return start_with_qt_environment(arguments)
        raise
    if args.gateway_slot is not None:
        os.environ['LINECHECK_GATEWAY_SLOT'] = str(args.gateway_slot)
    if args.project_peers:
        os.environ['DUTPILOT_PROJECT_PEERS'] = str(args.project_peers.resolve())
    if args.showcase:
        return run_showcase()
    if args.visual_preview:
        return run_visual_preview()
    if args.demo:
        return run_demo()
    # A running workspace may have a different working directory from this caller.
    project = os.path.abspath(args.project) if args.project else None
    return run_workspace(project)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.exit(main())

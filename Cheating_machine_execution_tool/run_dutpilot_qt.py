"""Opt-in Qt migration entry. The existing Tk launcher remains the default."""
import argparse
import multiprocessing
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='DUTPilot PySide6 迁移验证版')
    mode = parser.add_mutually_exclusive_group(required=not getattr(sys, 'frozen', False))
    mode.add_argument('--demo', action='store_true', help='使用明确标记的演示数据，不连接硬件或写项目')
    mode.add_argument('--workspace', action='store_true', help='打开多项目工作台')
    parser.add_argument('--project-peers', type=Path, metavar='JSON', help='以已配置的可信实例按项目路由群消息')
    parser.add_argument('project', nargs='?', help='显式打开原项目文件或项目目录，不自动恢复任务')
    args = parser.parse_args(argv)
    if args.demo and args.project:
        parser.error('演示模式不打开真实项目')
    if args.project_peers and args.demo:
        parser.error('演示模式不接收群消息')
    from scripts.source_environment_guard import ensure_source_environment_available
    try:
        ensure_source_environment_available()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    try:
        from src.ui.qt.application import run_demo, run_workspace
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith(('PySide6', 'shiboken6')):
            print('缺少独立Qt环境。请运行 scripts/setup_qt_environment.ps1 后使用该环境启动。', file=sys.stderr)
            return 2
        raise
    if args.project_peers:
        os.environ['DUTPILOT_PROJECT_PEERS'] = str(args.project_peers.resolve())
    return run_demo() if args.demo else run_workspace(args.project)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.exit(main())

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    import argparse
    import os
    parser = argparse.ArgumentParser(description="LineCheckAssistant")
    parser.add_argument('project', nargs='?', help='要打开的project.linecheck.json或项目文件夹')
    parser.add_argument('--legacy-single-project', action='store_true', help='兼容回退：使用原程序目录配置的单项目入口')
    parser.add_argument("--gateway-slot", type=int, help="显式启用已配对并在本地允许的统一接入槽位1至64")
    args = parser.parse_args()
    if args.legacy_single_project:
        os.environ['LINECHECK_LEGACY_SINGLE_PROJECT'] = '1'
    if args.gateway_slot is not None:
        if not 1 <= args.gateway_slot <= 64:
            parser.error("统一接入槽位须为1至64")
        os.environ["LINECHECK_GATEWAY_SLOT"] = str(args.gateway_slot)

    import sys
    if not getattr(sys, 'frozen', False):
        from scripts.source_environment_guard import ensure_source_environment_available
        try:
            ensure_source_environment_available()
        except RuntimeError as exc:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), '暂不能启动程序', 0x10)
            raise SystemExit(1)

    from line_check_assistant.app import main

    main(args.project)

"""Internal source restart helper; no dependency installation or device commands."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.source_restart import wait_and_restart


def main():
    try:
        if len(sys.argv) < 6:
            raise RuntimeError("重启参数不完整，请手动启动程序")
        wait_and_restart(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
        return 0
    except Exception:
        from tkinter import messagebox
        messagebox.showerror("重启未完成", "未能自动重新启动。请确认原程序已退出，再从原源码入口手动启动。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

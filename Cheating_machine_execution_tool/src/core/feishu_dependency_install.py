"""Bounded, locked installation of Feishu wheels into the current source venv only."""
import email.parser
import importlib.metadata
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(root):
    versions = {}
    for raw in (Path(root) / "requirements-build.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line or line.startswith("-r "):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.+_-]+)", line)
        if not match:
            raise ValueError("依赖锁定清单无效，未安装")
        name, version = normalized(match[1]), match[2]
        if name in versions and versions[name] != version:
            raise ValueError("依赖锁定清单包含冲突版本，未安装")
        versions[name] = version
    if versions.get("lark-oapi") != "1.7.5":
        raise ValueError("飞书SDK锁定版本无效，未安装")
    return versions


def source_environment(root):
    if getattr(sys, "frozen", False):
        raise ValueError("当前为EXE，请下载并完整解压新版便携ZIP；不能通过pip修补包内SDK")
    root = Path(root).resolve()
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    if (sys.platform != "win32" or sys.version_info[:3] != (3, 9, 10)
            or struct.calcsize("P") != 8 or sys.prefix == sys.base_prefix or not cfg.is_file()):
        raise ValueError("自动安装仅支持源码专用的CPython 3.9.10 x64虚拟环境，请先配置项目运行环境")
    settings = {k.strip(): v.strip() for k, v in
                (line.lower().split("=", 1) for line in cfg.read_text(encoding="utf-8").splitlines() if "=" in line)}
    if settings.get("include-system-site-packages") != "false":
        raise ValueError("虚拟环境必须与全局依赖隔离，未安装")
    if not (root / "run_dutpilot_qt.py").is_file():
        raise ValueError("源码入口不存在，未安装")
    locked_versions(root)
    try:
        with tempfile.TemporaryFile(dir=sys.prefix):
            pass
    except OSError:
        raise ValueError("当前虚拟环境不可写，请检查权限后重试") from None
    return root


def assert_environment_unoccupied():
    """Resolve Windows venv launchers; refuse same/ambiguous environments."""
    import psutil
    current = psutil.Process()
    allowed = {current.pid, *(p.pid for p in current.parents()), *(p.pid for p in current.children(recursive=True))}
    def canonical(path):
        return os.path.normcase(os.path.realpath(path))
    paths = {canonical(Path(sys.prefix) / 'Scripts' / name) for name in ('python.exe', 'pythonw.exe')}
    paths.add(canonical(sys.executable))
    base = Path(getattr(sys, '_base_executable', sys.executable)).parent
    base_paths = {canonical(base / name) for name in ('python.exe', 'pythonw.exe')}
    for process in psutil.process_iter(["pid", "name"]):
        if process.pid in allowed or (process.info["name"] or "").lower() not in ("python.exe", "pythonw.exe"):
            continue
        try:
            candidates = [process.exe()] + process.cmdline()[:1]
            if any(canonical(p) in paths for p in candidates if p):
                raise ValueError("当前Python环境正由其他程序实例使用，请关闭相关程序后重试")
            if any(canonical(p) in base_paths for p in candidates if p):
                for parent in process.parents():
                    if (parent.name() or '').lower() not in ('python.exe', 'pythonw.exe'):
                        break
                    candidates += [parent.exe()] + parent.cmdline()[:1]
                if any(canonical(p) in paths for p in candidates if p):
                    raise ValueError("当前Python环境正由其他程序实例使用，请关闭相关程序后重试")
                known_other = any((Path(p).parent.parent / 'pyvenv.cfg').is_file()
                                  for p in candidates if p and Path(p).parent.name.lower() == 'scripts')
                if not known_other:
                    raise ValueError("无法排除其他Python进程占用当前环境，请关闭相关Python程序后重试")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            raise ValueError("无法核对其他Python进程的环境占用，未安装；请检查权限后重试") from None


def subprocess_environment():
    result = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        result.pop(name, None)
    result["PYTHONUTF8"] = "1"
    result["PYTHONIOENCODING"] = "utf-8"
    return result


def run_checked(arguments, stage, emit, timeout=180, runner=subprocess.run):
    # Pip output may contain authenticated index/proxy URLs; never publish it.
    emit("[飞书依赖] 下发：" + subprocess.list2cmdline(arguments))
    try:
        result = runner(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        env=subprocess_environment(), timeout=timeout,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError(stage + "超时，请检查网络或环境后重试") from None
    except OSError:
        raise RuntimeError(stage + "进程启动失败，请检查当前Python环境") from None
    if result.returncode:
        output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else str(result.stdout)
        lower = output.lower()
        reason = ("网络或代理连接失败" if any(t in lower for t in ('connectionerror', 'proxyerror', 'connection refused', 'timed out', 'retrying')) else
                  "证书校验失败" if 'certificate_verify_failed' in lower else
                  "依赖版本冲突" if any(t in lower for t in ('incompatible', 'conflicting', 'resolutionimpossible', 'requires ')) else
                  "环境文件被占用或权限不足" if any(t in lower for t in ('access is denied', 'permission denied', 'winerror 5', 'winerror 32')) else
                  "依赖下载或环境检查未通过")
        raise RuntimeError(stage + "失败（退出码" + str(result.returncode) + "）：" + reason + "；请处理后重试")
    return result


def checked_wheels(directory, versions):
    wheels, found = [], set()
    for path in sorted(Path(directory).iterdir()):
        if path.suffix != ".whl":
            raise ValueError("下载结果含非wheel文件，未安装")
        with zipfile.ZipFile(path) as archive:
            metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1 or archive.getinfo(metadata[0]).file_size > 1024 * 1024:
                raise ValueError("依赖wheel元数据无效，未安装")
            message = email.parser.BytesParser().parsebytes(archive.read(metadata[0]))
        name, version = normalized(message.get("Name", "")), message.get("Version", "")
        if name in found or versions.get(name) != version:
            raise ValueError("下载依赖不符合项目锁定清单，未安装：" + name)
        found.add(name)
        wheels.append((name, version, path))
    if "lark-oapi" not in found:
        raise ValueError("下载结果缺少飞书SDK，未安装")
    return wheels


def install_feishu(root, emit, runner=subprocess.run):
    root = source_environment(root)
    versions = locked_versions(root)
    assert_environment_unoccupied()
    python = [sys.executable, "-I", "-X", "utf8"]
    with tempfile.TemporaryDirectory(prefix="linecheck-feishu-") as directory:
        folder = Path(directory)
        wheels = folder / "wheels"
        wheels.mkdir()
        constraints = folder / "constraints.txt"
        constraints.write_text("".join(f"{name}=={version}\n" for name, version in sorted(versions.items())), encoding="utf-8")
        emit("[飞书依赖] 正在下载SDK及必要依赖，所有版本受项目锁定清单约束")
        run_checked(python + ["-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
            "--timeout", "15", "--retries", "1", "--dest", str(wheels), "--constraint", str(constraints),
            "lark-oapi==" + versions["lark-oapi"]], "下载飞书依赖", emit, runner=runner)
        selected = []
        checked = checked_wheels(wheels, versions)
        for name, version, path in checked:
            try:
                installed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                installed = None
            if installed != version or name == "lark-oapi":
                selected.append(str(path))
        assert_environment_unoccupied()
        emit("[飞书依赖] 下载检查通过，开始离线安装")
        # Force only selected wheels: same-version healthy dependencies are untouched.
        run_checked(python + ["-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps",
            "--force-reinstall"] + selected, "安装飞书依赖", emit, runner=runner)
    emit("[飞书依赖] 正在验证SDK真实导入、锁定版本及依赖一致性")
    expected = {name: version for name, version, _ in checked}
    probe = ("import asyncio,importlib.metadata; asyncio.set_event_loop(asyncio.new_event_loop()); "
             "import lark_oapi.ws.client; from lark_oapi.core.const import VERSION; "
             "assert VERSION == '1.7.5'; import websockets.sync.client; "
             f"assert all(importlib.metadata.version(n) == v for n,v in {expected!r}.items())")
    run_checked(python + ["-c", probe], "验证飞书SDK", emit, timeout=60, runner=runner)
    run_checked(python + ["-m", "pip", "check"], "验证依赖一致性", emit, timeout=60, runner=runner)
    emit("[飞书依赖] 安装及验证成功")

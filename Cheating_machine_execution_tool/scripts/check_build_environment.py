"""Validate the accepted slim packaging profile without importing the app."""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys


PYTHON_VERSION = (3, 9, 10)
EXCLUDED_MODULES = ("numpy", "lxml", "PyQt5")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(root: Path) -> dict[str, str]:
    versions = {}
    for line in (root / "requirements-build.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line or line.startswith("-r "):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if not match:
            raise ValueError("Build dependencies must be exactly pinned: " + line)
        versions[normalized(match[1])] = match[2]
    if not versions:
        raise ValueError("Empty build dependency lock")
    return versions


def check_environment(root: Path = PROJECT_ROOT) -> dict:
    if sys.platform != "win32" or sys.version_info[:3] != PYTHON_VERSION or struct.calcsize("P") != 8:
        raise ValueError("Standard packaging requires CPython 3.9.10 x64 on Windows")
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    if sys.prefix == sys.base_prefix or not cfg.is_file():
        raise ValueError("Use the isolated packaging environment, not global Python")
    settings = dict(line.lower().split("=", 1) for line in cfg.read_text(encoding="utf-8").splitlines() if "=" in line)
    settings = {key.strip(): value.strip() for key, value in settings.items()}
    if settings.get("include-system-site-packages") != "false":
        raise ValueError("System site-packages must be disabled")
    expected = locked_versions(root)
    installed = {normalized(d.metadata["Name"]): d.version for d in importlib.metadata.distributions()}
    mismatches = [f"{name}: expected {version}, found {installed.get(name, 'missing')}" for name, version in expected.items() if installed.get(name) != version]
    if mismatches:
        raise ValueError("Build dependency drift: " + "; ".join(mismatches))
    extra = sorted(set(installed) - set(expected) - {"pip"})
    if extra:
        raise ValueError("Unexpected packages in build environment: " + ", ".join(extra))
    unwanted = [name for name in EXCLUDED_MODULES if importlib.util.find_spec(name) is not None]
    if unwanted:
        raise ValueError("Optional heavy dependencies must be absent: " + ", ".join(unwanted))
    return {"python": ".".join(map(str, PYTHON_VERSION)), "architecture": "x64", "dependencies": installed, "excluded_modules": list(EXCLUDED_MODULES)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = check_environment()
    except ValueError as exc:
        parser.exit(1, f"BUILD_ENVIRONMENT_FAILED: {exc}\n")
    print(json.dumps(report, indent=2) if args.json else "BUILD_ENVIRONMENT_OK CPython 3.9.10 x64; locked dependencies; numpy/lxml/PyQt5 absent")


if __name__ == "__main__":
    main()

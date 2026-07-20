"""项目级回归基线检查脚本(Q1=A 的工程兑现)。

封装 `ACCEPTANCE_BASELINE.md §0 / §1.3 / §1.4` 的全部检查,作为提交前必跑的最低门禁
(参见 `AGENTS.md` 规则 13 与 `.claude/skills/line-check-dev/SKILL.md §5 / §11`)。

执行 4 类检查:
1. **py_compile**: 全量 `src/` + `line_check_assistant/` 下的关键模块能编译
2. **unittest**: 全量测试通过,且能解析 `Ran N tests` 行(防止静默 0 项 / 误报 OK)
3. **must_exist**: §1.3 的 8 条协议不变量必须在指定目录下命中
4. **must_not_exist**: §1.3 / §1.4 的禁止模式(`0.0.0.0` 等)不能在指定文件的**代码行**中出现
   (跳过注释 / 文档字符串,避免反向语义误报)

退出码: 0 全部通过 / 1 任一失败。

设计要点:
- **单一来源**: `MUST_EXIST` / `MUST_NOT_EXIST` / `PY_COMPILE_FILES` 三个常量在本文件;
  `AGENTS.md` 中同名章节是可读副本,改任何一处都必须同步另一处。
- **跨平台**: 纯 Python + 标准库,Windows / Linux / macOS 直接可跑。
- **可测试**: 核心检查函数是纯函数,接受 `project_root: Path`,用 `tempfile.TemporaryDirectory`
  构造临时源码即可单元测试(参见 `tests/test_verify_baseline.py`)。
- **不引入新依赖**: 仅用 `subprocess` / `pathlib` / `re` / `sys`。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple


# 匹配三引号字符串(文档字符串 / 长字符串),用于在 grep 时跳过。
_DOCSTRING_PATTERN = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', re.MULTILINE)


class CheckResult(NamedTuple):
    """单条检查结果。"""

    name: str
    passed: bool
    detail: str = ""

    def render(self) -> str:
        marker = "OK  " if self.passed else "FAIL"
        suffix = f" - {self.detail}" if self.detail else ""
        return f"  [{marker}] {self.name}{suffix}"


# 1. py_compile 文件清单(以 `ACCEPTANCE_BASELINE.md §0` + 当前 `src/` / `line_check_assistant/`
#    下全部 .py 为准;新增 .py 后必须手工补到本列表)。
PY_COMPILE_FILES: tuple[str, ...] = (
    # line_check_assistant 包
    "line_check_assistant/app.py",
    "line_check_assistant/config_store.py",
    "line_check_assistant/network_ops.py",
    "line_check_assistant/onu_registration_store.py",
    "line_check_assistant/page_upgrade.py",
    "line_check_assistant/paths.py",
    "line_check_assistant/pipeline_window.py",
    "line_check_assistant/sample_upgrade_settings_store.py",
    "line_check_assistant/serial_ports.py",
    "line_check_assistant/test_item_config_store.py",
    # src 包
    "src/config.py",
    "src/ui/serial_terminal.py",
    "src/services/pipeline_orchestrator.py",
    "src/services/power_on_service.py",
    "src/services/sample_parameter_service.py",
    "src/services/serial_upgrade_service.py",
    "src/services/test_item_execution_service.py",
    "src/core/bind_socket.py",
    "src/core/fuzzy_match_runner.py",
    "src/core/parameter_session.py",
    "src/core/power_supply.py",
    "src/core/sample_parameter_table.py",
    "src/core/serial_transport.py",
    "src/core/telnet_transport.py",
    "src/core/tftp_transport.py",
    "src/core/ubus_enable_telnet.py",
    "src/core/ubus_http_client.py",
    "src/models/sample_parameter_models.py",
    "src/models/serial_models.py",
)

# 2. 必须命中(§1.3 / §1.4) - (pattern, 搜索目录组)
MUST_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bbfdm.operate", ("src/", "line_check_assistant/")),
    ("tclinux_allinone", ("src/",)),
    ("192.168.1.1", ("src/",)),
    ("vlan_to_serial_port", ("src/", "line_check_assistant/")),
    ("MAX_PARALLEL_UPGRADES = 8", ("src/", "line_check_assistant/")),
    ("clamp_parallel_count", ("src/", "line_check_assistant/")),
    ("source_address=(bind_ip, 0)", ("src/", "line_check_assistant/")),
    ("Device.Firewall.<X_SDMC_>Security.AccessCtrl", ("src/",)),
)

# 3. 必须不出现(§1.3 / §1.4) - (pattern, 限制文件列表)
MUST_NOT_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0.0.0.0", ("src/core/tftp_transport.py", "src/core/telnet_transport.py")),
)


def _glob_py_files(project_root: Path, dirs: Iterable[str]) -> list[Path]:
    """在 `dirs` 下递归收集所有 `.py` 文件。目录不存在时静默跳过。"""
    files: list[Path] = []
    for d in dirs:
        base = project_root / d
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _is_code_line(line: str) -> bool:
    """判断是否为代码行(排除纯注释行)。

    用于 `must_not_exist` 避开反向语义注释(如「不回退 0.0.0.0」)导致的误报。
    """
    return not line.lstrip().startswith("#")


def _strip_docstrings(content: str) -> str:
    """把三引号字符串(文档字符串 / 长字符串)替换为同长度的空白,保留行号。

    行内 `\n` 保留为空行,其余字符替换为空格。这样后续 grep `pattern in content`
    时,文档字符串里出现的禁止字符串(如「不回退 0.0.0.0」)不会触发误报。
    """
    def replace_with_whitespace(match: re.Match) -> str:
        text = match.group(0)
        return "".join("\n" if c == "\n" else " " for c in text)

    return _DOCSTRING_PATTERN.sub(replace_with_whitespace, content)


def _code_lines(content: str) -> list[tuple[int, str]]:
    """返回 (行号 1-based, 行内容) 列表,跳过文档字符串 + 纯注释行。"""
    stripped = _strip_docstrings(content)
    return [
        (idx + 1, line)
        for idx, line in enumerate(stripped.splitlines())
        if _is_code_line(line)
    ]


def run_py_compile(project_root: Path) -> CheckResult:
    """对 `PY_COMPILE_FILES` 全部运行 `python -m py_compile`。"""
    files = [str(project_root / f) for f in PY_COMPILE_FILES]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return CheckResult(
            "py_compile",
            False,
            f"missing files: {', '.join(Path(m).name for m in missing)}",
        )
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", *files],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if proc.returncode == 0:
        return CheckResult("py_compile", True, f"{len(files)} files compiled")
    return CheckResult("py_compile", False, (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "unknown error")


def run_unittest(project_root: Path) -> CheckResult:
    """运行 `python -m unittest discover -s tests` 并解析 `Ran N tests` 行。"""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    output = proc.stdout + proc.stderr
    match = re.search(r"Ran (\d+) tests?", output)
    if proc.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-5:])
        return CheckResult("unittest", False, f"non-zero exit; tail: {tail}")
    if match is None:
        return CheckResult(
            "unittest",
            False,
            f"could not parse 'Ran N tests' from output; tail: {output[-200:]}",
        )
    return CheckResult("unittest", True, f"Ran {match.group(1)} tests")


def check_must_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_EXIST` pattern 是否在指定目录下命中。"""
    results: list[CheckResult] = []
    for pattern, dir_groups in MUST_EXIST:
        files = _glob_py_files(project_root, dir_groups)
        found_in: list[str] = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern in content:
                found_in.append(str(f.relative_to(project_root)))
        if found_in:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=True,
                    detail=f"hit in {found_in[0]}" + (f" (+{len(found_in) - 1})" if len(found_in) > 1 else ""),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=False,
                    detail=f"not found in {','.join(dir_groups)}",
                )
            )
    return results


def check_must_not_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_NOT_EXIST` pattern 是否在限制文件的**代码行**中出现。

    跳过纯注释行(以 `#` 开头)以避免反向语义注释(例如「不回退 0.0.0.0」)误报。
    """
    results: list[CheckResult] = []
    for pattern, file_paths in MUST_NOT_EXIST:
        bad_locations: list[str] = []
        for fp in file_paths:
            full = project_root / fp
            if not full.exists():
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_no, line in _code_lines(content):
                if pattern in line:
                    bad_locations.append(f"{fp}:{line_no}")
                    break  # 每个文件只报一次,避免重复
        if bad_locations:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=False,
                    detail=f"found in code lines: {','.join(bad_locations)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=True,
                    detail=f"absent from code lines of {','.join(file_paths)}",
                )
            )
    return results


def collect_results(project_root: Path) -> list[CheckResult]:
    """串联所有 4 类检查,返回完整结果列表。"""
    results: list[CheckResult] = []
    results.append(run_py_compile(project_root))
    results.append(run_unittest(project_root))
    results.extend(check_must_exist(project_root))
    results.extend(check_must_not_exist(project_root))
    return results


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Project root: {project_root}")
    print()

    results = collect_results(project_root)
    for r in results:
        print(r.render())

    print()
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"FAILED: {len(failed)} check(s) failed")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
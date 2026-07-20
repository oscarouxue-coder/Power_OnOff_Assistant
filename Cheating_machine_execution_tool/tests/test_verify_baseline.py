"""`scripts/verify_baseline.py` 自身的不变量测试。

保护 `MUST_EXIST` / `MUST_NOT_EXIST` / `PY_COMPILE_FILES` 三个常量的结构合法性,
以及核心检查函数 `check_must_exist` / `check_must_not_exist` 在临时目录下的命中/缺失行为。
防止「不变量清单被改错」或「检查函数被改坏」导致门禁误判。

不依赖 subprocess,所有用例在 tempfile 临时目录构造最小化源码,毫秒级跑完。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 把 scripts/ 加进 sys.path 才能 import verify_baseline
_SCRIPTS_DIR = (
    Path(os.path.dirname(os.path.abspath(__file__))).parent / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from verify_baseline import (  # noqa: E402  (sys.path mutation above)
    MUST_EXIST,
    MUST_NOT_EXIST,
    PY_COMPILE_FILES,
    check_must_exist,
    check_must_not_exist,
)


class VerifyBaselineStructureTests(unittest.TestCase):
    """常量列表结构合法性。"""

    def test_must_exist_is_non_empty_and_well_formed(self):
        self.assertGreater(len(MUST_EXIST), 0)
        for entry in MUST_EXIST:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)
            pattern, dirs = entry
            self.assertIsInstance(pattern, str)
            self.assertGreater(len(pattern), 0)
            self.assertIsInstance(dirs, tuple)
            self.assertGreater(len(dirs), 0)
            for d in dirs:
                self.assertIsInstance(d, str)
                self.assertTrue(d.endswith("/"), f"dir {d!r} should end with '/'")

    def test_must_not_exist_is_non_empty_and_well_formed(self):
        self.assertGreater(len(MUST_NOT_EXIST), 0)
        for entry in MUST_NOT_EXIST:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)
            pattern, files = entry
            self.assertIsInstance(pattern, str)
            self.assertGreater(len(pattern), 0)
            self.assertIsInstance(files, tuple)
            self.assertGreater(len(files), 0)
            for fp in files:
                self.assertIsInstance(fp, str)
                self.assertTrue(fp.endswith(".py"), f"file {fp!r} should end with '.py'")

    def test_py_compile_files_under_allowed_dirs(self):
        """`PY_COMPILE_FILES` 全部位于 `line_check_assistant/` 或 `src/` 下。"""
        self.assertGreater(len(PY_COMPILE_FILES), 0)
        for f in PY_COMPILE_FILES:
            self.assertIsInstance(f, str)
            self.assertTrue(
                f.startswith("line_check_assistant/") or f.startswith("src/"),
                f"{f!r} must be under line_check_assistant/ or src/",
            )
            self.assertTrue(f.endswith(".py"), f"{f!r} should end with '.py'")


class CheckMustExistTests(unittest.TestCase):
    """`check_must_exist` 在临时目录下的命中/缺失行为。"""

    def _make_root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "line_check_assistant").mkdir()
        return root

    def test_returns_passed_when_pattern_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "src" / "fake.py").write_text(
                "def go():\n    return 'bbfdm.operate'\n",
                encoding="utf-8",
            )
            results = check_must_exist(root)
            bbfdm = next(r for r in results if "bbfdm.operate" in r.name)
            self.assertTrue(bbfdm.passed, bbfdm.detail)
            self.assertIn("fake.py", bbfdm.detail)

    def test_returns_failed_when_pattern_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "src" / "fake.py").write_text(
                "# no relevant code here\n",
                encoding="utf-8",
            )
            results = check_must_exist(root)
            bbfdm = next(r for r in results if "bbfdm.operate" in r.name)
            self.assertFalse(bbfdm.passed)
            self.assertIn("not found", bbfdm.detail)

    def test_handles_missing_directories_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 不创建 src/ / line_check_assistant/
            results = check_must_exist(root)
            # 全部应返回 failed(目录不存在 = 找不到)
            self.assertGreater(len(results), 0)
            for r in results:
                self.assertFalse(r.passed)
                self.assertIn("not found", r.detail)


class CheckMustNotExistTests(unittest.TestCase):
    """`check_must_not_exist` 在临时目录下的命中/缺失行为。"""

    def _make_root(self, tmp: str, include_forbidden_file: bool = True) -> Path:
        root = Path(tmp)
        (root / "src" / "core").mkdir(parents=True)
        if include_forbidden_file:
            (root / "src" / "core" / "tftp_transport.py").write_text(
                "bind = '127.0.0.1'\n",  # safe, no forbidden pattern
                encoding="utf-8",
            )
        return root

    def test_returns_passed_when_pattern_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, include_forbidden_file=True)
            results = check_must_not_exist(root)
            zero = next(r for r in results if "0.0.0.0" in r.name)
            self.assertTrue(zero.passed, zero.detail)

    def test_returns_failed_when_pattern_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, include_forbidden_file=False)
            (root / "src" / "core" / "tftp_transport.py").write_text(
                "# intentional violation\nbind = '0.0.0.0'\n",
                encoding="utf-8",
            )
            results = check_must_not_exist(root)
            zero = next(r for r in results if "0.0.0.0" in r.name)
            self.assertFalse(zero.passed)
            self.assertIn("found in", zero.detail)

    def test_tolerates_missing_limit_files(self):
        """限制文件不存在时,视为「未违反」(passed=True)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 不创建 src/core/tftp_transport.py
            results = check_must_not_exist(root)
            zero = next(r for r in results if "0.0.0.0" in r.name)
            self.assertTrue(zero.passed)

    def test_ignores_pattern_inside_pure_comment_lines(self):
        """禁止模式出现在纯注释行(以 `#` 开头)时,视为「未违反」(passed=True)。

        保护反向语义注释(如「不回退 0.0.0.0」)不会误报。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "core").mkdir(parents=True)
            (root / "src" / "core" / "tftp_transport.py").write_text(
                "# 严禁回退到 0.0.0.0\n"
                "bind = '127.0.0.1'\n",
                encoding="utf-8",
            )
            results = check_must_not_exist(root)
            zero = next(r for r in results if "0.0.0.0" in r.name)
            self.assertTrue(zero.passed, zero.detail)

    def test_still_flags_pattern_on_indented_comment_line(self):
        """缩进的注释行(以 `#` 开头)同样跳过——`lstrip().startswith('#')` 判断。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "core").mkdir(parents=True)
            (root / "src" / "core" / "tftp_transport.py").write_text(
                "    # leading indent + 0.0.0.0\n"
                "bind = '127.0.0.1'\n",
                encoding="utf-8",
            )
            results = check_must_not_exist(root)
            zero = next(r for r in results if "0.0.0.0" in r.name)
            self.assertTrue(zero.passed)


if __name__ == "__main__":
    unittest.main()
"""Windows hook integration tests using temporary repos and fake interpreters.

The fake executable only reports a Python profile and records baseline calls;
no Python installation, dependency download, commit, or real baseline is needed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SOURCE_ROOT.parent
POWERSHELL = shutil.which("powershell.exe")
GIT = shutil.which("git")


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL and GIT,
                     "Windows PowerShell and Git required")
class GitHookEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler_temp = tempfile.TemporaryDirectory(prefix="hook-interpreter-")
        cls.binary = Path(cls.compiler_temp.name) / "fake.exe"
        code = Path(cls.compiler_temp.name) / "fake.cs"
        code.write_text(r'''
using System;
using System.IO;
using System.Reflection;
public class FakePython {
    public static int Main(string[] args) {
        string exe = Assembly.GetExecutingAssembly().Location;
        int first = args.Length > 0 && args[0] == "-3.9" ? 1 : 0;
        if (args.Length > first && args[first] == "-I") {
            File.AppendAllText(exe + ".probes", "probe\n");
            if (File.Exists(exe + ".require-no-install") &&
                (Environment.GetEnvironmentVariable("PYLAUNCHER_ALLOW_INSTALL") != null ||
                 Environment.GetEnvironmentVariable("PYLAUNCHER_ALWAYS_INSTALL") != null ||
                 Environment.GetEnvironmentVariable("PYTHON_MANAGER_AUTOMATIC_INSTALL") != "false")) return 86;
            if (File.Exists(exe + ".probe-exit")) return 9;
            Console.WriteLine(File.ReadAllText(exe + ".profile"));
            return 0;
        }
        File.AppendAllText(exe + ".calls", Environment.CurrentDirectory + "\n" +
                          String.Join("\n", args) + "\nTEMP=" +
                          Environment.GetEnvironmentVariable("TEMP") + "\nTMP=" +
                          Environment.GetEnvironmentVariable("TMP") + "\nTMPDIR=" +
                          Environment.GetEnvironmentVariable("TMPDIR") + "\n");
        Console.WriteLine("FAKE_BASELINE_RESULT");
        return File.Exists(exe + ".exit") ? Int32.Parse(File.ReadAllText(exe + ".exit")) : 0;
    }
}
''', encoding="utf-8")
        compile_script = Path(cls.compiler_temp.name) / "compile.ps1"
        compile_script.write_text(
            "param($Source, $Target)\n$ErrorActionPreference = 'Stop'\n"
            "Add-Type -Path $Source -OutputAssembly $Target -OutputType ConsoleApplication\n",
            encoding="utf-8-sig")
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(compile_script), str(code), str(cls.binary)],
            capture_output=True, timeout=30)
        if result.returncode:
            cls.compiler_temp.cleanup()
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.compiler_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hook-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "中文 repo & spaces"
        self.scripts = self.root / "Cheating_machine_execution_tool/scripts"
        self.scripts.mkdir(parents=True)
        for name in ("git_hook_python.ps1", "run_git_pre_commit.ps1", "install_git_hooks.ps1"):
            shutil.copyfile(SOURCE_ROOT / "scripts" / name, self.scripts / name)
        (self.scripts / "verify_baseline.py").write_text("# fixture only\n", encoding="utf-8")
        (self.root / ".githooks").mkdir()
        shutil.copyfile(REPO_ROOT / ".githooks/pre-commit", self.root / ".githooks/pre-commit")
        self.git("init", "--quiet")
        # Isolate discovery from installed Python/py and the parent's venv/config.
        self.bin_dir = Path(self.temp.name) / "bin"
        self.bin_dir.mkdir()
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.upper() in {"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"} or key.upper().startswith("GIT_"):
                del self.env[key]
        self.env.update(PATH=os.pathsep.join((str(self.bin_dir), str(Path(GIT).parent),
                                             str(Path(POWERSHELL).parent))),
                        LOCALAPPDATA=str(Path(self.temp.name) / "local"),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def git(self, *args):
        # A real Git hook exports repository variables. Never let those direct
        # fixture config writes at the caller's repository instead of this temp.
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("GIT_")}
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        result = subprocess.run([GIT, "-C", str(self.root), *args],
                                env=environment, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.decode("utf-8").strip()

    def fake(self, path, *, version="3.9.10", bits=64, implementation="CPython", target=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.binary, path)
        Path(str(path) + ".profile").write_text(json.dumps(dict(
            executable=str(target or path), version=version, bits=bits,
            implementation=implementation)), encoding="ascii")
        return path

    def powershell(self, script="run_git_pre_commit.ps1", *args):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.scripts / script), *map(str, args)],
            cwd=self.temp.name, env=self.env, capture_output=True, timeout=30)

    def assert_selected(self, python, exit_code=0):
        result = self.powershell()
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        calls = Path(str(python) + ".calls").read_text(encoding="utf-8-sig")
        self.assertIn(str(self.scripts.parent), calls)
        self.assertIn("scripts/verify_baseline.py", calls)
        self.assertEqual(calls.count("scripts/verify_baseline.py"), 1)
        self.assertIn(b"FAKE_BASELINE_RESULT", result.stdout)

    def test_explicit_configuration_precedes_active_environment(self):
        configured = self.fake(self.root / "custom & python/python.exe")
        active = self.fake(self.root / "active/Scripts/python.exe")
        self.env["VIRTUAL_ENV"] = str(active.parent.parent)
        self.git("config", "--local", "linecheck.pythonExecutable", str(configured))
        self.assert_selected(configured)
        self.assertFalse(Path(str(active) + ".probes").exists())

    def test_active_environment_precedes_repository_venv(self):
        active = self.fake(self.root / "active/Scripts/python.exe")
        lower = self.fake(self.root / ".venv/Scripts/python.exe")
        self.env["VIRTUAL_ENV"] = str(active.parent.parent)
        self.assert_selected(active)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_root_venv_precedes_source_venv_without_activation(self):
        root_venv = self.fake(self.root / ".venv/Scripts/python.exe")
        lower = self.fake(self.scripts.parent / ".venv/Scripts/python.exe")
        self.assert_selected(root_venv)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_source_venv_precedes_build_environment(self):
        source_venv = self.fake(self.scripts.parent / ".venv/Scripts/python.exe")
        lower = self.fake(Path(self.env["LOCALAPPDATA"]) /
                          "LineCheckAssistant/build-env-py39/Scripts/python.exe")
        self.assert_selected(source_venv)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_build_environment_precedes_launcher(self):
        build = self.fake(Path(self.env["LOCALAPPDATA"]) /
                          "LineCheckAssistant/build-env-py39/Scripts/python.exe")
        lower = self.fake(self.bin_dir / "py.exe")
        self.assert_selected(build)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_launcher_resolves_actual_interpreter_before_path_python(self):
        target = self.fake(self.root / "launcher target/python.exe")
        self.fake(self.bin_dir / "py.exe", target=target)
        lower = self.fake(self.bin_dir / "python.exe")
        self.assert_selected(target)
        self.assertTrue(Path(str(target) + ".probes").exists())
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_path_python_precedes_python3(self):
        python = self.fake(self.bin_dir / "python.exe")
        lower = self.fake(self.bin_dir / "python3.exe")
        self.assert_selected(python)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_launcher_probe_disables_automatic_installation(self):
        python = self.fake(self.root / "existing/python.exe")
        launcher = self.fake(self.bin_dir / "py.exe", target=python)
        Path(str(launcher) + ".require-no-install").touch()
        Path(str(python) + ".require-no-install").touch()
        self.env.update(PYLAUNCHER_ALLOW_INSTALL="1", PYLAUNCHER_ALWAYS_INSTALL="1",
                        PYTHON_MANAGER_AUTOMATIC_INSTALL="true")
        self.assert_selected(python)

    def test_incompatible_automatic_candidates_are_skipped(self):
        self.fake(self.root / ".venv/Scripts/python.exe", version="3.11.9")
        self.fake(self.scripts.parent / ".venv/Scripts/python.exe", bits=32)
        self.fake(self.bin_dir / "python.exe", implementation="PyPy")
        python = self.fake(self.bin_dir / "python3.exe")
        self.assert_selected(python)

    def test_broken_automatic_probe_is_skipped(self):
        broken = self.fake(self.bin_dir / "python.exe")
        Path(str(broken) + ".probe-exit").write_text("9")
        self.assert_selected(self.fake(self.bin_dir / "python3.exe"))

    def test_explicit_invalid_paths_versions_and_bits_fail_without_fallback(self):
        fallback = self.fake(self.bin_dir / "python.exe")
        cases = [self.root / "missing.exe",
                 self.fake(self.root / "wrong.exe", version="3.9.13"),
                 self.fake(self.root / "32bit.exe", bits=32),
                 self.fake(self.root / "pypy.exe", implementation="PyPy")]
        for candidate in cases:
            with self.subTest(candidate=candidate.name):
                self.git("config", "--local", "linecheck.pythonExecutable", str(candidate))
                result = self.powershell()
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"Invalid linecheck.pythonExecutable", result.stderr)
                self.assertIn(b"--unset linecheck.pythonExecutable", result.stderr)
                self.assertFalse(Path(str(fallback) + ".probes").exists())

    def test_store_placeholder_is_never_executed(self):
        store = self.fake(self.root / "Microsoft/WindowsApps/python.exe")
        self.env["PATH"] = str(store.parent) + os.pathsep + self.env["PATH"]
        self.assert_selected(self.fake(self.bin_dir / "python3.exe"))
        self.assertFalse(Path(str(store) + ".probes").exists())

    def test_no_interpreter_has_actionable_error(self):
        result = self.powershell()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"No usable CPython 3.9.10 x64", result.stderr)
        self.assertIn(b"-PythonExecutable", result.stderr)

    def test_baseline_failure_propagates_without_retrying_other_python(self):
        python = self.fake(self.root / ".venv/Scripts/python.exe")
        Path(str(python) + ".exit").write_text("37")
        lower = self.fake(self.bin_dir / "python.exe")
        self.assert_selected(python, exit_code=37)
        self.assertFalse(Path(str(lower) + ".probes").exists())

    def test_temporary_directory_aliases_are_normalized_for_baseline_only(self):
        python = self.fake(self.bin_dir / "python.exe")
        original = self.env["TEMP"]
        self.env["TMP"] = original
        self.env["TMPDIR"] = original
        self.assert_selected(python)
        calls = Path(str(python) + ".calls").read_text(encoding="utf-8-sig")
        resolved = str(Path(original).resolve())
        self.assertIn("TEMP=" + resolved + "\n", calls)
        self.assertIn("TMP=" + resolved + "\n", calls)
        self.assertIn("TMPDIR=" + resolved + "\n", calls)
        self.assertEqual(self.env["TEMP"], original)

    def test_installer_validates_and_saves_only_local_configuration(self):
        python = self.fake(self.root / "local env/python.exe")
        result = self.powershell("install_git_hooks.ps1", "-PythonExecutable", python)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("config", "--local", "--get", "linecheck.pythonExecutable"), str(python))
        self.assertEqual(self.git("config", "--local", "--get", "core.hooksPath"), ".githooks")
        self.assertFalse(Path(str(python) + ".calls").exists())

    def test_installer_without_argument_preserves_configuration(self):
        self.git("config", "--local", "linecheck.pythonExecutable", "original.exe")
        result = self.powershell("install_git_hooks.ps1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("config", "--local", "--get", "linecheck.pythonExecutable"), "original.exe")

    def test_invalid_install_does_not_overwrite_configuration(self):
        self.git("config", "--local", "linecheck.pythonExecutable", "original.exe")
        result = self.powershell("install_git_hooks.ps1", "-PythonExecutable", self.root / "missing.exe")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("config", "--local", "--get", "linecheck.pythonExecutable"), "original.exe")

    def test_unset_restores_automatic_discovery(self):
        self.git("config", "--local", "linecheck.pythonExecutable", "missing.exe")
        self.git("config", "--local", "--unset", "linecheck.pythonExecutable")
        self.assert_selected(self.fake(self.bin_dir / "python.exe"))

    def test_fixture_git_commands_ignore_parent_repository_variables(self):
        with patch.dict(os.environ, GIT_DIR=str(self.root / "foreign.git"),
                        GIT_WORK_TREE=str(self.root / "foreign-worktree"),
                        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="linecheck.pythonExecutable",
                        GIT_CONFIG_VALUE_0="foreign.exe"):
            self.git("config", "--local", "linecheck.pythonExecutable", "fixture.exe")
            self.assertEqual(self.git("config", "--local", "--get", "linecheck.pythonExecutable"), "fixture.exe")

    def test_real_shell_hook_preserves_failure_code_and_unicode_path(self):
        shell = next((parent / "bin/sh.exe" for parent in Path(GIT).resolve().parents
                      if (parent / "bin/sh.exe").exists()), None)
        if shell is None:
            self.skipTest("Git for Windows shell unavailable")
        python = self.fake(self.root / "hook env/python.exe")
        Path(str(python) + ".exit").write_text("23")
        self.git("config", "--local", "linecheck.pythonExecutable", str(python))
        result = subprocess.run([str(shell), ".githooks/pre-commit"],
                                cwd=self.root, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(Path(str(python) + ".calls").exists())


if __name__ == "__main__":
    unittest.main()

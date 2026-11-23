"""Exercise the Windows process sampler against a disposable local sleeper."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("watch_process.ps1")


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell sampler")
class SamplerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="dutpilot-sampler-")
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "samples.jsonl"
        self.executable = Path(sys._base_executable)
        self.target = self.start([str(self.executable), "-c", "import time; time.sleep(40)"])

    def start(self, command):
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        self.addCleanup(cleanup)
        return process

    def sample(self, seconds, *arguments):
        return self.start(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                           "-TargetProcessId", str(self.target.pid), "-OutputPath", str(self.path),
                           "-DurationSeconds", str(seconds), "-IntervalSeconds", "1", *arguments])

    def candidate(self, executable):
        archive = self.path.with_name("DUTPilot_portable.zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("DUTPilot_portable/DUTPilot.exe", executable)
        digest = sha256(archive.read_bytes()).hexdigest()
        Path(str(archive) + ".sha256.txt").write_text(f"{digest} *{archive.name}\n", encoding="ascii")
        return archive, digest

    def sample_candidate(self, archive):
        return self.sample(1, "-CandidateZip", str(archive), "-ProjectId", "field-project", "-RunId", "field-run")

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def await_first(self, watcher):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.path.exists() and b'"sample"' in self.path.read_bytes():
                return
            self.assertIsNone(watcher.poll())
            time.sleep(.05)
        self.fail("No process sample arrived")

    def test_window_and_existing_file_protection(self):
        self.assertEqual(self.sample(2).wait(timeout=10), 0)
        rows = self.records()
        self.assertEqual(rows[0]["event"], "start")
        self.assertTrue(rows[0]["start_utc"])
        self.assertTrue(all((r["pid"], r["start_utc"]) == (self.target.pid, rows[0]["start_utc"]) for r in rows))
        samples = rows[1:-1]
        self.assertGreaterEqual(len(samples), 2)
        self.assertIsNone(samples[0]["cpu_pct_one_core"])
        for row in samples:
            self.assertEqual(row["event"], "sample")
            self.assertTrue(row["threads"] > 0 and row["working_set_bytes"] > 0 and row["private_bytes"] > 0)
        for prev, current in zip(samples, samples[1:]):
            self.assertGreater(current["elapsed_s"], prev["elapsed_s"])
            self.assertGreaterEqual(current["cpu_total_s"], prev["cpu_total_s"])
            self.assertEqual(current["gap"], current["interval_actual_s"] > 1.5)
            self.assertEqual(current["cpu_pct_one_core"] is None, current["gap"])
        self.assertEqual(rows[-1]["reason"], "observation_window_ended")
        self.assertGreaterEqual(rows[-1]["elapsed_s"], 2)
        original = self.path.read_bytes()
        self.assertNotEqual(self.sample(2).wait(timeout=10), 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIsNone(self.target.poll())

    def test_stop_leaves_target_alive(self):
        watcher = self.sample(30)
        self.await_first(watcher)
        Path(str(self.path) + ".stop").touch()
        self.assertEqual(watcher.wait(timeout=5), 0)
        self.assertEqual(self.records()[-1]["reason"], "operator_stop")
        self.assertIsNone(self.target.poll())

    def test_target_exit_ends_observation(self):
        watcher = self.sample(30)
        self.await_first(watcher)
        self.target.terminate()
        self.target.wait(timeout=5)
        self.assertNotEqual(watcher.wait(timeout=5), 0)
        self.assertEqual(self.records()[-1]["reason"], "target_exited")

    def test_candidate_records_verified_archive_and_process_image(self):
        image = self.executable.read_bytes()
        archive, digest = self.candidate(image)
        self.assertEqual(self.sample_candidate(archive).wait(timeout=10), 0)
        header = self.records()[0]
        self.assertEqual(header["candidate_zip_sha256"], digest)
        self.assertEqual(header["process_exe_sha256"], sha256(image).hexdigest())
        self.assertEqual((header["project_id"], header["run_id"]), ("field-project", "field-run"))
        self.path = self.path.with_name("pinned.jsonl")
        self.assertEqual(self.sample(1, "-ExpectedStartUtc", header["start_utc"]).wait(timeout=10), 0)

    def test_rejects_unmatched_zip_or_executable_without_creating_trace(self):
        archive, _ = self.candidate(b"different executable")
        self.assertNotEqual(self.sample_candidate(archive).wait(timeout=10), 0)
        self.assertFalse(self.path.exists())
        archive, _ = self.candidate(self.executable.read_bytes())
        Path(str(archive) + ".sha256.txt").write_text("0" * 64, encoding="ascii")
        self.assertNotEqual(self.sample_candidate(archive).wait(timeout=10), 0)
        self.assertFalse(self.path.exists())

    def test_rejects_stale_process_selection_without_creating_trace(self):
        watcher = self.sample(1, "-ExpectedStartUtc", "2000-01-01T00:00:00.0000000Z")
        self.assertNotEqual(watcher.wait(timeout=10), 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()

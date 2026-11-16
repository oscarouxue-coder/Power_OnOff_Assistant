from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_capability_coverage.py"
spec = importlib.util.spec_from_file_location("capability_coverage_check", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


class CapabilityCoverageTests(unittest.TestCase):
    def test_current_manifest_and_business_entries_are_consistent(self):
        self.assertEqual([], coverage.check(SCRIPT.parents[1]))

    def test_new_widget_and_changed_callback_are_detected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/ui").mkdir(parents=True)
            (root / "line_check_assistant").mkdir()
            for name in ("app.py", "pipeline_window.py"):
                (root / "line_check_assistant" / name).write_text("", encoding="utf-8")
            path = root / "src/ui/fake.py"
            path.write_text("class View:\n def run(self): return 1\n def build(self): Button(command=self.run)\n", encoding="utf-8")
            before = coverage.gui_actions(root)
            path.write_text(path.read_text().replace("return 1", "return 2"), encoding="utf-8")
            self.assertNotEqual(before, coverage.gui_actions(root))
            path.write_text(path.read_text() + "\ndef new(): Button(command=other)\n", encoding="utf-8")
            self.assertEqual(2, len(coverage.gui_actions(root)))

    def test_pending_businesses_remain_visible_and_manual_actions_are_explicit(self):
        from src.services.capability_catalog import business_catalog
        rows = {row["feature_id"]: row for row in business_catalog()}
        self.assertEqual("connected", rows["onu.register"]["status"])
        self.assertEqual("connected", rows["channels.configure"]["status"])
        self.assertEqual("connected", rows["firmware.settings"]["status"])
        self.assertEqual("pending", rows["serial.send"]["status"])
        self.assertEqual("connected", rows["aging.start"]["status"])
        self.assertEqual("manual_control", rows["ai.permissions"]["status"])
        self.assertTrue(all(row["reason"] for row in rows.values()))

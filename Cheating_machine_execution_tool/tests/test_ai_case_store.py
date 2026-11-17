import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import uuid
import zipfile

from src.services.ai_case_store import (SharedCaseStore, SNAPSHOT_NAME, export_snapshot,
                                        open_shared_cases, validate_snapshot)
from src.services.ai_store import DiagnosticStore


VALUES = ("report-a", "WiFi断线", "驱动异常", "更新驱动", "双频复测通过", "Win11")


class SharedCasesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = []

    def shared(self):
        store = SharedCaseStore(self.root / "case_library", self.logs.append)
        self.addCleanup(store.close)
        return store

    def old(self, relative="ai"):
        store = DiagnosticStore(self.root / relative)
        self.addCleanup(store.close)
        return store

    def test_two_project_stores_share_cases_but_not_settings_reports_or_chats(self):
        first = DiagnosticStore(self.root / "project-a", case_store=self.shared())
        second = DiagnosticStore(self.root / "project-b", case_store=self.shared())
        # DiagnosticStore owns its injected case connection; close only the runtime DB here.
        self.addCleanup(first.db.close)
        self.addCleanup(second.db.close)
        identifier = first.confirm_case(*VALUES)
        first.set_setting("chat_permission_mode", "FULL")
        first.save_report("report-a", {"text": "private-report"})
        first.create_chat({"id": "chat-a", "created": "2026", "title": "private-chat"})
        self.assertEqual(second.cases("WiFi")[0]["id"], identifier)
        self.assertEqual(second.setting("chat_permission_mode", "AUTO"), "AUTO")
        self.assertEqual(second.reports(), [])
        self.assertEqual(second.chats(), [])
        second.update_case_state(identifier)
        self.assertEqual(first.cases(), [])

    def test_migration_preserves_all_revisions_inactive_and_original_databases(self):
        old = self.old()
        identifier = old.confirm_case(*VALUES)
        old.confirm_case(*VALUES[:2], "服务异常", *VALUES[3:], case_id=identifier)
        old.update_case_state(identifier)
        project = self.old("projects/one")
        project.confirm_case(*VALUES)  # same local ID and text is a distinct source record
        paths = [s.directory / "diagnostics.sqlite3" for s in (old, project)]
        before = [p.read_bytes() for p in paths]
        store = self.shared()
        self.assertEqual(store.migrate(paths), 2)
        self.assertEqual(store.migrate(paths), 0)
        rows = store.snapshot()["cases"]
        self.assertEqual(len(rows), 2)
        inactive = next(r for r in rows if not r["active"])
        self.assertEqual(len(inactive["revisions"]), 2)
        self.assertEqual(inactive["cause"], "服务异常")
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertEqual(len(store.cases()), 1)

    def test_changed_legacy_content_does_not_overwrite_local_or_resurrect_deleted(self):
        old = self.old()
        identifier = old.confirm_case(*VALUES)
        path = old.directory / "diagnostics.sqlite3"
        store = self.shared()
        store.migrate([path])
        row = store.cases()[0]
        store.confirm_case(*VALUES[:2], "本地核实原因", *VALUES[3:], case_id=row["id"])
        old.confirm_case(*VALUES[:2], "旧版再次修订", *VALUES[3:], case_id=identifier)
        store.migrate([path])
        self.assertEqual(store.cases()[0]["cause"], "本地核实原因")
        store.update_case_state(row["id"], delete=True)
        store.migrate([path])
        self.assertEqual(store.cases(include_inactive=True), [])
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM case_revisions").fetchone()[0], 0)

    def test_package_import_only_adds_new_uuids_and_preserves_local_states(self):
        source = SharedCaseStore(self.root / "source")
        self.addCleanup(source.close)
        for i in range(3):
            source.confirm_case(VALUES[0], VALUES[1] + str(i), *VALUES[2:])
        payload = source.snapshot()
        store = self.shared()
        self.assertEqual(store.import_snapshot(payload), 3)
        rows = store.cases()
        store.confirm_case(*VALUES[:2], "本地修订", *VALUES[3:], case_id=rows[0]["id"])
        store.update_case_state(rows[1]["id"])
        store.update_case_state(rows[2]["id"], delete=True)
        source.confirm_case(*VALUES)
        self.assertEqual(store.import_snapshot(source.snapshot()), 1)
        remaining = {r["uuid"]: r for r in store.cases(include_inactive=True)}
        self.assertEqual(remaining[rows[0]["uuid"]]["cause"], "本地修订")
        self.assertEqual(remaining[rows[1]["uuid"]]["active"], 0)
        self.assertNotIn(rows[2]["uuid"], remaining)
        reopened = self.shared()
        self.assertEqual(reopened.import_snapshot(payload), 0)

    def test_validation_failure_does_not_partially_import(self):
        source = self.shared()
        source.confirm_case(*VALUES)
        payload = source.snapshot()
        other = copy.deepcopy(payload["cases"][0])
        other.update(uuid=str(uuid.uuid4()), active=2)
        payload["cases"].append(other)
        destination = SharedCaseStore(self.root / "destination")
        self.addCleanup(destination.close)
        with self.assertRaises(ValueError):
            destination.import_snapshot(payload)
        self.assertEqual(destination.cases(), [])

    def test_sql_failure_rolls_back_cases_and_revisions(self):
        source = self.shared()
        source.confirm_case(*VALUES)
        destination = SharedCaseStore(self.root / "destination", self.logs.append)
        self.addCleanup(destination.close)
        destination.db.execute("CREATE TRIGGER fail_revision BEFORE INSERT ON case_revisions "
                               "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        destination.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            destination.import_snapshot(source.snapshot())
        self.assertEqual(destination.cases(), [])
        self.assertTrue(any("回退" in line for line in self.logs))

    def test_stale_edit_toggle_delete_and_missing_record_are_rejected(self):
        first, second = self.shared(), self.shared()
        identifier = first.confirm_case(*VALUES)
        version = first.cases()[0]["version"]
        second.confirm_case(*VALUES[:2], "另一个项目修改", *VALUES[3:], case_id=identifier, expected_version=version)
        for operation in (lambda: first.confirm_case(*VALUES, case_id=identifier, expected_version=version),
                          lambda: first.update_case_state(identifier, expected_version=version),
                          lambda: first.update_case_state(identifier, delete=True, expected_version=version)):
            with self.assertRaisesRegex(ValueError, "刷新"):
                operation()
        second.update_case_state(identifier, delete=True)
        with self.assertRaisesRegex(ValueError, "删除"):
            first.confirm_case(*VALUES, case_id=identifier)

    def test_concurrent_writers_only_one_can_save_the_same_version(self):
        first, second = self.shared(), self.shared()
        identifier = first.confirm_case(*VALUES)
        barrier = threading.Barrier(2)
        def save(store):
            barrier.wait(timeout=5)
            try:
                store.confirm_case(*VALUES, case_id=identifier, expected_version=1)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(save, (first, second))), [False, True])
        self.assertEqual(len(first.snapshot()["cases"][0]["revisions"]), 2)

    def test_unrelated_query_and_inactive_cases_are_excluded(self):
        store = self.shared()
        identifier = store.confirm_case(*VALUES)
        self.assertEqual(store.cases("watchdog"), [])
        self.assertEqual(len(store.cases("WiFi")), 1)
        store.update_case_state(identifier)
        self.assertEqual(store.cases("WiFi"), [])

    def test_second_process_sees_committed_state_and_updates_same_library(self):
        store = self.shared()
        store.confirm_case(*VALUES)
        code = ("from src.services.ai_case_store import SharedCaseStore; import sys; "
                "s=SharedCaseStore(sys.argv[1]); r=s.cases()[0]; "
                "s.update_case_state(r['id'],expected_version=r['version']); s.close()")
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(store.directory)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(store.cases(), [])
        self.assertEqual(store.cases(include_inactive=True)[0]["version"], 2)

    def test_default_diagnostic_service_uses_user_shared_library(self):
        from src.services.ai_diagnostic_service import AiDiagnosticService
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            diagnostic = AiDiagnosticService(self.logs.append, Mock(), Mock(), Mock())
            try:
                diagnostic.confirm_case(*VALUES)
                self.assertEqual(diagnostic.store.case_store.directory,
                                 self.root / "LineCheckAssistant" / "case_library")
            finally:
                diagnostic.begin_close()
                for worker in (diagnostic.event_thread, diagnostic.worker_thread):
                    worker.join(4)
                    self.assertFalse(worker.is_alive())
                diagnostic.store.close()

    def test_source_and_frozen_initialization_import_into_same_user_library(self):
        self.old().confirm_case(*VALUES)
        source = open_shared_cases(root=self.root, emit=self.logs.append)
        self.addCleanup(source.close)
        snapshot = self.root / SNAPSHOT_NAME
        snapshot.write_text(json.dumps(source.snapshot()), encoding="utf-8")
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", str(self.root), create=True):
            frozen = open_shared_cases(root=self.root, emit=self.logs.append)
        self.addCleanup(frozen.close)
        self.assertEqual(source.cases(), frozen.cases())
        self.assertEqual(len(frozen.cases()), 1)

    def test_bad_seed_keeps_existing_data_and_reports_failure(self):
        store = self.shared()
        store.confirm_case(*VALUES)
        seed = self.root / SNAPSHOT_NAME
        seed.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            open_shared_cases(root=self.root, seed=seed, emit=self.logs.append)
        self.assertEqual(len(store.cases()), 1)
        self.assertTrue(any("初始化失败" in line for line in self.logs))

    def test_corrupt_shared_database_reports_initialization_failure(self):
        directory = self.root / "case_library"
        directory.mkdir()
        path = directory / "cases.sqlite3"
        path.write_bytes(b"corrupt")
        with self.assertRaises(sqlite3.DatabaseError):
            open_shared_cases(root=self.root, emit=self.logs.append)
        self.assertTrue(any("初始化失败" in line for line in self.logs))
        self.assertEqual(path.read_bytes(), b"corrupt")

    def test_export_is_case_only_repeatable_and_includes_inactive_history(self):
        old = self.old()
        identifier = old.confirm_case(*VALUES)
        old.update_case_state(identifier)
        old.set_setting("secret", "private-config")
        old.save_report("private", {"text": "private-report"})
        output = self.root / "output" / SNAPSHOT_NAME
        first = export_snapshot(output, root=self.root, emit=self.logs.append)
        data = output.read_bytes()
        self.assertEqual(first["cases"][0]["active"], 0)
        self.assertNotIn(b"private-", data)
        self.assertNotIn(str(self.root), data.decode("utf-8"))
        self.assertEqual(export_snapshot(output, root=self.root, emit=self.logs.append), first)
        self.assertEqual(output.read_bytes(), data)
        self.assertTrue(any(hashlib.sha256(data).hexdigest() in line for line in self.logs))

    def test_empty_export_is_valid_and_corrupt_source_does_not_create_output(self):
        output = self.root / SNAPSHOT_NAME
        self.assertEqual(export_snapshot(output, root=self.root, emit=self.logs.append)["cases"], [])
        previous = output.read_bytes()
        path = self.root / "ai" / "diagnostics.sqlite3"
        path.parent.mkdir()
        path.write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            export_snapshot(output, root=self.root, emit=self.logs.append)
        self.assertEqual(output.read_bytes(), previous)

    def test_build_export_cli_works_in_isolated_python_without_touching_real_user(self):
        source = DiagnosticStore(self.root / "user" / "LineCheckAssistant" / "ai")
        try:
            source.confirm_case(*VALUES)
        finally:
            source.close()
        output = self.root / "snapshot" / SNAPSHOT_NAME
        script = Path(__file__).resolve().parents[1] / "scripts" / "export_ai_cases.py"
        result = subprocess.run([sys.executable, "-I", "-X", "utf8", str(script), "--output", str(output)],
                                env=dict(os.environ, LOCALAPPDATA=str(self.root / "user")),
                                capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(validate_snapshot(json.loads(output.read_text(encoding="utf-8")))["cases"]), 1)
        self.assertIn("快照导出成功", result.stdout)
        self.assertNotIn(VALUES[1], result.stdout)

    def test_snapshot_rejects_duplicates_invalid_uuid_and_invalid_history(self):
        store = self.shared()
        store.confirm_case(*VALUES)
        valid = store.snapshot()
        for change in (lambda p: p.update(schema_version=2),
                       lambda p: p.update(schema_version=True),
                       lambda p: p["cases"].append(p["cases"][0]),
                       lambda p: p["cases"][0].update(uuid="bad"),
                       lambda p: p["cases"][0].pop("report_id"),
                       lambda p: p["cases"][0].update(revisions=[]),
                       lambda p: p["cases"][0]["revisions"][0].update(payload=[])):
            payload = copy.deepcopy(valid)
            change(payload)
            with self.assertRaises(ValueError):
                validate_snapshot(payload)


class CasePackageTests(unittest.TestCase):
    def test_verifier_compares_both_archives_to_same_snapshot_and_reports_counts(self):
        from scripts import verify_slim_package as verifier
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SharedCaseStore(root / "store")
            try:
                store.confirm_case(*VALUES)
                data = json.dumps(store.snapshot()).encode("utf-8")
            finally:
                store.close()
            snapshot = root / SNAPSHOT_NAME
            snapshot.write_bytes(data)
            bundle = root / "portable.zip"
            def write_bundle(content):
                with zipfile.ZipFile(bundle, "w") as archive:
                    archive.writestr("DUTPilot_portable/" + SNAPSHOT_NAME, content)
            write_bundle(data)
            reader = Mock()
            reader.extract.return_value = data
            with patch.object(verifier, "CArchiveReader", return_value=reader):
                report = verifier.inspect_case_snapshot(root / "unused.exe", bundle, snapshot)
                self.assertEqual((report["case_count"], report["case_revision_count"]), (1, 1))
                self.assertEqual(report["case_snapshot_sha256"], hashlib.sha256(data).hexdigest())
                reader.extract.return_value = b"wrong exe snapshot"
                with self.assertRaisesRegex(ValueError, "Embedded case"):
                    verifier.inspect_case_snapshot(root / "unused.exe", bundle, snapshot)
                reader.extract.return_value = data
                write_bundle(b"wrong zip snapshot")
                with self.assertRaisesRegex(ValueError, "Portable case"):
                    verifier.inspect_case_snapshot(root / "unused.exe", bundle, snapshot)


if __name__ == "__main__":
    unittest.main()

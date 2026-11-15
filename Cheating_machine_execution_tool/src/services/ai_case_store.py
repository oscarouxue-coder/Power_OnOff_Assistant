"""本机用户共用人工案例；旧库只读迁移，发布快照仅补充新 UUID。"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

from src.services.ai_evidence_analysis import match_score, query_terms


SNAPSHOT_NAME = "CONFIRMED_CASES.json"
FIELDS = ("report_id", "title", "cause", "solution", "verification", "scope")


def user_data_root():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LineCheckAssistant"


def legacy_case_sources(root):
    root = Path(root)
    return [root / "ai" / "diagnostics.sqlite3"] + sorted((root / "projects").glob("*/diagnostics.sqlite3"))


def validate_snapshot(payload):
    """先完整校验再导入，拒绝部分成功及重复 UUID。"""
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1 or not isinstance(payload.get("cases"), list)):
        raise ValueError("案例快照格式或版本不支持")
    seen = set()
    for row in payload["cases"]:
        if not isinstance(row, dict):
            raise ValueError("案例快照记录无效")
        try:
            identifier = str(uuid.UUID(row["uuid"]))
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError("案例 UUID 无效") from None
        if identifier != row["uuid"] or identifier in seen:
            raise ValueError("案例 UUID 重复或不规范")
        seen.add(identifier)
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in FIELDS[1:]):
            raise ValueError("案例内容不完整")
        if "report_id" not in row or (row["report_id"] is not None and not isinstance(row["report_id"], str)):
            raise ValueError("案例来源无效")
        if type(row.get("active")) is not int or row["active"] not in (0, 1):
            raise ValueError("案例启用状态无效")
        revisions = row.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            raise ValueError("案例修订历史缺失")
        for revision in revisions:
            if not isinstance(revision, dict) or not isinstance(revision.get("created"), str):
                raise ValueError("案例修订时间无效")
            values = revision.get("payload")
            if (not isinstance(values, list) or len(values) != len(FIELDS)
                    or (values[0] is not None and not isinstance(values[0], str))
                    or any(not isinstance(v, str) for v in values[1:])):
                raise ValueError("案例修订内容无效")
    return payload


class SharedCaseStore:
    def __init__(self, directory, emit=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.emit = emit or (lambda _line: None)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.directory / "cases.sqlite3"), timeout=5, check_same_thread=False)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS cases(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE NOT NULL,
                    report_id TEXT, title TEXT, cause TEXT, solution TEXT, verification TEXT,
                    scope TEXT, active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS case_revisions(
                    id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, created TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS revisions_case ON case_revisions(case_id,id);
                CREATE TABLE IF NOT EXISTS deleted_cases(uuid TEXT PRIMARY KEY);
            ''')
            self.db.commit()
        except Exception:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def _check_version(self, case_id, expected_version):
        row = self.db.execute("SELECT uuid,version FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None or (expected_version is not None and row[1] != expected_version):
            raise ValueError("案例已被其它项目修改或删除，请刷新案例列表后重试")
        return row[0]

    def confirm_case(self, report_id, title, cause, solution, verification, scope, case_id=None, expected_version=None):
        values = (report_id, title, cause, solution, verification, scope)
        if any(not isinstance(v, str) or not v.strip() for v in values[1:]):
            raise ValueError("确认案例需填写标题、实际原因、处理方法、复测结果和适用范围")
        with self.transaction():
            if case_id is None:
                cursor = self.db.execute("INSERT INTO cases(uuid,report_id,title,cause,solution,verification,scope) "
                                         "VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()),) + values)
                case_id = cursor.lastrowid
            else:
                self._check_version(case_id, expected_version)
                self.db.execute("UPDATE cases SET report_id=?,title=?,cause=?,solution=?,verification=?,scope=?,"
                                "version=version+1 WHERE id=?", values + (case_id,))
            self.db.execute("INSERT INTO case_revisions(case_id,created,payload) VALUES(?,?,?)",
                            (case_id, datetime.now().isoformat(), json.dumps(values, ensure_ascii=False)))
        return case_id

    def cases(self, query="", include_inactive=False):
        with self.lock:
            cursor = self.db.execute("SELECT * FROM cases" + ("" if include_inactive else " WHERE active=1") + " ORDER BY id DESC")
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor]
        if not query:
            return rows
        terms = query_terms(query)
        ranked = [(match_score(" ".join(str(row[k] or "") for k in FIELDS[1:]), terms), row) for row in rows]
        return [row for score, row in sorted(ranked, key=lambda item: item[0], reverse=True) if score][:5]

    def update_case_state(self, case_id, delete=False, expected_version=None):
        with self.transaction():
            identifier = self._check_version(case_id, expected_version)
            if delete:
                self.db.execute("INSERT OR IGNORE INTO deleted_cases VALUES(?)", (identifier,))
                self.db.execute("DELETE FROM case_revisions WHERE case_id=?", (case_id,))
                self.db.execute("DELETE FROM cases WHERE id=?", (case_id,))
            else:
                self.db.execute("UPDATE cases SET active=1-active,version=version+1 WHERE id=?", (case_id,))

    def import_snapshot(self, payload, source="发布包"):
        added = 0
        try:
            validate_snapshot(payload)
            with self.transaction():
                for row in payload["cases"]:
                    identifier = row["uuid"]
                    if (self.db.execute("SELECT 1 FROM cases WHERE uuid=?", (identifier,)).fetchone()
                            or self.db.execute("SELECT 1 FROM deleted_cases WHERE uuid=?", (identifier,)).fetchone()):
                        continue
                    cursor = self.db.execute("INSERT INTO cases(uuid,report_id,title,cause,solution,verification,scope,active) "
                                             "VALUES(?,?,?,?,?,?,?,?)", (identifier,) + tuple(row[k] for k in FIELDS) + (row["active"],))
                    self.db.executemany("INSERT INTO case_revisions(case_id,created,payload) VALUES(?,?,?)",
                        [(cursor.lastrowid, r["created"], json.dumps(r["payload"], ensure_ascii=False)) for r in row["revisions"]])
                    added += 1
        except Exception:
            self.emit(f"[AI案例] {source}导入失败，事务已回退")
            raise
        self.emit(f"[AI案例] {source}导入完成：新增{added}，跳过{len(payload['cases']) - added}")
        return added

    def migrate(self, paths):
        self.emit("[AI案例] 开始汇集旧库及项目库中的人工确认案例")
        total = 0
        for path in paths:
            path = Path(path)
            if not path.is_file():
                continue
            db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                db.execute("BEGIN")
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone():
                    continue
                columns = ",".join(("id",) + FIELDS + ("active",))
                rows = []
                source_key = os.path.normcase(str(path.resolve()))
                for raw in db.execute("SELECT " + columns + " FROM cases ORDER BY id"):
                    old_id, *values = raw
                    row = dict(zip(FIELDS + ("active",), values))
                    row["uuid"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "linecheck:legacy:" + source_key + ":" + str(old_id)))
                    row["revisions"] = [{"created": created, "payload": json.loads(payload)} for created, payload in
                        db.execute("SELECT created,payload FROM case_revisions WHERE case_id=? ORDER BY id", (old_id,))]
                    if not row["revisions"]:
                        row["revisions"] = [{"created": "", "payload": list(values[:-1])}]
                    rows.append(row)
                total += self.import_snapshot({"schema_version": 1, "cases": rows}, "旧库")
            finally:
                db.close()
        self.emit(f"[AI案例] 旧库汇集成功：新增{total}")
        return total

    def snapshot(self):
        with self.lock, self.db:
            self.db.execute("BEGIN")
            rows = self.cases(include_inactive=True)
            for row in rows:
                row["revisions"] = [{"created": r[0], "payload": json.loads(r[1])} for r in self.db.execute(
                    "SELECT created,payload FROM case_revisions WHERE case_id=? ORDER BY id", (row.pop("id"),))]
                row.pop("version")
            rows.sort(key=lambda row: row["uuid"])
        return validate_snapshot({"schema_version": 1, "cases": rows})

    def close(self):
        with self.lock:
            self.db.close()


def open_shared_cases(emit=None, root=None, seed=None):
    root = Path(root) if root is not None else user_data_root()
    logger = emit or (lambda _line: None)
    store = None
    try:
        store = SharedCaseStore(root / "case_library", logger)
        store.migrate(legacy_case_sources(root))
        if seed is None and getattr(sys, "frozen", False):
            seed = Path(sys._MEIPASS) / SNAPSHOT_NAME
        if seed is not None:
            store.emit("[AI案例] 开始导入随包案例快照")
            store.import_snapshot(json.loads(Path(seed).read_text(encoding="utf-8")))
        return store
    except Exception:
        logger("[AI案例] 共用库初始化失败，请检查案例库及快照；未回退至项目案例库")
        if store is not None:
            store.close()
        raise


def export_snapshot(destination, root=None, emit=print):
    store = open_shared_cases(emit=emit, root=root)
    try:
        payload = store.snapshot()
    finally:
        store.close()
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    emit(f"[AI案例] 快照导出成功：案例{len(payload['cases'])}，修订{sum(len(r['revisions']) for r in payload['cases'])}，"
         f"SHA256={hashlib.sha256(data).hexdigest()}")
    return payload

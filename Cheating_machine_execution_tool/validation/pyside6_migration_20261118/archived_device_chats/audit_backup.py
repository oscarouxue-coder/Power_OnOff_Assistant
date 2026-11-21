"""Count archived conversation shapes without exporting prompts or target identities."""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tempfile
import zipfile

STAGES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGES.parents[1]))
from src.models.ai_session_scope import session_scope, source_identity
from src.services.qt_ai_chat import _local_chat_mode


def count(archive):
    counts = Counter()
    with zipfile.ZipFile(archive) as zipped, tempfile.TemporaryDirectory(prefix='dutpilot-chat-audit-') as scratch:
        members = set(zipped.namelist())
        for index, member in enumerate(sorted(members)):
            if PurePosixPath(member).name != 'diagnostics.sqlite3':
                continue
            counts['databases'] += 1
            local = Path(scratch) / f'copy-{index}.sqlite3'
            for suffix in ('', '-wal', '-shm', '-journal'):
                if member + suffix in members:
                    Path(str(local) + suffix).write_bytes(zipped.read(member + suffix))
            with closing(sqlite3.connect(local.as_uri() + '?mode=ro', uri=True)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_sessions'").fetchone():
                    continue
                for identifier, payload in db.execute('SELECT id,payload FROM chat_sessions'):
                    counts['sessions'] += 1
                    row = json.loads(payload)
                    if session_scope(row) != 'device' or not row.get('target'):
                        continue
                    if row.get('batch_parent') or row.get('capability_business_batch') or source_identity(row.get('source')) != source_identity(None):
                        continue
                    counts['local_device_sessions'] += 1
                    if row.get('source_report_id'):
                        counts['report_origin'] += 1
                        continue
                    counts['without_report'] += 1
                    mode = _local_chat_mode(row, 'manual')
                    if mode == 'archived':
                        counts['qt_archived_at_manual_start'] += 1
                    elif not mode:
                        counts['qt_history_only_at_manual_start'] += 1
                    if row.get('run_id') not in ('manual', '', None):
                        counts['without_report_named_run'] += 1
                        counts['retained_evidence_rows'] += db.execute('SELECT count(*) FROM chat_evidence WHERE session_id=?',(identifier,)).fetchone()[0]
    return dict(counts)


if __name__ == '__main__':
    receipt = json.loads((STAGES/'backup_receipt.json').read_text('utf-8-sig'))
    archive = Path(receipt['directory'])/'data.zip'
    with archive.open('rb') as source:
        checksum = hashlib.sha256()
        for block in iter(lambda: source.read(1024*1024), b''):
            checksum.update(block)
    assert checksum.hexdigest() == receipt['data_zip_sha256']
    print(json.dumps(dict(archive_sha256=checksum.hexdigest(), counts=count(archive)),indent=2))

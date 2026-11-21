"""Select genuine old rows on disposable database copies. Only aggregate outcomes leave the copy."""
from contextlib import closing
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import socket
import sys
import tempfile
import time
import zipfile

STAGES = Path(__file__).resolve().parents[1]
ROOT = STAGES.parents[1]
sys.path.insert(0, str(ROOT))
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_session_scope import session_scope, source_identity
from src.services.ai_evidence_context import AiEvidenceContext
from src.services.ai_store import DiagnosticStore
from src.services.qt_ai_chat import QtAiChat


def check():
    receipt = json.loads((STAGES/'backup_receipt.json').read_text('utf-8-sig'))
    archive = Path(receipt['directory']) / 'data.zip'
    counts = dict(selected=0, writable_retained=0, evidence_rows=0, records_unchanged=0)
    with tempfile.TemporaryDirectory(prefix='dutpilot-read-legacy-chat-') as tmp, zipfile.ZipFile(archive) as zipped, \
            patch.dict(os.environ, dict(LOCALAPPDATA=tmp, APPDATA=tmp, PROGRAMDATA=tmp)), \
            patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')) as network, \
            patch.object(DiagnosticModelClient, '__init__', side_effect=AssertionError('model forbidden')) as model, \
            patch.object(DiagnosticStore, 'key', side_effect=AssertionError('credential unnecessary')) as key:
        members=set(zipped.namelist())
        for index, member in enumerate(sorted(members)):
            if PurePosixPath(member).name != 'diagnostics.sqlite3':
                continue
            directory = Path(tmp)/str(index)
            directory.mkdir()
            for suffix in ('','-wal','-shm','-journal'):
                if member+suffix in members:
                    (directory/('diagnostics.sqlite3'+suffix)).write_bytes(zipped.read(member+suffix))
            with closing(DiagnosticStore(directory)) as store:
                records = [row for row in store.chats() if session_scope(row)=='device' and row.get('target')
                           and row.get('run_id') not in ('manual', '', None) and not row.get('source_report_id')
                           and not row.get('batch_parent') and not row.get('capability_business_batch')
                           and source_identity(row.get('source'))==source_identity(None)]
                if not records:
                    continue
                context = AiEvidenceContext()
                app = QtAiChat(store, SimpleNamespace(source_root=ROOT, maintenance=None), lambda _: None,
                               SimpleNamespace(root=directory), context)
                try:
                    for row in records:
                        identifier = row['id']
                        messages, evidence = store.chat_items(identifier), store.chat_evidence(identifier)
                        view = app.execute('ai_chat_select', (identifier,))
                        assert view.selected == identifier
                        counts['selected'] += 1
                        counts['writable_retained'] += int(view.writable and view.history_analysis)
                        projected = app.execute('ai_chat_evidence', (identifier,))
                        assert projected == tuple((e['source'],e['timing'],e['text']) for e in evidence)
                        counts['evidence_rows'] += len(projected)
                        assert store.chat(identifier)==row and store.chat_items(identifier)==messages and store.chat_evidence(identifier)==evidence
                        counts['records_unchanged'] += 1
                finally:
                    deadline = time.monotonic()+10
                    while not app.begin_close():
                        assert time.monotonic()<deadline, 'project workers did not stop'
                        time.sleep(.02)
        network.assert_not_called()
        model.assert_not_called()
        key.assert_not_called()
        counts.update(network_connections=0,model_requests=0,credential_reads=0)
    return counts


if __name__=='__main__':
    print(json.dumps(check(),indent=2))

"""Restore into a disposable directory; never overwrite the user's live files."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def main():
    output = Path(__file__).resolve().parent
    receipt = json.loads((output / 'backup_receipt.json').read_text(encoding='utf-8'))
    backup = Path(receipt['directory'])
    manifest = json.loads((backup / 'source_manifest.json').read_text(encoding='utf-8'))
    databases = 0
    with tempfile.TemporaryDirectory(prefix='dutpilot-restore-check-') as temporary:
        root = Path(temporary).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        for filename in ('source.zip', 'data.zip'):
            destination = root / filename[:-4]
            destination.mkdir()
            with zipfile.ZipFile(backup / filename) as archive:
                assert archive.testzip() is None
                for item in archive.infolist():
                    (destination / item.filename).resolve().relative_to(destination)
                    archive.extract(item, destination)
        for relative, expected in manifest.items():
            assert hashlib.sha256((root / 'source' / relative).read_bytes()).hexdigest() == expected
        for path in (root / 'data').rglob('*'):
            if path.is_file() and path.suffix in ('.db', '.sqlite', '.sqlite3'):
                with path.open('rb') as stream:
                    if stream.read(16) != b'SQLite format 3\x00':
                        continue
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
                    assert database.execute('PRAGMA quick_check').fetchall() == [('ok',)]
                databases += 1
    result = dict(source_files_verified=len(manifest), sqlite_snapshots_verified=databases,
                  restored_to_live_paths=False, exe_executed=False, passed=True)
    (output / 'restore_result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()

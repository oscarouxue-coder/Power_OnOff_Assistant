"""Local-only source/data backup. No imports from the product, no hardware access."""
import hashlib
import importlib.metadata
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2]
REPO = SOURCE.parent
OUT = Path(__file__).resolve().parent


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def regular_files(root):
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = [name for name in children if not (
            (Path(directory) / name).stat().st_file_attributes & 0x400)]
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink() and not path.stat().st_file_attributes & 0x400:
                yield path


def main():
    destination = Path(os.environ['LOCALAPPDATA']) / 'LineCheckAssistant' / 'migration-backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    destination.mkdir(parents=True, exist_ok=False)
    subprocess.run(['git', 'diff', '--binary', '--output=' + str(destination / 'worktree.patch')], cwd=REPO, check=True)
    subprocess.run(['git', 'diff', '--cached', '--binary', '--output=' + str(destination / 'index.patch')], cwd=REPO, check=True)
    entries = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=REPO).decode('utf-8').split('\0')
    protected = {'build', 'dist', 'logs', '.venv', '__pycache__', '.git', 'validation', 'assistant_logs'}
    manifest = {}
    with zipfile.ZipFile(destination / 'source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(entries)):
            path = REPO / name
            if not name or any(part in protected or part.startswith('.venv') for part in path.relative_to(REPO).parts):
                continue
            if path.is_file():
                data = path.read_bytes()
                archive.writestr(name, data)
                manifest[name] = hashlib.sha256(data).hexdigest()
    (destination / 'source_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    roots = [SOURCE / 'Auto_power_on_off_tool' / 'config']
    local = Path(os.environ['LOCALAPPDATA']) / 'LineCheckAssistant'
    roots.extend(local / name for name in ('workspace', 'ai', 'case_library', 'projects', 'gateway'))
    roots.append(Path(os.environ['PROGRAMDATA']) / 'LineCheckAssistant' / 'host-resource-fence')
    recent = local / 'workspace' / 'recent_projects.json'
    if recent.is_file():
        values = json.loads(recent.read_text(encoding='utf-8-sig'))
        roots.extend(Path(value['path']).resolve().parent if Path(value['path']).suffix == '.json'
                     else Path(value['path']).resolve() for value in values)
    roots.extend([SOURCE / 'assistant_logs', SOURCE / 'test_results', SOURCE / 'Prototype_log',
                  SOURCE / 'Auto_power_on_off_tool' / 'logs', SOURCE / 'Auto_power_on_off_tool' / 'test_results'])
    counts, failures = [], []
    with zipfile.ZipFile(destination / 'data.zip', 'w', zipfile.ZIP_DEFLATED) as archive, tempfile.TemporaryDirectory(prefix='migration-db-') as temporary:
        for number, root in enumerate(dict.fromkeys(roots)):
            count = 0
            if root.is_dir():
                for path in regular_files(root):
                    if path.name.endswith(('-wal', '-shm')):
                        continue  # Databases use SQLite's online snapshot API below.
                    try:
                        value = path
                        if path.suffix in ('.db', '.sqlite', '.sqlite3'):
                            value = Path(temporary) / 'snapshot.sqlite3'
                            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as origin, closing(sqlite3.connect(str(value))) as target:
                                deadline = time.monotonic() + 30
                                def progress(status, remaining, total):
                                    if time.monotonic() > deadline:
                                        raise TimeoutError('SQLite snapshot exceeded 30 seconds')
                                origin.backup(target, pages=128, progress=progress)
                        archive.write(value, f'{number:02d}/' + path.relative_to(root).as_posix())
                        count += 1
                    except (OSError, sqlite3.Error, TimeoutError) as exc:
                        failures.append(dict(path=str(path), error=type(exc).__name__))
            counts.append(dict(root=str(root), exists=root.is_dir(), files=count))
    artifacts = []
    for path in SOURCE.joinpath('dist').glob('*.exe'):
        saved = destination / 'artifacts' / path.name
        saved.parent.mkdir(exist_ok=True)
        shutil.copy2(path, saved)
        artifacts.append(dict(name=path.name, bytes=path.stat().st_size, sha256=sha(saved),
                              executed=False, version_match='not established; existing artifact only'))
    dependencies = sorted({(d.metadata['Name'], d.version) for d in importlib.metadata.distributions()})
    (destination / 'dependencies.json').write_text(json.dumps(dict(python=sys.version, executable=sys.executable,
        dependencies=dependencies), ensure_ascii=False, indent=2), encoding='utf-8')
    # Verify every archived source byte, not just ZIP CRC.
    with zipfile.ZipFile(destination / 'source.zip') as archive:
        assert archive.testzip() is None
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest.items())
    with zipfile.ZipFile(destination / 'data.zip') as archive:
        assert archive.testzip() is None
    private = dict(data_roots=counts, failures=failures, warning='LOCAL PRIVATE BACKUP: contains configuration and possible credentials; do not publish.')
    (destination / 'PRIVATE_DATA_INDEX.json').write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding='utf-8')
    report = dict(directory=str(destination), branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO).decode().strip(),
        head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO).decode().strip(),
        source_files=len(manifest), data_files=sum(row['files'] for row in counts), data_failures=len(failures),
        artifact_copies=artifacts, source_zip_sha256=sha(destination / 'source.zip'), data_zip_sha256=sha(destination / 'data.zip'),
        original_environment_modified=False, data_consistency='per-file / SQLite online snapshots; not a transaction across all files')
    (OUT / 'backup_receipt.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())

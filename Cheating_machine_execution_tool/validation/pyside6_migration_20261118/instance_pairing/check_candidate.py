"""Compare a standard Qt candidate to its project sources without executing the EXE."""
import argparse
import ast
import hashlib
import json
import marshal
from pathlib import Path
from types import CodeType
from zipfile import ZipFile

from PyInstaller.archive.readers import CArchiveReader


def compare_source(code, path):
    if not isinstance(code, CodeType):
        raise ValueError(f'Missing Python code for {path}')
    expected = compile(path.read_bytes(), code.co_filename, 'exec', dont_inherit=True)
    if code != expected:
        raise ValueError(f'Packaged code differs from source: {path}')


def verify(candidate, reviewed_changes=None):
    root = Path(__file__).resolve().parents[3]
    if candidate.parent != root / 'dist':
        raise ValueError('Specify the dist subdirectory of the standard Qt build')
    table = root / 'build' / candidate.name / 'DUTPilotQt/PYZ-00.toc'
    _, entries = ast.literal_eval(table.read_text(encoding='utf-8'))
    directory = candidate / 'DUTPilot_portable'
    archive = CArchiveReader(str(directory / 'DUTPilot.exe'))
    pyz = archive.open_embedded_archive('PYZ-00.pyz')
    names = {name for name, _, _ in entries}
    if names != set(pyz.toc):
        raise ValueError('Build input module names differ from actual PYZ contents')

    source_hashes = {}
    for name, filename, _ in entries:
        path = Path(filename)
        if path.is_absolute() and root in path.parents:
            compare_source(pyz.extract(name), path)
            source_hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    required = {
        'src/services/qt_workspace_adapter.py',
        'src/services/legacy_power_test_service.py',
        'src/ui/qt/instance_pairing_dialog.py',
        'src/ui/qt/instance_status_dialog.py',
        'src/ui/qt/workspace_controller.py',
    }
    if not required.issubset(source_hashes):
        raise ValueError(f'Missing required project inputs: {sorted(required - source_hashes.keys())}')
    compare_source(marshal.loads(archive.extract('run_dutpilot_qt')), root / 'run_dutpilot_qt.py')

    original = Path(__file__).resolve().parents[1] / 'current_candidate_review/source-check.json'
    protected = json.loads(original.read_text(encoding='utf-8'))['protected_files']
    reviewed = {} if reviewed_changes is None else json.loads(reviewed_changes.read_text(encoding='utf-8'))
    if reviewed.keys() - {row['path'] for row in protected}:
        raise ValueError('Reviewed list contains a path outside the protected baseline')
    for row in protected:
        path = row['path']
        expected = row['sha256']
        if path in reviewed:
            change = reviewed[path]
            if change['before'] != expected or change['after'] == expected or source_hashes.get(path) != change['after']:
                raise ValueError(f'Reviewed change does not match baseline and packaged source: {path}')
            expected = change['after']
        if not row['matches_original'] or hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Original business source changed: {row['path']}")
    manual = 'line_check_assistant_README.md'
    bundle_path = candidate / 'DUTPilot_portable.zip'
    with ZipFile(bundle_path) as bundle:
        if bundle.testzip() is not None or bundle.read('DUTPilot_portable/' + manual) != (root / manual).read_bytes():
            raise ValueError('ZIP integrity or packaged operator manual mismatch')
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    checksum = (candidate / 'DUTPilot_portable.zip.sha256.txt').read_text(encoding='utf-8-sig')
    if digest.lower() not in checksum.lower().split():
        raise ValueError('ZIP checksum differs from sidecar')
    return dict(candidate=candidate.name, zip_sha256=digest, zip_bytes=bundle_path.stat().st_size,
                matched_project_modules=len(source_hashes), source_sha256=source_hashes,
                original_business_files=len(protected) - len(reviewed), reviewed_business_changes=reviewed,
                entry_matches=True, manual_matches=True,
                zip_crc_verified=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--reviewed-changes', type=Path, help='Stage-specific exact before/after SHA256 pairs')
    args = parser.parse_args()
    print(json.dumps(verify(args.candidate.resolve(), args.reviewed_changes), ensure_ascii=False, indent=2))

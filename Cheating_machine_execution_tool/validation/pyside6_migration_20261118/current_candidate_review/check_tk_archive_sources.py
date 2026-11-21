"""Check packaged first-party Python against both the release and the Phase 0 snapshot."""
import hashlib
import json
import marshal
from pathlib import Path
import subprocess
from zipfile import ZipFile

from PyInstaller.archive.readers import CArchiveReader


ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parents[1]
TAG = 'v1.2.10'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def same_code(code, source):
    return code == compile(source, code.co_filename, 'exec', dont_inherit=True)


def verify():
    receipt = json.loads((STAGE / 'backup_receipt.json').read_text('utf-8'))
    backup = Path(receipt['directory']) / 'source.zip'
    if hashlib.sha256(backup.read_bytes()).hexdigest() != receipt['source_zip_sha256']:
        raise ValueError('Phase 0 source backup checksum differs')
    package = ROOT / 'dist/V1.2.10_slim_20261113'
    executable = package / 'LineCheckAssistant.exe'
    bundle = package / 'LineCheckAssistant_portable.zip'
    reference = json.loads((STAGE / 'current_candidate_review/tk-archive.json').read_text('utf-8-sig'))
    exe_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    if exe_hash != reference['ExeSHA256'].lower():
        raise ValueError('Tk EXE differs from reviewed release')
    with ZipFile(bundle) as portable:
        if (hashlib.sha256(bundle.read_bytes()).hexdigest() != reference['ZipSHA256'].lower()
                or portable.testzip() is not None
                or hashlib.sha256(portable.read('LineCheckAssistant_portable/LineCheckAssistant.exe')).hexdigest() != exe_hash):
            raise ValueError('Tk portable archive differs from reviewed release')

    archive = CArchiveReader(str(executable))
    pyz = archive.open_embedded_archive('PYZ-00.pyz')
    prefix = git('rev-parse', '--show-prefix').decode().strip()
    files = set(git('ls-tree', '-rz', '--name-only', TAG, '--', '.').decode('utf-8').split('\0'))
    paths = {'run_line_check_assistant': 'run_line_check_assistant.py'}
    for module, entry in pyz.toc.items():
        relative = module.replace('.', '/') + ('/__init__.py' if entry[0] == 1 else '.py')
        candidates = [path for path in (relative, 'Auto_power_on_off_tool/' + relative) if path in files]
        if len(candidates) > 1:
            raise ValueError(f'Ambiguous source path: {module}')
        if candidates:
            paths[module] = candidates[0]
    if not {'src.services.legacy_power_test_service', 'line_check_assistant.app',
            'test_case.powe_on_off_telnet', 'common.power_on_off'} <= paths.keys():
        raise ValueError('Missing expected application / original power pipeline code')

    results = []
    with ZipFile(backup) as original:
        members = set(original.namelist())
        for module, relative in sorted(paths.items()):
            code = (marshal.loads(archive.extract(module)) if module == 'run_line_check_assistant'
                    else pyz.extract(module))
            member = prefix + relative
            release = git('cat-file', 'blob', f'{TAG}:{member}')
            results.append(dict(module=module, path=relative, matches_tag=same_code(code, release),
                                matches_backup=same_code(code, original.read(member)) if member in members else None))
    return dict(tag=TAG, tag_commit=git('rev-parse', TAG + '^{commit}').decode().strip(),
                backup_head=receipt['head'], exe_sha256=exe_hash, backup_sha256=receipt['source_zip_sha256'],
                modules=len(results), tag_matches=sum(row['matches_tag'] for row in results),
                backup_matches=sum(row['matches_backup'] is True for row in results), results=results)


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

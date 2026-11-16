"""Detect concurrent source edits during a baseline; never claims a later tree passed."""
import argparse
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2] / 'Cheating_machine_execution_tool'
parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--compare', type=Path)
arguments = parser.parse_args()
snapshot = {str(path.relative_to(root)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in ('src', 'line_check_assistant', 'tests', 'scripts') for path in sorted((root / directory).rglob('*.py'))}
arguments.output.write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
if arguments.compare:
    before = json.loads(arguments.compare.read_text(encoding='utf-8'))
    changed = [key for key in sorted(set(before) | set(snapshot)) if before.get(key) != snapshot.get(key)]
    if changed:
        print('SOURCE_CHANGED_DURING_BASELINE: ' + ', '.join(changed))
        raise SystemExit(1)
print('SOURCE_SNAPSHOT_OK: ' + str(len(snapshot)) + ' Python files')

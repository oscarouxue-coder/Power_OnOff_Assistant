"""Serial stage checks; preserve other stages' evidence."""
from verify_phase3 import main
import hashlib
import json
from pathlib import Path


if __name__ == '__main__':
    status = main('serial_source_checks.json')
    output = Path(__file__).resolve().parent
    receipt = json.loads((output / 'backup_receipt.json').read_text(encoding='utf-8'))
    manifest = json.loads((Path(receipt['directory']) / 'source_manifest.json').read_text(encoding='utf-8'))
    repository = output.parents[2]
    checked = {}
    for name in ('src/ui/serial_terminal.py', 'src/models/serial_delivery.py', 'src/core/serial_transport.py'):
        relative = 'Cheating_machine_execution_tool/' + name
        checked[name] = hashlib.sha256((repository / relative).read_bytes()).hexdigest() == manifest[relative]
    result_path = output / 'serial_source_checks.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    result['original_serial_boundary'] = checked
    result['passed'] &= all(checked.values())
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SERIAL_ORIGINAL_BOUNDARY', checked)
    raise SystemExit(status or int(not result['passed']))

"""DUT Telnet increment source gates and explicit original-boundary comparison."""
from verify_phase3 import main
import hashlib
import json
from pathlib import Path


if __name__ == '__main__':
    status = main('dut_telnet_source_checks.json')
    output = Path(__file__).resolve().parent
    receipt = json.loads((output / 'backup_receipt.json').read_text(encoding='utf-8'))
    manifest = json.loads((Path(receipt['directory']) / 'source_manifest.json').read_text(encoding='utf-8'))
    repository = output.parents[2]
    names = ('src/ui/dut_config_window.py', 'src/models/dut_config_models.py',
        'src/services/dut_config_service.py', 'src/services/dut_status_query_service.py',
        'src/services/dut_advanced_config_service.py', 'src/core/ubus_enable_telnet.py',
        'src/core/dut_ubus_config.py', 'src/core/dut_wifi_config.py',
        'src/services/capability_device_services.py')
    boundary = {}
    for name in names:
        relative = 'Cheating_machine_execution_tool/' + name
        boundary[name] = hashlib.sha256((repository / relative).read_bytes()).hexdigest() == manifest[relative]
    path = output / 'dut_telnet_source_checks.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    result['original_dut_boundary'] = boundary
    result['passed'] &= all(boundary.values())
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('ORIGINAL_DUT_BOUNDARY', boundary)
    raise SystemExit(status or int(not result['passed']))

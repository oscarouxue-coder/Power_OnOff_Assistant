"""Cumulative WAN/WiFi form extraction and unchanged original business gates."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile
from verify_phase3 import main
from verify_wan import index


def verify(result_filename='wifi_source_checks.json', additional_moves=None, additional_tests=(), legacy_reviewers=None):
    status = main(result_filename, legacy_reviewers)
    output = Path(__file__).resolve().parent
    source = output.parents[1]
    receipt = json.loads((output/'backup_receipt.json').read_text(encoding='utf-8'))
    backup = Path(receipt['directory'])
    manifest = json.loads((backup/'source_manifest.json').read_text(encoding='utf-8'))
    relative = 'Cheating_machine_execution_tool/src/ui/dut_config_window.py'
    with zipfile.ZipFile(backup/'source.zip') as archive:
        original_bytes = archive.read(relative)
    original = index(original_bytes.decode('utf-8'))
    current = index((source/'src/ui/dut_config_window.py').read_text(encoding='utf-8'))
    moves = {
        'dut_wan_form': {'WAN_ROUTER_SERVICE_TYPES','WAN_BRIDGE_SERVICE_TYPES','WAN_LAN_PORTS','WAN_LAN_PORT_MASK',
            '_port_bind_mask_value','wan_lan_ports_from_port_bind','wan_port_bind_from_lan_ports','WanFormRules',
            'normalize_wan_address_modes','resolve_wan_form_rules','wan_connection_form_values'},
        'dut_wifi_form': {'WIFI_SSID_INDEX_OPTIONS','WIFI_CHANNEL_OPTIONS','WIFI_TRANSMIT_POWER_OPTIONS',
            'wifi_status_form_values','wifi_choice_options'},
    }
    moves.update(additional_moves or {})
    expected = set().union(*moves.values())
    moved_ast = {}
    for module, names in moves.items():
        shared = index((source/('src/models/'+module+'.py')).read_text(encoding='utf-8'))
        moved_ast.update({n: original[n] == shared.get(n) for n in sorted(names)})
    ast_checks = dict(backup_verified=hashlib.sha256(original_bytes).hexdigest()==manifest[relative],
        moved_names_exact=set(original)-set(current)==expected, moved_ast=moved_ast,
        remaining_ast={n:original[n]==current.get(n) for n in sorted(set(original)-expected)},
        no_unexpected_definitions=not (set(current)-set(original)))
    path = output/result_filename
    result = json.loads(path.read_text(encoding='utf-8'))
    result['original_dut_presentation'] = ast_checks
    result['passed'] &= all((ast_checks['backup_verified'], ast_checks['moved_names_exact'],
        all(moved_ast.values()), all(ast_checks['remaining_ast'].values()), ast_checks['no_unexpected_definitions']))
    # Compile the explicit native suite even when desktop isolation cannot run it.
    for relative in ('tests/qt_workbench_probe.py','tests/qt_wifi_fakes.py','tests/test_qt_dut_wifi.py', *additional_tests):
        compile((source/relative).read_text(encoding='utf-8'),relative,'exec')
    result['native_suite_syntax'] = True
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('DUT_AST_PRESERVED',result['passed'],len(moved_ast),len(ast_checks['remaining_ast']))
    return status or int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(verify())

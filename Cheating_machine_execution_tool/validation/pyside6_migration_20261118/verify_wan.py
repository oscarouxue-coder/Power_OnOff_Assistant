"""WAN stage gates and exact AST preservation of extracted Tk form rules."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile
from verify_phase3 import main


def index(text):
    values = {}
    for node in ast.parse(text).body:
        name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name and isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)):
            values[name] = ast.dump(node, include_attributes=False)
    return values


if __name__ == '__main__':
    status = main('wan_source_checks.json')
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
    shared = index((source/'src/models/dut_wan_form.py').read_text(encoding='utf-8'))
    moved = set(original) - set(current)
    expected = {'WAN_ROUTER_SERVICE_TYPES','WAN_BRIDGE_SERVICE_TYPES','WAN_LAN_PORTS','WAN_LAN_PORT_MASK',
        '_port_bind_mask_value','wan_lan_ports_from_port_bind','wan_port_bind_from_lan_ports','WanFormRules',
        'normalize_wan_address_modes','resolve_wan_form_rules','wan_connection_form_values'}
    ast_checks = dict(backup_verified=hashlib.sha256(original_bytes).hexdigest()==manifest[relative],
        moved_names_exact=moved==expected, moved_ast={n:original[n]==shared.get(n) for n in sorted(expected)},
        remaining_ast={n:original[n]==current.get(n) for n in sorted(set(original)-expected)},
        no_unexpected_definitions=not (set(current)-set(original)))
    path = output/'wan_source_checks.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    result['original_wan_presentation']=ast_checks
    result['passed'] &= all((ast_checks['backup_verified'],ast_checks['moved_names_exact'],
        all(ast_checks['moved_ast'].values()),all(ast_checks['remaining_ast'].values()),ast_checks['no_unexpected_definitions']))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('WAN_AST_PRESERVED',result['passed'],len(ast_checks['moved_ast']),len(ast_checks['remaining_ast']))
    raise SystemExit(status or int(not result['passed']))

"""Read-only original-business preservation and source gates for the Qt stage."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile


def check_firmware_manual_bridge(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    replacements = {
        'firmware_upgrade_validation_service.py': (
            ('require_confirmation=True, local_manual_restart=False', 'require_confirmation=True'),
            ('''        manual_required = args["upgrade_type"] == "全包升级" and not snapshot.get("power_serial_port")
        if local_manual_restart:
            if authority.source != "gui":
                raise CapabilityError("source_forbidden", "人工重启续接只供本机升级窗口")
            if not manual_required:
                raise CapabilityError("target_changed", "程控电源或升级模式已变化，请重新预检")
''', ''),
            ('        if manual_required and not local_manual_restart:',
             '        if args["upgrade_type"] == "全包升级" and not snapshot.get("power_serial_port"):'),
        ),
        'capability_service.py': (
            ('''    def _upgrade(self, arguments, authority, *, local_manual_restart=False):
        # Only the host-owned firmware editor can supply this keyword; it is not in UPGRADE_SCHEMA.
        manual = {"local_manual_restart": True} if local_manual_restart else {}
        prepared = self.upgrades.validate(arguments, authority, **manual)
''', '''    def _upgrade(self, arguments, authority):
        prepared = self.upgrades.validate(arguments, authority)
'''),
            ('current = self.upgrades.validate(arguments, authority, **manual)',
             'current = self.upgrades.validate(arguments, authority)'),
            ('''            if local_manual_restart:
                context.event("preparing", "本机已确认所选样机手动重启，按空程控电源口进入原升级引擎")
''', ''),
            ('''        if local_manual_restart:
            recorded["manual_restart_confirmed"] = True
''', ''),
        ),
    }
    exact = current.read_text(encoding='utf-8')
    for new, prior in replacements[current.name]:
        if exact.count(new) != 1:
            return False
        exact = exact.replace(new, prior)
    return exact == original.decode('utf-8').replace('\r\n', '\n')


def check_pipeline_gui_bridge(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    exact = current.read_text(encoding='utf-8')
    for new, prior in (
        ('from contextlib import nullcontext\n', ''),
        ('log_directory, *, serial_prestart=None', 'log_directory'),
        ('        self.serial_prestart = serial_prestart\n', ''),
        ('''        if self.serial_prestart is not None:
            return self.serial_prestart(self.context, self.channels, self.log_directory)
''', ''),
        ('        self.gui_pipeline_serial_prestart = None\n', ''),
        ('        self.gui_pipeline_power_scope = None\n', ''),
        ('''                hold = self.gui_pipeline_power_scope if authority.source == "gui" and "legacy_power_test" in tasks else None
                with hold(projection) if hold is not None else nullcontext():
                    results = self.pipeline_factory(config, lambda line: context.event("pipeline", line)).run(set(tasks))
                    stopped = context.stop.is_set()''',
         '                results = self.pipeline_factory(config, lambda line: context.event("pipeline", line)).run(set(tasks))'),
        ('and not stopped,\n                            state="stopped" if stopped else',
         'and not context.stop.is_set(),\n                            state="stopped" if context.stop.is_set() else'),
        ('''                snapshot.get("serial_log_dir") or self.service.jobs.directory / "serial",
                serial_prestart=self.gui_pipeline_serial_prestart if authority.source == "gui" else None)''',
         '                snapshot.get("serial_log_dir") or self.service.jobs.directory / "serial")'),
    ):
        if exact.count(new) != 1:
            return False
        exact = exact.replace(new, prior)
    return exact == original.decode('utf-8').replace('\r\n', '\n')


def check_resource_options_extraction(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    text = original.decode('utf-8').replace('\r\n', '\n')
    start = text.index('def _power_serial_group_index(')
    end = text.index('CHANNEL_TABLE_COMBO_WIDTH', start)
    helpers = text[start:end]
    shared = current.parents[1] / 'src/models/channel_resource_options.py'
    expected_shared = '''"""Original channel resource candidate rules shared by both workbenches."""
import re

from line_check_assistant.network_ops import adapter_alias_from_display
from line_check_assistant.serial_ports import port_from_display


POWER_SUPPLY_COUNT = 6
VLAN_PER_POWER_SUPPLY = 8
FIRST_VLAN_ID = 101
POWER_SERIAL_OPTIONS = ("", *(f"COM{101 + index}" for index in range(POWER_SUPPLY_COUNT)))


''' + helpers
    if shared.read_text(encoding='utf-8') != expected_shared:
        return False
    text = text[:start] + text[end:]
    imports = 'from src.models.upgrade_stop import UpgradeStopped, UpgradeStoppedResult\n'
    for original_text, changed in (
        ('POWER_SUPPLY_COUNT = 6\nTOTAL_CHANNEL_COUNT = 16\nVLAN_PER_POWER_SUPPLY = 8\nFIRST_VLAN_ID = 101\n',
         'TOTAL_CHANNEL_COUNT = 16\n'),
        (imports, '''from src.models.channel_resource_options import (
    FIRST_VLAN_ID, POWER_SERIAL_OPTIONS, POWER_SUPPLY_COUNT, VLAN_PER_POWER_SUPPLY,
    _power_serial_group_index, serial_options_for_power_serial_port, vlan_options_for_power_serial_port,
)
''' + imports),
        ('return ["", *[f"COM{101 + index}" for index in range(POWER_SUPPLY_COUNT)]]',
         'return list(POWER_SERIAL_OPTIONS)'),
    ):
        if text.count(original_text) != 1:
            return False
        text = text.replace(original_text, changed)
    return text == current.read_text(encoding='utf-8')


def check_job_log_output(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    source = current.read_text(encoding='utf-8')
    for added, prior in (
        ('        self.event_output = None\n', ''),
        ('            created = time.time()\n', ''),
        ('                            (identifier, created, stage, str(message)))',
         '                            (identifier, time.time(), stage, str(message)))'),
        ('''            if self.event_output is None:
                self.emit(f"[业务任务 {identifier[:8]}][{stage}] {message}")
            else:
                self.event_output(identifier, created, stage, str(message))''',
         '            self.emit(f"[业务任务 {identifier[:8]}][{stage}] {message}")'),
    ):
        if source.count(added) != 1:
            return False
        source = source.replace(added, prior)
    return source == original.decode('utf-8').replace('\r\n', '\n')


def check_imported_connection_hook(current, digest, archive, relative):
    with zipfile.ZipFile(archive) as backup:
        original = backup.read(relative)
    if hashlib.sha256(original).hexdigest() != digest:
        return False
    text = current.read_text(encoding='utf-8')
    signature = '    def use_connection(self, candidate, *, validate_selection=None):'
    hook = '        if validate_selection is not None:\n            validate_selection(value)\n'
    if text.count(signature) != 1 or text.count(hook) != 1:
        return False
    without_hook = text.replace(signature, '    def use_connection(self, candidate):').replace(hook, '')
    return without_hook == original.decode('utf-8').replace('\r\n', '\n')


def main(result_filename='phase3_source_checks.json', legacy_reviewers=None):
    output = Path(__file__).resolve().parent
    source = output.parents[1]
    repository = source.parent
    sys.path.insert(0, str(source / 'scripts'))
    import verify_baseline as baseline
    import verify_capability_coverage as capability
    import verify_gui_test_coverage as gui
    checks = [baseline.run_py_compile(source), baseline.check_py_compile_inventory(source)]
    checks += baseline.check_must_exist(source) + baseline.check_must_not_exist(source)
    receipt = json.loads((output / 'backup_receipt.json').read_text(encoding='utf-8'))
    manifest = json.loads((Path(receipt['directory']) / 'source_manifest.json').read_text(encoding='utf-8'))
    prefix = source.name + '/'
    groups = {'original_core_services': [], 'original_legacy_python': [], 'local_config': [], 'original_tk_app': []}
    legacy_reviewers = {
        'src/services/capability_jobs.py': check_job_log_output,
        'line_check_assistant/app.py': check_resource_options_extraction,
        'src/services/capability_service.py': check_firmware_manual_bridge,
        'src/services/firmware_upgrade_validation_service.py': check_firmware_manual_bridge,
        'src/services/capability_device_services.py': check_pipeline_gui_bridge,
        'src/services/workspace_service.py': check_imported_connection_hook,
        **(legacy_reviewers or {}),
    }
    reviewed = {}
    for relative, digest in manifest.items():
        key = relative.replace('\\', '/')
        if not key.startswith(prefix):
            continue
        path = key[len(prefix):]
        group = None
        if path.startswith(('src/core/', 'src/services/')) and path.endswith('.py'):
            group = 'original_core_services'
        elif path.lower().startswith('auto_power_on_off_tool/'):
            if path.endswith('.py'):
                group = 'original_legacy_python'
            elif path.lower().startswith('auto_power_on_off_tool/config/'):
                group = 'local_config'
        elif path == 'line_check_assistant/app.py':
            group = 'original_tk_app'
        if group:
            current = repository / relative
            unchanged = current.is_file() and hashlib.sha256(current.read_bytes()).hexdigest() == digest
            if not unchanged and current.is_file() and path in legacy_reviewers:
                reviewed[path] = legacy_reviewers[path](current, digest, Path(receipt['directory']) / 'source.zip', relative)
            groups[group].append((relative, unchanged or reviewed.get(path, False)))
    result = dict(checks=[r._asdict() for r in checks], capability_errors=capability.check(source),
        gui_errors=gui.check(source), preservation={group: dict(files=len(rows), changed=[name for name, ok in rows if not ok])
            for group, rows in groups.items()})
    if reviewed:
        result['reviewed_legacy_edits'] = reviewed
    result['passed'] = (all(r.passed for r in checks) and not result['capability_errors'] and not result['gui_errors']
        and all(v['files'] and not v['changed'] for v in result['preservation'].values()))
    (output / result_filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

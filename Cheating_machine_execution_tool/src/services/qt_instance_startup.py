"""Local review and save of the original next-start instance configuration."""
import hashlib

from src.core.host_resource_lock import HostResourceBusy
from src.models.project_review import ReviewRequired
from src.services.ai_project_store import project_directory
from src.services.remote_instance_management import read_startup


def _saved_mode(management):
    try:
        return read_startup(management.app_dir), ''
    except ValueError:
        path = project_directory(management.app_dir) / 'instance_startup.json'
        return dict(mode='direct', slot=1), hashlib.sha256(path.read_bytes()).hexdigest()


def startup_review(management, registry, number=None):
    with management.lock:
        startup, invalid_digest = _saved_mode(management)
        number = startup['slot'] if number is None else number
        slot_error = ''
        try:
            slot = management.slot(number)
        except (HostResourceBusy, ValueError, OSError):
            slot = None
            slot_error = '槽位被占用或配置无法读取，可重新读取、选择其他槽位或保存直接接入'
        options = [(row['capability_id'], row['name']) for row in management.capabilities(registry)]
        return dict(startup=startup, number=number, slot=slot, slot_error=slot_error,
                    invalid_digest=invalid_digest, options=options)


def save_startup(management, registry, reviewed, mode, url, vpn, channels, capabilities):
    with management.lock:
        number = reviewed['number']
        if _saved_mode(management) != (reviewed['startup'], reviewed['invalid_digest']):
            raise ReviewRequired('configuration_changed', '保存期间配置已变化，请重新读取所选槽位', 'startup', 'reload')
        if mode == 'gateway' and (not reviewed['slot'] or management.slot(number) != reviewed['slot']):
            raise ReviewRequired('configuration_changed', '保存期间配置已变化，请重新读取所选槽位', 'startup', 'reload')
        management.save_instance(mode, number, url, vpn, channels, capabilities, registry=registry)

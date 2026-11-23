"""Persist project metadata alongside the existing versioned configuration files."""
import hashlib
import json
from pathlib import Path
from threading import RLock

from src.models.project_profile import normalize_project_profile
from src.services.project_store import atomic_json


PROFILE_FILE = 'project_profile.json'
_write_lock = RLock()


def read_project_profile(config_dir):
    path = Path(config_dir) / PROFILE_FILE
    if path.is_symlink():
        raise ValueError('项目档案不能通过链接重定向')
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise ValueError('项目档案须为 UTF-8 文件') from exc
    try:
        return normalize_project_profile(json.loads(text), assign_ids=False)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f'项目档案无效：{exc}') from exc


def project_profile_digest(profile):
    if profile is None:
        return ''
    data = normalize_project_profile(profile, assign_ids=False)
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def write_project_profile(config_dir, profile, *, expected_profile_digest=None):
    """Stage one complete edit in the draft. The caller chooses when to save a revision."""
    normalized = normalize_project_profile(profile)
    with _write_lock:
        previous = read_project_profile(config_dir)
        if expected_profile_digest is not None and project_profile_digest(previous) != expected_profile_digest:
            raise ValueError('项目档案已更改，请重新读取后核对')
        if previous != normalized:
            atomic_json(Path(config_dir) / PROFILE_FILE, normalized)
    return normalized

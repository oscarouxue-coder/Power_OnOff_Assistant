"""Versioned local defaults shared only by projects of the same model and test type."""
import json
from pathlib import Path

from src.core.host_resource_lock import HostResourceLock
from src.models.project_profile import normalize_project_profile
from src.services.project_store import atomic_json


PRESET_FIELDS = ('model', 'test_type', 'optional_steps', 'type_config')


def _defaults(profile):
    normalized = normalize_project_profile({key: profile[key] for key in PRESET_FIELDS}, assign_ids=False)
    if not normalized['model']:
        raise ValueError('请先保存产品型号')
    return {key: normalized[key] for key in PRESET_FIELDS}


class ProjectModelPresets:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / 'project_model_presets.json'

    def list(self):
        if self.path != self.path.resolve():
            raise ValueError('型号模板文件路径已重定向')
        try:
            with self.path.open(encoding='utf-8') as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return []
        if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
                or data['schema_version'] != 1 or not isinstance(data.get('presets'), list)):
            raise ValueError('型号模板文件格式无效')
        entries = []
        keys = set()
        for row in data['presets']:
            if (not isinstance(row, dict) or set(row) != {*PRESET_FIELDS, 'version'}
                    or type(row['version']) is not int or row['version'] < 1):
                raise ValueError('型号模板条目无效')
            entry = dict(_defaults(row), version=row['version'])
            key = (entry['model'].casefold(), entry['test_type'])
            if key in keys:
                raise ValueError('同一型号与测试类型存在重复模板')
            keys.add(key)
            entries.append(entry)
        return entries

    def save(self, profile, expected_version):
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('请核对模板版本')
        defaults = _defaults(profile)
        with HostResourceLock(['configuration:' + str(self.path)], reentrant=False):
            entries = self.list()
            previous = next((row for row in entries if row['model'].casefold() == defaults['model'].casefold()
                             and row['test_type'] == defaults['test_type']), None)
            if (previous['version'] if previous else 0) != expected_version:
                raise ValueError('型号模板已更新，请重新打开向导后核对')
            if previous:
                entries.remove(previous)
            entries.append(dict(defaults, version=expected_version + 1))
            entries.sort(key=lambda row: (row['model'].casefold(), row['test_type']))
            atomic_json(self.path, {'schema_version': 1, 'presets': entries})
        return entries

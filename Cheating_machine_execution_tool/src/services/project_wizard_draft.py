"""Recover one unfinished creation wizard per local workspace."""
import json
from pathlib import Path
import uuid

from src.core.host_resource_lock import HostResourceLock
from src.services.project_store import atomic_json


class ProjectWizardDraft:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / 'project_wizard_draft.json'

    def read(self):
        if self.path.resolve() != self.path:
            raise ValueError('向导草稿路径已重定向')
        try:
            with self.path.open(encoding='utf-8') as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return {'draft': None, 'token': ''}
        if (not isinstance(record, dict) or not isinstance(record.get('token'), str)
                or 'draft' not in record or not isinstance(record['draft'], (dict, type(None)))):
            raise ValueError('向导草稿格式无效，请核实工作区文件')
        return record

    def write(self, draft, expected_token):
        if draft is not None:
            if (not isinstance(draft, dict) or set(draft) != {'name', 'directory', 'page', 'profile'}
                    or not all(isinstance(draft[key], str) for key in ('name', 'directory'))
                    or type(draft['page']) is not int or not isinstance(draft['profile'], dict)
                    or len(json.dumps(draft, ensure_ascii=False)) > 128 * 1024):
                raise ValueError('向导草稿字段无效')
        with HostResourceLock(['configuration:' + str(self.path)], reentrant=False):
            if self.read()['token'] != expected_token:
                raise ValueError('向导草稿已更新，请重新打开核对')
            record = {'draft': draft, 'token': uuid.uuid4().hex}
            atomic_json(self.path, record)
            return record

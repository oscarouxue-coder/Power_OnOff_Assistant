"""Local Qt selection over the original imported platform stores."""
import hashlib

from src.models.capabilities import fingerprint


PLATFORM_NAMES = {'dingtalk': '钉钉', 'feishu': '飞书'}


class QtImportedConnections:
    def __init__(self, workspace):
        self.workspace = workspace

    @staticmethod
    def _digest(path, *, optional=False):
        if path.resolve() != path or path.is_symlink():
            raise ValueError('接入配置路径已重定向，请核对工作区目录')
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            if optional:
                return ''
            raise ValueError('已导入的接入配置不存在，请重新打开选择窗口') from None

    def _identity(self, candidate):
        root = self.workspace.directory.resolve() / 'platforms'
        directory = root / 'imported' / candidate['directory'].name
        kind = candidate['kind']
        return fingerprint((kind, directory.name, candidate['label'], self._digest(directory / 'source.json'),
            self._digest(directory / (kind + '.json')), self._digest(root / (kind + '.json'), optional=True)))

    def choices(self):
        return tuple((self._identity(item), PLATFORM_NAMES[item['kind']] + item['label'][len(item['kind']):])
                     for item in self.workspace.connection_candidates())

    def select(self, identity):
        for item in self.workspace.connection_candidates():
            if self._identity(item) == identity:
                break
        else:
            raise ValueError('候选或当前接入配置已变化，请重新打开选择窗口')

        def validate(value):
            if self._identity(item) != identity:
                raise ValueError('读取期间接入配置已变化，请重新打开选择窗口')
            if any(value.get(flag, False) is not False for flag in ('enabled', 'group_enabled', 'p2p_enabled', 'push_enabled')):
                raise ValueError('该导入候选含有启用设置，请重新导入后再选择')
            required = 'client_id' if item['kind'] == 'dingtalk' else 'app_id'
            if not value.get(required):
                raise ValueError('接入配置缺少应用身份，请重新导入后再选择')

        self.workspace.use_connection(item, validate_selection=validate)
        return PLATFORM_NAMES[item['kind']]

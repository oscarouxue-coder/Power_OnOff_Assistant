"""Project identity and paths; no GUI objects or device operations."""
from dataclasses import dataclass
from pathlib import Path


PROJECT_FILE = "project.linecheck.json"
FORMAT_VERSION = 1
WIZARD_DIRECTORY_SUFFIXES = {'power_cycle': '开关机挂测', 'service_aging': '全业务老化'}
_WINDOWS_DEVICE_NAMES = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + number for prefix in ('COM', 'LPT') for number in '123456789¹²³'
}


def wizard_project_destination(parent, name, test_type):
    """Build one safe directory name under the chosen parent, without touching disk."""
    name = name.strip()
    if not name or len(name) > 160:
        raise ValueError('项目名称须为1至160个字符')
    if name.endswith('.') or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name):
        raise ValueError('项目名称不能包含路径分隔符或 Windows 禁用字符，也不能以点结尾')
    if name.split('.', 1)[0].rstrip().upper() in _WINDOWS_DEVICE_NAMES:
        raise ValueError('项目名称不能使用 Windows 保留名，请更换项目名称')
    suffix = WIZARD_DIRECTORY_SUFFIXES.get(test_type) if isinstance(test_type, str) else None
    if suffix is None:
        raise ValueError('请选择自动开关机或全业务老化')
    location = Path(parent)
    if not location.is_absolute() or '..' in location.parts or '\0' in str(location):
        raise ValueError('请选择有效的绝对保存位置')
    leaf = f'{name}_{suffix}'
    if len(leaf.encode('utf-16-le', errors='surrogatepass')) > 510:
        raise ValueError('生成的项目文件夹名称过长，请缩短项目名称')
    return location / leaf


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    name: str
    revision: str
    format_version: int = FORMAT_VERSION


@dataclass
class ProjectContext:
    root: Path
    identity: ProjectIdentity
    source_root: Path

    @property
    def working_root(self):
        return self.root / "draft"

    @property
    def config_dir(self):
        return self.working_root / "Auto_power_on_off_tool" / "config"

    @property
    def saved_root(self):
        return self.root / "revisions" / self.identity.revision

    @property
    def history(self):
        return self.root / "history"

    def path(self, default):
        default = Path(default)
        if default == self.source_root:
            return self.working_root
        try:
            relative = default.relative_to(self.source_root)
        except ValueError:
            return default
        if relative.parts and relative.parts[0] == "assistant_logs":
            return self.root / "logs" / "main" / Path(*relative.parts[1:])
        return self.working_root / relative


def project_path(view, default):
    """Legacy callers retain module defaults; managed views use explicit context."""
    context = vars(view).get("project_context")
    return context.path(default) if context is not None else default


def project_log_root(view, default):
    if vars(view).get('project_context') is None:
        return default
    session = vars(view).get('power_test_resume_session')
    if session is not None:
        return session.request.tool_root
    return vars(view).get('_project_legacy_root', project_path(view, Path(default).parent) / 'Auto_power_on_off_tool')


def project_root_for(path):
    for parent in Path(path).resolve().parents:
        if (parent / PROJECT_FILE).is_file():
            return parent
    return None


def project_asset_path(config_path, value, *, saving=False):
    if not value:
        return value
    root = project_root_for(config_path)
    if root is None:
        return value
    path = Path(value)
    if saving:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return value
    return str(root / path) if not path.is_absolute() else value

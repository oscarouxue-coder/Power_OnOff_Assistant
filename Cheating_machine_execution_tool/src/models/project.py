"""Project identity and paths; no GUI objects or device operations."""
from dataclasses import dataclass
from pathlib import Path


PROJECT_FILE = "project.linecheck.json"
FORMAT_VERSION = 1


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

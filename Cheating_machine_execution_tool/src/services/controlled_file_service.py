"""Bounded file operations. Arbitrary executable/config writes are not a business API."""
from pathlib import Path
import hashlib
from src.models.capabilities import CapabilityError
from src.core.ai_local_executor import file_snapshot, read_local_file, write_local_file


class ControlledFiles:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()

    def information(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise CapabilityError("file_not_found", "文件不存在或不是普通文件")
        return dict(path=str(path), **file_snapshot(path))

    def list(self, path, pattern="*", limit=100):
        root = Path(path).expanduser().resolve()
        if not root.is_dir() or any(s in pattern for s in ("/", "\\", "..")):
            raise CapabilityError("invalid_parameters", "目录或单层匹配模式不合法")
        items = []
        for p in root.glob(pattern):
            if len(items) >= limit:
                return dict(items=items, truncated=True)
            items.append(dict(name=p.name, is_file=p.is_file(), size=p.stat().st_size if p.is_file() else None))
        return dict(items=items, truncated=False)

    def write(self, relative_path, content, expected_sha256=""):
        path = (self.workspace / relative_path).resolve()
        if self.workspace not in path.parents or path.suffix.lower() not in (".txt", ".md", ".csv", ".json"):
            raise CapabilityError("workspace_required", "文件输出仅允许工作区内的文本、报告及数据文件")
        # resolve() follows junctions/symlinks before the containment check.
        path.parent.mkdir(parents=True, exist_ok=True)
        before = file_snapshot(path)
        if before["exists"] and before["sha256"] != expected_sha256:
            raise CapabilityError("file_changed", "覆盖前需提供当前文件SHA256，不能覆盖未核对的内容")
        return write_local_file(str(path), content, before)

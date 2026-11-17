"""Thread-local configuration view of an admitted immutable project revision."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


_task_roots = ContextVar('linecheck_project_task_roots', default=None)


def task_path(path):
    roots = _task_roots.get()
    if roots is None:
        return path
    original, snapshot = roots
    try:
        return snapshot / Path(path).relative_to(original)
    except ValueError:
        return path


@contextmanager
def project_task_scope(original, snapshot):
    token = _task_roots.set((Path(original), Path(snapshot)))
    try:
        yield
    finally:
        _task_roots.reset(token)


class ScopedConfigPath:
    """A stored path resolves against the task snapshot only inside its worker."""
    def __set_name__(self, owner, name):
        self.storage = '_project_original_' + name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return task_path(vars(instance)[self.storage])

    def __set__(self, instance, value):
        vars(instance)[self.storage] = value

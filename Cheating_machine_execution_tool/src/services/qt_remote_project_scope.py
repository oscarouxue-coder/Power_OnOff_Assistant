"""Bind the local operator's scope review to the original workspace service."""
from dataclasses import dataclass
from uuid import uuid4
from weakref import ref


@dataclass(frozen=True)
class RemoteScopeReview:
    token: str
    rows: tuple


class QtRemoteProjectScope:
    def __init__(self, workspace):
        self.workspace = workspace
        self.review = None
        self.contexts = {}

    def _rows(self):
        opened = self.workspace.projects.opened
        allowed = self.workspace.remote_projects
        rows = [(key, context.identity.name, key in allowed) for key, context in opened.items()]
        rows.extend((key, '', True) for key in sorted(allowed - opened.keys()))
        return tuple(rows)

    def read(self):
        self.contexts = {key: ref(context) for key, context in self.workspace.projects.opened.items()}
        self.review = RemoteScopeReview(uuid4().hex, self._rows())
        return self.review

    def save(self, token, identifiers):
        review = self.review
        if review is None or token != review.token:
            raise ValueError('项目名单或授权范围已变化，请刷新后重新核对')
        self.review = None
        opened = self.workspace.projects.opened
        if (self._rows() != review.rows
                or any(saved() is not opened.get(key) for key, saved in self.contexts.items())):
            raise ValueError('项目名单或授权范围已变化，请刷新后重新核对')
        selected = set(identifiers)
        if not selected <= opened.keys():
            raise ValueError('只能授权本次已核对的打开项目，请刷新后重试')
        if selected != self.workspace.remote_projects:
            self.workspace.set_remote_projects(selected)
        return self.read()

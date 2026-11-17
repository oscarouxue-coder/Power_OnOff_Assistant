"""One authenticated platform connection routes to explicitly selected projects.

Per-project remote services retain their original inboxes, permissions, approvals,
reply correlation and jobs. The pool does not manufacture device authority.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading


class PooledLease:
    def __init__(self, *identities):
        pass

    def acquire(self):
        return self

    def close(self):
        pass


class ProjectPlatformConfig:
    def __init__(self, shared, directory):
        self.shared, self.directory = shared, Path(directory)
        self.path = shared.path

    def load(self):
        return self.shared.load()

    def save(self, value):
        return self.shared.save(value)

    def validate(self, value):
        return self.shared.validate(value)


class PooledTransport:
    def __init__(self, pool, project_id, credentials, receive, status, options=None):
        self.pool, self.project_id = pool, project_id
        self.credentials, self.receive, self.status = credentials, receive, status
        self.closed = False
        self.options = dict(options or {})

    def start(self):
        self.pool.add(self)

    def begin_close(self):
        self.closed = True
        self.pool.remove(self)

    @property
    def idle(self):
        return self.closed


class WorkspacePlatformPool:
    def __init__(self, kind, directory, projects, *, transport_factory=None, lease_factory=None, allowed=lambda: (), config_provider=None):
        self.kind, self.projects = kind, projects
        self.transport_factory, self.lease_factory = transport_factory, lease_factory
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory) / (kind + '_projects.sqlite3')), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS selected(identity TEXT PRIMARY KEY,project_id TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS received(id TEXT PRIMARY KEY,project_id TEXT,state TEXT)')
        self.db.commit()
        self.lock = threading.RLock()
        self.members = {}
        self.transport = self.lease = None
        self.credentials = None
        self.allowed = allowed
        self.config_provider = config_provider

    def factory(self, project_id):
        def make(first, second, receive, status, **options):
            return PooledTransport(self, project_id, (first, second), receive, status, options)
        return make

    def add(self, member):
        with self.lock:
            if self.transport is not None:
                if self.transport.idle:
                    self.transport = None
                    if self.lease:
                        self.lease.close()
                        self.lease = None
                elif self.credentials != member.credentials:
                    raise ValueError('平台账号已改变，请先停用统一接入并等待连接退出')
            self.members[member.project_id] = member
            if self.transport is not None:
                return
            if self.kind == 'dingtalk':
                from src.core.dingtalk_stream import DingTalkStream, InstanceLease
                factory, lease_factory = self.transport_factory or DingTalkStream, self.lease_factory or InstanceLease
                identity = 'client:' + member.credentials[0]
            else:
                from src.core.feishu_stream import FeishuStream, FeishuInstanceLease
                factory, lease_factory = self.transport_factory or FeishuStream, self.lease_factory or FeishuInstanceLease
                identity = member.credentials[0]
            lease = lease_factory(identity)
            lease.acquire()
            try:
                transport = factory(*member.credentials, self.receive, self.status, **member.options)
                transport.start()
            except BaseException:
                lease.close()
                self.members.pop(member.project_id, None)
                raise
            self.transport, self.lease, self.credentials = transport, lease, member.credentials

    def remove(self, member):
        with self.lock:
            if self.members.get(member.project_id) is member:
                self.members.pop(member.project_id)
            if not self.members and self.transport:
                self.transport.begin_close()

    def status(self, message):
        with self.lock:
            members = tuple(self.members.values())
        for member in members:
            member.status(message)

    def _parse(self, data, bot_id):
        if self.kind == 'dingtalk':
            from src.models.dingtalk_remote import RemoteMessage
            return RemoteMessage.parse(data)
        from src.models.feishu_remote import FeishuMessage
        return FeishuMessage.parse(data, self.credentials[0], bot_id)

    @staticmethod
    def _allowed(service, message, kind):
        if kind == 'feishu':
            return service._allowed(message)
        config = service.config
        return (not service.stop_event.is_set() and config.get('enabled') and message.robot == config.get('robot_code')
                and message.group == config.get('group') and message.corp == config.get('corp'))

    def receive(self, data, bot_id=''):
        try:
            message = self._parse(data, bot_id)
        except ValueError:
            return
        with self.lock:
            members = tuple(self.members.values())
        current = self.config_provider() if self.config_provider else None
        if current is not None:
            credentials = (current.get('client_id'), current.get('client_secret')) if self.kind == 'dingtalk' else (current.get('app_id'), current.get('app_secret'))
            if credentials != self.credentials:
                return
        # Binding keeps the existing local confirmation and token scope.
        for member in members:
            service = member.receive.__self__
            if service.binding_code and message.text == '绑定 ' + service.binding_code:
                self._deliver(member, data, bot_id)
                return
        eligible = [m for m in members if m.project_id in self.allowed() and self._allowed(m.receive.__self__, message, self.kind)
                    and (current is None or m.receive.__self__.config == current)]
        if not eligible:
            return
        key = json.dumps([self.kind, message.robot, message.corp, message.group, message.sender,
                          getattr(message, 'chat_type', 'group')], ensure_ascii=False)
        text = message.text.strip()
        chosen = None
        direct_text = text
        with self.lock:
            previous = self.db.execute('SELECT project_id,state FROM received WHERE id=?', (message.id,)).fetchone()
            if previous:
                return  # Routing/unknown receipt never implies safe replay.
            if text.startswith(('批准 ', '拒绝 ')):
                token = text.split(maxsplit=1)[1]
                matches = [m for m in eligible if token in m.receive.__self__.tokens]
                if len(matches) == 1:
                    chosen = matches[0]
            explicit = None
            selection_only = False
            if text.startswith('切换项目 '):
                explicit, selection_only = text[len('切换项目 '):].strip(), True
            elif text.startswith('项目 '):
                parts = text.split(maxsplit=2)
                explicit = parts[1] if len(parts) > 1 else ''
                direct_text = parts[2] if len(parts) > 2 else ''
                selection_only = not direct_text
            if explicit is not None:
                candidates = [m for m in eligible if m.project_id == explicit or
                    self.projects.opened.get(m.project_id) is not None and self.projects.opened[m.project_id].identity.name == explicit]
                if len(candidates) == 1:
                    chosen = candidates[0]
                    if selection_only:
                        with self.db:
                            self.db.execute('INSERT OR REPLACE INTO selected VALUES(?,?)', (key, chosen.project_id))
            elif chosen is None:
                row = self.db.execute('SELECT project_id FROM selected WHERE identity=?', (key,)).fetchone()
                chosen = next((m for m in eligible if row and m.project_id == row[0]), None)
            with self.db:
                self.db.execute('INSERT INTO received VALUES(?,?,?)', (message.id, chosen.project_id if chosen else '', 'routed'))
        with self.projects.lock:
            listing = '\n'.join(c.identity.name + ' · ' + c.identity.project_id for c in self.projects.opened.values()
                                if c.identity.project_id in self.allowed())
        if text == '项目列表' or chosen is None:
            eligible[0].receive.__self__.reply(message, '请明确选择项目：切换项目 项目ID\n' + listing)
            return
        if selection_only:
            context = self.projects.opened.get(chosen.project_id)
            chosen.receive.__self__.reply(message, '已选择项目：' + context.identity.name + '；原项目任务继续运行')
            return
        outgoing = deepcopy(data)
        if direct_text != text:
            if self.kind == 'dingtalk':
                outgoing['text']['content'] = direct_text
            else:
                original = json.loads(outgoing['event']['message']['content'])['text']
                # Preserve the trusted @ mention required by the platform parser.
                prefix = ''.join(m.get('key', '') + ' ' for m in outgoing['event']['message'].get('mentions', []))
                outgoing['event']['message']['content'] = json.dumps(dict(text=prefix + direct_text), ensure_ascii=False)
        self._deliver(chosen, outgoing, bot_id)

    def _deliver(self, member, data, bot_id):
        if self.kind == 'dingtalk':
            member.receive(data)
        else:
            member.receive(data, bot_id)

    def begin_close(self):
        if self.transport:
            self.transport.begin_close()

    @property
    def idle(self):
        return self.transport is None or self.transport.idle

    def close(self):
        if not self.idle:
            raise RuntimeError('平台连接仍在收尾')
        if self.lease:
            self.lease.close()
        self.db.close()

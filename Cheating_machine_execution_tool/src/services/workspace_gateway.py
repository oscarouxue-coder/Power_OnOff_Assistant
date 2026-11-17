"""Project routing inside an existing signed instance connection; protocol v1 stays valid."""
import json
import sqlite3
import threading
import time

from src.models.remote_gateway import RemotePrincipal, allows, validate_request
from src.services.remote_instance_service import GatewayAgentBridge


class WorkspaceGatewayBridge:
    def __init__(self, workspace, identity, config, bridge_factory=GatewayAgentBridge):
        self.workspace, self.identity, self.config = workspace, identity, config
        self.bridge_factory = bridge_factory
        self.lock = threading.RLock()
        self.bridges, self.active = {}, set()
        self.enabled = True
        self.db = sqlite3.connect(str(identity.directory / 'workspace_routes.sqlite3'), check_same_thread=False)
        self.db.executescript('CREATE TABLE IF NOT EXISTS selections(principal TEXT PRIMARY KEY,project_id TEXT);'
            'CREATE TABLE IF NOT EXISTS routes(request_id TEXT PRIMARY KEY,digest TEXT,project_id TEXT,receipt TEXT);')
        self.db.commit()

    def attach(self, controller, context):
        identifier = context.identity.project_id
        with self.lock:
            if identifier not in self.workspace.remote_projects:
                return
            if identifier in self.bridges:
                self.bridges[identifier].set_enabled(True)
                return
            bridge = self.bridge_factory(controller.conversation, self.identity, self.config['scopes'],
                self.config['channel_ids'], self.config['capability_ids'], enabled=True,
                directory=context.history / 'relay', project_path=context.config_dir / 'test_project_config.ini')
            self.bridges[identifier] = bridge

    def receive(self, request):
        from src.models.remote_gateway import digest
        validate_request(request, self.identity.instance_id, self.identity.run_id, time.time())
        principal = RemotePrincipal.parse(request['principal'])
        if not self.enabled or not allows(self.config['scopes'], principal):
            raise ValueError('实例来源未授权')
        request_id, signature = request['request_id'], digest(request)
        text = request['text'].strip()
        with self.lock:
            row = self.db.execute('SELECT digest,project_id,receipt FROM routes WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row[0] != signature:
                    raise ValueError('原请求身份已存在且正文不同')
                bridge = self.bridges.get(row[1])
                if bridge:
                    receipt = bridge.export_receipts().get(request_id)
                    if receipt:
                        return receipt
                return json.loads(row[2])
            available = {key: value for key, value in self.bridges.items() if key in self.workspace.remote_projects}
            project = None
            selection_only = False
            forwarded = text
            if text.startswith('切换项目 '):
                project, selection_only = text[len('切换项目 '):].strip(), True
            elif text.startswith('项目 '):
                parts = text.split(maxsplit=2)
                project = parts[1] if len(parts) > 1 else ''
                forwarded = parts[2] if len(parts) > 2 else ''
                selection_only = not forwarded
            if project is not None and project not in available:
                matches = [key for key in available if self.workspace.projects.opened[key].identity.name == project]
                project = matches[0] if len(matches) == 1 else ''
            if project is None:
                selected = self.db.execute('SELECT project_id FROM selections WHERE principal=?', (principal.key,)).fetchone()
                project = selected[0] if selected else ''
            if selection_only and project in available:
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO selections VALUES(?,?)', (principal.key, project))
                notice = '已选择项目：' + self.workspace.projects.opened[project].identity.name
                receipt = dict(state='done', request_id=request_id, notice=notice, answer=notice)
            elif text == '项目列表' or project not in available:
                notice = '请先选择项目：切换项目 项目ID\n' + '\n'.join(
                    self.workspace.projects.opened[key].identity.name + ' · ' + key for key in available)
                receipt = dict(state='done', request_id=request_id, notice=notice, answer=notice)
            else:
                receipt = dict(state='unknown', request_id=request_id, notice='项目路由已持久化；接收结果待确认，不自动重发')
            with self.db:
                self.db.execute('INSERT INTO routes VALUES(?,?,?,?)', (request_id, signature, project,
                    json.dumps(receipt, ensure_ascii=False)))
        if receipt['state'] == 'unknown':
            # Child inbox validates the original signed request. Explicit routing text
            # is stripped only after validation by its configured text transform.
            bridge = available[project]
            bridge.project_text = lambda value: value.split(maxsplit=2)[2] if value.startswith('项目 ') and len(value.split(maxsplit=2)) == 3 else value
            receipt = bridge.receive(request)
            with self.lock, self.db:
                self.db.execute('UPDATE routes SET receipt=? WHERE request_id=?', (json.dumps(receipt, ensure_ascii=False), request_id))
        return receipt

    def process_one(self):
        with self.lock:
            pending = [(key, value) for key, value in self.bridges.items()
                       if value.enabled and key in self.workspace.remote_projects]
        for key, bridge in pending:
            with self.lock:
                if self.bridges.get(key) is not bridge or not bridge.enabled:
                    continue
                self.active.add(key)
            try:
                result = bridge.process_one()
                if result:
                    return result
            finally:
                with self.lock:
                    self.active.discard(key)

    def export_receipts(self):
        with self.lock:
            result = {row[0]: json.loads(row[1]) for row in self.db.execute('SELECT request_id,receipt FROM routes')}
            for bridge in self.bridges.values():
                result.update(bridge.export_receipts())
        return result

    def prepare_project_close(self, identifier):
        with self.lock:
            bridge = self.bridges.get(identifier)
            if bridge:
                bridge.set_enabled(False)
            return identifier not in self.active

    def detach(self, identifier):
        with self.lock:
            if identifier in self.active:
                raise RuntimeError('项目网关请求仍在收尾')
            bridge = self.bridges.pop(identifier, None)
        if bridge:
            bridge.close()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        with self.lock:
            bridges = tuple(self.bridges.values())
        for bridge in bridges:
            bridge.set_enabled(enabled)

    def close(self):
        for identifier in tuple(self.bridges):
            self.detach(identifier)
        self.db.close()

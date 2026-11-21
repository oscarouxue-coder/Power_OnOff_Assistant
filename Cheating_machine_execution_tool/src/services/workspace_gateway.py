"""Project routing inside an existing signed instance connection; protocol v1 stays valid."""
from collections import Counter
import json
import sqlite3
import threading
import time
import uuid

from src.models.remote_gateway import RemotePrincipal, allows, validate_request
from src.services.remote_instance_service import GatewayAgentBridge


class WorkspaceGatewayBridge:
    def __init__(self, workspace, identity, config, bridge_factory=GatewayAgentBridge):
        self.workspace, self.identity, self.config = workspace, identity, config
        self.bridge_factory = bridge_factory
        self.lock = threading.RLock()
        self.bridges = {}
        self.project_epochs = {}
        self.control_projects = None  # Tk uses attached inboxes only.
        self.active = Counter()
        self.enabled = True
        self.db = sqlite3.connect(str(identity.directory / 'workspace_routes.sqlite3'), check_same_thread=False)
        self.db.executescript('CREATE TABLE IF NOT EXISTS selections(principal TEXT PRIMARY KEY,project_id TEXT);'
            'CREATE TABLE IF NOT EXISTS project_names(project_id TEXT PRIMARY KEY,name TEXT);'
            'CREATE TABLE IF NOT EXISTS routes(request_id TEXT PRIMARY KEY,digest TEXT,project_id TEXT,receipt TEXT);'
            'CREATE TABLE IF NOT EXISTS route_boots(run_id TEXT,request_id TEXT,PRIMARY KEY(run_id,request_id));')
        self.db.commit()

    def open_project_controls(self, context):
        """Publish project selection only. Business submission requires an attached inbox."""
        with self.lock:
            if self.control_projects is None:
                self.control_projects = set()
            self.control_projects.add(context.identity.project_id)
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO project_names VALUES(?,?)',
                                (context.identity.project_id, context.identity.name))

    def attach(self, controller, context):
        identifier = context.identity.project_id
        with self.lock:
            if identifier not in self.workspace.remote_projects:
                return
            if identifier in self.bridges:
                if not self.bridges[identifier].enabled:
                    self.project_epochs[identifier] = (uuid.uuid4().hex, time.time())
                self.bridges[identifier].set_enabled(True)
                return
            bridge = self.bridge_factory(controller.conversation, self.identity, self.config['scopes'],
                self.config['channel_ids'], self.config['capability_ids'], enabled=True,
                directory=context.history / 'relay', project_path=context.config_dir / 'test_project_config.ini')
            self.bridges[identifier] = bridge
            self.project_epochs[identifier] = (uuid.uuid4().hex, time.time())

    def project_catalog(self):
        with self.lock:
            known = {r['project_id']: r.get('name', '') for r in self.workspace.recent}
            known.update(self.db.execute('SELECT project_id,name FROM project_names'))
            result = []
            for key in sorted(self.workspace.remote_projects):
                context = self.workspace.projects.opened.get(key)
                bridge = self.bridges.get(key)
                name = context.identity.name if context else known.get(key)
                if not name:
                    continue
                ready = bridge and bridge.enabled and self.enabled
                check = getattr(getattr(bridge, 'owner', None), 'peer_ready', None)
                if ready and check is not None:
                    ready = check()
                state = ('ready' if ready else 'unready') if context else 'offline'
                epoch, since = self.project_epochs.get(key, ('', 0))
                result.append(dict(id=key, name=name, state=state, epoch=epoch, since=since))
            return result

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
                # An older database has only the digest. A validated, matching
                # request proves its boot without guessing from project or slot.
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO route_boots VALUES(?,?)', (request['run_id'], request_id))
                bridge = self.bridges.get(row[1])
                if bridge:
                    receipt = bridge.export_receipts().get(request_id)
                    if receipt:
                        return receipt
                return json.loads(row[2])
            available = {key: value for key, value in self.bridges.items() if key in self.workspace.remote_projects}
            if self.control_projects is not None:
                for key in sorted(self.control_projects.intersection(self.workspace.remote_projects)):
                    available.setdefault(key, None)
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
            if available.get(project) is not None and not available[project].enabled and text != '项目列表':
                raise ValueError('项目网关正在收尾，本次请求未转交')
            if selection_only and project in available:
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO selections VALUES(?,?)', (principal.key, project))
                notice = '已选择项目：' + self.workspace.projects.opened[project].identity.name
                receipt = dict(state='done', request_id=request_id, notice=notice, answer=notice)
            elif (self.control_projects is not None and not selection_only and text != '项目列表'
                    and available.get(project) is None):
                receipt = dict(state='rejected', request_id=request_id, notice='当前没有就绪的项目业务会话，本条业务消息已拒绝，未提交')
            elif text == '项目列表' or project not in available:
                notice = '请先选择项目：切换项目 项目ID\n' + '\n'.join(
                    self.workspace.projects.opened[key].identity.name + ' · ' + key
                    for key, child in available.items() if child is None or child.enabled)
                receipt = dict(state='done', request_id=request_id, notice=notice, answer=notice)
            else:
                receipt = dict(state='unknown', request_id=request_id, notice='项目路由已持久化；接收结果待确认，不自动重发')
            with self.db:
                self.db.execute('INSERT INTO routes VALUES(?,?,?,?)', (request_id, signature, project,
                    json.dumps(receipt, ensure_ascii=False)))
                self.db.execute('INSERT INTO route_boots VALUES(?,?)', (request['run_id'], request_id))
            forward = receipt['state'] == 'unknown'
            report_controls = self.control_projects is not None
            if forward:
                # Both the network receiver and the inbox worker may be using it.
                bridge = available[project]
                self.active[project] += 1
        if not forward:
            if report_controls:
                if receipt['state'] == 'rejected':
                    detail = '项目业务会话尚未就绪，已拒绝本条消息'
                elif selection_only and project in available:
                    detail = '已选择项目 ' + project
                else:
                    detail = '已返回本机授权的可用项目列表'
                self.workspace.emit('[统一接入] ' + detail + '；请求 ' + request_id[:8])
            return receipt
        try:
            # Child inbox validates the original signed request. Explicit routing text
            # is stripped only after validation by its configured text transform.
            bridge.project_text = lambda value: value.split(maxsplit=2)[2] if value.startswith('项目 ') and len(value.split(maxsplit=2)) == 3 else value
            receipt = bridge.receive(request)
            with self.lock, self.db:
                self.db.execute('UPDATE routes SET receipt=? WHERE request_id=?', (json.dumps(receipt, ensure_ascii=False), request_id))
            return receipt
        finally:
            self._finish_project_request(project)

    def _finish_project_request(self, identifier):
        with self.lock:
            self.active[identifier] -= 1
            if not self.active[identifier]:
                del self.active[identifier]

    def process_one(self):
        with self.lock:
            pending = [(key, value) for key, value in self.bridges.items()
                       if value.enabled and key in self.workspace.remote_projects]
        for key, bridge in pending:
            with self.lock:
                if self.bridges.get(key) is not bridge or not bridge.enabled:
                    continue
                self.active[key] += 1
            try:
                result = bridge.process_one()
                if result:
                    return result
            finally:
                self._finish_project_request(key)

    def export_receipts(self):
        with self.lock:
            rows = self.db.execute('SELECT routes.request_id,routes.receipt FROM route_boots '
                'JOIN routes USING(request_id) WHERE route_boots.run_id=?', (self.identity.run_id,))
            result = {request_id: json.loads(receipt) for request_id, receipt in rows}
            for bridge in self.bridges.values():
                result.update(bridge.export_receipts())
        return result

    def prepare_project_close(self, identifier):
        with self.lock:
            if self.control_projects is not None:
                self.control_projects.discard(identifier)
            bridge = self.bridges.get(identifier)
            if bridge:
                bridge.set_enabled(False)
            return identifier not in self.active

    def detach(self, identifier):
        with self.lock:
            if identifier in self.active:
                raise RuntimeError('项目网关请求仍在收尾')
            if self.control_projects is not None:
                self.control_projects.discard(identifier)
            bridge = self.bridges.pop(identifier, None)
            self.project_epochs.pop(identifier, None)
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

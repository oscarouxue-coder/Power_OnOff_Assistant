"""Member-scoped project discovery, durable message claims and direct delivery."""
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time
import uuid

from src.models.remote_gateway import RemotePrincipal, allows, canonical, digest, identifier


class ProjectPeerRouter:
    def __init__(self, identity, peers, bridge, scopes, emit):
        self.identity, self.peers, self.bridge = identity, tuple(peers), bridge
        self.scopes, self.emit = scopes, emit
        self.local = identity.instance_id
        self.call_peer = None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(identity.directory / 'project_peers.sqlite3'), check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS selections(member TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS claims(message TEXT PRIMARY KEY, fingerprint TEXT);
            CREATE TABLE IF NOT EXISTS catalogs(member TEXT, peer TEXT, value TEXT, PRIMARY KEY(member,peer));
            CREATE TABLE IF NOT EXISTS departures(peer TEXT PRIMARY KEY, run TEXT);
            CREATE TABLE IF NOT EXISTS presence(peer TEXT PRIMARY KEY, run TEXT, projects TEXT, scopes TEXT);
            CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY, member TEXT, project TEXT, name TEXT, run TEXT);
            CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, receipt TEXT);
        ''')
        # An offline acknowledgement from a previous local boot cannot establish
        # which messages an absent peer accepted while this node was stopped.
        with self.db:
            if 'observed' not in {r[1] for r in self.db.execute('PRAGMA table_info(presence)')}:
                self.db.execute('ALTER TABLE presence ADD COLUMN observed REAL DEFAULT 0')
            self.db.execute('DELETE FROM departures')

    def rpc(self, sender, packet):
        op = packet['op']
        if op == 'merge_history':
            with self.lock, self.db:
                self.db.executemany('INSERT OR IGNORE INTO claims VALUES(?,?)', packet['claims'])
                for member, encoded in packet['selections']:
                    self._remember(member, json.loads(encoded))
            return True
        if op == 'presence':
            with self.lock, self.db:
                self.db.execute('INSERT OR REPLACE INTO presence VALUES(?,?,?,?,?)',
                    (sender, identifier(packet['run']), canonical(packet['projects']), canonical(packet['scopes']), time.time()))
                self.db.execute('DELETE FROM departures WHERE peer=?', (sender,))
            return True
        if op == 'depart':
            with self.lock, self.db:
                self.db.execute('INSERT OR REPLACE INTO departures VALUES(?,?)', (sender, identifier(packet['run'])))
            return True
        principal = RemotePrincipal.parse(packet['principal'])
        permitted = principal.chat_type == 'group' and allows(self.scopes, principal)
        if op == 'receipt':
            if not permitted:
                return ''
            request_id = identifier(packet['request_id'])
            with self.lock:
                row = self.db.execute('SELECT project,name,run,receipt FROM deliveries LEFT JOIN results USING(id) '
                    'WHERE id=? AND member=?', (request_id, canonical(asdict(principal)))).fetchone()
            if not row or row[0] not in self.bridge.workspace.remote_projects:
                return ''
            detail = row[3] or '已登记，业务结果待确认。'
            if row[2] != self.identity.run_id:
                detail = '上次启动留存的回执：' + detail
            return '项目 ' + row[1] + ' · 请求 ' + request_id + '\n' + detail
        if op == 'snapshot':
            with self.lock:
                row = self.db.execute('SELECT value FROM selections WHERE member=?', (principal.key,)).fetchone()
                claimed = self.db.execute('SELECT 1 FROM claims WHERE message=?', (packet['message'],)).fetchone()
            return dict(run=self.identity.run_id, authorized=permitted, projects=self.bridge.project_catalog() if permitted else [],
                        selection=json.loads(row[0]) if row else [], claimed=bool(claimed))
        if op == 'claim':
            with self.lock, self.db:
                return bool(self.db.execute('INSERT OR IGNORE INTO claims VALUES(?,?)',
                                            (packet['message'], packet['fingerprint'])).rowcount)
        if op == 'select':
            selection = packet['selection']
            with self.lock, self.db:
                self._remember(principal.key, selection)
            return True
        if op != 'deliver' or not permitted:
            return dict(notice='未找到可访问的目标项目，本次请求未执行。')
        project = identifier(packet['project'])
        request = packet['request']
        from src.models.remote_gateway import validate_request
        validate_request(request, self.local, self.identity.run_id, time.time())
        if request['principal'] != asdict(principal):
            raise ValueError('项目请求来源不一致')
        with self.bridge.lock:
            catalog = {item['id']: item for item in self.bridge.project_catalog()}
            target = catalog.get(project)
            if not target:
                return dict(notice='未找到可访问的目标项目，本次请求未执行。')
            if target['state'] != 'ready':
                return dict(notice=self._status(target))
            if target['epoch'] != packet['epoch'] or packet['event_time'] < target['since']:
                return dict(notice='项目 ' + target['name'] + ' 已重新开放，本次旧请求未执行。')
            with self.lock, self.db:
                fresh = self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)',
                    (request['request_id'], canonical(asdict(principal)), project, target['name'], self.identity.run_id))
            if not fresh.rowcount:
                return dict(notice='原请求已登记，请核对原回执。')
            # The explicit project ID is part of the durable request. Never read a member's
            # mutable selection again on the target side.
            receipt = self.bridge.receive(dict(request, text='项目 ' + project + ' ' + request['text']))
        self.emit('[项目路由] 项目 ' + project + ' 接收请求 ' + request['request_id'] + '，状态 ' + receipt['state'])
        return dict(notice='项目 ' + target['name'] + ' · ' +
                    (receipt.get('notice') or '已接收，请求 ' + request['request_id']))

    def _remember(self, member, selection):
        row = self.db.execute('SELECT value FROM selections WHERE member=?', (member,)).fetchone()
        if not row or selection > json.loads(row[0]):
            self.db.execute('INSERT OR REPLACE INTO selections VALUES(?,?)', (member, canonical(selection)))

    def announce_departure(self, peer):
        # Only certify departure after the peer has all missed decisions. A
        # failure halfway leaves it unable to mistake a partition for shutdown.
        for table, columns in (('claims', 'message,fingerprint'), ('selections', 'member,value')):
            cursor = 0
            while True:
                with self.lock:
                    rows = self.db.execute(f'SELECT rowid,{columns} FROM {table} WHERE rowid>? ORDER BY rowid LIMIT 128',
                                           (cursor,)).fetchall()
                if not rows:
                    break
                packet = dict(op='merge_history', claims=[], selections=[])
                packet[table] = [row[1:] for row in rows]
                self.call_peer(peer, packet)
                cursor = rows[-1][0]
        self.call_peer(peer, dict(op='presence', run=self.identity.run_id,
                                  projects=self.bridge.project_catalog(), scopes=self.scopes))
        self.call_peer(peer, dict(op='depart', run=self.identity.run_id))

    @staticmethod
    def _status(project):
        state = project['state']
        reason = {'offline': '当前离线，本次请求未执行。', 'unready': '已在线，业务服务尚未就绪，本次请求未执行。',
                  'unknown': '当前状态暂时无法确认，本次请求未转交。'}
        return '项目 ' + project['name'] + ' ' + reason[state]

    def _call(self, peer, packet):
        return self.rpc(self.local, packet) if peer == self.local else self.call_peer(peer, packet)

    def _snapshot(self, peer, principal, packet):
        try:
            value = self._call(peer, packet)
        except Exception as error:
            with self.lock:
                row = self.db.execute('SELECT value FROM catalogs WHERE member=? AND peer=?', (principal.key, peer)).fetchone()
                departure = self.db.execute('SELECT run FROM departures WHERE peer=?', (peer,)).fetchone()
                presence = self.db.execute('SELECT run,projects,scopes,observed FROM presence WHERE peer=?', (peer,)).fetchone()
            last = json.loads(row[0]) if row else {}
            if presence and presence[3] >= last.get('observed', 0):
                permitted = allows(json.loads(presence[2]), principal)
                last.update(run=presence[0], projects=json.loads(presence[1]) if permitted else [], authorized=permitted)
            offline = isinstance(error, ConnectionRefusedError) or (departure and departure[0] == last.get('run'))
            state = 'offline' if offline else 'unknown'
            return dict(projects=[dict(p, state=state) for p in last.get('projects', [])],
                        selection=last.get('selection', []), reachable=False, uncertain=state == 'unknown',
                        authorized=last.get('authorized', False),
                        selection_uncertain=not (departure and departure[0] == last.get('run')))
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO catalogs VALUES(?,?,?)',
                            (principal.key, peer, canonical(dict(value, observed=time.time()))))
            self.db.execute('DELETE FROM departures WHERE peer=? AND run!=?', (peer, value['run']))
        return dict(value, reachable=True, uncertain=False)

    def can_reply_to_member(self, principal):
        if allows(self.scopes, principal):
            return True
        packet = dict(op='snapshot', principal=asdict(principal), message='')
        return any(self._snapshot(peer, principal, packet).get('authorized') for peer in self.peers)

    def handle(self, principal, message_id, text, event_time=None):
        if principal.chat_type != 'group':
            return None
        event_time = time.time() if event_time is None else event_time
        member = asdict(principal)
        message = digest((principal.key, message_id))
        packet = dict(principal=member, message=message)
        nodes = sorted((self.local,) + self.peers)
        with ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
            values = pool.map(lambda peer: self._snapshot(peer, principal, dict(packet, op='snapshot')), nodes)
            snapshots = dict(zip(nodes, values))
        if not any(v.get('authorized') for v in snapshots.values()):
            return None
        if any(item.get('claimed') for item in snapshots.values()):
            return None
        active = [peer for peer in nodes if snapshots[peer]['reachable']]
        # All active recipients reserve in the same order before replying or forwarding.
        for peer in active:
            if not self._call(peer, dict(packet, op='claim', fingerprint=digest(text))):
                return None
        projects = [dict(project, peer=peer) for peer, value in snapshots.items() for project in value['projects']]
        selection = max((v['selection'] for v in snapshots.values()), default=[])
        uncertain = any(v['uncertain'] for v in snapshots.values())
        text = text.strip()
        if text.startswith('查询请求 '):
            try:
                query_id = identifier(text.split(maxsplit=1)[1])
            except ValueError:
                return '请填写原回复中的完整请求 ID。'
            for peer in active:
                receipt = self._call(peer, dict(packet, op='receipt', request_id=query_id))
                if receipt:
                    return receipt
            return '当前在线实例没有可供本成员查看的该请求回执。'
        choices = '\n'.join(p['name'] + ' · ' + p['id'] for p in projects if p['state'] in ('ready', 'unready'))
        if text == '项目列表':
            return '可访问项目：\n' + (choices or '暂无已确认在线的项目')
        explicit = text.startswith(('切换项目 ', '项目 '))
        expression = text.partition(' ')[2].strip() if explicit else text
        candidates = []
        for project in projects:
            for key in (project['id'], project['name']):
                if expression == key or expression.startswith(key + ' '):
                    candidates.append((len(key), project))
                    break
        if candidates:
            size = max(n for n, _ in candidates)
            matches = [p for n, p in candidates if n == size]
            if len(matches) != 1:
                return '项目名称或身份有重复，请核对目标：\n' + choices
            target = matches[0]
            question = expression[size:].strip()
            if uncertain and target['state'] == 'ready' and expression[:size] != target['id']:
                return '部分实例状态待确认，请用项目 ID 明确指定目标。\n' + choices
            selected = [int(event_time * 1_000_000_000), message, target['peer'], target['id']]
            for peer in active:
                self._call(peer, dict(packet, op='select', selection=selected))
        elif explicit or text.startswith('项目') or not selection:
            if uncertain:
                return '有实例状态暂时无法确认，请核对项目 ID。本次请求未转交。'
            return '请指定可访问的项目名称或 ID。\n' + choices
        else:
            if int(event_time * 1_000_000_000) < selection[0]:
                return '这条消息早于最近一次切换项目，请明确指定项目后重新发送。'
            target = next((p for p in projects if (p['peer'], p['id']) == tuple(selection[2:])), None)
            if not target:
                return '原项目当前不可访问，本次请求未执行。'
            if any(v.get('selection_uncertain') for v in snapshots.values()) and target['state'] == 'ready':
                return '成员最近的项目选择尚未同步，请明确指定项目名称或 ID。'
            question = text
        if target['state'] != 'ready':
            return self._status(target)
        if not question:
            return '已选择项目 ' + target['name']
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, message))
        now = time.time()
        request = dict(version=1, instance_id=target['peer'], run_id=snapshots[target['peer']]['run'],
                       request_id=request_id, message_id=message_id, principal=member, text=question,
                       created=now, expires=now + 60)
        self.emit('[项目路由] 转交项目 ' + target['id'] + '，请求 ' + request_id)
        try:
            return self._call(target['peer'], dict(packet, op='deliver', project=target['id'],
                              epoch=target['epoch'], event_time=event_time, request=request))['notice']
        except Exception:
            return '项目 ' + target['name'] + ' 接收状态待确认，请求 ' + request_id + '。'

    def deliveries(self):
        with self.lock:
            return self.db.execute('SELECT id,member,project,name FROM deliveries WHERE run=?',
                                   (self.identity.run_id,)).fetchall()

    def record_result(self, request_id, body):
        with self.lock, self.db:
            self.db.execute('INSERT INTO results VALUES(?,?) ON CONFLICT(id) DO UPDATE SET receipt=excluded.receipt '
                            'WHERE receipt!=excluded.receipt', (request_id, body))

    def close(self):
        self.db.close()


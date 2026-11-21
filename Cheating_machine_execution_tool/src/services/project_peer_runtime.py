"""Opt-in Qt peer mode. Only the owning project creates sessions and business jobs."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
import time

from src.core.project_peer_transport import ProjectPeerTransport
from src.models.remote_gateway import RemotePrincipal, allows, canonical, digest, identifier
from src.services.project_peer_router import ProjectPeerRouter
from src.services.remote_gateway_platforms import GatewayPlatforms
from src.services.remote_gateway_store import RemoteGatewayStore, validate_pairing_scopes
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.workspace_gateway import WorkspaceGatewayBridge


class PeerPlatforms(GatewayPlatforms):
    def __init__(self, store, configs, router, emit):
        super().__init__(store, configs, emit=emit)
        self.projects = router
        with store.lock, store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS intake(id TEXT PRIMARY KEY,principal TEXT,mid TEXT,text TEXT,state TEXT)')
            if 'created' not in {r[1] for r in store.db.execute('PRAGMA table_info(intake)')}:
                store.db.execute('ALTER TABLE intake ADD COLUMN created REAL')
            store.db.execute("UPDATE intake SET state='interrupted' WHERE state IN ('new','routing')")

    def receive_event(self, principal, message_id, text, created_ms):
        # Both SDK events carry the platform creation time in milliseconds.
        # A replay from a previous project opening must never start a new job.
        try:
            created = int(created_ms) / 1000
        except (TypeError, ValueError, OverflowError):
            created = 0
        self.receive(principal, message_id, text, created)

    def receive(self, principal, message_id, text, created=None):
        if self.stop.is_set() or principal.chat_type != 'group':
            return
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO intake VALUES(?,?,?,?,'new',?)",
                (digest((principal.key, message_id)), canonical(asdict(principal)), message_id, text,
                 time.time() if created is None else created))

    def collect_results(self):
        with self.store.lock, self.store.db:
            row = self.store.db.execute("SELECT id,principal,mid,text,created FROM intake WHERE state='new' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                self.store.db.execute("UPDATE intake SET state='routing' WHERE id=?", (row[0],))
        if row:
            key, source, mid, question, created = row
            principal = RemotePrincipal.parse(json.loads(source))
            try:
                if not created or not 0 < created <= time.time() + 5:
                    answer = '消息时间无法确认，本次请求未执行。'
                else:
                    answer = self.projects.handle(principal, mid, question, created)
            except Exception:
                answer = '访问状态暂时无法确认，请核对原请求。'
                self.emit('[项目路由] 实例通信中断，请求 ' + key[:12])
            with self.store.lock, self.store.db:
                if answer:
                    self._queue(key, principal, answer)
                    self.emit('[项目路由] ' + answer.split('\n')[0])
                self.store.db.execute("UPDATE intake SET state='done' WHERE id=?", (key,))
        self.projects.bridge.process_one()
        receipts = self.projects.bridge.export_receipts()
        for request_id, member, project, name in self.projects.deliveries():
            receipt = receipts.get(request_id, {})
            principal = RemotePrincipal.parse(json.loads(member))
            if not allows(self.projects.scopes, principal) or project not in self.projects.bridge.workspace.remote_projects:
                continue
            body = receipt.get('answer') or ''
            if receipt.get('jobs'):
                body += '\n' + canonical(receipt['jobs'])
            if not body and (receipt.get('state') in ('unknown', 'rejected', 'interrupted')
                             or receipt.get('submitted') is False):
                body = receipt.get('notice', '')
            if body:
                self.projects.record_result(request_id, body)
                self._queue(digest((request_id, body)), principal, f'项目 {name} · 请求 {request_id}\n{body}', project)

    def may_send(self, principal, target):
        if target:
            return allows(self.projects.scopes, principal) and target in self.projects.bridge.workspace.remote_projects
        return self.projects.can_reply_to_member(principal)


class ProjectPeerRuntime:
    mode = 'project_peers'

    def __init__(self, workspace, path):
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        validate_pairing_scopes(value['scopes'])
        channels, capabilities = value['channel_ids'], value['capability_ids']
        if (not isinstance(channels, list) or not channels or any(type(v) is not int or not 1 <= v <= 16 for v in channels)
                or not isinstance(capabilities, list) or not capabilities or
                any(not isinstance(v, str) or not v.strip() for v in capabilities)):
            raise ValueError('须明确本机允许的通道和能力')
        if type(value['vpn']) is not bool or not isinstance(value['platforms'], list) or not value['platforms']:
            raise ValueError('请核对 VPN 和接入平台')
        if type(value['port']) is not int or not 1 <= value['port'] <= 65535:
            raise ValueError('请核对本机监听端口')
        if any(p not in ('dingtalk', 'feishu') for p in value['platforms']):
            raise ValueError('平台须为钉钉或飞书')
        peers = {}
        for item in value['peers']:
            peer_id = identifier(item['instance_id'])
            key = os.environ.get(item['key_env'], '')
            if peer_id in peers or len(key) < 32 or any(p['key'] == key for p in peers.values()):
                raise ValueError('须为每个可信对端配置独立的至少32字符密钥')
            tls = item.get('tls', False)
            if type(tls) is not bool or type(item['port']) is not int or not 1 <= item['port'] <= 65535:
                raise ValueError('对端端口或 TLS 选项无效')
            peers[peer_id] = dict(host=item['host'], port=item['port'], key=key, tls=tls)
        configs = {}
        for platform in value['platforms']:
            cfg = workspace.platform_config(platform).load()
            if cfg.get('enabled') or not cfg.get('corp') or not cfg.get('group'):
                raise ValueError('请先保存机器人群绑定并停用直接接入')
            configs[platform] = dict(cfg, enabled=True, group_enabled=True, p2p_enabled=False)
        for scope in value['scopes']:
            cfg = configs.get(scope['platform'], {})
            robot_key = 'app_id' if scope['platform'] == 'feishu' else 'robot_code'
            if (scope['chat_type'] != 'group' or scope['robot'] != cfg.get(robot_key)
                    or scope['chat'] != cfg.get('group') or scope['corp'] != cfg.get('corp')):
                raise ValueError('项目允许范围须对应本机已绑定的机器人、企业和群')
        self.identity = RemoteInstanceIdentity(workspace.source_root, slot=value.get('slot', 1))
        self.bridge = self.router = self.transport = self.platforms = self.store = None
        self.shutdown_thread = None
        self.stop_presence = threading.Event()
        self.announcer = None
        self.started = False
        self.emit = workspace.emit
        self.client = None
        try:
            if identifier(value['instance_id']) != self.identity.instance_id or self.identity.instance_id in peers:
                raise ValueError('配置的本机/对端 ID 与本机槽位不符')
            self.bridge = WorkspaceGatewayBridge(workspace, self.identity, value)
            self.router = ProjectPeerRouter(self.identity, peers, self.bridge, value['scopes'], self.emit)
            self.transport = ProjectPeerTransport(self.identity.instance_id, peers, (value['host'], value['port']),
                vpn=value['vpn'], dispatch=self.router.rpc, certificate=value.get('certificate'), private_key=value.get('private_key'))
            self.router.call_peer = self.transport.call
            self.store = RemoteGatewayStore(self.identity.directory / 'peer_platform')
            self.platforms = PeerPlatforms(self.store, configs, self.router, self.emit)
            self.transport.start()
            self.platforms.start()
            self.started = True
            self.announcer = threading.Thread(target=self._announce, name='project-peer-directory', daemon=True)
            self.announcer.start()
            self.emit('[项目路由] 已启动，实例 ' + self.identity.instance_id)
        except BaseException:
            self.close()
            raise

    def _announce(self):
        while not self.stop_presence.is_set():
            packet = dict(op='presence', run=self.identity.run_id,
                          projects=self.bridge.project_catalog(), scopes=self.router.scopes)
            for peer in self.router.peers:
                if self.stop_presence.is_set():
                    break
                try:
                    self.transport.call(peer, packet)
                except Exception:
                    continue
            self.stop_presence.wait(5)

    def _shutdown(self):
        self.stop_presence.set()
        if self.announcer and self.announcer.ident is not None:
            self.announcer.join()
        if self.platforms:
            self.platforms.stop.set()
            self.platforms.close()
            # Queued network calls and platform callbacks still own the stores.
            if self.platforms.worker and self.platforms.worker.ident is not None:
                self.platforms.worker.join()
            for transport in self.platforms.transports:
                while not transport.idle:
                    threading.Event().wait(.1)
            for lease in self.platforms.leases:
                lease.close()
            self.platforms.leases.clear()
        if self.transport:
            self.transport.close()
            if self.router and self.started:
                for peer in self.router.peers:
                    try:
                        self.router.announce_departure(peer)
                    except Exception:
                        self.emit('[项目路由] 对端未确认实例退出 ' + peer)

    def begin_close(self):
        if self.shutdown_thread is None:
            if self.bridge:
                self.bridge.set_enabled(False)
            self.shutdown_thread = threading.Thread(target=self._shutdown, name='project-peers-close', daemon=True)
            self.shutdown_thread.start()

    @property
    def idle(self):
        return self.shutdown_thread is None or not self.shutdown_thread.is_alive()

    def close(self):
        self.begin_close()
        self.shutdown_thread.join()
        if self.bridge:
            self.bridge.close()
        if self.router:
            self.router.close()
        if self.store:
            self.store.close()
        self.identity.close()


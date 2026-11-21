"""Two independent inboxes and authenticated loopback peers; no external traffic."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import secrets
import json
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from src.core.project_peer_transport import ProjectPeerTransport
from src.models.remote_gateway import RemotePrincipal
from src.services.project_peer_router import ProjectPeerRouter
from src.services.project_peer_runtime import PeerPlatforms
from src.services.remote_gateway_store import RemoteGatewayStore
from src.services.workspace_gateway import WorkspaceGatewayBridge


class VersionInbox:
    def __init__(self, conversation, identity, scopes, channels, caps, **options):
        self.name = conversation
        self.enabled = True
        self.queue = []
        self.jobs = {}
        self.sessions = []

    def receive(self, request):
        self.queue.append(request)
        return dict(state='received', request_id=request['request_id'])

    def process_one(self):
        if self.queue:
            req = self.queue.pop(0)
            self.sessions.append(self.project_text(req['text']))
            self.jobs[req['request_id']] = dict(state='submitted', answer='版本 ' + self.name)
            return True

    def export_receipts(self):
        return self.jobs.copy()

    def set_enabled(self, enabled):
        self.enabled = enabled

    def close(self):
        self.enabled = False


class ProjectPeerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        identities = []
        self.projects = []
        self.routers = []
        self.transports = []
        self.platforms = []
        self.sent = []
        self.principal = RemotePrincipal('feishu', 'bot', 'corp', 'group', 'group', 'alice')
        scopes = [dict(platform='feishu', robot='bot', corp='corp', chat_type='group', chat='group', members=['alice', 'bob'])]
        key = secrets.token_hex(32)
        for name in ('A', 'B'):
            directory = root / name
            directory.mkdir()
            identities.append(SimpleNamespace(directory=directory, instance_id=str(uuid.uuid4()), run_id=str(uuid.uuid4())))
        for index, identity in enumerate(identities):
            name = '项目' + ('A', 'B')[index]
            project_id = str(uuid.uuid4())
            self.projects.append(project_id)
            ctx = SimpleNamespace(identity=SimpleNamespace(project_id=project_id, name=name),
                                  config_dir=root, history=root)
            work = SimpleNamespace(remote_projects={project_id}, projects=SimpleNamespace(opened={project_id: ctx}),
                                   recent=[dict(project_id=project_id, name=name)], emit=lambda msg: None)
            bridge = WorkspaceGatewayBridge(work, identity, dict(scopes=scopes, channel_ids=[1],
                                            capability_ids=['device.version']), bridge_factory=VersionInbox)
            self.addCleanup(bridge.close)
            bridge.attach(SimpleNamespace(conversation=name), ctx)
            other = identities[1 - index].instance_id
            peers = {other: dict(host='127.0.0.1', port=0, key=key)}
            router = ProjectPeerRouter(identity, peers, bridge, scopes, work.emit)
            self.addCleanup(router.close)
            transport = ProjectPeerTransport(identity.instance_id, peers, ('127.0.0.1', 0), vpn=False, dispatch=router.rpc)
            transport.start()
            self.addCleanup(transport.close)
            router.call_peer = transport.call
            self.routers.append(router)
            self.transports.append(transport)
            store = RemoteGatewayStore(identity.directory / 'platform')
            self.addCleanup(store.close)
            platform = PeerPlatforms(store, {}, router, work.emit)
            platform.senders = {'feishu': lambda member, msg, _: self.sent.append((member.member, msg))}
            self.platforms.append(platform)
        for index, transport in enumerate(self.transports):
            other = self.transports[1 - index]
            transport.peers[other.local]['port'] = other.port

    def dispatch(self, index, mid, text, member='alice'):
        self.platforms[index].receive(replace(self.principal, member=member), mid, text)
        for platform in reversed(self.platforms):
            platform.collect_results()
            platform.send_one()

    def test_platform_received_on_b_only_a_executes_once_and_returns_version(self):
        self.dispatch(1, 'msg-1', '项目A 查版本')
        self.dispatch(0, 'msg-1', '项目A 查版本')
        a, b = [router.bridge.bridges[key] for router, key in zip(self.routers, self.projects)]
        self.assertEqual(a.sessions, ['查版本'])
        self.assertEqual(b.sessions, [])
        self.assertEqual(sum('版本 项目A' in msg for _, msg in self.sent), 1)
        self.dispatch(0, 'msg-2', '接着查')
        self.dispatch(1, 'bob-1', '项目B 查自己的版本', 'bob')
        self.dispatch(1, 'msg-3', '我的后续问题')
        self.assertEqual(a.sessions, ['查版本', '接着查', '我的后续问题'])
        self.assertEqual(b.sessions, ['查自己的版本'])

    def test_one_instance_hosts_multiple_projects_with_overlapping_names(self):
        bridge = self.routers[0].bridge
        original = bridge.workspace.projects.opened[self.projects[0]]
        second = str(uuid.uuid4())
        context = SimpleNamespace(identity=SimpleNamespace(project_id=second, name='项目A 二期'),
                                  config_dir=original.config_dir, history=original.history)
        bridge.workspace.projects.opened[second] = context
        bridge.workspace.remote_projects.add(second)
        bridge.attach(SimpleNamespace(conversation='项目A 二期'), context)
        self.dispatch(1, 'phase2', '项目A 二期 查版本')
        self.dispatch(0, 'follow-phase2', '继续核对')
        answer = self.routers[1].handle(self.principal, 'delayed', '继续之前的问题', event_time=1)
        self.assertIn('早于最近一次切换项目', answer)
        self.assertEqual(bridge.bridges[second].sessions, ['查版本', '继续核对'])
        self.assertFalse(bridge.bridges[self.projects[0]].sessions)

    def test_closed_offline_reopened_never_replays(self):
        self.dispatch(1, 'select', '项目A')
        a = self.routers[0].bridge
        key = self.projects[0]
        ctx = a.workspace.projects.opened.pop(key)
        a.detach(key)
        self.dispatch(1, 'offline', '查版本')
        self.assertEqual(sum('当前离线' in msg for _, msg in self.sent), 1)
        a.workspace.projects.opened[key] = ctx
        a.attach(SimpleNamespace(conversation='项目A'), ctx)
        self.dispatch(0, 'offline', '查版本')
        self.assertFalse(a.bridges[key].sessions)
        self.routers[1].rpc(self.routers[0].local, dict(op='depart', run=self.routers[0].identity.run_id))
        self.transports[0].close()
        self.dispatch(1, 'exit', '项目A 查版本')
        self.assertIn('当前离线', self.sent[-1][1])

    def test_collision_permission_and_unready(self):
        a, b = self.routers
        b.bridge.workspace.projects.opened[self.projects[1]].identity.name = '项目A'
        self.assertIn('重复', b.handle(self.principal, 'dupe', '项目A 查询'))
        self.assertIsNone(b.handle(replace(self.principal, member='unapproved'), 'denied', '项目A 查询'))
        a.bridge.bridges[self.projects[0]].set_enabled(False)
        self.assertIn('尚未就绪', b.handle(self.principal, 'unready', '项目 ' + self.projects[0] + ' 查版本'))
        a.bridge.workspace.remote_projects.clear()
        msg = b.handle(self.principal, 'revoked', '项目 ' + self.projects[0] + ' 查版本')
        self.assertNotIn(self.projects[0], msg)

    def test_lost_receipt_and_concurrent_duplicate(self):
        a, b = self.routers
        original = b.call_peer
        def lose_reply(peer, packet):
            result = original(peer, packet)
            if packet['op'] == 'deliver':
                raise TimeoutError('simulated receipt loss')
            return result
        with patch.object(b, 'call_peer', side_effect=lose_reply):
            self.assertIn('待确认', b.handle(self.principal, 'lost', '项目A 查版本'))
        self.assertIsNone(a.handle(self.principal, 'lost', '项目A 查版本'))
        start = threading.Barrier(2)
        def submit(router):
            start.wait(2)
            return router.handle(self.principal, 'duplicate', '项目A 再查')
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(submit, (a, b)))
        self.assertEqual(sum(reply is not None for reply in replies), 1)
        self.assertEqual(len(a.bridge.bridges[self.projects[0]].queue), 2)

    def test_close_between_snapshot_and_admission(self):
        a, b = self.routers
        original = b.call_peer
        def close_before_delivery(peer, packet):
            if packet['op'] == 'deliver':
                a.bridge.workspace.projects.opened.pop(self.projects[0])
                a.bridge.detach(self.projects[0])
            return original(peer, packet)
        with patch.object(b, 'call_peer', side_effect=close_before_delivery):
            self.assertIn('离线', b.handle(self.principal, 'race', '项目A 查版本'))
        self.assertFalse(a.deliveries())

    def test_old_platform_event_and_project_reopen_cannot_start_work(self):
        a, b = self.routers
        self.assertIn('旧请求未执行', b.handle(self.principal, 'old', '项目A 查版本', event_time=1))
        original = b.call_peer
        def reopen_before_delivery(peer, packet):
            if packet['op'] == 'deliver':
                project = self.projects[0]
                context = a.bridge.workspace.projects.opened[project]
                a.bridge.detach(project)
                a.bridge.attach(SimpleNamespace(conversation='项目A'), context)
            return original(peer, packet)
        with patch.object(b, 'call_peer', side_effect=reopen_before_delivery):
            self.assertIn('旧请求未执行', b.handle(self.principal, 'replaced', '项目A 查版本'))
        self.assertFalse(a.deliveries())

    def test_receiver_forwards_when_only_target_grants_member(self):
        self.routers[1].scopes = []
        self.dispatch(1, 'granted-at-owner', '项目A 查版本')
        self.assertEqual(self.routers[0].bridge.bridges[self.projects[0]].sessions, ['查版本'])
        self.assertTrue(any('版本 项目A' in msg for _, msg in self.sent))
        self.routers[0].announce_departure(self.routers[1].local)
        self.transports[0].close()
        self.dispatch(1, 'permitted-offline', '项目A 查版本')
        self.assertIn('当前离线', self.sent[-1][1])

    def test_network_timeout_is_not_proof_of_project_shutdown(self):
        a, b = self.routers
        self.assertIn('已选择项目', b.handle(self.principal, 'select', '项目A'))
        with patch.object(b, 'call_peer', side_effect=TimeoutError()):
            self.assertIn('暂时无法确认', b.handle(self.principal, 'timeout', '查版本'))
        self.assertFalse(a.deliveries())

    def test_receipt_follows_request_after_switch_and_checks_member(self):
        self.dispatch(1, 'business', '项目A 查版本')
        request_id = self.routers[0].deliveries()[0][0]
        self.dispatch(1, 'switch', '项目B')
        lookup = '查询请求 ' + request_id
        self.assertIn('版本 项目A', self.routers[1].handle(self.principal, 'lookup', lookup))
        self.assertNotIn('项目A', self.routers[1].handle(replace(self.principal, member='bob'), 'other', lookup))
        self.assertEqual(len(self.routers[0].deliveries()), 1)

    def test_untrusted_peer_cannot_receive_message_body(self):
        a, b = self.transports
        b.peers[a.local]['key'] = 'wrong-secret-for-simulated-peer-only'
        with patch.object(a, 'dispatch') as dispatch:
            with self.assertRaisesRegex(ValueError, '认证失败'):
                b.call(a.local, dict(op='presence', projects=['private']))
            dispatch.assert_not_called()

    def test_platform_mentions_require_matching_group_and_original_event_time(self):
        receiver = self.platforms[1]
        receiver.configs = {'feishu': dict(app_id='bot', group_enabled=True, enabled=True,
                                            corp='corp', group='group'),
                            'dingtalk': dict(robot_code='dt', corp='corp', group='group', enabled=True)}
        message = dict(message_id='from-feishu', chat_id='group', chat_type='group', message_type='text',
                       content=json.dumps(dict(text='@bot 项目A 查版本')), create_time=str(int(time.time() * 1000)),
                       mentions=[dict(key='@bot', id=dict(open_id='open-bot'))])
        event = dict(header=dict(app_id='bot', tenant_key='corp', event_type='im.message.receive_v1'),
                     event=dict(sender=dict(sender_type='user', tenant_key='corp', sender_id=dict(open_id='alice')),
                                message=message))
        receiver.receive_feishu(event, 'open-bot')
        receiver.collect_results()
        self.platforms[0].collect_results()
        self.assertEqual(self.routers[0].bridge.bridges[self.projects[0]].sessions, ['查版本'])
        receiver.receive_dingtalk(dict(conversationType='2', isInAtList=True, msgtype='text', msgId='from-dt',
            conversationId='group', senderCorpId='corp', senderId='alice', robotCode='dt', createAt=1,
            text=dict(content='项目A 查版本')))
        for router in self.routers:
            router.scopes.append(dict(platform='dingtalk', robot='dt', corp='corp', chat_type='group',
                                      chat='group', members=['alice']))
        receiver.collect_results()
        self.assertTrue(any('旧请求未执行' in row[0] for row in receiver.store.db.execute('SELECT payload FROM replies')))
        self.assertEqual(len(self.routers[0].deliveries()), 1)


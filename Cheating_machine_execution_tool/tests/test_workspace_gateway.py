from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from src.models.remote_gateway import RemotePrincipal
from src.services.workspace_gateway import WorkspaceGatewayBridge


class FakeBridge:
    def __init__(self, conversation, identity, scopes, channels, capabilities, **kwargs):
        self.enabled = kwargs['enabled']
        self.received = []
        self.receipts = {}

    def receive(self, request):
        self.received.append(request)
        value = dict(state='received', request_id=request['request_id'])
        self.receipts[request['request_id']] = value
        return value

    def export_receipts(self):
        return dict(self.receipts)

    def set_enabled(self, value):
        self.enabled = value

    def process_one(self):
        return None

    def close(self):
        self.enabled = False


class WorkspaceGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = SimpleNamespace(directory=self.root, instance_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()))
        self.principal = RemotePrincipal('feishu', 'bot', 'corp', 'group', 'chat', 'member')
        scope = dict(platform='feishu', robot='bot', corp='corp', chat_type='group', chat='chat', members=['member'])
        contexts = {key: SimpleNamespace(identity=SimpleNamespace(project_id=key, name=key.upper()), history=self.root / key,
                    config_dir=self.root / key / 'config') for key in ('a', 'b')}
        self.workspace = SimpleNamespace(projects=SimpleNamespace(opened=contexts), remote_projects={'a', 'b'})
        self.bridge = WorkspaceGatewayBridge(self.workspace, self.identity,
            dict(scopes=[scope], channel_ids=[1], capability_ids=['device.version']), bridge_factory=FakeBridge)
        self.addCleanup(self.bridge.close)
        for context in contexts.values():
            self.bridge.attach(SimpleNamespace(conversation=object()), context)

    def request(self, text, identifier=None):
        now = time.time()
        return dict(version=1, request_id=identifier or str(uuid.uuid4()), message_id=str(uuid.uuid4()),
            instance_id=self.identity.instance_id, run_id=self.identity.run_id, principal=asdict(self.principal),
            text=text, created=now, expires=now + 60)

    def test_client_first_poll_sees_attached_project_and_start_failure_drains_worker(self):
        import os
        from contextlib import ExitStack
        from unittest.mock import Mock
        from src.core.remote_gateway_transport import GatewayInstanceClient
        from src.services.remote_gateway_runtime import RemoteGatewayRuntime
        from src.services.workspace_service import WorkspaceService

        for fail_network in (False, True):
            with self.subTest(fail_network=fail_network), ExitStack() as scope:
                scope.enter_context(patch.dict(os.environ, LINECHECK_DISABLE_CAPABILITIES='0'))
                root = self.root / str(fail_network)
                root.mkdir()
                service = WorkspaceService(self.root, directory=root / 'workspace')
                scope.callback(service.close)
                service.gateway_slot = 1
                service.gateway_error = ''
                context = self.workspace.projects.opened['a']
                service.remote_projects = {'a'}
                service.projects.opened['a'] = context
                scope.callback(service.projects.opened.clear)
                controller = SimpleNamespace(capabilities=Mock(), conversation=object())
                runtime = RemoteGatewayRuntime.__new__(RemoteGatewayRuntime)
                identity = SimpleNamespace(**vars(self.identity))
                identity.directory = root
                identity.close = Mock()
                runtime.identity = identity
                runtime.config = dict(self.bridge.config, url='simulated', credential='simulated')
                runtime.bridge = runtime.client = runtime.fence = None
                scope.enter_context(patch('src.services.remote_gateway_runtime.RemoteGatewayRuntime', return_value=runtime))
                scope.enter_context(patch('src.services.workspace_gateway.WorkspaceGatewayBridge',
                    side_effect=lambda *a: WorkspaceGatewayBridge(*a, bridge_factory=FakeBridge)))
                observed = []
                entered, finish = threading.Event(), threading.Event()

                def worker():
                    entered.set()
                    finish.wait(5)

                def network():
                    observed.append(runtime.bridge.receive(self.request('项目列表'))['answer'])

                scope.enter_context(patch.object(GatewayInstanceClient, '_worker', lambda _: worker()))
                scope.enter_context(patch.object(GatewayInstanceClient, '_network', lambda _: network()))
                start = threading.Thread.start

                def start_thread(thread):
                    if thread.name == 'relay-client':
                        self.assertTrue(entered.wait(2))
                        if fail_network:
                            raise RuntimeError('simulated network thread creation failure')
                        start(thread)
                        thread.join(2)
                        return
                    start(thread)

                scope.enter_context(patch.object(threading.Thread, 'start', start_thread))
                try:
                    service.register_controller(controller, context)
                    if fail_network:
                        self.assertTrue(service.gateway_error)
                        self.assertIs(service.gateway_runtime, runtime)
                        self.assertTrue(runtime.client.stop.is_set())
                        self.assertFalse(service.idle)
                        self.assertFalse(runtime.bridge.enabled)
                    else:
                        self.assertFalse(service.gateway_error)
                        self.assertIn('A · a', observed[0])
                finally:
                    finish.set()
                    if runtime.client and runtime.client.worker:
                        runtime.client.worker.join(3)
                    if service.gateway_runtime is None and runtime.bridge:
                        runtime.bridge.close()
                self.assertTrue(service.idle)
            identity.close.assert_called_once_with()

    def test_requires_explicit_project_before_forwarding(self):
        value = self.bridge.receive(self.request('查询版本'))
        self.assertEqual(value['state'], 'done')
        self.assertIn('选择项目', value['answer'])
        self.assertFalse(any(child.received for child in self.bridge.bridges.values()))

    def test_unready_receipt_is_not_replayed_after_project_controller_attaches(self):
        context = self.workspace.projects.opened['a']
        self.workspace.emit = lambda message: None
        self.bridge.detach('a')
        self.bridge.open_project_controls(context)
        request = self.request('项目 a 查询版本')
        rejected = self.bridge.receive(request)
        self.assertEqual(rejected['state'], 'rejected')
        self.assertEqual(self.bridge.export_receipts()[request['request_id']], rejected)
        self.bridge.attach(SimpleNamespace(conversation=object()), context)
        self.assertEqual(self.bridge.receive(request), rejected)
        ready = self.bridge.bridges['a']
        self.assertFalse(ready.received)
        second = self.request('项目 a 查询版本')
        self.assertEqual(self.bridge.receive(second)['state'], 'received')
        self.assertEqual(ready.received, [second])
        self.assertFalse(self.bridge.bridges['b'].received)

    def test_exports_only_proven_current_boot_receipts_and_keeps_legacy_rows(self):
        import json
        import sqlite3
        from src.models.remote_gateway import digest

        identity = SimpleNamespace(**vars(self.identity))
        identity.directory = self.root / 'old-slot'
        identity.directory.mkdir()
        database = identity.directory / 'workspace_routes.sqlite3'
        old = self.request('项目列表')
        known = self.request('项目列表')
        old['run_id'] = str(uuid.uuid4())
        def legacy_receipt(request):
            return dict(state='done', request_id=request['request_id'], answer='历史目录')

        with sqlite3.connect(str(database)) as db:
            db.execute('CREATE TABLE routes(request_id TEXT PRIMARY KEY,digest TEXT,project_id TEXT,receipt TEXT)')
            for request in (old, known):
                db.execute('INSERT INTO routes VALUES(?,?,?,?)', (request['request_id'], digest(request), '',
                    json.dumps(legacy_receipt(request))))
        db.close()
        self.workspace.emit = lambda _: None
        def open_bridge():
            bridge = WorkspaceGatewayBridge(self.workspace, identity, self.bridge.config)
            bridge.open_project_controls(self.workspace.projects.opened['a'])
            return bridge

        bridge = open_bridge()
        try:
            self.assertEqual(bridge.export_receipts(), {})
            self.assertEqual(bridge.receive(known), legacy_receipt(known))
            new = self.request('停止')
            rejected = bridge.receive(new)
            self.assertEqual(rejected['state'], 'rejected')
        finally:
            bridge.close()
        bridge = open_bridge()
        try:
            self.assertEqual(bridge.export_receipts(), {known['request_id']: legacy_receipt(known), new['request_id']: rejected})
        finally:
            bridge.close()
        identity.run_id = str(uuid.uuid4())
        bridge = open_bridge()
        try:
            self.assertEqual(bridge.export_receipts(), {})
            self.assertEqual(bridge.db.execute('SELECT count(*) FROM routes').fetchone()[0], 3)
        finally:
            bridge.close()

    def test_selection_and_explicit_prefix_keep_original_signed_request(self):
        self.bridge.receive(self.request('切换项目 a'))
        request = self.request('查询版本')
        self.bridge.receive(request)
        self.assertEqual(self.bridge.bridges['a'].received, [request])
        explicit = self.request('项目 b 查询通道1版本')
        self.bridge.receive(explicit)
        child = self.bridge.bridges['b']
        self.assertEqual(child.received, [explicit])
        self.assertEqual(child.project_text(explicit['text']), '查询通道1版本')

    def test_repeated_receipt_after_switch_does_not_move_or_reexecute_original(self):
        self.bridge.receive(self.request('切换项目 a'))
        request = self.request('查询版本')
        self.bridge.receive(request)
        self.bridge.receive(self.request('切换项目 b'))
        self.bridge.receive(request)
        self.assertEqual(len(self.bridge.bridges['a'].received), 1)
        self.assertEqual(len(self.bridge.bridges['b'].received), 0)

    def test_local_project_revocation_does_not_expand_to_another_project(self):
        self.bridge.receive(self.request('切换项目 a'))
        self.workspace.remote_projects.remove('a')
        receipt = self.bridge.receive(self.request('查询版本'))
        self.assertEqual(receipt['state'], 'done')
        self.assertFalse(any(child.received for child in self.bridge.bridges.values()))

    def test_other_principal_is_rejected_before_project_listing(self):
        request = self.request('项目列表')
        request['principal']['member'] = 'other'
        with self.assertRaises(ValueError):
            self.bridge.receive(request)

    def test_close_waits_for_receipt_after_agent_worker_finishes(self):
        from concurrent.futures import ThreadPoolExecutor

        child = self.bridge.bridges['a']
        receiving, processing = threading.Event(), threading.Event()
        finish_receive, finish_process = threading.Event(), threading.Event()
        original_receive = child.receive

        def receive(request):
            receiving.set()
            if not finish_receive.wait(5):
                raise TimeoutError('test did not release the incoming receipt')
            return original_receive(request)

        def process():
            processing.set()
            if not finish_process.wait(5):
                raise TimeoutError('test did not release the agent worker')

        request = self.request('项目 a 查询版本')
        with patch.object(child, 'receive', receive), patch.object(child, 'process_one', process), ThreadPoolExecutor(2) as workers:
            incoming = workers.submit(self.bridge.receive, request)
            try:
                self.assertTrue(receiving.wait(2))
                worker = workers.submit(self.bridge.process_one)
                self.assertTrue(processing.wait(2))
                self.assertFalse(self.bridge.prepare_project_close('a'))
                finish_process.set()
                worker.result(2)
                self.assertFalse(self.bridge.prepare_project_close('a'))
                with self.assertRaisesRegex(RuntimeError, '仍在收尾'):
                    self.bridge.detach('a')
                self.assertEqual(self.bridge.receive(self.request('项目 b 查询版本'))['state'], 'received')
                with self.assertRaisesRegex(ValueError, '未转交'):
                    self.bridge.receive(self.request('项目 a 查询版本'))
                listing = self.bridge.receive(self.request('项目列表'))['answer']
                self.assertIn('B · b', listing)
                self.assertNotIn('A · a', listing)
            finally:
                finish_process.set()
                finish_receive.set()
            receipt = incoming.result(2)
        self.assertEqual(child.received, [request])
        self.assertTrue(self.bridge.prepare_project_close('a'))
        self.bridge.detach('a')
        self.assertEqual(self.bridge.receive(request), receipt)
        self.assertIn('b', self.bridge.bridges)

    def test_failed_incoming_receipt_releases_only_its_own_project(self):
        child = self.bridge.bridges['a']
        request = self.request('项目 a 查询版本')
        with patch.object(child, 'receive', side_effect=OSError('synthetic store error')):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                self.bridge.receive(request)
        self.assertTrue(self.bridge.prepare_project_close('a'))
        self.bridge.detach('a')
        self.assertEqual(self.bridge.receive(request)['state'], 'unknown')
        self.assertFalse(self.bridge.bridges['b'].received)

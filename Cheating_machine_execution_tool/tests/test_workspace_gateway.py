from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
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

    def test_requires_explicit_project_before_forwarding(self):
        value = self.bridge.receive(self.request('查询版本'))
        self.assertEqual(value['state'], 'done')
        self.assertIn('选择项目', value['answer'])
        self.assertFalse(any(child.received for child in self.bridge.bridges.values()))

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

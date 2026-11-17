import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from src.services.workspace_platforms import WorkspacePlatformPool, PooledLease


class FakeTransport:
    starts = 0

    def __init__(self, *args):
        self.idle = False

    def start(self):
        type(self).starts += 1

    def begin_close(self):
        self.idle = True


class FakeRemote:
    def __init__(self):
        self.stop_event = threading.Event()
        self.binding_code = ''
        self.tokens = {}
        self.messages, self.replies = [], []
        self.config = dict(enabled=True, robot_code='bot', group='group', corp='corp')

    def receive(self, data, bot_id=''):
        self.messages.append(data)

    def reply(self, message, text):
        self.replies.append((message.id, text))

    def _allowed(self, message):
        return message.robot == 'client' and message.corp == 'corp'


def message(identifier, text):
    return dict(conversationType='2', isInAtList=True, msgtype='text', msgId=identifier,
                conversationId='group', senderCorpId='corp', senderId='member', robotCode='bot', text=dict(content=text))


class WorkspacePlatformsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        FakeTransport.starts = 0
        self.projects = SimpleNamespace(lock=threading.RLock(), opened={
            'a': SimpleNamespace(identity=SimpleNamespace(name='项目 A', project_id='a')),
            'b': SimpleNamespace(identity=SimpleNamespace(name='项目 B', project_id='b'))})
        self.allowed = {'a', 'b'}
        self.pool = WorkspacePlatformPool('dingtalk', self.temporary.name, self.projects,
            transport_factory=FakeTransport, lease_factory=PooledLease, allowed=lambda: self.allowed)
        self.addCleanup(self.close)
        self.a, self.b = FakeRemote(), FakeRemote()
        for key, remote in (('a', self.a), ('b', self.b)):
            self.pool.factory(key)('client', 'simulated-secret', remote.receive, lambda text: None).start()

    def close(self):
        self.pool.begin_close()
        self.pool.close()

    def test_two_projects_share_one_transport(self):
        self.assertEqual(FakeTransport.starts, 1)

    def test_no_project_selection_never_executes(self):
        self.pool.receive(message('1', '查询版本'))
        self.assertFalse(self.a.messages or self.b.messages)
        self.assertIn('选择项目', self.a.replies[0][1])

    def test_switch_routes_new_messages_without_replaying_old_message(self):
        for identifier, text in (('1', '切换项目 a'), ('2', '查询版本'), ('3', '切换项目 b'), ('4', '查询版本')):
            self.pool.receive(message(identifier, text))
        self.pool.receive(message('2', '查询版本'))
        self.assertEqual([m['msgId'] for m in self.a.messages], ['2'])
        self.assertEqual([m['msgId'] for m in self.b.messages], ['4'])

    def test_approval_after_switch_returns_to_original_project(self):
        self.a.tokens['TOKEN-A'] = dict(session='original')
        self.pool.receive(message('1', '切换项目 b'))
        self.pool.receive(message('2', '批准 TOKEN-A'))
        self.assertEqual(self.a.messages[0]['text']['content'], '批准 TOKEN-A')
        self.assertFalse(self.b.messages)

    def test_explicit_project_message_strips_only_routing_prefix(self):
        self.pool.receive(message('1', '项目 a 查询通道1版本'))
        self.assertEqual(self.a.messages[0]['text']['content'], '查询通道1版本')

    def test_removed_project_is_not_executed_or_listed(self):
        self.allowed.remove('a')
        self.pool.receive(message('1', '项目 a 查询版本'))
        self.assertFalse(self.a.messages or self.b.messages)
        self.assertNotIn('项目 A', self.b.replies[0][1])

    def test_untrusted_group_does_not_receive_project_listing(self):
        value = message('1', '项目列表')
        value['conversationId'] = 'other-group'
        self.pool.receive(value)
        self.assertFalse(self.a.messages or self.b.messages or self.a.replies or self.b.replies)

    def test_duplicate_names_require_explicit_id(self):
        self.projects.opened['b'].identity.name = '项目 A'
        self.pool.receive(message('1', '切换项目 项目 A'))
        self.assertFalse(self.a.messages or self.b.messages)
        self.assertIn('选择项目', self.a.replies[0][1])

    def test_feishu_direct_message_project_routing(self):
        pool = WorkspacePlatformPool('feishu', Path(self.temporary.name) / 'feishu', self.projects,
            transport_factory=FakeTransport, lease_factory=PooledLease, allowed=lambda: self.allowed)
        try:
            pool.factory('a')('client', 'secret', self.a.receive, lambda text: None).start()
            value = dict(header=dict(event_type='im.message.receive_v1', app_id='client', tenant_key='corp'),
                event=dict(sender=dict(sender_type='user', tenant_key='corp', sender_id=dict(open_id='member')),
                           message=dict(message_type='text', chat_type='p2p', message_id='fs1', chat_id='chat',
                                        content=json.dumps(dict(text='项目 a 查询版本')))))
            pool.receive(value, 'bot')
            self.assertEqual(json.loads(self.a.messages[0]['event']['message']['content'])['text'], '查询版本')
        finally:
            pool.begin_close()
            pool.close()


if __name__ == '__main__':
    unittest.main()

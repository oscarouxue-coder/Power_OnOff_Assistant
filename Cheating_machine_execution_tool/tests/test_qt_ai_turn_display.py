"""Attribution and local-identity contracts; no GUI, credentials or transport."""
import threading
import unittest
from types import SimpleNamespace

from src.models.qt_ai_chat import ChatActivityView, ChatMessageView, is_model_identity_question
from src.services.qt_ai_chat import QtAiChat, QtLocalConversation, _display_model
from src.utils.ai_redaction import DiagnosticRedactor


class TurnDisplayTests(unittest.TestCase):
    def test_identity_requires_a_single_supported_question(self):
        for text in ('你现在是什么模型？', '你是什么模型', '当前用的是什么模型?', 'Which model are you?'):
            self.assertTrue(is_model_identity_question(text), text)
        for text in ('哪个模型好', '你是什么模型？再检查网络', '比较模型', '说明“你是什么模型”是什么意思',
                     'What model are you using for firmware upgrades?', '你是什么模型？？'):
            self.assertFalse(is_model_identity_question(text), text)

    def test_only_a_displayable_model_id_is_returned(self):
        redactor = DiagnosticRedactor(('fixture-secret',))
        self.assertEqual(_display_model('org/model-4.1', redactor), 'org/model-4.1')
        for value in ('https://internal.test', '10.0.0.1', 'localhost:8080/model', 'fixture-secret', '<b>x</b>'):
            self.assertEqual(_display_model(value, redactor), '型号不可展示')

    def test_late_usage_cannot_replace_another_request_or_session(self):
        stop = threading.Event()
        receiver = SimpleNamespace(lock=threading.RLock(), redactor=DiagnosticRedactor(),
            running={'a': stop}, drafts={'a': {'reply_id': 'current'}}, reply_display={})
        snapshot = dict(source='api', total_tokens=0, input_tokens=0, output_tokens=0, identity={'capacity': 0})
        for session, token, reply in [('b', stop, 'current'), ('a', threading.Event(), 'current'), ('a', stop, 'old')]:
            QtLocalConversation.observe_reply_usage(receiver, session, token, reply, 'wrong', snapshot)
        self.assertFalse(receiver.reply_display)
        QtLocalConversation.observe_reply_usage(receiver, 'a', stop, 'current', 'selected', snapshot)
        text = receiver.reply_display['a'][1]
        self.assertIn('合计 0 Token', text)
        self.assertNotIn('%', text)
        stop.set()
        QtLocalConversation.observe_reply_usage(receiver, 'a', stop, 'current', 'late', snapshot)
        self.assertEqual(receiver.reply_display['a'][1], text)

    def test_ordinary_event_uses_real_receipts_and_leaves_identity_unassigned_before_reply(self):
        session = {'id': 'session-a'}
        user = ChatMessageView('user', 'question', '', 'text')
        old = ChatMessageView('assistant', 'old body', '', 'text', 'old-id', 'completed')
        activity = QtAiChat._ordinary_activity(session, None, False, True, True, (old, user), None)
        self.assertEqual((activity.source, activity.request_id), ('conversation', ''))
        self.assertIn('编号尚未分配', activity.status_message().text)
        draft = {'reply_id': 'real-id', 'text': 'partial'}
        activity = QtAiChat._ordinary_activity(session, draft, False, False, True, (user,), None)
        self.assertEqual((activity.source, activity.request_id, activity.state), ('model_reply', 'real-id', 'running'))
        self.assertNotIn('partial', activity.status_message().text)
        final = ChatMessageView('assistant', 'final', '', 'text', 'real-id', 'completed')
        activity = QtAiChat._ordinary_activity(session, None, False, False, True, (user, final), None)
        self.assertEqual((activity.request_id, activity.state), ('real-id', 'completed'))
        aborted = ChatActivityView('session-a', 'model_reply', 'cancel-id', 'cancelled')
        activity = QtAiChat._ordinary_activity(session, None, False, False, False, (user,), aborted)
        self.assertEqual(activity, aborted)
        identity = ChatMessageView('assistant', 'local identity', '', 'text')
        self.assertIsNone(QtAiChat._ordinary_activity(session, None, False, False, False, (old, user, identity), aborted))

    def test_only_queue_receipts_label_a_supplement(self):
        row = dict(role='user', kind='text', text='再查一次')
        self.assertEqual(QtAiChat._message_view(row, 'pc').text, row['text'])
        self.assertIn('已接收', QtAiChat._message_view(dict(row, diagnostic_supplement=True), 'pc').text)
        legacy = dict(role='system', kind='progress', text='已采用你的补充，调整后续诊断方向。')
        self.assertNotIn('已采用', QtAiChat._message_view(legacy, 'pc').text)
        supplement = dict(row, diagnostic_supplement=True)
        for receipt, label in ((('received', 'a', None), '已接收'), (('cancelled', 'a', None), '已取消，未派发'),
                               (('not_dispatched', 'a', None), '未派发'), (('unconfirmed', 'a', None), '派发未核实'),
                               (('confirmed', 'a', None), '派发未核实'), (('confirmed', None, 'request-a'), '派发未核实'),
                               (('confirmed', 'a', 'request-a'), '已带入下一次请求')):
            text = QtAiChat._message_view(supplement, 'pc', receipt).text
            self.assertIn(label, text)
            self.assertNotIn('已采纳', text)
            self.assertEqual('已带入下一次请求' in text, bool(receipt[1] and receipt[2]))

"""Attribution and local-identity contracts; no GUI, credentials or transport."""
import threading
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.models.qt_ai_chat import ChatActivityView, ChatMessageView, is_model_identity_question
from src.services.ai_store import DiagnosticStore
from src.services.qt_ai_chat import (QtAiChat, QtLocalConversation, _display_model,
                                     _saved_context_text, _saved_empty_cancel_activity)
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

    def test_saved_context_display_preserves_source_basis_and_unknowns(self):
        saved = dict(identity=dict(capacity=65536, profile='fixture-hidden'), state='completed', basis='reply',
                     source='api', input_tokens=12, output_tokens=3, total_tokens=15,
                     updated='2026-11-25T10:00:00+08:00')
        text = _saved_context_text(saved)
        self.assertIn('已保存历史用量（非当前请求）', text)
        self.assertIn('接口返回：输入 12，输出 3，合计 15 Token', text)
        self.assertIn('记录当时上限 65,536 Token', text)
        self.assertNotIn('fixture-hidden', text)
        estimate = _saved_context_text(dict(saved, source='estimate', identity=dict(capacity=0)))
        self.assertIn('UTF-8 字节估算', estimate)
        self.assertIn('合计 约 15 Token', estimate)
        self.assertIn('记录当时上限未知', estimate)
        self.assertIn('保存状态为取消，回复计数与该次状态的对应关系未核实',
                      _saved_context_text(dict(saved, state='cancelled')))
        self.assertIn('保存状态为失败，回复计数与该次状态的对应关系未核实',
                      _saved_context_text(dict(saved, state='failed')))
        incomplete = _saved_context_text(dict(saved, basis='input', source='estimate', state='requesting',
                                              output_tokens=None, total_tokens=12))
        self.assertIn('结果未核实', incomplete)
        self.assertIn('完整回复用量未知', incomplete)
        for value in (None, {}, dict(saved, total_tokens=16), dict(saved, input_tokens=True),
                      dict(saved, source='unknown'), dict(saved, output_tokens=None)):
            self.assertIn('已保存历史用量未知', _saved_context_text(value))

    def test_context_display_does_not_use_old_values_as_current_or_cross_session(self):
        stop = threading.Event()
        old = threading.Event()
        conversation = SimpleNamespace(lock=threading.RLock(), reply_display={}, running={})
        view = SimpleNamespace(cursor=None, _intent=None, selected='a', conversation=conversation)
        saved = dict(id='a', context_usage=dict(state='completed', basis='reply', source='api',
            input_tokens=12, output_tokens=3, total_tokens=15, identity=dict(capacity=0)))
        self.assertIn('合计 15', QtAiChat._context_text(view, saved))
        self.assertIn('历史用量未知', QtAiChat._context_text(view, dict(saved, id='b')))
        conversation.running['a'] = stop
        conversation.reply_display['a'] = (old, '旧答复用量')
        self.assertNotIn('15', QtAiChat._context_text(view, saved, True))
        self.assertNotIn('旧答复', QtAiChat._context_text(view, saved, True))
        conversation.reply_display['a'] = (stop, '当前可信用量')
        self.assertIn('当前答复请求记录', QtAiChat._context_text(view, saved, True))
        stop.set()
        self.assertIn('当前可信用量', QtAiChat._context_text(view, saved, True))
        conversation.running.clear()
        self.assertIn('非当前请求', QtAiChat._context_text(view, saved))
        view.cursor = 1
        self.assertEqual(QtAiChat._context_text(view, saved), '')

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

    def _cancel_store(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = self._open_cancel_store(temporary.name)
        for identifier, scope in (('a', 'general'), ('b', 'general'), ('c', 'pc')):
            store.create_chat(dict(id=identifier, created='2026-11-26T10:00:00+08:00',
                scope=scope, title=identifier, target_label='fixture', model='', status='等待',
                diagnosis_only=scope == 'pc'))
        return store, temporary.name

    def _open_cancel_store(self, directory):
        # No credentials, transport, real workspace, workers or Qt windows.
        store = DiagnosticStore(directory, cipher=SimpleNamespace())
        self.addCleanup(store.close)
        return store

    @staticmethod
    def _cancel_conversation(store):
        conversation = object.__new__(QtLocalConversation)
        conversation.store = store
        conversation.lock = threading.RLock()
        conversation.context = SimpleNamespace(run_id='fixture-run')
        conversation.drafts = {}
        conversation.running = {}
        conversation.executors = {}
        conversation.reply_display = {}
        conversation.aborted_reply_display = {}
        conversation.redactor = DiagnosticRedactor()
        conversation.notify = lambda _identifier: None
        warnings = []
        conversation.emit = warnings.append
        return conversation, warnings

    @staticmethod
    def _cancel_view(store, conversation, identifier):
        chat = object.__new__(QtAiChat)
        chat.store, chat.conversation, chat.selected = store, conversation, identifier
        chat.titles = SimpleNamespace(chat_entries=lambda rows: rows)
        chat.diagnostic = SimpleNamespace(redactor=conversation.redactor, monitor_status=lambda: None)
        chat.cursor, chat._intent, chat._route_errors, chat._identity_messages = None, None, {}, []
        return chat

    def test_empty_cancel_is_saved_outside_messages_and_reopened_with_original_id(self):
        store, directory = self._cancel_store()
        conversation, warnings = self._cancel_conversation(store)
        conversation.message('a', 'user', 'synthetic question')
        original_messages = store.chat_items('a')
        original_groups = store.chat_items('a', group=True)
        reply_id = conversation._begin_draft('a')
        stop = threading.Event()
        stop.set()
        conversation._abort_draft('a', 'cancelled')
        saved = store.chat('a')['last_empty_reply_cancel']
        self.assertEqual(saved, dict(session_id='a', user_message_id=1, reply_id=reply_id,
                                    state='cancelled', no_body=True))
        self.assertEqual(store.chat_items('a'), original_messages)
        self.assertEqual(store.chat_items('a', group=True), original_groups)
        self.assertFalse(warnings)
        # Late callbacks and a duplicate terminal attempt must not replace the saved receipt.
        conversation._draft('a', 'late', reply_id=reply_id, stop=stop)
        conversation._abort_draft('a', 'failed')
        self.assertEqual(store.chat('a')['last_empty_reply_cancel'], saved)
        self.assertEqual(store.chat_items('a'), original_messages)
        store.update_chat('a', status='已停止')
        conversation.message('a', 'system', 'synthetic cancellation', 'error')
        self.assertEqual(self._cancel_view(store, conversation, 'a').snapshot().activity.request_id, reply_id)
        store.close()

        reopened = self._open_cancel_store(directory)
        new_conversation, _ = self._cancel_conversation(reopened)
        chat = self._cancel_view(reopened, new_conversation, 'a')
        view = chat.snapshot()
        self.assertEqual((view.activity.session_id, view.activity.request_id, view.activity.state),
                         ('a', reply_id, 'cancelled'))
        self.assertIn('历史记录', view.activity.detail)
        self.assertFalse(view.running)
        self.assertFalse(any(m.role == 'assistant' or m.reply_id for m in view.messages))
        self.assertEqual(reopened.chat_items('a', group=True), original_groups)
        chat.selected = 'b'
        self.assertIsNone(chat.snapshot().activity)
        chat.selected = 'a'
        self.assertEqual(chat.snapshot().activity.request_id, reply_id)

    def test_saved_empty_cancel_never_labels_a_new_question_or_missing_id(self):
        store, _ = self._cancel_store()
        conversation, _ = self._cancel_conversation(store)
        conversation.message('a', 'user', 'same synthetic text')
        first = conversation._begin_draft('a')
        conversation._abort_draft('a', 'cancelled')
        record = store.chat('a')['last_empty_reply_cancel']
        chat = self._cancel_view(store, conversation, 'a')
        conversation.message('a', 'user', 'same synthetic text')
        conversation._abort_draft('a', 'cancelled')  # no assigned reply for the new question
        self.assertEqual(store.chat('a')['last_empty_reply_cancel'], record)
        self.assertIsNone(chat.snapshot().activity)
        second = conversation._begin_draft('a')
        self.assertNotEqual(first, second)
        conversation._abort_draft('a', 'cancelled')
        self.assertEqual(chat.snapshot().activity.request_id, second)
        newer = store.chat('a')['last_empty_reply_cancel']
        self.assertNotEqual(newer['user_message_id'], record['user_message_id'])
        self.assertEqual(newer['reply_id'], second)
        for invalid in (None, {}, dict(newer, session_id='b'), dict(newer, reply_id=''),
                        dict(newer, state='failed'), dict(newer, no_body=False),
                        dict(newer, user_message_id=True)):
            self.assertIsNone(_saved_empty_cancel_activity(dict(id='a', last_empty_reply_cancel=invalid),
                             (newer['user_message_id'], 'user')))
        self.assertIsNone(_saved_empty_cancel_activity(dict(id='a', last_empty_reply_cancel=newer),
                         (newer['user_message_id'], 'assistant')))

    def test_partial_reply_failure_and_nonordinary_cancel_keep_existing_semantics(self):
        store, _ = self._cancel_store()
        conversation, _ = self._cancel_conversation(store)
        for identifier in ('a', 'b', 'c'):
            conversation.message(identifier, 'user', 'synthetic')
        partial = conversation._begin_draft('a')
        conversation._draft('a', 'partial synthetic body')
        conversation._abort_draft('a', 'cancelled')
        assistant = store.chat_items('a')[-1]
        self.assertEqual((assistant['role'], assistant['reply_id'], assistant['stream_state']),
                         ('assistant', partial, 'cancelled'))
        self.assertIn('partial synthetic body', assistant['text'])
        self.assertNotIn('last_empty_reply_cancel', store.chat('a'))
        conversation._begin_draft('b')
        conversation._abort_draft('b', 'failed')
        conversation._begin_draft('c')
        conversation._abort_draft('c', 'cancelled')
        self.assertNotIn('last_empty_reply_cancel', store.chat('b'))
        self.assertNotIn('last_empty_reply_cancel', store.chat('c'))

    def test_empty_cancel_write_failure_retains_only_transient_terminal(self):
        store, directory = self._cancel_store()
        conversation, warnings = self._cancel_conversation(store)
        conversation.message('a', 'user', 'synthetic')
        reply_id = conversation._begin_draft('a')
        with patch.object(store, 'update_chat', side_effect=OSError('synthetic write failure')):
            conversation._abort_draft('a', 'cancelled')
        self.assertFalse(conversation.drafts)
        self.assertEqual(conversation.aborted_reply_display['a'].request_id, reply_id)
        self.assertEqual(len(warnings), 1)
        self.assertNotIn('last_empty_reply_cancel', store.chat('a'))
        conversation.message('b', 'user', 'synthetic')
        second = conversation._begin_draft('b')
        with patch.object(store, 'update_chat', side_effect=OSError('synthetic write failure')), \
                patch.object(conversation, 'emit', side_effect=OSError('synthetic log failure')):
            conversation._abort_draft('b', 'cancelled')
        self.assertFalse(conversation.drafts)
        self.assertEqual(conversation.aborted_reply_display['b'].request_id, second)
        self.assertNotIn('last_empty_reply_cancel', store.chat('b'))
        store.close()
        reopened = self._open_cancel_store(directory)
        new_conversation, _ = self._cancel_conversation(reopened)
        self.assertIsNone(self._cancel_view(reopened, new_conversation, 'a').snapshot().activity)

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

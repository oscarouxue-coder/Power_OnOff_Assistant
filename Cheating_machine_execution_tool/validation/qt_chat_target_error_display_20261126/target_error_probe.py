"""Display-only synthetic target error; no routing, model or device work."""
from unittest import TestCase

from src.models.qt_ai_chat import is_model_identity_question
from src.services.ai_record_titles import AiRecordTitles
import test_qt_ai_turn_display as fixtures


class TargetErrorDisplayProbe(TestCase):
    _cancel_store = fixtures.TurnDisplayTests._cancel_store
    _open_cancel_store = fixtures.TurnDisplayTests._open_cancel_store
    _cancel_conversation = staticmethod(fixtures.TurnDisplayTests._cancel_conversation)
    _cancel_view = staticmethod(fixtures.TurnDisplayTests._cancel_view)

    def test_existing_rejection_displays_exact_selected_label_without_clearing_or_rerouting(self):
        store, _ = self._cancel_store()
        conversation, _ = self._cancel_conversation(store)
        for identifier, number in (('channel-a', 1), ('channel-b', 2)):
            store.create_chat(dict(id=identifier, created='2026-11-26T12:00:00+08:00',
                title='同名通道会话', scope='device', target={'channel': number}, run_id='fixture-run',
                qt_channel_analysis=True, status='等待', model='', target_label='fixture'))
        conversation.collection_status = lambda _identifier: {'enabled': False, 'passive_serial': False}
        conversation.message('channel-a', 'user', '合成历史版本问题')
        conversation.message('channel-a', 'assistant', '合成历史版本回复')
        original = store.chat_items('channel-a')
        chat = self._cancel_view(store, conversation, 'channel-a')
        chat.titles = AiRecordTitles(store, lambda _line: None)
        reason = '当前会话与识别目标不一致或目标已变化，请明确切换目标'
        question = '你是谁?'
        self.assertFalse(is_model_identity_question(question))
        self.assertEqual(conversation.local_mode(store.chat('channel-a')), 'channel')
        # Import only the already received error, never produce it via routing.
        chat._route_errors['channel-a'] = (question, reason)
        rejected = chat.snapshot()
        self.assertEqual(rejected.latest_status.kind, 'error')
        self.assertIn('当前所选会话：通道1', rejected.latest_status.text)
        self.assertIn(reason, rejected.latest_status.text)
        self.assertIn('未自动切换会话', rejected.latest_status.text)
        self.assertEqual(rejected.retry_input, question)
        self.assertEqual(rejected.messages[-2].text, question)
        self.assertEqual(chat._route_errors['channel-a'], (question, reason))
        self.assertEqual(store.chat_items('channel-a'), original)
        self.assertEqual(rejected.selected, 'channel-a')

        chat.selected = 'channel-b'
        other = chat.snapshot()
        self.assertIsNone(other.latest_status)
        self.assertEqual(other.retry_input, '')
        chat.selected = 'channel-a'
        returning = chat.snapshot()
        self.assertEqual(returning.latest_status.text, rejected.latest_status.text)
        chat.cursor = 1
        older = chat.snapshot()
        self.assertIsNone(older.latest_status)
        chat.cursor = None

        # A different pre-existing failure retains exactly its former display.
        chat._route_errors['channel-a'] = (question, '合成其他失败')
        self.assertEqual(chat.snapshot().latest_status.text, '目标识别失败：合成其他失败')
        # Simulate the existing clearance after a later accepted request only;
        # do not call _send, _finish_intent, router or any model/transport.
        chat._route_errors.pop('channel-a')
        self.assertIsNone(chat.snapshot().latest_status)
        self.assertEqual(store.chat_items('channel-a'), original)


"""One local display projection check; no Qt window, service worker or external I/O."""
import unittest

from src.services.qt_ai_chat import CHAT_PAGE
from test_qt_ai_turn_display import TurnDisplayTests as Fixtures


class ReceiptPaginationProbe(unittest.TestCase):
    _cancel_store = Fixtures._cancel_store
    _open_cancel_store = Fixtures._open_cancel_store
    _cancel_conversation = staticmethod(Fixtures._cancel_conversation)
    _cancel_view = staticmethod(Fixtures._cancel_view)

    def test_saved_empty_cancel_is_current_page_only_after_real_store_reopen(self):
        store, directory = self._cancel_store()
        conversation, warnings = self._cancel_conversation(store)
        for index in range(CHAT_PAGE + 2):
            role = 'user' if index % 2 == 0 else 'assistant'
            conversation.message('a', role, f'合成历史行 {index}')
        question = '新的合成无正文取消问题'
        conversation.message('a', 'user', question)
        identifier = conversation._begin_draft('a')
        conversation._abort_draft('a', 'cancelled')
        store.update_chat('a', status='已停止')
        conversation.message('a', 'system', '合成取消', 'error')
        self.assertFalse(warnings)
        saved = store.chat('a')['last_empty_reply_cancel']
        original_messages = store.chat_items('a')
        store.close()

        reopened = self._open_cancel_store(directory)
        new_conversation, _ = self._cancel_conversation(reopened)
        chat = self._cancel_view(reopened, new_conversation, 'a')
        latest = chat.snapshot()
        self.assertFalse(new_conversation.aborted_reply_display)
        self.assertEqual(latest.activity.request_id, identifier)
        self.assertEqual(latest.activity.state, 'cancelled')
        self.assertTrue(any(row.text == question for row in latest.messages))
        self.assertIsNotNone(latest.next_cursor)

        chat.cursor = latest.next_cursor
        older = chat.snapshot()
        self.assertTrue(older.messages)
        self.assertTrue(any(row.text.startswith('合成历史行') for row in older.messages))
        self.assertFalse(any(row.text == question for row in older.messages))
        self.assertIsNone(older.activity)
        self.assertEqual(older.context, '')

        chat.cursor = None
        again = chat.snapshot()
        self.assertEqual((again.activity.session_id, again.activity.request_id, again.activity.state),
                         ('a', identifier, 'cancelled'))
        self.assertIn('历史记录', again.activity.detail)
        self.assertGreater(again.snapshot_generation, older.snapshot_generation)
        self.assertEqual(reopened.chat('a')['last_empty_reply_cancel'], saved)
        self.assertEqual(reopened.chat_items('a'), original_messages)


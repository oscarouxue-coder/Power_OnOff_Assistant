"""Handwritten passive samples, unrelated to any external application's output."""
from unittest import TestCase
from unittest.mock import patch

from src.models.qt_ai_chat import ChatMessageView
from src.services.qt_ai_chat import QtAiChat
from src.ui.qt.ai_chat_transcript import _MESSAGE_ROLE, _MESSAGE_START
import bubble_projection_probe as display


class PassiveFourStateSamplesProbe(TestCase):
    def test_four_handwritten_states_preserve_unicode_literal_content_and_order(self):
        m = ChatMessageView
        session = {'id': 'synthetic-session'}
        stamp = '2026-11-26T12:00:00'
        combining = 'e\u0301'
        emoji = '👩‍💻🙂'
        user1 = m('user', f'合成问题 {emoji} {combining}\n第二行', stamp, 'text')
        user2 = m('user', '重复角色的合成问题\r\n末行无换行', stamp, 'text')
        complete_body = (f'合成完整回复 {emoji} {combining}\n<img src="literal.png">\n'
                         '[字面 URL](https://example.invalid/only-text)\n```text\n  合成 **代码**\n```\n完整末行')
        failed_body = (f'合成失败保留正文 {emoji} {combining}\r\n```text\r\n'
                       '  合成代码CRLF\r\n第二代码行\r\n```\r\n失败末行无换行')
        cancelled_body = f'合成取消部分正文 {emoji} {combining}\n```text\n未闭合 **字面代码\n取消末行'
        unknown_body = f'合成旧历史（状态未知） {emoji} {combining}\nhttps://example.invalid/literal\n未知末行'
        samples = (
            (m('assistant', complete_body, stamp, 'text', 'synthetic-complete', 'completed'), 'completed', '已完成'),
            (m('assistant', failed_body, stamp, 'incomplete', 'synthetic-failed', 'failed'), 'failed', '未完成'),
            (m('assistant', cancelled_body, stamp, 'incomplete', 'synthetic-cancelled', 'cancelled'), 'cancelled', '已取消'),
            (m('assistant', unknown_body, stamp, 'text'), None, '历史状态未知'),
        )
        history = [user1, user2]
        for message, state, label in samples:
            activity = QtAiChat._ordinary_activity(session, None, False, False, False, (user1, message), None)
            if state is None:
                self.assertIsNone(activity)  # no invented request ID or state
                status = m('system', '合成未知状态提示：历史状态未知', '', 'progress')
            else:
                self.assertEqual((activity.state, activity.request_id), (state, message.reply_id))
                status = activity.status_message()
                self.assertIn(label, status.text)
                self.assertEqual(status.kind, 'error' if state == 'failed' else 'progress')
            history.extend((message, status))

        original = tuple(history)
        transcript = display.TranscriptProjection(360)
        with patch('src.ui.qt.ai_chat_transcript.QTextCursor', display.RecordingCursor):
            transcript.show_messages(session['id'], original, '')
            output = transcript.doc.text
            self.assertIn(user1.text, output)
            self.assertIn(user2.text, output)
            for message, _, _ in samples:
                # Markdown deliberately removes only supported complete code fences;
                # the distinct first and last content lines, literal forms and
                # Unicode are checked separately rather than misclaiming raw equality.
                self.assertIn(message.text.split('\n')[0], output)
                self.assertIn(message.text.split('\n')[-1], output)
            self.assertIn('  合成 **代码**', output)
            self.assertIn('  合成代码CRLF\r\n第二代码行\r', output)
            self.assertIn('```text\n未闭合 **字面代码', output)
            self.assertIn('<img src="literal.png">', output)
            self.assertIn('[字面 URL](https://example.invalid/only-text)', output)
            self.assertIn('https://example.invalid/literal', output)
            self.assertEqual(output.count(combining), 5)
            self.assertEqual(output.count(emoji), 5)
            self.assertNotIn('合成未知状态提示', output)
            self.assertNotIn('模型回复 ·', output)
            self.assertTrue(all(not fmt.isAnchor() for _, _, _, _, fmt in transcript.doc.runs))
            starts = [fmt.property(_MESSAGE_ROLE) for _, _, _, fmt, _ in transcript.doc.runs
                      if fmt.property(_MESSAGE_START) is True]
            self.assertEqual(starts, ['user', 'user', 'assistant', 'assistant', 'assistant', 'assistant'])
            positions = [output.index(marker) for marker in ('合成问题', '重复角色的合成问题', '合成完整回复',
                         '合成失败保留正文', '合成取消部分正文', '合成旧历史（状态未知）')]
            self.assertEqual(positions, sorted(positions))
            self.assertEqual(tuple(history), original)


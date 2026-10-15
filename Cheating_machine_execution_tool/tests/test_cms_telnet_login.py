"""CMS 主动提示、空用户名错位回归及既有非 CMS 登录边界。"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from line_check_assistant.test_item_config_store import TelnetSettings
from src.services import device_project_info_service as info
from src.services import test_item_execution_service as execution
from src.services.test_item_pretest_service import _CancellableSession, PretestCancelled


class LoginPeer:
    """按登录状态响应，而非预填所有提示；初始空回车会消耗用户名位置。"""

    def __init__(self, flag=">", delayed=False, fail_at=None):
        self.flag, self.fail_at = flag, fail_at
        self.history = bytearray(b"banner\r\nLogin: " if not delayed else b"")
        self.pending = [b"banner\r\nLo", b"gin: "] if delayed else []
        self.sent, self.writes, self.waits = [], [], []
        self.state = "user"

    def cursor(self):
        return len(self.history)

    def write(self, data, sensitive=False):
        self.writes.append(data)
        if self.flag == ">":
            self.state = "empty_user_password"
            self.history.extend(b"\r\nPassword: ")
        else:
            self.history.extend(b"\r\nLogin: ")

    def send_line(self, text, sensitive=False):
        self.sent.append(text)
        if self.state == "user":
            self.state = "password"
            if self.fail_at != "password":
                self.history.extend(b"user\r\nPassword: ")
        elif self.state == "password":
            self.state = "authenticated"
            if self.fail_at == "success":
                self.history.extend(b"\r\nLogin incorrect. Try again.\r\nLogin: ")
            else:
                self.pending = [b"\r\n", b"\r\nEntering CMS CLI:\r\n ", self.flag.encode()]
        elif self.state == "empty_user_password":
            self.history.extend(b"\r\nLogin incorrect. Try again.\r\nLogin: ")
            self.state = "user"

    def wait_for_any(self, markers, timeout_seconds, cursor):
        self.waits.append((tuple(markers), cursor))
        while True:
            for marker in markers:
                if marker.lower().encode() in bytes(self.history[cursor:]).lower():
                    return marker
            if not self.pending:
                return None
            self.history.extend(self.pending.pop(0))


class CmsTelnetLoginTests(unittest.TestCase):
    def login(self, module, session, settings, messages):
        with patch.object(module.time, "sleep"):
            if module is info:
                module._login(session, settings, messages.append)
            else:
                module._login(session, settings, messages.append, lambda _: None)

    def test_cms_consumes_buffered_or_fragmented_prompt_without_empty_username(self):
        for module in (info, execution):
            for delayed in (False, True):
                with self.subTest(module=module.__name__, delayed=delayed):
                    peer, messages = LoginPeer(delayed=delayed), []
                    settings = TelnetSettings(user="user", password="secret", login_success_flag=">")
                    self.login(module, peer, settings, messages)
                    self.assertEqual(peer.writes, [])
                    self.assertEqual(peer.sent, ["user", "secret", "sh"])
                    self.assertEqual(peer.waits[0][1], 0)
                    self.assertEqual(len(peer.waits), 3)  # 无额外 # 等待。
                    self.assertIn("跳过初始回车", "".join(messages))
                    self.assertIn("已发送密码", "".join(messages))
                    self.assertNotIn("secret", "".join(messages))

    def test_non_cms_preserves_initial_enter_and_current_cursor(self):
        for module in (info, execution):
            for flag in ("#", "router>", " >", "> "):
                with self.subTest(module=module.__name__, flag=flag):
                    peer, messages = LoginPeer(flag=flag), []
                    initial_cursor = peer.cursor()
                    self.login(module, peer, TelnetSettings(login_success_flag=flag), messages)
                    self.assertEqual(peer.writes, [b"\r"])
                    self.assertEqual(peer.waits[0][1], initial_cursor)
                    self.assertEqual(len(peer.sent), 2)
                    self.assertNotIn("CMS 路径", "".join(messages))

    def test_missing_cms_prompt_does_not_blindly_send_enter_or_credentials(self):
        for module in (info, execution):
            with self.subTest(module=module.__name__):
                peer = LoginPeer(delayed=True)
                peer.pending = []
                with self.assertRaisesRegex(RuntimeError, "用户名提示符"):
                    self.login(module, peer, TelnetSettings(login_success_flag=">"), [])
                self.assertEqual(peer.sent, [])
                self.assertEqual(peer.writes, [])

    def test_password_timeout_does_not_send_password_or_post_login_command(self):
        for module in (info, execution):
            with self.subTest(module=module.__name__):
                peer = LoginPeer(fail_at="password")
                # 历史中的提示符不能代替发送用户名后的实际响应。
                peer.history[:0] = b"Password: > old banner\r\n"
                with self.assertRaisesRegex(RuntimeError, "密码提示符"):
                    self.login(module, peer, TelnetSettings(user="user", login_success_flag=">"), [])
                self.assertEqual(peer.sent, ["user"])

    def test_rejected_password_does_not_send_post_login_command(self):
        for module in (info, execution):
            with self.subTest(module=module.__name__):
                peer = LoginPeer(fail_at="success")
                peer.history[:0] = b"> old banner\r\n"
                with self.assertRaisesRegex(RuntimeError, "登录成功"):
                    self.login(module, peer, TelnetSettings(login_success_flag=">"), [])
                self.assertEqual(len(peer.sent), 2)

    def test_cms_empty_post_login_command_still_sends_one_enter(self):
        for module in (info, execution):
            with self.subTest(module=module.__name__):
                peer = LoginPeer()
                self.login(module, peer, TelnetSettings(login_success_flag=">", login_after_input_str=""), [])
                self.assertEqual(peer.writes, [])
                self.assertEqual(len(peer.sent), 3)
                self.assertEqual(peer.sent[-1], "")

    def test_pretest_cms_wrapper_and_stop_before_first_send(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                peer, cancel = LoginPeer(), threading.Event()
                if cancelled:
                    cancel.set()
                session = _CancellableSession(peer, cancel)
                if cancelled:
                    with self.assertRaises(PretestCancelled):
                        self.login(execution, session, TelnetSettings(login_success_flag=">"), [])
                    self.assertEqual(peer.sent, [])
                else:
                    self.login(execution, session, TelnetSettings(login_success_flag=">"), [])
                    self.assertEqual(peer.sent[-1], "sh")
                self.assertEqual(peer.writes, [])


if __name__ == "__main__":
    unittest.main()

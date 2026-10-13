"""Telnet 登录后指令的条件、下发边界及确认摘要测试。"""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from line_check_assistant.test_item_config_store import TelnetSettings
from src.services.telnet_post_login_service import (
    describe_telnet_post_login,
    run_telnet_post_login,
)


class TelnetPostLoginServiceTests(unittest.TestCase):
    def test_command_is_sent_once_before_one_second_wait_without_prompt_check(self):
        events = []
        session = Mock()
        session.send_line.side_effect = lambda command, **_kwargs: events.append(("send", command))
        telnet = TelnetSettings(login_success_flag=">", login_after_input_str="  busybox sh  ")
        messages = []

        run_telnet_post_login(
            session, telnet, messages.append, lambda seconds: events.append(("wait", seconds))
        )

        session.send_line.assert_called_once_with("busybox sh", sensitive=False)
        self.assertEqual(events, [("send", "busybox sh"), ("wait", 1.0)])
        session.wait_for_any.assert_not_called()
        self.assertIn("已下发：busybox sh", "".join(messages))
        self.assertNotIn("进入 Shell 成功", "".join(messages))

    def test_empty_value_still_sends_one_enter_and_waits(self):
        session, sleep = Mock(), Mock()
        messages = []

        run_telnet_post_login(
            session, TelnetSettings(login_success_flag=">", login_after_input_str=" \t "),
            messages.append, sleep,
        )

        session.send_line.assert_called_once_with("", sensitive=False)
        sleep.assert_called_once_with(1.0)
        self.assertIn("仅回车（配置为空）", "".join(messages))

    def test_only_exact_greater_than_flag_triggers_sending(self):
        for flag in ("#", "router>", " >", "> ", ""):
            with self.subTest(flag=flag):
                session, sleep, messages = Mock(), Mock(), []
                run_telnet_post_login(
                    session, TelnetSettings(login_success_flag=flag), messages.append, sleep
                )
                session.send_line.assert_not_called()
                sleep.assert_not_called()
                self.assertIn("跳过", "".join(messages))

    def test_send_failure_propagates_without_wait_or_completion_log(self):
        session, sleep, messages = Mock(), Mock(), []
        failure = RuntimeError("模拟连接中断")
        session.send_line.side_effect = failure

        with self.assertRaises(RuntimeError) as caught:
            run_telnet_post_login(
                session, TelnetSettings(login_success_flag=">"), messages.append, sleep
            )

        self.assertIs(caught.exception, failure)
        session.send_line.assert_called_once_with("sh", sensitive=False)
        sleep.assert_not_called()
        self.assertNotIn("已下发", "".join(messages))
        self.assertIn("下发失败", "".join(messages))
        self.assertNotIn("模拟连接中断", "".join(messages))

    def test_cancel_during_wait_propagates_without_completion_log(self):
        class Cancelled(Exception):
            pass

        session, sleep, messages = Mock(), Mock(), []
        cancelled = Cancelled()
        sleep.side_effect = cancelled
        with self.assertRaises(Cancelled) as caught:
            run_telnet_post_login(
                session, TelnetSettings(login_success_flag=">"), messages.append, sleep
            )

        self.assertIs(caught.exception, cancelled)
        session.send_line.assert_called_once()
        self.assertIn("已下发", "".join(messages))
        self.assertNotIn("缓冲等待完成", "".join(messages))

    def test_description_explains_command_wait_empty_enter_and_skip(self):
        for flag, command, expected in (
            (">", "  sh  ", "登录后指令：sh；"),
            (">", "", "仅回车（配置为空）"),
            ("#", "sh", "跳过"),
        ):
            with self.subTest(flag=flag, command=command):
                description = describe_telnet_post_login(
                    TelnetSettings(login_success_flag=flag, login_after_input_str=command)
                )
                self.assertIn(expected, description)
                if flag == ">":
                    self.assertIn("等待 1 秒", description)
                else:
                    self.assertNotIn("下发一次", description)


if __name__ == "__main__":
    unittest.main()

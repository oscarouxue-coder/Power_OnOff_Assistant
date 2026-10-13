"""登录后命令的真实 Tk 变量映射和手动查询确认回归。"""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from tkinter import IntVar, StringVar, Tcl
from types import SimpleNamespace
from unittest.mock import Mock, patch

from line_check_assistant import app
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import (
    TelnetSettings, TestItemConfigStore, TestProjectConfig,
)


class TelnetPostLoginTabTests(unittest.TestCase):
    def build_tab(self, settings):
        interpreter = Tcl()
        dirty = Mock()
        entries, labels = [], []

        def entry(*_args, **kwargs):
            widget = Mock()
            entries.append((kwargs, widget))
            return widget

        def label(*_args, **kwargs):
            widget = Mock()
            labels.append((kwargs, widget))
            return widget

        with ExitStack() as stack:
            stack.enter_context(patch.object(app, "StringVar", side_effect=lambda **kw: StringVar(master=interpreter, **kw)))
            stack.enter_context(patch.object(app, "IntVar", side_effect=lambda **kw: IntVar(master=interpreter, **kw)))
            for name in ("Frame", "Button", "Checkbutton"):
                stack.enter_context(patch.object(app, name))
            stack.enter_context(patch.object(app, "Label", side_effect=label))
            for name in ("Frame", "Spinbox"):
                stack.enter_context(patch.object(app.ttk, name))
            stack.enter_context(patch.object(app.ttk, "Entry", side_effect=entry))
            controls = app.LineCheckAssistant._build_test_item_telnet_tab(
                SimpleNamespace(), Mock(), settings, dirty,
            )
        command_label = next(widget for kw, widget in labels if kw.get("text") == "登录后命令")
        row = command_label.grid.call_args.kwargs["row"]
        command_var = next(kw["textvariable"] for kw, widget in entries
                           if widget.grid.call_args and widget.grid.call_args.kwargs["row"] == row)
        return controls, command_var, dirty, labels

    def test_new_field_has_chinese_label_and_follows_success_prompt(self):
        controls, variable, dirty, labels = self.build_tab(TelnetSettings())
        rows = {kw["text"]: widget.grid.call_args.kwargs["row"] for kw, widget in labels}
        self.assertEqual(rows["登录后命令"], rows["登录成功提示符"] + 1)
        self.assertNotIn("login_after_input_str", rows)
        self.assertEqual(variable.get(), "sh")
        self.assertEqual(controls["capture"]().login_after_input_str, "sh")
        dirty.assert_not_called()

    def test_edit_capture_and_reload_preserve_custom_and_empty_values(self):
        controls, variable, dirty, _labels = self.build_tab(TelnetSettings(login_after_input_str="exec sh"))
        self.assertEqual(variable.get(), "exec sh")
        variable.set("busybox sh")
        dirty.assert_called()
        self.assertEqual(controls["capture"]().login_after_input_str, "busybox sh")
        variable.set("")
        self.assertEqual(controls["capture"]().login_after_input_str, "")
        controls["load"](TelnetSettings(login_after_input_str="sh -l"))
        self.assertEqual(variable.get(), "sh -l")
        controls["load"](TelnetSettings(login_after_input_str=""))
        self.assertEqual(variable.get(), "")

    def test_save_and_reopen_tab_restores_the_command(self):
        controls, variable, _dirty, _labels = self.build_tab(TelnetSettings())
        variable.set("exec sh")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            store.save(TestProjectConfig(telnet=controls["capture"]()))
            reopened, value, _new_dirty, _new_labels = self.build_tab(store.load().telnet)
        self.assertEqual(value.get(), "exec sh")
        self.assertEqual(reopened["capture"]().login_after_input_str, "exec sh")


class ProjectInfoPostLoginConfirmationTests(unittest.TestCase):
    def context(self):
        return SimpleNamespace(
            _capture_current_channel=Mock(), current_index=0,
            channels=[ChannelConfig(section="channel_1", vlan_name="vlan139",
                                    network_card_ip="192.168.1.139", device_manage_ip="192.168.1.1")],
            _log=Mock(), log_queue=Mock(), test_item_config_window=Mock(),
            after=Mock(side_effect=lambda _delay, callback: callback()),
        )

    @patch.object(app, "query_device_project_info")
    @patch.object(app.threading, "Thread")
    @patch.object(app.messagebox, "askyesno", return_value=False)
    def test_declined_post_login_confirmation_starts_no_connection(self, confirm, thread, query):
        context = self.context()
        app.LineCheckAssistant._start_project_info_query(
            context, TelnetSettings(login_success_flag=">"), Mock(),
        )
        self.assertIn("sh", confirm.call_args.args[1])
        self.assertIn("1 秒", confirm.call_args.args[1])
        self.assertIn("192.168.1.139", confirm.call_args.args[1])
        thread.assert_not_called()
        query.assert_not_called()
        self.assertIn("取消", context._log.call_args.args[0])

    @patch.object(app, "query_device_project_info")
    @patch.object(app.threading, "Thread")
    @patch.object(app.messagebox, "askyesno", return_value=True)
    def test_confirmed_query_uses_the_described_command(self, confirm, thread, query):
        context = self.context()
        applied = Mock()
        telnet = TelnetSettings(login_success_flag=">", login_after_input_str="exec sh")
        app.LineCheckAssistant._start_project_info_query(context, telnet, applied)
        self.assertIn("exec sh", confirm.call_args.args[1])
        thread.call_args.kwargs["target"]()
        self.assertIs(query.call_args.args[0].telnet, telnet)
        applied.assert_called_once_with(query.return_value)

    @patch.object(app.threading, "Thread")
    @patch.object(app.messagebox, "askyesno", return_value=False)
    def test_empty_command_confirmation_describes_a_return(self, confirm, thread):
        app.LineCheckAssistant._start_project_info_query(
            self.context(), TelnetSettings(login_success_flag=">", login_after_input_str=""), Mock(),
        )
        self.assertIn("回车", confirm.call_args.args[1])
        thread.assert_not_called()

    @patch.object(app.threading, "Thread")
    @patch.object(app.messagebox, "askyesno")
    def test_hash_prompt_keeps_existing_query_interaction(self, confirm, thread):
        app.LineCheckAssistant._start_project_info_query(self.context(), TelnetSettings(), Mock())
        confirm.assert_not_called()
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()

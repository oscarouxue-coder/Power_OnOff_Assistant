"""Channel overview regressions without creating a Tk window or using devices."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from line_check_assistant.app import LineCheckAssistant


class PowerTestChannelStatusTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(
            power_test_channel_states={2: ("failed", "上轮验证失败")},
            power_test_channel_progresses={2: (3, 5, "第3轮完成")},
            power_test_channel_histories={2: [(3, "failed", "上轮验证失败")]},
            power_test_channel_overview=Mock(),
            power_test_channel_overview_shown=True,
            power_test_channel_overview_expanded=True,
            power_test_channel_summary_var=Mock(),
            power_test_channel_attention_var=Mock(),
            power_test_channel_grid=Mock(),
            power_test_channel_detail_label=Mock(),
            power_test_channel_attention_label=Mock(),
            power_test_channel_overview_toggle=Mock(),
            power_test_channel_detail_var=Mock(),
            power_test_channel_selected_number=2,
            _refresh_power_test_channel_history_window=Mock(),
        )
        self.context.power_test_channel_grid.winfo_children.return_value = []
        for method in (
            "_render_power_test_channel_overview",
            "_show_power_test_channel_detail",
            "_set_power_test_channel_state",
            "_set_power_test_channel_progress",
        ):
            setattr(self.context, method, getattr(LineCheckAssistant, method).__get__(self.context))
        label_patch = patch("line_check_assistant.app.ttk.Label")
        self.labels = label_patch.start()
        self.addCleanup(label_patch.stop)
        resume_patch = patch("src.ui.power_test_resume_menu.bind_resume_menu")
        resume_patch.start()
        self.addCleanup(resume_patch.stop)

    def assert_tile(self, channel, text, style):
        prefix = f"通道 {channel}  "
        matching = [
            invocation.kwargs
            for invocation in self.labels.call_args_list
            if invocation.kwargs["text"].startswith(prefix)
        ]
        self.assertTrue(matching, f"No tile rendered for channel {channel}")
        self.assertEqual(matching[-1]["text"], text)
        self.assertEqual(matching[-1]["style"], style)

    def test_explicit_normal_cycle_restores_green_before_all_cycles_complete(self):
        self.context._render_power_test_channel_overview()
        self.assert_tile(2, "通道 2  3/5  失败", "PowerChannelFailed.TLabel")

        self.context._set_power_test_channel_state(2, "success", "第3轮验证正常")

        self.assert_tile(2, "通道 2  3/5  正常", "PowerChannelCompleted.TLabel")
        self.context.power_test_channel_attention_var.set.assert_called_with("")
        self.context.power_test_channel_detail_var.set.assert_called_with(
            "通道 2：3/5，验证正常，第3轮验证正常"
        )
        self.assertEqual(
            self.context.power_test_channel_histories[2], [(3, "failed", "上轮验证失败")]
        )

    def test_next_cycle_running_replaces_previous_success_with_running_color(self):
        self.context._set_power_test_channel_state(2, "success", "第3轮验证正常")
        self.context._set_power_test_channel_progress(2, 3, 5, "第4轮执行中")

        self.context._set_power_test_channel_state(2, "running", "第4轮执行中")

        self.assertEqual(self.context.power_test_channel_states[2], ("running", "第4轮执行中"))
        self.assert_tile(2, "通道 2  3/5  运行", "PowerChannelRunning.TLabel")

    def test_new_retry_and_failure_replace_green_normal(self):
        self.context._set_power_test_channel_state(2, "success", "第3轮验证正常")

        self.context._set_power_test_channel_state(2, "retry", "准备第2/3次验证")
        self.assert_tile(2, "通道 2  3/5  重试", "PowerChannelRetry.TLabel")

        self.context._set_power_test_channel_state(2, "failed", "本轮验证失败")
        self.assert_tile(2, "通道 2  3/5  失败", "PowerChannelFailed.TLabel")
        self.assertIn("失败 1", self.context.power_test_channel_summary_var.set.call_args.args[0])

    def test_recovery_changes_only_its_channel_and_preserves_all_history(self):
        self.context.power_test_channel_states[7] = ("failed", "另一路失败")
        self.context.power_test_channel_progresses[7] = (3, 5, "第3轮完成")
        self.context.power_test_channel_histories[7] = [(3, "failed", "另一路失败")]

        self.context._set_power_test_channel_state(2, "success", "第3轮验证正常")

        self.assert_tile(2, "通道 2  3/5  正常", "PowerChannelCompleted.TLabel")
        self.assert_tile(7, "通道 7  3/5  失败", "PowerChannelFailed.TLabel")
        self.assertEqual(self.context.power_test_channel_states[7], ("failed", "另一路失败"))
        self.assertEqual(
            self.context.power_test_channel_histories,
            {2: [(3, "failed", "上轮验证失败")], 7: [(3, "failed", "另一路失败")]},
        )
        attention = self.context.power_test_channel_attention_var.set.call_args.args[0]
        self.assertIn("通道 7 3/5 失败", attention)
        self.assertNotIn("通道 2", attention)
        self.assertIn("失败 1", self.context.power_test_channel_summary_var.set.call_args.args[0])

    def test_final_success_keeps_completed_label_and_green_color(self):
        self.context._set_power_test_channel_progress(2, 5, 5, "所有测试项验证成功")

        self.context._set_power_test_channel_state(2, "success", "所有测试项验证成功")

        self.assert_tile(2, "通道 2  5/5  已完成", "PowerChannelCompleted.TLabel")
        self.context.power_test_channel_summary_var.set.assert_called_with("全部通道已完成：1/1")

    def test_progress_alone_keeps_failure_until_an_explicit_state_event(self):
        self.context._set_power_test_channel_progress(2, 3, 5, "第4轮执行中")

        self.assertEqual(self.context.power_test_channel_states[2], ("failed", "上轮验证失败"))
        self.assert_tile(2, "通道 2  3/5  失败", "PowerChannelFailed.TLabel")


if __name__ == "__main__":
    unittest.main()

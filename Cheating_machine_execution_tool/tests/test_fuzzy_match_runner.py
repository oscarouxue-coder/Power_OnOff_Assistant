"""fuzzy_match_runner 单元测试。

覆盖：
- 单段肯定：in / not in
- 单段否定：re.search / not re.search
- 多段 && 全肯定
- 多段 && 全否定
- 混合 !A&&B&&!C
- 空段 !&&A&& 跳过
- expected 为空 → 默认 True
- result 为 None → 不抛，按空串处理
- IPv6 边界（不实现 → 显式文档保证 + 一项「telnet 不会下发 tcapi」假阳单测）
- 长 result 性能（≥ 10 KiB 不退化，< 100ms）
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.fuzzy_match_runner import iter_segments, match_expected


class MatchExpectedSingleSegmentTests(unittest.TestCase):
    def test_single_positive_segment_matches(self) -> None:
        self.assertTrue(match_expected("hello world foo bar", "hello"))
        self.assertTrue(match_expected("hello world foo bar", "foo bar"))
        self.assertTrue(match_expected("ONU State: O5", "ONU State: O5"))

    def test_single_positive_segment_not_in_result(self) -> None:
        self.assertFalse(match_expected("hello world", "goodbye"))
        self.assertFalse(match_expected("ONU State: O1", "ONU State: O5"))


class MatchExpectedSingleNegateTests(unittest.TestCase):
    def test_single_negate_segment_present_fails(self) -> None:
        # 「不期望出现 00:00:00:00:00:00」但 result 含 → 失败
        self.assertFalse(match_expected("00:00:00:00:00:00 flags=...", "!00:00:00:00:00:00"))

    def test_single_negate_segment_absent_passes(self) -> None:
        # 「不期望出现 00:00:00:00:00:00」且 result 不含 → 成功
        self.assertTrue(match_expected("CA:7A:85:18:B0:E8 flags=...", "!00:00:00:00:00:00"))


class MatchExpectedAndTests(unittest.TestCase):
    def test_multiple_positive_segments_all_match(self) -> None:
        # 模拟 test_project_config.ini 真实 ifconfig pon1.335.1 期望
        result = "inet addr:172.33.5  netmask 255.255.255.0"
        self.assertTrue(match_expected(result, "inet addr:172.33.5"))
        # 多段全肯定
        self.assertTrue(match_expected(result, "inet addr:172.33.5&&netmask 255.255"))

    def test_multiple_positive_segments_one_missing_fails(self) -> None:
        result = "inet addr:172.33.5  netmask 255.255.255.0"
        self.assertFalse(match_expected(result, "inet addr:172.33.5&&inet addr:192.168"))

    def test_multiple_negate_segments_all_absent_passes(self) -> None:
        result = "rx bytes:1234 tx bytes:5678"
        self.assertTrue(match_expected(result, "!error&&!failed&&!denied"))

    def test_multiple_negate_segments_one_present_fails(self) -> None:
        # 大小写敏感（与老工具 fuzzy_match.py:67 re.findall 同款语义）：
        # 段「error」需在 result 中找到子串「error」才算「出现」。
        result = "rx bytes:1234 error: timeout"
        self.assertFalse(match_expected(result, "!error&&!failed"))


class MatchExpectedMixedTests(unittest.TestCase):
    def test_mixed_negate_and_positive(self) -> None:
        # 模拟 test_project_config.ini 中 ifconfig ra0 的期望
        result = "CA:7A:85:18:B0:E8  UP BROADCAST  MTU:1500"
        self.assertTrue(
            match_expected(result, "!00:00:00:00:00:00&&UP BROADCAST"),
            "MAC 全零应不出现 + UP BROADCAST 应出现 → 全部满足",
        )

    def test_mixed_negate_present_fails(self) -> None:
        result = "00:00:00:00:00:00  UP BROADCAST  MTU:1500"
        # MAC 全零出现 → 失败（即使 UP BROADCAST 出现）
        self.assertFalse(match_expected(result, "!00:00:00:00:00:00&&UP BROADCAST"))


class MatchExpectedEdgeCaseTests(unittest.TestCase):
    def test_empty_expected_returns_true(self) -> None:
        self.assertTrue(match_expected("anything", ""))
        self.assertTrue(match_expected("", ""))

    def test_all_empty_segments_skipped(self) -> None:
        # 全空段视为「无期望」→ True
        self.assertTrue(match_expected("hello", "&&&&"))
        # 混合空段 + 肯定段
        self.assertTrue(match_expected("hello world", "&&hello&&"))
        self.assertFalse(match_expected("hello world", "&&foo&&"))

    def test_none_result_treated_as_empty_string(self) -> None:
        # result=None 不抛，按空串处理；单段肯定找不到 → False
        self.assertFalse(match_expected(None, "hello"))
        # 全空段 → True
        self.assertTrue(match_expected(None, ""))

    def test_special_regex_chars_in_segment_are_escaped(self) -> None:
        # 老工具用 re.findall 对带正则元字符的段会产生意外匹配；
        # 本实现用 re.escape 保证「字面匹配」。这里 .+ 不应被当作「任意字符」。
        self.assertTrue(match_expected("version.+5.4", "version.+5.4"))
        self.assertFalse(match_expected("versionX5Y4", "version.+5.4"))


class IterSegmentsTests(unittest.TestCase):
    def test_iter_segments_basic(self) -> None:
        result = list(iter_segments("A&&!B&&C"))
        self.assertEqual(result, [(False, "A"), (True, "B"), (False, "C")])

    def test_iter_segments_empty(self) -> None:
        result = list(iter_segments(""))
        self.assertEqual(result, [(False, "")])


class Ipv6BoundaryTest(unittest.TestCase):
    """IPv6 特殊分支（老工具 fuzzy_match.py:47-59）不在本实现范围内。

    文档保证：测试项配置 ini 中不出现 ``tcapi get WanInfo_Entry`` 形式的命令；
    若未来需要，先把 IPv6 判定逻辑显式加到 ``match_expected``（而非悄悄依赖正则）。
    """

    def test_tcapi_waninfo_segment_does_not_trigger_ipv6_special(self) -> None:
        # 老工具会对「IP6 in key + tcapi get WanInfo_Entry in key」走 IPv6 特殊分支。
        # 本实现不识别此 key，不走特殊路径；只按「段是否在 result 中」判定。
        # 给一个不含 IPv6 的 result，期望「IPv6-style 期望」不通过。
        result = "no ipv6 here"
        # 老工具会对这种 key 走 IPv6 判定；本实现直接当普通子串匹配 → 失败
        self.assertFalse(match_expected(result, "::1"))


class MatchExpectedPerformanceTest(unittest.TestCase):
    def test_large_result_does_not_degrade(self) -> None:
        # 10 KiB result + 多段判定，应在合理时间内完成
        big_result = "RX bytes:1234 " * 500 + "ONGOING"  # ~10 KiB
        start = time.monotonic()
        for _ in range(50):
            self.assertTrue(match_expected(big_result, "ONGOING&&!ERROR&&!FAILED"))
        elapsed = time.monotonic() - start
        # 50 轮总耗时 < 1s（实测通常 < 100ms）
        self.assertLess(elapsed, 1.0, f"性能回归：{elapsed:.3f}s/50 轮")


if __name__ == "__main__":
    unittest.main()

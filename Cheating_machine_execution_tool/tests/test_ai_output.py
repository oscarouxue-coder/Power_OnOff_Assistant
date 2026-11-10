import codecs
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.ai_output import decode_pc_output, format_diagnostic_evidence


class PcOutputTests(unittest.TestCase):
    def setUp(self):
        self.windows = Mock()
        self.windows.kernel32.GetOEMCP.return_value = 936
        self.windows.kernel32.GetACP.return_value = 936
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("src.utils.ai_output.os.name", "nt"))
        self.stack.enter_context(patch("ctypes.windll", self.windows, create=True))
        self.stack.enter_context(patch("src.utils.ai_output.locale.getpreferredencoding", return_value="utf-8"))

    def test_utf8_netsh_is_not_misread_as_gbk(self):
        text = "系统上有 1 个接口：\r\n名称：VLAN101\r\n状态：已连接"
        self.assertEqual(decode_pc_output(text.encode("utf-8")), (text, "utf-8"))

    def test_legacy_chinese_commands_work_even_when_python_utf8_mode_is_on(self):
        text = "Windows IP 配置\r\n默认网关：<IP_1>"
        self.assertEqual(decode_pc_output(text.encode("gbk")), (text, "cp936"))

    def test_oem_codepage_can_differ_from_ansi(self):
        self.windows.kernel32.GetOEMCP.return_value = 437
        self.windows.kernel32.GetACP.return_value = 1252
        self.assertEqual(decode_pc_output("é".encode("cp437")), ("é", "cp437"))

    def test_ansi_is_used_when_oem_cannot_decode(self):
        self.windows.kernel32.GetOEMCP.return_value = 936
        self.windows.kernel32.GetACP.return_value = 1252
        self.assertEqual(decode_pc_output(b"\xe9"), ("é", "cp1252"))

    def test_unicode_bom_is_removed(self):
        for encoding in ("utf-8-sig", "utf-16"):
            with self.subTest(encoding=encoding):
                self.assertEqual(decode_pc_output("名称：无线接口".encode(encoding)),
                                 ("名称：无线接口", encoding))

    def test_broken_unicode_bom_does_not_fall_back_to_gbk(self):
        text, encoding = decode_pc_output(codecs.BOM_UTF8 + b"\xff")
        self.assertEqual(text, "\ufffd")
        self.assertEqual(encoding, "utf-8-sig/replace")

    def test_invalid_bytes_are_marked_not_dropped(self):
        text, encoding = decode_pc_output(b"\x81")
        self.assertEqual((text, encoding), ("\ufffd", "cp936/replace"))

    def test_empty_and_ascii_outputs(self):
        for raw in (b"", b"route print -4\r\n"):
            self.assertEqual(decode_pc_output(raw), (raw.decode("ascii"), "utf-8"))

    def test_non_windows_locale_fallback(self):
        with patch("src.utils.ai_output.os.name", "posix"), patch(
            "src.utils.ai_output.locale.getpreferredencoding", return_value="gbk"
        ):
            self.assertEqual(decode_pc_output("配置".encode("gbk")), ("配置", "gbk"))


class EvidenceDisplayTests(unittest.TestCase):
    def test_nested_pc_snapshot_has_real_lines_and_preserves_log_tail(self):
        pc = {"system": "Windows", "configured_same_subnet": True,
              "netsh wlan show interfaces": "系统上有 1 个接口：\r\n名称：VLAN101"}
        evidence = [{"tool": "read_pc_environment", "evidence": json.dumps(pc, ensure_ascii=False)},
                    {"tool": "read_serial_log", "evidence": "目标串口未打开"}]
        tail = "\n串口现场\n" + r"C:\temp\new\log.txt" + "\n"
        rendered = format_diagnostic_evidence(json.dumps(evidence, ensure_ascii=False) + tail)
        self.assertIn("[1] read_pc_environment\nsystem：Windows", rendered)
        self.assertIn("configured_same_subnet：是", rendered)
        self.assertIn("netsh wlan show interfaces：\n系统上有 1 个接口：\r\n名称：VLAN101", rendered)
        self.assertIn("[2] read_serial_log\n目标串口未打开", rendered)
        self.assertTrue(rendered.endswith(tail))
        self.assertNotIn(r'\"', rendered)
        self.assertNotIn(r"\r\n", rendered)

    def test_serial_text_and_paths_are_not_unescaped_or_parsed(self):
        text = r'C:\temp\new\report.txt literal \n \u4e2d {"status":"ok"}'
        evidence = [{"tool": "read_serial_log", "evidence": text}]
        self.assertEqual(format_diagnostic_evidence(evidence), "[1] read_serial_log\n" + text)
        self.assertEqual(format_diagnostic_evidence(json.dumps(evidence)), "[1] read_serial_log\n" + text)

    def test_failed_tool_and_empty_evidence_are_shown(self):
        self.assertEqual(format_diagnostic_evidence('[{"tool":"read_dut_state","error":"连接失败"}]'),
                         "[1] read_dut_state\n采集失败：连接失败")
        self.assertEqual(format_diagnostic_evidence("[]\n已有日志"), "\n已有日志")
        self.assertEqual(format_diagnostic_evidence(""), "")

    def test_unknown_or_truncated_old_evidence_stays_intact(self):
        for original in ('[{"tool":"read_pc_environment","evidence":', '{"legacy":1}',
                         '[{"other":"unknown"}]', "绯荤粺涓婃湁\n原始日志", "  原文  "):
            with self.subTest(original=original):
                self.assertEqual(format_diagnostic_evidence(original), original)

    def test_invalid_nested_json_keeps_raw_evidence(self):
        broken = '{"netsh":"系统上有 1 个接口"'
        evidence = [{"tool": "read_pc_environment", "evidence": broken}]
        self.assertTrue(format_diagnostic_evidence(evidence).endswith(broken))


if __name__ == "__main__":
    unittest.main()

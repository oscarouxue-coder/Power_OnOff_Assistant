"""样机项目信息只读 Telnet 查询服务测试。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from line_check_assistant.test_item_config_store import ProjectInfoSettings, TelnetSettings
from src.services.device_project_info_service import (
    DEVICEINFO_COMMAND,
    PROC_VERSION_COMMAND,
    DeviceProjectInfo,
    DeviceProjectInfoQueryRequest,
    project_info_mismatches,
    query_device_project_info,
)


class _FakeTelnetSession:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.sent_lines: list[str] = []
        self.closed = False

    def cursor(self) -> int:
        return len(self.sent_lines)

    def write(self, _data: bytes, sensitive: bool = False) -> None:
        return None

    def send_line(self, text: str, sensitive: bool = False) -> None:
        self.sent_lines.append(text)

    def wait_for_any(self, markers, timeout_seconds: float, cursor: int):
        return next(iter(markers))

    def peek_since(self, cursor: int) -> str:
        return self.outputs.pop(0)

    def close(self) -> None:
        self.closed = True


class DeviceProjectInfoQueryServiceTests(unittest.TestCase):
    @patch("src.services.device_project_info_service.TelnetSession")
    def test_query_reads_all_requested_fields(self, session_class) -> None:
        fake_session = _FakeTelnetSession(
            [
                "config deviceinfo\n\toption software_version 'S13.58.01.001'\n"
                "\toption inner_sw_version 'T13.58.01.003'\n",
                "Linux version 4.4.60 (builder@host) #1 SMP Mon Jun 8 10:16:25 UTC 2026\n",
            ]
        )
        session_class.return_value = fake_session
        messages: list[str] = []

        result = query_device_project_info(
            DeviceProjectInfoQueryRequest(
                bind_ip="192.168.1.139",
                device_host="192.168.1.1",
                telnet=TelnetSettings(user="root", password="secret"),
            ),
            messages.append,
        )

        self.assertEqual(result.software_version, "S13.58.01.001")
        self.assertEqual(result.internal_software_version, "T13.58.01.003")
        self.assertEqual(result.onu_compile_time, "Mon Jun 8 10:16:25 UTC 2026")
        self.assertEqual(fake_session.sent_lines[-2:], [DEVICEINFO_COMMAND, PROC_VERSION_COMMAND])
        self.assertTrue(fake_session.closed)
        self.assertIn("下发只读命令", "".join(messages))

    @patch("src.services.device_project_info_service.TelnetSession")
    def test_query_rejects_missing_deviceinfo_field(self, session_class) -> None:
        session_class.return_value = _FakeTelnetSession(
            ["option software_version 'S13.58.01.001'\n", "Linux version #1 SMP Mon Jun 8 10:16:25 UTC 2026\n"]
        )

        with self.assertRaisesRegex(RuntimeError, "inner_sw_version"):
            query_device_project_info(
                DeviceProjectInfoQueryRequest(
                    bind_ip="192.168.1.139",
                    device_host="192.168.1.1",
                    telnet=TelnetSettings(user="root", password="secret"),
                )
            )

    def test_project_info_mismatches_reports_only_different_fields(self) -> None:
        mismatches = project_info_mismatches(
            ProjectInfoSettings(
                software_version="S13.58.01.001",
                internal_software_version="T13.58.01.003",
                onu_compile_time="Mon Jun 8 10:16:25 UTC 2026",
            ),
            DeviceProjectInfo(
                software_version="S13.58.01.001",
                internal_software_version="T13.58.01.004",
                onu_compile_time="Mon Jun 8 10:16:25 UTC 2026",
            ),
        )

        self.assertEqual(
            mismatches,
            ("内部软件版本：期望 T13.58.01.003，实际 T13.58.01.004",),
        )

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.page_upgrade import (
    DEVICE_SAVE_PATH,
    PageUpgradeRequest,
    UbusRpcError,
    run_single_page_upgrade,
)


class FakeUbusClient:
    def __init__(self, bind_ip, login_results=None, status_results=None):
        self.bind_ip = bind_ip
        self.login_results = list(login_results or [True, True])
        self.status_results = list(status_results or [9])
        self.urls = []
        self.upload_calls = []
        self.triggered = False
        self.logout_count = 0
        self.ubus_url = ""

    def switch_url(self, url):
        self.ubus_url = url
        self.urls.append(url)

    def login(self, username, password, attempts=3):
        return self.login_results.pop(0) if self.login_results else True

    def upload_file(self, local_file_path, device_save_path, upload_url):
        self.upload_calls.append((local_file_path, device_save_path, upload_url))
        return 200, "ok"

    def trigger_upgrade(self, on_output=None):
        self.triggered = True
        return "bbfdm.operate"

    def query_upgrade_status(self):
        return self.status_results.pop(0) if self.status_results else 9

    def logout(self):
        self.logout_count += 1


class FakeTriggerFallbackClient(FakeUbusClient):
    def __init__(self, bind_ip):
        super().__init__(bind_ip, login_results=[True, True], status_results=[9])
        self.trigger_attempts = 0

    def trigger_upgrade(self, on_output=None):
        self.trigger_attempts += 1
        if on_output:
            on_output("bbfdm.operate 触发升级被拒绝，尝试下一种兼容方式。")
        return "bbfdm.operate(proto=web)"


class PageUpgradeTests(unittest.TestCase):
    @patch("line_check_assistant.page_upgrade.enable_adapter")
    def test_single_page_upgrade_falls_back_to_https_and_waits_for_reboot_login(self, enable_adapter):
        firmware = Path(__file__)
        enable_adapter.return_value = Mock(ok=True, message="enabled")
        fake_client = FakeUbusClient(
            "172.18.18.3",
            login_results=[False, True, True],
            status_results=[9],
        )
        output = Mock()

        result = run_single_page_upgrade(
            PageUpgradeRequest(
                vlan="vlan101",
                bind_ip="172.18.18.3",
                device_ip="192.168.29.1",
                username="sdmc",
                password="1234",
                firmware_path=firmware,
                adapter_alias="VLAN101",
            ),
            on_output=output,
            sleep_fn=Mock(),
            client_factory=Mock(return_value=fake_client),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            fake_client.urls,
            [
                "http://192.168.29.1/ubus/",
                "https://192.168.29.1/ubus/",
            ],
        )
        self.assertEqual(fake_client.upload_calls[0][1], DEVICE_SAVE_PATH)
        self.assertEqual(fake_client.upload_calls[0][2], "https://192.168.29.1/cgi-bin/cgi-upload")
        self.assertTrue(fake_client.triggered)
        self.assertEqual(fake_client.logout_count, 2)
        enable_adapter.assert_called_once_with("VLAN101")
        output.assert_any_call("vlan101 检查并启用网卡：VLAN101")
        output.assert_any_call("enabled")
        output.assert_any_call("vlan101 UBUS 登录成功")

    @patch("line_check_assistant.page_upgrade.enable_adapter")
    def test_single_page_upgrade_returns_failure_status_message(self, enable_adapter):
        enable_adapter.return_value = Mock(ok=True, message="enabled")
        fake_client = FakeUbusClient(
            "172.18.18.3",
            login_results=[True],
            status_results=[4],
        )

        result = run_single_page_upgrade(
            PageUpgradeRequest(
                vlan="vlan101",
                bind_ip="172.18.18.3",
                device_ip="192.168.29.1",
                username="sdmc",
                password="1234",
                firmware_path=Path(__file__),
                adapter_alias="VLAN101",
            ),
            sleep_fn=Mock(),
            client_factory=Mock(return_value=fake_client),
        )

        self.assertFalse(result.ok)
        self.assertIn("固件验证错误", result.message)

    @patch("line_check_assistant.page_upgrade.enable_adapter")
    def test_single_page_upgrade_accepts_trigger_fallback(self, enable_adapter):
        enable_adapter.return_value = Mock(ok=True, message="enabled")
        fake_client = FakeTriggerFallbackClient("172.18.18.3")
        output = Mock()

        result = run_single_page_upgrade(
            PageUpgradeRequest(
                vlan="vlan139",
                bind_ip="172.18.18.3",
                device_ip="192.168.29.1",
                username="sdmc",
                password="1234",
                firmware_path=Path(__file__),
                adapter_alias="VLAN139",
            ),
            on_output=output,
            sleep_fn=Mock(),
            client_factory=Mock(return_value=fake_client),
        )

        self.assertTrue(result.ok)
        output.assert_any_call("bbfdm.operate 触发升级被拒绝，尝试下一种兼容方式。")
        output.assert_any_call("vlan139 升级命令已触发：bbfdm.operate(proto=web)")

    @patch("line_check_assistant.page_upgrade.enable_adapter")
    def test_single_page_upgrade_stops_when_adapter_enable_fails(self, enable_adapter):
        enable_adapter.return_value = Mock(ok=False, message="启用网卡失败：拒绝访问")
        client_factory = Mock()

        result = run_single_page_upgrade(
            PageUpgradeRequest(
                vlan="vlan138",
                bind_ip="172.18.18.3",
                device_ip="192.168.29.1",
                username="sdmc",
                password="1234",
                firmware_path=Path(__file__),
                adapter_alias="VLAN138",
            ),
            sleep_fn=Mock(),
            client_factory=client_factory,
        )

        self.assertFalse(result.ok)
        self.assertIn("启用网卡失败", result.message)
        client_factory.assert_not_called()

    def test_ubus_rpc_error_detects_access_denied(self):
        error = UbusRpcError("bbfdm.operate", {"error": {"code": -32002, "message": "Access denied"}})

        self.assertTrue(error.is_access_denied)
        self.assertIn("bbfdm.operate", str(error))


if __name__ == "__main__":
    unittest.main()

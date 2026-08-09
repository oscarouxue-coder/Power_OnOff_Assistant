import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from src.core.ubus_http_client import UbusError, UbusHttpClient


def _fake_response(payload: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


class UbusHttpClientTests(unittest.TestCase):
    def _patch_ip(self):
        return patch("src.core.ubus_http_client.ip_is_bindable_locally", return_value=True)

    def test_constructor_rejects_non_bindable_ip(self):
        with patch("src.core.ubus_http_client.ip_is_bindable_locally", return_value=False):
            with self.assertRaisesRegex(UbusError, "UBUS 源 IP"):
                UbusHttpClient("192.168.29.115", "192.168.29.1")

    def test_login_returns_session_id(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        fake_response = _fake_response(
            {"jsonrpc": "2.0", "id": 1, "result": [0, {"ubus_rpc_session": "fake-session-abc"}]}
        )
        with patch.object(client, "_ensure_connection") as ensure:
            ensure.return_value = MagicMock()
            ensure.return_value.request.return_value = None
            ensure.return_value.getresponse.return_value = fake_response
            with patch.object(client, "_post", wraps=client._post) as post_method:
                # Patch the actual request mechanism by monkey-patching _post internal.
                with patch.object(client, "_post", return_value=[0, {"ubus_rpc_session": "fake-session-abc"}]) as patched:
                    session_id = client.login("user", "pass")
            self.assertEqual(session_id, "fake-session-abc")

    def test_login_raises_when_error_code_nonzero(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        with patch.object(client, "_post", return_value=[1, {"ubus_rpc_session": ""}]):
            with self.assertRaisesRegex(UbusError, "UBUS login 错误"):
                client.login("user", "pass")

    def test_bbfdm_get_sends_correct_payload(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []

        def fake_post(params: list) -> Any:
            captured.append(params)
            return [0, [{"path": "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.", "data": []}]]

        with patch.object(client, "_post", side_effect=fake_post):
            result = client.bbfdm_get("session-id", "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.")
        sent = captured[0]
        self.assertEqual(sent[0], "session-id")
        self.assertEqual(sent[1], "bbf.shell")
        self.assertEqual(sent[2], "get")
        self.assertEqual(sent[3]["path"], "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.")
        self.assertEqual(result[0], 0)

    def test_bbfdm_set_uses_obj_path(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []

        def fake_post(params: list) -> Any:
            captured.append(params)
            return [0, [{"data": "1"}]]

        with patch.object(client, "_post", side_effect=fake_post):
            client.bbfdm_set("session-id", "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.1.", {"Enable": "1"})
        sent = captured[0]
        self.assertEqual(sent[2], "set")
        self.assertEqual(sent[3]["obj_path"], {"Enable": "1"})

    def test_bbfdm_set_and_get_support_web_optional(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []
        with patch.object(client, "_post", side_effect=lambda params: captured.append(params) or [0, {}]):
            client.bbfdm_set("session-id", "Device.ManagementServer.", {"URL": "http://acs"}, {"proto": "web"})
            client.bbfdm_get("session-id", "Device.ManagementServer.", {"proto": "web"})

        self.assertEqual(captured[0][3]["optional"], {"proto": "web"})
        self.assertEqual(captured[1][3]["optional"], {"proto": "web"})

    def test_bbfdm_operate_sends_authenticated_wan_command(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []
        with patch.object(client, "_post", side_effect=lambda params: captured.append(params) or [0, {}]):
            client.bbfdm_operate(
                "session-id",
                "Device.X_SDMC_CreateWAN()",
                {"Method": "add", "VLAN": "200"},
                {"proto": "web"},
            )

        sent = captured[0]
        self.assertEqual(sent[2], "operate")
        self.assertEqual(sent[3]["command"], "Device.X_SDMC_CreateWAN()")
        self.assertEqual(sent[3]["input"]["VLAN"], "200")

    def test_logout_releases_device_session_and_clears_local_reference(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        client._session_id = "session-to-release"
        captured: list[list] = []
        with patch.object(
            client,
            "_post",
            side_effect=lambda params: captured.append(params) or [0, {"Result": "OK"}],
        ):
            client.logout()

        sent = captured[0]
        self.assertEqual(sent[0], "session-to-release")
        self.assertEqual(sent[1], "bbf.shell")
        self.assertEqual(sent[2], "unauthenticated_operate")
        self.assertEqual(sent[3]["command"], "Device.X_SDMC_Login.logout()")
        self.assertEqual(sent[3]["input"], {"SessionId": "session-to-release"})
        self.assertEqual(client._session_id, "")

    def test_close_best_effort_logs_out_active_session_once(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        client._session_id = "active-session"
        with patch.object(client, "logout", wraps=client.logout) as logout, patch.object(
            client, "_post", return_value=[0, {"Result": "OK"}]
        ):
            client.close()
            client.close()

        logout.assert_called_once_with()
        self.assertEqual(client._session_id, "")

    def test_bbfdm_add_supports_optional(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []

        def fake_post(params: list) -> Any:
            captured.append(params)
            return [0, [{"data": "1"}]]

        with patch.object(client, "_post", side_effect=fake_post):
            client.bbfdm_add(
                "session-id",
                "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.",
                {"SourceInterface": "lan", "IPVersion": 4, "SourceIP": "0.0.0.0", "Application": "telnet"},
            )
        sent = captured[0]
        self.assertEqual(sent[2], "add")
        self.assertEqual(sent[3]["obj_path"]["Application"], "telnet")
        self.assertNotIn("optional", sent[3])

    def test_bbfdm_add_with_optional_sends_optional(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        captured: list[list] = []

        def fake_post(params: list) -> Any:
            captured.append(params)
            return [0, [{"data": "1"}]]

        with patch.object(client, "_post", side_effect=fake_post):
            client.bbfdm_add(
                "session-id",
                "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.",
                {"Application": "telnet"},
                optional={"proto": "web"},
            )
        sent = captured[0]
        self.assertEqual(sent[3]["optional"], {"proto": "web"})

    def test_post_raises_on_non_200(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        fake_response = _fake_response({"jsonrpc": "2.0", "id": 1, "result": [0, {}]}, status=500)
        with patch.object(client, "_ensure_connection") as ensure:
            connection = MagicMock()
            ensure.return_value = connection
            connection.getresponse.return_value = fake_response
            with self.assertRaisesRegex(UbusError, "HTTP 状态非 200"):
                client._post(["0" * 32, "session", "login", {"username": "x", "password": "y"}])

    def test_close_is_idempotent(self):
        with self._patch_ip():
            client = UbusHttpClient("127.0.0.1", "127.0.0.1")
        with patch.object(client, "_ensure_connection") as ensure:
            ensure.return_value = MagicMock()
            client.close()
            client.close()
            self.assertIsNone(client._connection)

    def test_post_error_hint_when_bind_ip_equals_device_host(self):
        """2026-07-18:bind_ip 与 device_host 相同时,UBUS HTTP 错误消息应附加 hint
        （与 TelnetSession._open_socket 同款）,便于操作员快速定位
        network_card_ip.ini 中 device_manage_ip 误填。
        """
        with self._patch_ip():
            client = UbusHttpClient("192.168.1.110", "192.168.1.110")
        with patch.object(client, "_ensure_connection") as ensure:
            connection = MagicMock()
            ensure.return_value = connection
            connection.request.side_effect = OSError(110, "timed out")
            with self.assertRaisesRegex(UbusError, "提示") as ctx:
                client._post(["session-id", "bbf.shell", "get", {"path": "Device.Firewall.X_SDMC_Security.AccessCtrl.Enable"}])
        msg = str(ctx.exception)
        self.assertIn("bind_ip 与 device_host 相同", msg)
        self.assertIn("192.168.1.110", msg)
        self.assertIn("device_manage_ip", msg)

    def test_post_error_no_hint_when_bind_ip_differs_from_device_host(self):
        """bind_ip 与 device_host 不同时,UBUS HTTP 错误消息不应附加 hint,保持原行为。"""
        with self._patch_ip():
            client = UbusHttpClient("192.168.1.110", "192.168.1.1")
        with patch.object(client, "_ensure_connection") as ensure:
            connection = MagicMock()
            ensure.return_value = connection
            connection.request.side_effect = OSError(110, "timed out")
            with self.assertRaises(UbusError) as ctx:
                client._post(["session-id", "bbf.shell", "get", {"path": "x"}])
        self.assertNotIn("提示", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

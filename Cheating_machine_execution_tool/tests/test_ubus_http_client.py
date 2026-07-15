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


if __name__ == "__main__":
    unittest.main()

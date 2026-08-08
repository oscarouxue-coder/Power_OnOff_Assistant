from __future__ import annotations

import unittest
from typing import Any, Optional
from unittest.mock import MagicMock, patch

from src.core import ubus_enable_telnet
from src.core.ubus_enable_telnet import (
    ACCESS_CTRL_ENABLE_OBJECT_PATH,
    ACCESS_CTRL_ENABLE_PATH,
    ACCESS_CTRL_RULE_BASE_PATH,
    _bbfdm_all_results_one,
    enable_telnet_via_ubus,
)
from src.core.ubus_http_client import UbusError, UbusHttpClient


def _ok_response() -> list:
    # SdmcUbusLibEnableTelnet._add_SecurityAccessCtrlRule 要求 results[*].data == "1"。
    return [0, {"results": [{"data": "1"}, {"data": "1"}, {"data": "1"}]}]


def _failed_response() -> list:
    return [0, {"results": [{"data": "0"}, {"data": "1"}, {"data": "0"}]}]


def _rule_response(rules: list[dict]) -> list:
    return [0, {"Rule": rules}]


class FakeClient:
    """最小化的 UbusHttpClient stub,只覆盖 enable_telnet_via_ubus 调用的接口。"""

    def __init__(self, *, enable_state: str = "1", rules: Optional[list[dict]] = None,
                 get_total_response=None, set_total_response=None,
                 add_iface_response=None, add_lan_response=None,
                 set_rule_response=None) -> None:
        self.enable_state = enable_state
        self.rules = rules if rules is not None else []
        self._get_total_response = get_total_response
        self._set_total_response = set_total_response
        self._add_iface_response = add_iface_response
        self._add_lan_response = add_lan_response
        self._set_rule_response = set_rule_response
        self.calls: list = []
        self.session_id = "fake-session"

    # 必暴露给 enable_telnet_via_ubus 但实际不需要返回真实数据的接口
    def login(self, _username: str, _password: str) -> str:
        return self.session_id

    def bbfdm_get(self, _session: str, path: str) -> Any:
        self.calls.append(("get", path, {}))
        if path == ACCESS_CTRL_ENABLE_PATH:
            if self._get_total_response is not None:
                return self._get_total_response
            return [0, {"Enable": self.enable_state}]
        if path == ACCESS_CTRL_RULE_BASE_PATH:
            return _rule_response(self.rules)
        raise AssertionError(f"unexpected get {path}")

    def bbfdm_set(self, _session: str, path: str, obj_path) -> Any:
        self.calls.append(("set", path, obj_path))
        # 模拟 bbfdm 行为:总开关 SET 必须用对象路径 "...AccessCtrl.",而不是
        # 参数路径 "...AccessCtrl.Enable";后者会被 bbfdm 拼成 "...EnableEnable",
        # 返回 fault 9005 "Invalid parameter name"。
        if path == ACCESS_CTRL_ENABLE_OBJECT_PATH:
            response = self._set_total_response if self._set_total_response is not None else _ok_response()
            return response
        if path == ACCESS_CTRL_ENABLE_PATH:
            # 故意出现参数路径 + obj_path 这种错误形态(复刻现场报错),返回 fault 9005。
            return [0, {"results": [{"path": "Device.Firewall.X_SDMC_Security.AccessCtrl.EnableEnable",
                                     "fault": 9005,
                                     "fault_msg": "Invalid parameter name"}]}]
        if path.startswith(ACCESS_CTRL_RULE_BASE_PATH):
            response = self._set_rule_response if self._set_rule_response is not None else _ok_response()
            return response
        raise AssertionError(f"unexpected set {path}")

    def bbfdm_add(self, _session: str, path: str, obj_path) -> Any:
        self.calls.append(("add", path, obj_path))
        if obj_path.get("SourceInterface") == "lan":
            response = self._add_lan_response if self._add_lan_response is not None else _ok_response()
            return response
        response = self._add_iface_response if self._add_iface_response is not None else _ok_response()
        return response


class BbfdmResponseValidationTests(unittest.TestCase):
    def test_bbfdm_all_results_one_true_when_all_data_one(self):
        self.assertTrue(_bbfdm_all_results_one(_ok_response()))

    def test_bbfdm_all_results_one_false_when_any_data_zero(self):
        self.assertFalse(_bbfdm_all_results_one(_failed_response()))

    def test_bbfdm_all_results_one_false_when_payload_not_dict(self):
        self.assertFalse(_bbfdm_all_results_one([0, "string-payload"]))

    def test_bbfdm_all_results_one_false_when_no_results(self):
        self.assertFalse(_bbfdm_all_results_one([0, {"results": []}]))

    def test_bbfdm_all_results_one_false_when_results_missing(self):
        self.assertFalse(_bbfdm_all_results_one([0, {}]))

    def test_bbfdm_all_results_one_false_when_top_level_not_list(self):
        self.assertFalse(_bbfdm_all_results_one({"unexpected": True}))


class EnableTelnetViaUbusTests(unittest.TestCase):
    def test_operation_logs_include_real_paths_and_plaintext_password(self):
        events: list[ubus_enable_telnet.EnableTelnetResult] = []
        client = FakeClient(enable_state="0", rules=[])

        enable_telnet_via_ubus(
            client,
            "telecomadmin",
            "secret-password",
            on_log=events.append,
            sleep_fn=lambda _seconds: None,
            sleep_after_seconds=0.0,
        )

        messages = "\n".join(event.message for event in events)
        self.assertIn("TX UBUS session.login username=telecomadmin, password=secret-password", messages)
        self.assertIn(f"TX UBUS bbfdm.get path={ACCESS_CTRL_ENABLE_PATH}", messages)
        self.assertIn(f"TX UBUS bbfdm.set path={ACCESS_CTRL_ENABLE_OBJECT_PATH}", messages)
        self.assertIn(f"TX UBUS bbfdm.get path={ACCESS_CTRL_RULE_BASE_PATH}", messages)
        self.assertIn(f"TX UBUS bbfdm.add path={ACCESS_CTRL_RULE_BASE_PATH}", messages)
        self.assertIn("secret-password", messages)

    def test_already_present_path_skips_set_and_logs(self):
        # 已有规则且 Enable=="True": 不应调 set/add,只走 already_present 且最终 sleep 1.0s。
        rules = [{
            "Application": "telnet",
            "SourceInterface": "Device.IP.Interface.1",
            "Enable": "True",
            "X_SDMC_Instance": "1",
        }]
        client = FakeClient(enable_state="1", rules=rules)
        events: list[ubus_enable_telnet.EnableTelnetResult] = []
        sleeps: list[float] = []

        result = enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=events.append,
            sleep_fn=sleeps.append,
            sleep_after_seconds=0.0,
        )

        self.assertEqual(result.action, "already_present")
        self.assertEqual([c[0] for c in client.calls], ["get", "get"])
        # sleep_after_seconds (0.0) + ENABLE_TELNET_FINAL_SLEEP_SECONDS (1.0)
        self.assertEqual(sleeps, [0.0, ubus_enable_telnet.ENABLE_TELNET_FINAL_SLEEP_SECONDS])
        action_seq = [event.action for event in events]
        self.assertIn("already_present", action_seq)

    def test_existing_rule_with_enable_false_sets_rule_and_returns_reused(self):
        rules = [{
            "Application": "telnet",
            "SourceInterface": "lan",
            "Enable": "False",
            "X_SDMC_Instance": "7",
        }]
        client = FakeClient(enable_state="1", rules=rules, set_rule_response=_ok_response())
        events: list[ubus_enable_telnet.EnableTelnetResult] = []
        sleeps: list[float] = []

        result = enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=events.append,
            sleep_fn=sleeps.append,
            sleep_after_seconds=0.0,
        )

        self.assertEqual(result.action, "reused")
        set_calls = [c for c in client.calls if c[0] == "set"]
        self.assertEqual(len(set_calls), 1)
        self.assertEqual(set_calls[0][2], {"Enable": "1"})
        self.assertTrue(set_calls[0][1].startswith(f"{ACCESS_CTRL_RULE_BASE_PATH}7."))
        self.assertEqual(sleeps, [0.0, ubus_enable_telnet.ENABLE_TELNET_FINAL_SLEEP_SECONDS])

    def test_added_iface_when_no_existing_rules(self):
        client = FakeClient(enable_state="0", rules=[], add_iface_response=_ok_response())
        sleeps: list[float] = []

        result = enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=None,
            sleep_fn=sleeps.append,
            sleep_after_seconds=0.0,
        )

        self.assertEqual(result.action, "added_iface")
        add_calls = [c for c in client.calls if c[0] == "add"]
        self.assertEqual(len(add_calls), 1)
        self.assertEqual(add_calls[0][2]["SourceInterface"], "Device.IP.Interface.1")
        self.assertEqual(sleeps, [0.0, ubus_enable_telnet.ENABLE_TELNET_FINAL_SLEEP_SECONDS])

    def test_set_total_enable_rejected_when_data_zero(self):
        # 总开关 SET 返回 results.data=0 应抛 UbusError,不复用 SdmcUbusLib 旧版的无条件成功。
        client = FakeClient(enable_state="0", rules=[], set_total_response=_failed_response())
        with self.assertRaisesRegex(UbusError, "总开关失败"):
            enable_telnet_via_ubus(
                client,
                "user", "pass",
                on_log=None,
                sleep_fn=lambda _seconds: None,
                sleep_after_seconds=0.0,
            )

    def test_set_existing_rule_rejected_when_data_zero(self):
        rules = [{
            "Application": "telnet",
            "SourceInterface": "lan",
            "Enable": "False",
            "X_SDMC_Instance": "9",
        }]
        client = FakeClient(enable_state="1", rules=rules, set_rule_response=_failed_response())
        with self.assertRaisesRegex(UbusError, "开启 LAN-telnet 规则失败"):
            enable_telnet_via_ubus(
                client,
                "user", "pass",
                on_log=None,
                sleep_fn=lambda _seconds: None,
                sleep_after_seconds=0.0,
            )

    def test_add_iface_data_zero_falls_back_to_lan_and_eventually_succeeds(self):
        # 主 add 返回 data=0 → 校验抛 UbusError → except 走 lan 回退 → lan 成功 → added_lan_fallback。
        # 与 SdmcUbusLibEnableTelnet._add_SecurityAccessCtrlRule 设计一致:任何 if 失败都试 lan。
        client = FakeClient(
            enable_state="1",
            rules=[],
            add_iface_response=[0, {"results": [{"data": "0"}]}],
            add_lan_response=_ok_response(),
        )

        result = enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=None,
            sleep_fn=lambda _seconds: None,
            sleep_after_seconds=0.0,
        )

        self.assertEqual(result.action, "added_lan_fallback")
        iface_add_calls = [
            c for c in client.calls
            if c[0] == "add" and c[2].get("SourceInterface") == "Device.IP.Interface.1"
        ]
        lan_add_calls = [
            c for c in client.calls
            if c[0] == "add" and c[2].get("SourceInterface") == "lan"
        ]
        self.assertEqual(len(iface_add_calls), 1)
        self.assertEqual(len(lan_add_calls), 1)

    def test_add_lan_fallback_succeeds_when_iface_add_raises(self):
        # 主 add 触发真实 UbusError（HTTP 异常等）,进入 lan 回退分支并成功。
        client = FakeClient(enable_state="1", rules=[])

        # bbfdm_add 在收到 SourceInterface!="lan" 时抛 UbusError。
        real_add = client.bbfdm_add

        def faulty_add(_session: str, _path: str, obj_path: dict) -> Any:
            if obj_path.get("SourceInterface") != "lan":
                raise UbusError("bbfdm add iface 异常")
            return _ok_response()

        client.bbfdm_add = faulty_add  # type: ignore[assignment]
        result = enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=None,
            sleep_fn=lambda _seconds: None,
            sleep_after_seconds=0.0,
        )
        self.assertEqual(result.action, "added_lan_fallback")
        # 容许后续代码使用 original 引用,但此测试不会触发。
        del real_add

    def test_added_iface_emits_set_total_enable_when_total_off(self):
        events: list[ubus_enable_telnet.EnableTelnetResult] = []
        client = FakeClient(enable_state="0", rules=[], add_iface_response=_ok_response())

        enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=events.append,
            sleep_fn=lambda _seconds: None,
            sleep_after_seconds=0.0,
        )

        action_seq = [event.action for event in events]
        self.assertIn("set_total_enable", action_seq)
        self.assertIn("added_iface", action_seq)

    def test_set_total_enable_uses_object_path_not_parameter_path(self):
        # 回归:总开关 SET 必须用 "...AccessCtrl."(对象路径),不能用 "...AccessCtrl.Enable"(参数路径)。
        # bbfdm 收到参数路径 + obj_path={"Enable":"1"} 会拼成 "...AccessCtrl.EnableEnable" 并返回 fault 9005。
        set_calls: list = []

        def capturing_set(_session: str, path: str, obj_path):
            set_calls.append((path, obj_path))
            return _ok_response()

        client = FakeClient(enable_state="0", rules=[])
        client.bbfdm_set = capturing_set  # type: ignore[assignment]

        enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=None,
            sleep_fn=lambda _seconds: None,
            sleep_after_seconds=0.0,
        )

        total_enable_sets = [
            (path, obj_path) for path, obj_path in set_calls
            if path.endswith("AccessCtrl.") or path.endswith("AccessCtrl")
        ]
        self.assertTrue(total_enable_sets, "总开关 SET 未触发")
        chosen_path, obj_path = total_enable_sets[0]
        self.assertEqual(chosen_path, ACCESS_CTRL_ENABLE_OBJECT_PATH,
                         f"总开关 SET 必须用对象路径,实际 {chosen_path}")
        self.assertEqual(obj_path, {"Enable": "1"})

    def test_set_total_enable_fault_9005_with_parameter_path_raises(self):
        # 当 bbfdm 返回 fault 9005 "Invalid parameter name"(参数路径错误形态),
        # _bbfdm_all_results_one 必须判定 data != "1" 并抛 UbusError。
        invalid_response = [0, {
            "results": [{
                "path": "Device.Firewall.X_SDMC_Security.AccessCtrl.EnableEnable",
                "fault": 9005,
                "fault_msg": "Invalid parameter name",
            }]
        }]
        client = FakeClient(enable_state="0", rules=[],
                            set_total_response=invalid_response)
        with self.assertRaisesRegex(UbusError, "总开关失败"):
            enable_telnet_via_ubus(
                client,
                "user", "pass",
                on_log=None,
                sleep_fn=lambda _seconds: None,
                sleep_after_seconds=0.0,
            )

    def test_final_sleep_fires_even_when_sleep_after_seconds_is_zero(self):
        # 主要保证调用方传 sleep_after_seconds=0.0(快速路径)时仍走一遍 ENABLE_TELNET_FINAL_SLEEP_SECONDS,
        # 给防火墙 reload 留时间。
        sleeps: list[float] = []
        client = FakeClient(enable_state="1", rules=[])
        enable_telnet_via_ubus(
            client,
            "user", "pass",
            on_log=None,
            sleep_fn=sleeps.append,
            sleep_after_seconds=0.0,
        )
        self.assertIn(ubus_enable_telnet.ENABLE_TELNET_FINAL_SLEEP_SECONDS, sleeps)


if __name__ == "__main__":
    unittest.main()

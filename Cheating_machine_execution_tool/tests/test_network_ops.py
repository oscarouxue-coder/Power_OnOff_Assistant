import unittest
from unittest.mock import MagicMock, patch
import sys 
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.network_ops import (
    CommandResult,
    RegisteredOnuState,
    UnregisteredOnu,
    build_onu_registration_commands,
    check_telnet_connection,
    enable_adapter,
    factory_bind_ip_for,
    factory_device_host_for,
    login_olt_and_enter_global_mode,
    parse_registered_onu_states,
    ping_host,
    prepare_network_for_sample,
    query_unregistered_onus,
    register_unregistered_onus,
    run_line_check,
    save_olt_configuration,
    static_ip_for_vlan,
)


class FakeTelnetSocket:
    def __init__(self, responses, default_response=b"", command_responses=None):
        self.responses = list(responses)
        self.default_response = default_response
        self.command_responses = {command: list(values) for command, values in (command_responses or {}).items()}
        self.last_command = ""
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def settimeout(self, _timeout):
        return None

    def recv(self, _size):
        if self.responses:
            return self.responses.pop(0)
        if self.last_command in self.command_responses and self.command_responses[self.last_command]:
            return self.command_responses[self.last_command].pop(0)
        return self.default_response

    def sendall(self, data):
        self.sent.append(data)
        self.last_command = data.decode("ascii", errors="ignore").strip()


class StaticIpForVlanTests(unittest.TestCase):
    def test_uses_device_network_and_vlan_suffix(self):
        self.assertEqual(static_ip_for_vlan("VLAN108", "192.168.1.1"), "192.168.1.108")

    def test_accepts_adapter_display_name(self):
        self.assertEqual(static_ip_for_vlan("vlan24 [Up]", "10.20.30.254"), "10.20.30.24")

    def test_rejects_invalid_host_number(self):
        with self.assertRaisesRegex(ValueError, "1-254"):
            static_ip_for_vlan("VLAN300", "192.168.1.1")

    def test_rejects_invalid_device_ip(self):
        with self.assertRaisesRegex(ValueError, "样机管理 IP"):
            static_ip_for_vlan("VLAN108", "192.168.1")


class FactoryModeIpDerivationTests(unittest.TestCase):
    """工厂模式 IP 派生:第 3 段 → 29,主机位保持不变。"""

    def test_factory_bind_ip_swaps_third_octet_to_29(self):
        # VLAN114 常见场景:network_card_ip=192.168.1.114 → factory_bind_ip=192.168.29.114
        self.assertEqual(factory_bind_ip_for("192.168.1.114"), "192.168.29.114")

    def test_factory_device_host_swaps_third_octet_to_29(self):
        # device_manage_ip=192.168.1.1 → factory_device_host=192.168.29.1
        self.assertEqual(factory_device_host_for("192.168.1.1"), "192.168.29.1")

    def test_factory_bind_ip_preserves_unusual_subnets(self):
        # 非 192.168.1.x 子网也应派生:10.20.30.50 → 10.20.29.50
        self.assertEqual(factory_bind_ip_for("10.20.30.50"), "10.20.29.50")
        self.assertEqual(factory_device_host_for("172.16.5.10"), "172.16.29.10")

    def test_factory_bind_ip_returns_empty_for_empty_input(self):
        self.assertEqual(factory_bind_ip_for(""), "")
        self.assertEqual(factory_bind_ip_for("   "), "")
        self.assertEqual(factory_bind_ip_for(None), "")

    def test_factory_device_host_returns_empty_for_empty_input(self):
        self.assertEqual(factory_device_host_for(""), "")
        self.assertEqual(factory_device_host_for("   "), "")
        self.assertEqual(factory_device_host_for(None), "")

    def test_factory_bind_ip_returns_empty_for_invalid_ip(self):
        self.assertEqual(factory_bind_ip_for("192.168.1"), "")
        self.assertEqual(factory_bind_ip_for("192.168.1.114.5"), "")
        self.assertEqual(factory_bind_ip_for("not-an-ip"), "")
        self.assertEqual(factory_bind_ip_for("256.0.0.1"), "")

    def test_factory_device_host_returns_empty_for_invalid_ip(self):
        self.assertEqual(factory_device_host_for("192.168.1"), "")
        self.assertEqual(factory_device_host_for("not-an-ip"), "")

    def test_factory_bind_ip_rejects_leading_zeros(self):
        # Python ipaddress.IPv4Address 出于安全考虑拒绝前导零,与 inet_aton 行为一致
        self.assertEqual(factory_bind_ip_for("192.168.001.114"), "")


class PingHostTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_binds_ping_to_channel_static_ip(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "Reply from 192.168.1.1: bytes=32 time<1ms TTL=64"
        run.return_value.stderr = ""

        result = ping_host("192.168.1.1", "192.168.1.108")

        self.assertTrue(result.ok)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            ["ping", "-S", "192.168.1.108", "-n", "2", "-w", "1000", "192.168.1.1"],
        )

    def test_rejects_missing_source_ip(self):
        result = ping_host("192.168.1.1", "")
        self.assertFalse(result.ok)
        self.assertIn("PC 静态 IP", result.message)

    @patch("line_check_assistant.network_ops.time.sleep")
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_retries_same_bound_source_until_ping_succeeds(self, run, sleep):
        failed = unittest.mock.Mock(returncode=1, stdout="Request timed out.", stderr="")
        passed = unittest.mock.Mock(
            returncode=0,
            stdout="Reply from 192.168.1.1: bytes=32 time<1ms TTL=64",
            stderr="",
        )
        run.side_effect = [failed, passed]

        result = ping_host("192.168.1.1", "192.168.1.107")

        self.assertTrue(result.ok)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][1:3], ["-S", "192.168.1.107"])
        self.assertEqual(run.call_args_list[1].args[0][1:3], ["-S", "192.168.1.107"])
        self.assertIn("$ ping -S 192.168.1.107", result.output)
        sleep.assert_called_once_with(2.0)


class TelnetConnectionTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_telnet_connection_uses_olt_ip_and_default_port(self, create_connection):
        create_connection.return_value = MagicMock()

        result = check_telnet_connection("172.18.18.151")

        self.assertTrue(result.ok)
        create_connection.assert_called_once_with(("172.18.18.151", 23), timeout=3.0)

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_telnet_connection_rejects_invalid_ip(self, create_connection):
        result = check_telnet_connection("not-an-ip")

        self.assertFalse(result.ok)
        self.assertIn("OLT IP", result.message)
        create_connection.assert_not_called()

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_olt_login_enters_global_mode_after_telnet_prompt(self, create_connection):
        connection = FakeTelnetSocket(
            [
                b"Username:",
                b"Password:",
                b"ZXAN#",
                b"configure terminal\r\nZXAN(config)#",
            ]
        )
        create_connection.return_value = connection

        result = login_olt_and_enter_global_mode("172.18.18.151", "zte", "secret")

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "OLT 登录成功，已进入全局模式")
        self.assertEqual(connection.sent, [b"zte\r\n", b"secret\r\n", b"configure terminal\r\n"])

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_olt_login_reports_password_failure(self, create_connection):
        connection = FakeTelnetSocket([b"Username:", b"Password:", b"Login incorrect"])
        create_connection.return_value = connection

        result = login_olt_and_enter_global_mode("172.18.18.151", "zte", "wrong")

        self.assertFalse(result.ok)
        self.assertIn("登录失败", result.message)
        self.assertEqual(connection.sent, [b"zte\r\n", b"wrong\r\n"])

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_query_unregistered_onus_lists_all_pon_results(self, create_connection):
        connection = FakeTelnetSocket(
            [
                b"Username:",
                b"Password:",
                b"ZXAN#",
                b"terminal length 0\r\nZXAN#",
                (
                    b"show gpon onu uncfg\r\n"
                    b"OnuIndex                 Sn                  State\r\n"
                    b"---------------------------------------------------------------------\r\n"
                    b"gpon-onu_1/2/1:1         GPONA62D6F48        unknown\r\n"
                    b"gpon-onu_1/2/1:3         GPONA62D6F78        unknown\r\n"
                    b"ZXAN#"
                ),
            ]
        )
        create_connection.return_value = connection

        result = query_unregistered_onus("172.18.18.151", "zte", "zte")

        self.assertTrue(result.ok)
        self.assertIn("查询到 2 个未注册 ONU", result.message)
        self.assertIn("gpon-onu_1/2/1:1", result.message)
        self.assertIn("GPONA62D6F78", result.message)
        self.assertEqual(
            connection.sent,
            [b"zte\r\n", b"zte\r\n", b"terminal length 0\r\n", b"show gpon onu uncfg\r\n"],
        )

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_query_unregistered_onus_reports_empty_result(self, create_connection):
        connection = FakeTelnetSocket(
            [
                b"Username:",
                b"Password:",
                b"ZXAN#",
                b"terminal length 0\r\nZXAN#",
                b"show gpon onu uncfg\r\n%Code 62310-GPONSRV : No related information to show.\r\nZXAN#",
            ]
        )
        create_connection.return_value = connection

        result = query_unregistered_onus("172.18.18.151", "zte", "zte")

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "未查询到未注册 ONU")

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_save_olt_configuration_exits_config_mode_before_write(self, create_connection):
        connection = FakeTelnetSocket(
            [b"Username:", b"Password:", b"ZXAN(config)#"],
            command_responses={
                "exit": [b"ZXAN#"],
                "write": [b"Building configuration...\r\n[OK]\r\nZXAN#"],
            },
        )
        create_connection.return_value = connection

        result = save_olt_configuration("172.18.18.151", "zte", "zte")

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "OLT 最新配置已写入启动配置")
        self.assertEqual(
            [item.decode("ascii").strip() for item in connection.sent],
            ["zte", "zte", "exit", "write"],
        )

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_save_olt_configuration_exits_config_if_mode_before_write(self, create_connection):
        connection = FakeTelnetSocket(
            [b"Username:", b"Password:", b"ZXAN(config-if)#"],
            command_responses={
                "exit": [b"ZXAN(config)#", b"ZXAN#"],
                "write": [b"Building configuration...\r\n[OK]\r\nZXAN#"],
            },
        )
        create_connection.return_value = connection

        result = save_olt_configuration("172.18.18.151", "zte", "zte")

        self.assertTrue(result.ok)
        self.assertEqual(
            [item.decode("ascii").strip() for item in connection.sent],
            ["zte", "zte", "exit", "exit", "write"],
        )

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_save_olt_configuration_writes_directly_from_exec_mode(self, create_connection):
        connection = FakeTelnetSocket(
            [b"Username:", b"Password:", b"ZXAN#"],
            command_responses={"write": [b"Building configuration...\r\n[OK]\r\nZXAN#"]},
        )
        create_connection.return_value = connection

        result = save_olt_configuration("172.18.18.151", "zte", "zte")

        self.assertTrue(result.ok)
        self.assertEqual([item.decode("ascii").strip() for item in connection.sent], ["zte", "zte", "write"])

    def test_build_onu_registration_commands_uses_confirmed_template(self):
        commands = build_onu_registration_commands(UnregisteredOnu("gpon-onu_1/2/1:3", "GPONA62D6F78", "unknown"))

        self.assertEqual(commands[0:6], [
            "interface gpon-olt_1/2/1",
            "onu 3 type SD-41 sn GPONA62D6F78",
            "exit",
            "interface gpon-onu_1/2/1:3",
            "sn-bind enable sn",
            "tcont 1 profile 1G",
        ])
        self.assertIn("service-port 4 vport 4 user-vlan 600 vlan 600", commands)
        self.assertIn("pon-onu-mng gpon-onu_1/2/1:3", commands)
        self.assertIn("service Internet3 gemport 6 vlan 172", commands)
        self.assertEqual(commands[-2:], ["mvlan 600", "exit"])

    def test_parse_registered_onu_states_marks_offline_onu_reusable(self):
        states = parse_registered_onu_states(
            "OnuIndex   Admin State  OMCC State  Phase State  Channel\n"
            "--------------------------------------------------------------\n"
            "1/2/5:1     enable       disable     DyingGasp    1(GPON)\n"
            "1/2/5:2     enable       enable      working      1(GPON)\n"
        )

        self.assertEqual(
            states[0],
            RegisteredOnuState("1/2/5:1", "enable", "disable", "DyingGasp", "1(GPON)"),
        )
        self.assertEqual(states[0].interface_name, "gpon-onu_1/2/5:1")
        self.assertEqual(states[0].pon_path, "1/2/5")
        self.assertEqual(states[0].onu_id, "1")
        self.assertTrue(states[0].is_reusable_offline)
        self.assertFalse(states[1].is_reusable_offline)

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_register_unregistered_onus_sends_selected_onu_template(self, create_connection):
        connection = FakeTelnetSocket(
            [b"Username:", b"Password:", b"ZXAN#", b"configure terminal\r\nZXAN(config)#"],
            default_response=b"ZXAN(config)#",
        )
        create_connection.return_value = connection
        onu = UnregisteredOnu("gpon-onu_1/2/1:1", "GPONA62D6F48", "unknown")

        result = register_unregistered_onus("172.18.18.151", "zte", "zte", [onu])

        self.assertTrue(result.ok)
        self.assertIn("已处理 1 个 ONU 注册配置", result.message)
        self.assertIn("新增配置成功", result.message)
        sent_commands = [item.decode("ascii").strip() for item in connection.sent]
        self.assertEqual(sent_commands[0:4], ["zte", "zte", "configure terminal", "interface gpon-olt_1/2/1"])
        self.assertIn("onu 1 type SD-41 sn GPONA62D6F48", sent_commands)
        self.assertIn("service-port 1 vport 1 user-vlan 200 vlan 200", sent_commands)
        self.assertIn("service VOICE gemport 3 vlan 335", sent_commands)
        self.assertIn("mvlan 600", sent_commands)
        self.assertEqual(sent_commands[-1], "end")

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_register_unregistered_onus_deletes_offline_onus_before_retry_when_new_service_fails(self, create_connection):
        connection = FakeTelnetSocket(
            [b"Username:", b"Password:", b"ZXAN#", b"configure terminal\r\nZXAN(config)#"],
            default_response=b"ZXAN(config)#",
            command_responses={
                "service Internet gemport 1 vlan 200": [b"%Error 20200: Invalid input\r\nZXAN(config-if)#"],
                "show gpon onu state": [
                    (
                        b"OnuIndex   Admin State  OMCC State  Phase State  Channel\r\n"
                        b"--------------------------------------------------------------\r\n"
                        b"1/2/5:1     enable       disable     DyingGasp    1(GPON)\r\n"
                        b"1/2/1:8     enable       disable     DyingGasp    1(GPON)\r\n"
                        b"1/2/6:3     enable       disable     DyingGasp    1(GPON)\r\n"
                        b"1/2/5:2     enable       enable      working      1(GPON)\r\n"
                        b"ZXAN#"
                    )
                ],
            },
        )
        create_connection.return_value = connection
        onu = UnregisteredOnu("gpon-onu_1/2/1:1", "GPONA62D6F48", "unknown")

        result = register_unregistered_onus("172.18.18.151", "zte", "zte", [onu])

        self.assertTrue(result.ok)
        self.assertIn("新增配置失败后删除 3 个离线 ONU 后重新注册成功（同 PON 1 个，其它 PON 2 个）", result.message)
        sent_commands = [item.decode("ascii").strip() for item in connection.sent]
        self.assertIn("service Internet gemport 1 vlan 200", sent_commands)
        self.assertIn("show gpon onu state", sent_commands)
        self.assertNotIn("registration-method sn GPONA62D6F48", sent_commands)
        first_same_pon_delete = sent_commands.index("interface gpon-olt_1/2/1", sent_commands.index("show gpon onu state"))
        first_other_pon_delete = sent_commands.index("interface gpon-olt_1/2/5", first_same_pon_delete)
        self.assertLess(first_same_pon_delete, first_other_pon_delete)
        self.assertIn("no onu 8", sent_commands)
        self.assertIn("no onu 1", sent_commands)
        self.assertIn("no onu 3", sent_commands)
        self.assertGreater(sent_commands.count("onu 1 type SD-41 sn GPONA62D6F48"), 1)
        self.assertEqual(sent_commands[-1], "end")

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_register_unregistered_onus_rejects_empty_selection(self, create_connection):
        result = register_unregistered_onus("172.18.18.151", "zte", "zte", [])

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "未选择要注册的 ONU")
        create_connection.assert_not_called()

    @patch("line_check_assistant.network_ops.socket.create_connection")
    def test_register_unregistered_onus_rejects_invalid_onu_index(self, create_connection):
        result = register_unregistered_onus("172.18.18.151", "zte", "zte", [UnregisteredOnu("bad-index", "GPON1", "unknown")])

        self.assertFalse(result.ok)
        self.assertIn("ONU 接口格式无效", result.message)
        create_connection.assert_not_called()


class EnableAdapterTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_enables_selected_vlan_adapter(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        result = enable_adapter("VLAN107 [Disabled]")

        self.assertTrue(result.ok)
        self.assertEqual(
            run.call_args.args[0],
            ["netsh", "interface", "set", "interface", "name=VLAN107", "admin=enabled"],
        )

    @patch("line_check_assistant.network_ops.ping_host")
    @patch("line_check_assistant.network_ops.set_static_ip")
    @patch("line_check_assistant.network_ops.enable_adapter")
    def test_line_check_enables_adapter_before_setting_ip_and_ping(self, enable, set_ip, ping):
        calls = []
        enable.side_effect = lambda _alias: calls.append("enable") or CommandResult(True, "enabled")
        set_ip.side_effect = lambda *_args: calls.append("set_ip") or CommandResult(True, "set")
        ping.side_effect = lambda *_args: calls.append("ping") or CommandResult(True, "ping ok")

        result = run_line_check(
            "VLAN107",
            "192.168.1.107",
            "255.255.255.0",
            "192.168.1.1",
            settle_seconds=0,
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, ["enable", "set_ip", "ping"])


class PrepareNetworkForSampleTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.set_static_ip")
    @patch("line_check_assistant.network_ops.enable_adapter")
    def test_enables_adapter_then_sets_static_ip(self, enable, set_ip):
        enable.return_value = CommandResult(True, "enabled")
        set_ip.return_value = CommandResult(True, "static ip set")
        sleeps: list[float] = []
        output: list[str] = []

        result = prepare_network_for_sample(
            "VLAN107",
            "192.168.29.107",
            "255.255.255.0",
            on_output=output.append,
            sleep_fn=sleeps.append,
            settle_seconds=0.5,
        )

        self.assertTrue(result.ok)
        enable.assert_called_once_with("VLAN107")
        set_ip.assert_called_once_with("VLAN107", "192.168.29.107", "255.255.255.0")
        self.assertEqual(sleeps, [0.5, 0.5])
        self.assertTrue(any("VLAN107" in line for line in output), output)
        self.assertTrue(any("192.168.29.107" in line for line in output), output)
        self.assertTrue(any("255.255.255.0" in line for line in output), output)

    @patch("line_check_assistant.network_ops.set_static_ip")
    @patch("line_check_assistant.network_ops.enable_adapter")
    def test_returns_failure_when_enable_adapter_fails(self, enable, set_ip):
        enable.return_value = CommandResult(False, "启用网卡失败：拒绝访问")

        result = prepare_network_for_sample("VLAN107", "192.168.29.107", "255.255.255.0", sleep_fn=lambda _x: None)

        self.assertFalse(result.ok)
        self.assertIn("启用网卡失败", result.message)
        set_ip.assert_not_called()

    @patch("line_check_assistant.network_ops.set_static_ip")
    @patch("line_check_assistant.network_ops.enable_adapter")
    def test_returns_failure_when_set_static_ip_fails(self, enable, set_ip):
        enable.return_value = CommandResult(True, "enabled")
        set_ip.return_value = CommandResult(False, "设置网卡静态 IP 失败：拒绝访问")

        result = prepare_network_for_sample("VLAN107", "192.168.29.107", "255.255.255.0", sleep_fn=lambda _x: None)

        self.assertFalse(result.ok)
        self.assertIn("设置网卡静态 IP 失败", result.message)

    def test_returns_failure_when_adapter_alias_missing(self):
        result = prepare_network_for_sample("", "192.168.29.107", "255.255.255.0", sleep_fn=lambda _x: None)

        self.assertFalse(result.ok)
        self.assertIn("未选择 VLAN 网卡", result.message)

    def test_returns_failure_when_bind_ip_missing(self):
        result = prepare_network_for_sample("VLAN107", "", "255.255.255.0", sleep_fn=lambda _x: None)

        self.assertFalse(result.ok)
        self.assertIn("未配置用于访问样机的 PC 静态 IP", result.message)

    def test_strips_status_suffix_from_adapter_alias(self):
        with patch("line_check_assistant.network_ops.enable_adapter") as enable, \
                patch("line_check_assistant.network_ops.set_static_ip") as set_ip:
            enable.return_value = CommandResult(True, "enabled")
            set_ip.return_value = CommandResult(True, "ok")

            prepare_network_for_sample(
                "VLAN107 [Up]",
                "192.168.29.107",
                "255.255.255.0",
                sleep_fn=lambda _x: None,
            )

            enable.assert_called_once_with("VLAN107")
            set_ip.assert_called_once_with("VLAN107", "192.168.29.107", "255.255.255.0")


if __name__ == "__main__":
    unittest.main()

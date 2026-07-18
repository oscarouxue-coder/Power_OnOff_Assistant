import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.network_ops import CommandResult
from src.models import SampleParameterItemResult, SampleParameterWriteRequest


class SampleParameterAppTests(unittest.TestCase):
    def test_parameter_targets_follow_enabled_channels_and_vlan_serial_mapping(self):
        fake_app = Mock()
        fake_app.channels = [
            ChannelConfig("channel_1", vlan_name="VLAN101", enabled=True),
            ChannelConfig("channel_2", vlan_name="VLAN102", enabled=False),
            ChannelConfig("channel_3", adapter_alias="VLAN103", enabled=True),
        ]

        result = LineCheckAssistant._parameter_channel_ports(fake_app)

        self.assertEqual(result, [("VLAN101", "COM1"), ("VLAN103", "COM3")])
        fake_app._capture_current_channel.assert_called_once_with()


class FactoryModeIpHelperTests(unittest.TestCase):
    """_factory_bind_ip_for_vlan / _factory_device_host_for_vlan 在用户模式字段已填、
    工厂模式字段为空时,应自动按"第 3 段 → 29,主机位不变"派生。

    用户模式字段都缺失或格式无效时,返回空串(由 _start_sample_parameter_write 兜底报错)。
    """

    @staticmethod
    def _make_app(channel):
        fake_app = Mock()
        fake_app.channels = [channel]
        # Mock() 会自动 mock 所有属性,这里显式让 _channel_for_vlan 返回真实 ChannelConfig
        fake_app._channel_for_vlan = lambda vlan: channel if channel.enabled else None
        return fake_app

    def test_factory_bind_ip_derives_from_network_card_ip_when_unset(self):
        # 复刻用户现场 ini:VLAN114,factory_bind_ip 为空,只填了 network_card_ip
        channel = ChannelConfig(
            "channel_2", vlan_name="vlan114", adapter_alias="vlan114",
            network_card_ip="192.168.1.114", device_manage_ip="192.168.1.1",
            factory_bind_ip="", factory_device_host="",
            subnet_mask="255.255.255.0", enabled=True,
        )
        self.assertEqual(
            LineCheckAssistant._factory_bind_ip_for_vlan(self._make_app(channel), "vlan114"),
            "192.168.29.114",
        )

    def test_factory_device_host_derives_from_device_manage_ip_when_unset(self):
        channel = ChannelConfig(
            "channel_2", vlan_name="vlan114", adapter_alias="vlan114",
            network_card_ip="192.168.1.114", device_manage_ip="192.168.1.1",
            factory_bind_ip="", factory_device_host="",
            subnet_mask="255.255.255.0", enabled=True,
        )
        self.assertEqual(
            LineCheckAssistant._factory_device_host_for_vlan(self._make_app(channel), "vlan114"),
            "192.168.29.1",
        )

    def test_factory_bind_ip_respects_manual_override(self):
        # 手动填的 factory_bind_ip 优先级高于派生
        channel = ChannelConfig(
            "channel_2", vlan_name="vlan114",
            network_card_ip="192.168.1.114", device_manage_ip="192.168.1.1",
            factory_bind_ip="10.99.99.114", factory_device_host="",
            subnet_mask="255.255.255.0", enabled=True,
        )
        self.assertEqual(
            LineCheckAssistant._factory_bind_ip_for_vlan(self._make_app(channel), "vlan114"),
            "10.99.99.114",
        )

    def test_factory_device_host_respects_manual_override(self):
        channel = ChannelConfig(
            "channel_2", vlan_name="vlan114",
            network_card_ip="192.168.1.114", device_manage_ip="192.168.1.1",
            factory_bind_ip="", factory_device_host="10.99.99.1",
            subnet_mask="255.255.255.0", enabled=True,
        )
        self.assertEqual(
            LineCheckAssistant._factory_device_host_for_vlan(self._make_app(channel), "vlan114"),
            "10.99.99.1",
        )

    def test_factory_bind_ip_returns_empty_when_both_user_mode_fields_missing(self):
        channel = ChannelConfig(
            "channel_x", vlan_name="vlan114",
            network_card_ip="", device_manage_ip="",
            factory_bind_ip="", factory_device_host="",
            subnet_mask="255.255.255.0", enabled=True,
        )
        fake_app = self._make_app(channel)
        self.assertEqual(
            LineCheckAssistant._factory_bind_ip_for_vlan(fake_app, "vlan114"),
            "",
        )
        self.assertEqual(
            LineCheckAssistant._factory_device_host_for_vlan(fake_app, "vlan114"),
            "",
        )

    def test_factory_bind_ip_returns_empty_when_user_mode_ip_invalid(self):
        channel = ChannelConfig(
            "channel_x", vlan_name="vlan114",
            network_card_ip="not-an-ip", device_manage_ip="192.168.1.1",
            factory_bind_ip="", factory_device_host="",
            subnet_mask="255.255.255.0", enabled=True,
        )
        fake_app = self._make_app(channel)
        self.assertEqual(
            LineCheckAssistant._factory_bind_ip_for_vlan(fake_app, "vlan114"),
            "",
        )
        # device_manage_ip 仍合法,device_host 仍能派生
        self.assertEqual(
            LineCheckAssistant._factory_device_host_for_vlan(fake_app, "vlan114"),
            "192.168.29.1",
        )


def _make_request(
    vlan: str = "vlan101",
    bind_ip: str = "192.168.1.101",
    device_host: str = "192.168.1.1",
) -> SampleParameterWriteRequest:
    return SampleParameterWriteRequest(
        vlan=vlan,
        serial_port="COM1",
        initial_username="root",
        initial_password="x",
        values={},
        bind_ip=bind_ip,
        device_host=device_host,
        ubus_port=80,
        factory_bind_ip="192.168.29.101",
        factory_device_host="192.168.29.1",
    )


def _make_fake_app(adapter_alias: str = "vlan101", subnet_mask: str = "255.255.255.0") -> Mock:
    """构造一个够用且自给自足的 LineCheckAssistant Mock。

    _sample_parameter_write_worker 会访问 self.log_queue / self._adapter_alias_for_vlan /
    self._subnet_mask_for_vlan / self.serial_session_manager / self.serial_terminal。
    测试用 telnet 路径请求,serial_* 不会被实际访问,但 Mock 仍要给完整属性。
    """
    fake_app = Mock()
    fake_app.channels = []
    fake_app.log_queue = Mock()
    fake_app.serial_session_manager = Mock()
    fake_app.serial_terminal = Mock()
    fake_app._adapter_alias_for_vlan = Mock(return_value=adapter_alias)
    fake_app._subnet_mask_for_vlan = Mock(return_value=subnet_mask)
    return fake_app


def _invoke_factory_synchronously(mock_run_single):
    """让 mock 的 run_single_sample_parameter_write 在 executor 线程里同步调用 telnet 工厂。

    worker 通过 ThreadPoolExecutor.submit 把 make_telnet_factory(req) 传给
    run_single_sample_parameter_write。这里把 side_effect 设为同步调用工厂并返回
    一个成功的 SampleParameterItemResult,这样测试不需要等待异步 future 也能
    触发工厂闭包内部的全部调用链。
    """
    def side_effect(*args, **kwargs):
        factory = kwargs.get("telnet_session_factory")
        if factory is None and len(args) > 6:
            factory = args[6]
        request = args[0]
        if factory is not None:
            factory(request)
        return SampleParameterItemResult(request, True, "ok")
    mock_run_single.side_effect = side_effect


class SampleParameterAppNetworkPreflightTests(unittest.TestCase):
    """写样机参数 telnet 工厂的前置网络准备(启用网卡 + 设置静态 IP + 等可绑)。

    这三步必须在 UBUS 启用 telnet 之前完成,因为 UBUS HTTP 客户端和 TelnetSession 都用
    ``source_address=(bind_ip, 0)`` 锁源;网卡未启用或 IP 未生效会导致 WSAEADDRNOTAVAIL。
    """

    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_factory_prepares_network_before_ubus(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
    ):
        mock_prepare.return_value = CommandResult(True, "ok")
        mock_wait_bindable.return_value = True
        mock_enable_telnet.return_value = Mock(action="added_iface", message="ok")
        mock_telnet_session.return_value = Mock()
        _invoke_factory_synchronously(mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        # 全部 4 个外部依赖各被调用一次
        mock_prepare.assert_called_once()
        mock_wait_bindable.assert_called_once()
        mock_enable_telnet.assert_called_once()
        mock_telnet_session.assert_called_once()

        # prepare_network_for_sample 必须以 (adapter_alias, bind_ip, subnet_mask) 调用,
        # 并暴露 on_output / sleep_fn 供 emit_to_main 与 time.sleep 注入。
        prepare_args, prepare_kwargs = mock_prepare.call_args
        self.assertEqual(prepare_args[0], "vlan101")
        self.assertEqual(prepare_args[1], "192.168.1.101")
        self.assertEqual(prepare_args[2], "255.255.255.0")
        self.assertIn("on_output", prepare_kwargs)
        self.assertIn("sleep_fn", prepare_kwargs)

        # wait_for_bindable_ip 必须以 bind_ip + 15s 超时调用
        wait_args, wait_kwargs = mock_wait_bindable.call_args
        self.assertEqual(wait_args[0], "192.168.1.101")
        self.assertEqual(wait_kwargs.get("timeout_seconds"), 15.0)

        # 调用顺序: 准备网络 → 等可绑 → UBUS → TelnetSession
        self.assertLess(mock_prepare.call_count, mock_wait_bindable.call_count + 1)
        self.assertLess(mock_wait_bindable.call_count, mock_enable_telnet.call_count + 1)
        self.assertLess(mock_enable_telnet.call_count, mock_telnet_session.call_count + 1)

    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_factory_raises_when_prepare_network_fails(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
    ):
        """prepare_network_for_sample 返回 ok=False → 工厂抛 RuntimeError,后续 UBUS/Telnet 不调用。"""
        mock_prepare.return_value = CommandResult(False, "netsh exit 1")
        _invoke_factory_synchronously(mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        mock_prepare.assert_called_once()
        mock_wait_bindable.assert_not_called()
        mock_enable_telnet.assert_not_called()
        mock_telnet_session.assert_not_called()

        # 主执行日志应包含失败原因
        log_messages = [call.args[0] for call in fake_app.log_queue.put.call_args_list if call.args]
        self.assertTrue(
            any("网络准备失败" in msg for msg in log_messages),
            f"expected '网络准备失败' in logs, got {log_messages}",
        )

    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_factory_raises_when_bindable_ip_times_out(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
    ):
        """wait_for_bindable_ip 返回 False → 工厂抛 RuntimeError,后续 UBUS/Telnet 不调用。"""
        mock_prepare.return_value = CommandResult(True, "ok")
        mock_wait_bindable.return_value = False
        _invoke_factory_synchronously(mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        mock_prepare.assert_called_once()
        mock_wait_bindable.assert_called_once()
        mock_enable_telnet.assert_not_called()
        mock_telnet_session.assert_not_called()

        log_messages = [call.args[0] for call in fake_app.log_queue.put.call_args_list if call.args]
        self.assertTrue(
            any("仍未成为可绑地址" in msg for msg in log_messages),
            f"expected '仍未成为可绑地址' in logs, got {log_messages}",
        )

    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_factory_skips_network_step_when_adapter_alias_empty(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
    ):
        """adapter_alias 为空时(未配置该 VLAN 的网卡)跳过准备步骤,继续走 UBUS → TelnetSession。

        这是向后兼容兜底:旧配置若未填 adapter_alias,不应阻塞其它已配置通道的写参。
        _start_sample_parameter_write 的工厂校验已在弹窗前拒绝,但 worker 自身仍保持宽松。
        """
        mock_enable_telnet.return_value = Mock(action="added_iface", message="ok")
        mock_telnet_session.return_value = Mock()
        _invoke_factory_synchronously(mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app(adapter_alias="")  # 关键: adapter_alias 为空
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        mock_prepare.assert_not_called()
        mock_wait_bindable.assert_not_called()
        mock_enable_telnet.assert_called_once()
        mock_telnet_session.assert_called_once()


class SampleParameterAppUbusRetryTests(unittest.TestCase):
    """UBUS 启用 telnet 失败重试:首次失败 → 重试 3 次 → 仍失败则抛错。

    典型现场:UBUS HTTP 请求失败 192.168.1.1:80:timed out(防火墙 reload 中、
    telnetd 未启动、HTTP 连接握手慢)。给样机留缓冲可大幅降低误判失败。
    """

    def _make_ubus_fail_then_succeed(self, mock_enable_telnet, fail_count):
        """前 fail_count 次抛 RuntimeError(模拟 HTTP timed out),之后返回成功。"""
        outcomes = [RuntimeError("UBUS HTTP 请求失败 192.168.1.1:80：timed out")] * fail_count
        outcomes.append(Mock(action="added_iface", message="ok"))
        mock_enable_telnet.side_effect = outcomes

    def _setup_standard_mocks(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_enable_telnet,
        mock_run_single,
    ):
        mock_prepare.return_value = CommandResult(True, "ok")
        mock_wait_bindable.return_value = True
        mock_telnet_session.return_value = Mock()
        _invoke_factory_synchronously(mock_run_single)

    @patch("time.sleep")  # 重试间隔用 sleep,直接 mock 掉避免真睡 2*3=6 秒
    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_ubus_retry_succeeds_on_third_attempt(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
        mock_sleep,
    ):
        # 失败 2 次,第 3 次成功 → 期望 3 次调用 + 2 次 sleep
        self._make_ubus_fail_then_succeed(mock_enable_telnet, fail_count=2)
        self._setup_standard_mocks(mock_prepare, mock_wait_bindable, mock_telnet_session, mock_enable_telnet, mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        self.assertEqual(mock_enable_telnet.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # 第 2、3 次前各 sleep 一次
        mock_telnet_session.assert_called_once()  # 成功后继续建 TelnetSession

        # 主执行日志应包含 2 条 "第 X/3 次重试" + 2 条失败 + 1 条成功
        log_messages = [call.args[0] for call in fake_app.log_queue.put.call_args_list if call.args]
        retry_logs = [msg for msg in log_messages if "次重试," in msg and "等待" in msg]
        self.assertEqual(len(retry_logs), 2, f"expected 2 retry logs, got {retry_logs}")
        self.assertIn("第 1/3 次重试", retry_logs[0])
        self.assertIn("第 2/3 次重试", retry_logs[1])
        fail_logs = [msg for msg in log_messages if "UBUS 启用 telnet 失败" in msg]
        self.assertEqual(len(fail_logs), 2, f"expected 2 fail logs, got {fail_logs}")

    @patch("time.sleep")
    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_ubus_retry_gives_up_after_max_retries(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
        mock_sleep,
    ):
        # 4 次全部失败 → 期望 4 次调用 + 3 次 sleep + worker 标记失败 + 不建 TelnetSession
        mock_enable_telnet.side_effect = RuntimeError(
            "UBUS HTTP 请求失败 192.168.1.1:80：timed out"
        )
        self._setup_standard_mocks(mock_prepare, mock_wait_bindable, mock_telnet_session, mock_enable_telnet, mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        self.assertEqual(mock_enable_telnet.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_telnet_session.assert_not_called()

        log_messages = [call.args[0] for call in fake_app.log_queue.put.call_args_list if call.args]
        retry_logs = [msg for msg in log_messages if "次重试," in msg]
        self.assertEqual(len(retry_logs), 3, f"expected 3 retry logs, got {retry_logs}")
        fail_logs = [msg for msg in log_messages if "UBUS 启用 telnet 失败" in msg]
        self.assertEqual(len(fail_logs), 4, f"expected 4 fail logs, got {fail_logs}")
        # 最终失败包含 "重试 3 次后仍失败" 字样,便于操作员快速定位
        final_fail = [msg for msg in fail_logs if "RuntimeError" in msg or "timed out" in msg]
        self.assertEqual(len(final_fail), 4)

    @patch("time.sleep")
    @patch("src.services.sample_parameter_service.run_single_sample_parameter_write")
    @patch("src.core.ubus_enable_telnet.enable_telnet_via_ubus")
    @patch("src.core.ubus_http_client.UbusHttpClient")
    @patch("src.core.telnet_transport.TelnetSession")
    @patch("src.core.bind_socket.wait_for_bindable_ip")
    @patch("line_check_assistant.network_ops.prepare_network_for_sample")
    def test_ubus_first_try_success_no_retry_log(
        self,
        mock_prepare,
        mock_wait_bindable,
        mock_telnet_session,
        mock_ubus_client,
        mock_enable_telnet,
        mock_run_single,
        mock_sleep,
    ):
        # 首次成功 → 无重试日志 + 无 sleep
        mock_enable_telnet.return_value = Mock(action="added_iface", message="ok")
        self._setup_standard_mocks(mock_prepare, mock_wait_bindable, mock_telnet_session, mock_enable_telnet, mock_run_single)

        request = _make_request()
        fake_app = _make_fake_app()
        LineCheckAssistant._sample_parameter_write_worker(fake_app, [request], 1, Mock())

        self.assertEqual(mock_enable_telnet.call_count, 1)
        mock_sleep.assert_not_called()
        mock_telnet_session.assert_called_once()

        log_messages = [call.args[0] for call in fake_app.log_queue.put.call_args_list if call.args]
        retry_logs = [msg for msg in log_messages if "次重试," in msg]
        self.assertEqual(len(retry_logs), 0, f"expected no retry logs on first-try success, got {retry_logs}")


if __name__ == "__main__":
    unittest.main()
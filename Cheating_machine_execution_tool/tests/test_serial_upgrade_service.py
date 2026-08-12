import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.network_ops import CommandResult
from src.models import FullPackageUpgradeRequest
from src.services.serial_upgrade_service import (
    BOOT_PASSWORD,
    BOOT_USERNAME,
    TRANSFER_TFTP_COMMAND,
    TRANSFER_TFTP_PUT,
    SerialUpgradeController,
    UpgradePowerCycleCoordinator,
    prepare_tftp_network,
    run_parallel_tftp_command_upgrades,
    run_parallel_tftp_put_upgrades,
    run_single_full_package_upgrade,
)


class FakeSession:
    def __init__(self, any_results=(), all_result=True, peek_text="", all_results=None):
        self.any_results = list(any_results)
        self.all_result = all_result
        # 若 all_results 是列表,每次 wait_for_all 按序弹出一个布尔;
        # 列表耗尽后返回 False,用于模拟首次未完成 + 重试时完成的场景。
        self.all_results = list(all_results) if all_results is not None else None
        self.writes = []
        self.peek_text = peek_text
        self.peek_calls = 0
        self.all_calls = 0

    def cursor(self):
        return 0

    def write(self, data, sensitive=False):
        self.writes.append((data, sensitive))

    def send_line(self, text, sensitive=False):
        self.writes.append((text.encode("utf-8") + b"\r", sensitive))

    def wait_for_any(self, _markers, _timeout, _cursor):
        return self.any_results.pop(0) if self.any_results else None

    def wait_for_all(self, _markers, _timeout, _cursor):
        self.all_calls += 1
        if self.all_results is not None:
            if not self.all_results:
                return False
            return self.all_results.pop(0)
        return self.all_result

    def peek_since(self, _cursor):
        self.peek_calls += 1
        return self.peek_text


class FastMonotonic:
    """测试用 monotonic:第一次返回 0,后续每次返回远超 deadline 的值。

    让 _wait_for_tftp_completion_or_arp_failure 的 polling 循环直接跳过、
    立即进入 final check,避免测试在真实 time.monotonic 下阻塞 300 秒。
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        if self.calls == 1:
            return 0.0
        return 1_000_000.0


class FakeSessionManager:
    def __init__(self, session):
        self.session = session
        self.released = []
        self.acquired = []

    def acquire_control(self, _owner, _settings, _log_path):
        self.acquired.append(_settings)
        return self.session

    def release(self, owner, port):
        self.released.append((owner, port))


class SerialUpgradeControllerTests(unittest.TestCase):
    @patch(
        "src.services.serial_upgrade_service.prepare_network_for_sample",
        return_value=CommandResult(True, "network ready"),
    )
    def test_prepare_tftp_network_waits_for_bindable_ip_before_strict_server(self, prepare_network):
        messages = []

        result = prepare_tftp_network(
            "VLAN139",
            "192.168.1.139",
            on_output=messages.append,
            sleep_fn=lambda _seconds: None,
            bind_ready_fn=lambda ip, timeout: ip == "192.168.1.139" and timeout == 15.0,
        )

        self.assertTrue(result.ok)
        self.assertIn("等待 TFTP 网卡 IP 192.168.1.139 完成绑定（最长 15 秒）。", messages)
        self.assertTrue(prepare_network.call_args.kwargs["reuse_if_ready"])

    @patch(
        "src.services.serial_upgrade_service.prepare_network_for_sample",
        return_value=CommandResult(True, "network ready"),
    )
    def test_prepare_tftp_network_reports_timeout_when_ip_never_becomes_bindable(self, prepare_network):
        result = prepare_tftp_network(
            "VLAN139",
            "192.168.1.139",
            sleep_fn=lambda _seconds: None,
            bind_ready_fn=lambda _ip, _timeout: False,
        )

        self.assertFalse(result.ok)
        self.assertIn("15 秒内仍不可绑定", result.message)
        self.assertTrue(prepare_network.call_args.kwargs["reuse_if_ready"])

    def test_parallel_power_cycle_coordinator_serializes_shared_power_port(self):
        """两个并发 power_on_channel 仍被串行化（同 COM 共享一个 lock）。"""
        supply_open_count = 0
        power_on_calls = 0
        active = []
        peak_active = []
        guard = threading.Lock()
        guard_open = threading.Lock()

        class FakeSupply:
            def __init__(self, port, *, on_output=None):
                self.port = port
                self._on_output = on_output
                self.opened = False
                self.closed = False

            def open(self):
                nonlocal supply_open_count
                with guard_open:
                    supply_open_count += 1
                self.opened = True

            def close(self):
                self.closed = True

            def power_on_channels(self, channels, *, on_channel_powered=None):
                nonlocal power_on_calls
                with guard:
                    power_on_calls += 1
                    active.append(list(channels))
                    peak_active.append(len(active))
                time.sleep(0.05)
                with guard:
                    active.pop()
                return list(channels)

        coordinator = UpgradePowerCycleCoordinator(
            sleep_fn=lambda _seconds: None,
            supply_factory=FakeSupply,
        )
        workers = [
            threading.Thread(
                target=coordinator.power_on_channel,
                args=("COM106", channel),
                kwargs={"wait_seconds": 10},
            )
            for channel in (1, 2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        # 锁串行化：同一 COM 任意时刻只允许一次 power_on_channels。
        self.assertEqual(max(peak_active), 1)
        self.assertEqual(power_on_calls, 2)
        # supply 在两次调用之间被复用 —— 同一 COM 只 open 一次。
        self.assertEqual(supply_open_count, 1)
        # close 还没发生，由调用方负责；这里 sanity-check supply 仍处于 opened 状态。
        self.assertTrue(all(callable(s.close) for s in coordinator._supplies.values()))

    def test_parallel_power_cycle_coordinator_closes_supplies_on_close(self):
        """coordinator.close() 关闭所有持有过的 supply。"""
        opened: list[str] = []
        closed: list[str] = []

        class FakeSupply:
            def __init__(self, port, *, on_output=None):
                self.port = port

            def open(self):
                opened.append(self.port)

            def close(self):
                closed.append(self.port)

            def power_on_channels(self, channels, *, on_channel_powered=None):
                return list(channels)

        coordinator = UpgradePowerCycleCoordinator(
            sleep_fn=lambda _seconds: None,
            supply_factory=FakeSupply,
        )
        coordinator.power_on_channel("COM106", 1, wait_seconds=0)
        coordinator.power_on_channel("COM107", 2, wait_seconds=0)

        self.assertEqual(sorted(opened), ["COM106", "COM107"])
        coordinator.close()
        self.assertEqual(sorted(closed), ["COM106", "COM107"])
        # 再次关闭幂等。
        coordinator.close()
        self.assertEqual(closed, ["COM106", "COM107"])

    def test_parallel_power_cycle_coordinator_skips_empty_power_port(self):
        supply_factory = Mock()
        messages = []
        coordinator = UpgradePowerCycleCoordinator(
            sleep_fn=lambda _seconds: None,
            supply_factory=supply_factory,
        )

        result = coordinator.power_on_channel("", 1, wait_seconds=0, on_output=messages.append)

        self.assertTrue(result.ok)
        self.assertIn("请手动重启样机后", result.message)
        self.assertEqual(messages, [result.message])
        supply_factory.assert_not_called()
        self.assertEqual(coordinator._supplies, {})

    @patch("src.services.serial_upgrade_service.run_single_full_package_upgrade")
    def test_parallel_tftp_command_limits_running_workers_and_continues_after_failure(self, run_upgrade):
        requests = [
            FullPackageUpgradeRequest(
                vlan=f"vlan10{index}",
                server_interface=f"VLAN10{index}",
                tftp_server_ip=f"192.168.1.10{index}",
                firmware_path=Path(r"F:\firmware\tclinux_allinone"),
                power_serial_port="COM106",
                final_username="root",
                final_password="secret",
                transfer_method=TRANSFER_TFTP_COMMAND,
                power_channel=index,
            )
            for index in (1, 2, 3)
        ]
        active = []
        peak_active = []
        active_lock = threading.Lock()
        first_two_started = threading.Event()
        release = threading.Event()

        def fake_upgrade(request, *_args, **kwargs):
            with active_lock:
                active.append(request.vlan)
                peak_active.append(len(active))
                if len(active) == 2:
                    first_two_started.set()
            release.wait(2)
            with active_lock:
                active.remove(request.vlan)
            return CommandResult(request.vlan != "vlan101", f"{request.vlan} completed")

        run_upgrade.side_effect = fake_upgrade
        completed_events = []
        collected = []

        def run_scheduler():
            collected.extend(
                run_parallel_tftp_command_upgrades(
                    requests,
                    Mock(),
                    on_item_complete=lambda item: completed_events.append(item),
                )
            )

        runner = threading.Thread(target=run_scheduler)
        runner.start()
        self.assertTrue(first_two_started.wait(1))
        self.assertEqual(max(peak_active), 2)
        release.set()
        runner.join(3)

        self.assertFalse(runner.is_alive())
        self.assertEqual(run_upgrade.call_count, 3)
        self.assertTrue(all(call.kwargs["strict_tftp_bind"] for call in run_upgrade.call_args_list))
        self.assertEqual(len(completed_events), 3)
        self.assertEqual(len(collected), 3)
        self.assertFalse(next(item.result.ok for item in collected if item.request.vlan == "vlan101"))
        self.assertTrue(next(item.result.ok for item in collected if item.request.vlan == "vlan103"))

    @patch("src.services.serial_upgrade_service.run_single_full_package_upgrade")
    def test_parallel_tftp_put_limits_running_workers_and_continues_after_failure(self, run_upgrade):
        requests = [
            FullPackageUpgradeRequest(
                vlan=f"vlan10{index}",
                server_interface=f"VLAN10{index}",
                tftp_server_ip=f"192.168.1.10{index}",
                firmware_path=Path(r"F:\\firmware\\tclinux_allinone"),
                power_serial_port="COM106",
                final_username="root",
                final_password="secret",
                transfer_method=TRANSFER_TFTP_PUT,
                power_channel=index,
            )
            for index in (1, 2, 3)
        ]
        active = []
        peak_active = []
        active_lock = threading.Lock()
        first_two_started = threading.Event()
        release = threading.Event()

        def fake_upgrade(request, *_args, **_kwargs):
            with active_lock:
                active.append(request.vlan)
                peak_active.append(len(active))
                if len(active) == 2:
                    first_two_started.set()
            release.wait(2)
            with active_lock:
                active.remove(request.vlan)
            return CommandResult(request.vlan != "vlan101", f"{request.vlan} completed")

        run_upgrade.side_effect = fake_upgrade
        completed_events = []
        collected = []

        def run_scheduler():
            collected.extend(
                run_parallel_tftp_put_upgrades(
                    requests,
                    Mock(),
                    on_item_complete=lambda item: completed_events.append(item),
                )
            )

        runner = threading.Thread(target=run_scheduler)
        runner.start()
        self.assertTrue(first_two_started.wait(1))
        self.assertEqual(max(peak_active), 2)
        release.set()
        runner.join(3)

        self.assertFalse(runner.is_alive())
        self.assertEqual(run_upgrade.call_count, 3)
        coordinators = [call.kwargs["power_cycle_coordinator"] for call in run_upgrade.call_args_list]
        self.assertTrue(all(coordinator is coordinators[0] for coordinator in coordinators))
        self.assertTrue(all(call.kwargs["strict_tftp_bind"] is False for call in run_upgrade.call_args_list))
        self.assertEqual(len(completed_events), 3)
        self.assertEqual([item.request.vlan for item in collected], [request.vlan for request in requests])
        self.assertFalse(next(item.result.ok for item in collected if item.request.vlan == "vlan101"))
        self.assertTrue(next(item.result.ok for item in collected if item.request.vlan == "vlan103"))

    def test_parallel_tftp_put_rejects_other_transfer_method(self):
        request = FullPackageUpgradeRequest(
            vlan="vlan101",
            server_interface="VLAN101",
            tftp_server_ip="192.168.1.101",
            firmware_path=Path(r"F:\\firmware\\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_COMMAND,
            power_channel=1,
        )

        with self.assertRaisesRegex(ValueError, "Tftp Put"):
            run_parallel_tftp_put_upgrades([request], Mock())

    def test_tftp_command_requires_done_and_write_stage_result(self):
        session = FakeSession(all_result=True)
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller.send_tftp_command_and_wait("tftp 192.168.1.101:tclinux_allinone")

        self.assertTrue(result.ok)
        self.assertEqual(session.writes[0][0], b"tftp 192.168.1.101:tclinux_allinone\r")

    def test_boot_login_and_factory_reset_preserve_send_timing_order(self):
        event = threading.Event()
        event.set()
        session = FakeSession(any_results=["username:", None, "password:", "#"])
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.wait_for_boot_login(event, timeout_seconds=1)
        controller.restore_factory_if_enabled(True)

        self.assertTrue(result.ok)
        values = [item[0] for item in session.writes]
        self.assertIn(b"firstboot -y;reboot", values)
        factory_index = values.index(b"firstboot -y;reboot")
        # 一旦稳定命中 UserName，周期探测即停止；其后的两个回车仅用于提交用户名和密码。
        self.assertEqual(
            values[:factory_index],
            [b"\r", BOOT_USERNAME.encode("utf-8"), b"\r", BOOT_PASSWORD.encode("utf-8"), b"\r"],
        )
        self.assertEqual(values[factory_index + 1], b"\r")
        self.assertEqual(sleeps[-2:], [1, 8])

    def test_post_tftp_boot_marker_sends_reset_once(self):
        session = FakeSession(any_results=["boot"])
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        self.assertTrue(controller.monitor_post_tftp(seconds=1))
        self.assertEqual(session.writes, [(b"reset\r", False)])

    def test_restore_factory_logs_command_only_when_it_is_sent(self):
        session = FakeSession()
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)
        execution_log = []

        controller.restore_factory_if_enabled(False, on_command_sent=execution_log.append)
        self.assertEqual(execution_log, [])
        self.assertEqual(session.writes, [])

        controller.restore_factory_if_enabled(True, on_command_sent=execution_log.append)

        self.assertEqual(execution_log, ["TX firstboot -y;reboot"])
        self.assertEqual(session.writes, [(b"firstboot -y;reboot", False), (b"\r", False)])

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=False)
    @patch("src.services.serial_upgrade_service.upload_firmware")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    @patch("src.services.serial_upgrade_service.power_on_selected_channels", return_value=CommandResult(True, "powered on"))
    def test_full_package_upgrade_tftp_put_runs_full_flow_after_power_cycle(
        self,
        _power_on_selected_channels,
        _prepare_network,
        _upload_firmware,
        _monitor_post_tftp,
    ):
        """Tftp Put 升级流程在前置下电 + 上电后，看到 UserName 即登录 boot 并使用 TFTPy。"""
        # wait_for_any 调用顺序:
        #   1. wait_for_tftp_put_boot_username:username:
        #   2. login_tftp_put_boot_after_username:password / #
        #   3. login_final_system:login / password / #
        session = FakeSession(
            any_results=[
                "username:",
                "password:", "#",
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan102",
            server_interface="VLAN102",
            tftp_server_ip="192.168.1.102",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
            serial_port="COM8",
        )

        result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        self.assertEqual(manager.acquired[0].port, "COM8")

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=True)
    @patch("src.services.serial_upgrade_service.upload_firmware")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    def test_full_package_upgrade_tftp_put_continues_when_power_port_is_empty(
        self,
        _prepare_network,
        _upload_firmware,
        _monitor_post_tftp,
    ):
        session = FakeSession(
            any_results=["username:", "password:", "#", "login", "password", "#"]
        )
        messages = []
        request = FullPackageUpgradeRequest(
            vlan="vlan102",
            server_interface="VLAN102",
            tftp_server_ip="192.168.1.102",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
        )
        manager = FakeSessionManager(session)

        result = run_single_full_package_upgrade(
            request,
            manager,
            on_output=messages.append,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertIn("请手动重启样机后，再进行 Tftp Put boot 登录", "".join(messages))
        self.assertIn("请手动重启样机后", "".join(messages))
        # UserName 后直接进行 boot 登录，不再先登录最终系统或发送 reboot。
        decoded = [item[0].decode("utf-8", "ignore").rstrip("\r") for item in session.writes]
        self.assertIn(BOOT_USERNAME, decoded)
        self.assertNotIn("reboot", decoded)
        self.assertEqual(len(manager.released), 1)

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=False)
    @patch("src.services.serial_upgrade_service.upload_firmware")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    @patch("src.services.serial_upgrade_service.power_on_selected_channels", return_value=CommandResult(True, "powered on"))
    def test_tftp_put_waits_for_username_before_starting_boot_login(
        self,
        _power_on_selected_channels,
        _prepare_network,
        _upload_firmware,
        _monitor_post_tftp,
    ):
        """Tftp Put 前必须等待 1 秒、发送回车并确认 UserName，再提交 boot 凭据。"""
        events = []
        sleeps = []

        class RecordingSession(FakeSession):
            def wait_for_any(self, markers, timeout, cursor):
                result = super().wait_for_any(markers, timeout, cursor)
                events.append(("wait", tuple(markers), result))
                return result

        session = RecordingSession(
            any_results=[
                "username:",
                "password:", "#",
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan124",
            server_interface="VLAN124",
            tftp_server_ip="192.168.1.124",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="sdmc",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
        )

        result = run_single_full_package_upgrade(
            request,
            manager,
            sleep_fn=sleeps.append,
            on_output=lambda message: events.append(("message", message)),
        )

        self.assertTrue(result.ok)
        self.assertEqual(sleeps[0], 1.0)
        self.assertEqual(session.writes[:2], [(b"\r", False), (b"telecomadmin\r", False)])
        prompt_index = next(
            index
            for index, event in enumerate(events)
            if event == ("wait", ("username:", "user name:"), "username:")
        )
        status_index = next(
            index
            for index, event in enumerate(events)
            if event == ("message", "检测到 UserName 提示符，开始使用 boot 用户名和密码登录。")
        )
        self.assertLess(prompt_index, status_index)

    def test_tftp_put_boot_login_keeps_password_cursor_before_username_write(self):
        """回归：Password: 在用户名写入后立刻到达时，不能因新游标而漏检。"""

        class ImmediatePasswordSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.cursor_value = 0
                self.password_wait_cursors = []

            def cursor(self):
                return self.cursor_value

            def write(self, data, sensitive=False):
                super().write(data, sensitive)
                if data == b"telecomadmin\r":
                    # 模拟用户名刚写出时，串口读取线程已把 Password: 写入历史。
                    self.cursor_value = 1

            def wait_for_any(self, markers, timeout, cursor):
                if tuple(markers) == ("passvord:", "password:"):
                    self.password_wait_cursors.append(cursor)
                    return "password:" if cursor == 0 else None
                return "#"

        session = ImmediatePasswordSession()
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller.login_tftp_put_boot_after_username()

        self.assertTrue(result.ok)
        self.assertEqual(session.password_wait_cursors, [0])
        self.assertEqual(session.writes[:2], [(b"telecomadmin\r", False), (b"nE7jA%5m\r", True)])

    def test_tftp_put_boot_login_keeps_shell_cursor_before_password_write(self):
        """回归：ECNT> 在密码写入后立刻到达时，不能因新游标而漏检。"""

        class ImmediateShellSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.cursor_value = 0
                self.shell_wait_cursors = []

            def cursor(self):
                return self.cursor_value

            def write(self, data, sensitive=False):
                super().write(data, sensitive)
                if data == b"telecomadmin\r":
                    self.cursor_value = 1
                elif data == b"nE7jA%5m\r":
                    # 模拟密码刚写出时，串口读取线程已把 ECNT> 写入历史。
                    self.cursor_value = 2

            def wait_for_any(self, markers, timeout, cursor):
                if tuple(markers) == ("passvord:", "password:"):
                    return "password:"
                if "ecnt>" in markers:
                    self.shell_wait_cursors.append(cursor)
                    return "ecnt>" if cursor == 1 else None
                return None

        session = ImmediateShellSession()
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller.login_tftp_put_boot_after_username()

        self.assertTrue(result.ok)
        self.assertEqual(session.shell_wait_cursors, [1])

    def test_full_package_upgrade_tftp_put_power_cycles_before_existing_flow(self):
        """回归保护:Tftp Put 在现有 reboot → boot → TFTP 流程之前,
        必须由程控电源对当前通道执行一次下电 + 上电。"""
        session = FakeSession(
            any_results=[
                "username:",
                "password:", "#",
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan102",
            server_interface="VLAN102",
            tftp_server_ip="192.168.1.102",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
        )

        with patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=False), \
             patch("src.services.serial_upgrade_service.upload_firmware"), \
             patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready")), \
             patch("src.services.serial_upgrade_service.power_on_selected_channels") as direct_power, \
             patch("src.services.power_on_service.turn_on_selected_channels") as turn_on, \
             patch("src.services.power_on_service.turn_off_selected_channels") as turn_off:
            result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        # Tftp Put 必须先调用一次 power_on_selected_channels 完成下电 + 上电;
        # 参数必须精确指向本次请求对应的程控电源串口和通道。
        direct_power.assert_called_once()
        first_call = direct_power.call_args
        self.assertEqual(first_call.args[0], request.power_serial_port)
        self.assertEqual(list(first_call.args[1]), [request.power_channel])
        self.assertEqual(first_call.kwargs.get("wait_seconds", 0), 0)
        self.assertTrue(callable(first_call.kwargs["on_output"]))
        # 分通道间隔开关仍不在 Tftp Put 流程内出现,继续保持纯 cycle 语义。
        turn_on.assert_not_called()
        turn_off.assert_not_called()
        self.assertEqual(len(manager.released), 1)

    def test_full_package_upgrade_tftp_put_propagates_power_cycle_failure(self):
        """回归保护:Tftp Put 前置下电 + 上电失败时,直接返回失败结果,不进入 reboot 流程。"""
        session = FakeSession(
            any_results=[
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan102",
            server_interface="VLAN102",
            tftp_server_ip="192.168.1.102",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
        )

        with patch(
            "src.services.serial_upgrade_service.power_on_selected_channels",
            return_value=CommandResult(False, "程控电源直接上电失败：串口被占用"),
        ):
            result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertFalse(result.ok)
        self.assertIn("程控电源直接上电失败", result.message)
        # 下电 + 上电失败时不应触发任何 reboot / 串口登录交互
        decoded = [item[0].decode("utf-8", "ignore").rstrip("\r") for item in session.writes]
        self.assertNotIn("reboot", decoded)
        self.assertNotIn("login", decoded)
        self.assertEqual(len(manager.released), 1)

    def test_boot_login_uses_one_second_gap_between_username_and_enter(self):
        """回归：boot 登录每条指令间应留出 1 秒缓冲，避免贴在一起导致密码错位。

        现场：用户名输入太快会被 boot 菜单"吃掉"，表现为提示符一直停在
        "UserName: ftp 192..." 这种半截状态，无法进入密码提示符。
        """
        session = FakeSession(any_results=["username:", None, "password:", "#"])
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller._login_boot()

        self.assertTrue(result.ok)
        # username 写出后、休眠再 \r：第一次 sleep 来自用户名→\r;
        # 第二次 sleep 来自密码→\r。两次都应该是 1.0 秒而不是 0.3 秒。
        self.assertGreaterEqual(len(sleeps), 2)
        self.assertEqual(sleeps[0], 1.0)
        self.assertEqual(sleeps[1], 1.0)
        # 仍然保留 send 顺序:用户名、\r、密码、\r。
        values = [item[0] for item in session.writes]
        self.assertIn(BOOT_USERNAME.encode("utf-8"), values)
        password_bytes = [item[0] for item in session.writes if item[1]][0]
        self.assertEqual(password_bytes, BOOT_PASSWORD.encode("utf-8"))

    def test_login_boot_waits_for_password_after_username_enter_using_fresh_cursor(self):
        """回归：不能用用户名输入前缓存中的 Password: 提前发送密码。"""

        class CursorSession(FakeSession):
            def __init__(self):
                super().__init__(any_results=["username:", None, "password:", "#"])
                self.cursor_value = 0
                self.wait_calls = []

            def cursor(self):
                self.cursor_value += 1
                return self.cursor_value

            def wait_for_any(self, markers, timeout, cursor):
                self.wait_calls.append((tuple(markers), timeout, cursor))
                return super().wait_for_any(markers, timeout, cursor)

        session = CursorSession()
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller._login_boot()

        self.assertTrue(result.ok)
        self.assertEqual(session.wait_calls[0][2], 1)
        self.assertEqual(session.wait_calls[1][2], 1)
        self.assertEqual(session.wait_calls[2][2], 2)
        self.assertEqual(session.wait_calls[3][2], 3)
        values = [item[0] for item in session.writes]
        self.assertEqual(values[:5], [b"\r", BOOT_USERNAME.encode("utf-8"), b"\r", BOOT_PASSWORD.encode("utf-8"), b"\r"])

    def test_login_boot_rejects_password_received_before_username_submission(self):
        """首轮 UserName/Password 同时出现时不能填写任何凭据。"""
        session = FakeSession(
            any_results=[
                "username:", "password:",  # 上电过渡态：丢弃整轮
                "username:", None, "password:", "#",  # 下一轮稳定登录
            ]
        )
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller._login_boot(max_attempts=2)

        self.assertTrue(result.ok)
        values = [item[0] for item in session.writes]
        self.assertEqual(values[:2], [b"\r", b"\r"])
        self.assertEqual(values[2:], [BOOT_USERNAME.encode("utf-8"), b"\r", BOOT_PASSWORD.encode("utf-8"), b"\r"])

    def test_wait_for_boot_login_does_not_declare_success_on_orphan_prompt(self):
        """回归：wait_for_boot_login 不能仅凭残余的 # / > 直接宣告 boot 已就绪。

        必须先看到 UserName / Password 提示符并完成 _login_boot,才能宣告成功,
        否则 tftp 命令会被发到还没登录的 UserName 提示符上,变成 "UserName: ftp 192..."
        这种半截状态,后续走不下去。
        """
        # 模拟 FakeSession.pop 的顺序(每次 wait_for_any 消耗一个 marker):
        #   iter 1 wait_for_boot_login: >              ← 设备启动瞬态的 >,不能直接 return
        #   iter 2 wait_for_boot_login: username:      ← 真正的 boot 登录提示符
        #   iter 2 _login_boot 稳定窗口: None
        #   iter 2 _login_boot password: password:     ← 用户名回车后才开始等密码提示符
        #   iter 2 _login_boot result: >               ← 登录成功后看到 boot 菜单提示符
        session = FakeSession(any_results=[None, "username:", None, "password:", ">"])
        event = threading.Event()
        event.set()
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.wait_for_boot_login(event, timeout_seconds=5)

        self.assertTrue(result.ok)
        # 关键:第一个 > 没有让方法直接 return;之后看到 user prompt 才调用 _login_boot,
        # 所以 sleeps 至少包含用户名→\r 和密码→\r 各 1.0 秒。
        self.assertIn(1.0, sleeps)
        # 写出顺序:应包含用户名、密码(且密码走 sensitive=True)。
        writes_bytes = [item[0] for item in session.writes]
        self.assertIn(BOOT_USERNAME.encode("utf-8"), writes_bytes)
        self.assertIn(BOOT_PASSWORD.encode("utf-8"), writes_bytes)

    def test_wait_for_boot_login_returns_failure_if_no_user_prompt_ever_appears(self):
        """回归:即便看到 # / >,若始终不出现 user/password 提示符,必须返回失败而不是误判成功。"""
        # 一直只有 > 没有 user prompt,模拟极端瞬态:几十次 > 都没有任何 user prompt。
        session = FakeSession(any_results=[">"] * 30)
        event = threading.Event()
        event.set()
        controller = SerialUpgradeController(session, sleep_fn=lambda _s: None)

        result = controller.wait_for_boot_login(event, timeout_seconds=1)

        self.assertFalse(result.ok)

    def test_login_boot_recovers_when_serial_port_is_closed_mid_flow(self):
        """回归:串口在 login_boot 期间被关闭(例如 COM 口被拔除),必须返回失败而非抛出未捕获异常。

        现场症状:boot_worker 抛出 "串口 COM39 未打开" 异常,daemon 线程死亡,
        主线程只能看到笼统的 "boot 登录线程未返回结果。",看不到底层原因。
        这里改为会话层异常被 _login_boot 捕获并返回 ok=False 的 CommandResult。
        """
        class ClosingSession(FakeSession):
            """第一次 send_line 写入后就关闭,模拟 COM 口在登录中途被移除。"""
            def __init__(self):
                super().__init__(any_results=["username:", "username:"])
                self.closed = False

            def write(self, data, sensitive=False):  # noqa: D401
                super().write(data, sensitive)
                if not self.closed and len(self.writes) >= 1:
                    self.closed = True
                    raise RuntimeError("串口 COM39 未打开(open() 失败或从未调用,常见原因:"
                                       "该 COM 端口不存在、PC 串口驱动异常或权限不足)")

        session = ClosingSession()
        controller = SerialUpgradeController(session, sleep_fn=lambda _s: None)

        result = controller._login_boot()

        self.assertFalse(result.ok)
        self.assertIn("串口交互异常", result.message)
        # 不会让 daemon 线程因为未捕获的 RuntimeError 死亡。

    def test_login_boot_salvages_after_garbled_username_echo(self):
        """Tftp指令：用户名回显含 UTF-8 替换标记时,盲发密码一次,命中 shell 提示符即成功。

        模拟现场 UART 输出损坏:UserName/Password 都是乱码,但 UART 输入正常,
        样机实际已接受账号,密码后能进入 shell。
        """
        # pop 顺序:
        #   1) USERNAME_PROMPTS 等待 → "username:"
        #   2) Password 稳定窗口检查 → None (没有 Password,继续)
        #   3) Password 30s 等待 → None (超时,乱码导致没有 Password:)
        #   4) salvage 的 SHELL 等待 → ">" (盲发密码后命中)
        session = FakeSession(
            any_results=[
                "username:", None, None, ">",
            ],
            peek_text="}\r\nC�H�\r\n",
        )
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller._login_boot(max_attempts=1)

        self.assertTrue(result.ok)
        self.assertIn("用户名回显乱码", result.message)
        # 验证写出顺序:探测 \r、username、\r(用户名)、password、\r(密码)
        values = [item[0] for item in session.writes]
        self.assertEqual(values, [b"\r", BOOT_USERNAME.encode("utf-8"), b"\r", BOOT_PASSWORD.encode("utf-8"), b"\r"])
        # 盲发密码时仍走 sensitive 标记
        password_writes = [item for item in session.writes if item[0] == BOOT_PASSWORD.encode("utf-8")]
        self.assertEqual(password_writes, [(BOOT_PASSWORD.encode("utf-8"), True)])

    def test_login_boot_garbled_salvage_without_shell_falls_through_to_retry(self):
        """Tftp指令：乱码回显 + 盲发密码后无 shell → 走 continue 常规重试。"""
        # iter 1 顺序:UserName / Password 稳定 / Password 30s 超时 / salvage shell 超时 → 失败 continue
        # iter 2 顺序:UserName / Password 稳定 / Password 命中 / shell 命中 → 成功
        session = FakeSession(
            any_results=[
                "username:", None, None, None,  # iter 1
                "username:", None, "password:", "#",  # iter 2
            ],
            peek_text="}\r\nC�H�\r\n",
        )
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller._login_boot(max_attempts=3)

        self.assertTrue(result.ok)
        # iter1: \r 探测 + username/\r + 盲发 password/\r;iter2: \r 探测 + username/\r + password/\r
        values = [item[0] for item in session.writes]
        self.assertEqual(
            values,
            [
                b"\r",  # iter1 探测
                BOOT_USERNAME.encode("utf-8"), b"\r",
                BOOT_PASSWORD.encode("utf-8"), b"\r",
                b"\r",  # iter2 探测
                BOOT_USERNAME.encode("utf-8"), b"\r",
                BOOT_PASSWORD.encode("utf-8"), b"\r",
            ],
        )

    def test_login_boot_clean_timeout_does_not_salvage(self):
        """Tftp指令：超时但响应无乱码 → 不盲发,避免误伤正常延迟场景。"""
        # iter 1:Password 超时;peek_since 返回干净文本(无 U+FFFD);不走 salvage → continue
        # iter 2:同 iter 1 → 循环结束 → 失败
        session = FakeSession(
            any_results=[
                "username:", None,  # iter 1
                "username:", None,  # iter 2
                "username:", None,  # iter 3
            ],
            peek_text="clean text without replacement markers",
        )
        controller = SerialUpgradeController(session, sleep_fn=lambda _s: None)

        result = controller._login_boot(max_attempts=3)

        self.assertFalse(result.ok)
        # 全程未写密码(只写 \r 探测 + username + \r)
        values = [item[0] for item in session.writes]
        for value in values:
            self.assertNotEqual(value, BOOT_PASSWORD.encode("utf-8"))

    def test_tftp_put_salvages_after_garbled_username_echo(self):
        """Tftp Put：用户名回显含 UTF-8 替换标记时,盲发密码一次,命中 shell 提示符即成功。"""
        # Tftp Put 把 username + \r 一次写出,然后等 Password 提示符
        # Password 超时、peek 出乱码、盲发密码等 shell 命中 "ecnt>"
        session = FakeSession(
            any_results=[
                None, "ecnt>",  # 等 Password 超时 + 盲发等 shell 命中
            ],
            peek_text="}\r\nC!���ݽɑ�\r\n",
        )
        controller = SerialUpgradeController(session, sleep_fn=lambda _s: None)

        result = controller.login_tftp_put_boot_after_username()

        self.assertTrue(result.ok)
        self.assertIn("用户名回显乱码", result.message)
        values = [item[0] for item in session.writes]
        self.assertEqual(values, [
            b"telecomadmin\r",
            BOOT_PASSWORD.encode("utf-8"), b"\r",
        ])
        password_writes = [item for item in session.writes if item[0] == BOOT_PASSWORD.encode("utf-8")]
        self.assertEqual(password_writes, [(BOOT_PASSWORD.encode("utf-8"), True)])

    def test_tftp_put_clean_timeout_still_fails_without_salvage(self):
        """Tftp Put：超时但响应无乱码 → 立即失败,无盲发。"""
        session = FakeSession(
            any_results=[None],  # Password 等不到
            peek_text="just slow response, no garbled bytes",
        )
        controller = SerialUpgradeController(session, sleep_fn=lambda _s: None)

        result = controller.login_tftp_put_boot_after_username()

        self.assertFalse(result.ok)
        self.assertIn("boot 登录未检测到 Password 提示符", result.message)
        # 只写了 username + \r,没写密码
        values = [item[0] for item in session.writes]
        self.assertEqual(values, [b"telecomadmin\r"])

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=True)
    @patch("src.services.serial_upgrade_service.TftpServerHandle")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    @patch("src.services.serial_upgrade_service.power_on_selected_channels", return_value=CommandResult(True, "powered"))
    def test_tftp_command_branch_waits_one_second_after_power_supply_before_first_carriage_return(
        self,
        _power_on_selected_channels,
        _prepare_network,
        _tftp_server_handle,
        _monitor_post_tftp,
    ):
        """回归:程控电源动作完成后应等待 1 秒再启动 worker,确保上电瞬态稳定。

        现场需求:power_on_selected_channels 完成后间隔 1 秒发送第一帧 \r,
        避免上电瞬态被误判为 boot 提示符。
        """
        sleeps: list[float] = []
        writes_before_boot_release: list[tuple[bytes, bool]] = []
        # wait_for_any 调用顺序:
        #   wait_for_boot_login → _login_boot:username: / password: / #
        #   login_final_system:login / password / #
        session = FakeSession(
            any_results=[
                "username:", None, "password:", "#",
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)

        def fake_power_on(*_args, on_channel_powered=None, **_kwargs):
            # 回调在电源函数尚未返回时触发，不能因此提前放行 boot 登录线程。
            on_channel_powered(1)
            return CommandResult(True, "powered")

        def record_sleep(seconds: float) -> None:
            if not sleeps:
                writes_before_boot_release.extend(session.writes)
            sleeps.append(seconds)

        _power_on_selected_channels.side_effect = fake_power_on
        request = FullPackageUpgradeRequest(
            vlan="vlan101",
            server_interface="VLAN101",
            tftp_server_ip="192.168.1.101",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_COMMAND,
            power_channel=1,
        )

        result = run_single_full_package_upgrade(
            request, manager, sleep_fn=record_sleep, on_output=lambda _line: None
        )

        self.assertTrue(result.ok)
        # 第一笔 sleep 必须是程控电源完成后的 1.0 秒缓冲。
        self.assertGreaterEqual(len(sleeps), 1)
        self.assertEqual(sleeps[0], 1.0)
        self.assertEqual(writes_before_boot_release, [])
        _power_on_selected_channels.assert_called()

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=True)
    @patch("src.services.serial_upgrade_service.TftpServerHandle")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    def test_tftp_command_branch_invokes_programmable_power_supply(
        self,
        _prepare_network,
        _tftp_server_handle,
        _monitor_post_tftp,
    ):
        """Tftp指令(样机主动拉固件)链路必须由程控电源上电驱动。

        在 wait_for_boot_login 触发之前由 power_on_selected_channels 写入上电帧,
        业务侧不依赖样机手动上电。上电失败立即 cancel 并返回。
        """
        # wait_for_any 调用顺序:
        #   wait_for_boot_login → _login_boot:username: / password: / #
        #   login_final_system:login / password / #
        session = FakeSession(
            any_results=[
                "username:", None, "password:", "#",
                "login", "password", "#",
            ]
        )
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan101",
            server_interface="VLAN101",
            tftp_server_ip="192.168.1.101",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_COMMAND,
            power_channel=1,
        )

        with patch(
            "src.services.serial_upgrade_service.power_on_selected_channels",
            return_value=CommandResult(True, "powered on"),
        ) as direct_power, \
             patch("src.services.power_on_service.turn_on_selected_channels") as turn_on, \
             patch("src.services.power_on_service.turn_off_selected_channels") as turn_off:
            result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        # Tftp指令 链路至少调用一次程控电源上电(初始上电,可配 repower)。
        self.assertGreaterEqual(direct_power.call_count, 1)
        first_call = direct_power.call_args
        # 第一次调用应传入本次请求对应的程控电源串口 / 通道号。
        self.assertEqual(first_call.args[0], request.power_serial_port)
        self.assertEqual(list(first_call.args[1]), [request.power_channel])
        self.assertTrue(callable(first_call.kwargs["on_channel_powered"]))
        self.assertTrue(callable(first_call.kwargs["on_output"]))
        # turn_on / turn_off 仍不调用(它们是分通道间隔开关,本次没有需求)。
        turn_on.assert_not_called()
        turn_off.assert_not_called()
        self.assertEqual(len(manager.released), 1)

    def test_tftp_command_does_not_retry_on_first_attempt_success(self):
        """首次尝试即检测到 done + write 时只发一条命令,不打印重试日志。"""
        session = FakeSession(all_result=True, peek_text="Bytes transferred = 1000\ndone\nwrite")
        sleeps: list[float] = []
        output: list[str] = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
            on_output=output.append,
        )

        self.assertTrue(result.ok)
        # 只有一条 tftp 命令,无重试。
        self.assertEqual(len(session.writes), 1)
        self.assertEqual(session.writes[0][0], b"tftp 192.168.1.101:tclinux_allinone\r")
        # 首次成功不打印任何重试 / ARP 相关日志。
        self.assertFalse(any("自动重试 TFTP" in line for line in output))
        self.assertFalse(any("ARP Retry count exceeded" in line for line in output))
        self.assertEqual(sleeps, [])

    def test_tftp_command_retries_on_arp_failure_then_succeeds(self):
        """首次命中 ARP 失败 + U-Boot>,第二次成功:共发 2 次命令,第 1 次后 sleep 1 秒。"""
        # 序列:1st attempt helper 见到 ARP 失败 → 2nd attempt helper 见到 done + write
        session = FakeSession(
            all_results=[False, True],
            peek_text="Using eth@1fb59000 device\nTFTP from server 192.168.1.101\n"
            "ARP Retry count exceeded; starting again\nU-Boot> ",
        )
        sleeps: list[float] = []
        output: list[str] = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
            on_output=output.append,
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(session.writes), 2)
        self.assertEqual(session.writes[0][0], b"tftp 192.168.1.101:tclinux_allinone\r")
        self.assertEqual(session.writes[1][0], b"tftp 192.168.1.101:tclinux_allinone\r")
        # 1 次 retry sleep(1 秒)
        self.assertEqual(sleeps, [1.0])
        # 重试相关日志完整:
        #   - 第 1 次 ARP 失败时还剩 2 次自动重试
        #   - 第 2 次发送属于自动重试 (第 2/3 次)
        #   - 第 2 次检测到完成标记
        self.assertTrue(any("ARP Retry count exceeded" in line and "剩余 2 次自动重试" in line for line in output))
        self.assertTrue(any("自动重试 TFTP 命令" in line and "第 2/3 次" in line for line in output))
        self.assertTrue(any("第 2 次尝试时检测到完成标记" in line for line in output))

    def test_tftp_command_retries_three_times_then_fails(self):
        """3 次尝试都遇 ARP 失败 → 失败。共发 3 条命令,2 次 sleep。"""
        session = FakeSession(
            all_results=[False, False, False],
            peek_text="ARP Retry count exceeded; starting again\nU-Boot> ",
        )
        sleeps: list[float] = []
        output: list[str] = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
            on_output=output.append,
        )

        self.assertFalse(result.ok)
        self.assertIn("已重试 3 次仍未成功", result.message)
        self.assertEqual(len(session.writes), 3)
        # 2 次 retry sleep,3 条命令之间间隔 1 秒。
        self.assertEqual(sleeps, [1.0, 1.0])
        # 每次尝试都有 ARP 失败日志,最后一次打印已达最大次数。
        arp_logs = [line for line in output if "ARP Retry count exceeded" in line]
        self.assertEqual(len(arp_logs), 3)
        self.assertTrue(any("已达最大重试次数 3" in line for line in output))
        self.assertFalse(any("检测到完成标记" in line for line in output))

    def test_tftp_command_does_not_retry_without_arp_marker(self):
        """peek_since 不含 ARP 失败模式 → 不重试,直接返回超时失败。"""
        # 强制 polling loop 不进入,只走 final check;peek_text 既无 arp marker 也无 u-boot>。
        session = FakeSession(
            all_result=False,
            peek_text="Loading: ##################################################",
        )
        sleeps: list[float] = []
        output: list[str] = []
        controller = SerialUpgradeController(
            session, sleep_fn=sleeps.append, monotonic_fn=FastMonotonic()
        )

        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
            on_output=output.append,
        )

        self.assertFalse(result.ok)
        self.assertIn("等待样机串口 TFTP 完成标记超时", result.message)
        # 只有 1 次尝试,1 条命令,无 sleep。
        self.assertEqual(len(session.writes), 1)
        self.assertEqual(sleeps, [])
        # 不打印任何重试 / ARP 日志。
        self.assertFalse(any("自动重试 TFTP" in line for line in output))
        self.assertFalse(any("ARP Retry count exceeded" in line for line in output))

    def test_tftp_command_does_not_retry_when_arp_marker_missing_u_boot_prompt(self):
        """仅有 ARP 失败标记但样机未返回 U-Boot>(卡在 Loading)→ 不重试。"""
        session = FakeSession(
            all_result=False,
            peek_text="Loading: *\nARP Retry count exceeded; starting again\nLoading: *",
        )
        output: list[str] = []
        controller = SerialUpgradeController(
            session, sleep_fn=lambda _: None, monotonic_fn=FastMonotonic()
        )

        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
            on_output=output.append,
        )

        self.assertFalse(result.ok)
        self.assertEqual(len(session.writes), 1)
        self.assertFalse(any("自动重试 TFTP" in line for line in output))
        self.assertFalse(any("ARP Retry count exceeded" in line for line in output))

    def test_tftp_command_skips_retry_log_when_on_output_not_provided(self):
        """不传 on_output 时,即使命中 ARP 失败也不会抛异常,只是不打印日志。"""
        session = FakeSession(
            all_results=[False, True],
            peek_text="ARP Retry count exceeded; starting again\nU-Boot> ",
        )
        controller = SerialUpgradeController(session, sleep_fn=lambda _: None)

        # 不传 on_output 也应正常工作,不抛异常。
        result = controller.send_tftp_command_and_wait(
            "tftp 192.168.1.101:tclinux_allinone",
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(session.writes), 2)

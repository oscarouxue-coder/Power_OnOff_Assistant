import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.network_ops import CommandResult
from src.models import FullPackageUpgradeRequest
from src.services.serial_upgrade_service import BOOT_PASSWORD, BOOT_USERNAME, TRANSFER_TFTP_COMMAND, TRANSFER_TFTP_PUT, SerialUpgradeController, run_single_full_package_upgrade


class FakeSession:
    def __init__(self, any_results=(), all_result=True):
        self.any_results = list(any_results)
        self.all_result = all_result
        self.writes = []

    def cursor(self):
        return 0

    def write(self, data, sensitive=False):
        self.writes.append((data, sensitive))

    def send_line(self, text, sensitive=False):
        self.writes.append((text.encode("utf-8") + b"\r", sensitive))

    def wait_for_any(self, _markers, _timeout, _cursor):
        return self.any_results.pop(0) if self.any_results else None

    def wait_for_all(self, _markers, _timeout, _cursor):
        return self.all_result


class FakeSessionManager:
    def __init__(self, session):
        self.session = session
        self.released = []

    def acquire_control(self, _owner, _settings, _log_path):
        return self.session

    def release(self, owner, port):
        self.released.append((owner, port))


class SerialUpgradeControllerTests(unittest.TestCase):
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

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=False)
    @patch("src.services.serial_upgrade_service.upload_firmware")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    def test_full_package_upgrade_skips_programmable_power_supply(
        self,
        _prepare_network,
        _upload_firmware,
        _monitor_post_tftp,
    ):
        """升级流程不再操作程控电源:串口开启后直接登录超级用户,
        reboot 中断 → boot 登录 → TFTP → 最终系统登录 → 恢复出厂。"""
        # wait_for_any 调用顺序:
        #   1. login_final_system(第 1 次):login / password / #
        #   2. interrupt_boot_with_enter:username:
        #   3. _login_boot:username: / 稳定窗口 / password: / #
        #   4. login_final_system(第 2 次):login / password / #
        session = FakeSession(
            any_results=[
                "login", "password", "#",
                "username:",
                "username:", None, "password:", "#",
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

        result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        # 写入序列里必须包含 reboot,且不应再有任何程控电源协议帧。
        decoded = [item[0].decode("utf-8", "ignore").rstrip("\r") for item in session.writes]
        self.assertIn("reboot", decoded)
        self.assertEqual(len(manager.released), 1)

    def test_full_package_upgrade_does_not_invoke_power_supply_module(self):
        """回归保护:升级流程不得再调用 power_on_service 里的任何函数。"""
        session = FakeSession(
            any_results=[
                "login", "password", "#",
                "username:",
                "username:", None, "password:", "#",
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
             patch("src.services.power_on_service.power_on_selected_channels") as direct_power, \
             patch("src.services.power_on_service.turn_on_selected_channels") as turn_on, \
             patch("src.services.power_on_service.turn_off_selected_channels") as turn_off:
            result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        direct_power.assert_not_called()
        turn_on.assert_not_called()
        turn_off.assert_not_called()

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

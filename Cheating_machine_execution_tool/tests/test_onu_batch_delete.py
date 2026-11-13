from dataclasses import replace
import threading
import unittest
from unittest.mock import Mock

from src.core.zte_olt_telnet import OltCommandError, OltTelnetError, OperationCancelled
from src.models.onu_registration_models import OltConnection, OnuOperationResult, RegisteredOnu
from src.services.onu_batch_delete_service import OnuBatchDeleteService
from src.services.onu_registration_service import OnuRegistrationService, driver_for_family


CONNECTION = OltConnection("192.0.2.1", "192.0.2.2", "test", "test")


def candidate(family="C600", onu_id=1):
    pon, onu = ("gpon-olt_", "gpon-onu_") if family == "C300" else ("gpon_olt-", "gpon_onu-")
    return RegisteredOnu(family, pon + "1/1/1", onu + f"1/1/1:{onu_id}", onu_id,
                         "working" if onu_id == 1 else "OffLine", f"TEST{onu_id:08X}", "TEST-TYPE")


class ScriptedSession:
    def __init__(self, target, cancel, failure="", fail_at="no onu", stop_after=""):
        self.target, self.cancel = target, cancel
        self.failure, self.fail_at, self.stop_after = failure, fail_at, stop_after
        self.commands = []
        self.closed = False
        self.deleted = False

    def connect(self):
        if self.failure == "login":
            raise OltTelnetError("OLT 登录失败")

    def execute(self, command, **_kwargs):
        if self.cancel.is_set():
            raise OperationCancelled("操作已停止")
        self.commands.append(command)
        if self.failure == "verify_timeout" and self.deleted and command.startswith("show "):
            raise OltTelnetError("回读超时")
        if command.startswith(self.fail_at):
            if self.failure == "cli":
                raise OltCommandError(command, "%Error")
            if self.failure == "transport":
                raise OltTelnetError("OLT 关闭了 Telnet 连接")
            if self.failure == "unexpected":
                raise ValueError("unexpected")
        if command.startswith("no onu "):
            self.deleted = True
        if self.stop_after and command.startswith(self.stop_after):
            self.cancel.set()
        if command.startswith("show "):
            if self.deleted and self.failure != "verify":
                return "ONU data is null.\nZXAN#"
            sn = "CHANGED00000001" if self.failure == "sn" else self.target.serial_number
            return f"{self.target.onu_interface} TEST-TYPE sn SN:{sn} ready\nZXAN#"
        return "ZXAN#"

    def best_effort_end(self):
        pass

    def close(self):
        self.closed = True


class BatchDeleteTests(unittest.TestCase):
    def run_batch(self, family="C600", failures=None, stop_after="", targets=None, cancel=None):
        targets = targets or tuple(candidate(family, index) for index in (1, 2, 3))
        sessions = []
        logs = []
        cancel = cancel or threading.Event()

        def factory(connection, logger=None, cancel_event=None):
            self.assertEqual(connection, CONNECTION)
            target = targets[len(sessions)]
            session = ScriptedSession(target, cancel_event, (failures or {}).get(target.onu_id, ""),
                                      stop_after=stop_after if not sessions else "")
            sessions.append(session)
            return session

        service = OnuBatchDeleteService(logs.append, OnuRegistrationService(logs.append, session_type=factory))
        result = service.delete(family, CONNECTION, targets[0].pon_interface, targets, cancel)
        return result, sessions, logs

    def test_both_families_success_in_query_order_with_independent_sessions_and_no_write(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                targets = tuple(candidate(family, index) for index in (3, 1, 2))
                result, sessions, logs = self.run_batch(family, targets=targets)
                self.assertTrue(result.ok, result.message)
                self.assertEqual([item.candidate for item in result.items], list(targets))
                self.assertEqual(len(sessions), 3)
                for target, session in zip(targets, sessions):
                    identity = driver_for_family(family).build_delete_identity_command(target)
                    self.assertEqual(session.commands.count(identity), 2)
                    self.assertEqual([line for line in session.commands if line.startswith("no onu ")], [f"no onu {target.onu_id}"])
                    self.assertLess(session.commands.index(identity), session.commands.index(f"no onu {target.onu_id}"))
                    self.assertNotIn("write", session.commands)
                    self.assertTrue(session.closed)
                self.assertIn("成功 3 台", logs[-1])

    def test_only_selected_single_target_is_processed(self):
        result, sessions, _logs = self.run_batch(targets=(candidate(onu_id=2),))
        self.assertTrue(result.ok)
        self.assertEqual(len(sessions), 1)
        self.assertIn("no onu 2", sessions[0].commands)
        self.assertNotIn("no onu 1", sessions[0].commands)

    def test_target_failures_continue_and_are_not_counted_as_success(self):
        for failure in ("cli", "sn", "verify"):
            with self.subTest(failure=failure):
                result, sessions, logs = self.run_batch(failures={1: failure})
                self.assertFalse(result.ok)
                self.assertEqual([item.status for item in result.items], ["failed", "success", "success"])
                self.assertEqual(len(sessions), 3)
                if failure == "sn":
                    self.assertNotIn("no onu 1", sessions[0].commands)
                    self.assertFalse(result.items[0].operation.outcome_uncertain)
                else:
                    self.assertIn("结果待核实", result.items[0].message)
                self.assertIn("失败 1 台", logs[-1])

    def test_transport_or_login_failure_stops_remaining_targets_without_retry(self):
        for failure in ("transport", "login", "verify_timeout", "unexpected"):
            with self.subTest(failure=failure):
                result, sessions, _logs = self.run_batch(failures={1: failure})
                self.assertEqual([item.status for item in result.items], ["failed", "not_executed", "not_executed"])
                self.assertEqual(len(sessions), 1)
                self.assertTrue(sessions[0].closed)
                if failure in ("transport", "verify_timeout", "unexpected"):
                    self.assertIn("结果待核实", result.items[0].message)

    def test_stop_before_start_sends_no_commands(self):
        cancel = threading.Event()
        cancel.set()
        result, sessions, _logs = self.run_batch(cancel=cancel)
        self.assertEqual(sessions, [])
        self.assertTrue(all(item.status == "not_executed" for item in result.items))

    def test_stop_before_delete_does_not_mark_unknown_or_start_next_target(self):
        result, sessions, _logs = self.run_batch(stop_after="configure terminal")
        self.assertEqual(len(sessions), 1)
        self.assertNotIn("no onu 1", sessions[0].commands)
        self.assertEqual(result.items[0].operation.error_kind, "cancelled")
        self.assertFalse(result.items[0].operation.outcome_uncertain)
        self.assertEqual(result.items[1].status, "not_executed")

    def test_stop_after_delete_marks_result_unknown_and_never_success(self):
        result, sessions, _logs = self.run_batch(stop_after="no onu ")
        self.assertEqual(len(sessions), 1)
        self.assertIn("结果待核实", result.items[0].message)
        self.assertEqual([item.status for item in result.items], ["failed", "not_executed", "not_executed"])

    def test_stop_between_targets_retains_verified_success(self):
        cancel = threading.Event()
        single = Mock()

        def completed(*_args):
            cancel.set()
            return OnuOperationResult(True, "已回读确认")

        single.delete_registered_onu.side_effect = completed
        targets = (candidate(), candidate(onu_id=2))
        result = OnuBatchDeleteService(registration_service=single).delete("C600", CONNECTION, targets[0].pon_interface, targets, cancel)
        self.assertEqual([item.status for item in result.items], ["success", "not_executed"])
        single.delete_registered_onu.assert_called_once()

    def test_missing_sn_skips_target_and_continues(self):
        single = Mock()
        single.delete_registered_onu.return_value = OnuOperationResult(True, "OK")
        targets = (replace(candidate(), serial_number=""), candidate(onu_id=2))
        result = OnuBatchDeleteService(registration_service=single).delete("C600", CONNECTION, targets[0].pon_interface, targets)
        self.assertEqual([item.status for item in result.items], ["failed", "success"])
        self.assertIn("缺少 SN", result.items[0].message)
        self.assertEqual(single.delete_registered_onu.call_args.args[2], targets[1])

    def test_invalid_target_snapshot_rejects_whole_batch_before_connection(self):
        first = candidate()
        invalid_groups = (
            (first, first), (first, candidate("C300", 2)),
            (first, replace(candidate(onu_id=2), pon_interface="gpon_olt-1/1/2")),
            (first, replace(candidate(onu_id=2), onu_interface="gpon_onu-1/1/1:3")),
            (first, replace(candidate(onu_id=2), onu_id=-1)),
            (first, replace(candidate(onu_id=2), onu_id="2")),
        )
        for targets in invalid_groups:
            with self.subTest(targets=targets):
                single = Mock()
                result = OnuBatchDeleteService(registration_service=single).delete("C600", CONNECTION, first.pon_interface, targets)
                self.assertTrue(all(item.status == "not_executed" for item in result.items))
                single.delete_registered_onu.assert_not_called()

    def test_bad_connection_and_empty_batch_never_start_deletion(self):
        single = Mock()
        service = OnuBatchDeleteService(registration_service=single)
        result = service.delete("C600", replace(CONNECTION, source_ip=""), candidate().pon_interface, (candidate(),))
        self.assertEqual(result.items[0].status, "not_executed")
        self.assertFalse(service.delete("C600", CONNECTION, candidate().pon_interface, ()).ok)
        single.delete_registered_onu.assert_not_called()

    def test_unexpected_service_exception_aborts_without_retry(self):
        single = Mock()
        single.delete_registered_onu.side_effect = ValueError("unexpected")
        targets = (candidate(), candidate(onu_id=2))
        result = OnuBatchDeleteService(registration_service=single).delete("C600", CONNECTION, targets[0].pon_interface, targets)
        self.assertEqual([item.status for item in result.items], ["failed", "not_executed"])
        single.delete_registered_onu.assert_called_once()


if __name__ == "__main__":
    unittest.main()

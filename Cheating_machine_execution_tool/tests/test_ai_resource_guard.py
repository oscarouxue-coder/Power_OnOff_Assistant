"""A1: simulated execution only; no host command, COM or DUT is accessed."""
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

import test_ai_actions as action_fixture
import test_ai_conversation as conversation_fixture
from test_ai_core import chat
from test_ai_debug import TARGET
from src.models.ai_permissions import ASK, AUTO, FULL
from src.models.ai_actions import ActionAssessment
from src.core.ai_debug_transport import DebugSessionInvalid
from src.ui.ai_serial_bridge import AiSerialBridge
import threading
import time
from types import SimpleNamespace


class LocalResourceGuardTests(unittest.TestCase):
    setUp = action_fixture.ActionServiceTests.setUp
    execute = action_fixture.ActionServiceTests.execute

    def test_device_bound_local_command_is_blocked_in_all_permission_modes(self):
        for mode in (ASK, AUTO, FULL):
            with self.subTest(mode=mode):
                self.owner.permissions = Mock()
                self.owner.permissions.status.return_value = {"mode": mode, "grant_id": "test"}
                self.owner.scope_busy = Mock(return_value=True)
                with patch("src.services.ai_action_service.run_local_command") as run, patch.object(self.service, "_wait_approval", return_value=False):
                    with self.assertRaises(ValueError):
                        self.execute()
                    run.assert_not_called()
                    self.review.assert_not_called()

    def test_bound_file_write_is_blocked_without_changing_file(self):
        path = Path(self.temp) / "keep.txt"
        path.write_text("original", encoding="utf-8")
        self.owner.diagnostic.busy.return_value = True
        with self.assertRaises(ValueError):
            self.execute("write_local_file", {"path": str(path), "content": "changed"})
        self.assertEqual(path.read_text(encoding="utf-8"), "original")

    def test_shared_resource_alone_blocks_bound_command(self):
        self.owner.diagnostic.shared_busy = Mock(return_value=True)
        with patch("src.services.ai_action_service.run_local_command") as run:
            with self.assertRaises(ValueError):
                self.execute()
            run.assert_not_called()

    def test_host_busy_blocks_even_when_ai_target_subset_is_idle(self):
        self.owner.diagnostic.host_busy = Mock(return_value=True)
        self.owner.diagnostic.targets = {}
        self.owner.scope_busy = Mock(return_value=False)
        with patch("src.services.ai_action_service.run_local_command") as run:
            with self.assertRaises(ValueError): self.execute()
            run.assert_not_called()

    def test_host_snapshot_detects_power_test_without_ai_target_selection(self):
        from line_check_assistant.app import LineCheckAssistant
        app = SimpleNamespace(power_test_running=True, power_test_resume_session=None)
        self.assertTrue(LineCheckAssistant._ai_target_busy(app, None))

    def test_busy_state_is_rechecked_after_review(self):
        self.owner.scope_busy = Mock(side_effect=[False, True])
        with patch("src.services.ai_action_service.run_local_command") as run:
            result = self.execute()
        self.review.assert_called_once()
        run.assert_not_called()
        self.assertFalse(result["dispatched"])

    def test_busy_state_is_rechecked_after_specific_approval(self):
        self.owner.scope_busy = Mock(return_value=False)
        def approve(action, stop):
            self.owner.scope_busy.return_value = True
            self.store.change_action(action["id"], ("reviewing",), "approved")
            return True
        self.review.return_value = ActionAssessment("dangerous", "test")
        with patch.object(self.service, "_wait_approval", side_effect=approve), patch("src.services.ai_action_service.run_local_command") as run:
            result = self.execute()
        run.assert_not_called()
        self.assertFalse(result["dispatched"])

    def test_read_local_file_remains_available_when_device_busy(self):
        path = Path(self.temp) / "evidence.txt"
        path.write_text("historical evidence", encoding="utf-8")
        self.owner.diagnostic.busy.return_value = True
        self.owner.scope_busy = Mock(return_value=True)
        result = self.execute("read_local_file", {"path": str(path)})
        self.assertEqual(result["text"], "historical evidence")
        self.owner.scope_busy.assert_not_called()

    def test_idle_bound_local_command_keeps_existing_execution(self):
        self.owner.scope_busy = Mock(return_value=False)
        with patch("src.services.ai_action_service.run_local_command", return_value={"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}) as run:
            self.assertEqual(self.execute()["action_state"], "succeeded")
        run.assert_called_once()

    def test_preflight_veto_is_not_reported_as_dispatched(self):
        self.owner.permissions = Mock()
        self.owner.permissions.status.return_value = {"mode": FULL, "grant_id": "test"}
        self.executor._connection.return_value.command.side_effect = DebugSessionInvalid("simulated invalid shell", False)
        result = self.execute("run_dut_command", {"command": "id"})
        self.assertFalse(result["dispatched"])
        self.assertEqual(result["action_state"], "failed")


class SerialResourceGuardTests(unittest.TestCase):
    def test_host_busy_snapshot_runs_on_dispatcher_owner_thread(self):
        bridge = AiSerialBridge(Mock(), Mock(), lambda _: False)
        result, threads = [], []
        bridge.dispatcher.handlers['host_busy'] = lambda request: threads.append(threading.get_ident()) or True
        worker = threading.Thread(target=lambda: result.append(bridge.client.host_busy()))
        worker.start()
        try:
            deadline = time.monotonic()+2
            while not result and time.monotonic() < deadline:
                bridge.poll(); time.sleep(.001)
            self.assertEqual(result, [True])
            self.assertEqual(threads, [threading.get_ident()])
        finally:
            bridge.close(); worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_controller_and_closing_guards_preserve_passive_and_own_lease(self):
        manager = Mock()
        bridge = AiSerialBridge(Mock(), manager, lambda _: False)
        self.addCleanup(bridge.dispatcher.dispose)
        for owner, closing, expected in (("", False, False), ("upgrade", False, True), ("", True, True), ("ai-debug:test", False, False)):
            manager.diagnostic_state.return_value = {"control_owner": owner, "closing_in_program": closing}
            bridge.controls[TARGET.port.upper()] = ("ai-debug:test", threading.Event())
            with self.subTest(owner=owner, closing=closing): self.assertEqual(bridge._busy(TARGET), expected)
        bridge.controls[TARGET.port.upper()][1].set()
        self.assertTrue(bridge._busy(TARGET))


class ReadOnlyDuringBusyTests(unittest.TestCase):
    setUp = conversation_fixture.ConversationTests.setUp
    stop_services = conversation_fixture.ConversationTests.stop_services
    send = conversation_fixture.ConversationTests.send

    def test_historical_evidence_search_is_available_when_device_busy(self):
        self.diag.busy = Mock(return_value=True)
        self.service.add_evidence(self.id, "history", "WAN evidence log")
        result = self.service.search(self.id, "WAN")
        self.assertGreater(result["matched"], 0)
        self.diag.serial_acquire.assert_not_called()

    def test_material_only_analysis_is_available_when_device_busy(self):
        self.diag.busy = Mock(return_value=True)
        self.responses.append(chat("Material analysis only"))
        session = self.send("Explain the supplied history")
        self.assertEqual(session["status"], "可继续")
        self.diag.serial_acquire.assert_not_called()

    def test_question_report_can_finish_without_active_dut_commands(self):
        self.diag.busy = Mock(return_value=True)
        self.responses.append(chat("Report from passive evidence"))
        identifier = self.diag.submit("Explain existing evidence", TARGET.channel, level="question")
        self.diag.jobs.join()
        self.assertEqual(self.store.report(identifier)["status"], "完成")
        self.diag.serial_acquire.assert_not_called()


if __name__ == "__main__":
    unittest.main()

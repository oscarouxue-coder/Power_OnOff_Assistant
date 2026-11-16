"""OLT adapter tests use original plan validators with fake network executors."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import time
import unittest

from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.onu_registration_models import DiscoveredOnu, RegisteredOnu, OnuOperationResult
from src.models.onu_batch_delete import OnuBatchDeleteResult, OnuDeleteItemResult
from line_check_assistant.onu_registration_store import OnuRegistrationConfig
from src.services.capability_service import CapabilityService
from src.services.onu_registration_service import OnuRegistrationService


class OnuCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = OnuRegistrationConfig(c300_olt_ip="192.0.2.1", c300_source_ip="192.0.2.2",
            c300_username="synthetic", c300_password="synthetic")
        self.authority = CapabilityAuthority("remote-user", "session", "operation", (1,), source="feishu",
                                              mode="full_access", grant_id="grant")
        self.service = CapabilityService(self.root / "runtime", Mock(), lambda: {}, tool_root=self.root,
                                        onu_configuration=lambda: asdict(self.config))
        self.registration = Mock()
        self.registration.test_connection.return_value = OnuOperationResult(True, "fake login")
        self.registration.query_unregistered.return_value = OnuOperationResult(True, "fake discovered", onus=(
            DiscoveredOnu("C300", "gpon-olt_1/2/1", "GPONA62D6F78", onu_interface="gpon-onu_1/2/1:3", suggested_onu_id=3),))
        self.registration.query_registered_candidates.return_value = OnuOperationResult(True, "fake registered", registered_onus=(
            RegisteredOnu("C300", "gpon-olt_1/2/1", "gpon-onu_1/2/1:3", 3, "OffLine", "GPONA62D6F78", "SD-41"),))
        self.registration.register.return_value = OnuOperationResult(True, "fake registered")
        self.registration.save_configuration.return_value = OnuOperationResult(True, "fake write")
        self.registration.query_templates.return_value = OnuOperationResult(True, "fake templates")
        self.registration.build_preview.side_effect = lambda requests: OnuRegistrationService().build_preview(requests)
        self.service.onu.registration_factory = Mock(return_value=self.registration)
        self.args = dict(family="C300")

    def tearDown(self):
        self.wait()
        self.service.jobs.close()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 4
        while not self.service.jobs.idle and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.service.jobs.idle)

    def approve(self, operation, **kwargs):
        args = dict(self.args, **kwargs)
        scope = self.service.onu.scope(args, operation)
        self.service.scopes.grant(self.authority.principal, scope, "synthetic-local-reviewer")
        return scope

    def run_job(self, operation, **kwargs):
        job = self.service.execute("onu." + operation, dict(self.args, **kwargs), self.authority)
        self.wait()
        return self.service.jobs.status(job["job_id"], self.authority)

    def test_channel_full_access_does_not_grant_olt_scope(self):
        with self.assertRaises(CapabilityError) as caught:
            self.run_job("connection")
        self.assertEqual("local_scope_approval_required", caught.exception.code)
        self.service.onu.registration_factory.assert_not_called()

    def test_reviewed_connection_uses_saved_binding_and_real_service_api(self):
        self.approve("connection")
        self.assertEqual("succeeded", self.run_job("connection")["state"])
        connection = self.registration.test_connection.call_args[0][1]
        self.assertEqual(("192.0.2.1", "192.0.2.2"), (connection.host, connection.source_ip))

    def test_changed_olt_profile_invalidates_scope_without_network(self):
        self.approve("connection")
        self.config.c300_olt_ip = "192.0.2.10"
        with self.assertRaises(CapabilityError):
            self.run_job("connection")
        self.service.onu.registration_factory.assert_not_called()

    def test_write_scope_can_read_same_pon_but_cannot_expand_to_another(self):
        self.approve("register", serial_numbers=["GPONA62D6F78"])
        self.assertTrue(self.service.scopes.allowed(self.authority.principal, self.service.onu.scope(self.args, "registered")))
        self.assertFalse(self.service.scopes.allowed(self.authority.principal,
            self.service.onu.scope(dict(self.args, pon=2), "registered")))

    def test_registration_uses_fresh_sn_and_immutable_original_command_plan(self):
        self.approve("register", serial_numbers=["GPONA62D6F78"])
        result = self.run_job("register", serial_numbers=["GPONA62D6F78"])
        self.assertEqual("succeeded", result["state"])
        request = self.registration.register.call_args[0][1][0]
        plans = self.registration.register.call_args.kwargs["command_plans"]
        self.assertEqual("GPONA62D6F78", request.onu.serial_number)
        self.assertTrue(plans[0].commands)
        self.registration.save_configuration.assert_not_called()

    def test_sn_missing_from_current_discovery_cannot_be_registered(self):
        self.approve("register", serial_numbers=["GPONA62D6F79"])
        result = self.run_job("register", serial_numbers=["GPONA62D6F79"])
        self.assertEqual("failed", result["state"])
        self.registration.register.assert_not_called()

    def test_whole_olt_discovery_does_not_allow_whole_olt_registration(self):
        with self.assertRaises(CapabilityError) as caught:
            self.service.onu.scope(dict(self.args, shelf=0, slot=0, pon=0), "register")
        self.assertEqual("explicit_pon_required", caught.exception.code)

    def test_batch_delete_reuses_current_candidates_and_never_write(self):
        self.approve("delete")
        candidate = self.registration.query_registered_candidates.return_value.registered_onus[0]
        delete = Mock()
        delete.delete.return_value = OnuBatchDeleteResult((OnuDeleteItemResult(candidate, "success", "fake"),))
        self.service.onu.delete_factory = Mock(return_value=delete)
        result = self.run_job("delete", onu_interfaces=[candidate.onu_interface])
        self.assertEqual("succeeded", result["state"])
        self.assertEqual([candidate], delete.delete.call_args[0][3])
        self.registration.save_configuration.assert_not_called()

    def test_stale_delete_selection_never_reaches_delete_service(self):
        self.approve("delete")
        factory = self.service.onu.delete_factory = Mock()
        result = self.run_job("delete", onu_interfaces=["gpon-onu_1/2/1:99"])
        self.assertEqual("failed", result["state"])
        factory.assert_not_called()

    def test_save_configuration_requires_separate_global_scope(self):
        self.approve("register", serial_numbers=["GPONA62D6F78"])
        with self.assertRaises(CapabilityError):
            self.run_job("save")
        self.registration.save_configuration.assert_not_called()
        self.approve("save")
        self.assertEqual("succeeded", self.run_job("save")["state"])

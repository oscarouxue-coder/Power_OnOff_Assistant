"""Next module adapters: fake only; no subprocess, adapter, power or DUT access."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import threading
import time
import unittest

from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.dut_config_models import DutAdvancedConfigResult
from src.services.capability_service import CapabilityService
from src.services.pipeline_orchestrator import PipelineOrchestrator, PipelineError, SubTaskResult
from line_check_assistant.network_ops import CommandResult


MODULE = "src.services.capability_device_services."


class DeviceCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = dict(channels=[dict(section="channel_1", vlan_name="vlan116", adapter_alias="vlan116",
            serial_port="COM16", network_card_ip="192.168.1.116", device_manage_ip="192.168.1.1", enabled=True)],
            power_serial_port="COM102", upgrade_settings=dict(parameter_initial_username="synthetic",
                                                             parameter_initial_password="synthetic"),
            serial_log_dir=str(self.root / "serial"))
        self.authority = CapabilityAuthority("local-user", "session", "operation", (1,), mode="full_access", grant_id="grant")
        self.manager = Mock()
        self.service = CapabilityService(self.root / "runtime", self.manager, lambda: self.snapshot, tool_root=self.root)

    def tearDown(self):
        self.service.jobs.begin_close()
        deadline = time.monotonic() + 4
        while not self.service.jobs.idle and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.service.jobs.idle)
        self.service.jobs.close()
        self.temp.cleanup()

    def result(self, capability, **kwargs):
        job = self.service.execute(capability, dict(channel_ids=[1], **kwargs), self.authority)
        deadline = time.monotonic() + 4
        while not self.service.jobs.idle and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.service.jobs.idle)
        return self.service.jobs.status(job["job_id"], self.authority)

    def test_power_uses_existing_business_and_only_selected_channel(self):
        for identifier, function in (("power.on", "turn_on_selected_channels"), ("power.off", "turn_off_selected_channels")):
            with patch(MODULE + function, return_value=CommandResult(True, "fake")) as run:
                result = self.result(identifier)
                self.assertEqual("succeeded", result["state"])
                self.assertEqual(("COM102", [1]), run.call_args[0])

    def test_no_power_com_never_guesses_or_dispatches(self):
        self.snapshot["power_serial_port"] = ""
        with patch(MODULE + "turn_on_selected_channels") as run:
            result = self.result("power.on")
            self.assertEqual("failed", result["state"])
            run.assert_not_called()

    def test_pipeline_reuses_original_orchestrator_and_data_projection(self):
        self.assertIs(PipelineOrchestrator, self.service.devices.pipeline_factory)
        observed = []
        def pipeline(ctx, emit):
            self.assertFalse(hasattr(ctx.app, "tk"))
            observed.append(ctx)
            def run(tasks):
                self.assertEqual({"legacy_power_test"}, tasks)
                ctx.app._set_power_test_progress(1, 5)
                return [SubTaskResult("legacy_power_test", True)]
            return SimpleNamespace(run=run)
        self.service.devices.pipeline_factory = pipeline
        result = self.result("aging.start")
        self.assertEqual("succeeded", result["state"])
        self.assertEqual(self.root / "Auto_power_on_off_tool", observed[0].legacy_tool_root)
        self.assertEqual([1], [int(c.section.split('_')[-1]) for c in observed[0].channels])

    def test_environment_check_uses_existing_pipeline_subtask(self):
        pipeline = Mock()
        pipeline.run.return_value = [SubTaskResult("env_check", True)]
        self.service.devices.pipeline_factory = Mock(return_value=pipeline)
        self.assertEqual("succeeded", self.result("network.line_check")["state"])
        pipeline.run.assert_called_once_with({"env_check"})

    def test_pipeline_requires_explicit_tasks_and_retains_failure_verdict(self):
        with self.assertRaises(CapabilityError):
            self.service.execute("pipeline.start", dict(channel_ids=[1]), self.authority)
        pipeline = Mock()
        pipeline.run.side_effect = PipelineError("fake failed version precheck")
        self.service.devices.pipeline_factory = Mock(return_value=pipeline)
        result = self.result("pipeline.start", tasks=["legacy_power_test"])
        self.assertEqual("failed", result["state"])
        self.assertFalse(result["result"]["ok"])

    def test_resume_never_reconstructs_or_replays_after_restart(self):
        with self.assertRaises(CapabilityError) as caught:
            self.service.execute("aging.resume", dict(channel_ids=[1], parent_job_id="old"), self.authority)
        self.assertEqual("resume_unavailable", caught.exception.code)

    def test_dut_query_returns_structured_data_without_execution_credentials(self):
        def run(requests, **kwargs):
            self.assertEqual("synthetic", requests[0].username)
            return [DutAdvancedConfigResult(requests[0], True, "queried", "fake", details={"wan": "present"})]
        with patch(MODULE + "run_dut_wan_query_batch", side_effect=run):
            result = self.result("dut.wan.query")
            self.assertEqual("succeeded", result["state"])
            self.assertNotIn("request", result["result"]["items"][0])
            self.assertNotIn("password", str(result["result"]))

    def test_dut_wan_configuration_reuses_existing_validation_and_engine(self):
        def run(requests, **kwargs):
            self.assertEqual("200", requests[0].settings.vlan_id)
            self.assertEqual(1, kwargs["max_workers"])
            return [DutAdvancedConfigResult(requests[0], True, "configured", "fake")]
        with patch(MODULE + "run_dut_advanced_config_batch", side_effect=run) as engine:
            result = self.result("dut.wan.configure", settings=dict(vlan_id="200"))
            self.assertEqual("succeeded", result["state"])
            engine.assert_called_once()

    def test_device_reported_capabilities_cannot_be_injected(self):
        with self.assertRaises(CapabilityError):
            self.service.execute("dut.wifi_5g.configure", dict(channel_ids=[1], settings=dict(supported_channels=["999"])), self.authority)

    def test_invalid_config_fails_before_any_device_modification(self):
        with patch(MODULE + "run_dut_advanced_config_batch") as engine:
            result = self.result("dut.wan.configure", settings=dict(vlan_id="99999"))
            self.assertEqual("failed", result["state"])
            self.assertFalse(result["result"]["dispatched"])
            engine.assert_not_called()

    def test_device_range_enforced_even_in_full_access(self):
        with self.assertRaises(CapabilityError):
            self.service.execute("power.on", dict(channel_ids=[2]), self.authority)

    def test_admission_recheck_protects_changed_channel(self):
        def admissible(owner, keys):
            self.snapshot["channels"][0]["serial_port"] = "COM17"
            return True
        self.service.resources.admissible = admissible
        with patch(MODULE + "turn_on_selected_channels") as engine, self.assertRaises(CapabilityError):
            self.result("power.on")
        engine.assert_not_called()

    def parameter_table(self):
        from test_sample_parameter_service import values
        from src.models.sample_parameter_models import SampleParameterRecord
        from src.core.sample_parameter_table import save_parameter_records_xlsx
        path = self.root / "parameters.xlsx"
        save_parameter_records_xlsx(path, [SampleParameterRecord("vlan116", values(), 2)])
        return path

    def test_parameter_preflight_does_not_dispatch_or_expose_table_credentials(self):
        path = self.parameter_table()
        result = self.service.execute("parameters.preflight", dict(channel_ids=[1], table_path=str(path)), self.authority)
        self.assertTrue(result["ok"])
        self.assertEqual("COM16", result["targets"][0]["serial_port"])
        self.assertNotIn("secret-super", str(result))
        self.assertTrue(self.service.jobs.idle)

    def test_parameter_write_uses_shared_application_and_factory_ip_derivation(self):
        from src.models.sample_parameter_models import SampleParameterItemResult
        def run(requests, parallel, cancel, manager, network, emit):
            self.assertEqual("192.168.29.116", requests[0].factory_bind_ip)
            self.assertEqual("192.168.29.1", requests[0].factory_device_host)
            self.assertEqual((False, False), (requests[0].clear_parameters, requests[0].exit_aging))
            self.assertEqual(("vlan116", "255.255.255.0"), network["vlan116"])
            return [SampleParameterItemResult(requests[0], True, "fake", written_count=15)]
        self.service.parameters.runner = Mock(side_effect=run)
        result = self.result("parameters.write", table_path=str(self.parameter_table()))
        self.assertEqual("succeeded", result["state"])
        self.assertNotIn("request", result["result"]["items"][0])
        self.service.parameters.runner.assert_called_once()

    def test_parameter_table_missing_target_fails_before_job_or_device(self):
        path = self.parameter_table()
        self.snapshot["channels"][0]["vlan_name"] = "vlan117"
        self.snapshot["channels"][0]["adapter_alias"] = "vlan117"
        self.service.parameters.runner = Mock()
        with self.assertRaises(CapabilityError):
            self.result("parameters.write", table_path=str(path))
        self.service.parameters.runner.assert_not_called()

    def test_parameter_generation_stays_in_workspace_and_uses_existing_rules(self):
        from test_sample_parameter_table import template
        result = self.service.execute("parameters.generate", dict(channel_ids=[1], output_name="parameters.xlsx",
                                       template=asdict(template())), self.authority)
        self.assertEqual(1, result["count"])
        self.assertTrue(Path(result["path"]).is_file())
        with self.assertRaises(CapabilityError):
            self.service.execute("parameters.generate", dict(channel_ids=[1], output_name="../escape.xlsx",
                                     template=asdict(template())), self.authority)

    def test_parameter_table_replacement_during_admission_never_dispatches(self):
        path = self.parameter_table()
        self.service.parameters.runner = Mock()
        def admission(owner, keys):
            path.write_bytes(path.read_bytes() + b'\n')
            return True
        self.service.resources.admissible = admission
        with self.assertRaises(CapabilityError) as caught:
            self.result('parameters.write', table_path=str(path))
        self.assertEqual('parameter_table_changed', caught.exception.code)
        self.service.parameters.runner.assert_not_called()

"""Four production job services and real business workflows over fake transports."""
from pathlib import Path
import gc
import tempfile
import time
from types import SimpleNamespace
import unittest

from project_validation_fixtures import ValidationSandbox, ValidationJobs, KINDS
from src.core.serial_transport import SerialSessionManager
from src.models.capabilities import CapabilityError
from src.services.workspace_service import WorkspaceService

SOURCE = Path(__file__).resolve().parents[1]


class MultiProjectBusinessTests(unittest.TestCase):
    def setUp(self):
        gc.collect()  # Collect retired GUI fixtures on their owner thread before workers start.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = WorkspaceService(SOURCE, Path(self.temp.name) / 'user')
        self.contexts = [self.service.projects.create(Path(self.temp.name) / str(i), '模拟项目' + str(i)) for i in range(4)]
        self.managers = [SerialSessionManager(resource_coordinator=self.service.resources,
            project_id=c.identity.project_id, project_name=c.identity.name) for c in self.contexts]
        self.batch = ValidationJobs(self.service, self.contexts, self.managers)
        for context, jobs in zip(self.contexts, self.batch.jobs):
            self.service.controllers[context.identity.project_id] = SimpleNamespace(capabilities=SimpleNamespace(jobs=jobs))
        self.sandbox = ValidationSandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.finish)

    def finish(self):
        self.batch.close()
        self.sandbox.__exit__(None, None, None)
        for context in self.contexts:
            self.service.projects.close(context)
        self.service.close()

    def results(self, submissions):
        deadline = time.monotonic() + 5
        while any(not j.idle for j, _, _ in submissions) and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(all(j.idle for j, _, _ in submissions))
        return [j.status(identifier, authority) for j, identifier, authority in submissions]

    def test_four_projects_execute_every_business_kind_with_isolated_commands_and_results(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                gates, submissions = self.batch.start(kind)
                try:
                    for gate in gates:
                        if not gate.entered.wait(3):
                            self.fail(str([(j._row(key)['state'], j._row(key)['result']) for j, key, _ in submissions]))
                    self.assertTrue(all(not j.idle for j in self.batch.jobs))
                    # Save a new revision while four real worker jobs retain their snapshots.
                    for context in self.contexts:
                        self.service.projects.save(context)
                    self.assertEqual(4, len({project for project, keys in self.service.resources.owners.values()}))
                finally:
                    for gate in gates:
                        gate.proceed.set()
                    completed = self.results(submissions)
                for result, context, gate in zip(completed, self.contexts, gates):
                    self.assertEqual('succeeded', result['state'], (kind, result))
                    self.assertTrue(gate.commands)
                    self.assertTrue(result['result']['simulated'])
                    self.assertEqual(context.identity.project_id, result['result']['project_id'])
                    self.service.refresh_status(context)
                    self.assertEqual('succeeded', self.service.status.snapshot(context).last_result)
                for index, logs in enumerate(self.batch.logs):
                    self.assertTrue(logs)
                    self.assertTrue(all(self.contexts[index].identity.project_id in line for line in logs))

    def test_stopping_one_real_job_does_not_cancel_or_release_the_other_three(self):
        gates, submissions = self.batch.start('network')
        try:
            self.assertTrue(all(gate.entered.wait(3) for gate in gates))
            jobs, identifier, authority = submissions[0]
            jobs.cancel(identifier, authority)
            gates[0].proceed.set()
            self.assertEqual('stopped', self.results([submissions[0]])[0]['state'])
            self.assertTrue(all(not job.idle for job in self.batch.jobs[1:]))
            self.assertEqual(3, len(self.service.resources.owners))
            self.assertTrue(all(not gate.commands for gate in gates[1:]))
        finally:
            for gate in gates:
                gate.proceed.set()
        self.assertTrue(all(r['state'] == 'succeeded' for r in self.results(submissions[1:])))

    def test_physical_conflict_is_rejected_before_fake_device_dispatch(self):
        gates, submissions = self.batch.start('network')
        try:
            self.assertTrue(all(gate.entered.wait(3) for gate in gates))
            with self.assertRaises(CapabilityError):
                self.service.resources.acquire('competing', self.contexts[1].identity.project_id, 'other', ['adapter:simulated0'])
            self.assertFalse(gates[0].commands)
        finally:
            for gate in gates:
                gate.proceed.set()
        self.results(submissions)

    def test_unknown_is_visible_and_blocks_restart_until_original_job_is_reviewed(self):
        self.batch.inject(unknown=True)
        key, authority = self.batch.injected
        result = self.results([(self.batch.jobs[0], key, authority)])[0]
        self.assertEqual('unknown', result['state'])
        self.service.refresh_status(self.contexts[0])
        self.assertEqual(1, self.service.list_projects()[0]['unknown_task_count'])
        with self.assertRaises(CapabilityError):
            self.batch.inject(unknown=False)
        self.batch.reconcile_injected()
        self.service.refresh_status(self.contexts[0])
        self.assertEqual(0, self.service.list_projects()[0]['unknown_task_count'])
        self.assertFalse(self.batch.rounds)


if __name__ == '__main__':
    unittest.main()

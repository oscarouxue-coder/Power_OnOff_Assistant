"""Original process lifetime guards, using disposable project identities and no device I/O."""
from contextlib import ExitStack
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from src.models.project import PROJECT_FILE, ProjectContext, ProjectIdentity
from src.services import power_worker_lifetime as lifetime


def hold_worker(root, ready, finish):
    lifetime.publish_power_worker(root)
    ready.set()
    if not finish.wait(30):
        raise RuntimeError('fixture timed out')


@unittest.skipUnless(os.name == 'nt', 'Windows process lifetime')
class PowerWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def project(self):
        identity = ProjectIdentity(uuid4().hex, '模拟项目', 'r1')
        root = self.root / identity.project_id
        tool = root / 'runs' / 'test-run' / 'Auto_power_on_off_tool'
        tool.mkdir(parents=True)
        (root / PROJECT_FILE).write_text(json.dumps(dict(project_id=identity.project_id)), encoding='utf-8')
        (tool.parent / 'run.json').write_text(json.dumps(dict(project_id=identity.project_id, run_id='test-run')), encoding='utf-8')
        return ProjectContext(root, identity, root), tool

    def test_two_project_events_release_only_after_last_owner_exits(self):
        first, a = self.project()
        second, b = self.project()
        spawn = multiprocessing.get_context('spawn')

        def start(tool, cleanup):
            ready, finish = spawn.Event(), spawn.Event()
            worker = spawn.Process(target=hold_worker, args=(tool, ready, finish))
            worker.start()
            cleanup.callback(worker.join, 35)
            cleanup.callback(finish.set)
            self.assertTrue(ready.wait(12))
            return finish, worker

        with ExitStack() as cleanup, patch.object(lifetime, '_legacy_worker_notice', return_value=''):
            workers = [start(tool, cleanup) for tool in (a, a, b)]
            self.assertEqual([lifetime.power_worker_notice(c) for c in (first, second)], [lifetime.ACTIVE] * 2)
            for index, expected in enumerate(((lifetime.ACTIVE, lifetime.ACTIVE), ('', lifetime.ACTIVE), ('', ''))):
                finish, worker = workers[index]
                finish.set()
                worker.join(8)
                self.assertEqual(worker.exitcode, 0)
                self.assertEqual(tuple(lifetime.power_worker_notice(c) for c in (first, second)), expected)

    def test_orphan_before_registration_and_mismatched_project_cannot_start(self):
        project, tool = self.project()
        parent = Mock()
        parent.is_alive.return_value = False
        with patch.object(multiprocessing, 'parent_process', return_value=parent):
            with self.assertRaisesRegex(RuntimeError, '登记前已退出'):
                lifetime.publish_power_worker(tool)
            with patch.object(lifetime, '_legacy_worker_notice', return_value=''):
                self.assertEqual(lifetime.power_worker_notice(project), '')
            (tool.parent / 'run.json').write_text(json.dumps(dict(project_id=uuid4().hex, run_id='test-run')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '标识不一致'):
                lifetime.publish_power_worker(tool)

    def test_unreadable_legacy_worker_keeps_protection(self):
        project, _ = self.project()
        worker = Mock(pid=98765, info={'name': 'python.exe'})
        worker.cmdline.return_value = ['python.exe', '--multiprocessing-fork']
        worker.cwd.side_effect = lifetime.psutil.AccessDenied()
        with patch.object(lifetime.psutil, 'process_iter', return_value=[worker]):
            with self.assertRaisesRegex(lifetime.CapabilityError, lifetime.UNVERIFIED):
                lifetime.guard_power_worker_review(project)

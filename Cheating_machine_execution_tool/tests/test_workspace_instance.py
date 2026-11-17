import os
from pathlib import Path
import tempfile
import unittest
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

from src.core.workspace_instance import WorkspaceInstance


@unittest.skipUnless(os.name == 'nt', 'Windows authenticated named pipe')
class WorkspaceInstanceTests(unittest.TestCase):
    def test_second_launch_forwards_project_without_starting_another_manager(self):
        with tempfile.TemporaryDirectory(prefix='workspace ipc ') as directory:
            primary = WorkspaceInstance(directory)
            secondary = WorkspaceInstance(directory)
            try:
                self.assertTrue(primary.start())
                project = str(Path(directory) / 'simulated/project.linecheck.json')
                self.assertFalse(secondary.start(project))
                self.assertEqual(primary.requests.get(timeout=3), dict(action='open', project=project))
            finally:
                secondary.close()
                primary.close()
                primary.worker.join(3)
            self.assertFalse(primary.worker.is_alive())

    def test_invalid_authentication_does_not_kill_listener_or_accept_request(self):
        with tempfile.TemporaryDirectory(prefix='workspace auth ') as directory:
            primary = WorkspaceInstance(directory)
            secondary = WorkspaceInstance(directory)
            try:
                self.assertTrue(primary.start())
                with self.assertRaises(AuthenticationError):
                    Client(primary.address, family='AF_PIPE', authkey=b'invalid')
                self.assertFalse(secondary.start())
                self.assertEqual(primary.requests.get(timeout=3), dict(action='open', project=''))
                self.assertTrue(primary.requests.empty())
            finally:
                secondary.close()
                primary.close()
                primary.worker.join(3)

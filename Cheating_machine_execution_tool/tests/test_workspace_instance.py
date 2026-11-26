import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

from src.core.workspace_instance import WorkspaceInstance, WorkspaceInstanceError


@unittest.skipUnless(os.name == 'nt', 'Windows authenticated named pipe')
class WorkspaceInstanceTests(unittest.TestCase):
    def test_packaged_instances_share_machine_lock_but_source_can_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory}):
            from src.services.workspace_service import workspace_data_dir
            formal = WorkspaceInstance(workspace_data_dir(frozen=True), machine_wide=True)
            other = WorkspaceInstance(Path(directory) / 'other-user', machine_wide=True)
            source = WorkspaceInstance(workspace_data_dir(frozen=False))
            source_duplicate = WorkspaceInstance(source.directory)
            duplicate = WorkspaceInstance(formal.directory, machine_wide=True)
            self.assertEqual(formal.machine_lease.keys, other.machine_lease.keys)
            self.assertEqual(formal.machine_lease.namespace, other.machine_lease.namespace)
            namespace = uuid.uuid4().hex
            for instance in (formal, other, duplicate):
                instance.machine_lease.namespace = namespace
            try:
                self.assertTrue(formal.start())
                self.assertTrue(source.start())
                self.assertNotEqual(source.address, formal.address)
                self.assertFalse(duplicate.start('formal-project'))
                self.assertEqual(formal.requests.get(timeout=3)['project'], 'formal-project')
                self.assertTrue(source.requests.empty())
                self.assertFalse(source_duplicate.start('source-project'))
                self.assertEqual(source.requests.get(timeout=3)['project'], 'source-project')
                self.assertTrue(formal.requests.empty())
                with self.assertRaisesRegex(WorkspaceInstanceError, '此电脑已有 DUTPilot'):
                    other.start()
            finally:
                for instance in (duplicate, other, source_duplicate, source, formal):
                    instance.close()
            replacement = WorkspaceInstance(other.directory, machine_wide=True)
            replacement.machine_lease.namespace = namespace
            try:
                self.assertTrue(replacement.start())
            finally:
                replacement.close()

    def test_simultaneous_process_start_and_abnormal_owner_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            namespace = uuid.uuid4().hex
            gate = root / 'start'
            code = '''
import sys, time
from pathlib import Path
from src.core.workspace_instance import WorkspaceInstance, WorkspaceInstanceError
directory, namespace, gate, result = sys.argv[1:]
instance = WorkspaceInstance(directory, machine_wide=True)
instance.machine_lease.namespace = namespace
deadline = time.monotonic() + 10
while not Path(gate).exists() and time.monotonic() < deadline:
    time.sleep(.02)
assert Path(gate).exists()
result_path = Path(result)
temporary = result_path.with_suffix('.tmp')
try:
    assert instance.start()
except WorkspaceInstanceError:
    temporary.write_text('blocked')
    temporary.replace(result_path)
else:
    temporary.write_text('owner')
    temporary.replace(result_path)
    time.sleep(30)
'''
            paths = [root / name for name in ('first', 'second')]
            results = [path.with_suffix('.result') for path in paths]
            children = []
            try:
                for path, result in zip(paths, results):
                    children.append(subprocess.Popen([sys.executable, '-c', code, str(path), namespace,
                        str(gate), str(result)], creationflags=subprocess.CREATE_NO_WINDOW))
                gate.touch()
                deadline = time.monotonic() + 10
                while not all(result.exists() for result in results) and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(all(result.exists() for result in results))
                states = [result.read_text() for result in results]
                self.assertCountEqual(states, ['owner', 'blocked'])
                contender = WorkspaceInstance(root / 'other', machine_wide=True)
                contender.machine_lease.namespace = namespace
                try:
                    with self.assertRaises(WorkspaceInstanceError):
                        contender.start()
                finally:
                    contender.close()
            finally:
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
            replacement = WorkspaceInstance(paths[states.index('owner')], machine_wide=True)
            replacement.machine_lease.namespace = namespace
            try:
                self.assertTrue(replacement.start())
            finally:
                replacement.close()

    def test_requests_are_rejected_during_safe_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            primary = WorkspaceInstance(directory)
            secondary = WorkspaceInstance(directory)
            try:
                self.assertTrue(primary.start())
                primary.closing_requested.set()
                with self.assertRaisesRegex(WorkspaceInstanceError, '正在安全退出'):
                    secondary.start('project')
                self.assertTrue(primary.requests.empty())
            finally:
                secondary.close()
                primary.close()

    def test_source_workspace_imports_configuration_once_without_runtime_state(self):
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_store import DiagnosticStore
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from src.services.feishu_remote_store import FeishuConfigStore
        from src.services.workspace_service import initialize_source_workspace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal, source = root / 'workspace', root / 'workspace-source'
            formal.mkdir()
            recent = formal / 'recent_projects.json'
            recent.write_text(json.dumps([dict(project_id='synthetic', name='Demo', path=str(root / 'project'))]), encoding='utf-8')
            for file in ('workspace_session.json', 'remote_projects.json', 'ipc-synthetic.key'):
                (formal / file).write_text('synthetic runtime state', encoding='utf-8')
            with self.subTest(config='model'):
                models = DiagnosticStore(formal / 'models')
                try:
                    profile = models.save_profile(ProviderProfile(model='synthetic'), 'synthetic-key')
                    models.set_setting('selected_profile', profile.id)
                    models.set_setting('chat_permission_mode', 'full')
                finally:
                    models.close()
            dingtalk = RemoteConfigStore(root, directory=formal / 'platforms')
            dingtalk.save(dict(dingtalk.load(), client_id='app', client_secret='synthetic-secret',
                               group='group', corp='corp', robot_code='robot', webhook='https://example.invalid', enabled=True))
            feishu = FeishuConfigStore(root, directory=formal / 'platforms')
            feishu.save(dict(feishu.load(), app_id='app', app_secret='synthetic-secret', group='group',
                             corp='corp', group_enabled=True, p2p_enabled=True, push_enabled=True))
            original = {file: file.read_bytes() for file in formal.rglob('*') if file.is_file()}
            messages = []
            initialize_source_workspace(source, root, messages.append)
            self.assertEqual(json.loads((source / recent.name).read_text(encoding='utf-8')), json.loads(recent.read_text(encoding='utf-8')))
            models = DiagnosticStore(source / 'models')
            try:
                self.assertEqual(models.key(models.profiles()[0]), 'synthetic-key')
                self.assertEqual(models.setting('selected_profile'), profile.id)
                self.assertIsNone(models.setting('chat_permission_mode'))
            finally:
                models.close()
            for factory, flags, secret in ((RemoteConfigStore, ('enabled',), 'client_secret'),
                                           (FeishuConfigStore, ('enabled', 'group_enabled', 'p2p_enabled', 'push_enabled'), 'app_secret')):
                value = factory(root, directory=source / 'platforms').load()
                self.assertEqual(value[secret], 'synthetic-secret')
                self.assertTrue(all(not value[flag] for flag in flags))
            for file in ('workspace_session.json', 'remote_projects.json', 'ipc-synthetic.key'):
                self.assertFalse((source / file).exists())
            (source / recent.name).write_text('[]', encoding='utf-8')
            initialize_source_workspace(source, root, messages.append)
            self.assertEqual((source / recent.name).read_text(encoding='utf-8'), '[]')
            self.assertEqual(original, {file: file.read_bytes() for file in formal.rglob('*') if file.is_file()})
            self.assertTrue(any('初始化完成' in message for message in messages))

    def test_default_workspaces_keep_the_same_host_resource_protection(self):
        from src.services.workspace_service import WorkspaceService

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory}), \
                patch('src.services.workspace_service.host_resource_directory', return_value=Path(directory) / 'host'), \
                patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None):
            services = []
            try:
                for frozen in (True, False):
                    with patch.object(sys, 'frozen', frozen, create=True):
                        services.append(WorkspaceService(Path(directory)))
                formal, source = services
                self.assertNotEqual(formal.directory, source.directory)
                databases = [service.resources.fence.db.execute('PRAGMA database_list').fetchone()[2]
                             for service in services]
                self.assertEqual(databases[0], databases[1])
                self.assertTrue(all(not service.resources.inventory_ready for service in services))
            finally:
                for service in services:
                    service.close()

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

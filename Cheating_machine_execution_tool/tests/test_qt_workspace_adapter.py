"""Real project store round trips in temporary directories; no GUI or hardware."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from src.models.workbench_presentation import LogView, matches_project_filter
from src.services.qt_host_inventory import HostInventoryReading
from src.services.qt_workspace_adapter import QtWorkspaceAdapter


SOURCE = Path(__file__).resolve().parents[1]


class QtWorkspaceAdapterTests(unittest.TestCase):
    def setUp(self):
        from qt_execution_fakes import block_live_model_transport, install_native_fixture_locks
        block_live_model_transport(self)
        install_native_fixture_locks(self)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-project-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.results = {}
        self.logs = []
        self.projects = ()
        self.addCleanup(self.close_adapter)
        self.wait_for(lambda: any(r.operation == 'ready' for r in self.results.values()))

    def drain(self):
        self.projects, logs, results = self.adapter.take_updates()
        self.logs.extend(logs)
        for result in results:
            self.results[result.identifier, result.operation] = result

    def wait_for(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.drain()
            if predicate():
                return
            time.sleep(.01)
        self.fail('project worker did not return the expected result')

    def command(self, operation, *args, expected_error=False):
        identifier = self.adapter.submit(operation, *args)
        self.wait_for(lambda: (identifier, operation) in self.results)
        result = self.results[identifier, operation]
        self.assertEqual(bool(result.error), expected_error, result)
        return result

    def close_adapter(self):
        if not self.adapter.closed.is_set():
            self.adapter.begin_close({p.project_id: 'discard' for p in self.projects})
            self.assertTrue(self.adapter.wait_closed(5))

    def restart_workspace(self, selected=''):
        self.adapter.begin_close(selected_project=selected)
        self.assertTrue(self.adapter.wait_closed(5))
        self.results.clear()
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.wait_for(lambda: (0, 'ready') in self.results)
        return self.results[0, 'ready'].project_id

    def test_feishu_repair_holds_admission_until_finished_and_released(self):
        from src.services.feishu_dependency_repair import FeishuDependencyRepair

        started, release = threading.Event(), threading.Event()
        lease = Mock()

        def install(root, emit):
            emit('[飞书依赖] 模拟校验')
            started.set()
            if not release.wait(5):
                raise RuntimeError('测试超时')

        def repair(root, gate):
            return FeishuDependencyRepair(root, gate, installer=install, lease_factory=lambda _: lease)

        with patch('src.services.qt_feishu_repair.find_spec', return_value=None), \
                patch('src.services.qt_feishu_repair.FeishuDependencyRepair', side_effect=repair), \
                patch('src.services.feishu_dependency_repair.source_environment', return_value=SOURCE):
            self.command('feishu_repair_start')
            try:
                self.assertTrue(started.wait(2))
                self.assertIn('等待重启', self.command('create', self.root / 'project', 'project', expected_error=True).error)
                self.command('feishu_repair_release', expected_error=True)
            finally:
                release.set()
            self.wait_for(lambda: self.adapter.feishu_repair_status()[1] is True)
            self.assertTrue(self.adapter._service.maintenance.active)
            lease.close.assert_not_called()
            self.command('feishu_repair_release')
        self.assertFalse(self.adapter._service.maintenance.active)
        lease.close.assert_called_once()
        self.assertTrue(self.command('create', self.root / 'project', 'project').project_id)

    def test_feishu_repair_refuses_busy_workspace_before_install(self):
        with patch('src.services.qt_feishu_repair.find_spec', return_value=None), \
                patch.object(self.adapter, '_feishu_repair_busy', return_value=True), \
                patch('src.services.feishu_dependency_repair.source_environment') as source_environment:
            rejected = self.command('feishu_repair_start', expected_error=True)
        self.assertIn('结束当前任务', rejected.error)
        source_environment.assert_not_called()
        self.assertFalse(self.adapter._service.maintenance.active)

    def test_platform_configuration_saves_with_original_stores_without_starting_transport(self):
        from src.services.message_push_config_service import MessagePushConfigService

        project = self.command('create', self.root / 'project', '接入测试项目').project_id
        context = self.adapter._service.projects.opened[project]
        push = MessagePushConfigService(context.config_dir / 'config.ini')
        fixture_secret = 'only-use-inside-the-test'
        webhook = 'https://oapi.dingtalk.com/robot/send?access_token=fixture'
        values = {
            'dingtalk': dict(client_id='fixture', client_secret=fixture_secret, robot_code='robot',
                            webhook=webhook, secret='signature', ai_card_template_id='template'),
            'feishu': dict(app_id='cli_fixture', app_secret=fixture_secret),
        }
        for kind, draft in values.items():
            with self.subTest(kind=kind):
                previous = self.command('platform_configuration_open', project, kind).payload
                pool = self.adapter._service.platforms[kind]
                with patch.object(pool, 'add') as connect:
                    reply = self.command('platform_configuration_save', project, kind,
                                         previous['revision'], draft).payload
                connect.assert_not_called()
                stored = self.adapter._service.platform_config(kind).load()
                secret_key = 'client_secret' if kind == 'dingtalk' else 'app_secret'
                self.assertEqual(stored[secret_key], fixture_secret)
                self.assertEqual(reply['values'][secret_key], '')
                self.assertFalse(stored['enabled'])
                self.assertNotIn(fixture_secret, str(reply))
                self.assertIn('已变化', self.command('platform_configuration_save', project, kind,
                    previous['revision'], draft, expected_error=True).error)
        self.assertEqual(push.load()['webhook'], webhook)
        self.assertTrue(next(row for row in self.projects if row.project_id == project).dirty)
        self.assertNotIn(fixture_secret, '\n'.join(entry.message for entry in self.logs))

    def test_platform_configuration_refuses_save_while_gateway_mode_is_selected(self):
        project = self.command('create', self.root / 'project', '接入测试项目').project_id
        self.adapter._service.gateway_slot = 3
        opened = self.command('platform_configuration_open', project, 'feishu').payload
        self.assertIn('统一接入', opened['blocked'])
        result = self.command('platform_configuration_save', project, 'feishu', opened['revision'],
                              dict(app_id='cli_fixture', app_secret='fixture'), expected_error=True)
        self.assertIn('统一接入', result.error)
        self.assertFalse(self.adapter._service.platform_config('feishu').path.exists())

    def test_platform_binding_checks_the_candidate_and_leaves_direct_access_disabled(self):
        from test_dingtalk_remote import incoming as dingtalk_event
        from test_feishu_remote import incoming as feishu_event
        from src.services.workspace_platforms import PooledLease

        class Transport:
            def __init__(self, *args, **kwargs):
                self.idle = False

            def start(self):
                pass

            def begin_close(self):
                self.idle = True

        project = self.command('create', self.root / 'project', '绑定测试项目').project_id
        other = self.command('create', self.root / 'second', '另一项目').project_id
        values = {
            'dingtalk': dict(client_id='dt-fixture', client_secret='fixture-secret', robot_code='robot1',
                webhook='https://oapi.dingtalk.com/robot/send?access_token=fixture', secret='', ai_card_template_id=''),
            'feishu': dict(app_id='cli_app1', app_secret='fixture-secret'),
        }
        for kind, draft in values.items():
            with self.subTest(kind=kind):
                pool = self.adapter._service.platforms[kind]
                pool.transport_factory, pool.lease_factory = Transport, PooledLease
                loaded = self.command('platform_configuration_open', project, kind).payload
                saved = self.command('platform_configuration_save', project, kind, loaded['revision'], draft).payload
                binding = self.command('platform_binding_start', project, kind, saved['revision']).payload
                self.assertTrue(binding['code'])
                if kind == 'dingtalk':
                    pool.receive(dingtalk_event('绑定 ' + binding['code']))
                else:
                    pool.receive(feishu_event('绑定 ' + binding['code']), 'bot1')
                candidate = self.command('platform_binding_state', project, kind).payload['candidate']
                self.assertIsNotNone(candidate)
                self.command('platform_binding_confirm', other, kind, candidate, expected_error=True)
                self.command('platform_binding_confirm', project, kind, dict(candidate, group='other'), expected_error=True)
                store = self.adapter._service.platform_config(kind)
                self.assertEqual(store.load()['group'], '')
                self.command('platform_binding_confirm', project, kind, candidate)
                self.assertEqual(store.load()['group'], candidate['group'])
                self.assertFalse(store.load()['enabled'])
                self.assertTrue(pool.idle)
                self.command('platform_binding_confirm', project, kind, candidate, expected_error=True)

    def test_feishu_test_send_binds_saved_project_and_group_and_returns_the_worker_result(self):
        from src.services.feishu_notifications import FeishuNotificationService

        project = self.command('create', self.root / 'project', '通知项目').project_id
        context = self.adapter._service.projects.opened[project]
        (context.config_dir / 'test_project_config.ini').write_text('[project_info]\nproject_name=确认项目\n', encoding='utf-8')
        self.command('save', project)
        store = self.adapter._service.platform_config('feishu')
        store.save(dict(store.defaults(), app_id='cli_fixture', app_secret='fixture-secret',
                        group='confirmed-group', corp='tenant', group_name='群'))
        opened = self.command('platform_configuration_open', project, 'feishu').payload
        self.assertEqual(opened['trial'], dict(project='确认项目', group='confirmed-group'))
        api = Mock()

        def notifications(*args, **kwargs):
            return FeishuNotificationService(*args, **kwargs, api_factory=lambda *credentials: api)

        with patch('src.services.feishu_notifications.FeishuNotificationService', side_effect=notifications):
            self.command('platform_trial_start', project, 'feishu', opened['revision'],
                         dict(opened['trial'], group='other'), expected_error=True)
            api.send_text.assert_not_called()
            started = self.command('platform_trial_start', project, 'feishu', opened['revision'], opened['trial']).payload
            self.assertTrue(started['busy'])
            deadline = time.monotonic() + 5
            while True:
                status = self.command('platform_trial_state', project, 'feishu').payload
                if not status['busy'] or time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            self.assertFalse(status['busy'])
        self.assertIn('飞书已接受', status['message'])
        api.send_text.assert_called_once()
        self.assertEqual(api.send_text.call_args.args[0], 'confirmed-group')
        self.assertIn('确认项目', api.send_text.call_args.args[1])

    def test_feishu_automatic_notifications_use_original_worker_and_stop_without_stopping_test(self):
        from src.services.feishu_notifications import FeishuNotificationService

        project = self.command('create', self.root / 'project', '通知项目').project_id
        context = self.adapter._service.projects.opened[project]
        (context.config_dir / 'test_project_config.ini').write_text(
            '[project_info]\nproject_name=确认项目\n', encoding='utf-8')
        self.command('save', project)
        store = self.adapter._service.platform_config('feishu')
        store.save(dict(store.defaults(), app_id='cli_fixture', app_secret='fixture-secret',
                        group='confirmed-group', corp='tenant', group_name='群'))
        execution = self.adapter._execution(context)
        event = dict(type='test_notification', id='automatic-event', channel=4, normal=True)
        api = Mock()
        peer = threading.Event()
        api.send_text.side_effect = lambda *arguments: peer.set()

        def notifications(*args, **kwargs):
            return FeishuNotificationService(*args, **kwargs, api_factory=lambda *credentials: api)

        with patch('src.services.qt_feishu_notifications.FeishuNotificationService', side_effect=notifications) as make:
            execution.observe_ai_event(event)
            make.assert_not_called()
            current = self.command('platform_configuration_open', project, 'feishu').payload
            current = self.command('platform_notifications_set', project, 'feishu', current['revision'], True).payload
            execution.observe_ai_event(event)
            self.assertTrue(peer.wait(3))
            current = self.command('platform_notifications_set', project, 'feishu', current['revision'], False).payload
            execution.observe_ai_event(dict(event, id='after-disable'))
            self.assertFalse(current['notifications_enabled'])
            self.assertFalse(execution.closing)
        api.send_text.assert_called_once()
        self.assertEqual(api.send_text.call_args.args[0], 'confirmed-group')
        self.assertIn('通道4', api.send_text.call_args.args[1])

    def test_controlled_extension_review_binds_project_hash_and_local_decision(self):
        first = self.command('create', self.root / 'first', '原项目').project_id
        second = self.command('create', self.root / 'second', '其它项目').project_id
        path = self.root / 'extension.json'
        manifest = dict(id='fixture_extension', name='查询通道', version='1', description='模拟审阅',
                        target_capability='channels.list', input_schema=dict(type='object', additionalProperties=False),
                        arguments={}, bindings={}, allowed_channels=[1])
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        preview = self.command('extension_review', first, path).payload
        self.assertEqual(preview['review']['manifest'], manifest)
        self.assertFalse(self.command('extension_list', first).payload['rows'])
        self.command('extension_approve', second, preview['token'], expected_error=True)
        self.command('extension_cancel', first, preview['token'])
        self.command('extension_approve', first, preview['token'], expected_error=True)
        preview = self.command('extension_review', first, path).payload
        listed = self.command('extension_approve', first, preview['token']).payload
        row, = listed['rows']
        self.assertEqual(row['reviewed_sha256'], preview['review']['reviewed_sha256'])
        self.assertTrue(row['enabled'])
        self.command('extension_set_enabled', first, row['id'], 'wrong-version', False, expected_error=True)
        closed = self.command('extension_set_enabled', first, row['id'], row['reviewed_sha256'], False).payload
        self.assertFalse(closed['rows'][0]['enabled'])
        self.assertFalse(self.command('extension_list', second).payload['rows'])

    def test_direct_platform_enable_requires_current_local_scope_and_exact_sender_identity(self):
        from src.services.workspace_platforms import PooledLease
        from test_feishu_remote import incoming

        class Transport:
            def __init__(self, *args, **kwargs):
                self.idle = False

            def start(self):
                pass

            def begin_close(self):
                self.idle = True

        project = self.command('create', self.root / 'project', '远程访问项目').project_id
        other = self.command('create', self.root / 'other', '原授权外的项目').project_id
        store = self.adapter._service.platform_config('feishu')
        store.save(dict(store.defaults(), app_id='cli_fixture', app_secret='fixture-secret',
                        group='confirmed-group', corp='tenant', group_name='目标群'))
        pool = self.adapter._service.platforms['feishu']
        pool.transport_factory, pool.lease_factory = Transport, PooledLease
        opened = self.command('platform_configuration_open', project, 'feishu').payload
        rejected = self.command('platform_direct_set', project, 'feishu', opened['revision'],
                                'group', True, expected_error=True)
        self.assertIn('远程访问范围', rejected.error)
        self.assertIsNone(pool.transport)
        self.adapter._service.remote_projects.add(project)
        applied = self.command('platform_direct_set', project, 'feishu', opened['revision'],
                               'group', True).payload
        self.assertTrue(applied['direct']['group'])
        remote = self.adapter._direct_platforms
        source = dict(kind='feishu', robot='cli_fixture', corp='tenant',
                      chat_type='group', group='confirmed-group', sender='member')
        self.assertTrue(remote.authorized(project, source))
        self.assertFalse(remote.authorized(other, source))
        self.assertFalse(remote.authorized(project, dict(source, group='other')))
        self.assertFalse(remote.authorized(project, dict(source, sender='')))
        scope = remote.active[project, 'feishu'][1]
        route = threading.Event()

        def capture(*args, **kwargs):
            route.set()
            raise ValueError('模拟路由，不执行')

        with patch.object(scope, 'reply'), patch.object(scope.conversation.router, 'send', side_effect=capture) as dispatch:
            pool.receive(incoming('项目 ' + project + ' 查看状态', user='member', chat='confirmed-group',
                                  tenant='tenant', app='cli_fixture'), 'bot1')
            self.assertTrue(route.wait(3))
            dispatched = dispatch.call_args.kwargs['source']
            self.assertEqual(dispatched['group'], 'confirmed-group')
            self.assertEqual(dispatched['sender'], 'member')
            pool.receive(incoming('项目 ' + project + ' 查看状态', identifier='other-message',
                                  chat='not-bound', tenant='tenant', app='cli_fixture'), 'bot1')
            self.assertEqual(dispatch.call_count, 1)
        updated = self.command('platform_direct_set', project, 'feishu', applied['revision'],
                               'p2p', True).payload
        self.assertTrue(updated['direct']['group'])
        self.assertTrue(updated['direct']['p2p'])
        self.command('platform_direct_set', project, 'feishu', updated['revision'], 'p2p', False)
        self.assertTrue(remote.authorized(project, source))
        self.adapter._service.remote_projects.remove(project)
        self.assertFalse(remote.authorized(project, source))
        self.wait_for(lambda: scope.stop_event.is_set() and pool.idle)

        dingtalk = self.adapter._service.platform_config('dingtalk')
        dingtalk.save(dict(dingtalk.load(), client_id='client', client_secret='fixture-secret',
                           robot_code='robot', group='target', corp='corp', group_name='目标群',
                           webhook='https://oapi.dingtalk.com/robot/send?access_token=fixture'))
        dt_pool = self.adapter._service.platforms['dingtalk']
        dt_pool.transport_factory, dt_pool.lease_factory = Transport, PooledLease
        self.adapter._service.remote_projects.add(project)
        opened = self.command('platform_configuration_open', project, 'dingtalk').payload
        started = self.command('platform_direct_set', project, 'dingtalk', opened['revision'],
                               'group', True).payload
        principal = dict(kind='dingtalk', robot='robot', corp='corp', group='target', sender='member')
        self.assertTrue(remote.authorized(project, principal))
        self.assertFalse(remote.authorized(project, dict(principal, robot='unbound')))
        self.command('platform_direct_set', project, 'dingtalk', started['revision'], 'group', False)
        self.assertFalse(remote.authorized(project, principal))
        self.assertTrue(dt_pool.idle)

    def test_legacy_unbound_dut_from_creation_can_be_mapped_in_main_channel_editor(self):
        profile = {'test_type': 'service_aging', 'type_config': {'collectors': ['voice']},
                   'duts': [{'label': '旧样机', 'hardware_id': 'LAB-1'}]}
        created = self.command('wizard_create', self.root, '旧草稿恢复', profile).project_id
        view = self.command('wizard_profile_get', created).payload['profile']
        self.assertFalse(view.get('environment_channels'))
        editor = self.command('channels_editor_open', created).payload
        self.assertEqual(editor.values['unbound_duts'], [
            {'dut_id': view['duts'][0]['dut_id'], 'label': '旧样机'}])
        self.command('channels_editor_close', created, {'token': editor.token})

    def test_model_template_only_shares_versioned_defaults_with_independent_new_projects(self):
        profile = {'model': 'AX1', 'test_type': 'power_cycle', 'optional_steps': ['wan'],
                   'type_config': {'target_cycles': 500}, 'requirements': 'private notes',
                   'software_version': 'field-build', 'duts': [{'label': 'bench 3', 'hardware_id': 'unit-1'}]}
        project = self.command('create_typed', self.root / 'source', 'source', profile).project_id
        view = self.command('wizard_profile_get', project).payload
        revision = view['saved_revision']
        saved = self.command('wizard_preset_save', project, revision, 0).payload['presets']
        self.assertEqual(view['profile']['optional_steps'], ['wan'])
        defaults = dict(model='AX1', test_type='power_cycle', optional_steps=[], type_config={'target_cycles': 500})
        self.assertEqual(saved, [dict(defaults, version=1)])
        self.assertEqual(self.command('wizard_draft_get').payload['presets'], saved)
        self.command('wizard_preset_save', project, revision, 0, expected_error=True)
        independent = self.command('create_typed', self.root / 'new', 'new', defaults).project_id
        self.command('wizard_profile_save', project, dict(view['profile'], model='ax1',
                     type_config={'target_cycles': 300}), view['token'])
        self.command('wizard_preset_save', project, revision, 1, expected_error=True)
        self.command('save', project)
        self.command('wizard_preset_save', project, revision, 1, expected_error=True)
        current = self.command('wizard_profile_get', project).payload
        updated = self.command('wizard_preset_save', project, current['saved_revision'], 1).payload['presets']
        self.assertEqual([(r['model'], r['version'], r['type_config']) for r in updated],
                         [('ax1', 2, {'target_cycles': 300})])
        copy = self.command('wizard_profile_get', independent).payload['profile']
        self.assertEqual((copy['type_config'], copy['duts'], copy['software_version'], copy['requirements']),
                         ({'target_cycles': 500}, [], '', ''))
        catalog = self.root / 'workspace/project_model_presets.json'
        catalog.write_text('invalid', encoding='utf-8')
        damaged = self.command('wizard_profile_get', independent).payload
        self.assertEqual(damaged['profile'], copy)
        self.assertTrue(damaged['preset_error'])
        self.command('wizard_preset_save', project, current['saved_revision'], 2, expected_error=True)
        self.assertEqual(catalog.read_text(encoding='utf-8'), 'invalid')

    def test_corrupt_typed_history_is_scoped_to_one_project(self):
        broken = self.command('create_typed', self.root / 'broken', '业务老化', {
            'test_type': 'service_aging', 'duts': [], 'type_config': {'collectors': ['voice']},
        }).project_id
        other = self.command('create', self.root / 'other', '另一个项目').project_id
        context = self.adapter._service.projects.opened[broken]
        (context.history / 'service_aging.sqlite3').write_bytes(b'invalid sqlite file')
        self.command('refresh')
        projects = {project.project_id: project for project in self.projects}
        self.assertFalse(projects[broken].can_start)
        self.assertIn('读取失败', projects[broken].state_text)
        self.assertTrue(projects[other].can_start)

    def test_dut_offline_and_business_alarm_count_the_affected_device_once(self):
        from src.services.aging_observation_source import Observation
        from src.services.service_aging import ServiceAging
        profile = {'test_type': 'service_aging', 'duts': [{'label': 'A'}, {'label': 'B'}],
                   'type_config': {'collectors': ['dut_presence', 'iptv'], 'feed_collectors': ['dut_presence', 'iptv']}}
        identifier = self.command('create_typed', self.root / 'rack', '老化测试架', profile).project_id
        service = ServiceAging(self.adapter._service.projects.opened[identifier])
        plan = service.prepare()
        job = 'rack-run-01'
        service.history.begin(job, plan, 60)
        first, second = [dut['dut_id'] for dut in plan['duts']]
        def observe(dut, collector):
            event = Observation(identifier, job, dut, collector, collector, time.time(), 'abnormal', '隔离测试')
            service.history.observe(job, dut, collector, event.outcome, event.evidence, '',
                                    kind='sample', feed_event=event)
        observe(first, 'iptv')
        observe(first, 'dut_presence')
        self.command('refresh')
        self.assertEqual(self.projects[0].attention_count, 1)
        observe(second, 'dut_presence')
        self.command('refresh')
        self.assertEqual(self.projects[0].attention_count, 2)

    def test_peer_mode_delivers_version_through_project_chat_and_local_approval(self):
        from contextlib import ExitStack
        from dataclasses import replace
        import os
        import socket
        import secrets
        import uuid
        from types import SimpleNamespace
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.ai_actions import ActionAssessment
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_store import profile_fingerprint
        from src.services.device_project_info_service import DeviceProjectInfo
        from src.services.remote_instance_identity import RemoteInstanceIdentity
        from src.core.project_peer_transport import ProjectPeerTransport
        from src.services.project_peer_router import ProjectPeerRouter
        from src.services.project_peer_runtime import PeerPlatforms
        from src.services.remote_gateway_store import RemoteGatewayStore
        from src.services.workspace_gateway import WorkspaceGatewayBridge
        from test_remote_gateway import PRINCIPAL, SCOPES

        self.close_adapter()
        with ExitStack() as scope:
            path = self.root / 'peers.json'
            scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'local'),
                DUTPILOT_PROJECT_PEERS=str(path), LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0'))
            identity = RemoteInstanceIdentity(SOURCE, slot=1)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            peer_dir = self.root / 'second-instance'
            peer_dir.mkdir()
            peer = SimpleNamespace(directory=peer_dir, instance_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()))
            empty = SimpleNamespace(remote_projects=set(), recent=[], projects=SimpleNamespace(opened={}))
            bridge = WorkspaceGatewayBridge(empty, peer, dict(scopes=SCOPES, channel_ids=[1], capability_ids=['device.version']))
            scope.callback(bridge.close)
            key = secrets.token_hex(32)
            scope.enter_context(patch.dict(os.environ, DUTPILOT_TEST_PEER_AB=key))
            links = {identity.instance_id: dict(host='127.0.0.1', port=port, key=key)}
            router = ProjectPeerRouter(peer, links, bridge, SCOPES, lambda line: None)
            scope.callback(router.close)
            link = ProjectPeerTransport(peer.instance_id, links, ('127.0.0.1', 0), vpn=False, dispatch=router.rpc)
            link.start()
            scope.callback(link.close)
            router.call_peer = link.call
            ledger = RemoteGatewayStore(peer_dir / 'platform')
            scope.callback(ledger.close)
            ingress = PeerPlatforms(ledger, {}, router, lambda line: None)
            remote = dict(instance_id=peer.instance_id, host='127.0.0.1', port=link.port, key_env='DUTPILOT_TEST_PEER_AB')
            path.write_text(json.dumps(dict(instance_id=identity.instance_id, host='127.0.0.1', port=port,
                vpn=False, peers=[remote], platforms=['feishu'], scopes=SCOPES, channel_ids=[1],
                capability_ids=['device.version'])), encoding='utf-8')
            identity.close()
            scope.enter_context(patch('src.services.project_peer_runtime.PeerPlatforms.start'))
            scope.enter_context(patch('src.services.workspace_service.WorkspaceService.platform_config',
                return_value=SimpleNamespace(load=lambda: dict(corp=PRINCIPAL.corp, group=PRINCIPAL.chat,
                                                              app_id=PRINCIPAL.robot, enabled=False))))
            query = scope.enter_context(patch('src.services.capability_device_services.query_device_project_info',
                return_value=DeviceProjectInfo('PEER-TEST-1', 'fixture', 'synthetic')))
            self.results.clear()
            self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace', start_configured_gateway=True)
            scope.callback(self.close_adapter)
            self.wait_for(lambda: (0, 'ready') in self.results)
            service = self.adapter._service
            runtime = service.gateway_runtime
            self.assertIsNotNone(runtime, service.gateway_error)
            result = self.command('create', self.root / 'peer-project', '项目A')
            project = result.project_id
            context = service.projects.opened[project]
            ChannelConfigStore(context.config_dir / 'network_card_ip.ini').save([
                ChannelConfig('channel_1', enabled=True, vlan_name='VLAN101', serial_port='COM701',
                              network_card_ip='192.0.2.11', device_manage_ip='192.0.2.1')])
            profile = service.models.save_profile(ProviderProfile(model='fixture-peer', context_tokens=65536), 'test-key')
            service.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            review = self.command('remote_scope_read').payload
            self.command('remote_scope_save', review.token, [project])
            chat = self.adapter._ai_chats[project]
            chat.diagnostic.client_factory = lambda *args: SimpleNamespace(
                complete=lambda history, tools, stop: ModelReply('模拟查询已完成', [], history), close=lambda: None)
            scope.enter_context(patch.object(chat.conversation, '_review_action',
                return_value=ActionAssessment('ordinary', '模拟版本查询')))
            ingress.receive(PRINCIPAL, 'version-1', '项目A 查询通道1版本')
            ingress.collect_results()
            runtime.platforms.collect_results()
            def pending():
                return next(((row['id'], act) for row in chat.store.chats()
                             for act in chat.store.actions(row['id'], ('waiting_approval',))), None)
            self.wait_for(pending)
            session, action = pending()
            self.assertEqual(chat.conversation.permissions.status(session)['mode'], 'ask')
            query.assert_not_called()
            self.command('ai_chat_select', project, session)
            self.command('ai_chat_decide', project, session, action['id'], action['fingerprint'], True)
            self.wait_for(lambda: query.called and session not in chat.conversation.running)
            runtime.platforms.receive(PRINCIPAL, 'version-1', '项目A 查询通道1版本')
            runtime.platforms.collect_results()
            self.assertTrue(any('PEER-TEST-1' in row[0] for row in runtime.store.db.execute('SELECT payload FROM replies')))
            self.assertFalse(router.deliveries())
            query.assert_called_once()

    def test_configured_gateway_restart_routes_project_controls_over_loopback(self):
        import os
        from contextlib import ExitStack
        from src.core.remote_gateway_transport import GatewayWebSocketServer
        from src.services.ai_project_store import project_directory
        from src.services.remote_gateway_platforms import GatewayPlatforms
        from src.services.remote_gateway_runtime import RemoteInstanceConfig
        from src.services.remote_gateway_store import RemoteGatewayStore
        from src.services.remote_instance_identity import RemoteInstanceIdentity
        from test_ai_core import FakeCipher
        from test_remote_gateway import PRINCIPAL, SCOPES

        paths = [self.root / name for name in ('first', 'second')]
        first, second = [self.command('create', path, name).project_id
                         for path, name in zip(paths, ('模拟甲', '模拟乙'))]
        review = self.command('remote_scope_read').payload
        self.command('remote_scope_save', review.token, [first])
        self.close_adapter()

        with ExitStack() as scope:
            scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'local'),
                                           LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0'))
            cipher = FakeCipher()
            scope.enter_context(patch('src.services.remote_gateway_runtime.WindowsCredentialCipher', return_value=cipher))
            ledger = RemoteGatewayStore(self.root / 'simulated-gateway', cipher=cipher)
            scope.callback(ledger.close)
            server = GatewayWebSocketServer(ledger).start()
            scope.callback(server.close)
            identity = RemoteInstanceIdentity(SOURCE, slot=4)
            try:
                paired = ledger.pair(ledger.create_pairing(SCOPES), identity.instance_id, '模拟电脑')
                RemoteInstanceConfig(identity, cipher).save(dict(paired, instance_id=identity.instance_id,
                    scopes=SCOPES, url=f'ws://127.0.0.1:{server.port}', vpn=False, enabled=True,
                    channel_ids=[1], capability_ids=['device.version']))
            finally:
                identity.close()
            settings = project_directory(SOURCE) / 'instance_startup.json'
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps(dict(mode='gateway', slot=4)), encoding='utf-8')
            self.results.clear()
            self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace', start_configured_gateway=True)
            scope.callback(self.close_adapter)
            self.wait_for(lambda: any(r.operation == 'ready' for r in self.results.values()))
            for path in paths:
                self.command('open', path)
            runtime = self.adapter._service.gateway_runtime
            self.assertIsNotNone(runtime)
            self.assertTrue(runtime.client.connected.wait(4))
            current = self.command('instance_status').payload
            self.assertEqual((current['current_mode'], current['current_slot'], current['connected']), ('gateway', 4, True))
            ledger.select(PRINCIPAL, current['instance_id'])

            def receive(message, text):
                req = ledger.route(PRINCIPAL, message, text)['request']
                def received():
                    return ledger.receipt(PRINCIPAL, req['request_id'])['state'] in ('done', 'rejected')
                self.wait_for(received)
                return ledger.receipt(PRINCIPAL, req['request_id'])

            before_selection = receive('business-before-selection', '查询版本')
            self.assertEqual(before_selection['state'], 'rejected')
            self.assertIn('未提交', before_selection['correlation']['notice'])
            directory = receive('directory-a', '项目列表')['correlation']['answer']
            self.assertIn(first, directory)
            self.assertNotIn(second, directory)
            self.assertIn('已选择项目', receive('select-a', '切换项目 ' + first)['correlation']['answer'])
            self.assertEqual(receive('unready', '查询版本')['state'], 'rejected')
            self.assertFalse(runtime.bridge.bridges)
            self.assertFalse(self.adapter._executions)
            review = self.command('remote_scope_read').payload
            self.command('remote_scope_save', review.token, [second])
            directory = receive('directory-b', '项目列表')['correlation']['answer']
            self.assertNotIn(first, directory)
            self.assertIn(second, directory)
            self.assertEqual(receive('revoked-business', '项目 ' + first + ' 查询版本')['state'], 'rejected')
            self.assertTrue(ledger.route(PRINCIPAL, 'unready', '查询版本')['duplicate'])
            review = self.command('remote_scope_read').payload
            self.command('remote_scope_save', review.token, [first, second])
            both = receive('after-regrant', '项目列表')['correlation']['answer']
            self.assertIn(first, both)
            self.assertIn(second, both)
            self.assertTrue(any('已拒绝本条消息' in row.message for row in self.logs))
            self.command('close', second)
            self.assertNotIn(second, receive('after-close', '项目列表')['correlation']['answer'])
            self.command('close', first)
            self.assertEqual(receive('after-last-close', '查询版本')['state'], 'rejected')
            self.close_adapter()
            self.assertTrue(runtime.client.idle)
            self.assertIsNone(runtime.identity.lease)

            # The persistent slot now contains receipts for the previous boot.
            self.results.clear()
            self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace', start_configured_gateway=True)
            self.wait_for(lambda: any(r.operation == 'ready' for r in self.results.values()))
            self.command('open', paths[0])
            restarted = self.adapter._service.gateway_runtime
            self.assertEqual(restarted.identity.instance_id, runtime.identity.instance_id)
            self.assertNotEqual(restarted.identity.run_id, runtime.identity.run_id)
            self.assertTrue(restarted.client.connected.wait(4))
            ledger.select(PRINCIPAL, restarted.identity.instance_id)
            self.assertIn(first, receive('second-boot-list', '项目列表')['correlation']['answer'])
            self.assertEqual(receive('second-boot-select', '切换项目 ' + first)['state'], 'done')
            delivered = []
            platforms = GatewayPlatforms(ledger, {}, senders={PRINCIPAL.platform: lambda *args: delivered.append(args)})
            acknowledge = ledger.acknowledge
            lost = threading.Event()

            def lose_first_rejection(instance, run, request, receipt):
                if receipt.get('state') == 'rejected' and not lost.is_set():
                    lost.set()
                    raise OSError('synthetic loss before acknowledgement')
                return acknowledge(instance, run, request, receipt)

            with patch.object(ledger, 'acknowledge', side_effect=lose_first_rejection):
                platforms.receive(PRINCIPAL, 'second-boot-stop', '停止')
                stop_request = ledger.route(PRINCIPAL, 'second-boot-stop', '停止')['request']['request_id']
                self.wait_for(lambda: ledger.receipt(PRINCIPAL, stop_request)['state'] == 'rejected')
            self.assertTrue(lost.is_set())
            platforms.receive(PRINCIPAL, 'second-boot-stop', '停止')
            platforms.collect_results()
            platforms.collect_results()
            queued = ledger.db.execute("SELECT count(*) FROM replies WHERE state='pending'").fetchone()[0]
            for _ in range(queued):
                platforms.send_one()
            refusals = [(principal, text) for principal, text, _ in delivered if stop_request in text and '已拒绝' in text]
            self.assertEqual(len(refusals), 1)
            self.assertEqual(refusals[0][0], PRINCIPAL)
            self.assertIn('未提交', refusals[0][1])
            self.assertFalse(restarted.bridge.bridges)
            self.assertFalse(self.adapter._executions)
            self.close_adapter()

            with patch('src.core.remote_gateway_transport.GatewayInstanceClient') as client:
                for saved, disabled, expected in (('gateway', '1', 'error'), ('direct', '0', 'direct')):
                    with self.subTest(saved=saved, disabled=disabled), patch.dict(os.environ, LINECHECK_DISABLE_CAPABILITIES=disabled):
                        settings.write_text(json.dumps(dict(mode=saved, slot=4)), encoding='utf-8')
                        self.results.clear()
                        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace', start_configured_gateway=True)
                        self.wait_for(lambda: any(r.operation == 'ready' for r in self.results.values()))
                        self.command('open', paths[0])
                        self.assertEqual(self.command('instance_status').payload['current_mode'], expected)
                        self.assertIsNone(self.adapter._service.gateway_runtime)
                        self.close_adapter()
                client.assert_not_called()

    def test_project_gateway_close_waits_for_receipts_and_workbench_waits_for_client(self):
        from unittest.mock import Mock

        first = self.command('create', self.root / 'first', '第一项目').project_id
        second = self.command('create', self.root / 'second', '第二项目').project_id
        workspace = self.adapter._service
        preparing, release_receipt = threading.Event(), threading.Event()
        stopping, client_finished = threading.Event(), threading.Event()

        class Runtime:
            bridge = Mock()
            close = Mock()

            def begin_close(self):
                stopping.set()

            @property
            def idle(self):
                return client_finished.is_set()

        def prepare(key):
            if key == first:
                preparing.set()
                return release_receipt.is_set()
            return True

        gateway = Runtime()
        gateway.bridge.prepare_project_close.side_effect = prepare
        with patch.object(workspace, 'gateway_runtime', gateway):
            try:
                request = self.adapter.submit('close', first)
                self.assertTrue(preparing.wait(2))
                scope = self.command('remote_scope_read').payload
                self.assertEqual({row[0] for row in scope.rows}, {first, second})
                self.assertNotIn((request, 'close'), self.results)
                gateway.bridge.detach.assert_not_called()
                release_receipt.set()
                self.wait_for(lambda: (request, 'close') in self.results)
                self.assertFalse(self.results[request, 'close'].error)
                gateway.bridge.detach.assert_called_once_with(first)

                self.adapter.begin_close()
                self.assertTrue(stopping.wait(2))
                self.assertIn(second, workspace.projects.opened)
                self.assertFalse(self.adapter.closed.is_set())
                gateway.close.assert_not_called()
                client_finished.set()
                self.assertTrue(self.adapter.wait_closed(5))
                gateway.bridge.detach.assert_called_with(second)
                gateway.close.assert_called_once()
                self.assertFalse(workspace.projects.opened)
            finally:
                release_receipt.set()
                client_finished.set()

    def test_remote_scope_save_rechecks_open_contexts_and_original_grants(self):
        from unittest.mock import Mock
        first = self.command('create', self.root / 'scope-a', '同名项目').project_id
        second = self.command('create', self.root / 'scope-b', '同名项目').project_id
        workspace = self.adapter._service
        workspace.set_remote_projects([first])
        review = self.command('remote_scope_read').payload
        self.command('close', second)
        self.command('open', self.root / 'scope-b')
        self.command('remote_scope_save', review.token, [second], expected_error=True)
        self.assertEqual(workspace.remote_projects, {first})
        review = self.command('remote_scope_read').payload
        workspace.set_remote_projects([])
        self.command('remote_scope_save', review.token, [second], expected_error=True)
        self.assertFalse(workspace.remote_projects)
        workspace.set_remote_projects([first])
        review = self.command('remote_scope_read').payload
        controller = Mock()
        with patch.dict(workspace.controllers, {first: controller}):
            self.command('remote_scope_save', review.token, [second])
        self.assertEqual([call.args for call in controller.conversation.router.cancel_platform.call_args_list],
                         [('dingtalk',), ('feishu',)])
        self.assertEqual(json.loads((workspace.directory / 'remote_projects.json').read_text(encoding='utf-8')), [second])
        self.command('remote_scope_save', review.token, [first], expected_error=True)
        self.assertEqual(workspace.remote_projects, {second})
        fresh = self.command('remote_scope_read').payload
        self.command('remote_scope_save', fresh.token, ['missing'], expected_error=True)
        self.assertEqual(workspace.remote_projects, {second})

    def test_window_placement_reads_old_state_merges_preferences_and_handles_write_failure(self):
        from src.models.qt_window_placement import WindowPlacement

        project = self.command('create', self.root / 'window-state', '布局项目').project_id
        other = self.command('create', self.root / 'window-state-other', '独立布局项目').project_id
        workspace = self.adapter._service
        serial = workspace.projects.opened[project].root / 'ui/serial.json'
        dut = workspace.projects.opened[project].root / 'ui/dut.json'
        serial.parent.mkdir(exist_ok=True)
        raw_serial = dict(geometry='1050x680+80+90', log_dir=str(self.root), unrelated='fixture')
        raw_dut = dict(window_size=dict(width=920, height=630),
                       current_status_heights=dict(telnet=9, wan='99', voice='broken', future='keep'))
        serial.write_text(json.dumps(raw_serial), encoding='utf-8')
        dut.write_text(json.dumps(raw_dut), encoding='utf-8')
        self.assertEqual(self.command('serial_show', project).payload['placement'], WindowPlacement(1050, 680, 80, 90, True))
        legacy_dut = self.command('dut_show', project).payload
        self.assertEqual(legacy_dut['placement'], WindowPlacement(920, 630))
        self.assertEqual(legacy_dut['status_heights'], dict(telnet=9, wan=16, voice=4))
        self.assertIsNone(self.command('serial_show', other).payload['placement'])
        self.assertIsNone(self.command('dut_show', other).payload['placement'])
        with self.adapter.lock:
            self.adapter.remember_window_placement(project, 'serial', WindowPlacement(790, 490, 30, 40))
            self.adapter.remember_window_placement(project, 'serial', WindowPlacement(800, 500, -35, 50))
            self.adapter.remember_window_placement(project, 'dut', WindowPlacement(745, 485, 60, 70))
        self.assertEqual(self.command('serial_show', project).payload['placement'], WindowPlacement(800, 500, -35, 50))
        self.assertEqual(self.command('dut_show', project).payload['placement'], WindowPlacement(745, 485))
        self.assertEqual(json.loads(serial.read_text(encoding='utf-8')), dict(raw_serial,
            qt_geometry=dict(width=800, height=500, x=-35, y=50)))
        self.assertEqual(json.loads(dut.read_text(encoding='utf-8')), dict(raw_dut, window_size=dict(width=745, height=485)))
        with self.adapter.lock:
            self.adapter.remember_window_placement(project, 'dut', status_heights={'telnet': 6})
            self.adapter.remember_window_placement(project, 'dut', status_heights={'wifi_2g': -5, 'wifi_5g': 7})
        self.assertEqual(self.command('dut_show', project).payload['status_heights'],
                         dict(telnet=6, wan=16, wifi_2g=2, wifi_5g=7, voice=4))
        state = json.loads(dut.read_text(encoding='utf-8'))
        self.assertEqual(state['window_size'], dict(width=745, height=485))
        self.assertEqual(state['current_status_heights']['future'], 'keep')
        self.assertEqual(self.command('dut_show', other).payload['status_heights'], {})
        with patch('src.services.qt_window_state.atomic_json', side_effect=PermissionError):
            self.adapter.remember_window_placement(project, 'dut', WindowPlacement(755, 495))
            self.command('close', project)
        self.assertNotIn(project, workspace.projects.opened)
        self.assertEqual(json.loads(dut.read_text(encoding='utf-8'))['window_size'], dict(width=745, height=485))
        self.assertTrue(any(row.level == 'WARN' and '窗口状态保存失败' in row.message for row in self.logs))

    def test_module_sizes_share_the_tk_file_and_save_only_the_current_project(self):
        from src.models.qt_window_placement import WindowPlacement
        from src.ui.window_size_state import load_module_window_size, save_module_window_size

        directory = self.root / 'legacy-window-size'
        project = self.command('create', directory, '原项目').project_id
        other = self.command('create', self.root / 'other-window-size', '其它项目').project_id
        self.command('close', project)
        state = directory / 'ui/module_windows.json'
        state.parent.mkdir(exist_ok=True)
        state.write_text(json.dumps({'window_sizes': {'future': {'width': 400, 'height': 300},
            'sample_upgrade': {'width': 'broken', 'height': 600}}, 'reserved': True}), encoding='utf-8')
        options = dict(default_width=760, default_height=440, min_width=560, min_height=300)
        self.assertTrue(save_module_window_size(state, 'power_test_channel_history', 823, 491, **options))
        self.assertEqual(self.command('open', directory).project_id, project)
        placement = self.adapter.module_window_placement
        self.assertEqual(placement(project, 'power_test_channel_history'), WindowPlacement(823, 491))
        self.assertIsNone(placement(project, 'sample_upgrade'))
        self.assertIsNone(placement(other, 'power_test_channel_history'))

        self.adapter.remember_window_placement(project, 'power_test_channel_history', WindowPlacement(801, 501, 80, 70))
        self.assertEqual(placement(project, 'power_test_channel_history').width, 801)
        self.adapter.remember_window_placement(project, 'pipeline', WindowPlacement(924, 600))
        self.command('close', project)
        self.assertIsNone(placement(project, 'pipeline'))
        self.adapter.remember_window_placement(project, 'pipeline', WindowPlacement(888, 500))
        payload = json.loads(state.read_text(encoding='utf-8'))
        self.assertEqual(payload['window_sizes']['pipeline'], {'width': 924, 'height': 600})
        self.assertEqual(payload['window_sizes']['power_test_channel_history'], {'width': 801, 'height': 501})
        self.assertEqual(payload['window_sizes']['future'], {'width': 400, 'height': 300})
        self.assertTrue(payload['reserved'])
        self.assertFalse((self.root / 'other-window-size/ui/module_windows.json').exists())
        self.assertEqual(load_module_window_size(state, 'power_test_channel_history',
            screen_width=1920, screen_height=1080, **options), (801, 501))
        self.command('open', directory)
        self.assertEqual(placement(project, 'pipeline'), WindowPlacement(924, 600))

    def test_health_tracks_actual_log_failure_and_recovery_separately_from_task_logs(self):
        status = self.adapter.health_snapshot()
        self.assertIsNone(status.task_log_at)
        self.assertIsNone(status.inventory_check)
        self.adapter._emit('普通工作区记录')
        self.assertIsNone(self.adapter.health_snapshot().task_log_at)
        task_log = LogView('09:10:11', 'INFO', 'p1', '工程', '测试任务记录', 'job-1')
        self.assertTrue(self.adapter._log_writer.flush())
        with patch.object(Path, 'open', side_effect=PermissionError('synthetic write denial')):
            self.adapter._record(task_log)
            self.assertTrue(self.adapter._log_writer.flush())
        failed = self.adapter.health_snapshot()
        self.assertIsNotNone(failed.task_log_at)
        self.assertFalse(failed.log_write[1])
        self.assertEqual(failed.log_write_failures, 1)
        self.drain()
        self.assertTrue(any(log.level == 'ERROR' and 'PermissionError' in log.message for log in self.logs))
        self.adapter._emit('写入恢复')
        self.assertTrue(self.adapter._log_writer.flush())
        recovered = self.adapter.health_snapshot()
        self.assertTrue(recovered.log_write[1])
        self.assertEqual(recovered.log_write_failures, 1)
        self.assertEqual(recovered.task_log_at, failed.task_log_at)
        path = self.root / 'workspace' / 'workspace.log'
        self.assertIn('写入恢复', path.read_text(encoding='utf-8'))
        self.assertNotIn('测试任务记录', path.read_text(encoding='utf-8'))

    def test_update_worker_can_log_after_business_close_and_window_waits_for_disk(self):
        from src.services.workspace_event_log import read_workspace_events
        self.adapter.begin_close(update_logs_pending=True)
        self.assertTrue(self.adapter.wait_closed())
        service = self.adapter._service
        writer = self.adapter._log_writer
        self.assertEqual(service.emit, self.adapter._emit)
        self.assertIsNotNone(service.resources.recovery_context)
        self.assertTrue(callable(writer.report))
        self.assertTrue(callable(writer.associate))
        entered, release = threading.Event(), threading.Event()
        write = self.adapter._log_writer._write_text
        def slow(batch):
            entered.set()
            release.wait(5)
            write(batch)
        with patch.object(self.adapter._log_writer, '_write_text', side_effect=slow):
            try:
                self.adapter.record_update_log('更新取消末条原文')
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.adapter.finish_log_close())
                self.assertEqual(service.emit, self.adapter._emit)
                self.assertTrue(callable(writer.associate))
                self.assertEqual(self.adapter.health_snapshot().log_write_failures, 0)
            finally:
                release.set()
                self.adapter._log_writer.close()
        self.assertTrue(self.adapter.finish_log_close())
        self.assertEqual(read_workspace_events(self.root / 'workspace')[0]['message'], '更新取消末条原文')
        self.assertIn('更新取消末条原文', (self.root / 'workspace/workspace.log').read_text(encoding='utf-8'))
        self.assertIsNone(writer.report)
        self.assertIsNone(writer.associate)
        self.assertIsNone(service.resources.recovery_context)
        self.assertNotEqual(service.emit, self.adapter._emit)
        self.assertTrue(self.adapter.finish_log_close())
        self.adapter.begin_close()
        self.assertTrue(self.adapter.wait_closed())

    def test_display_backlog_limits_preserve_the_workspace_file(self):
        self.drain()
        before = self.adapter.health_snapshot().logs_omitted
        for number in range(510):
            self.adapter._emit(f'合成积压记录 #{number:03d}')
        self.assertEqual(self.adapter.health_snapshot().logs_omitted - before, 10)
        _, rows, _ = self.adapter.take_updates()
        self.assertEqual(len(rows), 500)
        self.assertTrue(rows[0].message.endswith('#010'))
        self.assertTrue(rows[-1].message.endswith('#509'))
        self.adapter._emit('大' * (128 * 1024 + 1))
        self.assertEqual(self.adapter.take_updates()[1], ())
        self.assertEqual(self.adapter.health_snapshot().logs_omitted - before, 11)
        self.assertTrue(self.adapter._log_writer.flush())
        contents = (self.root / 'workspace' / 'workspace.log').read_text(encoding='utf-8')
        self.assertEqual(contents.count('合成积压记录 #'), 510)
        self.assertIn('大' * (128 * 1024 + 1), contents)

    def test_ai_log_projection_preserves_archive_and_does_not_displace_live_alerts(self):
        from src.ui.qt.log_presentation import project_live_log
        from test_main_log_filter import ai_json, ai_recorded_run

        self.adapter._display_log = project_live_log
        self.drain()
        omitted = self.adapter.health_snapshot().logs_omitted
        raw = ai_recorded_run()
        noise = '[AI对话] 会话12345678模型请求成功'
        unknown = ai_json('操作12345678结束', dict(action_state='unknown', stdout='需人工核对的原始输出'))
        broken = '[AI对话] 操作12345678结束：{后端新格式'
        ordinary = '[旧工具Logs][INFO] ' + noise
        explicit = LogView('09:10:12', 'ERROR', 'project-fixture', '合成项目', noise, 'job-a', 7)

        for message in (*raw, unknown, broken, ordinary, *(noise,) * 550):
            self.adapter._record(LogView('09:10:12', 'INFO', 'project-fixture', '合成项目', message, 'job-a', 7))
        self.adapter._record(explicit)
        _, displayed, _ = self.adapter.take_updates()
        self.assertEqual([row.level for row in displayed], ['INFO', 'INFO', 'WARN', 'INFO', 'INFO', 'ERROR'])
        self.assertIn('开始排查（已入队）', displayed[0].message)
        self.assertIn('本轮结束', displayed[1].message)
        self.assertIn('结果待核实', displayed[2].message)
        self.assertNotIn('需人工核对的原始输出', displayed[2].message)
        self.assertEqual(displayed[3].message, broken)
        self.assertEqual(displayed[4].message, ordinary)
        self.assertEqual(displayed[5], explicit)
        self.assertTrue(all((entry.project_id, entry.run_id, entry.channel) == ('project-fixture', 'job-a', 7)
                            for entry in displayed))
        status = self.adapter.health_snapshot()
        self.assertEqual(status.logs_omitted, omitted)
        self.assertIsNotNone(status.task_log_at)
        self.assertTrue(self.adapter._log_writer.flush())
        contents = (self.root / 'workspace/workspace.log').read_text(encoding='utf-8')
        for message in (*raw, unknown, broken, ordinary):
            self.assertIn(message, contents)
        self.assertGreaterEqual(contents.count(noise), 551)

    def test_concurrent_log_burst_keeps_every_record_on_disk_with_bounded_handoff(self):
        from concurrent.futures import ThreadPoolExecutor

        self.drain()
        before = self.adapter.health_snapshot()
        path = self.root / 'workspace' / 'workspace.log'
        self.assertTrue(self.adapter._log_writer.flush())
        previous_length = len(path.read_text(encoding='utf-8')) if path.exists() else 0
        producers, count = 4, 1500

        def write(producer):
            for number in range(count):
                self.adapter._record(LogView('09:10:11', 'INFO', f'p{producer}', f'合成项目 {producer}',
                                             f'合成压力记录 {number:04d}', f'job-{producer}', producer + 1))

        with ThreadPoolExecutor(max_workers=producers) as pool:
            results = [pool.submit(write, producer) for producer in range(producers)]
            for result in results:
                result.result(timeout=25)
        self.assertTrue(self.adapter._log_writer.flush())
        _, rows, _ = self.adapter.take_updates()
        health = self.adapter.health_snapshot()
        self.assertEqual(len(rows), 500)
        self.assertEqual(health.logs_omitted - before.logs_omitted, producers * count - len(rows))
        self.assertEqual(health.log_write_failures, before.log_write_failures)
        self.assertTrue(health.log_write[1])
        self.assertTrue(all(row.channel == int(row.project_id[1:]) + 1 for row in rows))
        self.assertTrue(all(row.run_id == 'job-' + row.project_id[1:] for row in rows))

        self.adapter.begin_close()
        self.assertTrue(self.adapter.wait_closed(5))
        contents = path.read_text(encoding='utf-8')[previous_length:].splitlines()
        burst = [line for line in contents if '合成压力记录' in line]
        self.assertEqual(len(burst), producers * count)
        for producer in range(producers):
            prefix = f'09:10:11 [p{producer}] 合成压力记录 '
            self.assertEqual([line for line in burst if line.startswith(prefix)],
                             [prefix + f'{number:04d}' for number in range(count)])

    def test_model_configuration_shares_accounts_but_keeps_project_selection_and_secrets_local(self):
        from src.services.ai_case_store import open_shared_cases

        project = self.command('create', self.root / 'models-a', '模型项目 A').project_id
        other = self.command('create', self.root / 'models-b', '模型项目 B').project_id
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-ai'), \
                patch('src.services.ai_case_store.open_shared_cases',
                   side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'case-fixture')):
            initial = self.command('ai_model_open', project).payload
            self.assertTrue(initial.draft)
            self.assertEqual(initial.profile.timeout, 60)
            args = dict(name='模拟账号', provider='DeepSeek', base_url='https://models.example.invalid/v1/',
                        protocol='chat_completions', model='model-fixture', timeout='65', max_output='1024',
                        context_tokens='8192', source_ip='192.0.2.19')
            secret = 'temporary-synthetic-key-test'
            stored = self.command('ai_model_save', project, initial.profile, True, args, secret).payload
            self.assertEqual(stored.profile.base_url, 'https://models.example.invalid/v1')
            self.assertEqual(stored.context_tokens, 8192)
            self.assertNotIn(secret, repr(stored))
            models = self.adapter._service.models
            self.assertEqual(models.key(stored.profile), secret)
            with models.lock:
                credential, = models.db.execute('SELECT credential FROM profiles').fetchone()
            self.assertNotIn(secret.encode(), credential)

            shared = self.command('ai_model_open', other).payload
            self.assertEqual(shared.profiles, (stored.profile,))
            original = self.adapter._model_settings.stores[project]
            separate = self.adapter._model_settings.stores[other]
            self.assertEqual(original.setting('selected_profile'), stored.profile.id)
            self.assertIsNone(separate.setting('selected_profile'))
            self.command('ai_model_select', other, stored.profile.id)
            self.assertEqual(separate.setting('selected_profile'), stored.profile.id)
            updated = self.command('ai_model_save', project, stored.profile, False, dict(args, name='更新账号'), '').payload
            self.assertEqual(models.key(updated.profile), secret)
            self.command('ai_model_delete', other, stored.profile, expected_error=True)
            self.assertEqual(models.profiles(), [updated.profile])
            self.command('ai_model_delete', project, updated.profile)
            self.assertFalse(models.profiles())
            self.assertFalse(any(secret in entry.message for entry in self.logs))

    def test_local_chat_reuses_project_history_and_cancels_before_store_close(self):
        from dataclasses import asdict, replace
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        started, stopping, release = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        class Client(DiagnosticModelClient):
            from qt_execution_fakes import continue_chat_intent as complete

            def complete_stream(self, history, tools, stop, on_text=None):
                if tools:
                    raise AssertionError('ordinary question and answer must not receive tools')
                on_text('模型回复草稿')
                started.set()
                if not stop.wait(6):
                    raise AssertionError('close did not cancel the original conversation')
                stopping.set()
                release.wait(6)
                raise InterruptedError('模拟取消')

        first = self.command('create', self.root / 'local-chat-a', '会话项目 A').project_id
        second = self.command('create', self.root / 'local-chat-b', '会话项目 B').project_id
        workspace = self.adapter._service
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-chat'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'chat-case-fixture')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService', side_effect=partial(AiDiagnosticService, client_factory=Client)):
            self.command('ai_model_open', first)
            profile = workspace.models.save_profile(ProviderProfile(model='fixture-chat', context_tokens=32768), 'chat-fixture-key')
            profile = workspace.models.save_profile(replace(profile, capability='可自动诊断',
                tested_fingerprint=profile_fingerprint(profile)))
            fixture = self.adapter._model_settings.stores[first]
            fixture.create_chat(dict(id='old-pc-fixture', created='2026-10-01T08:00:00', title='历史电脑会话', run_id='',
                scope='pc', target=None, profile=asdict(profile), status='可继续', settings={}, pending=None))
            self.command('ai_chat_open', first)
            legacy = self.command('ai_chat_select', first, 'old-pc-fixture').payload
            self.assertFalse(legacy.writable)
            fixture.update_chat(legacy.selected, permission_mode='full_access')
            permission = self.command('ai_chat_permissions', first, legacy.selected).payload
            self.assertEqual(permission, (legacy.selected, '完全访问', '帮我批准', False))
            self.assertEqual(fixture.chat(legacy.selected)['permission_mode'], 'full_access')
            self.command('ai_chat_permissions', second, legacy.selected, expected_error=True)
            conversation = self.adapter._ai_chats[first].conversation
            self.assertEqual(self.command('ai_chat_review', first, legacy.selected).payload, (legacy.selected, None))
            pending = dict(session_id=legacy.selected, id='review-a', fingerprint='fixture-fingerprint')
            with patch.object(conversation.actions, 'pending', return_value=pending), \
                    patch.object(conversation.actions, 'decide') as decide:
                self.command('ai_chat_decide', first, legacy.selected, 'review-a', 'old-fingerprint', True,
                             expected_error=True)
                decide.assert_not_called()
                self.command('ai_chat_decide', first, legacy.selected, 'review-a', 'fixture-fingerprint', False)
                decide.assert_called_once_with(legacy.selected, 'review-a', 'fixture-fingerprint', False)
            self.assertFalse(self.adapter._ai_chats[first].conversation.permissions.grants)
            self.command('ai_chat_send', first, legacy.selected, '不应派发', expected_error=True)
            self.assertFalse(started.is_set())

            view = self.command('ai_chat_new', first).payload
            selected = view.selected
            self.command('ai_chat_permissions', first, legacy.selected, expected_error=True)
            self.assertTrue(view.writable)
            self.assertEqual(fixture.chat(selected)['profile']['id'], profile.id)
            self.assertEqual(self.command('ai_chat_open', second).payload.sessions, ())
            self.command('ai_chat_select', second, selected, expected_error=True)
            self.command('ai_chat_rename', first, selected, '研发回归')
            data = self.root / 'evidence-fixture.txt'
            data.write_text('测试导入原文', encoding='utf-8')
            self.command('ai_chat_import', first, selected, data)
            self.assertIn('测试导入原文', self.command('ai_chat_evidence', first, selected).payload[0][2])
            self.command('ai_chat_send', first, selected, '合成问题')
            try:
                self.assertTrue(started.wait(3))
                view = self.command('ai_chat_poll', first).payload
                self.assertEqual(view.draft, '模型回复草稿')
                self.command('ai_chat_delete', first, selected, expected_error=True)
                close_request = self.adapter.submit('close', first)
                self.assertTrue(stopping.wait(3))
                self.assertIn(first, workspace.projects.opened)
                self.assertIn('合成问题', repr(fixture.chat_items(selected)))
                self.assertNotIn((close_request, 'close'), self.results)
            finally:
                release.set()
            self.wait_for(lambda: (close_request, 'close') in self.results and
                          first not in {project.project_id for project in self.projects})
            self.assertFalse(self.results[close_request, 'close'].error)
            self.command('open', self.root / 'local-chat-a')
            restored = self.command('ai_chat_open', first).payload
            self.assertEqual(restored.selected, selected)
            self.assertIn('研发回归', {item.title for item in restored.sessions})
            self.assertTrue(any('回复未完成' in message.text for message in restored.messages))
            fixture = self.adapter._model_settings.stores[first]
            fixture.append_chat(selected, {'role': 'system', 'kind': 'error', 'text': '分页之外的实际状态'})
            fixture.append_chat(selected, {'role': 'system', 'kind': 'context', 'text': '上下文容量：只显示在容量区'})
            for number in range(121):
                fixture.append_chat(selected, {'role': 'user', 'text': f'分页消息 {number}'})
            newest = self.command('ai_chat_page', first, selected, None).payload
            self.assertEqual(newest.latest_status.text, '分页之外的实际状态')
            self.assertEqual([message.text for message in newest.messages],
                             [f'分页消息 {number}' for number in range(1, 121)])
            older = self.command('ai_chat_page', first, selected, newest.next_cursor).payload
            self.assertEqual(older.messages[-1].text, '分页消息 0')
            self.assertIsNone(older.next_cursor)
            self.assertTrue(data.is_file())
            self.command('ai_chat_delete', first, selected)
            self.assertTrue(data.is_file())

    def test_ai_session_manager_rejects_cross_project_and_busy_batches_and_deletes_related_records(self):
        from dataclasses import asdict
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_case_store import open_shared_cases

        project = self.command('create', self.root / 'chat-manage', '会话管理项目').project_id
        other = self.command('create', self.root / 'chat-other', '独立会话项目').project_id
        workspace = self.adapter._service
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-manage'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'manager-cases')):
            profile = workspace.models.save_profile(ProviderProfile(model='manage-fixture'), 'synthetic-manager-key')
            self.command('ai_chat_open', project)
            self.command('ai_chat_open', other)
            chosen = self.command('ai_chat_new', project).payload.selected
            foreign = self.command('ai_chat_new', other).payload.selected
            chat = self.adapter._ai_chats[project]
            store = chat.store
            common = dict(created='2026-10-05T08:00:00', run_id='fixture', target=None,
                          profile=asdict(profile), status='可继续')
            store.create_chat(dict(common, id='batch-parent', title='旧批量会话', batch_children={'1': 'batch-child'}))
            store.create_chat(dict(common, id='batch-child', title='内部记录', batch_parent='batch-parent'))
            other_local = 'older-session'
            store.create_chat(dict(common, id=other_local, title='另一条历史'))
            store.add_chat_evidence('batch-child', {'source': 'fixture', 'text': '合成子会话证据', 'run_id': 'fixture'})
            store.save_report('manager-report-fixture', dict(report='保留报告'))
            for number in range(121):
                store.append_chat(chosen, {'role': 'user', 'text': f'保留消息 {number}'})
            newest = self.command('ai_chat_page', project, chosen, None).payload
            page = self.command('ai_chat_page', project, chosen, newest.next_cursor).payload
            for invalid in (foreign, 'batch-child'):
                self.command('ai_chat_delete_many', project, (other_local, invalid), expected_error=True)
                self.assertEqual(store.chat(other_local)['title'], '另一条历史')
            with chat.conversation.lock:
                chat.conversation.executors['batch-child'] = object()
            try:
                view = self.command('ai_chat_manage', project).payload
                self.assertNotIn('batch-child', {row.identifier for row in view.sessions})
                self.assertTrue(next(row.busy for row in view.sessions if row.identifier == 'batch-parent'))
                result = self.command('ai_chat_delete_many', project, (other_local, 'batch-parent'), expected_error=True)
                self.assertIn('本次全部会话均未删除', result.error)
                self.assertEqual(store.chat(other_local)['title'], '另一条历史')
            finally:
                with chat.conversation.lock:
                    chat.conversation.executors.pop('batch-child')
            view = self.command('ai_chat_delete_many', project, (other_local, 'batch-parent')).payload
            self.assertEqual(view.deleted, 3)
            self.assertEqual(view.selected, chosen)
            self.assertEqual((view.messages, view.next_cursor), (page.messages, page.next_cursor))
            self.assertEqual([row['id'] for row in store.chats()], [chosen])
            self.assertEqual(store.chat_evidence('batch-child'), [])
            self.assertEqual(store.report('manager-report-fixture')['report'], '保留报告')
            self.assertEqual(self.command('ai_chat_manage', other).payload.selected, foreign)
            self.command('close', project)
            self.wait_for(lambda: project not in workspace.projects.opened)
            self.command('open', self.root / 'chat-manage')
            restored = self.command('ai_chat_open', project).payload
            self.assertEqual([row.identifier for row in restored.sessions], [chosen])

    def test_ai_reports_reuse_project_store_and_reject_a_busy_deletion_batch(self):
        from src.services.ai_case_store import open_shared_cases

        first = self.command('create', self.root / 'reports-a', '报告项目 A').project_id
        second = self.command('create', self.root / 'reports-b', '报告项目 B').project_id
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-reports'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'report-case-fixture')):
            for identifier in (first, second):
                self.command('ai_chat_open', identifier)
            stores = self.adapter._model_settings.stores
            store = stores[first]
            payload = dict(report='## 原报告', evidence='[{"tool":"合成探测","evidence":"结果"}]\n原始日志尾部',
                           channel=3, question='报告标题', status='完成')
            store.save_report('report-a', payload)
            store.save_report('report-busy', dict(payload, report='生成中'))
            stores[second].save_report('report-a', dict(payload, report='另一个项目'))
            stores[second].save_report('other-only', payload)
            store.create_chat(dict(id='linked-chat', created='2026-11-20T08:00:00', source_report_id='report-a', status='可继续'))
            store.add_chat_evidence('linked-chat', dict(source='fixture', text='留存材料', run_id='fixture-run'))
            diagnostic = self.adapter._ai_chats[first].diagnostic
            entry = ('report-busy', 3, threading.Event())
            with diagnostic.lock:
                diagnostic.stops.add(entry)
            try:
                view = self.command('ai_report_open', first, 'report-a').payload
                self.assertEqual({row.identifier: row.busy for row in view.rows},
                                 {'report-a': False, 'report-busy': True})
                self.assertEqual(view.detail.analysis, '## 原报告')
                self.assertIn('原始日志尾部', view.detail.evidence)
                self.command('ai_report_select', first, 'other-only', expected_error=True)
                self.command('ai_report_rename', first, 'report-a', '本地显示标题')
                self.assertEqual(store.report('report-a'), payload)
                self.assertEqual(stores[second].record_titles('report'), {})
                self.command('ai_report_delete', first, 'report-a', ('report-a', 'report-busy'), expected_error=True)
                self.assertEqual(len(store.reports()), 2)
            finally:
                with diagnostic.lock:
                    diagnostic.stops.discard(entry)
            self.assertEqual(store.record_titles('report'), {'report-a': '本地显示标题'})
            view = self.command('ai_report_delete', first, 'report-a', ('report-a', 'report-busy')).payload
            self.assertEqual(view.deleted, 2)
            self.assertIsNone(view.detail)
            self.assertEqual(store.chat('linked-chat')['source_report_id'], 'report-a')
            self.assertEqual(store.chat_evidence('linked-chat')[0]['text'], '留存材料')
            self.assertEqual(stores[second].report('report-a')['report'], '另一个项目')

    def test_ai_case_edits_reuse_shared_store_and_preserve_version_protection(self):
        from src.services.ai_case_store import open_shared_cases

        first = self.command('create', self.root / 'case-a', '案例项目 A').project_id
        second = self.command('create', self.root / 'case-b', '案例项目 B').project_id
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-cases'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'shared-cases')):
            for identifier in (first, second):
                self.command('ai_chat_open', identifier)
            stores = self.adapter._model_settings.stores
            report = {'report': '未核实的模型假设'}
            stores[first].save_report('case-source', report)
            self.command('ai_case_from_report', second, 'case-source', expected_error=True)
            draft = self.command('ai_case_from_report', first, 'case-source').payload
            self.assertEqual((draft.selected, draft.report_id, draft.rows), (None, 'case-source', ()))
            fields = ('合成案例', '复核原因', '调整后复测', '通过', '测试设备')
            self.command('ai_case_save', first, None, None, draft.report_id, fields[:-1] + ('',), expected_error=True)
            self.assertEqual(stores[first].cases(include_inactive=True), [])
            view = self.command('ai_case_save', first, None, None, draft.report_id, fields).payload
            original, = view.rows
            self.assertEqual(original.identifier, view.selected)
            self.assertEqual(original.report_id, 'case-source')
            self.assertTrue(original.active)
            other = self.command('ai_case_open', second, None, '').payload
            self.assertEqual(other.rows, (original,))
            revision = fields[:-1] + ('设备版本 V2',)
            view = self.command('ai_case_save', second, original.identifier, original.version, original.report_id, revision).payload
            current, = view.rows
            self.assertEqual(current.version, original.version + 1)
            self.assertEqual(current.fields, revision)
            self.command('ai_case_toggle', first, original.identifier, original.version, expected_error=True)
            self.command('ai_case_delete', first, original.identifier, None, expected_error=True)
            latest = self.command('ai_case_toggle', first, current.identifier, current.version).payload.rows[0]
            self.assertFalse(latest.active)
            self.assertEqual(stores[second].cases(), [])
            snapshot = stores[first].case_store.snapshot()['cases'][0]
            self.assertEqual(len(snapshot['revisions']), 2)
            self.assertEqual(snapshot['report_id'], 'case-source')
            self.command('ai_case_delete', first, latest.identifier, latest.version)
            self.assertEqual(stores[second].cases(include_inactive=True), [])
            self.assertEqual(stores[second].case_store.import_snapshot({'schema_version': 1, 'cases': [snapshot]}), 0)
            self.assertEqual(stores[first].report('case-source'), report)

    def test_report_handoff_freezes_reviewed_report_and_legacy_target(self):
        from dataclasses import asdict, replace
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.ai_diagnostics import DiagnosticTarget, ProviderProfile
        from src.services.ai_case_store import open_shared_cases

        first = self.command('create', self.root / 'handoff-a', '报告接手 A').project_id
        second = self.command('create', self.root / 'handoff-b', '报告接手 B').project_id
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-handoff'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'handoff-case-fixture')), \
                patch('src.services.ai_conversation_service.AiConversationService.send', side_effect=AssertionError('handoff must not send')) as send, \
                patch('src.services.ai_diagnostic_service.AiDiagnosticService.submit', side_effect=AssertionError('handoff must not collect')) as collect:
            work = self.adapter._service
            work.models.save_profile(ProviderProfile(model='handoff-fixture'), 'synthetic-fixture-key')
            for identifier in (first, second):
                self.command('ai_chat_open', identifier)
            stores = self.adapter._model_settings.stores
            store = stores[first]
            channel = ChannelConfig('channel_7', vlan_name='vlan107', network_card_ip='192.0.2.100', device_manage_ip='192.0.2.1')
            config = ChannelConfigStore(work.projects.opened[first].config_dir / 'network_card_ip.ini')
            config.save([channel, ChannelConfig('channel_8', vlan_name='vlan108')])
            original = DiagnosticTarget(7, 'vlan142', 'COM42', '192.0.2.101', '192.0.2.2')
            store.save_report('snap', dict(report='原目标结论', target=asdict(original), channel=7, run_id='original-run'))
            detail = self.command('ai_report_select', first, 'snap').payload
            self.command('ai_report_handoff', second, detail.identifier, detail.revision, expected_error=True)
            view = self.command('ai_report_handoff', first, detail.identifier, detail.revision).payload
            session = store.chat(view.selected)
            self.assertEqual(session['target'], asdict(original))
            self.assertEqual(session['run_id'], 'original-run')
            self.assertTrue(view.writable and view.history_analysis)
            self.assertIn('原目标结论', store.chat_evidence(view.selected)[0]['text'])

            store.save_report('legacy', dict(report='旧报告原文', channel=7))
            detail = self.command('ai_report_select', first, 'legacy').payload
            args = (first, detail.identifier, detail.revision)
            preview = self.command('ai_report_handoff', *args).payload
            self.assertIn('COM7', preview.target)
            self.command('ai_report_handoff_finish', second, preview.token, True, expected_error=True)
            self.assertIsNone(self.command('ai_report_handoff_finish', first, preview.token, False).payload)
            self.command('ai_report_handoff_finish', first, preview.token, True, expected_error=True)
            preview = self.command('ai_report_handoff', *args).payload
            config.save([replace(channel, device_manage_ip='192.0.2.9')])
            self.command('ai_report_handoff_finish', first, preview.token, True, expected_error=True)
            config.save([channel])
            preview = self.command('ai_report_handoff', *args).payload
            store.save_report('legacy', dict(report='确认期间改写', channel=7))
            self.command('ai_report_handoff_finish', first, preview.token, True, expected_error=True)
            self.command('ai_report_handoff', *args, expected_error=True)
            detail = self.command('ai_report_select', first, 'legacy').payload
            preview = self.command('ai_report_handoff', first, detail.identifier, detail.revision).payload
            view = self.command('ai_report_handoff_finish', first, preview.token, True).payload
            legacy = store.chat(view.selected)
            self.assertEqual(legacy['run_id'], 'historical:legacy')
            self.assertEqual((legacy['source_report_id'], legacy['target']['host']), ('legacy', channel.device_manage_ip))
            self.assertEqual(len(store.chats()), 2)
            self.assertEqual(stores[second].chats(), [])
            self.assertFalse(self.adapter._ai_chats[first].conversation.permissions.grants)
            config.save([replace(channel, enabled=False)])
            self.command('ai_report_handoff', first, detail.identifier, detail.revision, expected_error=True)
            send.assert_not_called()
            collect.assert_not_called()

    def test_qt_active_diagnostics_and_serial_batch_use_confirmed_project_targets(self):
        from contextlib import ExitStack
        from dataclasses import replace
        from functools import partial
        from qt_execution_fakes import continue_chat_intent
        from qt_serial_fakes import SerialHarness
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        observations, queries, probes, monitor_calls = [], [], [], []
        pause_probe = threading.Event()
        blocked = threading.Event()
        failed_channels = set()
        class Client(DiagnosticModelClient):
            def complete(self, history, tools, stop):
                instructions = history[0]['content']
                if '只分解多样机任务' in instructions:
                    stage = dict(scope='device', select='all', instruction='读取系统状态', read_only=True, probe='none')
                    return ModelReply(json.dumps({'stages': [stage]}), [], history)
                if '只汇总本次多样机任务结果' in instructions:
                    return ModelReply('模拟跨通道汇总', [], history)
                if '自动监控' not in instructions:
                    return continue_chat_intent(self, history, tools, stop)
                monitor_calls.append({tool['name'] for tool in tools})
                calls = [] if len(monitor_calls) > 1 else [
                    dict(id='monitor-state', name='read_dut_state', arguments={'category': 'system'})]
                return ModelReply('模拟监控报告', calls, history)

            def complete_stream(self, history, tools, stop, on_text=None):
                observations.append({tool['name'] for tool in tools})
                calls = [] if getattr(self, 'queried', False) else [
                    dict(id='read-state', name='read_dut_state', arguments={'category': 'system'})]
                self.queried = True
                return ModelReply('模拟完成' if not calls else '', calls, history)

        def ping(target, settings, path, stop, emit, busy):
            self.assertFalse(stop.is_set() or busy(target))
            probes.append((target.channel, path))
            if pause_probe.is_set():
                blocked.set()
                if not stop.wait(5):
                    raise AssertionError('模拟探测未收到停止')
                raise InterruptedError('模拟探测已停止')
            return {'result': {'ok': target.channel not in failed_channels}}

        with ExitStack() as stack:
            stack.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'))
            stack.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')))
            stack.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
                side_effect=partial(AiDiagnosticService, client_factory=Client)))
            physical = stack.enter_context(patch('serial.Serial', side_effect=AssertionError('physical COM')))
            external = stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('external connection')))
            harness = SerialHarness().start()
            stack.callback(harness.stop)
            project = self.command('create', self.root / 'diagnostics', '诊断专项').project_id
            service = self.adapter._service
            ctx = service.projects.opened[project]
            config = ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini')
            rows = [ChannelConfig('channel_' + str(n), enabled=True, serial_port='COM79' + str(n),
                        vlan_name='vlan10' + str(n), network_card_ip='192.0.2.' + str(n),
                        device_manage_ip='192.0.2.1') for n in (7, 9)]
            config.save(rows)
            profile = service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            service.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.command('ai_chat_open', project)
            origin = self.command('ai_chat_new', project).payload.selected
            chat = self.adapter._ai_chats[project]
            policy = ((7, 9), ('ping',), 3, 60, (), (), True, 'ask')
            view = self.command('ai_chat_monitor_settings', project).payload
            config.save(rows[:1])
            self.command('ai_chat_monitor_apply', project, view['token'], *policy, expected_error=True)
            self.assertFalse(chat.diagnostic.trigger.enabled)
            config.save(rows)
            view = self.command('ai_chat_monitor_settings', project).payload
            self.command('ai_chat_monitor_apply', project, view['token'], *policy)
            self.assertTrue(chat.diagnostic.trigger.enabled)
            from src.models.capabilities import CapabilityAuthority, CapabilityError
            remote = CapabilityAuthority('model', 'session', 'test', (7, 9), source='local', approved=True)
            with self.assertRaises(CapabilityError) as denied:
                chat.access.execution.capabilities.execute('diagnostics.qt.configure',
                    dict(token=view['token'], channel_ids=[7, 9], features=['ping'], threshold=3,
                         cooldown=60, keywords=[], codes=[], monitor=True, permission='ask'), remote)
            self.assertEqual(denied.exception.code, 'source_forbidden')
            self.assertEqual(chat.diagnostic.trigger.policy.channels, (7, 9))
            self.assertNotIn('run_dut_command', {tool['name'] for tool in chat.diagnostic.monitor.tools()})

            target = chat.handoff._target(7)
            session, release, stop = chat.access.acquire_serial(target, threading.Event())
            try:
                self.assertTrue(chat.access.execution.manager.control_owner(target.port))
                self.assertFalse(stop.is_set())
            finally:
                release()
            self.assertFalse(chat.access.execution.manager.control_owner(target.port))
            from src.core.ai_debug_transport import DiagnosticTransport
            from test_ai_debug import Session
            from qt_execution_fakes import install_native_fixture_locks
            install_native_fixture_locks(self)
            initialize = DiagnosticTransport.__init__
            def initialize_transport(transport, target, *args, **kwargs):
                class SyntheticDevice(Session):
                    def send_line(self, command, sensitive=False):
                        queries.append((target.channel, command))
                        super().send_line(command, sensitive)
                def connect_device(**connection):
                    self.assertEqual((connection['bind_ip'], connection['device_host']), (target.bind_ip, target.host))
                    return SyntheticDevice()
                initialize(transport, target, *args, telnet_factory=connect_device, **kwargs)
            stack.enter_context(patch.object(DiagnosticTransport, '__init__', initialize_transport))
            selected = self.command('ai_chat_send', project, origin, '切换到通道7').payload.selected
            self.command('ai_chat_send', project, selected, '读取设备系统状态')
            self.wait_for(lambda: len(queries) == 1 and not chat.conversation.running)
            self.assertEqual(queries[0][0], 7)
            self.assertIn('uname', queries[0][1])
            self.assertIn('read_dut_state', observations[0])
            self.assertNotIn('run_dut_command', observations[0])

            stack.enter_context(patch('src.services.qt_device_diagnostics.probe_connectivity', ping))
            self.command('ai_chat_send', project, selected, '通道7、9 Ping')
            self.wait_for(lambda: chat._intent is None and chat.selected != selected and not chat.conversation.running)
            parent = chat.store.chat(chat.selected)
            self.assertEqual(probes, [(7, 'wired'), (9, 'wired')], [r.message for r in self.logs[-20:]])
            self.assertEqual([r['status'] for r in parent['batch']['rows']], ['reachable', 'reachable'])
            self.assertTrue(self.command('ai_chat_open', project).payload.writable)
            pause_probe.set()
            self.command('ai_chat_send', project, parent['id'], '通道7、9 Ping')
            self.assertTrue(blocked.wait(5))
            self.command('ai_chat_stop', project, parent['id'])
            self.wait_for(lambda: not chat.conversation.running)
            stopped = chat.store.chat(parent['id'])['batch']['rows']
            self.assertEqual([r['status'] for r in stopped], ['stopped', 'stopped'])
            self.assertEqual(probes[2:], [(7, 'wired')])
            pause_probe.clear()
            self.command('ai_chat_send', project, parent['id'], '继续剩余')
            self.wait_for(lambda: len(probes) == 5 and not chat.conversation.running)
            self.assertEqual(probes[3:], [(7, 'wired'), (9, 'wired')])
            stack.enter_context(patch('src.services.ai_debug_service.DiagnosticToolExecutor.pc_environment',
                                      return_value='synthetic PC'))
            failed_channels.add(9)
            self.command('ai_chat_send', project, parent['id'], '通道7、9 Ping')
            self.wait_for(lambda: len(probes) == 7 and not chat.conversation.running)
            self.assertEqual([r['status'] for r in chat.store.chat(parent['id'])['batch']['rows']], ['reachable', 'unreachable'])
            failed_channels.clear()
            self.command('ai_chat_send', project, parent['id'], '重查失败通道')
            self.wait_for(lambda: len(probes) == 8 and not chat.conversation.running)
            self.assertEqual(probes[-1], (9, 'wired'))
            self.command('ai_chat_send', project, parent['id'], '通道7、9 逐台读取设备系统状态')
            self.wait_for(lambda: len(queries) == 3 and not chat.conversation.running)
            inspected = chat.store.chat(parent['id'])['batch']['rows']
            self.assertEqual([(r['channel'], r['status']) for r in inspected], [(7, 'completed'), (9, 'completed')])
            for row in inspected:
                self.assertEqual(row['observations'][0]['tool'], 'read_dut_state')
            event = chat.access.execution.observe_ai_event
            event(dict(type='diagnostic_start', run_id='fixture-run'))
            self.wait_for(lambda: chat.diagnostic.run_active)
            from src.models.serial_models import SerialEvent
            observe_serial = chat.access.execution.terminal.diagnostic_receiver
            observe_serial('vlan109', SerialEvent('COM799', 'RX', b'', 'fixture-monitor-serial\n'))
            observe_serial('vlan107', SerialEvent('COM799', 'RX', b'', 'fixture-other-channel\n'))
            self.assertIn('fixture-monitor-serial', chat.diagnostic.trigger.context(9))
            self.assertNotIn('fixture-other-channel', chat.diagnostic.trigger.context(7))
            event(dict(type='diagnostic_event', run_id='fixture-run', channel=9, stage='ping',
                       status='failed', detail='synthetic failure', feature='ping'))
            self.wait_for(lambda: chat.diagnostic.monitor_status().waiting_approval == 1)
            action = self.command('ai_chat_monitor_review', project).payload
            self.assertEqual(action['target']['channel'], 9)
            self.command('ai_chat_monitor_decide', project, action['id'], 'obsolete', True, expected_error=True)
            self.command('ai_chat_monitor_decide', project, action['id'], action['fingerprint'], True)
            self.wait_for(lambda: any(row[2]['status'] == '完成' for row in chat.store.reports()))
            self.assertEqual([n for n, _ in queries], [7, 7, 9, 9])
            self.assertNotIn('run_dut_command', monitor_calls[0])
            self.command('ai_chat_monitor_off', project)
            self.assertFalse(chat.conversation.collection_status(parent['id'])['enabled'])
            self.assertIsNone(chat.access.execution.terminal.diagnostic_receiver)
            with self.assertRaises(ValueError):
                chat.access.acquire_serial(target, threading.Event())
            physical.assert_not_called()
            external.assert_not_called()

    def test_local_channel_passive_serial_rechecks_binding_and_never_writes(self):
        from contextlib import ExitStack
        from dataclasses import replace
        from functools import partial
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from qt_serial_fakes import SerialHarness
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.models.serial_models import SerialSettings
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        calls = []
        requested = threading.Event()
        proceed = threading.Event()
        pending = {}
        marker = 'fixture-RX-selected-port'
        other_marker = 'fixture-RX-unrelated-port'

        class Client(DiagnosticModelClient):
            from qt_execution_fakes import continue_chat_intent as complete

            def complete_stream(self, history, tools, stop, on_text=None):
                calls.append({tool['name'] for tool in tools})
                if pending:
                    call = pending.copy()
                    pending.clear()
                    requested.set()
                    if not proceed.wait(5):
                        raise AssertionError('模拟模型等待目标核对超时')
                    return ModelReply('', [call], history)
                return ModelReply('模拟回复', [], history + [dict(role='assistant', content='模拟回复')])

        with ExitStack() as guards:
            guards.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'))
            guards.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')))
            guards.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
                side_effect=partial(AiDiagnosticService, client_factory=Client)))
            physical = guards.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial')))
            connect = guards.enter_context(patch('socket.socket.connect', side_effect=AssertionError('external request')))
            harness = SerialHarness().start()
            guards.callback(harness.stop)
            project = self.command('create', self.root / 'serial-chat', '模拟串口会话').project_id
            service = self.adapter._service
            ctx = service.projects.opened[project]
            config = ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini')
            channel = ChannelConfig('channel_7', enabled=True, serial_port='COM7963', vlan_name='VLAN107',
                                    network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')
            config.save([channel])
            profile = service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            service.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.command('serial_show', project)
            manager = self.adapter._execution(ctx).manager
            for port, text in [(channel.serial_port, marker), ('COM7964', other_marker)]:
                session = manager.acquire_monitor('fixture', SerialSettings(port))
                guards.callback(manager.release, 'fixture', port, wait=True)
                harness.drivers[port].input.put(text.encode('ascii'))
                self.wait_for(lambda: session.cursor() == len(text))
            self.command('ai_chat_open', project)
            general = self.command('ai_chat_new', project).payload.selected
            selected = self.command('ai_chat_send', project, general, '切换到通道7').payload.selected
            chat = self.adapter._ai_chats[project]
            read = guards.enter_context(patch.object(chat.diagnostic, 'serial_read', wraps=chat.diagnostic.serial_read))
            for index, failure in enumerate(('', 'parameters', 'target_change', 'forged_tool')):
                with self.subTest(failure=failure):
                    config.save([channel])
                    requested.clear()
                    proceed.clear()
                    before = len(calls)
                    identifier = 'fixture-' + str(index)
                    params = {'port': 'COM7964'} if failure == 'parameters' else {}
                    name = 'run_dut_command' if failure == 'forged_tool' else 'read_serial_log'
                    pending.update(id=identifier, name=name, arguments=params)
                    self.command('ai_chat_send', project, selected, '只读当前通道已有的串口输出')
                    try:
                        self.assertTrue(requested.wait(4))
                        self.assertEqual(calls[before], {'ask_user', 'read_test_evidence', 'read_serial_log'})
                        if failure == 'target_change':
                            config.save([replace(channel, serial_port='COM7964')])
                    finally:
                        proceed.set()
                    self.wait_for(lambda: not chat._is_running())
                    evidence = next(row for row in chat.store.chat_evidence(selected) if row['source'].endswith('/' + identifier))
                    self.assertNotIn(other_marker, evidence['text'])
                    if failure:
                        self.assertNotIn(marker, evidence['text'])
                        self.assertIn('error', evidence['text'])
                    else:
                        self.assertIn(marker, evidence['text'])
                    self.assertEqual(read.call_count, 1)
            self.assertFalse(any(driver.writes for driver in harness.drivers.values()))
            physical.assert_not_called()
            connect.assert_not_called()

    def test_local_natural_target_routing_cancels_late_results_and_rechecks_project(self):
        import json
        import threading
        from contextlib import ExitStack
        from dataclasses import replace
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_session_router import ROUTE_INSTRUCTIONS

        entered, release = threading.Event(), threading.Event()
        decision = dict(intent='switch', scope='device', channel=7, question='', clarification='')
        messages = []

        class Client(DiagnosticModelClient):
            def complete(self, history, tools, stop):
                assert history[0]['content'] == ROUTE_INSTRUCTIONS and not tools
                request = json.loads(history[1]['content'])
                assert [target['channel'] for target in request['targets']] == [7]
                messages.append(request['message'])
                entered.set()
                assert release.wait(6), 'fixture intent was not released'
                return ModelReply(json.dumps(decision), [], history)

            def complete_stream(self, *args, **kwargs):
                raise AssertionError('仅识别目标，不应发送诊断问题')

        with ExitStack() as guards:
            guards.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'))
            guards.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')))
            physical = guards.enter_context(patch('serial.Serial', side_effect=AssertionError('真实串口')))
            network = guards.enter_context(patch('socket.socket.connect', side_effect=AssertionError('外部连接')))
            project = self.command('create', self.root / 'natural', '模拟自然语言选择').project_id
            config = ChannelConfigStore(self.adapter._service.projects.opened[project].config_dir / 'network_card_ip.ini')
            channel = ChannelConfig('channel_7', enabled=True, vlan_name='VLAN107', serial_port='COM7963',
                                    network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')
            config.save([channel])
            self.adapter._service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            self.command('ai_chat_open', project)
            origin = self.command('ai_chat_new', project).payload.selected
            chat = self.adapter._ai_chats[project]
            guards.enter_context(patch.object(chat.diagnostic, 'client_factory', Client))
            submit = guards.enter_context(patch.object(chat.conversation, 'send', side_effect=AssertionError('纯切换不能执行')))
            guards.callback(release.set)
            question = '请把排查对象换到七号测试位'

            def begin():
                entered.clear()
                release.clear()
                view = self.command('ai_chat_send', project, origin, question).payload
                self.assertTrue(entered.wait(2) and view.routing and view.running)
                self.assertEqual(view.messages[-1].text, question)

            def finish():
                release.set()
                self.wait_for(lambda: chat._intent is None)

            begin()
            with self.assertRaises(RuntimeError):
                self.adapter._service.maintenance.begin()
            self.command('refresh')
            self.command('ai_chat_stop', project, origin)
            finish()
            self.assertEqual(chat.selected, origin)
            self.assertEqual(len(chat.store.chats()), 1)

            begin()
            config.save([replace(channel, serial_port='COM7964')])
            finish()
            self.assertEqual(len(chat.store.chats()), 1)
            self.assertIn('已变化', self.command('ai_chat_open', project).payload.messages[-1].text)
            self.assertFalse(any(row['role'] == 'user' for row in chat.store.chat_items(origin)))

            begin()
            new = self.command('ai_chat_new', project).payload.selected
            finish()
            self.assertEqual(chat.selected, new)
            self.assertEqual(len(chat.store.chats()), 2)
            self.command('ai_chat_select', project, origin)

            begin()
            finish()
            selected = chat.selected
            self.assertEqual(chat.store.chat(selected)['target']['port'], 'COM7964')
            self.command('ai_chat_select', project, origin)
            begin()
            finish()
            self.assertEqual(chat.selected, selected)
            self.assertEqual(len(chat.store.chats()), 3)
            self.assertEqual(messages, [question] * 5)
            physical.assert_not_called()
            network.assert_not_called()
            submit.assert_not_called()

            self.command('ai_chat_select', project, origin)
            decision.update(scope='batch', channel=None, channels=[7], workflow='business')
            begin()
            finish()
            self.assertIn('尚未接入', self.command('ai_chat_open', project).payload.messages[-1].text)
            self.assertEqual(chat.selected, origin)
            self.assertEqual(len(chat.store.chats()), 3)
            submit.assert_not_called()

            decision.clear()
            decision.update(scope='device', channel=7, intent='switch', question='模型改写的操作', clarification='')
            submit.side_effect = None
            begin()
            finish()
            self.assertEqual(chat.selected, selected)
            self.assertEqual(submit.call_args.args, (selected, question))
            self.assertEqual(messages, [question] * 7)
            submit.reset_mock()
            decision.update(intent='continue', scope='device', channel=7, question='分析串口记录')
            config.save([replace(channel, serial_port='COM7965')])
            self.command('ai_chat_send', project, selected, '分析串口记录')
            self.wait_for(lambda: chat._intent is None)
            self.assertIn('目标已变化', self.command('ai_chat_open', project).payload.messages[-1].text)
            self.assertEqual(chat.selected, selected)
            self.assertEqual(len(chat.store.chats()), 3)
            submit.assert_not_called()

            self.command('ai_chat_select', project, origin)
            decision.update(intent='switch', scope='pc', channel=None, question='')
            begin()
            finish()
            ordinary_pc = self.command('ai_chat_open', project).payload
            self.assertTrue(ordinary_pc.writable and not ordinary_pc.pc_diagnosis)
            self.assertEqual(chat.store.chat(ordinary_pc.selected)['scope'], 'pc')
            self.assertFalse(chat.store.chat(ordinary_pc.selected).get('diagnosis_only'))
            continuous_pc = self.command('ai_chat_new_pc', project).payload
            self.assertTrue(continuous_pc.pc_diagnosis)
            self.assertNotEqual(ordinary_pc.selected, continuous_pc.selected)
            self.command('ai_chat_select', project, origin)
            begin()
            pending = chat._intent
            self.adapter.begin_close({project: 'discard'})
            self.assertTrue(pending.stop.wait(3))
            self.assertFalse(self.adapter.wait_closed(.05))
            self.assertEqual(chat.store.chat(origin)['id'], origin)
            release.set()
            self.assertTrue(self.adapter.wait_closed(5))
            self.assertEqual(self.adapter._service.maintenance.operations, 0)
            submit.assert_not_called()

    def test_explicit_local_channel_routes_from_send_and_preserves_report_and_project_scope(self):
        from contextlib import ExitStack
        from dataclasses import replace
        from functools import partial
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        replies = []

        class Client(DiagnosticModelClient):
            from qt_execution_fakes import continue_chat_intent as complete

            def complete_stream(self, history, tools, stop, on_text=None):
                replies.append(tuple(tool['name'] for tool in tools))
                return ModelReply('模拟通道回答', [], history + [dict(role='assistant', content='模拟通道回答')])

        with ExitStack() as guards:
            guards.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'))
            guards.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')))
            guards.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
                side_effect=partial(AiDiagnosticService, client_factory=Client)))
            serial_open = guards.enter_context(patch('src.core.serial_transport.PySerialSession.open',
                side_effect=AssertionError('不应访问串口')))
            connect = guards.enter_context(patch('socket.socket.connect', side_effect=AssertionError('不应连接网络')))
            project = self.command('create', self.root / 'channels', '模拟通道').project_id
            context = self.adapter._service.projects.opened[project]
            config = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
            channel = ChannelConfig('channel_7', enabled=True, vlan_name='VLAN107', serial_port='COM7963',
                                    network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')
            config.save([channel])
            models = self.adapter._service.models
            profile = models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            profile = models.save_profile(replace(profile, capability='可自动诊断',
                                                   tested_fingerprint=profile_fingerprint(profile)))
            self.command('ai_chat_open', project)
            general = self.command('ai_chat_new', project).payload.selected
            chat = self.adapter._ai_chats[project]
            target = chat.handoff._target(7)
            report = chat.conversation.create_session(target, profile, source_report_id='fixture-report')
            route = self.command('ai_chat_send', project, general, '切换到通道7').payload
            selected = route.selected
            self.assertNotIn(selected, (general, report))
            self.assertTrue(route.writable and route.passive_serial and not route.history_analysis)
            self.assertEqual(chat.store.chat(selected)['target']['port'], 'COM7963')
            self.assertFalse(chat.conversation.collection_status(selected)['enabled'])
            self.assertEqual(self.command('ai_chat_send', project, selected, '切回通道7').payload.selected, selected)
            self.assertEqual(replies, [])
            clarification = self.command('ai_chat_send', project, selected, '通道8 分析前次超时').payload
            self.assertEqual(clarification.selected, general)
            self.assertIn('有效目标通道：7', clarification.messages[-1].text)
            view = self.command('ai_chat_send', project, general, '通道7').payload
            self.assertEqual(view.selected, selected)
            self.wait_for(lambda: not chat._is_running())
            self.assertTrue(any('分析前次超时' in m['text'] for m in chat.store.chat_items(selected) if m['role'] == 'user'))
            self.assertFalse(chat.store.chat(general).get('routing_pending'))
            self.command('ai_chat_send', project, selected, '日志里出现了通道8')
            self.wait_for(lambda: not chat._is_running())
            self.assertEqual(chat.selected, selected)
            material_tools = ('ask_user', 'read_test_evidence')
            serial_tools = material_tools + ('read_serial_log',)
            self.assertEqual(replies, [serial_tools, serial_tools])
            self.command('ai_chat_select', project, report)
            self.command('ai_chat_send', project, report, '切换到通道7')
            self.wait_for(lambda: not chat._is_running())
            self.assertEqual(chat.selected, report)
            self.command('ai_chat_select', project, selected)
            config.save([replace(channel, serial_port='COM7964')])
            newer = self.command('ai_chat_send', project, selected, '切换到通道7').payload.selected
            self.assertNotEqual(selected, newer)
            self.assertEqual(chat.store.chat(newer)['target']['port'], 'COM7964')
            other = self.command('create', self.root / 'other', '另一项目').project_id
            self.command('ai_chat_open', other)
            other_general = self.command('ai_chat_new', other).payload.selected
            self.command('ai_chat_send', other, selected, '切换到通道7', expected_error=True)
            self.assertNotEqual(selected, other_general)
            self.assertEqual(replies, [serial_tools, serial_tools, material_tools])
            serial_open.assert_not_called()
            connect.assert_not_called()

    def test_old_local_device_session_accepts_retained_evidence_only(self):
        from dataclasses import replace
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import DiagnosticTarget, ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        calls = []

        class Client(DiagnosticModelClient):
            def complete_stream(self, history, tools, stop, on_text=None):
                calls.append((history, tuple(tool['name'] for tool in tools)))
                reply = '模拟模型已核对旧批次留存串口记录'
                return ModelReply(reply, [], history + [dict(role='assistant', content=reply)])

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'archived-models'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'archived-cases')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService',
                      side_effect=partial(AiDiagnosticService, client_factory=Client)):
            project = self.command('create', self.root / 'archived-chat', '旧设备对话').project_id
            models = self.adapter._service.models
            profile = models.save_profile(ProviderProfile(model='archived-fixture', context_tokens=65536), 'fixture-key')
            profile = models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.command('ai_chat_open', project)
            chat = self.adapter._ai_chats[project]
            conversation = chat.conversation
            context = conversation.context
            context.observe(dict(type='diagnostic_start', run_id='old-fixture-run'))
            current = conversation.create_session(DiagnosticTarget(3, 'vlan103', 'COM3', '192.0.2.10', '192.0.2.1'), profile)
            # Some pre-migration local records have no explicit source or scope.
            legacy = dict(chat.store.chat(current), id='archived-local')
            for key in ('scope', 'source', 'source_report_id'):
                legacy.pop(key, None)
            chat.store.create_chat(legacy)
            original_message = '会话已创建；默认允许主动采集。发送问题后按需采集。'
            conversation.message(legacy['id'], 'system', original_message)
            conversation.add_evidence(legacy['id'], '旧串口记录', '仅旧批次标记')
            context.observe(dict(type='diagnostic_start', run_id='new-fixture-run'))
            context.observe(dict(type='log', run_id=context.run_id, channel=3, message='新批次禁止带入'))
            with patch.object(context, 'snapshot', side_effect=AssertionError('live context not allowed')) as live, \
                    patch.object(conversation, '_collect', side_effect=AssertionError('no live collection')) as collect:
                view = self.command('ai_chat_select', project, legacy['id']).payload
                self.assertTrue(view.history_analysis and view.writable)
                self.assertNotIn(original_message, [m.text for m in view.messages])
                self.assertIn(original_message, [m['text'] for m in chat.store.chat_items(legacy['id'])])
                self.assertFalse(calls)
                self.command('ai_chat_send', project, legacy['id'], '请解释旧串口记录')
                self.wait_for(lambda: any(row['role'] == 'assistant' and '已核对旧批次' in row['text']
                                          for row in chat.store.chat_items(legacy['id'])))
                self.assertEqual(calls[0][1], ('ask_user', 'read_test_evidence'))
                self.assertIn('仅旧批次标记', str(calls[0][0]))
                self.assertNotIn('新批次禁止带入', str(calls[0][0]))
                self.assertNotIn('diagnosis_only', chat.store.chat(legacy['id']))
                self.wait_for(lambda: conversation.idle)
                chat.store.update_chat(legacy['id'], diagnosis_only=True)
                self.command('ai_chat_send', project, legacy['id'], '保留原会话诊断偏好')
                self.wait_for(lambda: len(calls) == 2 and conversation.idle)
                self.assertTrue(chat.store.chat(legacy['id'])['diagnosis_only'])
                self.assertEqual(set(calls[1][1]), {'ask_user', 'read_test_evidence', 'update_diagnostic_plan'})
                live.assert_not_called()
                collect.assert_not_called()
            for label, fields in [('current', dict(run_id=context.run_id)),
                                  ('missing-run', dict(run_id='')),
                                  ('blank-run', dict(run_id='  ')),
                                  ('remote', dict(source=dict(kind='feishu', sender='fixture')))]:
                entry = dict(legacy, id=label, **fields)
                chat.store.create_chat(entry)
                view = self.command('ai_chat_select', project, label).payload
                self.assertFalse(view.writable or view.history_analysis, label)
                self.command('ai_chat_send', project, label, '不应提交', expected_error=True)
            child = dict(legacy, id='archived-child', batch_parent='parent-fixture')
            chat.store.create_chat(child)
            self.command('ai_chat_select', project, child['id'], expected_error=True)
            self.assertEqual(len(calls), 2)

    def test_report_chat_analyzes_retained_evidence_without_live_collection(self):
        from dataclasses import asdict, replace
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import DiagnosticTarget, ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        requests = []

        class Client(DiagnosticModelClient):
            def complete_stream(self, history, tools, stop, on_text=None):
                requests.append((history, tuple(tool['name'] for tool in tools)))
                if len(requests) == 1:
                    calls = [dict(id='evidence', name='read_test_evidence', arguments='{"query":"留存主题标记"}'),
                             dict(id='device', name='read_dut_state', arguments='{}')]
                    message = dict(role='assistant', content=None, tool_calls=[dict(id=call['id'], type='function',
                        function=dict(name=call['name'], arguments=call['arguments'])) for call in calls])
                    return ModelReply('', calls, history + [message])
                reply = '基于留存材料的合成结论'
                return ModelReply(reply, [], history + [dict(role='assistant', content=reply)])

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-analysis'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'analysis-cases')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService', side_effect=partial(AiDiagnosticService, client_factory=Client)), \
                patch('src.services.ai_conversation_service.AiConversationService._collect', side_effect=AssertionError('live collection forbidden')) as collect:
            work = self.adapter._service
            project = self.command('create', self.root / 'report-analysis', '报告分析回归').project_id
            profile = work.models.save_profile(ProviderProfile(model='history-fixture', context_tokens=65536), 'synthetic-analysis-key')
            work.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.command('ai_chat_open', project)
            chat = self.adapter._ai_chats[project]
            store = chat.store
            target = DiagnosticTarget(3, 'vlan103', 'COM3', '192.0.2.10', '192.0.2.1')
            store.save_report('fixture', dict(report='留存主题标记：历史检查失败', channel=3, target=asdict(target), run_id='fixture-run'))
            store.save_report('unrelated', dict(report='不相关报告不可带入', channel=3))
            detail = self.command('ai_report_select', project, 'fixture').payload
            with patch.object(chat.conversation.context, 'snapshot', side_effect=AssertionError('retained report must not read live context')):
                view = self.command('ai_report_handoff', project, detail.identifier, detail.revision).payload
                self.assertTrue(view.history_analysis)
                self.assertTrue(view.writable)
                source = self.root / 'analysis-log.txt'
                source.write_text('人工补充材料', encoding='utf-8')
                self.command('ai_chat_import', project, view.selected, source)
                self.assertFalse(requests)
                self.command('ai_chat_send', project, view.selected, '请解释留存主题标记')
                self.wait_for(lambda: any(row['text'] == '基于留存材料的合成结论' for row in store.chat_items(view.selected)))
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0][1], ('ask_user', 'read_test_evidence'))
            self.assertIn('留存主题标记', str(requests[0][0]))
            self.assertNotIn('不相关报告不可带入', str(requests[1][0]))
            results = {row['tool_call_id']: row['content'] for row in requests[1][0] if row.get('role') == 'tool'}
            self.assertIn('留存主题标记', results['evidence'])
            self.assertIn('工具未开放', results['device'])
            collect.assert_not_called()
            self.assertFalse(chat.conversation.permissions.grants)

            remote = dict(store.chat(view.selected), id='platform-fixture', source={'kind': 'feishu', 'sender': 'fixture'})
            store.create_chat(remote)
            view = self.command('ai_chat_select', project, remote['id']).payload
            self.assertFalse(view.writable or view.history_analysis)
            self.command('ai_chat_send', project, remote['id'], '禁止跨来源发送', expected_error=True)
            self.assertEqual(len(requests), 2)

    def test_model_probe_uses_original_request_profile_and_discards_stale_capability(self):
        from src.services.ai_case_store import open_shared_cases

        first = self.command('create', self.root / 'profile-test-a', 'A').project_id
        second = self.command('create', self.root / 'profile-test-b', 'B').project_id
        entered, release, stopping = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        class Client:
            def __init__(self, profile, key, redactor, emit=None):
                self.profile = profile
                self.key = key

            def close(self):
                pass

            def model_details(self, stop):
                self.assert_model()
                return [{'id': 'model-fixture', 'context_tokens': 65536}]

            def test_connection(self, stop):
                self.assert_model()
                entered.set()
                deadline = time.monotonic() + 8
                while not release.wait(.02) and time.monotonic() < deadline:
                    if stop.is_set():
                        stopping.set()
                if not release.is_set():
                    raise AssertionError('test did not release fake client')
                return '支持工具调用', '模拟返回'

            def assert_model(self):
                if self.profile.source_ip != '192.0.2.12' or self.key != 'fixture-key':
                    raise AssertionError('original network settings did not reach the client')

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-ai'), \
                patch('src.services.ai_case_store.open_shared_cases',
                   side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'shared-case-fixture')), \
                patch('src.services.qt_model_settings.DiagnosticModelClient', Client):
            initial = self.command('ai_model_open', first).payload
            args = dict(name='原配置', provider='DeepSeek', base_url='https://models.example.invalid',
                        protocol='chat_completions', model='model-fixture', timeout='60', max_output='1024',
                        context_tokens='', source_ip='192.0.2.12')
            refresh = self.command('ai_model_refresh', first, initial.profile, True, args, 'fixture-key').payload
            self.assertEqual(refresh.model_ids, ('model-fixture',))
            self.assertEqual(refresh.context_tokens, 65536)
            request = self.adapter.submit('ai_model_test', first, refresh.profile, False, args, '')
            try:
                self.assertTrue(entered.wait(3))
                changed = self.command('ai_model_save', second, refresh.profile, False, dict(args, source_ip=''), '').payload
            finally:
                release.set()
            self.wait_for(lambda: (request, 'ai_model_test') in self.results)
            response = self.results[request, 'ai_model_test']
            self.assertIn('配置已变化', response.payload.notice)
            current = self.adapter._service.models.profiles()[0]
            self.assertEqual(current, changed.profile)
            self.assertEqual(current.capability, '未验证')
            restored = self.command('ai_model_save', first, current, False, args, '').payload
            entered.clear()
            release.clear()
            self.adapter.submit('ai_model_test', first, restored.profile, False, args, '')
            try:
                self.assertTrue(entered.wait(3))
                self.adapter.begin_close()
                self.assertTrue(stopping.wait(3))
                self.assertFalse(self.adapter.closed.is_set())
            finally:
                release.set()
            self.assertTrue(self.adapter.wait_closed(5))

    def test_health_uses_current_leases_and_actual_inventory_result(self):
        resources = self.adapter._service.resources
        self.wait_for(lambda: self.adapter.health_snapshot().resources is not None)
        initial = self.adapter.health_snapshot()
        self.assertEqual(initial.resources.serial, 0)
        with resources.lock:
            resources.aliases['ethernet-test'] = 'guid-test'
            resources.owners['synthetic-owner'] = ('p1', ('serial:com102', 'adapter:ethernet-test', 'adapter:guid-test', 'wifi:lab'))
            try:
                self.wait_for(lambda: self.adapter.health_snapshot().worker_tick > initial.worker_tick + 1)
                self.assertEqual(self.adapter.health_snapshot().resources, initial.resources)
            finally:
                resources.owners.pop('synthetic-owner')
        with resources.lock:
            with patch.dict(resources.owners, {'synthetic-owner': ('p1',
                    ('serial:com102', 'adapter:ethernet-test', 'adapter:guid-test', 'wifi:lab'))}), \
                    patch.dict(resources.labels, {'synthetic-owner': '模拟项目'}):
                self.adapter._sample_resources(time.monotonic())
                measured = self.adapter.health_snapshot().resources
                self.assertEqual((measured.serial, measured.adapters, measured.other), (1, 1, 1))
                _, leases = self.adapter.device_inventory_snapshot()
                self.assertEqual(dict(leases.owners), {key: ('模拟项目',) for key in
                    ('serial:com102', 'adapter:ethernet-test', 'adapter:guid-test')})
        readings = (HostInventoryReading(None, ()), HostInventoryReading((), ()))
        with patch('src.services.qt_workspace_adapter.read_host_inventory', side_effect=readings):
            self.command('refresh_inventory')
            self.assertFalse(self.adapter.health_snapshot().inventory_check[1])
            self.command('refresh_inventory')
            self.assertTrue(self.adapter.health_snapshot().inventory_check[1])

    def test_device_inventory_retains_last_success_per_source(self):
        from src.models.network_adapter import AdapterIdentity

        identity = AdapterIdentity('VLAN171', 'fixture-device-guid', 'Up')
        readings = (HostInventoryReading(('COM171',), (identity,)),
                    HostInventoryReading((), None),
                    HostInventoryReading(None, ()))
        with patch('src.services.qt_workspace_adapter.read_host_inventory', side_effect=readings):
            self.command('refresh_inventory')
            first, _ = self.adapter.device_inventory_snapshot()
            self.assertEqual((first.ports, first.adapters), (('COM171',), (identity,)))
            self.assertIsNotNone(first.adapters_at)
            self.assertFalse(first.ports_failed or first.adapters_failed)
            self.command('refresh_inventory')
            second, _ = self.adapter.device_inventory_snapshot()
            self.assertEqual((second.ports, second.adapters), ((), (identity,)))
            self.assertEqual(second.adapters_at, first.adapters_at)
            self.assertFalse(second.ports_failed)
            self.assertTrue(second.adapters_failed)
            self.command('refresh_inventory')
            third, _ = self.adapter.device_inventory_snapshot()
            self.assertEqual((third.ports, third.adapters), ((), ()))
            self.assertEqual(third.ports_at, second.ports_at)
            self.assertTrue(third.ports_failed)
            self.assertFalse(third.adapters_failed)

    def test_adapter_rename_rechecks_guid_and_protects_after_partial_project_write(self):
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.network_adapter import AdapterIdentity

        first = self.command('create', self.root / 'rename-from', '源项目').project_id
        other = self.command('create', self.root / 'rename-other', '另一个引用').project_id
        workspace = self.adapter._service
        contexts = workspace.projects.opened
        stores = [ChannelConfigStore(contexts[key].config_dir / 'network_card_ip.ini') for key in (first, other)]
        old, new, guid = 'Rename Fixture', 'VLAN137', 'qt-rename-guid-fixture'
        stores[0].save([ChannelConfig('channel_1', vlan_name='VLAN131', device_manage_ip='192.168.7.1')])
        stores[1].save([ChannelConfig('channel_2', vlan_name='VLAN141', adapter_alias=old,
                                     device_manage_ip='192.168.7.1', serial_port='COM41')])
        original = [store.config_path.read_bytes() for store in stores]
        draft = self.command('channels_editor_open', first).payload
        rename = self.adapter._adapter_rename.rename_service
        adapters = [AdapterIdentity(old, guid)]
        patches = dict(token=draft.token, revision=draft.revision, number=1, old_name=old, new_name=new)
        def simulated_rename(source, destination):
            self.assertEqual(source, old)
            adapters[:] = [AdapterIdentity(destination, guid)]
        with patch.object(rename, 'reader', side_effect=lambda: tuple(adapters)), \
                patch.object(rename, 'availability', return_value=''), \
                patch.object(rename, 'renamer', side_effect=simulated_rename) as dispatch:
            review = self.command('channels_editor_rename_preview', first, patches).payload
            self.assertIn('另一个引用 · channel_2', review['summary'])
            self.assertIn(guid, review['summary'])
            adapters[:] = [AdapterIdentity(old, 'replacement-guid')]
            confirmed = dict(token=draft.token, confirmation=review['confirmation'])
            result = self.command('channels_editor_rename_confirm', first, confirmed).payload
            self.assertEqual(result['state'], 'failed')
            dispatch.assert_not_called()
            self.assertEqual([store.config_path.read_bytes() for store in stores], original)
            adapters[:] = [AdapterIdentity(old, guid)]
            preview = self.command('channels_editor_rename_preview', first, patches).payload
            stores[1].config_path.write_bytes(original[1] + b'\n')
            confirmed['confirmation'] = preview['confirmation']
            changed = self.command('channels_editor_rename_confirm', first, confirmed, expected_error=True)
            self.assertIn('项目通道已变化', changed.error)
            dispatch.assert_not_called()
            stores[1].config_path.write_bytes(original[1])
            preview = self.command('channels_editor_rename_preview', first, patches).payload
            confirmed['confirmation'] = preview['confirmation']
            save = ChannelConfigStore.save
            def fail_other(store, channels, power):
                if store.config_path == stores[1].config_path:
                    raise PermissionError('synthetic failure')
                return save(store, channels, power)
            with patch.object(ChannelConfigStore, 'save', fail_other):
                result = self.command('channels_editor_rename_confirm', first, confirmed).payload
            dispatch.assert_called_once_with(old, new)
            self.assertEqual(result['state'], 'unknown')
            self.assertIn('另一个引用', result['message'])
            self.assertEqual(stores[1].config_path.read_bytes(), original[1])
            saved = stores[0].load()[0]
            self.assertEqual((saved.vlan_name, saved.serial_port, saved.network_card_ip),
                             (new, 'COM31', '192.168.7.137'))
            owner, label = workspace.resources.unknown_gui()[0]
            self.assertIn(new, label)
            self.assertTrue(owner.startswith('gui:' + first + ':'))
            self.assertEqual({key for key, in workspace.resources.fence.db.execute('SELECT resource FROM fence')},
                             {'adapter:' + guid, 'adapter:' + old.casefold(), 'adapter:' + new.casefold()})
            self.assertEqual(self.adapter.device_inventory_snapshot()[0].adapters[0].alias, new)
            self.command('channels_editor_rename_confirm', first, confirmed, expected_error=True)
            dispatch.assert_called_once()

    def test_original_project_lifecycle_preserves_values_and_identity(self):
        path = self.root / '工程A'
        identifier = self.command('create', path, '工程A').project_id
        manifest = path / 'project.linecheck.json'
        before = json.loads(manifest.read_text(encoding='utf-8'))
        config = path / 'draft/Auto_power_on_off_tool/config/test_project_config.ini'
        saved = config.read_bytes()
        self.command('save', identifier)
        after = json.loads(manifest.read_text(encoding='utf-8'))
        self.assertEqual(after['format_version'], 1)
        self.assertEqual(after['project_id'], identifier)
        self.assertNotEqual(before['revision'], after['revision'])
        self.assertEqual(config.read_bytes(), saved)
        self.command('rename', identifier, '工程A改')
        self.assertEqual(self.projects[0].name, '工程A改')
        duplicate = self.command('duplicate', identifier, self.root / '副本').project_id
        self.assertNotEqual(duplicate, identifier)
        self.assertEqual(len(self.projects), 2)
        self.command('close', identifier)
        self.command('open', manifest)
        self.assertEqual({p.project_id for p in self.projects}, {identifier, duplicate})
        self.assertTrue(any(e.project_id == identifier and 'save' in e.message for e in self.logs))

    def test_legacy_import_creates_original_backup_and_leaves_source_intact(self):
        import hashlib

        config = self.root / 'legacy' / 'Auto_power_on_off_tool' / 'config'
        config.mkdir(parents=True)
        settings = config / 'test_project_config.ini'
        original = b'[project_info]\nproject_name = Old project\n[telnet]\nrequest_url = http://192.0.2.200\n'
        settings.write_bytes(original)
        path = self.root / 'imported'
        with patch('serial.Serial', side_effect=AssertionError('legacy import cannot open serial')):
            identifier = self.command('import_legacy', config, path, 'Imported project').project_id
        self.assertTrue(identifier)
        self.assertEqual(settings.read_bytes(), original)
        self.assertEqual(self.projects[0].active_task_count, 0)
        self.assertFalse(matches_project_filter(self.projects[0], 'completed'))
        self.assertEqual(self.projects[0].saved_revision, self.adapter._service.projects.opened[identifier].identity.revision)
        self.assertEqual(self.projects[0].name, 'Imported project')
        self.assertEqual(json.loads((path / 'import_state.json').read_text(encoding='utf-8'))['state'], 'complete')
        backup, = (path / 'backups' / 'imports').iterdir()
        receipt = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['state'], 'complete')
        self.assertEqual(receipt['files'][0]['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual((backup / 'config' / settings.name).read_bytes(), original)
        self.command('close', identifier)
        self.assertEqual(self.command('open', path).project_id, identifier)

    def test_open_project_directory_rejects_closed_project_and_reports_shell_failure(self):
        folder = self.root / 'directory'
        identifier = self.command('create', folder, '目录项目').project_id
        with patch('os.startfile', side_effect=OSError('shell failure')) as explorer:
            result = self.command('open_project_directory', identifier, expected_error=True)
            self.assertIn('Windows 无法打开项目目录', result.error)
            self.assertEqual(result.project_id, identifier)
            explorer.assert_called_once_with(str(folder), 'explore')
            self.command('close', identifier)
            result = self.command('open_project_directory', identifier, expected_error=True)
            self.assertIn('项目未打开', result.error)
            self.assertEqual(explorer.call_count, 1)

    def test_recent_projects_persist_reorder_and_forget_keeps_open_project(self):
        first_path, second_path = self.root / '一号工程', self.root / '二号工程'
        first = self.command('create', first_path, '一号工程').project_id
        second = self.command('create', second_path, '二号工程').project_id
        renamed = self.command('rename', first, '改名后的工程')
        expected = (('改名后的工程', str(first_path)), ('二号工程', str(second_path)))
        self.assertEqual(renamed.payload, expected)
        manifest = first_path / 'project.linecheck.json'
        original_manifest = manifest.read_bytes()
        self.close_adapter()
        self.results.clear()
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.wait_for(lambda: (0, 'ready') in self.results)
        self.assertEqual(self.results[0, 'ready'].payload, (expected, ''))
        self.assertEqual([p.project_id for p in self.projects], [first, second])
        self.assertEqual(self.command('open', second_path).project_id, second)
        self.assertEqual(self.command('open', first_path).project_id, first)
        self.assertEqual(self.command('forget_recent', first).payload, expected[1:])
        self.assertEqual({p.project_id for p in self.projects}, {first, second})
        self.assertEqual(manifest.read_bytes(), original_manifest)
        recents = json.loads((self.root / 'workspace/recent_projects.json').read_text(encoding='utf-8'))
        self.assertEqual([item['project_id'] for item in recents], [second])

    def test_session_restores_only_open_projects_in_order_and_remembers_empty_dashboard(self):
        first, closed, last = [self.command('create', self.root / name, name).project_id for name in 'ABC']
        self.command('close', closed)
        self.command('forget_recent', first)
        with patch.object(QtWorkspaceAdapter, '_execution', side_effect=AssertionError('unexpected device execution')):
            self.assertEqual(self.restart_workspace(first), first)
            self.assertEqual([p.project_id for p in self.projects], [first, last])
            self.assertEqual(self.restart_workspace(), '')
            self.assertEqual([p.project_id for p in self.projects], [first, last])
        self.command('close', first)
        self.command('close', last)
        self.assertEqual(self.restart_workspace(), '')
        self.assertFalse(self.projects)
        self.assertTrue(self.results[0, 'ready'].payload[0])

    def test_session_skips_missing_locked_and_replaced_projects_and_restores_the_next(self):
        from src.core.host_resource_lock import HostResourceLock
        paths = [self.root / name for name in ('missing', 'locked', 'replaced', 'valid')]
        missing, locked, replaced, valid = [self.command('create', path, path.name).project_id for path in paths]
        self.adapter.begin_close(selected_project=missing)
        self.assertTrue(self.adapter.wait_closed(5))
        paths[0].rename(self.root / 'moved')
        manifest = paths[2] / 'project.linecheck.json'
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['project_id'] = missing
        manifest.write_text(json.dumps(value), encoding='utf-8')
        with HostResourceLock(['project:' + locked], reentrant=False):
            self.results.clear()
            self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
            self.wait_for(lambda: (0, 'ready') in self.results)
        self.assertEqual([p.project_id for p in self.projects], [valid])
        self.assertEqual(self.results[0, 'ready'].project_id, '')
        for path in paths[:3]:
            self.assertTrue(any(str(path) in row.message and row.level == 'WARN' for row in self.logs))
        self.assertEqual(set(self.adapter._service.projects.leases), {valid})

    def test_unreadable_session_keeps_workspace_available_for_manual_open(self):
        path = self.root / 'manual'
        project = self.command('create', path, '手动').project_id
        self.close_adapter()
        session = self.root / 'workspace/workspace_session.json'
        session.write_bytes(b'{invalid')
        self.results.clear()
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.wait_for(lambda: (0, 'ready') in self.results)
        self.assertFalse(self.projects)
        self.assertEqual(session.read_bytes(), b'{invalid')
        self.assertTrue(any('会话无法读取' in row.message for row in self.logs))
        self.assertEqual(self.command('open', path).project_id, project)

    def test_session_write_failure_keeps_last_clean_exit_and_releases_projects(self):
        first = self.command('create', self.root / 'first', '上次项目').project_id
        self.assertEqual(self.restart_workspace(first), first)
        path = self.root / 'workspace/workspace_session.json'
        previous = path.read_bytes()
        self.command('create', self.root / 'next', '本次项目')
        with patch('src.services.workspace_service.atomic_json', side_effect=PermissionError):
            self.close_adapter()
        self.drain()
        self.assertFalse(self.adapter._service.projects.leases)
        self.assertEqual(path.read_bytes(), previous)
        self.assertTrue(any(row.level == 'WARN' and '会话保存失败' in row.message for row in self.logs))

    def test_corrupt_recents_warn_without_rewriting_at_startup(self):
        self.close_adapter()
        path = self.root / 'workspace/recent_projects.json'
        original = b'{bad fixture'
        path.write_bytes(original)
        self.results.clear()
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.wait_for(lambda: (0, 'ready') in self.results)
        projects, warning = self.results[0, 'ready'].payload
        self.assertFalse(projects)
        self.assertIn('最近项目列表无法读取', warning)
        self.assertTrue(any(entry.message == warning for entry in self.logs))
        self.assertEqual(path.read_bytes(), original)

    def _history_project(self, name, event_count=1):
        from src.services.capability_jobs import CapabilityJobs

        project = self.command('create', self.root / name, name).project_id
        context = self.adapter._service.projects.opened[project]
        jobs = CapabilityJobs(context.history / 'ai/business', self.adapter._service.resources)
        try:
            with jobs.db:
                jobs.db.execute('INSERT INTO jobs(id,capability,state,created) VALUES(?,?,?,?)',
                                ('shared-job', 'aging.start', 'succeeded', 1))
                message = json.dumps(dict(channel=7, origin=name))
                jobs.db.executemany('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                                    [('shared-job', 1, 'aging', message)] * event_count)
        finally:
            jobs.close()
        return project

    def test_slow_sql_history_keeps_project_commands_available_and_read_results_in_order(self):
        from src.models.qt_log_history import HistoryEventFilter, job_event_channel

        first = self._history_project('history-A')
        second = self._history_project('history-B')
        started, release = threading.Event(), threading.Event()
        read_order = []

        def observe_query(stage, message):
            origin = json.loads(message)['origin']
            read_order.append(origin)
            if origin == 'history-A':
                started.set()
                if not release.wait(12):
                    raise AssertionError('test did not release the first SQL query')
            return job_event_channel(stage, message)

        with patch('src.services.qt_log_history.job_event_channel', side_effect=observe_query):
            try:
                options = (None, 'shared-job', HistoryEventFilter(channel=7))
                a = self.adapter.submit('history_events', first, *options)
                self.assertTrue(started.wait(3))
                b = self.adapter.submit('history_events', second, *options)
                saved = self.command('save', second)
                self.assertEqual(saved.project_id, second)
                self.assertEqual(read_order, ['history-A'])
                self.assertNotIn((a, 'history_events'), self.results)
                self.assertNotIn((b, 'history_events'), self.results)
            finally:
                release.set()
            self.wait_for(lambda: (a, 'history_events') in self.results and (b, 'history_events') in self.results)
        self.assertEqual(read_order, ['history-A', 'history-B'])
        for request, project, origin in ((a, first, 'history-A'), (b, second, 'history-B')):
            result = self.results[request, 'history_events']
            self.assertFalse(result.error, result.error)
            self.assertEqual(result.project_id, project)
            entry, = result.payload.entries
            self.assertEqual((entry.project_id, entry.run_id, entry.channel), (project, 'shared-job', 7))
            self.assertIn(origin, entry.message)

    def test_pairing_reuses_original_single_use_store_without_granting_runtime_access(self):
        import os
        from unittest.mock import Mock
        from test_ai_core import FakeCipher
        from test_remote_instance_management import SCOPES
        from src.services.remote_gateway_store import RemoteGatewayStore
        from src.services.remote_gateway_host import RemoteGatewayHost
        from src.services.remote_instance_management import RemoteInstanceManagement, read_startup
        folder = self.root / 'private-pairing'
        ledger = RemoteGatewayStore(folder, cipher=FakeCipher())
        self.addCleanup(ledger.close)
        simulated = Mock()
        simulated.pair.side_effect = ledger.pair
        host = RemoteGatewayHost(folder, cipher=FakeCipher())
        manager = RemoteInstanceManagement(self.root / 'program', host=host, cipher=FakeCipher(),
            connection_factory=lambda *a, **kw: simulated, emit=self.adapter._emit)
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root)), patch.object(self.adapter._service, 'management', return_value=manager):
            self.command('gateway_pairing_code', expected_error=True)
            manager.save_gateway(dict(host='127.0.0.1', port=18761, platforms=[]), SCOPES)
            code, deadline = self.command('gateway_pairing_code').payload
            self.assertTrue(0 < deadline - time.monotonic() <= 300)
            row = self.command('gateway_pairing_slot', None).payload
            self.assertEqual(row['slot'], read_startup(manager.app_dir)['slot'])
            self.assertFalse(row['paired'])
            options = ('ws://127.0.0.1:18761', '模拟实例', False, code)
            self.command('gateway_pair_instance', 1, 'stale-id', *options, expected_error=True)
            simulated.pair.assert_not_called()
            paired = self.command('gateway_pair_instance', 1, row['instance_id'], *options).payload
            self.assertEqual(paired['scopes'], SCOPES)
            self.assertTrue(paired['paired'])
            self.assertFalse(paired['enabled'])
            self.assertEqual((paired['channel_ids'], paired['capability_ids']), ([], []))
            self.assertNotIn('credential', paired)
            self.assertEqual(self.command('gateway_pairing_slot', 1).payload, paired)
            self.command('gateway_pair_instance', 1, row['instance_id'], *options, expected_error=True)
            self.assertEqual(simulated.pair.call_count, 1)
            other = self.command('gateway_pairing_slot', 2).payload
            self.command('gateway_pair_instance', 2, other['instance_id'], *options, expected_error=True)
            self.assertFalse(self.command('gateway_pairing_slot', 2).payload['paired'])
            self.assertEqual(read_startup(manager.app_dir)['mode'], 'direct')
            self.assertNotIn(code, repr(self.logs))
            self.assertEqual(simulated.close.call_count, 2)

            # Configure via the Qt project's actual registry and exercise the
            # original encrypted pending-to-active handover without a client.
            from src.services.remote_gateway_runtime import RemoteGatewayRuntime
            project = self.command('create', self.root / 'startup-project', '启动配置测试').project_id
            review = self.command('gateway_startup_read', project, 1).payload
            ids = dict(review['options'])
            self.assertIn('firmware.upgrade', ids)
            self.assertNotIn('serial.terminal.send', ids)
            save = (project, review, 'gateway', options[0], False, [2, 16])
            self.command('gateway_startup_save', *save, ['serial.terminal.send'], expected_error=True)
            self.assertFalse(manager.slot(1)['pending'])
            self.command('gateway_startup_save', *save, ['firmware.upgrade'])
            self.assertEqual(read_startup(manager.app_dir), dict(mode='gateway', slot=1))
            self.assertTrue(manager.slot(1)['pending'])
            self.command('gateway_startup_save', *save, ['firmware.upgrade'], expected_error=True)
            runtime = RemoteGatewayRuntime(manager.app_dir, 1, cipher=FakeCipher())
            try:
                self.assertEqual(runtime.config['channel_ids'], [2, 16])
                self.assertEqual(runtime.config['capability_ids'], ['firmware.upgrade'])
                self.assertIsNone(runtime.client)
            finally:
                runtime.close()
            current = self.command('gateway_startup_read', project, None).payload
            self.assertFalse(current['slot']['pending'])
            self.command('gateway_startup_save', project, current, 'direct', '', False, [], [])
            self.assertEqual(read_startup(manager.app_dir)['mode'], 'direct')
            self.assertEqual(simulated.pair.call_count, 2)  # Initial pairing and the earlier rejected replay only.

    def test_instance_direct_startup_recovers_corrupt_settings_and_an_occupied_slot(self):
        import os
        from src.services.ai_project_store import project_directory
        from src.services.remote_instance_identity import RemoteInstanceIdentity
        from src.services.remote_instance_management import read_startup
        service = self.adapter._service
        management = service.management()
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root)), patch.object(management, 'app_dir', self.root / 'program'):
            path = project_directory(management.app_dir) / 'instance_startup.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{broken', encoding='utf-8')
            occupied = RemoteInstanceIdentity(management.app_dir, slot=1)
            try:
                review = self.command('gateway_startup_read', '', None).payload
                self.assertIsNone(review['slot'])
                self.assertTrue(review['invalid_digest'] and review['slot_error'])
                path.write_text('{changed', encoding='utf-8')
                self.command('gateway_startup_save', '', review, 'direct', '', False, [], [], expected_error=True)
                refreshed = self.command('gateway_startup_read', '', None).payload
                self.command('gateway_startup_save', '', refreshed, 'direct', '', False, [], [])
                self.assertEqual(read_startup(management.app_dir), dict(mode='direct', slot=1))
            finally:
                occupied.close()
            with patch.object(service, 'gateway_slot', 3):
                state = self.command('instance_status').payload
                self.assertEqual((state['current_mode'], state['current_slot'], state['connected']),
                                 ('gateway_pending', 3, False))

    def test_project_close_waits_for_review_of_its_registered_capabilities(self):
        import os
        project = self.command('create', self.root / 'startup-close', '收尾测试').project_id
        entered, release = threading.Event(), threading.Event()
        manager = self.adapter._service.management()
        slot = manager.slot
        def read(number):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('fixture read not released')
            return slot(number)
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root)), patch.object(manager, 'slot', side_effect=read):
            request = self.adapter.submit('gateway_startup_read', project, 1)
            try:
                self.assertTrue(entered.wait(3))
                close = self.adapter.submit('close', project, 'discard')
                self.command('refresh')
                self.assertIn(project, self.adapter._service.projects.opened)
                self.assertNotIn((close, 'close'), self.results)
            finally:
                release.set()
            self.wait_for(lambda: (close, 'close') in self.results)
            self.assertFalse(self.results[request, 'gateway_startup_read'].error)
            self.assertFalse(self.results[close, 'close'].error)
            self.assertNotIn(project, self.adapter._service.projects.opened)

    def test_gateway_operations_wait_for_original_service_without_blocking_workspace(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        management = self.adapter._service.management()
        def start():
            entered.set()
            release.wait(6)
        with patch.object(management, 'start_gateway', side_effect=start) as start_gateway, \
                patch.object(management, 'stop_gateway') as stop_gateway:
            request = self.adapter.submit('gateway_start')
            self.assertTrue(entered.wait(3))
            try:
                self.command('gateway_stop', expected_error=True)
                self.command('refresh')
                self.assertNotIn((request, 'gateway_start'), self.results)
            finally:
                release.set()
            self.wait_for(lambda: (request, 'gateway_start') in self.results)
            self.assertFalse(self.results[request, 'gateway_start'].error)
            self.command('gateway_stop')
            start_gateway.assert_called_once_with()
            stop_gateway.assert_called_once_with()
        original = dict(host='127.0.0.1', port=18761, scopes=[], platforms=[], platform_config_dir='fixture')
        with patch.object(management, 'gateway_config', return_value=original) as read, \
                patch.object(management, 'save_gateway') as save:
            settings = self.command('gateway_read_config').payload
            self.command('gateway_save_config', settings, {'port': 18763}, [])
            save.assert_called_once_with(dict(original, port=18763), [])
            read.return_value = dict(original, port=18764)
            self.command('gateway_save_config', settings, {'port': 18765}, [], expected_error=True)
            self.assertEqual(save.call_count, 1)

    def test_slow_gateway_does_not_delay_power_stop_during_workspace_exit(self):
        from qt_execution_fakes import ControlledPipeline, configure_project
        project = self.command('create', self.root / 'gateway-and-power', '模拟挂测').project_id
        workspace = self.adapter._service
        resources = configure_project(workspace, workspace.projects.opened[project], (14,))
        engine = ControlledPipeline()
        entered, release = threading.Event(), threading.Event()
        def slow_gateway():
            entered.set()
            release.wait(8)
        with patch.object(workspace.management(), 'start_gateway', side_effect=slow_gateway), \
                patch('src.core.network_adapter.read_adapter_identities', return_value=resources), \
                patch('src.services.capability_device_services.PipelineOrchestrator', engine.factory), \
                patch('serial.Serial', side_effect=AssertionError('physical serial forbidden')):
            try:
                request = self.command('prepare_execution', project, 'aging.start').payload
                self.command('confirm_execution', project, request.token)
                self.assertTrue(engine.started.wait(3))
                self.adapter.submit('gateway_start')
                self.assertTrue(entered.wait(3))
                self.adapter.begin_close({project: 'discard'})
                self.assertTrue(engine.stop_observed.wait(3))
                self.assertTrue(workspace.resources.owners)
                self.assertFalse(self.adapter.closed.is_set())
            finally:
                engine.release_stop.set()
                engine.finish.set()
                release.set()
            self.assertTrue(self.adapter.wait_closed(5))
            self.assertFalse(workspace.resources.owners)

    def test_close_workspace_interrupts_active_sql_scan_and_settles_each_read_once(self):
        from src.models.qt_log_history import HistoryEventFilter, job_event_channel
        from src.services.qt_log_history import read_log_history

        first = self._history_project('closing-A', event_count=1200)
        second = self._history_project('closing-B')
        entered, finished = threading.Event(), threading.Event()
        cancel_events, interrupted = [], []

        def track_read(context, *args, closing_event=None):
            cancel_events.append(closing_event)
            try:
                return read_log_history(context, *args, closing_event=closing_event)
            except ValueError as error:
                interrupted.append(str(error))
                raise
            finally:
                finished.set()

        def wait_inside_sql(stage, message):
            if not entered.is_set():
                entered.set()
                # Resume the real SQLite scan once shutdown signals cancellation.
                cancel = cancel_events[0]
                if cancel is None or not cancel.wait(6):
                    raise AssertionError('active history read did not receive cancellation')
            return job_event_channel(stage, message)

        with patch('src.services.qt_log_history.read_log_history', side_effect=track_read), \
             patch('src.services.qt_log_history.job_event_channel', side_effect=wait_inside_sql):
            options = (None, 'shared-job', HistoryEventFilter(keyword='absent', channel=7))
            a = self.adapter.submit('history_events', first, *options)
            self.assertTrue(entered.wait(3))
            b = self.adapter.submit('history_events', second, *options)
            self.adapter.begin_close()
            self.assertTrue(self.adapter.wait_closed(4))
            self.assertTrue(finished.wait(3))
        self.assertEqual(len(cancel_events), 1)
        self.assertIsNotNone(cancel_events[0])
        self.assertTrue(cancel_events[0].is_set())
        self.assertTrue(interrupted, 'the running SQLite query must actually terminate on cancellation')
        _, _, results = self.adapter.take_updates()
        reads = [result for result in results if result.operation == 'history_events']
        self.assertCountEqual([(result.identifier, result.project_id) for result in reads], [(a, first), (b, second)])
        self.assertTrue(all(result.error and result.payload is None for result in reads))

    def test_close_project_releases_sql_reader_before_reopen_and_keeps_other_project_reads(self):
        from contextlib import closing, contextmanager
        import sqlite3
        from src.models.qt_log_history import HistoryEventFilter, job_event_channel
        from src.services.qt_log_history import job_database_path

        a = self._history_project('reopen-A')
        b = self._history_project('unaffected-B')
        store = self.adapter._service.projects
        original = store.opened[a]
        database = job_database_path(original)
        entered, release, connection_closed = threading.Event(), threading.Event(), threading.Event()
        close_observations, results = [], []
        close_project, take_updates = store.close, self.adapter.take_updates

        @contextmanager
        def observe_connection(connection):
            path = connection.execute('PRAGMA database_list').fetchone()[2]
            try:
                with closing(connection):
                    yield connection
            finally:
                if Path(path) == database:
                    connection_closed.set()

        def block_first_query(stage, message):
            if 'reopen-A' in message and not entered.is_set():
                entered.set()
                if not release.wait(12):
                    raise AssertionError('test did not release the SQLite query')
            return job_event_channel(stage, message)

        def observe_project_close(context):
            if context is original:
                close_observations.append(connection_closed.is_set())
            return close_project(context)

        def collect_results():
            updates = take_updates()
            results.extend(updates[2])
            return updates

        with patch('src.services.qt_log_history.closing', observe_connection), \
             patch('src.services.qt_log_history.job_event_channel', side_effect=block_first_query), \
             patch.object(store, 'close', side_effect=observe_project_close), \
             patch.object(self.adapter, 'take_updates', side_effect=collect_results):
            options = (None, 'shared-job', HistoryEventFilter(channel=7))
            try:
                active = self.adapter.submit('history_events', a, *options)
                self.assertTrue(entered.wait(3))
                queued = self.adapter.submit('history_events', a, *options)
                other = self.adapter.submit('history_events', b, *options)
                close_request = self.adapter.submit('close', a)
                second_close = self.adapter.submit('close', a)
                self.command('refresh')  # All preceding workspace commands were admitted.
                self.assertIs(store.opened[a], original)
                self.assertFalse(connection_closed.is_set())
                self.assertNotIn((close_request, 'close'), self.results)
                self.assertNotIn((second_close, 'close'), self.results)
                refused = self.command('open', original.root, expected_error=True)
                self.assertIn('正在关闭', refused.error)
            finally:
                release.set()
            self.wait_for(lambda: (second_close, 'close') in self.results and (other, 'history_events') in self.results)
            self.assertNotIn(a, store.opened)
            for receipt in (close_request, second_close):
                self.assertFalse(self.results[receipt, 'close'].error)
            self.assertEqual(close_observations, [True])
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('UPDATE job_events SET message=?', (json.dumps(dict(channel=7, origin='after-reopen')),))
            self.assertEqual(self.command('open', original.root).project_id, a)
            reopened = self.command('history_events', a, *options)
        reads = [r for r in results if r.operation == 'history_events']
        self.assertCountEqual([(r.identifier, r.project_id) for r in reads],
                              [(active, a), (queued, a), (other, b), (reopened.identifier, a)])
        for request in (active, queued):
            cancelled = self.results[request, 'history_events']
            self.assertTrue(cancelled.error)
            self.assertIsNone(cancelled.payload)
        other_result = self.results[other, 'history_events']
        self.assertFalse(other_result.error)
        self.assertIn('unaffected-B', other_result.payload.entries[0].message)
        self.assertIn('after-reopen', reopened.payload.entries[0].message)

    def test_slow_archive_reader_does_not_delay_workspace_work_or_exit(self):
        entered, release = threading.Event(), threading.Event()

        def blocked(directory, cursor):
            entered.set()
            release.wait(10)
            return None

        with patch('src.services.qt_archived_logs.read_workspace_log', side_effect=blocked):
            try:
                request = self.adapter.submit('archive_workspace_log', '', None)
                self.assertTrue(entered.wait(3))
                self.assertIsNotNone(self.command('refresh'))
                self.assertNotIn((request, 'archive_workspace_log'), self.results)
                self.assertIn('已有归档', self.command('archive_workspace_log', '', None, expected_error=True).error)
                self.adapter.begin_close()
                self.assertTrue(self.adapter.wait_closed(3))
                self.drain()
                self.assertIn('已取消归档', self.results[request, 'archive_workspace_log'].error)
            finally:
                release.set()

    def test_imported_connection_uses_original_encrypted_store_and_keeps_platform_disabled(self):
        from src.services.feishu_remote_store import FeishuConfigStore

        workspace = self.adapter._service
        self.assertEqual(self.command('imported_connection_choices').payload, ())
        directory = workspace.directory / 'platforms/imported/123456789abcdefghijk'
        candidate = FeishuConfigStore(SOURCE, directory=directory)
        imported = dict(app_id='cli_imported_fixture', app_secret='fixture-private-secret',
                        isolated=True, group='group-fixture', corp='tenant-fixture')
        candidate.save(imported)
        (directory / 'source.json').write_text(json.dumps({'name': '旧项目'}), encoding='utf-8')
        destination = workspace.platform_config('feishu')
        destination.save(dict(app_id='cli_previous_fixture', app_secret='previous-secret', isolated=True))
        previous = destination.path.read_bytes()
        original_candidate = candidate.path.read_bytes()
        choices = self.command('imported_connection_choices').payload
        identity, description = choices[0]
        self.assertEqual(description, '飞书 · 旧项目 · 12345678')
        self.assertNotIn('fixture-private-secret', repr(choices))
        self.assertEqual(destination.path.read_bytes(), previous)
        with patch('socket.socket', side_effect=AssertionError('selection cannot open a transport')):
            self.assertEqual(self.command('imported_connection_select', identity).payload, '飞书')
        saved = destination.load()
        self.assertEqual(saved['app_id'], 'cli_imported_fixture')
        self.assertEqual(saved['app_secret'], 'fixture-private-secret')
        self.assertTrue(saved['isolated'])
        self.assertFalse(any(saved[name] for name in ('enabled', 'group_enabled', 'p2p_enabled', 'push_enabled')))
        self.assertEqual(candidate.path.read_bytes(), original_candidate)
        self.assertIsNone(workspace.platforms['feishu'].transport)
        self.assertFalse(workspace.remote_projects)
        self.assertNotIn('fixture-private-secret', '\n'.join(entry.message for entry in self.logs))
        self.command('imported_connection_select', identity, expected_error=True)

    def test_imported_connection_rejects_changed_or_enabled_dingtalk_candidate(self):
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from unittest.mock import PropertyMock

        workspace = self.adapter._service
        directory = workspace.directory / 'platforms/imported/123456789abcdefghijk'
        candidate = RemoteConfigStore(SOURCE, directory=directory)
        value = dict(client_id='fixture-app', client_secret='fixture-secret', robot_code='fixture-robot',
                     group='group-fixture', corp='tenant-fixture', webhook='fixture-webhook', isolated=True)
        candidate.save(value)
        (directory / 'source.json').write_text(json.dumps({'name': 'fixture'}), encoding='utf-8')
        destination = workspace.platform_config('dingtalk')
        destination.save(dict(client_id='old-fixture'))
        identity = self.command('imported_connection_choices').payload[0][0]
        pool = workspace.platforms['dingtalk']
        with patch.object(pool, 'transport', object()), patch.object(type(pool), 'idle', new_callable=PropertyMock, return_value=False):
            rejected = self.command('imported_connection_select', identity, expected_error=True)
            self.assertIn('等待连接退出', rejected.error)
        destination.save(dict(client_id='changed-fixture'))
        self.assertIn('已变化', self.command('imported_connection_select', identity, expected_error=True).error)
        identity = self.command('imported_connection_choices').payload[0][0]
        candidate.save(dict(value, enabled=True))
        self.assertIn('已变化', self.command('imported_connection_select', identity, expected_error=True).error)
        identity = self.command('imported_connection_choices').payload[0][0]
        self.assertIn('含有启用设置', self.command('imported_connection_select', identity, expected_error=True).error)
        self.assertEqual(destination.load()['client_id'], 'changed-fixture')

    def test_legacy_import_rejects_an_overlapping_destination_without_writes(self):
        config = self.root / 'legacy' / 'config'
        config.mkdir(parents=True)
        settings = config / 'test_project_config.ini'
        settings.write_bytes(b'[telnet]\n')
        path = config / 'nested'
        result = self.command('import_legacy', config, path, 'Invalid', expected_error=True)
        self.assertIn('不能包含彼此', result.error)
        self.assertFalse(path.exists())
        self.assertEqual(settings.read_bytes(), b'[telnet]\n')
        self.assertFalse(self.projects)

    def test_selected_channels_are_unknown_not_claimed_running(self):
        path = self.root / 'channels'
        identifier = self.command('create', path, 'channels').project_id
        self.assertEqual(self.projects[0].state, 'idle')
        self.assertEqual(self.projects[0].active_task_count, 0)
        self.assertIsNone(self.projects[0].progress)
        self.assertTrue(all(c.state in ('unknown', 'disabled') and c.cycle is None for c in self.projects[0].channels))
        self.assertIsNone(self.projects[0].success_count)

    def test_old_running_and_queued_history_never_starts_hardware(self):
        path = self.root / 'history'
        identifier = self.command('create', path, 'history').project_id
        self.command('close', identifier)
        for index, state in enumerate(('running', 'queued')):
            run = path / 'runs' / ('run' + str(index)) / 'run.json'
            run.parent.mkdir(parents=True)
            run.write_text(json.dumps(dict(project_id=identifier, owner='old' + str(index),
                run_id='old' + str(index), state=state, operation='aging.start', updated_at=time.time())), encoding='utf-8')
        with patch('serial.Serial', side_effect=AssertionError('physical serial must never open')):
            self.command('open', path)
            project = self.projects[0]
            self.assertEqual(project.state, 'unknown')
            self.assertEqual(project.active_task_count, 0)
            self.assertTrue(matches_project_filter(project, 'unknown'))
            self.assertFalse(matches_project_filter(project, 'queued'))
            self.assertEqual(project.test_type, '开关机挂测')
            self.assertIsNone(project.progress)
        self.assertEqual(json.loads((path / 'runs/run0/run.json').read_text())['state'], 'unknown')

    def test_start_time_follows_project_ledger_after_reopen(self):
        from datetime import datetime
        stamp = 1777777777
        for index, (value, expected) in enumerate((
                (stamp, '开始于 ' + datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M:%S')),
                (None, '尚无开始时间'), ('broken', '开始时间待核实'))):
            path = self.root / f'archived-{index}'
            project_id = self.command('create', path, path.name).project_id
            self.command('close', project_id)
            run = path / 'runs' / f'batch-{index}' / 'run.json'
            run.parent.mkdir(parents=True)
            record = dict(project_id=project_id, owner=f'job-{index}', run_id=run.parent.name,
                          state='succeeded', operation='aging.start', updated_at=stamp + 90)
            if value is not None:
                record['started_at'] = value
            run.write_text(json.dumps(record), encoding='utf-8')
            self.command('open', path)
            project = next(p for p in self.projects if p.project_id == project_id)
            self.assertEqual((project.run_id, project.started_text), (run.parent.name, expected))
            self.assertEqual(project.active_task_count, 0)
            self.assertTrue(matches_project_filter(project, 'completed'))
            self.assertEqual(json.loads(run.read_text(encoding='utf-8')), record)

    def test_reopened_project_attention_uses_its_own_failed_task_receipt(self):
        import sqlite3
        for index, reason in enumerate(('模拟电源初始化失败', '模拟通信失败')):
            path = self.root / f'attention-{index}'
            identifier = self.command('create', path, path.name).project_id
            self.command('close', identifier)
            run_id = f'{index + 1:032x}'
            job_id = f'job-{index}'
            run = path / 'runs' / run_id / 'run.json'
            run.parent.mkdir(parents=True)
            run.write_text(json.dumps(dict(project_id=identifier, run_id=run_id, owner=job_id,
                state='failed', operation='aging.start', created_at=1, started_at=2,
                finished_at=3, updated_at=3)), encoding='utf-8')
            database = path / 'history/ai/business/capability_jobs.sqlite3'
            database.parent.mkdir(parents=True, exist_ok=True)
            from contextlib import closing
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript('''CREATE TABLE jobs(id TEXT PRIMARY KEY, capability TEXT, state TEXT,
                    stage TEXT, updated REAL, result TEXT, payload TEXT);
                    CREATE TABLE job_events(id INTEGER PRIMARY KEY, job_id TEXT, created REAL, stage TEXT, message TEXT);''')
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (job_id, 'aging.start', 'failed',
                    'failed', 3, json.dumps(dict(error=reason if index == 0 else '失败通道：[1]')),
                    json.dumps(dict(arguments=dict(channel_ids=[1])))))
                db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                           (job_id, 2, 'pipeline', reason))
                if index == 1:
                    db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                               (job_id, 2.5, 'history', json.dumps(dict(channel=1, cycle=8, status='failed', detail=reason))))
                    db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                               (job_id, 2.6, 'aging', json.dumps(dict(channel=1, status='failed', detail='测试失败，详细信息请查看执行日志'))))
            self.command('open', path)
            view = next(p for p in self.projects if p.project_id == identifier)
            self.assertEqual(view.attention_count, 1)
            entry, = view.attention_records
            self.assertEqual(entry.reason, reason)
            self.assertIn(reason, entry.related_events[0])
            self.assertEqual(entry.channel, None if index == 0 else 1)
        self.assertEqual({p.attention_records[0].reason for p in self.projects},
                         {'模拟电源初始化失败', '模拟通信失败'})

    def test_overview_reopens_unchecked_pretest_only_with_matching_project_job_evidence(self):
        import sqlite3
        path = self.root / 'overview-history'
        project_id = self.command('create', path, path.name).project_id
        self.command('close', project_id)
        for owner, state, created, updated in (('older', 'succeeded', 1, 5), ('latest', 'skipped', 2, 3)):
            run = path / 'runs' / owner / 'run.json'
            run.parent.mkdir(parents=True)
            run.write_text(json.dumps(dict(project_id=project_id, run_id=owner, owner=owner, state=state,
                operation='pretest.start' if state == 'skipped' else 'aging.start',
                started_at=created, created_at=created, updated_at=updated)), encoding='utf-8')
        database = path / 'history/ai/business/capability_jobs.sqlite3'
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        with connection:
            connection.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, capability TEXT, state TEXT, result TEXT)')
            connection.execute("INSERT INTO jobs VALUES('unrelated','pretest.start','skipped',?)",
                               (json.dumps(dict(outcome='unchecked')),))
        self.command('open', path)
        view, = self.projects
        self.assertFalse(matches_project_filter(view, 'completed'))
        self.assertFalse(matches_project_filter(view, 'unchecked'))
        self.assertEqual(view.overview_state, 'skipped')
        self.assertEqual(view.run_id, 'latest')
        self.assertNotEqual(view.test_type, '开关机挂测')
        from datetime import datetime
        self.assertEqual(view.started_text, datetime.fromtimestamp(2).strftime('开始于 %Y-%m-%d %H:%M:%S'))
        self.command('close', project_id)
        with connection:
            connection.execute("UPDATE jobs SET id='latest'")
        self.command('open', path)
        view, = self.projects
        self.assertTrue(matches_project_filter(view, 'unchecked'))
        self.assertFalse(matches_project_filter(view, 'completed'))
        self.assertTrue(matches_project_filter(view, 'attention'))
        # Earlier service variants returned a successful job plus the original
        # command counters. A positive unchecked count still prevents completion.
        self.command('close', project_id)
        record_path = path / 'runs/latest/run.json'
        record = json.loads(record_path.read_text(encoding='utf-8'))
        record_path.write_text(json.dumps(dict(record, state='succeeded')), encoding='utf-8')
        with connection:
            connection.execute("UPDATE jobs SET state='succeeded', result=? WHERE id='latest'",
                               (json.dumps(dict(result={'unchecked': 1})),))
        self.command('open', path)
        self.assertTrue(matches_project_filter(self.projects[0], 'unchecked'))
        self.command('close', project_id)
        with connection:
            connection.execute("UPDATE jobs SET result=? WHERE id='latest'",
                               (json.dumps(dict(result={'unchecked': 0, 'passed': 1})),))
        self.command('open', path)
        self.assertTrue(matches_project_filter(self.projects[0], 'completed'))

    def test_overview_uses_actual_resume_job_state_and_waits_for_cleanup(self):
        from types import SimpleNamespace
        project_id = self.command('create', self.root / 'overview-resume', '续跑').project_id
        project, = self.projects
        self.assertEqual(project.project_id, project_id)
        latest = dict(owner='resume', state='stopped', created_at=2)
        job = dict(status=dict(state='queued'))
        execution = SimpleNamespace(latest='original', jobs={'resume': job}, jobs_idle=False,
                                    resume=SimpleNamespace(recovery_job='resume', has_waiting=False))
        for raw, expected in (('queued', 'queued'), ('running', 'running'), ('stop_requested', 'stopping'),
                              ('stopped', 'stopping')):
            job['status']['state'] = raw
            self.assertEqual(self.adapter._overview_state(project, latest, (), execution), expected)
        execution.jobs_idle = True
        self.assertEqual(self.adapter._overview_state(project, latest, (), execution), 'stopped')
        execution.resume.has_waiting = True
        self.assertEqual(self.adapter._overview_state(project, latest, (), execution), 'queued')


    def test_reopen_releases_stale_serial_sessions_and_keeps_upgrade_verdicts(self):
        from types import SimpleNamespace
        import uuid
        from src.services.capability_jobs import CapabilityJobs
        from test_qt_log_history import QtLogHistoryTests

        identifier = self.command('create', self.root / 'interrupted', 'NP7287XGS').project_id
        context = self.adapter._service.projects.opened[identifier]
        jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
        try:
            with jobs.db:
                for index, job in enumerate(('f0eb0967-fixture', '95a6b995-fixture')):
                    QtLogHistoryTests.insert_job(jobs, job, index)
                    jobs.db.execute("UPDATE jobs SET capability='firmware.upgrade', state='failed', "
                                    "stage='reconciled' WHERE id=?", (job,))
        finally:
            jobs.close()
        resources = self.adapter._service.resources
        group = uuid.uuid4().hex + ':' + identifier
        ports = ('COM14', 'COM15', 'COM16')
        with resources.lock, resources.fence.db:
            for port in ports:
                key = 'serial:qt-fixture-' + port.lower()
                resources.fence.db.execute('INSERT INTO fence VALUES(?,?,?)', (key, group, 'active'))
                resources.fence.db.execute('INSERT INTO workspace_owners VALUES(?,?,?,?,?)',
                    (f'serial-session:{identifier}:{port}', group, 'active', 'NP7287XGS', json.dumps([key])))
        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=''), \
                patch('serial.Serial', side_effect=AssertionError('recovery must never open serial')):
            self.restart_workspace(identifier)
            self.assertTrue(self.projects[0].can_start)
            resources = self.adapter._service.resources
            self.assertFalse(resources.unknown_for(identifier))
            self.assertEqual(resources.lease_entries(), ())
            execution = self.adapter._execution(self.adapter._service.projects.opened[identifier])
            execution._prepare_guard()
            history = self.command('history_jobs', identifier, None).payload.entries
        self.assertEqual([(job.job_id, job.state) for job in history],
                         [('95a6b995-fixture', 'failed'), ('f0eb0967-fixture', 'failed')])
        self.assertTrue(any('已释放失效占用' in entry.message for entry in self.logs))
        self.assertIsNone(execution.capabilities)

    def test_recovery_releases_only_unlocked_owners_and_retries_interrupted_transaction(self):
        import sqlite3
        import uuid
        from src.core.host_resource_lock import HostResourceLock

        identifier = self.command('create', self.root / 'release', '模拟资源').project_id
        resources = self.adapter._service.resources
        group = uuid.uuid4().hex + ':' + identifier
        free, held = 'serial:qt-fixture-release-free', 'serial:qt-fixture-release-held'
        with resources.lock, resources.fence.db:
            for owner, key in (('free-owner', free), ('held-owner', held)):
                resources.fence.db.execute('INSERT INTO fence VALUES(?,?,?)', (key, group, 'active'))
                resources.fence.db.execute('INSERT INTO workspace_owners VALUES(?,?,?,?,?)',
                    (owner, group, 'active', '模拟资源', json.dumps([key])))
        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=''):
            with HostResourceLock([held], reentrant=False):
                resources.recover_stale(identifier)
                self.assertEqual(resources.unknown_for(identifier), ('held-owner',))
                self.assertEqual([row.resource_key for row in resources.lease_entries()], [held])
            with patch.object(resources, '_refresh_fence', side_effect=sqlite3.OperationalError('fixture interrupted')):
                with self.assertRaises(sqlite3.OperationalError):
                    resources.recover_stale(identifier)
            self.assertEqual(resources.unknown_for(identifier), ('held-owner',))
            self.assertEqual([row.resource_key for row in resources.lease_entries()], [held])
            resources.acquire('fresh-owner', identifier, '模拟资源', (held,))
        self.assertFalse(resources.unknown_for(identifier))
        self.assertEqual([row.owner_id for row in resources.lease_entries()], ['fresh-owner'])
        resources.release('fresh-owner')

    def test_history_stops_only_the_selected_live_job_in_its_project(self):
        from test_qt_log_history import QtLogHistoryTests

        one = self.command('create', self.root / 'one', '有活动任务的项目').project_id
        other = self.command('create', self.root / 'other', '其他项目').project_id
        execution = self.adapter._execution(self.adapter._service.projects.opened[one])
        execution.instance_registry()
        jobs = execution.capabilities.jobs
        selected, unrelated, ended = 'active-one', 'active-other', 'already-ended'
        for index, identifier in enumerate((selected, unrelated, ended)):
            QtLogHistoryTests.insert_job(jobs, identifier, index)
        with jobs.lock, jobs.db:
            payload = json.dumps(dict(arguments=dict(channel_ids=[1]), resources=[]))
            jobs.db.execute('UPDATE jobs SET state=?,payload=? WHERE id IN (?,?)',
                            ('running', payload, selected, unrelated))
        def finish_fixture():
            with jobs.lock, jobs.db:
                jobs.threads.pop(selected, None)
                jobs.threads.pop(unrelated, None)
                jobs.db.execute('UPDATE jobs SET state=? WHERE id IN (?,?)',
                                ('stopped', selected, unrelated))

        self.addCleanup(finish_fixture)
        selected_control, other_control = Mock(), Mock()
        workers = {identifier: Mock(is_alive=Mock(return_value=True)) for identifier in (selected, unrelated)}
        with patch.dict(jobs.threads, workers), patch.dict(jobs.controls, {
                selected: selected_control, unrelated: other_control}):
            self.command('job_stop_active', other, selected, expected_error=True)
            self.command('job_stop_active', one, ended, expected_error=True)
            selected_control.request_stop.assert_not_called()
            stopped = self.command('job_stop_active', one, selected)
            self.assertEqual(stopped.payload['state'], 'stop_requested')
            self.command('job_stop_active', one, selected)
            selected_control.request_stop.assert_called_once()
            other_control.request_stop.assert_not_called()
        self.assertEqual(jobs._row(unrelated)['state'], 'running')


    def test_interrupted_power_worker_protects_original_resources_until_exit(self):
        from src.models.capabilities import CapabilityError
        from src.services.power_worker_lifetime import ACTIVE, UNVERIFIED

        first = self.command('create', self.root / 'interrupted-power', '原开关机项目').project_id
        second = self.command('create', self.root / 'other-job', '其它项目').project_id
        service = self.adapter._service
        context = service.projects.opened[first]
        identifier, other = 'interrupted-power-fixture', 'separate-job-fixture'
        snapshot = service.projects.snapshot(context)
        service.status.begin(context, identifier, snapshot, 'aging.start')
        service.status.update(identifier, 'running')
        old_key = 'serial:qt-fixture-interrupted-power'
        service.resources.acquire(identifier, first, context.identity.name, (old_key,))
        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=ACTIVE):
            self.restart_workspace(first)

        service = self.adapter._service
        context = service.projects.opened[first]
        resources = service.resources
        execution = self.adapter._execution(context)
        resources.acquire(other, second, '其它项目', ('serial:qt-fixture-separate-job',))
        self.addCleanup(lambda: resources.release(other) if not self.adapter.closed.is_set() else None)
        for notice in (ACTIVE, UNVERIFIED):
            with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=notice):
                with self.assertRaisesRegex(CapabilityError, notice):
                    execution._prepare_guard()
                with self.assertRaisesRegex(CapabilityError, notice):
                    resources.acquire('other-request', second, '其它项目', (old_key,))
                self.assertIn(identifier, resources.unknown_for(first))

        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=''):
            execution._prepare_guard()
        self.assertFalse(resources.unknown_for(first))
        self.assertIn(other, resources.owners)
        ledger = json.loads((snapshot / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['state'], 'unknown')
        self.assertFalse(ledger.get('reconciled'))
        resources.release(other)

    def test_unconfirmed_dirty_close_keeps_worker_and_data_until_explicit_choice(self):
        path = self.root / 'dirty'
        identifier = self.command('create', path, 'dirty').project_id
        config = path / 'draft/Auto_power_on_off_tool/config/network_card_ip.ini'
        original = config.read_bytes()
        config.write_bytes(original + b'\n# unsaved test draft\n')
        self.command('refresh')
        self.assertTrue(self.projects[0].dirty)
        session = self.root / 'workspace/workspace_session.json'
        previous = b'{"projects":[],"selected_project":""}'
        session.write_bytes(previous)
        self.adapter.begin_close()
        self.wait_for(lambda: (0, 'close_rejected') in self.results)
        self.assertEqual(session.read_bytes(), previous)
        self.assertFalse(self.adapter.closed.is_set())
        self.assertFalse(self.adapter._service.release_closed_callbacks())
        self.assertEqual(self.adapter._service.emit, self.adapter._emit)
        self.assertTrue(callable(self.adapter._log_writer.report))
        self.assertIn(b'unsaved test draft', config.read_bytes())
        self.adapter.begin_close({identifier: 'discard'})
        self.assertTrue(self.adapter.wait_closed(5))
        self.assertEqual(config.read_bytes(), original)
        self.assertIsNone(self.adapter._log_writer.report)
        self.assertIsNone(self.adapter._service.resources.recovery_context)

    def test_invalid_operations_preserve_configuration_and_emit_failure(self):
        path = self.root / 'invalid'
        identifier = self.command('create', path, 'invalid').project_id
        before = (path / 'project.linecheck.json').read_bytes()
        self.command('create', path, 'cannot overwrite', expected_error=True)
        self.assertEqual((path / 'project.linecheck.json').read_bytes(), before)
        self.assertTrue(any(entry.level == 'ERROR' for entry in self.logs))
        self.assertEqual(self.projects[0].project_id, identifier)

    def test_refresh_is_coalesced_and_file_commands_run_off_main_thread(self):
        self.assertNotEqual(self.adapter.thread.ident, threading.main_thread().ident)
        with self.adapter.lock:
            first = self.adapter.submit('refresh')
            second = self.adapter.submit('refresh')
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.wait_for(lambda: (first, 'refresh') in self.results)

    def test_host_refresh_shares_one_reader_and_does_not_delay_project_commands(self):
        from src.models.network_adapter import AdapterIdentity
        entered, release = threading.Event(), threading.Event()
        order = []

        def read_serial():
            order.append('serial')
            entered.set()
            self.assertTrue(release.wait(5))
            return ['COM1800']

        def read_adapters():
            order.append('adapters')
            return (AdapterIdentity('VLAN147', 'fixture-inventory-guid'),)

        with patch('src.core.serial_inventory.list_serial_port_names', side_effect=read_serial), \
             patch('src.core.network_adapter.read_adapter_identities', side_effect=read_adapters):
            first = self.adapter.submit('refresh_inventory')
            self.assertTrue(entered.wait(5))
            second = self.adapter.submit('refresh_inventory')
            try:
                self.command('create', self.root / 'while-reading', '读取期间创建')
                self.assertNotIn((first, 'refresh_inventory'), self.results)
            finally:
                release.set()
            self.wait_for(lambda: (second, 'refresh_inventory') in self.results)
        early, late = (self.results[key, 'refresh_inventory'].payload for key in (first, second))
        self.assertEqual(early, dict(adapters=['VLAN147'], ports=['COM1800'], errors=[]))
        self.assertEqual(late, early)
        self.assertIsNot(late['ports'], early['ports'])
        self.assertEqual(order, ['serial', 'adapters'])
        resources = self.adapter._service.resources
        self.assertTrue(resources.inventory_ready)
        self.assertEqual(resources.aliases['vlan147'], 'fixture-inventory-guid')

    def test_host_refresh_keeps_existing_resource_authority_and_ignores_late_results_on_exit(self):
        from src.models.network_adapter import AdapterIdentity
        resources = self.adapter._service.resources
        resources.register_adapter('fixture-inventory', 'old-scan-guid')
        resources.inventory_ready = True
        resources.acquire('inventory-fixture', 'fixture-project', '模拟占用', ('adapter:fixture-inventory',))
        existing = dict(resources.owners)
        try:
            with patch('src.core.serial_inventory.list_serial_port_names', return_value=[]), \
                 patch('src.core.network_adapter.read_adapter_identities', return_value=(
                    AdapterIdentity('fixture-inventory', 'new-scan-guid'),)):
                outcome = self.command('refresh_inventory').payload
            self.assertEqual(outcome['adapters'], ['fixture-inventory'])
            self.assertEqual(resources.aliases['fixture-inventory'], 'old-scan-guid')

            self.assertEqual(resources.owners, existing)
            self.assertTrue(resources.inventory_ready)
        finally:
            resources.release('inventory-fixture')

        entered, release, read_finished = threading.Event(), threading.Event(), threading.Event()

        def blocked_scan():
            entered.set()
            try:
                self.assertTrue(release.wait(5))
                return (AdapterIdentity('fixture-inventory', 'late-scan-guid'),)
            finally:
                read_finished.set()

        with patch('src.core.serial_inventory.list_serial_port_names', return_value=[]), \
             patch('src.core.network_adapter.read_adapter_identities', side_effect=blocked_scan):
            pending = self.adapter.submit('refresh_inventory')
            try:
                self.assertTrue(entered.wait(5))
                self.adapter.begin_close()
                self.assertTrue(self.adapter.wait_closed(4))
                self.drain()
                self.assertIn('已跳过', self.results[pending, 'refresh_inventory'].error)
            finally:
                release.set()
                self.assertTrue(read_finished.wait(5))
            self.assertEqual(resources.aliases['fixture-inventory'], 'old-scan-guid')

    def test_host_refresh_does_not_replace_a_newer_verified_adapter_binding(self):
        from src.models.network_adapter import AdapterIdentity
        resources = self.adapter._service.resources
        entered, release = threading.Event(), threading.Event()

        def read_adapters():
            entered.set()
            self.assertTrue(release.wait(5))
            return (AdapterIdentity('VLAN147', 'earlier-scan-guid'),)

        with patch('src.core.serial_inventory.list_serial_port_names', return_value=[]), \
             patch('src.core.network_adapter.read_adapter_identities', side_effect=read_adapters):
            pending = self.adapter.submit('refresh_inventory')
            try:
                self.assertTrue(entered.wait(5))
                resources.register_adapter('VLAN147', 'newly-verified-guid')
                resources.inventory_ready = True
            finally:
                release.set()
            self.wait_for(lambda: (pending, 'refresh_inventory') in self.results)
        self.assertEqual(resources.aliases['vlan147'], 'newly-verified-guid')
        self.assertTrue(resources.inventory_ready)
        self.assertEqual(self.results[pending, 'refresh_inventory'].payload['adapters'], ['VLAN147'])

    def test_bad_configuration_admission_releases_the_project_lease(self):
        path = self.root / 'bad-config'
        identifier = self.command('create', path, 'bad-config').project_id
        self.command('close', identifier)
        config = path / 'draft/Auto_power_on_off_tool/config/network_card_ip.ini'
        original = config.read_bytes()
        config.write_text('not an ini section\n', encoding='utf-8')
        self.command('open', path, expected_error=True)
        self.assertNotIn(identifier, self.adapter._service.projects.opened)
        self.assertEqual(config.read_text(encoding='utf-8'), 'not an ini section\n')
        config.write_bytes(original)
        self.command('open', path)
        self.assertEqual(self.projects[0].project_id, identifier)

    def test_qt_serial_admission_and_project_close_wait_for_safe_stop(self):
        from qt_execution_fakes import ControlledPipeline, configure_project
        from line_check_assistant.config_store import ChannelConfigStore
        from src.services.qt_log_history import read_log_history
        first = self.command('create', self.root / 'first-run', '模拟项目A').project_id
        second = self.command('create', self.root / 'second-run', '模拟项目B').project_id
        workspace = self.adapter._service
        first_context = workspace.projects.opened[first]
        second_context = workspace.projects.opened[second]
        identities = configure_project(workspace, first_context, (1,))
        identities += configure_project(workspace, second_context, (8,))
        store = ChannelConfigStore(second_context.config_dir / 'network_card_ip.ini')
        store.save(store.load(), 'COM103')
        workspace.projects.save(second_context)
        engine = ControlledPipeline()
        second_engine = ControlledPipeline()
        def pipeline(config, emit):
            owner = second_engine if config.enabled_channels[0].section == 'channel_8' else engine
            return owner.factory(config, emit)
        try:
            with patch('src.core.network_adapter.read_adapter_identities', return_value=identities), \
                 patch('src.services.capability_device_services.PipelineOrchestrator', pipeline), \
                 patch('serial.Serial', side_effect=AssertionError('physical hardware forbidden')):
                confirmation = self.command('prepare_execution', first, 'aging.start').payload
                self.command('confirm_execution', first, confirmation.token)
                self.assertTrue(engine.started.wait(3))
                self.command('prepare_execution', second, 'network.line_check', expected_error=True)
                self.assertFalse(next(p for p in self.projects if p.project_id == second).can_start)
                self.assertTrue(next(p for p in self.projects if p.project_id == second).parallel_power_available)
                confirmation = self.command('prepare_execution', second, 'aging.start').payload
                self.command('confirm_execution', second, confirmation.token)
                self.assertTrue(second_engine.started.wait(3))
                self.assertEqual({project for project, _ in workspace.resources.owners.values()}, {first, second})
                self.assertEqual(len(engine.calls), 1)
                self.command('close', first, expected_error=True)
                reading, release = threading.Event(), threading.Event()

                def delayed_read(*args, **kwargs):
                    reading.set()
                    if not release.wait(8):
                        raise AssertionError('stop did not reach the test engine while reading history')
                    return read_log_history(*args, **kwargs)

                with patch('src.services.qt_log_history.read_log_history', side_effect=delayed_read):
                    request = self.adapter.submit('history_jobs', second, None)
                    try:
                        self.assertTrue(reading.wait(3))
                        self.command('stop_and_close', first, 'discard')
                        self.assertTrue(engine.stop_observed.wait(3))
                        self.assertNotIn((request, 'history_jobs'), self.results)
                    finally:
                        release.set()
                    self.wait_for(lambda: (request, 'history_jobs') in self.results)
                    self.assertFalse(self.results[request, 'history_jobs'].error)
                self.assertIn(first, workspace.projects.opened)
                self.assertTrue(workspace.resources.owners)
                engine.release_stop.set()
                self.wait_for(lambda: first not in workspace.projects.opened)
                self.assertIn(second, workspace.projects.opened)
                self.assertFalse(second_engine.stop_observed.is_set())
                self.assertEqual({project for project, _ in workspace.resources.owners.values()}, {second})
                second_engine.finish.set()
                self.wait_for(lambda: not workspace.resources.owners)
        finally:
            engine.finish.set()
            engine.release_stop.set()
            second_engine.finish.set()
            second_engine.release_stop.set()

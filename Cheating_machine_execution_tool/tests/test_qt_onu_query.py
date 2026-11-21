"""Exercise the native project store, authorization and original jobs with fake OLT results."""
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from line_check_assistant.onu_registration_store import DEFAULT_C600_SERVICES, OnuRegistrationConfig, OnuRegistrationStore
from src.core.zte_olt_telnet import OperationCancelled
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.onu_registration_models import DiscoveredOnu, OnuOperationResult, OnuTemplate, RegisteredOnu
from src.services.onu_registration_service import OnuRegistrationService
from test_onu_registration_service import FakeSession, c300_register_responses
import test_qt_dut_configuration as base


def configure_onu(workspace, context):
    store = OnuRegistrationStore(context.config_dir / 'onu_registration.ini')
    store.save(OnuRegistrationConfig(
        olt_ip='192.0.2.153', source_ip='192.0.2.30', username='fixture-c300', password='fixture-c300-private',
        c600_olt_ip='192.0.2.156', c600_source_ip='192.0.2.60',
        c600_username='fixture-c600', c600_password='fixture-c600-private',
        c600_onu_type='Fixture-C600-Template', c600_services='1,171,170', c300_onu_type='Fixture-C300-Template',
    ))
    workspace.projects.save(context)
    return store


class OnuHarness:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.finished.set()
        self.stop_seen = threading.Event()

    def factory(self, logger):
        return self

    def test_connection(self, family, connection, cancel):
        return self._complete('connection', family, connection, None, cancel,
                              OnuOperationResult(True, '模拟 OLT 登录通过'))

    def query_unregistered(self, family, connection, discovery, cancel):
        c300 = family == 'C300'
        pon = 'gpon-olt_1/2/1' if c300 else 'gpon_olt-1/1/5'
        return self._complete('unregistered', family, connection, discovery, cancel,
            OnuOperationResult(True, '查询到 1 台模拟未注册 ONU', onus=(
                DiscoveredOnu(family, pon, 'FIXT00000001', state='unregistered',
                    onu_interface='gpon-onu_1/2/1:1' if c300 else '',
                    registration_type='SD-41（配置模板）' if c300 else '',
                    pon_type='GPON（根据接口推断）' if c300 else 'XGS-PON',
                    model='' if c300 else 'Fixture DUT'),)))

    def query_templates(self, family, connection, kind, cancel):
        return self._complete('templates', family, connection, kind, cancel,
            OnuOperationResult(True, '模拟模板查询完成', templates=(
                OnuTemplate('Fixture template', kind, pon_type='GPON', rate_label='1G'),)))

    def query_registered_candidates(self, family, connection, pon, cancel):
        return self._complete('registered', family, connection, pon, cancel,
            OnuOperationResult(True, '模拟已注册查询完成', registered_onus=(
                RegisteredOnu(family, pon, 'gpon_onu-1/1/5:3', 3, 'working', 'FIXT00000002', 'Fixture'),)))

    def _complete(self, action, family, connection, detail, cancel, result):
        self.calls.append((action, family, connection, detail))
        self.entered.set()
        for _ in range(1500):
            if self.finished.wait(.01):
                return OnuOperationResult(False, '模拟 OLT 已停止并退出') if cancel.is_set() else result
            if cancel.is_set():
                self.stop_seen.set()
        raise AssertionError('fake OLT call was not released')


def configure_registration(workspace, context, *, whole_olt=False):
    store = configure_onu(workspace, context)
    changes = dict(c600_onu_type='CXP-55', c600_services=DEFAULT_C600_SERVICES)
    if whole_olt:
        changes.update(c600_shelf=0, c600_slot=0, c600_pon=0)
    store.save(replace(store.load(), **changes))
    workspace.projects.save(context)
    return store


class RegistrationHarness(OnuHarness):
    def __init__(self, *, cross_pon=False):
        super().__init__()
        self.cross_pon = cross_pon
        self.registrations = []

    def query_unregistered(self, family, connection, discovery, cancel):
        if family == 'C300':
            return super().query_unregistered(family, connection, discovery, cancel)
        pon = 'gpon_olt-1/1/5'
        return OnuOperationResult(True, '查询到两台模拟 ONU', onus=(
            DiscoveredOnu(family, pon, 'FIXT00000001'),
            DiscoveredOnu(family, 'gpon_olt-1/1/6' if self.cross_pon else pon, 'FIXT00000002'),
        ))

    def register(self, connection, requests, *, cancel_event, command_plans):
        self.registrations.append((connection, tuple(requests), tuple(command_plans)))
        return self._complete('register', requests[0].family, connection, requests, cancel_event,
                              OnuOperationResult(True, '模拟注册与回读完成'))


class SaveHarness(RegistrationHarness):
    def __init__(self, **arguments):
        super().__init__(**arguments)
        self.save_calls = []
        self.save_entered = threading.Event()
        self.save_finished = threading.Event()
        self.save_finished.set()
        self.fail_save = False
        self.fail_registration = False

    def factory(self, logger):
        self.logger = logger
        return self

    def register(self, connection, requests, *, cancel_event, command_plans):
        if self.fail_registration:
            return OnuOperationResult(False, '模拟回读失败')
        return super().register(connection, requests, cancel_event=cancel_event, command_plans=command_plans)

    def save_configuration(self, family, connection, cancel_event):
        service = OnuRegistrationService(logger=self.logger, session_type=self._save_session)
        return service.save_configuration(family, connection, cancel_event)

    @contextmanager
    def _save_session(self, connection, logger, cancel_event):
        def execute(command, timeout):
            self.save_calls.append((connection.host, connection.source_ip, command, timeout))
            logger('模拟已下发 ' + command)
            self.save_entered.set()
            if not self.save_finished.wait(10):
                raise AssertionError('fake save call was not released')
            if cancel_event.is_set():
                raise OperationCancelled('模拟已下发后停止等待')
            if self.fail_save:
                raise TimeoutError('模拟等待保存回执超时')
            return '............[OK].'
        yield SimpleNamespace(execute=execute)


class CleanupHarness(RegistrationHarness):
    def __init__(self, **arguments):
        super().__init__(**arguments)
        responses = c300_register_responses()
        responses['show gpon onu state'] = ('1/2/1:8 enable disable DyingGasp 1(GPON)\n'
                                            '1/2/1:9 enable disable LOS 1(GPON)\n'
                                            '1/2/5:7 enable disable LOS 1(GPON)\nZXAN#')
        responses['show gpon onu baseinfo gpon-olt_1/2/1 8'] = 'gpon-onu_1/2/1:8 SD-41 sn SN:GPON12345678 ready\nZXAN#'
        # The second offline row deliberately has no verifiable SN.
        self.session = FakeSession(responses=responses, fail_once='service Internet gemport 1 vlan 200')

    def factory(self, logger):
        return OnuRegistrationService(logger=logger, session_type=self.session, readiness_timeout=0)


class DeleteHarness(OnuHarness):
    def __init__(self):
        super().__init__()
        self.deleted = []
        self.failures = {}

    def query_registered_candidates(self, family, connection, pon, cancel):
        prefix = 'gpon-onu_' if family == 'C300' else 'gpon_onu-'
        interface = prefix + pon[9:]
        candidates = tuple(
            RegisteredOnu(family, pon, f'{interface}:{number}', number, 'working',
                          f'FIXT0000000{number}', 'Fixture')
            for number in (3, 4)
        )
        return self._complete('registered', family, connection, pon, cancel,
                              OnuOperationResult(True, '查询到 2 台模拟 ONU', registered_onus=candidates))

    def delete_registered_onu(self, family, connection, candidate, cancel):
        self.deleted.append(candidate)
        return self.failures.get(candidate.onu_id, OnuOperationResult(True, '模拟删除并回读'))


class QtOnuQueryTests(unittest.TestCase):
    cleanup_runtime = base.QtDutConfigurationTests.cleanup_runtime
    wait = base.QtDutConfigurationTests.wait

    def setUp(self):
        base.QtDutConfigurationTests.setUp(self)
        self.store = configure_onu(self.workspace, self.context)
        self.harness = OnuHarness()
        self.addCleanup(self.harness.finished.set)
        self.execution.capabilities.onu.registration_factory = self.harness.factory
        self.open()

    def open(self):
        self.window = self.execution.onu_command('show', {})
        self.token = self.window['token']

    def command(self, suffix, **values):
        return self.execution.onu_command(suffix, dict(token=self.token, **values))

    def preview(self, action, family='C300'):
        return self.command('preview', action=action, family=family)

    def run_query(self, action, family='C300'):
        prompt = self.preview(action, family)
        self.command('execute', confirmation=prompt['confirmation'])
        self.wait(lambda: self.execution.idle)
        return prompt, self.command('poll')

    def test_profiles_use_saved_project_store_and_preserve_existing_business_fields(self):
        profiles = self.window['profiles']
        c300, c600 = profiles['C300'], profiles['C600']
        self.assertEqual(c300['olt_ip'], '192.0.2.153')
        self.assertEqual(c600['password'], 'fixture-c600-private')
        c600.update(olt_ip='192.0.2.157', pon=6)
        self.command('save_profile', family='C600', profiles=profiles)
        stored = self.store.load()
        self.assertEqual((stored.olt_family, stored.olt_ip, stored.c600_pon), ('C600', '192.0.2.157', 6))
        self.assertEqual(stored.c300_olt_ip, '192.0.2.153')
        self.assertEqual(stored.c600_services, '1,171,170')
        self.assertEqual(stored.c600_onu_type, 'Fixture-C600-Template')
        self.assertFalse(self.harness.calls)
        old = self.store.config_path.read_bytes()
        profiles['C600']['pon'] = 7
        with patch.object(self.workspace.projects, 'save', side_effect=OSError('fixture save failure')):
            with self.assertRaisesRegex(CapabilityError, '已恢复'):
                self.command('save_profile', family='C600', profiles=profiles)
        self.assertEqual(self.store.config_path.read_bytes(), old)

    def test_query_confirmation_cancels_and_stale_project_cannot_connect(self):
        prompt = self.preview('unregistered')
        self.assertIn('gpon-olt_1/2/1', prompt['summary'])
        self.assertIn('先执行整机发现', prompt['summary'])
        self.assertIn('192.0.2.30', prompt['summary'])
        self.assertNotIn('private', str(prompt))
        self.command('cancel')
        with self.assertRaisesRegex(CapabilityError, '失效'):
            self.command('execute', confirmation=prompt['confirmation'])
        prompt = self.preview('connection')
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, '配置已变化'):
            self.command('execute', confirmation=prompt['confirmation'])
        self.assertFalse(self.harness.calls)

    def test_original_queries_bind_each_family_and_discard_the_temporary_read_grant(self):
        for action, family, key in (
            ('connection', 'C300', 'message'), ('unregistered', 'C300', 'onus'),
            ('onu_type', 'C300', 'templates'), ('dba', 'C600', 'templates'), ('registered', 'C600', 'registered'),
        ):
            with self.subTest(action=action, family=family):
                _, result = self.run_query(action, family)
                self.assertEqual(result['state'], 'succeeded')
                self.assertTrue(result[key])
                self.assertEqual(result['family'], family)
                self.assertNotIn('private', str(result))
                job = self.execution.jobs[result['job']]
                scope = self.execution.onu.latest_request.scope
                self.assertEqual(scope['access'], 'read')
                self.assertFalse(self.execution.capabilities.scopes.allowed(job['authority'].principal, scope))
        self.assertEqual(self.harness.calls[1][3].pon, 1)
        self.assertEqual(self.harness.calls[-1][3], 'gpon_olt-1/1/5')
        self.assertEqual(self.harness.calls[-1][2].source_ip, '192.0.2.60')

    def test_whole_olt_discovery_cannot_be_reused_for_registered_management(self):
        profiles = self.window['profiles']
        profiles['C600'].update(shelf=0, slot=0, pon=0)
        self.command('save_profile', family='C600', profiles=profiles)
        with self.assertRaisesRegex(CapabilityError, '明确单个 PON'):
            self.preview('registered', 'C600')
        prompt, result = self.run_query('unregistered', 'C600')
        self.assertIn('整台 OLT', prompt['summary'])
        self.assertEqual(result['target'], 'OLT')
        self.assertTrue(self.harness.calls[-1][3].is_all_olt)

    def test_stop_waits_for_original_job_and_editor_authority_is_local(self):
        remote = CapabilityAuthority('remote', 'session', 'operation', (), source='feishu', approved=True)
        with self.assertRaisesRegex(CapabilityError, '来源'):
            self.execution.capabilities.execute('onu.editor.show', {}, remote)
        self.harness.finished.clear()
        prompt = self.preview('connection')
        self.command('execute', confirmation=prompt['confirmation'])
        self.assertTrue(self.harness.entered.wait(5))
        self.command('stop')
        self.assertTrue(self.harness.stop_seen.wait(5))
        self.assertFalse(self.execution.idle)
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'stopped')

    def deletion_fixture(self, family='C600'):
        self.harness = DeleteHarness()
        self.execution.capabilities.onu.registration_factory = self.harness.factory
        _, result = self.run_query('registered', family)
        interfaces = [row['onu_interface'] for row in result['registered_rows']]
        return dict(family=family, query_job=result['registered_job'], interfaces=interfaces)

    def test_delete_keeps_confirmed_identity_and_original_per_item_behavior(self):
        data = self.deletion_fixture()
        self.harness.failures[3] = OnuOperationResult(False, '模拟 SN 已变化', error_kind='target')
        prompt = self.command('prepare_delete', **data)
        self.assertIn('FIXT00000003', prompt['targets'][0])
        self.assertIn('FIXT00000004', prompt['targets'][1])
        self.assertFalse(self.harness.deleted)
        self.command('delete', confirmation=prompt['confirmation'])
        self.wait(lambda: self.execution.idle)
        self.assertEqual([candidate.serial_number for candidate in self.harness.deleted], ['FIXT00000003', 'FIXT00000004'])
        self.assertEqual([action[0] for action in self.harness.calls], ['registered'])
        result = self.command('poll')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual([row['status'] for row in result['deleted']], ['failed', 'success'])
        self.assertEqual(result['registered_job'], '')

    def test_delete_decline_stale_scope_and_unlisted_interface_never_run(self):
        data = self.deletion_fixture(family='C300')
        with self.assertRaisesRegex(CapabilityError, '本次查询'):
            self.command('prepare_delete', **dict(data, interfaces=['gpon-onu_1/2/2:3']))
        prompt = self.command('prepare_delete', **data)
        self.command('cancel')
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.command('delete', confirmation=prompt['confirmation'])
        prompt = self.command('prepare_delete', **data)
        profiles = self.window['profiles']
        profiles['C300']['pon'] = 2
        self.command('save_profile', family='C300', profiles=profiles)
        with self.assertRaisesRegex(CapabilityError, '配置已变化'):
            self.command('delete', confirmation=prompt['confirmation'])
        self.assertFalse(self.harness.deleted)

    def test_delete_retains_uncertain_result_and_skips_remaining_targets(self):
        data = self.deletion_fixture()
        self.harness.failures[3] = OnuOperationResult(False, '模拟通信中断', error_kind='transport',
                                                       outcome_uncertain=True)
        prompt = self.command('prepare_delete', **data)
        self.command('delete', confirmation=prompt['confirmation'])
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual([row['status'] for row in result['deleted']], ['failed', 'not_executed'])
        self.assertTrue(self.workspace.resources.unknown_for(self.context.identity.project_id))

    def registration_fixture(self, *, family='C600', cross_pon=False, harness=RegistrationHarness):
        self.store = configure_registration(self.workspace, self.context, whole_olt=cross_pon)
        self.open()
        self.harness = harness(cross_pon=cross_pon)
        self.addCleanup(self.harness.finished.set)
        if isinstance(self.harness, SaveHarness):
            self.addCleanup(self.harness.save_finished.set)
        self.execution.capabilities.onu.registration_factory = self.harness.factory
        _, result = self.run_query('unregistered', family)
        selected = [dict(sn=row['serial_number'], pon=row['pon_interface'], id=index)
                    for index, row in enumerate(result['discovered'], 3)]
        return dict(family=family, discovery=result['discovery'], selection=selected,
                    business=self.window['business'][family])

    def test_registration_dispatches_exact_confirmed_plan_and_keeps_per_pon_scopes(self):
        data = self.registration_fixture(cross_pon=True)
        preview = self.command('prepare_registration', **data)
        self.assertIn('FIXT00000001 · gpon_olt-1/1/5 · ONU ID 3', preview['summary'])
        self.assertIn('FIXT00000002 · gpon_olt-1/1/6 · ONU ID 4', preview['summary'])
        self.assertFalse(self.harness.registrations)
        self.command('register', confirmation=preview['confirmation'], **data)
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'succeeded')
        self.assertIn('未选择保存', self.command('poll')['message'])
        connection, requests, plans = self.harness.registrations[0]
        self.assertEqual(connection.source_ip, '192.0.2.60')
        self.assertEqual([request.onu_id for request in requests], [3, 4])
        self.assertEqual(tuple(plan.request for plan in plans), requests)
        for plan in plans:
            self.assertIn('\n'.join(plan.commands), preview['commands'])
            self.assertNotIn('write', plan.commands)
        self.assertEqual(self.command('poll')['discovery'], '')

    def test_registration_rejects_changed_selection_and_duplicate_ids(self):
        data = self.registration_fixture()
        original = self.command('prepare_registration', **data)
        data['selection'][1]['id'] = 3
        with self.assertRaisesRegex(CapabilityError, '已变化'):
            self.command('register', confirmation=original['confirmation'], **data)
        with self.assertRaisesRegex(CapabilityError, 'ID 重复'):
            self.command('prepare_registration', **data)
        self.assertFalse(self.harness.registrations)

    def test_c300_plan_uses_original_service_and_cancel_invalidates_preview(self):
        data = self.registration_fixture(family='C300')
        preview = self.command('prepare_registration', **data)
        self.assertIn('gpon-olt_1/2/1', preview['commands'])
        self.command('cancel')
        with self.assertRaisesRegex(CapabilityError, '重新生成'):
            self.command('register', confirmation=preview['confirmation'], **data)
        self.assertFalse(self.harness.registrations)
        self.harness.finished.clear()
        self.harness.entered.clear()
        preview = self.command('prepare_registration', **data)
        self.command('register', confirmation=preview['confirmation'], **data)
        self.assertTrue(self.harness.entered.wait(5))
        self.command('stop')
        self.assertTrue(self.harness.stop_seen.wait(5))
        self.assertFalse(self.execution.idle)
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'unknown')
        self.assertTrue(self.workspace.resources.unknown_for(self.context.identity.project_id))

    def test_business_save_preserves_connection_and_invalidates_preview(self):
        data = self.registration_fixture()
        preview = self.command('prepare_registration', **data)
        data['business']['onu_id'] = 7
        self.command('save_business', family='C600', business=data['business'])
        self.assertEqual(self.store.load().c600_onu_id, 7)
        self.assertEqual(self.store.load().c600_source_ip, '192.0.2.60')
        with self.assertRaisesRegex(CapabilityError, '重新生成'):
            self.command('register', confirmation=preview['confirmation'], **data)
        self.assertTrue(self.command('prepare_registration', **data)['confirmation'])

    def register_for_save(self, data):
        prompt = self.command('prepare_registration', **data)
        self.command('register', confirmation=prompt['confirmation'], **data)
        return prompt

    def test_c300_save_requires_new_local_decision_and_does_not_replay_after_decline(self):
        data = self.registration_fixture(family='C300', harness=SaveHarness)
        with self.assertRaisesRegex(CapabilityError, '单独确认'):
            self.command('prepare_registration', **dict(data, write_after_success=True))
        self.register_for_save(data)
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'succeeded')
        self.assertIn('整台 OLT', result['save_confirmation']['summary'])
        self.assertFalse(self.harness.save_calls)
        authority = CapabilityAuthority('remote', 'session', 'operation', (), source='feishu', approved=True)
        request = dict(token=self.token, registration_job=result['job'], accepted=True)
        with self.assertRaisesRegex(CapabilityError, '来源'):
            self.execution.capabilities.execute('onu.editor.save_olt', request, authority)
        decision = self.command('save_olt', registration_job=result['job'], accepted=False)
        self.assertIsNone(decision['save_confirmation'])
        self.assertIn('暂不保存', decision['message'])
        with self.assertRaisesRegex(CapabilityError, '已失效'):
            self.command('save_olt', registration_job=result['job'], accepted=True)
        self.assertFalse(self.harness.save_calls)

    def test_c300_save_checks_the_original_binding_and_global_admission(self):
        data = self.registration_fixture(family='C300', harness=SaveHarness)
        self.register_for_save(data)
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.workspace.projects.save(self.context)
        result = self.command('save_olt', registration_job=result['job'], accepted=True)
        self.assertIn('已变化', result['save_notice'])
        self.assertFalse(self.harness.save_calls)

        data = self.registration_fixture(family='C300', harness=SaveHarness)
        self.register_for_save(data)
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        with patch.object(self.execution, 'other_jobs_active', return_value=True):
            result = self.command('save_olt', registration_job=result['job'], accepted=True)
        self.assertIn('其他项目', result['save_notice'])
        self.assertFalse(self.harness.save_calls)

    def test_c600_save_option_is_frozen_and_runs_once_after_validated_registration(self):
        data = self.registration_fixture(harness=SaveHarness)
        prompt = self.command('prepare_registration', **data)
        self.assertIn('未选择保存', prompt['commands'])
        with self.assertRaisesRegex(CapabilityError, '已变化'):
            self.command('register', confirmation=prompt['confirmation'], **dict(data, write_after_success=True))
        self.harness.finished.clear()
        prompt = self.register_for_save(dict(data, write_after_success=True))
        self.assertIn('独立会话执行 write', prompt['summary'])
        registered_job = self.execution.onu.latest
        self.assertTrue(self.harness.entered.wait(5))
        self.assertFalse(self.harness.save_calls)
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.execution.poll()  # Workspace tick, independent of the modal and selected project.
        self.wait(lambda: self.execution.idle)
        snapshot = self.command('poll')
        self.assertEqual((snapshot['action'], snapshot['state']), ('save', 'succeeded'))
        self.assertEqual(self.harness.save_calls, [('192.0.2.156', '192.0.2.60', 'write', 120)])
        registration, save = (self.execution.jobs[job] for job in (registered_job, snapshot['job']))
        self.assertEqual(registration['authority'].operation_id, save['authority'].operation_id)
        self.assertEqual(save['status']['result']['registration_job'], registered_job)
        self.assertEqual(save['status']['request']['resources'], ['device-business', 'olt:192.0.2.156'])
        self.assertFalse(self.execution.capabilities.scopes.allowed(save['authority'].principal,
                                                                   save['status']['request']['arguments']['scope']))
        self.command('poll')
        self.assertEqual(len(self.harness.save_calls), 1)

    def test_c600_failed_registration_does_not_start_save(self):
        data = self.registration_fixture(harness=SaveHarness)
        self.harness.fail_registration = True
        self.register_for_save(dict(data, write_after_success=True))
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'unknown')
        self.assertFalse(self.harness.save_calls)

    def test_c600_stopped_registration_does_not_start_save(self):
        data = self.registration_fixture(harness=SaveHarness)
        self.harness.finished.clear()
        self.register_for_save(dict(data, write_after_success=True))
        self.assertTrue(self.harness.entered.wait(5))
        self.command('stop')
        self.assertTrue(self.harness.stop_seen.wait(5))
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        self.assertEqual(self.command('poll')['state'], 'unknown')
        self.assertFalse(self.harness.save_calls)

    def test_c600_save_timeout_retains_protection_without_repeat(self):
        data = self.registration_fixture(harness=SaveHarness)
        self.harness.fail_save = True
        self.register_for_save(dict(data, write_after_success=True))
        self.wait(lambda: self.command('poll')['action'] == 'save' and self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'unknown')
        self.assertIn('超时', result['message'])
        self.assertTrue(self.workspace.resources.unknown_for(self.context.identity.project_id))
        self.assertEqual(len(self.harness.save_calls), 1)

    def test_c600_save_admission_error_is_visible_and_does_not_retry(self):
        data = self.registration_fixture(harness=SaveHarness)
        self.harness.finished.clear()
        self.register_for_save(dict(data, write_after_success=True))
        self.harness.finished.set()
        self.wait(lambda: self.execution.idle)
        with patch.object(self.execution.capabilities.jobs, 'start', side_effect=RuntimeError) as admission:
            result = self.command('poll')
            self.assertEqual(admission.call_count, 1)
        self.assertEqual((result['action'], result['state']), ('register', 'succeeded'))
        self.assertIn('任务准入失败', result['save_notice'])
        self.assertEqual(self.command('poll')['save_notice'], result['save_notice'])
        self.assertFalse(self.harness.save_calls)

    def test_c300_stopped_save_remains_unknown_with_origin_registration_success(self):
        data = self.registration_fixture(family='C300', harness=SaveHarness)
        self.register_for_save(data)
        self.wait(lambda: self.execution.idle)
        registration = self.command('poll')['job']
        self.harness.save_finished.clear()
        self.command('save_olt', registration_job=registration, accepted=True)
        self.assertTrue(self.harness.save_entered.wait(5))
        self.command('stop')
        self.assertFalse(self.execution.idle)
        self.harness.save_finished.set()
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual((result['action'], result['state']), ('save', 'unknown'))
        self.assertEqual(self.execution.jobs[registration]['status']['state'], 'succeeded')
        self.assertTrue(self.workspace.resources.unknown_for(self.context.identity.project_id))
        self.assertEqual(self.harness.save_calls, [('192.0.2.153', '192.0.2.30', 'write', 120)])

    def cleanup_fixture(self):
        data = self.registration_fixture(family='C300', harness=CleanupHarness)
        data['business']['onu_type'] = 'SD-41'
        return data

    def query_cleanup(self, data):
        prompt = self.command('prepare_cleanup', **data)
        self.command('execute', confirmation=prompt['confirmation'])
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'succeeded', result['message'])
        self.assertEqual([row['onu_interface'] for row in result['cleanup_candidates']], ['gpon-onu_1/2/1:8'])
        return dict(data, cleanup=dict(query_job=result['job'], interface='gpon-onu_1/2/1:8'))

    def test_c300_cleanup_dispatches_frozen_candidate_through_original_retry(self):
        data = self.query_cleanup(self.cleanup_fixture())
        commands = self.harness.session.commands
        self.assertNotIn('configure terminal', commands)
        self.assertNotIn('no onu 8', commands)
        prompt = self.register_for_save(data)
        self.assertIn('GPON12345678', prompt['commands'])
        self.assertIn('gpon-onu_1/2/1:8', prompt['summary'])
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'succeeded', result['message'])
        self.assertIsNotNone(result['save_confirmation'])
        self.assertEqual(commands.count('no onu 8'), 1)
        self.assertEqual(commands.count('onu 3 type SD-41 sn GPONA62D6F78'), 2)
        self.assertNotIn('no onu 7', commands)
        self.assertNotIn('no onu 9', commands)
        self.assertNotIn('write', commands)
        status = self.execution.jobs[result['job']]['status']
        self.assertEqual(status['request']['arguments']['cleanup']['serial_number'], 'GPON12345678')

    def test_c300_cleanup_rejects_changed_identity_at_original_execution_boundary(self):
        data = self.query_cleanup(self.cleanup_fixture())
        self.harness.session.responses['show gpon onu baseinfo gpon-olt_1/2/1 8'] = (
            'gpon-onu_1/2/1:8 SD-41 sn SN:GPON87654321 ready\nZXAN#')
        self.register_for_save(data)
        self.wait(lambda: self.execution.idle)
        result = self.command('poll')
        self.assertEqual(result['state'], 'unknown')
        self.assertIn('SN 已变化', result['message'])
        self.assertNotIn('no onu 8', self.harness.session.commands)
        self.assertIsNone(result['save_confirmation'])

    def test_c300_cleanup_rejects_wrong_family_batch_stale_option_and_missing_sn(self):
        data = self.cleanup_fixture()
        with self.assertRaisesRegex(CapabilityError, '仅支持 C300 单台'):
            self.command('prepare_cleanup', **dict(data, family='C600'))
        with self.assertRaisesRegex(CapabilityError, '仅支持 C300 单台'):
            self.command('prepare_cleanup', **dict(data, selection=data['selection'] * 2))
        prepared = self.query_cleanup(data)
        with self.assertRaisesRegex(CapabilityError, '未在本次离线候选'):
            self.command('prepare_registration', **dict(prepared, cleanup=dict(prepared['cleanup'], interface='gpon-onu_1/2/1:9')))
        with self.assertRaisesRegex(CapabilityError, '重新查询离线候选'):
            self.command('prepare_registration', **dict(prepared, business=dict(data['business'], onu_id=5)))
        preview = self.command('prepare_registration', **prepared)
        with self.assertRaisesRegex(CapabilityError, '请重新生成'):
            self.command('register', confirmation=preview['confirmation'], **data)
        self.assertNotIn('configure terminal', self.harness.session.commands)

    def test_c300_cleanup_query_confirmation_cancels_and_cannot_retarget(self):
        data = self.cleanup_fixture()
        first = self.command('prepare_cleanup', **data)
        self.command('cancel')
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.command('execute', confirmation=first['confirmation'])
        second = self.command('prepare_cleanup', **data)
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, '配置已变化'):
            self.command('execute', confirmation=second['confirmation'])
        self.assertNotIn('show gpon onu state', self.harness.session.commands)

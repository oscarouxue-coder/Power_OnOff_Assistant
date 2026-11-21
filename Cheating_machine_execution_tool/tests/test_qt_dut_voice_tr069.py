"""Voice and TR069 editor regressions using the original device code and Fake UBUS."""
from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import patch

import test_qt_dut_configuration as base
from qt_voice_tr069_fakes import ManagementHarness
from src.core.dut_ubus_config import MANAGEMENT_SERVER_PATH, MANUAL_INFORM_STAGE_PATH
from src.models.capabilities import CapabilityError
from src.models.dut_config_models import DutTr069Settings, DutVoiceSettings


class QtDutVoiceTr069Tests(unittest.TestCase):
    cleanup_runtime = base.QtDutConfigurationTests.cleanup_runtime
    wait = base.QtDutConfigurationTests.wait
    finish = base.QtDutConfigurationTests.finish

    def setUp(self):
        base.QtDutConfigurationTests.setUp(self)
        self.management = ManagementHarness()
        for method, handler in (
            ('run_dut_status_query_batch', self.management.query_batch),
            ('run_dut_advanced_config_batch', self.management.configure_batch),
        ):
            mock = patch('src.services.qt_dut_configuration.'+method, side_effect=handler)
            mock.start()
            self.addCleanup(mock.stop)
        self.addCleanup(self.management.release_inform.set)

    def preview(self, feature, settings=None, index='2', query_id='', channel_ids=(7,)):
        action = '_query' if settings is None else '_configure'
        parameters = dict(token=self.token, action=feature+action, channel_ids=list(channel_ids),
                          username='fixture-user', password='fixture-private-password', parallel_count=1)
        if feature == 'voice':
            parameters['line_index'] = index
        if settings is not None:
            values = dict(settings) if isinstance(settings, dict) else {
                k: v for k, v in asdict(settings).items() if not k.startswith('supported_')}
            if 'codecs' in values:
                values['codecs'] = list(values['codecs'])
            parameters.update(settings=values, query_id=query_id)
        return self.execution.dut_command('preview', parameters)

    def execute(self, confirmation):
        self.execution.dut_command('execute', dict(token=self.token, confirmation=confirmation['confirmation']))

    def assert_private(self, *values):
        job = self.execution.jobs[self.execution.dut.latest]
        status = self.execution.capabilities.jobs.status(self.execution.dut.latest, job['authority'])
        durable = json.dumps(status)
        display = '\n'.join(row.message for row in self.logs)
        for value in values:
            self.assertNotIn(value, durable)
            self.assertNotIn(json.dumps(value)[1:-1], durable)
            self.assertNotIn(value, display)
            self.assertNotIn(repr(value)[1:-1], display)

    def voice(self, **changes):
        values = dict(line_index='2', display_name='1002', auth_username='fixture-voice',
                      auth_password='fixture-voice-write-secret', proxy_server='192.0.2.60',
                      registrar_server='192.0.2.61', dtmf_method='SIPINFO', sip_mode='IMSSIP', codecs=('G.729',)*5)
        values.update(changes)
        return DutVoiceSettings(**values)

    def test_voice_query_uses_line_and_private_caps_block_unsupported_write(self):
        self.execute(self.preview('voice'))
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'succeeded')
        query = snapshot['voice_tr069_queries']['voice']
        self.assertEqual(query['settings']['line_index'], '2')
        secret = query['settings']['auth_password']
        self.assertIn('fixture-quoted-voice', secret)
        self.assert_private(secret)
        calls = self.management.clients[0].calls
        self.assertTrue(all(call[0]=='get' for call in calls))
        self.assertTrue(any(call[2].endswith('SIP.Client.2.') for call in calls))
        with self.assertRaises(CapabilityError):
            self.preview('voice', self.voice(sip_mode='SIP'), query_id=query['query_id'])
        with self.assertRaises(CapabilityError):
            self.preview('voice', self.voice(line_index='1'), index='1', query_id=query['query_id'])
        with self.assertRaises(CapabilityError):
            self.preview('voice', dict(asdict(self.voice()), supported_sip_modes=['SIP']))

    def test_voice_passes_unchanged_secret_and_ordered_codecs_to_original_core(self):
        settings = self.voice(codecs=('G.729','G.722','G.729','G.711 A-law','G.711 U-law'))
        confirmation = self.preview('voice', settings)
        self.assertNotIn(settings.auth_password, confirmation['summary'])
        self.execute(confirmation)
        self.assertEqual(self.finish()['state'], 'succeeded')
        calls = self.management.clients[-1].calls
        account = next(c for c in calls if c[0] == 'set' and c[2].endswith('SIP.Client.2.'))
        self.assertEqual(account[3]['X_SDMC_AuthPassword'], settings.auth_password)
        codecs = next(c for c in calls if c[0] == 'call')[4]['paths']
        self.assertEqual([item['value'] for item in codecs], list(settings.codecs))
        self.assertTrue(self.management.clients[-1].closed)
        self.assert_private(settings.auth_password)

    def test_tr069_query_capabilities_filter_original_payload_and_inform(self):
        self.execute(self.preview('tr069'))
        query = self.finish()['voice_tr069_queries']['tr069']
        self.assertFalse(query['settings']['manual_inform'])
        self.assert_private(query['settings']['acs_password'], query['settings']['connection_request_password'])
        settings = DutTr069Settings(acs_url='https://acs.example.test/acs', acs_password='fixture-acs-write-secret',
                                    connection_request_password='fixture-request-write-secret')
        with self.assertRaises(CapabilityError):
            self.preview('tr069', replace(settings, manual_inform=True), query_id=query['query_id'])
        self.execute(self.preview('tr069', settings, query_id=query['query_id']))
        self.assertEqual(self.finish()['state'], 'succeeded')
        calls = self.management.clients[-1].calls
        set_call = next(c for c in calls if c[0] == 'set')
        self.assertEqual(set_call[2], MANAGEMENT_SERVER_PATH)
        self.assertEqual(set_call[3], {'URL':settings.acs_url, 'Password':settings.acs_password,
                                     'ConnectionRequestPassword':settings.connection_request_password})
        self.assertFalse(any(c[0] == 'call' for c in calls))
        self.assert_private(settings.acs_password, settings.connection_request_password)

    def test_tr069_manual_inform_failure_is_unknown_after_write(self):
        self.management.inform_result = 'unexpected-failure-code'
        settings = DutTr069Settings(acs_url='https://acs.example.test/acs', manual_inform=True)
        self.execute(self.preview('tr069', settings))
        status = self.finish()
        self.assertEqual(status['state'], 'unknown')
        self.assertFalse(status['rows'][0]['ok'])
        trigger = [c for c in self.management.clients[-1].calls if c[0] == 'call']
        self.assertEqual(len(trigger), 1)
        self.assertEqual(trigger[0][4]['path'], MANUAL_INFORM_STAGE_PATH)

    def test_tr069_manual_inform_stop_keeps_worker_until_safe_point(self):
        self.management.release_inform.clear()
        settings = DutTr069Settings(acs_url='https://acs.example.test/acs', manual_inform=True)
        self.execute(self.preview('tr069', settings))
        self.assertTrue(self.management.inform_waiting.wait(4))
        self.execution.dut_command('stop', dict(token=self.token))
        self.assertTrue(self.management.stop_seen.wait(3))
        self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        self.management.release_inform.set()
        status = self.finish()
        self.assertEqual(status['state'], 'stopped')
        self.assertFalse(status['rows'][0]['ok'])

    def test_acs_url_userinfo_is_private_in_query_and_actual_write(self):
        private_url = 'http://fixture-url-user:fixture-url-private@acs.example.test/acs'
        self.management.reported_fields['URL'] = private_url
        self.execute(self.preview('tr069'))
        query = self.finish()['voice_tr069_queries']['tr069']
        self.assertEqual(query['settings']['acs_url'], private_url)
        self.assert_private('fixture-url-private')
        settings = DutTr069Settings(acs_url=private_url)
        confirmation = self.preview('tr069', settings, query_id=query['query_id'])
        self.assertNotIn('fixture-url-private', confirmation['summary'])
        self.execute(confirmation)
        self.assertEqual(self.finish()['state'], 'succeeded')
        self.assertEqual(self.management.clients[-1].management_values['URL'], private_url)
        self.assert_private('fixture-url-private')

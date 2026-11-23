"""WiFi adapter over original batch/single/core with fake UBUS and fake time."""
from dataclasses import asdict, replace
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import test_qt_dut_configuration as base
from qt_wifi_fakes import WifiHarness
from src.models.capabilities import CapabilityError
from src.models.dut_config_models import DutWifiRadioSettings
from src.models.dut_wifi_form import wifi_editor_defaults, wifi_status_form_values


def parameters(settings):
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if not k.startswith('supported_') and v is not None}
        return value
    return clean(asdict(settings))


class QtDutWifiTests(unittest.TestCase):
    cleanup_runtime=base.QtDutConfigurationTests.cleanup_runtime
    wait=base.QtDutConfigurationTests.wait
    finish=base.QtDutConfigurationTests.finish

    def setUp(self):
        base.QtDutConfigurationTests.setUp(self)
        self.wifi=WifiHarness()
        for name,handler in (
            ('src.services.qt_dut_configuration.run_dut_status_query_batch',self.wifi.query_batch),
            ('src.services.qt_dut_configuration.run_dut_advanced_config_batch',self.wifi.configure_batch)):
            handle=patch(name,side_effect=handler);handle.start();self.addCleanup(handle.stop)
        self.addCleanup(self.wifi.release.set)
        self.addCleanup(self.wifi.release_settle.set)

    def preview(self,feature='wifi_2g',query=False,settings=None,increment=False,ids=None,index='1',query_id=''):
        args=dict(token=self.token,action=feature+('_query' if query else '_configure'),channel_ids=ids or [1,7],
            username='fixture-user',password='fixture-private-password',parallel_count=2,ssid_index=index)
        if not query:args.update(settings=parameters(settings or wifi_editor_defaults(feature)),increment_ssid=increment,query_id=query_id)
        return self.execution.dut_command('preview',args)

    def execute(self,confirmation):
        self.execution.dut_command('execute',dict(token=self.token,confirmation=confirmation['confirmation']))

    def query(self,feature='wifi_2g',ids=None,index='1'):
        self.execute(self.preview(feature,query=True,ids=ids,index=index));return self.finish()

    def test_shared_wifi_defaults_match_legacy_forms_without_tk(self):
        # The values below were captured from both original windows.
        common = {'channel': 'auto',
         'max_associations': '32',
         'peer_channel': 'auto',
         'security_mode': 'WPA2-Personal',
         'ssid_index': '1',
         'transmit_power': '100'}
        variants = {'wifi_2g': {'channel_bandwidth': '20/40MHz',
                     'operating_mode': 'b,g,n,ax',
                     'password': 'Sdmc@1234_2G',
                     'peer_channel_bandwidth': '160MHz',
                     'peer_operating_mode': 'a,n,ac,ax',
                     'ssid': 'Test_2G_01'},
         'wifi_5g': {'channel_bandwidth': '160MHz',
                     'operating_mode': 'a,n,ac,ax',
                     'password': 'Sdmc@1234_5G',
                     'peer_channel_bandwidth': '20/40MHz',
                     'peer_operating_mode': 'b,g,n,ax',
                     'ssid': 'Test_5G_01'}}
        for feature, fields in variants.items():
            expected = dict(common, **fields)
            values = wifi_status_form_values(wifi_editor_defaults(feature))
            self.assertEqual({key: values[key] for key in expected}, expected)
        result=subprocess.run([sys.executable,'-c',"import sys;import src.models.dut_wifi_form;assert 'tkinter' not in sys.modules"],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_query_actual_mapping_and_caps_are_private_but_public_result_has_no_key(self):
        status=self.query(index='8')
        self.assertEqual(status['state'],'succeeded')
        query=status['wifi_queries']['wifi_2g']
        self.assertEqual(query['settings']['password'],'password2g')
        self.assertEqual(query['settings']['ssid_index'],'8')
        self.assertEqual(query['settings']['supported_channels'],('1','6','11'))
        item=self.execution.jobs[self.execution.dut.latest]
        durable=self.execution.capabilities.jobs.status(self.execution.dut.latest,item['authority'])
        self.assertNotIn('password2g',json.dumps(durable))
        self.assertNotIn('password2g','\n'.join(v.message for v in self.logs))
        self.assertFalse([c for s in self.wifi.states.values() for c in s.calls if c[0]=='call'])
        self.assertTrue(all(c.closed for c in self.wifi.sessions))

    def test_normal_configuration_uses_original_core_and_each_original_60_second_wait(self):
        self.execute(self.preview('wifi_5g'))
        status=self.finish()
        self.assertEqual(status['state'],'succeeded')
        self.assertEqual(self.wifi.shared,[False])
        waits=[e for e in self.wifi.events if e[0]=='wait' and e[2]==60]
        self.assertEqual(len(waits),2);self.assertTrue(all(e[1]!='batch' for e in waits))
        for state in self.wifi.states.values():
            self.assertEqual(state.ssids['Device.WiFi.SSID.12.']['SSID'],'Test_5G_01')
            self.assertEqual(state.radios['Device.WiFi.Radio.32.']['OperatingChannelBandwidth'],'160MHz')

    def test_increment_batch_preserves_order_one_shared_wait_and_verified_outcomes(self):
        settings=replace(wifi_editor_defaults('wifi_2g'),ssid='Lab_009')
        before=self.execution._binding()
        confirmation=self.preview(settings=settings,increment=True)
        self.assertIn('统一稳定等待60秒',confirmation['summary'])
        self.assertNotIn(settings.password,confirmation['summary'])
        self.execute(confirmation)
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual(self.wifi.shared,[True])
        waits=[(i,e) for i,e in enumerate(self.wifi.events) if e[0]=='wait' and e[2]==60]
        self.assertEqual(len(waits),1);self.assertEqual(waits[0][1][1],'batch')
        self.assertTrue(all(i<waits[0][0] for i,e in enumerate(self.wifi.events) if e[0]=='apply'))
        self.assertTrue(all(i>waits[0][0] for i,e in enumerate(self.wifi.events) if e[0]=='verify'))
        self.assertEqual(self.wifi.state('通道 1').ssids['Device.WiFi.SSID.11.']['SSID'],'Lab_009')
        self.assertEqual(self.wifi.state('通道 7').ssids['Device.WiFi.SSID.11.']['SSID'],'Lab_010')
        self.assertEqual(self.execution._binding(),before)
        job=self.execution.jobs[self.execution.dut.latest]
        saved=self.execution.capabilities.jobs.status(self.execution.dut.latest,job['authority'])
        self.assertTrue(saved['request']['arguments']['wifi']['shared_settle'])
        self.assertNotIn(settings.password,json.dumps(saved))

    def test_single_increment_keeps_single_device_configure_wait(self):
        self.execute(self.preview(increment=True,ids=[7]))
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual(self.wifi.shared,[False])
        self.assertEqual([e[0] for e in self.wifi.events if e[0] in ('apply','verify','configure')],['configure'])

    def test_dual_band_updates_both_radios_and_original_shared_parameters(self):
        settings=replace(wifi_editor_defaults('wifi_2g'),dual_band_enabled=True,transmit_power='80',
            peer_radio=DutWifiRadioSettings('5G',channel='36',channel_bandwidth='80MHz',operating_mode='a,n,ac,ax',transmit_power='80'))
        self.execute(self.preview(settings=settings,ids=[1]))
        self.assertEqual(self.finish()['state'],'succeeded')
        state=self.wifi.state('通道 1')
        self.assertEqual(state.ssids['Device.WiFi.SSID.11.']['SSID'],state.ssids['Device.WiFi.SSID.12.']['SSID'])
        self.assertEqual(state.radios['Device.WiFi.Radio.32.']['OperatingChannelBandwidth'],'80MHz')
        self.assertTrue(all(v['TransmitPower']=='80' for v in state.radios.values()))

    def test_real_query_caps_block_unsupported_values_and_client_cannot_forge_lists(self):
        query=self.query()['wifi_queries']['wifi_2g']
        with self.assertRaises(CapabilityError):self.preview(settings=replace(wifi_editor_defaults('wifi_2g'),channel='13'),query_id=query['query_id'])
        args=dict(token=self.token,action='wifi_2g_configure',channel_ids=[1,7],username='fixture-user',password='fixture-private-password',
            parallel_count=1,ssid_index='1',increment_ssid=False,settings=parameters(wifi_editor_defaults('wifi_2g')))
        args['settings']['supported_channels']=['13']
        with self.assertRaises(CapabilityError):self.execution.dut_command('preview',args)

    def test_no_peer_query_does_not_invent_a_peer_power_capability_intersection(self):
        for channel in ('通道 1','通道 7'):
            radio=self.wifi.state(channel).radios['Device.WiFi.Radio.31.']
            radio['TransmitPower']='35';radio['TransmitPowerSupported']='35,45,65'
        query=self.query()['wifi_queries']['wifi_2g']
        # The original core always queries both radios. Inject a partial model
        # only to characterize the shared form helper's no-peer fallback.
        cache=self.execution.dut.wifi.queries['wifi_2g']
        cache['settings']=replace(cache['settings'],peer_radio=None)
        settings=replace(wifi_editor_defaults('wifi_2g'),dual_band_enabled=True,transmit_power='45',
            peer_radio=replace(wifi_editor_defaults('wifi_2g').peer_radio,transmit_power='45'))
        self.preview(settings=settings,query_id=query['query_id'])
        self.assertEqual(len(self.wifi.calls),2)

    def test_different_target_settings_do_not_return_a_common_configuration(self):
        self.wifi.state('通道 7').ssids['Device.WiFi.SSID.11.']['SSID']='different'
        query=self.query()['wifi_queries']['wifi_2g']
        self.assertTrue(query['all_succeeded']);self.assertIsNone(query['settings'])

    def test_stopped_shared_wait_never_reports_applied_but_unverified_as_success(self):
        self.wifi.release_settle.clear()
        self.execute(self.preview(increment=True))
        self.assertTrue(self.wifi.settle_entered.wait(4))
        self.execution.dut_command('stop',dict(token=self.token))
        self.assertTrue(self.wifi.stop_seen.wait(3));self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        self.wifi.release_settle.set()
        status=self.finish()
        self.assertEqual(status['state'],'stopped')
        self.assertFalse(any(r.get('ok') for r in status['rows']))
        self.assertFalse(any(e[0]=='verify' for e in self.wifi.events))

    def test_readback_mismatch_is_an_unknown_write_outcome_not_success(self):
        self.wifi.mismatch=True
        self.execute(self.preview(increment=True))
        status=self.finish();self.assertEqual(status['state'],'unknown')
        self.assertFalse(any(r.get('ok') for r in status['rows']))
        with self.assertRaises(CapabilityError):self.preview()

    def test_expiry_cancel_config_and_query_changes_prevent_dispatch(self):
        query=self.query()['wifi_queries']['wifi_2g']
        confirmation=self.preview(query_id=query['query_id'])
        self.execution.dut_command('cancel',dict(token=self.token))
        with self.assertRaises(CapabilityError):self.execute(confirmation)
        confirmation=self.preview(query_id=query['query_id'])
        p=self.execution.dut.pending;self.execution.dut.pending=(*p[:2],time.monotonic()-121,*p[3:])
        with self.assertRaises(CapabilityError):self.execute(confirmation)
        confirmation=self.preview(query_id=query['query_id'])
        self.execution.dut.wifi.queries['wifi_2g']['query_id']='0'*32
        with self.assertRaises(CapabilityError):self.execute(confirmation)
        self.assertFalse([e for e in self.wifi.events if e[0] in ('apply','configure')])

    def test_malformed_ssid_sequence_band_index_and_radio_fail_before_job(self):
        for settings in (replace(wifi_editor_defaults('wifi_2g'),ssid='NoSuffix'),
                replace(wifi_editor_defaults('wifi_2g'),band='5G'),replace(wifi_editor_defaults('wifi_2g'),ssid='中'*11)):
            with self.assertRaises(CapabilityError):self.preview(settings=settings,increment=True)
        with self.assertRaises(CapabilityError):self.preview(query=True,index='9')
        self.assertFalse(self.wifi.calls)

    def test_query_index_failure_remains_failure_and_never_falls_back_to_first_ssid(self):
        self.wifi.mapping_count=1
        status=self.query(index='8')
        self.assertEqual(status['state'],'failed')
        self.assertFalse(status['wifi_queries']['wifi_2g']['all_succeeded'])
        self.assertIsNone(status['wifi_queries']['wifi_2g']['settings'])

    def test_quoted_key_and_credentials_never_enter_logs_or_durable_metadata(self):
        password='fixture"key\\secret'
        settings=replace(wifi_editor_defaults('wifi_2g'),password=password)
        self.execute(self.preview(settings=settings,ids=[1]))
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual(self.wifi.state('通道 1').aps['Device.WiFi.AccessPoint.21.']['Security']['X_SDMC_Key'],password)
        text='\n'.join(v.message for v in self.logs)
        self.assertNotIn(password,text);self.assertNotIn(repr(password)[1:-1],text)
        job=self.execution.jobs[self.execution.dut.latest]
        self.assertNotIn(password,json.dumps(self.execution.capabilities.jobs.status(self.execution.dut.latest,job['authority'])))

    def test_open_auth_omits_wire_key_but_keeps_entered_password_in_request(self):
        settings=replace(wifi_editor_defaults('wifi_2g'),security_mode='None',password='retained-password')
        self.execute(self.preview(settings=settings,ids=[1]));self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual(self.wifi.calls[0].settings.password,'retained-password')
        sets=[c[4]['paths'] for c in self.wifi.state('通道 1').calls if c[0]=='call']
        self.assertFalse(any('X_SDMC_Key' in p['obj_path'] for group in sets for p in group))

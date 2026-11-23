"""WAN GUI commands through original jobs, batches, single services and payloads."""
from dataclasses import asdict
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import test_qt_dut_configuration as base
from qt_dut_fakes import WanHarness
from src.models.capabilities import CapabilityError
from src.models.dut_config_models import DutWanSettings


class QtDutWanTests(unittest.TestCase):
    cleanup_runtime = base.QtDutConfigurationTests.cleanup_runtime
    wait = base.QtDutConfigurationTests.wait
    finish = base.QtDutConfigurationTests.finish

    def setUp(self):
        base.QtDutConfigurationTests.setUp(self)
        self.wan = WanHarness()
        for target, side_effect in (
            ('src.services.qt_dut_configuration.run_dut_wan_query_batch', self.wan.wan_query_batch),
            ('src.services.qt_dut_configuration.run_dut_advanced_config_batch', self.wan.wan_configure_batch)):
            handle = patch(target, side_effect=side_effect)
            handle.start(); self.addCleanup(handle.stop)
        self.addCleanup(self.wan.release.set)

    def preview(self, action='wan_query', ids=None, settings=None, query_id='', password='fixture-private-password'):
        arguments = dict(token=self.token, action=action, channel_ids=ids or [1, 7], username='fixture-user',
            password=password, parallel_count=2)
        if settings is not None: arguments.update(settings=asdict(settings), query_id=query_id)
        confirmation = self.execution.dut_command('preview', arguments)
        self.assertIn('UBUS',confirmation['summary'])
        self.assertIn(':80',confirmation['summary'])
        self.assertNotIn(':23',confirmation['summary'])
        return confirmation

    def execute(self, confirmation):
        return self.execution.dut_command('execute', dict(token=self.token, confirmation=confirmation['confirmation']))

    def query(self, ids=None):
        self.execute(self.preview(ids=ids))
        return self.finish()

    def test_shared_wan_model_preserves_rules_without_tk(self):
        from src.models.dut_wan_form import normalize_wan_address_modes, resolve_wan_form_rules

        ipv4, ipv6 = normalize_wan_address_modes('PPPoE', 'IPv4+IPv6（双栈）', '静态', '静态')
        self.assertEqual((ipv4, ipv6), ('DHCP', 'SLAAC'))
        rules = resolve_wan_form_rules('修改', '路由', 'PPPoE', 'IPv4+IPv6（双栈）', ipv4, ipv6, 'IPTV')
        self.assertTrue(rules.show_index)
        self.assertTrue(rules.show_pppoe_credentials)
        self.assertTrue(rules.show_multicast_vlan)
        self.assertFalse(rules.show_ipv4_static)
        self.assertFalse(rules.show_ipv6_static)
        self.assertEqual(rules.mtu_default, '1492')
        result = subprocess.run([sys.executable,'-c',
            "import sys; import src.models.dut_wan_form; assert 'tkinter' not in sys.modules"],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_query_private_common_details_never_enter_job_results_or_logs(self):
        status = self.query()
        self.assertEqual(status['state'],'succeeded')
        query=status['wan_query']
        self.assertEqual(query['names'],['1_INTERNET'])
        self.assertEqual(query['details']['1_INTERNET']['pppoe_password'],'fixture-ppp-private')
        self.assertEqual(self.wan.workers,[2])
        job=self.execution.jobs[self.execution.dut.latest]
        stored=self.execution.capabilities.jobs.status(self.execution.dut.latest,job['authority'])
        self.assertNotIn('fixture-ppp-private',json.dumps(stored))
        self.assertNotIn('fixture-private-password',json.dumps(stored))
        self.assertNotIn('fixture-private-password','\n'.join(r.message for r in self.logs))

    def test_modify_calls_original_payload_with_selected_targets_and_unmodified_password(self):
        cache=self.query(ids=[7])['wan_query']
        settings=DutWanSettings(operation='modify',connection_index='1_INTERNET',vlan_id='205',
            port_bind='265',mtu='1492',access_type='PPPoE',pppoe_username='u',pppoe_password='fixture-ppp-private')
        preview=self.preview('wan_configure',ids=[7],settings=settings,query_id=cache['query_id'])
        self.assertNotIn('fixture-ppp-private',preview['summary'])
        self.execute(preview)
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual(len(self.wan.operations),1)
        command,payload=self.wan.operations[0]
        self.assertEqual(payload['Method'],'modify'); self.assertEqual(payload['Index'],1)
        self.assertEqual(payload['VLAN'],'205'); self.assertEqual(payload['PortBind'],265)
        self.assertEqual(payload['Password'],'fixture-ppp-private')
        self.assertNotIn('fixture-ppp-private','\n'.join(r.message for r in self.logs))
        self.assertIsNone(self.finish()['wan_query'])

    def test_add_and_bridge_iptv_use_original_payload_and_keep_project_files(self):
        before=self.execution._binding()
        self.execute(self.preview('wan_configure',settings=DutWanSettings(mode='bridge',service_type='IPTV',
            vlan_id='200',multicast_vlan_id='300',port_bind='9')))
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertEqual([p['Method'] for _,p in self.wan.operations],['add','add'])
        self.assertTrue(all(p['MulticastVLANID']==300 for _,p in self.wan.operations))
        self.assertEqual(self.execution._binding(),before)

    def test_delete_only_accepts_current_common_name_and_original_delete_payload(self):
        cache=self.query()['wan_query']
        self.execute(self.preview('wan_configure',settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),
            query_id=cache['query_id']))
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertTrue(all(p['Method']=='Delete' and p['Index']==1 for _,p in self.wan.operations))

    def test_different_complete_details_do_not_autofill_but_common_delete_is_allowed(self):
        self.wan.different=True
        query=self.query()['wan_query']
        self.assertEqual(query['names'],['1_INTERNET']); self.assertFalse(query['details'])
        self.execute(self.preview('wan_configure',settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),
            query_id=query['query_id']))
        self.assertEqual(self.finish()['state'],'succeeded')

    def test_old_target_credentials_and_invented_name_cannot_use_a_cached_query(self):
        cache=self.query()['wan_query']
        for kwargs in (dict(ids=[7]),dict(password='changed'),dict(query_id='0'*32),
                dict(settings=DutWanSettings(operation='delete',connection_index='99_INVENTED'))):
            args=dict(settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),query_id=cache['query_id'])
            args.update(kwargs)
            with self.assertRaises(CapabilityError): self.preview('wan_configure',**args)
        self.assertFalse(self.wan.operations)

    def test_query_config_change_and_confirmation_changes_never_dispatch(self):
        cache=self.query()['wan_query']
        settings=DutWanSettings(operation='delete',connection_index='1_INTERNET')
        preview=self.preview('wan_configure',settings=settings,query_id=cache['query_id'])
        path=self.context.config_dir/'config.ini'; old=path.read_bytes()
        path.write_bytes(old+b'\n# change after confirmation\n')
        try:
            with self.assertRaises(CapabilityError): self.execute(preview)
        finally: path.write_bytes(old)
        self.assertFalse(self.wan.operations)

    def test_failed_new_query_clears_previous_common_connections(self):
        self.assertIsNotNone(self.query()['wan_query'])
        self.wan.failure=True
        self.assertIsNone(self.query()['wan_query'])
        self.assertFalse(self.wan.operations)

    def test_safe_stop_waits_for_original_wan_worker_and_skips_pending_targets(self):
        self.wan.release.clear()
        self.execute(self.preview('wan_configure',settings=DutWanSettings(vlan_id='200')))
        self.assertTrue(self.wan.started.wait(3))
        self.execution.dut_command('stop',dict(token=self.token))
        self.assertTrue(self.wan.stop_seen.wait(3))
        self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        self.wan.release.set()
        self.assertEqual(self.finish()['state'],'stopped')
        self.assertFalse(self.wan.operations)

    def test_cancel_and_expiry_keep_original_query_without_wan_commands(self):
        cache=self.query()['wan_query']
        preview=self.preview('wan_configure',settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),query_id=cache['query_id'])
        self.execution.dut_command('cancel',dict(token=self.token))
        with self.assertRaises(CapabilityError): self.execute(preview)
        self.assertEqual(self.finish()['wan_query']['query_id'],cache['query_id'])
        preview=self.preview('wan_configure',settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),query_id=cache['query_id'])
        p=self.execution.dut.pending; self.execution.dut.pending=(*p[:2],time.monotonic()-121,*p[3:])
        with self.assertRaises(CapabilityError): self.execute(preview)
        self.assertFalse(self.wan.operations)

    def test_invalid_wan_parameters_fail_before_any_resource_or_device_admission(self):
        for settings in (DutWanSettings(vlan_id='0'),DutWanSettings(vlan_id='200',access_type='PPPoE'),
                DutWanSettings(mode='bridge',service_type='VOICE',vlan_id='200')):
            with self.assertRaises(CapabilityError): self.preview('wan_configure',settings=settings)
        self.assertFalse(self.wan.calls); self.assertFalse(self.workspace.resources.owners)

    def test_resource_denial_preserves_private_query_for_an_explicit_retry(self):
        cache=self.query()['wan_query']
        preview=self.preview('wan_configure',settings=DutWanSettings(operation='delete',connection_index='1_INTERNET'),query_id=cache['query_id'])
        resources=self.execution.capabilities.resources
        resources.acquire('fixture-other-job',('device-business',))
        try:
            with self.assertRaises(CapabilityError): self.execute(preview)
        finally: resources.release('fixture-other-job')
        self.assertEqual(self.finish()['wan_query'],cache)
        self.assertFalse(self.wan.operations)

    def test_json_escaped_pppoe_password_is_sent_exactly_and_hidden_from_logs(self):
        password='fixture-quote"slash\\private'
        self.execute(self.preview('wan_configure',settings=DutWanSettings(vlan_id='200',access_type='PPPoE',
            pppoe_username='fixture-user',pppoe_password=password)))
        self.assertEqual(self.finish()['state'],'succeeded')
        self.assertTrue(all(p['Password']==password for _,p in self.wan.operations))
        logs='\n'.join(r.message for r in self.logs)
        self.assertNotIn(password,logs)
        self.assertNotIn(json.dumps(password)[1:-1],logs)

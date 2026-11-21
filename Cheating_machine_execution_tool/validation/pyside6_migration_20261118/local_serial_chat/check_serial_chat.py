"""Compare an already-open simulated channel session with the tools offered by Qt chat."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
from functools import partial
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
SOURCE = STAGES.parents[1]
sys.path[:0] = [str(STAGES / 'archived_projects'), str(SOURCE / 'tests')]
from check_archived_projects import Workspace, block_external_io
from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from qt_serial_fakes import SerialHarness
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import ModelReply, ProviderProfile
from src.models.serial_models import SerialSettings
from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_serial_client import read_existing_serial
from src.services.ai_store import profile_fingerprint


def relay_workspace(root, guards):
    sys.path.insert(0, str(STAGES / 'qt_gateway_client'))
    from check_live_power import FakeCipher, RelayWorkspace, RemoteInstanceConfig, RemoteInstanceIdentity, SCOPES, project_directory
    cipher = FakeCipher()
    identity = RemoteInstanceIdentity(SOURCE, slot=5)
    try:
        RemoteInstanceConfig(identity, cipher).save(dict(instance_id=identity.instance_id, name='模拟实例',
            url='ws://127.0.0.1:1', vpn=False, credential='fixture', enabled=True, scopes=SCOPES,
            channel_ids=[7], capability_ids=['device.version']))
    finally:
        identity.close()
    settings = project_directory(SOURCE) / 'instance_startup.json'
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(dict(mode='gateway', slot=5)), encoding='utf8')

    def local_transport(client):
        client.connected.set()
        client.stop.wait(30)
        client.connected.clear()

    guards.enter_context(patch('src.services.remote_gateway_runtime.WindowsCredentialCipher', return_value=cipher))
    guards.enter_context(patch('src.core.remote_gateway_transport.GatewayInstanceClient._network', local_transport))
    return RelayWorkspace(root)


def relay_request(runtime, text):
    from test_remote_gateway import PRINCIPAL
    now = time.time()
    return dict(version=1, request_id=str(uuid4()), message_id=str(uuid4()),
                instance_id=runtime.identity.instance_id, run_id=runtime.identity.run_id,
                principal=asdict(PRINCIPAL), text=text, created=now, expires=now+45)


def verify(root, expect_bridge, gateway=False):
    external = []
    block_external_io(external)
    observed = []
    remote_states = []
    marker = 'fixture-only-serial-output-79'

    class Client(DiagnosticModelClient):
        def complete_stream(self, history, tools, stop, on_text=None):
            names = [tool['name'] for tool in tools]
            observed.append(names)
            if len(observed) == 1 and 'read_serial_log' in names:
                if gateway:
                    for request_text in ('读取通道7串口', '停止'):
                        req = relay_request(runtime, request_text)
                        receipt = runtime.bridge.receive(req)
                        assert receipt['state'] == 'rejected' and '未提交' in receipt['notice']
                        assert marker not in json.dumps(receipt) and runtime.bridge.receive(req) == receipt
                        remote_states.append(receipt['state'])
                call = dict(id='fixture-read', name='read_serial_log', arguments={})
                return ModelReply('', [call], history)
            return ModelReply('fixture reply', [], history + [dict(role='assistant', content='fixture reply')])

    with ExitStack() as guards:
        physical = guards.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial')))
        harness = SerialHarness().start()
        guards.callback(harness.stop)
        guards.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
            side_effect=partial(AiDiagnosticService, client_factory=Client)))
        ui = relay_workspace(root, guards) if gateway else Workspace(root)
        guards.callback(ui.close)
        project = ui.command('create', root / 'project', '模拟已有串口').project_id
        service = ui.adapter._service
        ctx = service.projects.opened[project]
        if gateway:
            ui.command('remote_scope_save', ui.command('remote_scope_read').payload.token, [project])
            runtime = service.gateway_runtime
            assert runtime.client.connected.wait(3)
            directory = runtime.bridge.receive(relay_request(runtime, '项目列表'))
            selected = runtime.bridge.receive(relay_request(runtime, '切换项目 ' + project))
            assert project in directory['answer'] and selected['state'] == 'done'
            remote_states.extend([directory['state'], selected['state']])
        port = 'COM7963'
        ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini').save([ChannelConfig('channel_7',
            enabled=True, vlan_name='VLAN107', serial_port=port, network_card_ip='192.0.2.7',
            device_manage_ip='192.0.2.1')])
        profile = service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
        service.models.save_profile(replace(profile, capability='可自动诊断',
                                            tested_fingerprint=profile_fingerprint(profile)))
        ui.command('serial_show', project)
        execution = ui.adapter._execution(ctx)
        manager = execution.manager
        session = manager.acquire_monitor('fixture', SerialSettings(port))
        try:
            driver = harness.drivers[port]
            driver.input.put(marker.encode('ascii'))
            ui.wait(lambda: marker in read_existing_serial(manager, port))
            assert session.cursor() == len(marker)
            ui.command('ai_chat_open', project)
            initial = ui.command('ai_chat_new', project).payload.selected
            selected = ui.command('ai_chat_send', project, initial, '切换到通道7').payload.selected
            backend = ui.adapter._ai_chats[project]
            assert backend.store.chat(selected)['target']['port'] == port
            ui.command('ai_chat_send', project, selected, '读取这个通道已经打开的串口日志')
            ui.wait(lambda: not backend._is_running())
            evidence = backend.store.chat_evidence(selected)
            has_serial = any(marker in row['text'] and 'read_serial_log' in row['source'] for row in evidence)
            assert bool('read_serial_log' in observed[0]) == expect_bridge and has_serial == expect_bridge
            assert all(set(names) <= {'read_serial_log', 'read_test_evidence', 'ask_user'} for names in observed)
            assert manager.existing_session(SerialSettings(port)) is session
            assert not driver.writes and not physical.called and not external
            if gateway:
                assert remote_states == ['done', 'done', 'rejected', 'rejected'] and not runtime.bridge.bridges
            result = dict(old_passive_reader_received_marker=True, qt_offered_tools=observed[0],
                        qt_retained_serial_marker=has_serial, same_monitor=True, device_writes=len(driver.writes),
                        physical_serial_opens=physical.call_count, external_requests=len(external))
            if gateway:
                result['remote_receipts_during_local_chat'] = remote_states
            return result
        finally:
            manager.release('fixture', port, wait=True)


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--expect-bridge', action='store_true')
    args.add_argument('--gateway', action='store_true')
    opts = args.parse_args()
    with tempfile.TemporaryDirectory(prefix='dutpilot-serial-chat-') as directory:
        root = Path(directory).resolve()
        os.environ.update(LOCALAPPDATA=str(root / 'local'), APPDATA=str(root / 'roaming'),
                          PROGRAMDATA=str(root / 'machine'), LINECHECK_GATEWAY_SLOT='')
        print(json.dumps(verify(root, opts.expect_bridge, opts.gateway), indent=2))

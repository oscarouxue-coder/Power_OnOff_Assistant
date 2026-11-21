"""Verify that rejecting a relay message and revoking access leave an admitted power run intact."""
from contextlib import ExitStack
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

STAGES = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(STAGES / 'archived_projects'), str(STAGES / 'power_worker_replay')]
from check_archived_projects import Workspace
import replay
from line_check_assistant.config_store import ChannelConfigStore
from src.models.network_adapter import AdapterIdentity
from src.core.power_supply import channel_power_frame
from src.services import legacy_power_test_service as legacy
from src.services.ai_project_store import project_directory
from src.services.qt_workspace_adapter import QtWorkspaceAdapter
from src.services.remote_gateway_runtime import RemoteInstanceConfig
from src.services.remote_instance_identity import RemoteInstanceIdentity
from test_ai_core import FakeCipher
from test_remote_gateway import PRINCIPAL, SCOPES


RELAY_PORT = 'COM7687'


def relay_child(trace, started, target, args):
    assert args[0].serial_port == RELAY_PORT
    with patch.object(replay, 'POWER_PORT', RELAY_PORT):
        replay.record_child(trace, started, False, None, target, args)


class RelayRack(replay.RecordingSpawn):
    def Process(self, *, target, args, name):
        assert target is legacy._legacy_start_all_worker and self.request is None
        self.request = args[0]
        return self.context.Process(target=relay_child, name=name,
                                    args=(self.trace, self.started_power, target, args))


def configure_relay(service, project):
    replay.configure(service, project, False, 1, 'telnet')
    store = ChannelConfigStore(project.config_dir / 'network_card_ip.ini')
    bindings, adapters = [], []
    for channel in store.load():
        number = int(channel.section.rsplit('_', 1)[1])
        alias = f'VLAN{800 + number}'
        bindings.append(replace(channel, adapter_alias=alias, vlan_name=alias,
                                serial_port=f'COM{7800 + number}'))
        adapters.append(AdapterIdentity(alias, f'qt-relay-simulation-guid-{number}', 'Up'))
    store.save(bindings, RELAY_PORT)
    service.projects.save(project)
    return adapters


class RelayWorkspace(Workspace):
    def __init__(self, root):
        self.adapter = QtWorkspaceAdapter(replay.ROOT, directory=root / 'ws', start_configured_gateway=True)
        self.rows, self.results = {}, {}
        self.wait(lambda: any(r.operation == 'ready' for r in self.results.values()))


def observe(root):
    blocked = []
    replay.block_external_io(blocked)
    cipher = FakeCipher()
    identity = RemoteInstanceIdentity(replay.ROOT, slot=5)
    try:
        RemoteInstanceConfig(identity, cipher).save(dict(instance_id=identity.instance_id, name='模拟实例',
            url='ws://127.0.0.1:1', vpn=False, credential='simulated', enabled=True, scopes=SCOPES,
            channel_ids=[3, 9], capability_ids=['device.version']))
    finally:
        identity.close()
    settings = project_directory(replay.ROOT) / 'instance_startup.json'
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(dict(mode='gateway', slot=5)), encoding='utf-8')

    def network(client):
        client.connected.set()
        client.stop.wait(80)
        client.connected.clear()

    with ExitStack() as scope:
        scope.enter_context(patch('src.services.remote_gateway_runtime.WindowsCredentialCipher', return_value=cipher))
        scope.enter_context(patch('src.core.remote_gateway_transport.GatewayInstanceClient._network', network))
        physical = scope.enter_context(patch('serial.Serial', side_effect=AssertionError('unexpected physical serial')))
        ui = RelayWorkspace(root)
        scope.callback(ui.close)
        key = ui.command('create', root / 'project', '模拟运行中项目').project_id
        service = ui.adapter._service
        project = service.projects.opened[key]
        nics = configure_relay(service, project)
        review = ui.command('remote_scope_read').payload
        ui.command('remote_scope_save', review.token, [key])
        runtime = service.gateway_runtime
        assert runtime.client.connected.wait(3)

        def request(text):
            now = time.time()
            return dict(version=1, request_id=str(uuid4()), message_id=str(uuid4()),
                        instance_id=runtime.identity.instance_id, run_id=runtime.identity.run_id,
                        principal=asdict(PRINCIPAL), text=text, created=now, expires=now+45)

        selected = runtime.bridge.receive(request('切换项目 ' + key))
        assert selected['state'] == 'done' and '已选择项目' in selected['answer']
        rack = RelayRack(root / 'serial.json', False, None)
        original = legacy.run_legacy_power_test
        scope.enter_context(patch.object(legacy, 'run_legacy_power_test', side_effect=lambda req, *a, **kw:
            original(req, *a, process_context=rack, **kw)))
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=nics))
        token = ui.command('prepare_execution', key, 'aging.start').payload.token
        ui.command('confirm_execution', key, token)
        assert rack.started_power.wait(30)
        ui.command('refresh')
        row = ui.rows[key]
        assert row.state == 'running' and row.run_id in service.resources.owners
        job = row.run_id
        stop = request('停止')
        rejection = runtime.bridge.receive(stop)
        assert rejection['state'] == 'rejected' and '未提交' in rejection['notice']
        ui.command('remote_scope_save', ui.command('remote_scope_read').payload.token, [])
        assert runtime.bridge.receive(stop) == rejection
        assert job in service.resources.owners
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ui.command('refresh')
            if ui.rows[key].state != 'running':
                break
            time.sleep(.1)
        assert ui.rows[key].state == 'completed' and ui.rows[key].run_id == job
        assert not service.resources.owners
        trace = json.loads(rack.trace.read_text('utf-8'))
        frames = [event['hex'] for event in trace['events'] if event['event']=='frame']
        assert len(frames)==8
        for number in replay.CHANNELS:
            assert [s for s in frames if bytes.fromhex(s)[4]==number] == [
                channel_power_frame(number, on).hex() for on in (False, True, False, True)]
        assert not blocked and not trace['blocked']
        physical.assert_not_called()
        return dict(relay_receipt=rejection, duplicate_preserved=True, lease_held_after_revocation=True,
                    result='completed', physical_serial_opens=0, external_requests=0, frames=frames,
                    worker_pid=trace['pid'])


if __name__ == '__main__':
    destination = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='dutpilot-relay-power-') as temporary:
        root = Path(temporary).resolve()
        os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'), PROGRAMDATA=str(root/'machine'),
                          LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0')
        evidence = observe(root)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('REJECTED_RELAY_LOCAL_POWER_COMPLETED',len(evidence['frames']))

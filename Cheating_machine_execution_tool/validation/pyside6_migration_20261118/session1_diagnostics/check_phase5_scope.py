"""Exercise local diagnostic admission using synthetic projects and a simulated intent model."""
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGES / 'archived_projects'))
from check_archived_projects import Workspace, block_external_io
from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import ModelReply, ProviderProfile
from src.models.project_task import project_task_scope
from src.services.ai_store import profile_fingerprint


def check(root):
    external = []
    block_external_io(external)
    with ExitStack() as guards:
        serial = guards.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial')))
        ui = Workspace(root)
        guards.callback(ui.close)
        project = ui.command('create', root / 'project', '诊断范围回放').project_id
        workspace = ui.adapter._service
        ctx = workspace.projects.opened[project]
        channels = [ChannelConfig(f'channel_{i}', enabled=True, vlan_name=f'VLAN{100+i}',
                                  serial_port=f'COM{7900+i}') for i in (3, 7)]
        ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini').save(channels)
        profile = workspace.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
        workspace.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
        ui.command('ai_chat_open', project)
        general = ui.command('ai_chat_new', project).payload.selected
        chat = ui.adapter._ai_chats[project]
        text = '一起检查两个测试位的近期情况'
        decisions = []
        class Client(DiagnosticModelClient):
            def complete(self, history, tools, stop):
                assert not tools and json.loads(history[1]['content'])['message'] == text
                decisions.append(text)
                return ModelReply(json.dumps(dict(intent='switch', scope='batch', channels=[3, 7],
                    channel=None, selection='all', question=text, clarification='')), [], history)

        with patch.object(chat.diagnostic, 'client_factory', Client), patch.object(
                chat.conversation.batch, 'submit', side_effect=AssertionError('unexpected batch')) as submit:
            ui.command('ai_chat_send', project, general, text)
            ui.wait(lambda: chat._intent is None)
            status = ui.command('ai_chat_open', project).payload
            assert decisions == [text] and status.selected == general and status.retry_input == text
            assert '尚未接入此批量' in status.latest_status.text and len(chat.store.chats()) == 1
            submit.assert_not_called()
        selected = ui.command('ai_chat_send', project, general, '切换到通道7').payload.selected
        authority = chat.conversation.collection_status(selected)
        tools = sorted(tool['name'] for tool in chat.conversation.tools_for_turn(authority, 'device'))
        assert tools == ['ask_user', 'read_serial_log', 'read_test_evidence'] and not authority['enabled']
        review = ui.command('ai_chat_review', project, selected).payload
        assert review == (selected, None) and not chat.diagnostic.trigger.enabled
        workspace.projects.save(ctx)
        run_root = workspace.projects.snapshot(ctx)
        config = run_root / 'Auto_power_on_off_tool/config'
        execution = chat.conversation.execution
        # These are IPC fixture events. Only the admitted task owns the run.
        with project_task_scope(ctx.config_dir, config):
            execution.observe_ai_event(dict(type='diagnostic_start', run_id='origin-check'))
            execution.observe_ai_event(dict(type='stage', run_id='origin-check', channel=7,
                                            message='owned-record fixture-key'))
        execution.observe_ai_event(dict(type='stage', run_id='origin-check', channel=7,
                                        message='unbound-event-marker'))
        ui.command('ai_chat_select', project, general)
        current = ui.command('ai_chat_send', project, general, '切换到通道7').payload.selected
        retained = chat.store.chat_evidence(current)
        material = json.dumps(retained, ensure_ascii=False)
        assert 'owned-record' in material and 'fixture-key' not in material and 'unbound-event-marker' not in material
        execution.observe_ai_event(dict(type='diagnostic_start', run_id='origin-check'))
        with project_task_scope(ctx.config_dir, config):
            execution.observe_ai_event(dict(type='stage', run_id='origin-check', channel=7,
                                            message='after-conflict'))
        ui.command('ai_chat_evidence', project, current)
        assert chat.store.chat_evidence(current) == retained and chat.store.chat(current)['qt_evidence_notice']
        assert not external and serial.call_count == 0
        return dict(foreign_event_ignored=True, conflicting_start_retains_material=True, model_key_redacted=True,
                    batch_receipt=status.latest_status.text, input_restored=True, batch_created=False,
                    channel_tools=tools, active_collection=authority['enabled'], monitor_enabled=False,
                    pending_channel_approval=review[1], physical_serial_opens=0, external_requests=0)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='qt-phase5-scope-') as temp:
        root = Path(temp).resolve()
        os.environ.update(LOCALAPPDATA=str(root / 'local'), APPDATA=str(root / 'roaming'),
                          PROGRAMDATA=str(root / 'machine'), LINECHECK_GATEWAY_SLOT='')
        print(json.dumps(check(root), ensure_ascii=False, indent=2))

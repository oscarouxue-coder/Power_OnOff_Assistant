"""Cancel delayed local target recognition during the existing simulated power replay."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGES / 'qt_gateway_client'))
import check_live_power as power
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import ModelReply, ProviderProfile
from src.services.ai_session_router import ROUTE_INSTRUCTIONS


def observe(root):
    entered, release = threading.Event(), threading.Event()
    local = {}
    original = power.RelayWorkspace.command

    class DelayedModel(DiagnosticModelClient):
        def complete(self, history, tools, stop):
            request = json.loads(history[1]['content'])
            assert history[0]['content'] == ROUTE_INSTRUCTIONS and not tools
            assert sorted(t['channel'] for t in request['targets']) == [3, 9]
            local['intent_calls'] += 1
            entered.set()
            assert release.wait(8)
            local['recognition_cancelled'] = stop.is_set()
            return ModelReply(json.dumps(dict(intent='switch', scope='device', channel=3,
                                              question='', clarification='')), [], history)

        def complete_stream(self, *args, **kwargs):
            raise AssertionError('cancelled local request must not submit a question')

    def command(ui, operation, *args):
        if operation == 'prepare_execution' and 'origin' not in local:
            project = args[0]
            ui.adapter._service.models.save_profile(ProviderProfile(model='fixture'), 'fixture-key')
            original(ui, 'ai_chat_open', project)
            local.update(project=project, origin=original(ui, 'ai_chat_new', project).payload.selected, intent_calls=0)
            ui.adapter._ai_chats[project].diagnostic.client_factory = DelayedModel
        result = original(ui, operation, *args)
        if operation == 'refresh' and 'project' in local and 'run_id' not in local:
            project, origin = local['project'], local['origin']
            row = ui.rows[project]
            if row.state == 'running':
                local['run_id'] = row.run_id
                chat = ui.adapter._ai_chats[project]
                try:
                    view = original(ui, 'ai_chat_send', project, origin, '请把排查对象换到第三个测试位').payload
                    assert view.routing and entered.wait(4)
                    original(ui, 'refresh')
                    assert ui.rows[project].run_id == row.run_id and ui.rows[project].state == 'running'
                    original(ui, 'ai_chat_stop', project, origin)
                    assert row.run_id in ui.adapter._service.resources.owners
                    local['power_lease_after_chat_stop'] = True
                finally:
                    release.set()
                ui.wait(lambda: chat._intent is None)
                assert chat.selected == origin and len(chat.store.chats()) == 1
        return result

    with patch.object(power.RelayWorkspace, 'command', command):
        record = power.observe(root)
    assert local['intent_calls'] == 1 and local['recognition_cancelled'] and local['power_lease_after_chat_stop']
    return dict(power=record, local_intent_cancelled=True, workspace_refresh_while_waiting=True,
                power_lease_after_chat_stop=True, local_target_changed=False)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='dutpilot-intent-and-power-') as temp:
        root = Path(temp).resolve()
        os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'), PROGRAMDATA=str(root/'machine'),
                          LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0')
        print(json.dumps(observe(root), ensure_ascii=False, indent=2))

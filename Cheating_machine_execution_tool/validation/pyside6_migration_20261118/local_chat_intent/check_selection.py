"""Compare the Qt send path and the original local target router with synthetic data."""
import argparse
from contextlib import ExitStack
from functools import partial
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(STAGES / 'archived_projects')]
from check_archived_projects import Workspace, block_external_io
from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import ModelReply, ProviderProfile
from src.services.ai_diagnostic_service import AiDiagnosticService


def verify(root, case):
    model_calls = []
    intent_calls = []
    external = []
    block_external_io(external)

    class Client(DiagnosticModelClient):
        def complete(self, history, tools, stop):
            from src.services.ai_session_router import ROUTE_INSTRUCTIONS
            assert case == 'natural' and history[0]['content'] == ROUTE_INSTRUCTIONS and not tools
            request = json.loads(history[1]['content'])
            assert [target['channel'] for target in request['targets']] == [7]
            intent_calls.append(request['message'])
            route = dict(intent='switch', scope='device', channel=7, question='', clarification='')
            return ModelReply(json.dumps(route), [], history)

        def complete_stream(self, history, tools, stop, on_text=None):
            assert not tools
            model_calls.append('general')
            return ModelReply('模拟普通问答', [], history + [dict(role='assistant', content='模拟普通问答')])

    with ExitStack() as scope:
        physical = scope.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial')))
        session_open = scope.enter_context(patch('src.core.serial_transport.PySerialSession.open',
                                                  side_effect=AssertionError('serial session')))
        scope.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
                                  side_effect=partial(AiDiagnosticService, client_factory=Client)))
        ui = Workspace(root)
        scope.callback(ui.close)
        project = ui.command('create', root / 'project', '模拟通道切换').project_id
        service = ui.adapter._service
        ctx = service.projects.opened[project]
        ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini').save([
            ChannelConfig('channel_7', enabled=True, vlan_name='VLAN107', serial_port='COM7963',
                          network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')], '')
        profile = service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
        ui.command('ai_chat_open', project)
        original = ui.command('ai_chat_new', project).payload.selected
        chat = ui.adapter._ai_chats[project]
        text = '请把排查对象换到七号测试位' if case == 'natural' else '切换到通道7'
        ui.command('ai_chat_send', project, original, text)
        ui.wait(lambda: not chat._is_running())
        qt_session = chat.store.chat(chat.selected)
        qt_scope = qt_session['scope']
        qt_intent_calls=len(intent_calls)
        if case == 'current' or case == 'natural':
            assert qt_scope == 'device' and qt_session['target']['channel'] == 7 and not model_calls, (qt_scope, chat.store.chat_items(original), intent_calls, model_calls)
        else:
            messages = chat.store.chat_items(original)
            assert any(row.get('text') == '模拟普通问答' for row in messages)
            assert qt_scope == 'general' and model_calls == ['general']

        # Tk refreshes the configured targets before calling this same router.
        target = chat.handoff._target(7)
        assert target and target.port == 'COM7963'
        chat.diagnostic.configure(profile, (target,))
        result = chat.conversation.router.send(text, profile, selected=original)
        routed = chat.store.chat(result['identifier'])
        assert not result['submitted'] and routed['target']['channel'] == 7 and routed['scope'] == 'device'
        assert intent_calls == ([text, text] if case == 'natural' else [])
        assert not external and not physical.called and not session_open.called
        return dict(qt_scope=qt_scope, qt_model_replies=len(model_calls), qt_intent_model_calls=qt_intent_calls, original_intent_model_calls=len(intent_calls)-qt_intent_calls, original_router_scope=routed['scope'],
                    original_router_channel=routed['target']['channel'], original_router_submitted=False,
                    real_model_calls=0, external_requests=len(external), serial_opens=physical.call_count)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['current', 'before', 'natural'], default='current')
    case = parser.parse_args().case
    with tempfile.TemporaryDirectory(prefix='dutpilot-local-target-audit-') as directory:
        root = Path(directory).resolve()
        os.environ.update(LOCALAPPDATA=str(root / 'local'), APPDATA=str(root / 'roaming'),
                          PROGRAMDATA=str(root / 'machine'), LINECHECK_GATEWAY_SLOT='')
        print(json.dumps(verify(root, case), indent=2))

"""Compare project-scoped Qt and original evidence capture after a simulated original power run."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGES/'qt_gateway_client'))
import check_live_power as power
from src.models.ai_diagnostics import ProviderProfile
from src.services.qt_execution_adapter import QtExecutionAdapter
from src.services.ai_conversation_service import AiConversationService


def observe(root):
    original = power.RelayWorkspace.command
    evidence = {}
    starts = []
    original_event = QtExecutionAdapter.observe_ai_event

    def observe_event(execution, event):
        if event.get('type') == 'diagnostic_start':
            starts.append((execution.context.identity.project_id, event['run_id']))
        original_event(execution, event)

    def command(ui, operation, *args):
        result = original(ui, operation, *args)
        if operation != 'refresh' or evidence:
            return result
        row = next((r for r in ui.rows.values() if r.state == 'completed'), None)
        if row is None:
            return result
        key = row.project_id
        ui.adapter._service.models.save_profile(ProviderProfile(model='fixture'), 'fixture-key')
        original(ui, 'ai_chat_open', key)
        origin = original(ui, 'ai_chat_new', key).payload.selected
        chat = ui.adapter._ai_chats[key]
        with patch.object(chat.diagnostic, 'client_factory', side_effect=AssertionError('pure session selection')) as model:
            selected = original(ui, 'ai_chat_send', key, origin, '切换到通道3').payload.selected
            record = chat.store.chat(selected)
            assert record['scope'] == 'device' and record['target']['channel'] == 3
            run = record['run_id']
            raw = chat.conversation.context.snapshot(run, 3)
            assert set(starts) == {(key, run)} and raw and all(r['channel'] == 3 and r['run_id'] == run for r in raw), (starts, key, run, len(raw))
            before = chat.store.chat_evidence(selected)
            control = chat.conversation.create_session(chat.handoff._target(3), chat._profile(), source_report_id='control')
            AiConversationService.refresh_evidence(chat.conversation, control)
            after = chat.store.chat_evidence(control)
            model.assert_not_called()
        def comparable(rows):
            return [(r['source'], r['text'], r['run_id'], r['channel'], r['timing']) for r in rows]
        assert before and comparable(before) == comparable(after)
        for qt_row, original_row in zip(before, after):
            assert datetime.fromisoformat(qt_row['created']).tzinfo is not None
            if '读取时间' not in qt_row['timing']:
                assert qt_row['created'] == original_row['created']
        original(ui, 'ai_chat_select', key, selected)
        assert chat.store.chat_evidence(selected) == before
        assert all(r['channel'] == 3 and r['run_id'] == run for r in after)
        fields = json.dumps(comparable(before), ensure_ascii=False).encode('utf-8')
        evidence.update(project=key, diagnostic_run=run, workspace_job=row.run_id,
                        snapshot=chat.store.chat(selected)['qt_power_snapshot'],
                        source_counts=dict(Counter(item['source'].split(' / ')[0] for item in before)),
                        compared_rows_sha256=hashlib.sha256(fields).hexdigest(),
                        rows_equal=True, event_times_equal=True, repeated_select_unchanged=True,
                        diagnostic_start_matches_project_and_batch=True, diagnostic_start_events=len(starts),
                        workspace_job_id_equals_diagnostic_id=(run == row.run_id), local_channel=3, power_events_available=len(raw),
                        qt_evidence_after_select=len(before), original_evidence_after_refresh=len(after),
                        observed_sources=sorted({str(item['source']).split(' / ')[0] for item in after}),
                        wrong_channel_records=0, model_calls=0)
        return result

    with patch.object(power.RelayWorkspace, 'command', command), patch.object(QtExecutionAdapter, 'observe_ai_event', observe_event):
        trace = power.observe(root)
    assert evidence and len(trace['frames']) == 8
    return dict(comparison=evidence, power_result=trace['result'], power_frames=len(trace['frames']),
                real_serial_opens=trace['physical_serial_opens'], external_requests=trace['external_requests'])


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='dutpilot-readonly-power-evidence-') as temp:
        root = Path(temp).resolve()
        os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'), PROGRAMDATA=str(root/'machine'),
                          LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0')
        print(json.dumps(observe(root), ensure_ascii=False, indent=2))

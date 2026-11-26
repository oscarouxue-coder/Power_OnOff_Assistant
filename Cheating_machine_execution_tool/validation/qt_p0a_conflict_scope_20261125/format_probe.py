"""Synthetic scope check only; NOT a genuine contradictory-evidence fixture."""
from contextlib import ExitStack
from pathlib import Path
import json
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
with ExitStack() as scope:
    endpoints = ('requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                 'socket.socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.startfile')
    blocked = {endpoint: scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))
               for endpoint in endpoints}
    from src.services.qt_power_logs import _material_observation
    time = '2026-11-20 22:10:01.123456'
    fixtures = [
        ('existing_positive_marker', 'command_results', '通道 7 ping 通'),
        ('hypothetical_negative_not_supported', 'command_results', '通道 7 ping 不通'),
        ('hypothetical_timestamped_positive_not_supported', 'command_results', time + ' 通道 7 ping 通'),
        ('same_time_wifi_header_info', 'wifi', time + ' [INFO] [WiFi] 通道7 第3轮 synthetic-marker-a'),
        ('same_time_wifi_header_error', 'wifi', time + ' [ERROR] [WiFi] 通道7 第3轮 synthetic-marker-b'),
    ]
    result = {label: _material_observation(kind, line, 7) for label, kind, line in fixtures}
    assert result['existing_positive_marker'][0] == '时间未知'
    assert result['hypothetical_negative_not_supported'] is None
    assert result['hypothetical_timestamped_positive_not_supported'] is None
    for label in ('same_time_wifi_header_info', 'same_time_wifi_header_error'):
        assert result[label][0] == time + '（原日志本地时间）'
        assert '业务结果未知' in result[label][1]
        assert 'synthetic-marker' not in result[label][1]
    calls = {name: item.call_count for name, item in blocked.items()}
    assert not any(calls.values())
    evidence = dict(synthetic=True, genuine_conflict_constructible=False,
                    observation_count=len(fixtures), observations=result, denied_calls=calls)
    (Path(__file__).resolve().parent / 'format-observation.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print('FORMAT_SCOPE_OBSERVED; GENUINE_CONFLICT_NOT_ACCEPTED')

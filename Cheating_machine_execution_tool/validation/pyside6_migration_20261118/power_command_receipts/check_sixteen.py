"""Run two rounds through the original Windows child on all 16 virtual channels."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from check_timing import inspect_channel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'power_worker_replay'))
import replay


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--qt', action='store_true', help='Use the Qt prepare and confirm path with original host leases')
    args = cli.parse_args()
    numbers = tuple(range(1, 17))
    blocked = []
    replay.block_external_io(blocked)
    with tempfile.TemporaryDirectory(prefix='dutpilot-16-virtual-') as directory, \
            patch.object(replay, 'CHANNELS', numbers), \
            patch('serial.Serial', side_effect=AssertionError('parent must not open a port')):
        case = replay.run_case('qt' if args.qt else 'direct', Path(directory), short_wait=True, execution_timeout=360)
    assert not blocked and not case['blocked']
    assert case['original_reported_state'] == 'succeeded' and case['complete_serial_sequences']
    assert sum(event['event'] == 'frame' for event in case['events']) == 64
    for channel in numbers:
        inspect_channel(case['events'], channel, 1)
    args.output.write_text(json.dumps(case, indent=2), encoding='utf-8')
    print('POWER_WORKER_16_CHANNELS_64_FRAMES_OK')

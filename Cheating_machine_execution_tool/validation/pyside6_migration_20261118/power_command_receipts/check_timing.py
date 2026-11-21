"""Check monotonic timestamps from the recording serial port and original waits."""
import json
from pathlib import Path


def inspect_channel(events, channel, startup):
    frames = [event for event in events if event['event'] == 'frame'
              and bytes.fromhex(event['hex'])[4] == channel]
    directions = [bytes.fromhex(event['hex'])[2] for event in frames]
    if directions != [0xa1, 0xa0, 0xa1, 0xa0]:
        raise ValueError(f'CH{channel}: missing or unexpected on/off sequence')
    waits = [event for event in events if event['event'] == 'configured_wait' and event['channel'] == channel]
    if [event['duration'] for event in waits] != [startup, 2, startup]:
        raise ValueError(f'CH{channel}: configured waits differ')
    dispatched = frames[1:]
    if any(wait['seconds'] < write['seconds'] for wait, write in zip(waits, dispatched)):
        raise ValueError(f'CH{channel}: channel started a wait before writing its command')
    close = next(event['seconds'] for event in events if event['event'] == 'serial_close')
    end_times = [dispatched[1]['seconds'], dispatched[2]['seconds'], close]
    intervals = [round(end - write['seconds'], 3) for end, write in zip(end_times, dispatched)]
    # The raw Windows traces use a monotonic clock, rounded in the recording process.
    if any(actual + 0.03 < wait['duration'] for actual, wait in zip(intervals, waits)):
        raise ValueError(f'CH{channel}: observed interval shorter than configured wait: {intervals}')
    return intervals


if __name__ == '__main__':
    stage = Path(__file__).resolve().parent
    for name, startup in [('short', 1), ('normal', 10)]:
        cases = json.loads((stage / f'final-{name}.json').read_text(encoding='utf-8'))['cases']
        complete = [case for case in cases if case['entry'] in ('direct', 'qt')]
        assert {case['entry'] for case in complete} == {'direct', 'qt'} and len(complete) == 2
        for case in complete:
            for channel in (3, 9):
                times = inspect_channel(case['events'], channel, startup)
                print(f"{name} {case['entry']} CH{channel} measured intervals (seconds): {times}")

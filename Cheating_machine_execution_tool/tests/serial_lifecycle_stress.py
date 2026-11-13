"""Isolated real-Tk/real-transport simulation. Never opens physical serial ports.

Run with the repository CPython3.9 interpreter; the parent kills its own child
on timeout. Artifacts go only to the explicitly supplied temporary directory.
"""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback
import weakref
from contextlib import ExitStack
from unittest.mock import patch
from tk_test_windows import OffscreenTkWindows

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def child(seconds, cycles, rate, report, test_windows):
    import psutil
    import tkinter as tk
    from src.core.serial_transport import PySerialSession, SerialSessionManager
    from src.ui.serial_terminal import SerialTerminalWindow
    from line_check_assistant.pipeline_window import PipelineWindow
    from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
    from line_check_assistant.onu_registration_store import OnuRegistrationConfig

    report.parent.mkdir(parents=True, exist_ok=True)
    log_dir = report.parent / ('logs_' + report.stem)
    log_dir.mkdir(exist_ok=True)
    owner_thread = threading.get_ident()
    wrong_threads, releases, reads = [], [], []
    original_del = tk.Variable.__del__
    original_set, original_init = tk.Variable.set, tk.Variable.__init__
    def initialized(variable, *args, **kwargs):
        if threading.get_ident() != owner_thread:
            wrong_threads.append(('create', type(variable).__name__))
        original_init(variable, *args, **kwargs)
    def finalized(variable):
        releases.append(threading.get_ident())
        if threading.get_ident() != owner_thread:
            wrong_threads.append(('finalize', str(variable)))
        original_del(variable)
    def checked_get(original):
        def get(variable):
            if threading.get_ident() != owner_thread:
                wrong_threads.append(('get', str(variable)))
            return original(variable)
        return get
    def set_value(variable, value):
        if threading.get_ident() != owner_thread:
            wrong_threads.append(('set', str(variable)))
        return original_set(variable, value)

    stop = threading.Event()
    drivers = {}
    expected = {f'SIM{i}': {'count': 0, 'hash': hashlib.sha256()} for i in range(1, 9)}
    targets = [(f'vlan{100+i}', f'SIM{i}') for i in range(1, 9)]
    manager = SerialSessionManager()
    workers = []
    stats = {'seconds': seconds, 'ports': 8, 'rate_per_port': rate, 'block_bytes': 256,
             'cycles': 0, 'max_heartbeat_gap': 0, 'memory': [], 'max_subscriptions': 0,
             'display_drops': 0, 'max_mailbox': 0, 'max_pending_chars': 0, 'errors': []}
    retired = []
    process = psutil.Process()

    class Driver:
        def __init__(self, port):
            self.port = port
            self.queue = queue.SimpleQueue()
            self.lock = threading.Lock()
            self.paused = False
            self.closed = False
            self.offered = self.consumed = 0

        def offer(self):
            with self.lock:
                if self.paused or self.closed or self.offered-self.consumed > 128:
                    return
                state = expected[self.port]
                prefix = f"S{self.port}:{state['count']:08d}:"
                line = prefix + 'x' * (255-len(prefix))
                canonical = (line+'\n').encode('ascii')
                # Exercise split CRLF and tail buffers, with exactly known data.
                if state['count'] % 101 == 0:
                    wire = (line+'\r\n').encode('ascii')
                    blocks = (wire[:71], wire[71:-1], wire[-1:])
                else:
                    blocks = (canonical,)
                for block in blocks:
                    self.queue.put(block)
                self.offered += len(blocks)
                state['hash'].update(canonical)
                state['count'] += 1

        def read(self, _size):
            try:
                data = self.queue.get(timeout=.03)
            except queue.Empty:
                return b''
            if data:
                with self.lock:
                    self.consumed += 1
            return data

        def cancel_read(self):
            self.queue.put(b'')

        def close(self):
            self.closed = True

        def write(self, data):
            raise AssertionError('Simulation must never send serial commands')

        def pause_and_drained(self):
            if not self.lock.acquire(False):
                return False
            try:
                self.paused = True
                return self.offered == self.consumed
            finally:
                self.lock.release()

    def make_session(settings, log_path=None):
        driver = Driver(settings.port)
        drivers[settings.port] = driver
        return PySerialSession(settings, log_path, serial_factory=lambda **kwargs: driver)

    def produce(port):
        deadline = time.monotonic()
        while not stop.is_set():
            driver = drivers.get(port)
            if driver is not None:
                driver.offer()
            deadline += 1.0/rate
            stop.wait(max(0, deadline-time.monotonic()))
            if time.monotonic()-deadline > 1:
                deadline = time.monotonic()

    def collect():
        while not stop.wait(.025):
            garbage = []
            garbage.append(garbage)
            del garbage
            gc.collect()

    root = tk.Tk()
    root.withdraw()
    root._restore_module_window_size = lambda *_args: (880, 520)
    root._remember_module_window_size = lambda *_args: None
    root.channels = []
    def snapshot():
        reads.append(threading.get_ident())
        return SampleUpgradeSettings()
    root._current_sample_upgrade_settings = snapshot
    root.onu_registration_config = OnuRegistrationConfig()
    root._serial_log_directory = lambda: log_dir
    terminal = SerialTerminalWindow(root, manager, log_dir, log_dir/'state.json')
    terminal._restore_log_dir = lambda: log_dir
    start = time.monotonic()
    last_heartbeat = start
    next_cycle = start + max(.03, seconds/max(cycles, 1))
    stage = 'running'
    close_targets = []
    whole = False
    finished = False
    last_progress = start

    def progress():
        snapshot = dict(stats)
        snapshot.update(elapsed=round(time.monotonic()-start, 2),
                        total_records=sum(value['count'] for value in expected.values()))
        report.with_suffix('.progress.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')

    def heartbeat():
        nonlocal last_heartbeat
        now = time.monotonic()
        stats['max_heartbeat_gap'] = max(stats['max_heartbeat_gap'], now-last_heartbeat)
        last_heartbeat = now
        root.after(100, heartbeat)

    def tick():
        nonlocal stage, next_cycle, whole, close_targets, finished, last_progress
        now = time.monotonic()
        try:
            stats['max_mailbox'] = max(stats['max_mailbox'], terminal.events.qsize(), terminal.events.high_water)
            pending = sum(terminal._pending_char_counts.values())
            stats['max_pending_chars'] = max(stats['max_pending_chars'], pending)
            assert terminal.events.qsize() <= 2000
            assert all(size <= 64*1024 for size in terminal._pending_char_counts.values())
            if now-last_progress > 10:
                progress()
                last_progress = now
            if stage == 'running' and now >= next_cycle and stats['cycles'] < cycles:
                whole = stats['cycles'] % 8 == 7
                close_targets = list(targets) if whole else [targets[stats['cycles'] % 8]]
                stage = 'drain'
            if stage == 'running' and now-start >= seconds and stats['cycles'] >= cycles:
                close_targets = list(targets)
                stage = 'finish_drain'
            if stage in ('drain', 'finish_drain'):
                drained = [drivers[port].pause_and_drained() for _, port in close_targets]
                if all(drained):
                    if stage == 'finish_drain':
                        stop.set()
                        terminal.close()
                        stage = 'finishing'
                    else:
                        # Associated real Tk window while the other readers run.
                        with patch('line_check_assistant.pipeline_window.compute_all_subtask_statuses', return_value={}):
                            panel = PipelineWindow(root)
                        panel.window.withdraw()
                        panel._on_close()
                        retired.append(weakref.ref(panel))
                        panel = None
                        if whole:
                            terminal.close()
                        else:
                            terminal.close_tab(close_targets[0][0])
                        stage = 'closing'
            if stage == 'closing':
                terminal._process_closes()
                closed = terminal.window is None if whole else close_targets[0][0] not in terminal.tabs
                if closed:
                    terminal.show(close_targets)
                    terminal.window.withdraw()
                    assert terminal.open_all() == ()
                    stats['cycles'] += 1
                    subscriptions = sum(len(session._subscribers) for session in manager._sessions.values())
                    stats['max_subscriptions'] = max(stats['max_subscriptions'], subscriptions)
                    assert subscriptions == 8
                    assert len(manager._sessions) == 8
                    stats['memory'].append({'cycle': stats['cycles'], 'rss': process.memory_info().rss,
                                            'history': sum(len(session._history) for session in manager._sessions.values()),
                                            'callbacks': len(root.tk.call('after', 'info'))})
                    next_cycle = start + (stats['cycles']+1)*seconds/max(cycles, 1)
                    stage = 'running'
            if stage == 'finishing':
                terminal._process_closes()
                if terminal.window is None and not any(thread.is_alive() for thread in workers):
                    assert not manager._sessions
                    assert not manager._closing
                    stats['display_drops'] = terminal.events.dropped
                    finished = True
                    root.quit()
                    return
        except Exception:
            stats['errors'].append(traceback.format_exc())
            stop.set()
            root.quit()
            return
        root.after(10, tick)

    with ExitStack() as hooks:
        for cls in (tk.Variable, tk.StringVar, tk.BooleanVar):
            hooks.enter_context(patch.object(cls, 'get', checked_get(cls.get)))
        hooks.enter_context(patch.object(tk.Variable, '__init__', initialized))
        hooks.enter_context(patch.object(tk.Variable, '__del__', finalized))
        hooks.enter_context(patch.object(tk.Variable, 'set', set_value))
        hooks.enter_context(patch('src.core.serial_transport.PySerialSession', side_effect=make_session))
        terminal.show(targets)
        terminal.window.withdraw()
        assert terminal.open_all() == ()
        for port in expected:
            thread = threading.Thread(target=produce, args=(port,), name='sim-producer-'+port, daemon=True)
            workers.append(thread)
        workers.append(threading.Thread(target=collect, name='sim-gc-pressure', daemon=True))
        for thread in workers:
            thread.start()
        root.after(100, heartbeat)
        root.after(10, tick)
        root.mainloop()
        stop.set()
        if not finished:
            # Cleanup in the child only; parent timeout protects against hangs.
            manager.shutdown_all()
            terminal.close()
            for thread in workers:
                thread.join(2)
        root._serial_close_styles.clear()
        root.destroy()
        terminal = None
        gc.collect()
        stats['tk_finalizers'] = len(releases)
        stats['wrong_tk_threads'] = wrong_threads
        stats['snapshot_threads_correct'] = bool(reads) and all(value == owner_thread for value in reads)
        stats['retained_closed_pipeline_windows'] = sum(ref() is not None for ref in retired)
    stats['elapsed'] = round(time.monotonic()-start, 3)
    stats['total_records'] = sum(value['count'] for value in expected.values())
    stats['log_integrity'] = {}
    for index, (vlan, port) in enumerate(targets, 1):
        digest, count = hashlib.sha256(), 0
        paths = sorted(log_dir.glob(f'{vlan}_{port}_*.log'))
        for path in paths:
            with path.open(encoding='utf-8') as handle:
                for line in handle:
                    marker = ' RX '
                    if marker in line:
                        content = line.split(marker, 1)[1]
                        assert content.startswith(f'S{port}:{count:08d}:'), (port, count, content[:40])
                        digest.update(content.encode('ascii'))
                        count += 1
        stats['log_integrity'][port] = count == expected[port]['count'] and digest.hexdigest() == expected[port]['hash'].hexdigest()
    stats['remaining_sim_threads'] = [thread.name for thread in threading.enumerate()
                                      if thread.name.startswith(('serial-reader-', 'serial-close-', 'sim-'))]
    if len(stats['memory']) >= 40:
        samples = stats['memory']
        warm = [item['rss']-item['history'] for item in samples[20:40]]
        tail = [item['rss']-item['history'] for item in samples[-20:]]
        growth = sum(tail)/len(tail)-sum(warm)/len(warm)
        budget = max(10*1024*1024, sum(warm)/len(warm)*.05)
        stats['memory_growth_excluding_live_history'] = growth
        stats['memory_growth_budget'] = budget
        if growth > budget:
            stats['errors'].append('Memory growth after warmup exceeded budget')
    if stats['memory'] and max(item['callbacks'] for item in stats['memory']) > 6:
        stats['errors'].append('Unexpected persistent Tk timer growth')
    test_windows.assert_offscreen()
    stats['offscreen_windows_created'] = test_windows.created_windows
    stats['offscreen_window_events'] = test_windows.checked_events
    stats['offscreen_violations'] = list(test_windows.violations)
    stats['passed'] = (finished and not stats['errors'] and not wrong_threads
                       and stats['max_heartbeat_gap'] < 1 and all(stats['log_integrity'].values())
                       and not stats['remaining_sim_threads'] and stats['retained_closed_pipeline_windows'] == 0)
    report.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in stats.items() if key != 'memory'}, ensure_ascii=False), flush=True)
    return 0 if stats['passed'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--cycles', type=int, default=100)
    parser.add_argument('--rate', type=int, default=100)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    if args.child:
        with OffscreenTkWindows() as test_windows:
            return child(args.seconds, args.cycles, args.rate, args.report, test_windows)
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--child',
               '--seconds', str(args.seconds), '--cycles', str(args.cycles), '--rate', str(args.rate),
               '--report', str(args.report.resolve())]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=args.seconds+90)
    except subprocess.TimeoutExpired:
        print('FAIL: isolated simulation timed out; its child was killed and reaped')
        return 1
    print(result.stdout)
    print(result.stderr)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())

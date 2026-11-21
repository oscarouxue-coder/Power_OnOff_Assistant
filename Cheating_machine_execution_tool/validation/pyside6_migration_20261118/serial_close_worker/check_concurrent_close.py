"""Race individual and whole-workspace release with a queue-backed serial driver."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from qt_serial_fakes import QueueSerial
from src.core.host_resource_lock import HostResourceLock
from src.core.serial_transport import PySerialSession, SerialSessionManager
from src.models.serial_models import SerialSettings


def verify(directory, cycles):
    settings = SerialSettings('COM8055')
    manager = SerialSessionManager()
    closes = writes = 0
    with ThreadPoolExecutor(2) as workers:
        for index in range(cycles):
            driver = QueueSerial()
            session = PySerialSession(settings, directory / f'{index}.log', lambda **kwargs: driver)
            with patch('src.core.serial_transport.PySerialSession', return_value=session):
                manager.acquire_monitor('terminal', settings)
            driver.input.put(b'simulated RX before close\n')
            assert session.wait_for_all(('simulated RX',), 2, 0)
            barrier = threading.Barrier(2, timeout=3)

            def stop_monitor():
                barrier.wait()
                return manager.release('terminal', settings.port, wait=False)

            def close_workspace():
                barrier.wait()
                return manager.shutdown_all(wait=False)

            with patch.object(driver, 'close', wraps=driver.close) as close:
                monitor = workers.submit(stop_monitor)
                workspace = workers.submit(close_workspace)
                tickets = (monitor.result(4), *workspace.result(4))
                assert all(ticket.done.wait(4) and not ticket.error for ticket in tickets)
                close.assert_called_once_with()
                closes += close.call_count
            state = manager.diagnostic_state(settings.port)
            assert not any(state[key] for key in ('opened_in_program', 'closing_in_program', 'monitor_owners', 'control_owner'))
            assert driver.closed and not session._reader.is_alive() and session._log_handle is None
            assert 'simulated RX before close' in session.log_path.read_text('utf-8')
            with HostResourceLock(['serial:' + settings.port], reentrant=False):
                pass
            writes += len(driver.writes)
    assert not writes
    return dict(cycles=cycles, driver_closes=closes, serial_writes=writes,
                terminated_readers=cycles, complete_logs=cycles, released_port_checks=cycles)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='dutpilot-serial-close-race-') as temp:
        print(json.dumps(verify(Path(temp), 50), indent=2))

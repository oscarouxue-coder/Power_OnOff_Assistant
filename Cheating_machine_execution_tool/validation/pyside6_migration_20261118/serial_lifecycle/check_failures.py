"""Exercise serial ownership failures with the original manager and a fake driver."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from qt_serial_fakes import QueueSerial
from src.core.host_resource_lock import HostResourceBusy, HostResourceLock
from src.core.serial_transport import PySerialSession, SerialSessionManager
from src.models.serial_models import SerialSettings


class Recorder:
    def __init__(self):
        self.releases = []

    def acquire(self, *args):
        pass

    def release(self, owner, uncertain=False):
        self.releases.append(bool(uncertain))


def inspect(case, directory):
    port = {'log_open': 'COM7901', 'reader_start': 'COM7902', 'driver_close': 'COM7903'}[case]
    settings = SerialSettings(port)
    coordinator = Recorder()
    manager = SerialSessionManager(resource_coordinator=coordinator, project_id='fixture')
    driver = QueueSerial()
    session = None

    def session_factory(settings, log_path):
        nonlocal session
        session = PySerialSession(settings, log_path, serial_factory=lambda **kwargs: driver)
        return session

    log_path = directory / 'session.log'
    if case == 'log_open':
        log_path.mkdir()
    error = ''
    with ExitStack() as scope:
        scope.enter_context(patch('src.core.serial_transport.PySerialSession', side_effect=session_factory))
        if case == 'reader_start':
            scope.enter_context(patch.object(threading.Thread, 'start', side_effect=RuntimeError('fixture-start')))
        try:
            manager.acquire_monitor('terminal', settings, log_path)
            if case == 'driver_close':
                with patch.object(driver, 'close', side_effect=OSError('fixture-close')):
                    manager.release('terminal', port)
        except (OSError, RuntimeError) as exc:
            error = type(exc).__name__ + (': ' + str(exc) if case != 'log_open' else '')

    state = manager.diagnostic_state(port)
    try:
        lock = HostResourceLock(['serial:' + port], reentrant=False).acquire()
    except HostResourceBusy:
        busy = True
    else:
        busy = False
        lock.close()
    observation = dict(error=error, driver_closed=driver.closed, log_open=bool(session._log_handle and not session._log_handle.closed),
                       manager_closing=state['closing_in_program'], system_reserved=busy, releases=coordinator.releases, writes=len(driver.writes))
    # All handles in this process belong to the test driver. Dispose only its fixtures.
    driver.close()
    if session._log_handle and not session._log_handle.closed:
        session._log_handle.close()
    if session._host_resource_lock:
        session._host_resource_lock.close()
    return observation


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='dutpilot-serial-failure-') as temporary:
        root = Path(temporary)
        results = {}
        for case in ('log_open', 'reader_start', 'driver_close'):
            directory = root / case
            directory.mkdir()
            results[case] = inspect(case, directory)
        print(json.dumps(results, indent=2))

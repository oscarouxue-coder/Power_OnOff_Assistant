"""Replay a refused asynchronous close against a fake serial driver only."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from qt_serial_fakes import SerialHarness
from src.core.serial_transport import SerialSessionManager
from src.models.serial_models import SerialSettings


def inspect():
    settings = SerialSettings('COM7959')
    harness = SerialHarness()
    manager = SerialSessionManager()
    with tempfile.TemporaryDirectory() as folder, harness.patch:
        session = manager.acquire_control('fixture-owner', settings, Path(folder) / 'serial.log')
        try:
            with patch.object(threading.Thread, 'start', side_effect=RuntimeError('simulated close worker refusal')):
                try:
                    manager.release('fixture-owner', settings.port, wait=False)
                except RuntimeError as failure:
                    error = str(failure)
                else:
                    raise AssertionError('Expected the simulated worker refusal')
            state = manager.diagnostic_state(settings.port)
            tickets = manager.shutdown_all(wait=False)
            return dict(error=error, state_after_refusal=state,
                        shutdown_completed=[ticket.done.wait(2) for ticket in tickets],
                        driver_closed=harness.drivers[settings.port].closed,
                        driver_writes=len(harness.drivers[settings.port].writes))
        finally:
            session.close()  # Also release the fixture when replaying the original failure.


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))

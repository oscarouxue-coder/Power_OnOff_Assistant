"""Measure retained RX bytes and snapshot size using the original reader with a queue driver."""
import json
from pathlib import Path
import sys
import time
import tracemalloc


ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from qt_serial_fakes import SerialHarness
from src.core.serial_transport import SerialSessionManager
from src.models.serial_models import SerialSettings
from src.services.ai_serial_client import read_existing_serial


def measure():
    harness = SerialHarness().start()
    manager = SerialSessionManager()
    try:
        session = manager.acquire_monitor('simulated-long-log', SerialSettings('COM216'))
        driver = harness.drivers['COM216']
        packet = b'x' * 4096
        tracemalloc.start()
        samples = []
        for mb in range(1, 9):
            for _ in range(256):
                driver.input.put(packet)
            expected = mb * 1024 * 1024
            deadline = time.monotonic() + 8
            while session.cursor() < expected and time.monotonic() < deadline:
                time.sleep(.01)
            retained = session.cursor()
            snapshot = read_existing_serial(manager, 'COM216')
            if retained != expected or snapshot != 'x' * 65536:
                raise ValueError(f'Unexpected reader or snapshot size at {mb} MiB')
            samples.append(dict(received_bytes=expected, history_bytes=retained,
                                snapshot_chars=len(snapshot), python_traced_bytes=tracemalloc.get_traced_memory()[0]))
        if driver.writes:
            raise ValueError('Unexpected serial transmission')
        return dict(simulated_driver=True, ports=1, packet_bytes=len(packet), writes=len(driver.writes),
                    samples=samples)
    finally:
        manager.shutdown_all()
        harness.stop()
        tracemalloc.stop()


if __name__ == '__main__':
    print(json.dumps(measure(), indent=2))

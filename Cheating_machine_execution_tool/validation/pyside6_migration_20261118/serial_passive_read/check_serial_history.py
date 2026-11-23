from pathlib import Path
import hashlib
import json
import sys
import time
import psutil
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from qt_serial_fakes import QueueSerial
from src.core.serial_transport import PySerialSession
from src.models.serial_models import SerialSettings


def check():
    driver = QueueSerial()
    session = PySerialSession(SerialSettings('COM7839'), serial_factory=lambda **options: driver)
    block = (b'fixture-line\n' * 5500)[:65536]
    samples = []
    digest = hashlib.sha256()
    process = psutil.Process()
    session.open()
    try:
        for count in range(1, 129):
            driver.input.put(block)
            digest.update(block)
            if count not in (16, 32, 64, 128):
                continue
            expected = count * len(block)
            deadline = time.monotonic() + 10
            while session.cursor() < expected and time.monotonic() < deadline:
                time.sleep(.005)
            with session._condition:
                retained = len(session._history)
            history_digest = hashlib.sha256()
            for part in session.iter_rx_history():
                history_digest.update(part)
            samples.append(dict(received_bytes=expected, cursor=session.cursor(), resident_bytes=retained,
                                spilled_bytes=session._history_offset, process_rss_bytes=process.memory_info().rss,
                                raw_sha256_equal=(digest.digest() == history_digest.digest())))
            assert samples[-1]['cursor'] == expected
            assert samples[-1]['raw_sha256_equal']
            assert retained <= session.HISTORY_LIMIT
            assert session._history_offset + retained == expected
        assert session.peek_since(0).startswith('fixture-line')
        assert len(session.peek_since(-65536)) == 65536
        assert not driver.writes
    finally:
        session.close()
    return dict(samples=samples, writes=len(driver.writes), log_enabled=False, driver_closed=driver.closed)


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))

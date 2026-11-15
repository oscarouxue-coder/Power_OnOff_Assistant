"""Isolated append-only RX endurance test; never opens hardware or modifies app config.

Example: python tests/transport_history_stress.py --channels 8 --seconds 3600 --output <directory>
The parent imposes a wall-clock timeout on its own child only.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SimulatedDriver:
    def __init__(self, port):
        self.port = port
        self.queue = queue.Queue()
        self.cancelled = threading.Event()
        self.offered = self.received = 0
        self.raw_hash = hashlib.sha256()

    @property
    def in_waiting(self): return 0

    def read(self, _size):
        if self.cancelled.is_set(): return b""
        try: data = self.queue.get(timeout=.05)
        except queue.Empty: return b""
        self.received += len(data)
        self.raw_hash.update(data)
        return data

    def offer(self, data):
        self.offered += len(data)
        self.queue.put(data)

    def cancel_read(self): self.cancelled.set()
    def close(self): self.cancelled.set()


def payload(channel, sequence):
    bodies = ("netifd: Interface 'wan' is now up; DHCP lease acquired",
              "kernel: eth0 link up 1000Mbps full duplex; br-lan forwarding",
              "hostapd: wlan0: AP-STA-CONNECTED 02:00:00:00:00:01",
              "odhcp6c: router advertisement received; route lifetime 1800",
              "kernel: [12345.678901] PON ONU operational state observation")
    return (f"LCASEQ:{channel:02d}:{sequence:010d} " + bodies[sequence % len(bodies)] +
            " observation=" + "0123456789abcdef" * (2 + sequence % 12) + "\r\n").encode("ascii")


def child(args):
    from src.core.serial_transport import PySerialSession
    from src.models.serial_models import SerialSettings
    from src.core.transport_observation import HISTORY_REGISTRY, label_session
    from src.services.transport_history_monitor import TransportHistoryMonitor
    directory = args.output
    directory.mkdir(parents=True, exist_ok=True)
    captures = directory / "captures"; captures.mkdir(exist_ok=True)
    truth = directory / "input"; truth.mkdir(exist_ok=True)
    drivers, sessions, expected, source_files = {}, {}, {}, {}
    stop = threading.Event()
    errors = []
    for channel in range(1, args.channels+1):
        port = f"SIM{channel}"
        driver = SimulatedDriver(port)
        drivers[channel] = driver
        expected[channel] = {"records": 0, "raw_hash": hashlib.sha256(), "text_hash": hashlib.sha256()}
        source_files[channel] = (truth / f"channel_{channel:02d}.rx.bin").open("wb")
        session = PySerialSession(SerialSettings(port), captures / f"channel_{channel:02d}.log",
                                  serial_factory=lambda driver=driver, **_: driver)
        session.open()
        label_session(session, channel=channel, vlan=f"sim-channel-{channel}")
        sessions[channel] = session
    session = None
    monitor = TransportHistoryMonitor(directory, lambda message: print(message, flush=True))
    samples = []
    def sample(stage):
        row = monitor.sample()
        row["stage"] = stage
        for item in row["sessions"]:
            channel = item.get("channel")
            if channel in drivers:
                item.update(driver_received_bytes=drivers[channel].received,
                            source_offered_bytes=drivers[channel].offered)
        samples.append(row)
        with (directory / "samples.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+"\n")
        progress = {"channels": args.channels, "elapsed_seconds": round(row["elapsed_seconds"], 2),
                    "rss_bytes": row["rss_bytes"], "history_bytes": sum(r.get("history_bytes", 0) for r in row["sessions"]),
                    "pending_rx_chars": sum(r.get("pending_rx_chars", 0) for r in row["sessions"]),
                    "driver_received_bytes": sum(d.received for d in drivers.values()), "stage": stage}
        (directory / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        print("STRESS_PROGRESS " + json.dumps(progress), flush=True)
    sample("started")
    start = time.monotonic()
    def producer():
        tick = 0
        try:
            while not stop.is_set():
                elapsed = time.monotonic()-start
                if elapsed >= args.seconds: break
                for channel, driver in drivers.items():
                    phase = elapsed + channel*.17
                    if phase % 300 >= 290: continue  # Ten-second idle intervals.
                    count = 10 if phase % 60 < 2 else 1  # 100/s bursts, otherwise 10/s.
                    for _ in range(count):
                        state = expected[channel]
                        data = payload(channel, state["records"])
                        state["records"] += 1
                        state["raw_hash"].update(data)
                        state["text_hash"].update(data.replace(b"\r\n", b"\n"))
                        source_files[channel].write(data)
                        # Split selected CRLF pairs across reads; no test-only logger.
                        if state["records"] % 17 == 0:
                            driver.offer(data[:-1]); driver.offer(data[-1:])
                        else: driver.offer(data)
                tick += 1
                stop.wait(max(0, start+tick*.1-time.monotonic()))
        except Exception:
            errors.append(traceback.format_exc()); stop.set()
    producer_thread = threading.Thread(target=producer, name="sim-producer")
    producer_thread.start()
    next_sample = start + args.interval
    try:
        while producer_thread.is_alive():
            producer_thread.join(timeout=min(.2, max(.01, next_sample-time.monotonic())))
            if time.monotonic() >= next_sample:
                sample("running"); next_sample += args.interval
    finally:
        stop.set(); producer_thread.join(5)
        for handle in source_files.values(): handle.close()
    deadline = time.monotonic()+30
    while any(d.received != d.offered for d in drivers.values()) and time.monotonic() < deadline:
        time.sleep(.02)
    sample("before_close")
    results = []
    references = [weakref.ref(s) for s in sessions.values()]
    for channel, session in sessions.items():
        session.close()
        driver, state = drivers[channel], expected[channel]
        memory_hash = hashlib.sha256(session._history).hexdigest()
        actual_hash = hashlib.sha256(); count = missing = duplicates = 0
        previous = -1
        path = captures / f"channel_{channel:02d}.log"
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if " RX " not in line: continue
                content = line.split(" RX ", 1)[1]
                try: sequence = int(content.split(" ", 1)[0].rsplit(":", 1)[1])
                except (ValueError, IndexError): errors.append(f"channel {channel}: malformed record"); continue
                if sequence <= previous: duplicates += 1
                elif sequence > previous+1: missing += sequence-previous-1
                previous = sequence; count += 1
                actual_hash.update(content.encode("ascii"))
        missing += max(0, state["records"]-previous-1)
        results.append({"channel": channel, "records_generated": state["records"], "records_on_disk": count,
                        "source_bytes": driver.offered, "driver_received_bytes": driver.received,
                        "memory_history_bytes": len(session._history), "disk_file_bytes": path.stat().st_size,
                        "pending_rx_chars_after_close": len(session._rx_log_line_buffer),
                        "source_to_receive_bytes_equal": driver.offered == driver.received,
                        "source_to_memory_sha256_equal": state["raw_hash"].hexdigest() == memory_hash,
                        "source_to_driver_sha256_equal": state["raw_hash"].hexdigest() == driver.raw_hash.hexdigest(),
                        "normalized_text_sha256_equal": state["text_hash"].hexdigest() == actual_hash.hexdigest(),
                        "missing_records": missing, "duplicate_or_reordered_records": duplicates,
                        "raw_byte_fidelity": False, "raw_byte_fidelity_note": "Application log is timestamped normalized text, not a raw-byte archive; input/*.rx.bin is the independent test oracle only.",
                        "log_handle_closed": session._log_handle is None,
                        "reader_stopped": not session._reader.is_alive()})
    session = None
    sessions.clear(); gc.collect()
    sample("after_release")
    time.sleep(.1)
    remaining = [t.name for t in threading.enumerate() if t.name.startswith(("serial-reader-", "serial-close-", "sim-"))]
    retained = sum(ref() is not None for ref in references)
    elapsed = time.monotonic()-start
    passed = (not errors and elapsed >= args.seconds and not remaining and retained == 0
              and all(r["source_to_receive_bytes_equal"] and r["source_to_memory_sha256_equal"]
                      and r["source_to_driver_sha256_equal"] and r["normalized_text_sha256_equal"]
                      and not r["missing_records"] and not r["duplicate_or_reordered_records"]
                      and r["reader_stopped"] and r["log_handle_closed"] for r in results))
    report = {"channels": args.channels, "requested_seconds": args.seconds, "elapsed_seconds": elapsed,
              "sample_interval_seconds": args.interval, "profile": "deterministic OpenWrt-style ASCII; 10 lines/s baseline, 100 lines/s 2s/min bursts, 10s/5min idle; CRLF split across reads",
              "rows": results, "errors": errors, "retained_sessions": retained, "remaining_threads": remaining,
              "text_and_lifecycle_checks_passed": passed, "raw_byte_fidelity_accepted": False,
              "note": "No physical DUT or model. No 72h/168h acceptance. Existing byte-fidelity limitations are separate from ASCII text sequence completeness."}
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STRESS_RESULT "+json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", type=int, choices=(8, 16), required=True)
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.seconds <= 0 or args.interval <= 0: parser.error("duration and interval must be positive")
    if args.child: return child(args)
    args.output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", "--channels", str(args.channels),
               "--seconds", str(args.seconds), "--interval", str(args.interval), "--output", str(args.output)]
    with (args.output / "console.txt").open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=args.seconds+120)
        except subprocess.TimeoutExpired:
            (args.output / "timeout.json").write_text(json.dumps({"timed_out": True}), encoding="utf-8")
            return 1
    return result.returncode


if __name__ == "__main__": sys.exit(main())

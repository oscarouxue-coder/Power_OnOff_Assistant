"""Low-frequency monitoring, independent of AI and test result decisions."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import threading
import time

import psutil
from src.core.transport_observation import HISTORY_REGISTRY


class TransportHistoryMonitor:
    def __init__(self, directory, emit, interval=60, registry=None):
        self.directory = Path(directory)
        self.emit = emit  # A data queue sink, never a Tk callback.
        self.interval = interval
        self.registry = registry or HISTORY_REGISTRY
        self.stop = threading.Event()
        self.thread = None
        self.process = psutil.Process()
        self.started = time.monotonic()
        self.previous = {}
        self.closed_received = {}
        self.alerted = set()
        self.path = self.directory / ("transport_history_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jsonl")

    def sample(self):
        now = time.monotonic()
        report = self.registry.collect()
        current_ids = set()
        for row in report["sessions"]:
            identifier = row["session_id"]
            current_ids.add(identifier)
            previous = self.previous.get(identifier)
            row["history_bytes_per_second"] = None
            if row.get("sample_status") == "ok":
                if previous:
                    elapsed = now - previous[0]
                    row["history_bytes_per_second"] = (row["history_bytes"] - previous[1]) / elapsed if elapsed > 0 else None
                    if (row["received_bytes"] > previous[1] and row.get("log_file_bytes") == previous[2]
                            and row["pending_rx_chars"] == 0 and not row["closed"] and row.get("log_path")):
                        row["write_status"] = "possible_write_stall"
                self.previous[identifier] = (now, row["history_bytes"], row.get("log_file_bytes"))
                if row.get("final"):
                    key = row["protocol"] + ":" + row["endpoint"]
                    self.closed_received[key] = self.closed_received.get(key, 0) + row["received_bytes"]
                    self.previous.pop(identifier, None)
            status = row.get("write_status")
            if status in ("reader_stopped_unexpectedly", "stat_error", "possible_write_stall", "not_configured", "not_open"):
                alert = identifier, status
                if alert not in self.alerted:
                    self.alerted.add(alert)
                    self.emit(f"[资源监测] 告警：{row['protocol']} {row['endpoint']}，状态={status}；不能确认日志完整落盘")
        self.previous = {k: v for k, v in self.previous.items() if k in current_ids}
        self.alerted = {a for a in self.alerted if a[0] in current_ids}
        try:
            disk_free = shutil.disk_usage(self.directory if self.directory.exists() else self.directory.parent).free
        except OSError:
            disk_free = None
        children = []
        try:
            for child in self.process.children(recursive=True):
                try:
                    children.append({"pid": child.pid, "rss_bytes": child.memory_info().rss, "history_status": "not_instrumented"})
                except psutil.Error:
                    children.append({"pid": child.pid, "rss_bytes": None, "history_status": "unavailable"})
        except psutil.Error:
            pass
        report.update(timestamp=datetime.now().astimezone().isoformat(), elapsed_seconds=now-self.started,
                      pid=self.process.pid, rss_bytes=self.process.memory_info().rss,
                      disk_free_bytes=disk_free, children=children, closed_received_bytes=dict(self.closed_received),
                      note="Read-only observations; receive count is derived from append-only memory history. File size includes text metadata; flush success and byte fidelity are not proven.")
        return report

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._loop, name="transport-history-monitor", daemon=True)
        try:
            self.thread.start()
        except Exception as exc:
            self.thread = None
            self.emit("[资源监测] 无法启动采样线程：" + type(exc).__name__ + "；原程序继续")

    def _loop(self):
        self.emit(f"[资源监测] 开始：每{self.interval}秒只读采样；记录={self.path}")
        failed = False
        while True:
            final = self.stop.is_set()
            try:
                report = self.sample()
                report["final_sample"] = final
                self.directory.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(report, ensure_ascii=False) + "\n")
                if failed:
                    self.emit("[资源监测] 监测记录已恢复；此前缺口保留，原测试继续")
                failed = False
            except Exception as exc:
                if not failed:
                    self.emit("[资源监测] 采样或记录失败：" + type(exc).__name__ + "；原测试继续")
                failed = True
            if final:
                break
            self.stop.wait(self.interval)
        self.emit("[资源监测] 已停止采样，未清理原始日志或历史缓冲")

    def begin_close(self):
        self.stop.set()

    @property
    def idle(self):
        return self.thread is None or not self.thread.is_alive()

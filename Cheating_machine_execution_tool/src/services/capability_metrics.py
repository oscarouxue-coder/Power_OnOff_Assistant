"""Bounded per-turn counters plus append-only JSONL observations, without prompt contents."""
import json
import threading
import time
from pathlib import Path


class CapabilityMetrics:
    def __init__(self, directory=None, clock=time.monotonic, emit=lambda line: None):
        self.path = Path(directory) / "capability_metrics.jsonl" if directory else None
        self.clock, self.lock = clock, threading.RLock()
        self.turns = {}
        self.emit, self.last_error = emit, ""

    def begin(self, key, *, only_if_missing=False):
        with self.lock:
            if only_if_missing and key in self.turns:
                return
            self.turns[key] = dict(start=self.clock(), first_response_seconds=None,
                                   model_calls=0, tool_calls=0, tool_failures=0)

    def model(self, key):
        with self.lock:
            if key in self.turns:
                self.turns[key]["model_calls"] += 1

    def response(self, key):
        with self.lock:
            item = self.turns.get(key)
            if item and item["first_response_seconds"] is None:
                item["first_response_seconds"] = self.clock() - item["start"]

    def tool(self, key, failed=False):
        with self.lock:
            if key in self.turns:
                self.turns[key]["tool_calls"] += 1
                self.turns[key]["tool_failures"] += bool(failed)

    def finish(self, key):
        with self.lock:
            item = self.turns.pop(key, None)
            if item is None:
                return None
            result = dict(item, total_seconds=self.clock() - item["start"], kind="agent_turn")
            result.pop("start")
            result["tool_failure_rate"] = result["tool_failures"] / max(1, result["tool_calls"])
            self.record(result)
            return result

    def record(self, record):
        if self.path:
            with self.lock:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                except OSError as exc:
                    if not self.last_error:
                        self.emit("[业务指标] 写入失败，业务结果保持；指标不完整：" + str(exc))
                    self.last_error = str(exc)

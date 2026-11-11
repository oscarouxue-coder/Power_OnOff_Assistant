"""挂测IPC旁路证据缓存；无网络、无设备控制、无文件写入。"""
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
import json
import re
import threading

from src.models.ai_conversation import DiagnosticEvidence


class AiEvidenceContext:
    def __init__(self):
        self.lock = threading.RLock()
        self.run_id = "manual"
        self.records = defaultdict(deque)
        self.sizes = defaultdict(int)
        self.attempts = {}
        self.files = {}
        self.settings = {}

    def observe(self, message):
        with self.lock:
            kind = message.get("type")
            if kind == "diagnostic_start":
                run_id = str(message["run_id"])
                if self.run_id != run_id:
                    self.run_id = run_id
                    self.records.clear()
                    self.sizes.clear()
                    self.files.clear()
                    self.attempts.clear()
                    self.settings.clear()
                return
            if message.get("run_id", self.run_id) != self.run_id:
                return
            channel = int(message.get("channel") or 0)
            text = str(message.get("message") or message.get("detail") or "")
            if not channel:
                match = re.search(r"通道\s*[【]?\s*(\d+)", text)
                channel = int(match[1]) if match else 0
            if not channel:
                return
            attempt = int(message.get("attempt") or 0)
            if kind == "channel_started":
                self.attempts[channel] = attempt
            if attempt != self.attempts.get(channel, attempt):
                return
            if kind in ("wifi_log_created", "result_log_created"):
                path = Path(str(message["path"]))
                # 路径只由本地业务事件提供，不接受模型提供的任意路径。
                self.files[channel, attempt, kind] = path
            if kind == "diagnostic_settings":
                self.settings[channel] = dict(message.get("settings", {}))
            if kind not in ("log", "stage") or text:
                data = json.dumps(dict(message), ensure_ascii=False, default=str)
                item = asdict(DiagnosticEvidence(kind or "event", data[-32768:], self.run_id, channel))
                size = len(item["text"].encode("utf-8"))
                self.records[channel].append(item)
                self.sizes[channel] += size
                while self.sizes[channel] > 2 * 1024 * 1024 or len(self.records[channel]) > 2000:
                    removed = self.records[channel].popleft()
                    self.sizes[channel] -= len(removed["text"].encode("utf-8"))

    def snapshot(self, run_id, channel):
        with self.lock:
            if run_id != self.run_id:
                return []  # 旧会话使用自己的持久化证据，绝不读取新批次。
            records = list(self.records[channel])
            paths = [(key, value) for key, value in self.files.items() if key[0] == channel]
        for (_, attempt, source), path in paths:
            try:
                # 有界尾读；不扫描其它历史文件，不改写正在写入的日志。
                with path.open("rb") as stream:
                    stream.seek(0, 2)
                    start = max(0, stream.tell() - 65536)
                    stream.seek(start)
                    raw = stream.read(65536)
                    if start and b"\n" in raw:
                        raw = raw.split(b"\n", 1)[1]  # 不把截断的半行/半个UTF8字符当成原始乱码。
                    text = raw.decode("utf-8", "replace")
                records.append(asdict(DiagnosticEvidence(
                    f"{source} / 续跑{attempt} / {path}", text, run_id, channel,
                    "测试日志原文（最多64KiB尾部）；此时间为读取时间，故障时间以行内记录为准")))
            except OSError as exc:
                records.append(asdict(DiagnosticEvidence(source, "日志不可读取：" + type(exc).__name__, run_id, channel)))
        return records

    def target_settings(self, run_id, channel):
        with self.lock:
            return dict(self.settings.get(channel, {})) if run_id == self.run_id else {}

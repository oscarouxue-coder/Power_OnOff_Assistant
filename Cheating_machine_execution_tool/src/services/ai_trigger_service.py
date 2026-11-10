"""确定性触发及有限上下文；与模型隔离，不改变测试结果。"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict
import threading
import time

from src.models.ai_diagnostics import DebugTriggerPolicy, TriggerDecision


class DiagnosticTrigger:
    def __init__(self, policy=None, clock=time.monotonic):
        self.policy = policy or DebugTriggerPolicy()
        self.clock = clock
        self.enabled = False
        self.run_id = ""
        self.lock = threading.RLock()
        self.buffers = defaultdict(deque)
        self.sizes = defaultdict(int)
        self.states = {}

    def start(self, run_id):
        with self.lock:
            self.run_id = run_id
            self.states.clear()
            self.buffers.clear()
            self.sizes.clear()

    def append(self, channel, text):
        now = self.clock()
        data = str(text).encode("utf-8")[-2 * 1024 * 1024:].decode("utf-8", "ignore")
        with self.lock:
            size = len(data.encode("utf-8"))
            self.buffers[channel].append((now, data, size))
            self.sizes[channel] += size
            self._trim(channel, now)

    def _trim(self, channel, now):
        items = self.buffers[channel]
        while items and (now - items[0][0] > 120 or self.sizes[channel] > 2 * 1024 * 1024):
            _, _, size = items.popleft()
            self.sizes[channel] -= size

    def context(self, channel):
        with self.lock:
            self._trim(channel, self.clock())
            return "\n".join(item[1] for item in self.buffers[channel])

    def reset_channel(self, channel):
        with self.lock:
            for key in tuple(self.states):
                if key[0] == channel:
                    self.states.pop(key, None)

    def observe(self, event):
        with self.lock:
            policy = self.policy
            if (not self.enabled or event.run_id != self.run_id or not event.trusted
                    or event.channel not in policy.channels or event.feature not in policy.features):
                return None
            key = event.channel, event.stage, event.band
            # 一个阶段的不同轮次/续跑尝试不能串计数。
            state = self.states.get(key)
            if state is None or state["cycle"] != event.cycle:
                state = {"cycle": event.cycle, "seen": set(), "count": 0,
                         "last": float("-inf"), "level": "", "final": False}
                self.states[key] = state
            if event.status == "success":
                self.states.pop(key, None)
                return None
            if event.status in ("cancelled", "stopped", "waiting", "skipped", "info", "running"):
                return None
            if event.status not in ("retry", "error", "failed"):
                return None
            identity = event.attempt or event.detail
            distinct = identity not in state["seen"]
            if distinct:
                state["seen"].add(identity)
                state["count"] += 1
            final = event.status == "failed"
            if not distinct and not final:
                return None
            custom = (bool(event.error_code) and event.error_code in policy.error_codes) or any(
                word and word.casefold() in event.detail.casefold() for word in policy.keywords)
            if not final and not custom and state["count"] < policy.threshold:
                return None
            deep = policy.deep_enabled and (final or state["count"] >= policy.threshold + 1)
            level = "deep" if deep else "light"
            now = self.clock()
            upgrade = (final and not state["final"]) or (bool(state["level"]) and level == "deep" and state["level"] != "deep")
            if final and state["final"]:
                return None
            if now - state["last"] < policy.cooldown and not upgrade:
                return None
            state.update(last=now, level=level, final=state["final"] or final)
            reason = "业务最终失败" if final else ("自定义条件" if custom else f"连续{state['count']}次异常")
            return TriggerDecision(event, level, reason)

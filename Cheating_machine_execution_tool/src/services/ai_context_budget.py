"""持续对话的容量发现及完整协议组预算；不执行设备工具。"""
from dataclasses import dataclass
import json
import math


@dataclass(frozen=True)
class ContextCapacity:
    tokens: int = 0
    source: str = "未知容量：最近50轮 / 100000字符"


def context_capacity(store, profile):
    if profile.context_tokens:
        return ContextCapacity(profile.context_tokens, "手动填写")
    cached = store.model_context(profile)
    if type(cached) is int and cached > 0:
        return ContextCapacity(cached, "模型接口（缓存）")
    return ContextCapacity()


def refresh_model_context(store, client, stop=None):
    models = client.model_details(stop)
    store.cache_model_contexts(client.profile, models)
    return models


class ContextBudgetError(RuntimeError):
    pass


class ConversationBudget:
    """current 始终完整留存；仅移除之前的整组，避免重复执行工具。"""
    def __init__(self, groups, prefix, current, capacity, max_output, dumps):
        self.total = len(groups)
        self.groups = list(groups)
        self.prefix, self.current = prefix, current
        self.capacity, self.max_output, self.dumps = capacity, max_output, dumps
        if not capacity.tokens:
            selected, size = [], 0
            for group in reversed(self.groups):
                length = len(dumps(group))
                if len(selected) >= 50 or size + length > 100000:
                    break
                selected.append(group)
                size += length
            self.groups = list(reversed(selected))

    @property
    def skipped(self):
        return self.total - len(self.groups)

    def history(self):
        # 本轮首条为程序生成的材料封装，裁剪后更新省略轮数。
        if self.current:
            first = self.current[0]
            if first.get("role") == "user":
                try:
                    info = json.loads(first["content"])
                    if isinstance(info, dict) and "omitted_turns" in info:
                        info["omitted_turns"] = self.skipped
                        first["content"] = self.dumps(info)
                except (ValueError, TypeError, KeyError):
                    pass
        return self.prefix + [item for group in self.groups for item in group] + self.current

    def fit(self, client, tools):
        while True:
            history = self.history()
            # 含协议封装、工具定义及所有文本；字节估算比字符计数更保守。
            estimated = len(self.dumps(client.request_payload(history, tools)).encode("utf-8"))
            limit = self.capacity.tokens
            if not limit or estimated + self.max_output + math.ceil(limit * .05) <= limit:
                return history, estimated
            if not self.groups:
                raise ContextBudgetError(
                    f"上下文预算不足：估算输入{estimated} Token，输出预留{self.max_output} Token，"
                    f"容量{limit} Token（另留5%余量）；当前问题及本轮工具链未截断。"
                    "请调整容量、缩短材料或新建会话。")
            self.groups.pop(0)

    def halve_history(self):
        if not self.groups:
            return False
        del self.groups[:math.ceil(len(self.groups) / 2)]
        return True

"""最近模型请求的上下文用量快照；不累计账单、不修改预算。"""
from math import ceil

from src.models.ai_conversation import timestamp
from src.services.ai_store import profile_fingerprint


def usage_identity(profile, capacity):
    return {"profile": profile_fingerprint(profile), "capacity": capacity.tokens,
            "source": capacity.source, "max_output": profile.max_output}


def request_usage(profile, capacity, estimated, skipped, previous=None):
    previous = previous or {}
    valid = ({k: v for k, v in previous.items() if k != "previous_valid"}
             if previous.get("basis") == "reply" else previous.get("previous_valid"))
    return {"identity": usage_identity(profile, capacity), "state": "requesting", "basis": "input",
            "source": "estimate", "input_tokens": estimated, "output_tokens": None,
            "total_tokens": estimated, "skipped": skipped, "updated": timestamp(),
            "previous_valid": valid}


def reply_usage(snapshot, usage, protocol, output, dumps):
    keys = ("input_tokens", "output_tokens") if protocol == "responses" else ("prompt_tokens", "completion_tokens")
    values = [usage.get(key) for key in keys] if isinstance(usage, dict) else []
    exact = len(values) == 2 and all(type(value) is int and value >= 0 for value in values)
    incoming, outgoing = values if exact else (
        snapshot["input_tokens"], len(dumps(output).encode("utf-8")))
    result = {k: v for k, v in snapshot.items() if k != "previous_valid"}
    result.update(state="completed", basis="reply", source="api" if exact else "estimate",
                  input_tokens=incoming, output_tokens=outgoing, total_tokens=incoming + outgoing,
                  updated=timestamp())
    return result


def failed_usage(snapshot, state):
    snapshot = snapshot or {}
    result = dict(snapshot.get("previous_valid") or snapshot)
    result.pop("previous_valid", None)
    result.update(state=state, status_updated=timestamp())
    return result


def context_usage_status(store, session):
    """只读取配置及缓存；UI刷新不出网，不重新估算历史或草稿。"""
    from src.models.ai_diagnostics import ProviderProfile
    from src.services.ai_context_budget import context_capacity

    frozen = ProviderProfile(**session["profile"])
    current = next((p for p in store.profiles() if p.id == frozen.id), None)
    profile = current or frozen
    capacity = context_capacity(store, profile)
    snapshot = session.get("context_usage") or {}
    identity = usage_identity(profile, capacity)
    stale = bool(snapshot.get("identity") and (snapshot["identity"] != identity or current is None))
    return {"capacity": capacity.tokens, "source": capacity.source, "max_output": profile.max_output,
            "margin": ceil(capacity.tokens * .05), "snapshot": snapshot, "stale": stale}

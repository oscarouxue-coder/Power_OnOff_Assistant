"""会话范围与显示投影；旧记录默认设备会话。"""
def session_scope(session):
    return session.get("scope", "device")


def target_channel(session):
    return (session.get("target") or {}).get("channel")


def target_label(session):
    if session_scope(session) == "batch":
        return "通道" + "、".join(str(t["channel"]) for t in session.get("batch_targets", [])) + "（批量）"
    channel = target_channel(session)
    return f"通道{channel}" if channel is not None else (
        "本机电脑" if session_scope(session) == "pc" else "普通问答")


def source_identity(source):
    source = source or {}
    base = tuple(source.get(key, "local" if key == "kind" else "")
                 for key in ("kind", "robot", "corp", "chat_type", "group", "sender"))
    if source.get("gateway_instance_id"):
        return base + ("gateway", source["gateway_instance_id"], source.get("gateway_run_id", ""))
    return base


def business_source_identity(source):
    identity = source_identity(source)
    return identity[:-1] if (source or {}).get("gateway_instance_id") else identity

"""Versioned relay contracts. No authority, grant, device commands or model-created IDs."""
from dataclasses import dataclass, asdict
import hashlib
import hmac
import json
import math
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def signature(secret, value):
    return hmac.new(secret.encode(), canonical(value).encode(), hashlib.sha256).hexdigest()


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("实例/请求标识无效")
    return value


@dataclass(frozen=True)
class RemotePrincipal:
    platform: str
    robot: str
    corp: str
    chat_type: str
    chat: str
    member: str

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("可信来源字段无效")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 512 for v in value.values()):
            raise ValueError("可信来源不完整")
        if value["platform"] not in ("dingtalk", "feishu") or value["chat_type"] not in ("group", "p2p"):
            raise ValueError("不支持的来源")
        if value["platform"] == "dingtalk" and value["chat_type"] != "group":
            raise ValueError("钉钉当前仅接收群聊")
        return cls(**value)

    @property
    def key(self):
        return digest(asdict(self))

    def source(self, instance_id, run_id):
        return dict(kind=self.platform, robot=self.robot, corp=self.corp, chat_type=self.chat_type,
                    group=self.chat, sender=self.member, nickname=self.member,
                    gateway_instance_id=instance_id, gateway_run_id=run_id)


def allows(scopes, principal):
    """Scopes are local operator configuration, never supplied in an incoming request."""
    principal = RemotePrincipal.parse(principal) if isinstance(principal, dict) else principal
    for scope in scopes:
        if all(scope.get(k) == getattr(principal, k) for k in ("platform", "robot", "corp", "chat_type", "chat")):
            members = scope.get("members", [])
            if principal.member in members or members == ["*"]:
                return True
    return False


def validate_request(value, instance_id, run_id, now):
    required = {"version", "request_id", "message_id", "instance_id", "run_id", "principal", "text", "created", "expires"}
    if not isinstance(value, dict) or set(value) != required or value["version"] != 1:
        raise ValueError("请求协议/字段无效，不接受授权声明")
    identifier(value["request_id"])
    if value["instance_id"] != instance_id or value["run_id"] != run_id:
        raise ValueError("请求不属于当前实例启动")
    for key in ("message_id", "text"):
        if not isinstance(value[key], str) or not 1 <= len(value[key]) <= (32768 if key == "text" else 512):
            raise ValueError("请求正文或消息标识无效")
    for key in ("created", "expires"):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]):
            raise ValueError("时间字段无效")
    if not value["created"] - 5 <= now <= value["expires"] or not 0 < value["expires"] - value["created"] <= 60:
        raise ValueError("请求已经过期或时间无效")
    RemotePrincipal.parse(value["principal"])
    return value


class SignedChannel:
    """Per-connection nonce, directional MAC and exact sequence prevent replay/reflection."""
    def __init__(self, secret, nonce, role):
        self.secret, self.nonce, self.role = secret, nonce, role
        self.sent = self.received = 0

    def pack(self, payload):
        self.sent += 1
        value = dict(nonce=self.nonce, sender=self.role, sequence=self.sent, payload=payload)
        return dict(value, mac=signature(self.secret, value))

    def unpack(self, value):
        if not isinstance(value, dict) or set(value) != {"nonce", "sender", "sequence", "payload", "mac"}:
            raise ValueError("消息认证字段无效")
        body = {k: value[k] for k in ("nonce", "sender", "sequence", "payload")}
        other = "gateway" if self.role == "instance" else "instance"
        if (body["nonce"] != self.nonce or body["sender"] != other or type(body["sequence"]) is not int
                or body["sequence"] != self.received + 1 or not isinstance(value["mac"], str)
                or not hmac.compare_digest(signature(self.secret, body), value["mac"])):
            raise ValueError("消息签名/顺序无效")
        self.received += 1
        return body["payload"]

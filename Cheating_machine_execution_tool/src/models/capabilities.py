"""Data-only capability contracts. Authority is supplied by the host, never model arguments."""
from dataclasses import dataclass, field
from typing import Callable, Tuple
import hashlib
import json
import math


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class CapabilityError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def result(self):
        return dict(status="blocked", code=self.code, error=str(self), **self.details)


@dataclass(frozen=True)
class CapabilityAuthority:
    principal: str
    session_id: str
    operation_id: str
    channels: Tuple[int, ...]
    source: str = "local"
    mode: str = "ask"
    grant_id: str = ""
    approved: bool = False
    # Optional host-owned endpoints; never accepted from model/tool arguments.
    target_endpoints: Tuple[Tuple[int, str, str, int], ...] = ()

    def check(self, channels=(), risk="read"):
        if not self.principal or not self.session_id or not self.operation_id:
            raise CapabilityError("identity_required", "缺少可信任务身份")
        if self.source not in ("local", "dingtalk", "feishu", "gui"):
            raise CapabilityError("source_forbidden", "当前来源不允许启动业务任务")
        if any(type(c) is not int or c not in self.channels for c in channels):
            raise CapabilityError("target_out_of_scope", "目标超出本次已授权设备范围")
        if risk != "read" and not (self.approved or self.mode == "full_access" and self.grant_id):
            raise CapabilityError("approval_required", "本次业务操作需要按当前权限批准")


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    name: str
    description: str
    input_schema: dict
    handler: Callable
    risk: str = "read"
    execution_mode: str = "sync"
    resource_requirements: Tuple[str, ...] = ()
    output_schema: dict = field(default_factory=lambda: {"type": "object"})
    version: str = "1"
    status: str = "implemented_unaccepted"
    cancellation: str = "none"
    resource_scope: Callable = None
    sources: Tuple[str, ...] = ("local", "dingtalk", "feishu", "gui")

    def public(self):
        return {key: getattr(self, key) for key in (
            "capability_id", "name", "description", "input_schema", "output_schema", "risk",
            "execution_mode", "resource_requirements", "version", "status", "cancellation", "sources")}


def validate_schema(value, schema, path="arguments"):
    """The deliberately small schema subset used by registered, typed adapters."""
    kind = schema.get("type")
    valid = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
             "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
             "boolean": lambda: type(value) is bool, "number": lambda: type(value) in (int, float)}
    if kind not in valid or not valid[kind]():
        raise CapabilityError("invalid_parameters", path + " 类型不正确")
    if "enum" in schema and value not in schema["enum"]:
        raise CapabilityError("invalid_parameters", path + " 不是支持的选项")
    if kind == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", ())) - set(value):
            raise CapabilityError("invalid_parameters", path + " 缺少必填参数")
        if schema.get("additionalProperties", False) is False and set(value) - set(properties):
            raise CapabilityError("invalid_parameters", path + " 包含未开放参数")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], path + "." + key)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            raise CapabilityError("invalid_parameters", path + " 数量超出限制")
        if schema.get("uniqueItems") and len({fingerprint(v) for v in value}) != len(value):
            raise CapabilityError("invalid_parameters", path + " 不允许重复项")
        for item in value:
            validate_schema(item, schema["items"], path + "[]")
    elif kind == "string":
        if "\x00" in value or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 32768):
            raise CapabilityError("invalid_parameters", path + " 文本长度或内容不合法")
    elif kind in ("integer", "number"):
        if not math.isfinite(value) or value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise CapabilityError("invalid_parameters", path + " 数值超出限制")


def object_schema(properties=None, required=()):
    return dict(type="object", properties=properties or {}, required=list(required), additionalProperties=False)

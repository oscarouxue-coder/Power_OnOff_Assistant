"""Locally reviewed, versioned declarative templates over trusted business services.

Templates are data, not Python/PowerShell. A genuinely new low-level operation
must first be implemented as a reviewed formal service, rather than bypassing
resource/permission checks with an executable template.
"""
from dataclasses import replace
from pathlib import Path
import hashlib
import inspect
import json
import re
import threading
import time
import marshal
import math

from src.models.capabilities import CapabilitySpec, CapabilityError, fingerprint, validate_schema


class CapabilityExtensions:
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.unavailable = {}
        with service.jobs.lock, service.jobs.db:
            service.jobs.db.executescript('''
                CREATE TABLE IF NOT EXISTS capability_templates(id TEXT PRIMARY KEY,version TEXT,payload TEXT,
                    digest TEXT,reviewer TEXT,enabled INTEGER,uses INTEGER);
                CREATE TABLE IF NOT EXISTS capability_template_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id TEXT,version TEXT,digest TEXT,reviewer TEXT,created REAL,decision TEXT);
            ''')

    def _target_hash(self, target):
        source = inspect.getsourcefile(target.handler)
        if source and Path(source).is_file():
            return hashlib.sha256(Path(source).read_bytes()).hexdigest()
        code = getattr(target.handler, "__code__", None)
        if code is None:
            raise CapabilityError("extension_unreviewable", "目标服务缺少可核对的代码来源")
        # Frozen deployments still expose the executing code object; no build-machine path is needed.
        return hashlib.sha256(marshal.dumps(code)).hexdigest()

    def review(self, manifest):
        required = {"id", "name", "version", "description", "target_capability", "input_schema", "arguments", "bindings", "allowed_channels"}
        if not isinstance(manifest, dict) or required - set(manifest) or set(manifest) - required - {"expires_at", "max_executions"}:
            raise CapabilityError("invalid_template", "模板字段不完整或包含未开放字段")
        if not isinstance(manifest["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", manifest["id"]) or not isinstance(manifest["version"], str) or not manifest["version"]:
            raise CapabilityError("invalid_template", "模板ID或版本无效")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", manifest["version"]) or any(
                not isinstance(manifest[k], str) or not 1 <= len(manifest[k]) <= 2000 for k in ("name", "description")):
            raise CapabilityError("invalid_template", "模板名称、用途或版本格式不合法")
        if str(manifest["target_capability"]).startswith("extension."):
            raise CapabilityError("invalid_template", "模板不能递归调用另一个模板")
        target = self.service.registry.get(manifest["target_capability"])
        if not isinstance(manifest["arguments"], dict) or not isinstance(manifest["bindings"], dict):
            raise CapabilityError("invalid_template", "固定参数和绑定必须为对象")
        schema = manifest["input_schema"]
        self._check_schema(schema)
        if not isinstance(schema, dict) or schema.get("type") != "object" or schema.get("additionalProperties", False) is not False:
            raise CapabilityError("invalid_template", "模板输入必须为封闭对象schema")
        if any(not isinstance(value, str) or value not in schema.get("properties", {}) for value in manifest["bindings"].values()):
            raise CapabilityError("invalid_template", "参数绑定只能引用已声明的输入字段，不支持eval/代码/路径表达式")
        if set(manifest["arguments"]) & set(manifest["bindings"]):
            raise CapabilityError("invalid_template", "固定参数不能被动态绑定覆盖")
        channels = manifest["allowed_channels"]
        if not isinstance(channels, list) or any(type(c) is not int or not 1 <= c <= 16 for c in channels):
            raise CapabilityError("invalid_template", "允许通道必须明确列为1至16的整数")
        maximum = manifest.get("max_executions")
        if maximum is not None and (type(maximum) is not int or not 1 <= maximum <= 1000000):
            raise CapabilityError("invalid_template", "执行次数限制无效")
        expiry = manifest.get("expires_at")
        if expiry is not None and (type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time()):
            raise CapabilityError("template_expired", "模板授权有效期已经结束或格式无效（Unix秒）")
        code_hash = self._target_hash(target)
        record = dict(manifest=manifest, target_version=target.version, target_code_sha256=code_hash,
                      target_schema_sha256=fingerprint(target.input_schema), risk=target.risk,
                      resources=list(target.resource_requirements), sources=list(target.sources))
        return dict(record, reviewed_sha256=fingerprint(record))

    @staticmethod
    def _check_schema(schema, depth=0):
        if depth > 8 or not isinstance(schema, dict):
            raise CapabilityError("invalid_template", "参数schema嵌套过深或格式无效")
        supported = {"type", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
                     "uniqueItems", "minLength", "maxLength", "minimum", "maximum", "enum", "description"}
        kind = schema.get("type")
        if set(schema) - supported or kind not in ("object", "array", "string", "integer", "number", "boolean"):
            raise CapabilityError("invalid_template", "参数schema包含执行层不支持的约束")
        for key in ("minItems", "maxItems", "minLength", "maxLength"):
            if key in schema and (type(schema[key]) is not int or not 0 <= schema[key] <= 1048576):
                raise CapabilityError("invalid_template", "参数schema长度约束无效")
        for key in ("minimum", "maximum"):
            if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
                raise CapabilityError("invalid_template", "参数schema数值约束无效")
        if "enum" in schema and (not isinstance(schema["enum"], list) or not 1 <= len(schema["enum"]) <= 1000):
            raise CapabilityError("invalid_template", "参数schema枚举无效")
        if kind == "object":
            properties, required = schema.get("properties", {}), schema.get("required", [])
            if (not isinstance(properties, dict) or len(properties) > 100 or
                    any(not isinstance(k, str) for k in properties) or not isinstance(required, list) or
                    any(not isinstance(k, str) or k not in properties for k in required) or
                    schema.get("additionalProperties", False) is not False):
                raise CapabilityError("invalid_template", "参数schema必须为封闭对象且必填字段已声明")
            for item in properties.values():
                CapabilityExtensions._check_schema(item, depth + 1)
        if kind == "array":
            CapabilityExtensions._check_schema(schema.get("items"), depth + 1)

    def approve(self, manifest, reviewed_sha256, reviewer):
        if 'extensions' not in self.service.enabled_modules:
            raise CapabilityError('module_disabled', '当前启动配置已停用受控扩展，须由本地负责人重新启用模块后重启')
        record = self.review(manifest)
        if record["reviewed_sha256"] != reviewed_sha256 or not reviewer:
            raise CapabilityError("template_changed", "实际内容/代码自审阅后已变化，或缺少本地审阅人")
        with self.lock, self.service.jobs.lock, self.service.jobs.db:
            previous = self.service.jobs.db.execute("SELECT version,digest,uses FROM capability_templates WHERE id=?", (manifest["id"],)).fetchone()
            if previous and previous[0] == manifest["version"] and previous[1] != reviewed_sha256:
                raise CapabilityError("template_version_required", "模板实质变化须更新版本后重新审阅")
            uses = previous[2] if previous and previous[1] == reviewed_sha256 else 0
            self.service.jobs.db.execute("INSERT OR REPLACE INTO capability_templates VALUES(?,?,?,?,?,1,?)",
                (manifest["id"], manifest["version"], json.dumps(manifest, ensure_ascii=False), reviewed_sha256, reviewer, uses))
            self.service.jobs.db.execute("INSERT INTO capability_template_reviews(template_id,version,digest,reviewer,created,decision) VALUES(?,?,?,?,?,?)",
                (manifest["id"], manifest["version"], reviewed_sha256, reviewer, time.time(), "approved"))
        self._register(manifest)
        self.service.emit(f"[受控扩展] 本地负责人已审阅模板 {manifest['id']} v{manifest['version']}；SHA256={reviewed_sha256}")

    def restore(self):
        with self.service.jobs.lock:
            manifests = [json.loads(r[0]) for r in self.service.jobs.db.execute("SELECT payload FROM capability_templates")]
        for manifest in manifests:
            try:
                self._register(manifest)
                self.unavailable.pop(manifest['id'], None)
            except (CapabilityError, ValueError, KeyError) as exc:
                self.unavailable[manifest.get("id", "unknown")] = str(exc)
                self.service.emit("[受控扩展] 原模板暂不可用，保留审阅记录：" + str(exc))

    def _register(self, manifest):
        target = self.service.registry.get(manifest["target_capability"])
        def bind(arguments):
            result = dict(manifest["arguments"])
            for destination, source in manifest["bindings"].items():
                if source in arguments:
                    result[destination] = arguments[source]
            if any(c not in manifest["allowed_channels"] for c in result.get("channel_ids", ())):
                raise CapabilityError("extension_scope_exceeded", "参数超出本地负责人审阅的模板通道范围")
            return result
        spec = CapabilitySpec("extension." + manifest["id"], manifest["name"], manifest["description"], manifest["input_schema"],
            lambda a, authority: self.execute(manifest["id"], a, authority), risk=target.risk,
            execution_mode=target.execution_mode, resource_requirements=target.resource_requirements, version=manifest["version"],
            cancellation=target.cancellation, sources=target.sources,
            resource_scope=(lambda a: target.resource_scope(bind(a))) if target.resource_scope else None)
        with self.service.jobs.lock:
            row = self.service.jobs.db.execute("SELECT enabled FROM capability_templates WHERE id=?", (manifest["id"],)).fetchone()
        self.service.registry.install_extension(replace(spec, status="disabled") if row and not row[0] else spec)

    def execute(self, identifier, arguments, authority):
        with self.lock:
            with self.service.jobs.lock:
                row = self.service.jobs.db.execute("SELECT payload,digest,enabled,uses FROM capability_templates WHERE id=?", (identifier,)).fetchone()
            if not row or not row[2]:
                raise CapabilityError("template_disabled", "模板已停用或撤销")
            manifest = json.loads(row[0])
            if self.review(manifest)["reviewed_sha256"] != row[1]:
                raise CapabilityError("template_changed", "模板依赖服务代码/版本/schema已变化，必须重新审阅")
            if manifest.get("max_executions") is not None and row[3] >= manifest["max_executions"]:
                raise CapabilityError("template_limit", "模板已达到本地批准的执行次数")
            validate_schema(arguments, manifest["input_schema"])
            target_args = dict(manifest["arguments"])
            for destination, source in manifest["bindings"].items():
                if source in arguments:
                    target_args[destination] = arguments[source]
            if any(c not in manifest["allowed_channels"] for c in target_args.get("channel_ids", ())):
                raise CapabilityError("extension_scope_exceeded", "目标超出已审阅模板范围")
            # Reserve an invocation atomically; never keep a template mutex while
            # the target waits on Tk admission. Local revocation/listing must stay usable.
            with self.service.jobs.lock, self.service.jobs.db:
                self.service.jobs.db.execute("UPDATE capability_templates SET uses=uses+1 WHERE id=?", (identifier,))
        try:
            result = self.service.execute(manifest["target_capability"], target_args, authority)
        except BaseException:
            self._release_use(identifier, row[1])
            raise
        if isinstance(result, dict) and result.get("reused"):
            self._release_use(identifier, row[1])
        return result

    def _release_use(self, identifier, digest):
        with self.service.jobs.lock, self.service.jobs.db:
            self.service.jobs.db.execute("UPDATE capability_templates SET uses=MAX(0,uses-1) WHERE id=? AND digest=?", (identifier, digest))

    def set_enabled(self, identifier, enabled, reviewer):
        if enabled and 'extensions' not in self.service.enabled_modules:
            raise CapabilityError('module_disabled', '本次启动已停用受控扩展，未恢复模板授权')
        if type(enabled) is not bool or not reviewer:
            raise ValueError("缺少明确本地操作员决定")
        with self.lock, self.service.jobs.lock, self.service.jobs.db:
            row = self.service.jobs.db.execute("SELECT version,digest,payload FROM capability_templates WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise CapabilityError("template_missing", "模板不存在")
            if enabled and self.review(json.loads(row[2]))["reviewed_sha256"] != row[1]:
                raise CapabilityError("template_changed", "目标代码/约束已变化，不能直接恢复旧授权")
            self.service.jobs.db.execute("UPDATE capability_templates SET enabled=? WHERE id=?", (int(enabled), identifier))
            self.service.jobs.db.execute("INSERT INTO capability_template_reviews(template_id,version,digest,reviewer,created,decision) VALUES(?,?,?,?,?,?)",
                (identifier, row[0], row[1], reviewer, time.time(), "enabled" if enabled else "revoked"))
        spec = self.service.registry.get("extension." + identifier)
        self.service.registry.install_extension(replace(spec, status="implemented_unaccepted" if enabled else "disabled"))

    def list(self):
        with self.service.jobs.lock:
            return [dict(id=r[0], version=r[1], reviewed_sha256=r[2], reviewer=r[3], enabled=bool(r[4]), uses=r[5])
                    for r in self.service.jobs.db.execute("SELECT id,version,digest,reviewer,enabled,uses FROM capability_templates")]

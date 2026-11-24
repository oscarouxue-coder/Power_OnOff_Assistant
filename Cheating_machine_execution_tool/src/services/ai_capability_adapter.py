"""Trusted session/permission bridge. Model arguments never carry identity or grants."""
from dataclasses import replace, asdict
import re

from src.models.ai_actions import ActionAssessment, action_fingerprint
from src.models.ai_permissions import ASK, FULL
from src.models.ai_session_scope import source_identity, business_source_identity
from src.models.capabilities import CapabilityAuthority, CapabilityError, fingerprint, object_schema


FAST_CAPABILITIES = {"start_firmware_upgrade": ("firmware.upgrade", ("升级", "固件", "firmware", "tftp")),
    "start_aging_test": ("aging.start", ("老化", "挂测", "开关机测试")),
    "start_test_pipeline": ("pipeline.start", ("全流程", "检查并执行")),
    "power_on": ("power.on", ("上电", "开启电源")),
    "power_off": ("power.off", ("下电", "断电", "关闭电源")),
    "query_device_version": ("device.version", ("版本", "刷后")),
    "start_pretest": ("pretest.start", ("预备测试",)),
    "write_sample_parameters": ("parameters.write", ("写参", "写入参数", "写样机参数")),
    "query_registered_onus": ("onu.registered", ("已注册",)),
    "query_unregistered_onus": ("onu.unregistered", ("未注册",)),
    "register_onus": ("onu.register", ("注册onu", "onu注册", "注册光猫")),
    "delete_onus": ("onu.delete", ("删除onu", "删除已注册")),
    "query_wan": ("dut.wan.query", ("wan",)),
    "configure_wan": ("dut.wan.configure", ("wan",))}
CAPABILITY_TOOLS = frozenset(("list_capabilities", "describe_capability", "validate_capability",
    "execute_capability", "get_job_status", "get_job_result", "cancel_job")) | frozenset(FAST_CAPABILITIES)


def capability_tools(service, text=""):
    identifier = dict(type="string", minLength=1)
    request = object_schema({"capability_id": identifier, "arguments": {"type": "object", "additionalProperties": True}},
                            ("capability_id", "arguments"))
    tools = [dict(name="list_capabilities", description="按模块/关键词查询当前已接入业务；常见任务可直接execute，不要求先查询。",
                  parameters=object_schema({"module": dict(type="string"), "query": dict(type="string")})),
             dict(name="describe_capability", description="按需读取能力参数；定义有版本缓存，不必每轮查询。",
                  parameters=object_schema({"capability_id": identifier}, ("capability_id",))),
             dict(name="validate_capability", description="仅在需要单独预检时调用；execute已自动校验。", parameters=request),
             dict(name="execute_capability", description="直接调用已注册业务；内部完成校验/授权/资源预检，长任务返回job_id。", parameters=request)]
    for name, description in (("get_job_status", "读取独立业务任务的状态及增量事件，不能以模型超时重启任务。"),
                              ("get_job_result", "读取原业务任务结果；查询不会重发操作。"),
                              ("cancel_job", "仅在用户明确要求停止业务时请求安全取消；停止对话不会取消业务。")):
        tools.append(dict(name=name, description=description,
                          parameters=object_schema({"job_id": identifier, "after_event": dict(type="integer", minimum=0)}, ("job_id",))))
    for name, (capability, words) in FAST_CAPABILITIES.items():
        if any(word in text.casefold() for word in words):
            try:
                tools.append(service.registry.tool_schema(capability, name))
            except CapabilityError:
                pass  # A module in the coverage matrix may not be installed yet.
    return tools


class AiCapabilityAdapter:
    def __init__(self, conversation, service):
        self.owner, self.service = conversation, service

    def authority(self, identifier, operation_id="query", approved=False):
        session = self.owner.store.chat(identifier)
        source = session.get("source") or {}
        kind = source.get("kind", "local")
        if kind in ("dingtalk", "feishu") and any(not source.get(k) for k in ("robot", "corp", "sender", "group")):
            raise CapabilityError("identity_required", "远程业务缺少经过入口校验的真实身份")
        targets = session.get("batch_targets") or ([session["target"]] if session.get("target") else [])
        permission = self.owner.permissions.status(identifier)
        if source.get("gateway_instance_id"):
            gateway = getattr(self.owner, "gateway", None)
            if gateway is None or not gateway.authorized_source(source, session):
                raise CapabilityError("relay_identity_required", "统一接入实例未验证当前来源及范围")
        return CapabilityAuthority(fingerprint(business_source_identity(source)), identifier, operation_id,
            tuple(int(t["channel"]) for t in targets), kind, permission["mode"], permission.get("grant_id", ""), approved,
            tuple((int(t["channel"]), t["bind_ip"], t["host"], int(t.get("telnet_port", 23))) for t in targets))

    def accept_confirmation(self, identifier, text):
        match = re.fullmatch(r"确认固件适配\s+([0-9a-f]{8})", text.strip())
        if match:
            self.owner.actions._eligible(identifier)
            self.service.upgrades.confirm(self.authority(identifier).principal, match[1])
            return True
        return False

    def execute(self, identifier, name, params, stop, executor, review):
        from src.models.capabilities import validate_schema
        schemas = {t["name"]: t["parameters"] for t in capability_tools(self.service,
            " ".join(word for _, words in FAST_CAPABILITIES.values() for word in words))}
        if name not in schemas:
            raise CapabilityError("unsupported_capability", "能力工具未开放")
        validate_schema(params, schemas[name])
        session = self.owner.store.chat(identifier)
        if (session.get("source") or {}).get("gateway_instance_id"):
            gateway = getattr(self.owner, "gateway", None)
            if gateway is None:
                raise CapabilityError("relay_identity_required", "统一接入服务未初始化")
            gateway.check_capability(session, name, params)
        self.owner.actions._eligible(identifier, stop)
        authority = self.authority(identifier)
        if name == "list_capabilities":
            from src.services.capability_catalog import business_catalog
            module, query = params.get("module", ""), params.get("query", "")
            pending = [r for r in business_catalog() if r["status"] in ("pending", "partial", "manual_control")
                       and (getattr(self.service, "require_job_review", True) or r["feature_id"] != "projects.resolve_unknown")
                       and (not module or r["feature_id"].split(".")[0] == module)
                       and (not query or query.casefold() in (r["feature_id"] + r["name"]).casefold())]
            return dict(capabilities=self.service.registry.list(module, query), pending_or_manual=pending,
                        enabled_modules=sorted(self.service.enabled_modules),
                        revision=self.service.registry.revision, notice="未接入项见Capability Coverage Matrix；登记不等于可执行")
        if name == "describe_capability":
            return self.service.registry.describe(params["capability_id"])
        if name in ("get_job_status", "get_job_result"):
            return self.service.jobs.status(params["job_id"], authority, params.get("after_event", 0))
        capability = FAST_CAPABILITIES[name][0] if name in FAST_CAPABILITIES else params.get("capability_id")
        arguments = params if name in FAST_CAPABILITIES else params.get("arguments", {})
        if name == "validate_capability":
            return self.service.validate(capability, arguments, authority)
        spec = None if name == "cancel_job" else self.service.registry.validate(capability, arguments)
        risk = "dangerous" if spec is None else spec.risk
        scope = spec.resource_scope(arguments) if spec is not None and spec.resource_scope is not None else None
        needs_scope = scope is not None and not self.service.scopes.allowed(authority.principal, scope)
        if spec is not None and authority.source not in spec.sources:
            raise CapabilityError("source_forbidden", "当前来源不能执行此控制面操作")
        if risk == "read" and not needs_scope:
            return self.service.execute(capability, arguments, replace(authority,
                operation_id=self._operation(identifier, capability, arguments)))
        # Close only this conversation's transport before a job preflight checks COM
        # ownership. ASK/AUTO must be able to hand off a connection just like FULL.
        if spec is not None and spec.execution_mode == 'job':
            executor.close()
            if hasattr(executor, 'transport'):
                executor.transport = None
        # Preflight errors/compatibility requests must be resolved before asking to approve execution.
        if name != "cancel_job" and authority.mode != FULL:
            self.service.validate(capability, arguments, authority, check_scope=False)
        action = self.owner.actions._prepare(identifier, name, params)
        action.update(permission_mode=authority.mode, authorization_id=authority.grant_id,
                      authorization_source=authority.source, principal=authority.principal)
        if needs_scope:
            action.update(local_only=True, scope_extension=scope)
        action["fingerprint"] = action_fingerprint(action)
        self.owner.store.change_action(action["id"], ("reviewing",), "reviewing", **{
            k: action[k] for k in ("permission_mode", "authorization_id", "authorization_source", "principal", "fingerprint", "local_only", "scope_extension") if k in action})
        approved = False
        if authority.mode != FULL or needs_scope:
            assessment = ActionAssessment("dangerous", "本地负责人审阅新增资源范围：" + str(scope)) if needs_scope else (
                ActionAssessment("dangerous", "受控业务操作：" + (spec.name if spec else "停止业务任务")) if risk == "dangerous" else review(action))
            action["assessment"] = asdict(assessment)
            self.owner.store.change_action(action["id"], ("reviewing",), "reviewing", assessment=action["assessment"])
            if authority.mode == ASK or assessment.risk != "ordinary":
                if assessment.risk == "blocked" or not self.owner.actions._wait_approval(action, stop):
                    return self.owner.actions._finish(action, "blocked", dict(dispatched=False, notice="未获得具体业务批准"))
            approved = True
        self.owner.actions._eligible(identifier, stop)
        current = self.authority(identifier, action["id"], approved)
        if (current.mode, current.grant_id, current.channels, current.principal, current.target_endpoints) != (
                authority.mode, authority.grant_id, authority.channels, authority.principal, authority.target_endpoints):
            raise CapabilityError("authorization_changed", "批准期间授权或目标已变化，未执行")
        if needs_scope:
            decided = self.owner.store.action(action["id"])
            if decided.get("approval_source") not in ("operator", "local"):
                raise CapabilityError("local_scope_approval_required", "缺少真实本地资源审阅记录")
            if spec.resource_scope(arguments) != scope:
                raise CapabilityError("target_changed", "审阅期间资源配置已变化，未执行")
            self.service.scopes.grant(current.principal, scope, decided.get("operator_identity") or "local-operator")
        # A verified diagnostic connection may own the COM. Release this conversation's transport before handoff.
        expected = ("approved",) if approved and self.owner.store.action(action["id"])["state"] == "approved" else ("reviewing",)
        self.owner.store.change_action(action["id"], expected, "executing")
        try:
            # Use the host turn identity + immutable request for retries, not a model-created id.
            operation = self._operation(identifier, capability, arguments)
            current = replace(current, operation_id=operation)
            result = self.service.jobs.cancel(params["job_id"], current) if name == "cancel_job" else self.service.execute(capability, arguments, current)
            return self.owner.actions._finish(action, "succeeded", dict(result, dispatched=True))
        except CapabilityError as exc:
            return self.owner.actions._finish(action, "failed", dict(exc.result(), dispatched=False))

    def _operation(self, identifier, capability, arguments):
        context = self.owner.store.chat(identifier)
        # The native entry supplies the turn identity. A future gateway must supply
        # its request association through the same trusted session boundary.
        turn = context.get('gateway_request_id') if (context.get('source') or {}).get('gateway_instance_id') else context.get('capability_turn', '')
        if capability == 'firmware.upgrade':
            from src.services.firmware_upgrade_service import normalized_upgrade_arguments
            arguments = normalized_upgrade_arguments(arguments)
        return fingerprint((identifier, turn, capability, arguments))

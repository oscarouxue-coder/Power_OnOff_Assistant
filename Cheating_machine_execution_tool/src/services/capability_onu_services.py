"""OLT/ONU adapters. New OLT/PON scope requires fingerprint-bound local review."""
from dataclasses import asdict, replace
from pathlib import Path

from line_check_assistant.onu_registration_store import OnuRegistrationStore, OnuRegistrationConfig
from line_check_assistant.paths import resolve_config_dir
from src.models.capabilities import CapabilitySpec, CapabilityError, fingerprint, object_schema
from src.models.onu_registration_models import OltConnection, OnuDiscoveryScope, OnuProvisionRequest
from src.core.zte_c600_onu import parse_service_mappings
from src.services.onu_registration_service import OnuRegistrationService
from src.services.onu_batch_registration_service import build_batch_requests
from src.services.onu_command_edit_service import OnuCommandEditService
from src.services.onu_batch_delete_service import OnuBatchDeleteService


class OnuCapabilities:
    def __init__(self, service, tool_root, configuration=None):
        self.service = service
        self.store = OnuRegistrationStore(resolve_config_dir(Path(tool_root)) / "onu_registration.ini")
        self.configuration = configuration or (lambda: asdict(self.store.load()))
        self.registration_factory = OnuRegistrationService
        self.delete_factory = OnuBatchDeleteService
        self._register()

    def _register(self):
        base = {"family": dict(type="string", enum=["C300", "C600"]),
                "shelf": dict(type="integer", minimum=0, maximum=64),
                "slot": dict(type="integer", minimum=0, maximum=64),
                "pon": dict(type="integer", minimum=0, maximum=64)}
        serials = dict(type="array", minItems=1, maxItems=128, uniqueItems=True,
                       items=dict(type="string", minLength=1, maxLength=128))
        provision = dict(serial_numbers=serials,
            onu_id=dict(type="integer", minimum=1, maximum=1024), onu_type=dict(type="string", minLength=1),
            tcont_id=dict(type="integer", minimum=1), tcont_profile=dict(type="string", minLength=1),
            gemport_id=dict(type="integer", minimum=1), vport_id=dict(type="integer", minimum=1),
            real_speed=dict(type="string"), sn_bind_both=dict(type="boolean"), services=dict(type="string"),
            cleanup_onu_interface=dict(type="string"), target_ids=dict(type="object", additionalProperties=True))
        operations = {
            "connection": ({}, ()), "unregistered": ({}, ()),
            "templates": ({"kind": dict(type="string", enum=["onu_type", "dba"])}, ("kind",)),
            "preview": (provision, ("serial_numbers",)), "register": (provision, ("serial_numbers",)),
            "cleanup_query": (provision, ("serial_numbers",)), "registered": ({}, ()),
            "delete": ({"onu_interfaces": serials}, ("onu_interfaces",)), "save": ({}, ())}
        for operation, (extra, required) in operations.items():
            write = operation in ("register", "delete", "save")
            spec = CapabilitySpec("onu." + operation, "ONU " + operation,
                "通过现有OLT/ONU业务执行" + operation + "；OLT/PON范围首次须本地负责人审阅，不能从通道授权推断。",
                object_schema(dict(base, **extra), ("family", *required)),
                lambda a, auth, op=operation: self.execute(op, a, auth), risk="dangerous", execution_mode="job",
                resource_requirements=("device-business", "olt", "pon"), cancellation="cooperative",
                resource_scope=lambda a, op=operation: self.scope(a, op))
            self.service.registry.register(spec)

    def connection(self, arguments):
        config = OnuRegistrationConfig(**self.configuration())
        family = arguments["family"]
        prefix = family.lower() + "_"
        def value(name):
            stored = getattr(config, prefix + name)
            return stored or (getattr(config, name) if config.olt_family == family else "")
        connection = OltConnection(value("olt_ip"), value("source_ip"), value("username"), value("password"))
        errors = connection.validate()
        if errors:
            raise CapabilityError("invalid_olt_configuration", "; ".join(errors))
        discovery = OnuDiscoveryScope(*(arguments.get(name, getattr(config, prefix + name)) for name in ("shelf", "slot", "pon")))
        errors = discovery.validate()
        if errors:
            raise CapabilityError("invalid_parameters", "; ".join(errors))
        pon = ("gpon-olt_" if family == "C300" else "gpon_olt-") + f"{discovery.shelf}/{discovery.slot}/{discovery.pon}"
        return config, connection, discovery, pon

    def scope(self, arguments, operation):
        config, connection, discovery, pon = self.connection(arguments)
        if operation in ("register", "delete", "cleanup_query", "preview") and discovery.is_all_olt:
            raise CapabilityError("explicit_pon_required", "注册/删除/预览/清理须明确单个PON，不把整机查询扩大成整机修改")
        access = "save_configuration" if operation == "save" else "write" if operation in ("register", "delete") else "read"
        target = "OLT" if operation == "save" or discovery.is_all_olt else pon
        return dict(id=f"olt:{arguments['family']}:{connection.host}:{target}:{access}",
            family=arguments["family"], host=connection.host, source_ip=connection.source_ip, target=target, access=access,
            connection_revision=fingerprint(asdict(connection)),
            notice="查询可能读取OLT模板元数据；设备修改限明确PON，保存配置write为独立整OLT操作")

    def _requests(self, operation, arguments, config, connection, discovery, registration, context):
        discovered = registration.query_unregistered(arguments["family"], connection, discovery, context.stop.event)
        if not discovered.ok:
            raise CapabilityError("onu_discovery_failed", discovered.message)
        serials = [s.strip().upper() for s in arguments["serial_numbers"]]
        selected = []
        for serial in serials:
            candidates = [o for o in discovered.onus if o.serial_number.strip().upper() == serial]
            if len(candidates) != 1:
                raise CapabilityError("onu_identity_changed", "指定SN未在本次查询中唯一命中：" + serial)
            selected.append(candidates[0])
        prefix = arguments["family"].lower() + "_"
        def value(name, default=None):
            return arguments.get(name, getattr(config, prefix + name, default))
        business = parse_service_mappings(value("services"), allow_translation=arguments["family"] == "C600")
        base = OnuProvisionRequest(family=arguments["family"], onu=selected[0], onu_id=value("onu_id"),
            onu_type=value("onu_type").split("（", 1)[0].strip(), tcont_id=value("tcont_id"),
            tcont_profile=value("tcont_profile").split("（", 1)[0].strip(), services=tuple(business),
            real_speed=value("real_speed", "auto"), gemport_id=value("gemport_id", 1),
            vport_id=value("vport_id", 1), sn_bind_both=value("sn_bind_both", True))
        supplied = arguments.get("target_ids", {})
        if set(supplied) - set(serials):
            raise CapabilityError("invalid_parameters", "手动ONU ID包含未选择的SN")
        target_ids = {o: str(supplied[o.serial_number.upper()]) for o in selected if o.serial_number.upper() in supplied}
        requests = build_batch_requests(selected, base, target_ids)
        registration.build_preview(requests)  # The original family drivers validate business parameters.
        plans = tuple(OnuCommandEditService().build_default(request) for request in requests)
        return requests, plans

    def execute(self, operation, arguments, authority):
        scope = self.scope(arguments, operation)
        self.service.scopes.require(authority, scope)
        config, connection, discovery, pon = self.connection(arguments)
        def recheck():
            if self.scope(arguments, operation) != scope:
                raise CapabilityError("olt_configuration_changed", "准入前OLT连接或PON配置已变化")
        def runner(context):
            registration = self.registration_factory(logger=lambda line: context.event("onu", line))
            context.stop.checkpoint()
            if operation == "connection":
                value = registration.test_connection(arguments["family"], connection, context.stop.event)
            elif operation == "unregistered":
                value = registration.query_unregistered(arguments["family"], connection, discovery, context.stop.event)
            elif operation == "templates":
                value = registration.query_templates(arguments["family"], connection, arguments["kind"], context.stop.event)
            elif operation == "registered":
                value = registration.query_registered_candidates(arguments["family"], connection, pon, context.stop.event)
            elif operation == "save":
                context.event("onu", "独立授权保存OLT配置，不从其它任务推断write", dispatched=True)
                value = registration.save_configuration(arguments["family"], connection, context.stop.event)
            elif operation == "delete":
                current = registration.query_registered_candidates(arguments["family"], connection, pon, context.stop.event)
                if not current.ok:
                    raise CapabilityError("onu_query_failed", current.message)
                chosen = []
                for interface in arguments["onu_interfaces"]:
                    matches = [o for o in current.registered_onus if o.onu_interface == interface]
                    if len(matches) != 1:
                        raise CapabilityError("onu_identity_changed", "选中ONU已变化或不属于当前PON")
                    chosen.append(matches[0])
                context.event("onu", "调用原逐台身份回读与批量删除服务；不执行write", dispatched=True)
                value = self.delete_factory(logger=lambda line: context.event("onu", line), registration_service=registration).delete(
                    arguments["family"], connection, pon, chosen, context.stop.event)
            else:
                requests, plans = self._requests(operation, arguments, config, connection, discovery, registration, context)
                if operation == "preview":
                    return dict(ok=True, plans=[dict(serial_number=p.request.onu.serial_number, commands=list(p.commands)) for p in plans])
                if operation == "cleanup_query":
                    if arguments["family"] != "C300" or len(requests) != 1:
                        raise CapabilityError("invalid_parameters", "离线清理候选只支持明确单台C300")
                    value = registration.query_c300_cleanup_candidates(connection, requests[0], context.stop.event)
                else:
                    cleanup = None
                    interface = arguments.get("cleanup_onu_interface", "")
                    if interface:
                        if arguments["family"] != "C300" or len(requests) != 1:
                            raise CapabilityError("invalid_parameters", "批量或C600禁止离线清理重试")
                        candidates = registration.query_c300_cleanup_candidates(connection, requests[0], context.stop.event)
                        matches = [o for o in candidates.cleanup_candidates if o.onu_interface == interface] if candidates.ok else []
                        if len(matches) != 1:
                            raise CapabilityError("onu_identity_changed", "明确离线清理候选未在当前查询中唯一命中")
                        cleanup = matches[0]
                    context.event("onu", "执行不可变注册计划，保留原注册/验证及单台清理边界", dispatched=True)
                    value = registration.register(connection, requests, cleanup, context.stop.event, command_plans=plans)
            result = asdict(value)
            result.update(ok=value.ok, state="stopped" if context.stop.is_set() else "succeeded" if value.ok else
                          "unknown" if context.dispatched else "failed")
            return result
        return self.service.jobs.start("onu." + operation, dict(arguments, resource_scope=scope), authority,
            ["device-business", "olt:" + connection.host, "pon:" + connection.host + ":" + pon], runner, recheck=recheck,
            observational=operation not in ("register", "delete", "save"))

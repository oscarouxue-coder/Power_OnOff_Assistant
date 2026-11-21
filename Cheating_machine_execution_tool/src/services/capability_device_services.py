"""Controlled adapters to existing power, pipeline, pretest and DUT services.

No device commands or test verdict logic live here. The pipeline projection owns
only data and events; it is intentionally not a Tk application or GUI callback.
"""
from contextlib import nullcontext
from dataclasses import asdict, fields, is_dataclass, MISSING
from pathlib import Path
import json
import threading
import time


from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
from line_check_assistant.onu_registration_store import OnuRegistrationConfig
from line_check_assistant.paths import resolve_config_dir
from line_check_assistant.test_item_config_store import TestItemConfigStore
from line_check_assistant.network_ops import adapter_alias_from_display
from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.models.dut_config_models import (DutTelnetEnableRequest, DutAdvancedConfigRequest, DutWanSettings,
    DutVoiceSettings, DutTr069Settings, DutWifiSettings, DutWifiRadioSettings)
from src.models.serial_models import SerialSettings
from src.services.pipeline_orchestrator import PipelineContext, PipelineOrchestrator, PipelineError
from src.services.power_on_service import turn_on_selected_channels, turn_off_selected_channels
from src.services.device_project_info_service import DeviceProjectInfoQueryRequest, query_device_project_info
from src.services.test_item_pretest_service import prepare_pretest_request, run_pretest
from src.services.dut_config_service import run_dut_telnet_enable_batch
from src.services.dut_wan_query_service import run_dut_wan_query_batch
from src.services.dut_status_query_service import run_dut_status_query_batch
from src.services.dut_advanced_config_service import run_dut_advanced_config_batch, validate_dut_advanced_request


# The original orchestrator wraps both a negative test verdict and a graceful
# stop receipt in PipelineError. Keep unrelated failures and forcibly terminated
# workers distinguishable even when the operator requested a stop.
_POWER_STOP_ERRORS = frozenset('子任务 legacy_power_test 失败:' + detail for detail in (
    '开关机版本预检已停止，未启动开关机测试',
    '开关机测试已停止，未启动开关机测试',
    '用户已停止初始化断电，未启动开关机测试',
    '用户已停止执行开关机测试',
))


CHANNEL_PROPERTIES = {"channel_ids": dict(type="array", minItems=1, maxItems=16, uniqueItems=True,
    items=dict(type="integer", minimum=1, maximum=16))}


def settings_schema(model):
    properties = {}
    for item in fields(model):
        if item.name.startswith("supported_"):
            continue  # Device-reported support lists are never supplied by the model.
        value = item.default if item.default is not MISSING else ""
        if item.name == "peer_radio":
            properties[item.name] = settings_schema(DutWifiRadioSettings)
        elif isinstance(value, bool):
            properties[item.name] = dict(type="boolean")
        elif isinstance(value, int):
            properties[item.name] = dict(type="integer")
        elif isinstance(value, tuple):
            properties[item.name] = dict(type="array", maxItems=64, items=dict(type="string", maxLength=500))
        else:
            properties[item.name] = dict(type="string", maxLength=4096)
    return object_schema(properties)


class PipelineProjection:
    """Data-only implementation of the existing orchestrator's application protocol."""
    def __init__(self, context, channels, manager, log_directory, *, serial_prestart=None):
        self.context, self.channels, self.manager = context, channels, manager
        self.log_directory = Path(log_directory)
        self.power_test_resume_session = None
        self.monitors = []
        self.serial_prestart = serial_prestart

    def _open_pipeline_serial_logs(self):
        if self.serial_prestart is not None:
            return self.serial_prestart(self.context, self.channels, self.log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        for channel in self.channels:
            port = channel.serial_port
            if not port:
                from src.core.serial_transport import vlan_to_serial_port
                port = vlan_to_serial_port(channel.vlan_name.lower())
            owner = "business-log:" + self.context.job_id + ":" + channel.section
            self.manager.acquire_monitor(owner, SerialSettings(port),
                self.log_directory / (channel.vlan_name.lower() + "_" + self.context.job_id[:8] + ".log"))
            self.monitors.append((owner, port))

    def _reset_power_test_channel_states(self, numbers):
        self.context.event("aging", "初始化目标通道：" + ",".join(map(str, numbers)))

    def _set_power_test_progress(self, completed, total):
        self.context.event("aging", json.dumps(dict(completed=completed, total=total)))

    def _set_power_test_channel_state(self, channel, status, detail):
        self.context.event("aging", json.dumps(dict(channel=channel, status=status, detail=detail), ensure_ascii=False))

    def _record_power_test_channel_history(self, channel, cycle, status, detail):
        self.context.event("history", json.dumps(dict(channel=channel, cycle=cycle, status=status, detail=detail), ensure_ascii=False))

    def _set_power_test_channel_progress(self, channel, completed, total, stage):
        self.context.event("aging", json.dumps(dict(channel=channel, completed=completed, total=total, stage=stage), ensure_ascii=False))

    def close(self):
        for owner, port in self.monitors:
            self.manager.release(owner, port)
        self.monitors.clear()


class DeviceCapabilities:
    def __init__(self, service, tool_root):
        self.service, self.root = service, Path(tool_root)
        self.config_path = resolve_config_dir(self.root) / "test_project_config.ini"
        self.pipeline_factory = PipelineOrchestrator
        self.latest_aging = None
        self.gui_pipeline_serial_prestart = None
        self.gui_diagnostic_observer = None
        self.gui_pipeline_power_scope = None
        self._register()

    def _add(self, identifier, name, handler, properties=None, risk="dangerous"):
        required = ["channel_ids"] + (["settings"] if identifier.endswith(".configure") else
            ["tasks"] if identifier == "pipeline.start" else ["parent_job_id"] if identifier == "aging.resume" else [])
        schema = object_schema(dict(CHANNEL_PROPERTIES, **(properties or {})), required)
        self.service.registry.register(CapabilitySpec(identifier, name, name + "；直接调用现有业务服务，异步返回任务编号。",
            schema, handler, risk=risk, execution_mode="job", resource_requirements=("device-business",), cancellation="cooperative"))

    def _register(self):
        self._add("power.on", "自动上电", lambda a, auth: self._power(a, auth, True))
        self._add("power.off", "自动下电", lambda a, auth: self._power(a, auth, False))
        self._add("network.line_check", "环境线路检查", lambda a, auth: self._pipeline(a, auth, ("env_check",)), risk="modify")
        self._add("aging.start", "启动老化/开关机测试", lambda a, auth: self._pipeline(a, auth, ("legacy_power_test",)))
        self._add("pipeline.start", "执行所选三项全流程", self._pipeline_start, {
            "tasks": dict(type="array", minItems=1, maxItems=3, uniqueItems=True,
                          items=dict(type="string", enum=["env_check", "serial_terminal", "legacy_power_test"]))})
        self._add("aging.resume", "失败轮次续跑", self._resume, {"parent_job_id": dict(type="string", minLength=1)})
        self._add("device.version", "查询当前样机版本", self._version, risk="modify")
        self._add("pretest.start", "执行已配置预备测试命令", self._pretest)
        self._add("dut.telnet.enable", "开启DUT Telnet", lambda a, auth: self._dut(a, auth, "telnet", False))
        self._add("dut.wan.query", "查询DUT WAN", lambda a, auth: self._dut(a, auth, "wan", True), risk="modify")
        for feature, model in (("wan", DutWanSettings), ("voice", DutVoiceSettings), ("tr069", DutTr069Settings),
                               ("wifi_2g", DutWifiSettings), ("wifi_5g", DutWifiSettings)):
            self._add("dut." + feature + ".configure", "配置DUT " + feature,
                lambda a, auth, f=feature: self._dut(a, auth, f, False),
                {"settings": settings_schema(model), "parallel_count": dict(type="integer", minimum=1, maximum=8)})
        for feature in ("telnet", "voice", "tr069", "wifi_2g", "wifi_5g"):
            self._add("dut." + feature + ".query", "查询DUT " + feature,
                lambda a, auth, f=feature: self._dut(a, auth, f, True),
                {"line_index": dict(type="string", minLength=1), "ssid_index": dict(type="string", minLength=1)}, risk="modify")

    def selected(self, arguments, authority, snapshot=None):
        authority.check(arguments["channel_ids"])
        snapshot = snapshot or self.service.snapshot()
        indexed = {int(c["section"].split("_")[-1]): c for c in snapshot["channels"]}
        result = []
        for number in arguments["channel_ids"]:
            item = indexed.get(number)
            if not item or not item.get("enabled", True):
                raise CapabilityError("invalid_target", "目标通道不存在或未启用")
            result.append(ChannelConfig(**item))
        return snapshot, result

    def _job(self, identifier, arguments, authority, run, *, recorded_extra=None, precheck=lambda: None,
             power_test=False):
        snapshot, channels = self.selected(arguments, authority)
        def identity(current_snapshot, current_channels):
            return fingerprint(dict(channels=[asdict(c) for c in current_channels],
                power=current_snapshot.get('power_serial_port', ''),
                profile=current_snapshot.get('upgrade_settings', {})))
        binding = identity(snapshot, channels)
        def recheck():
            current_snapshot, current = self.selected(arguments, authority)
            if identity(current_snapshot, current) != binding:
                raise CapabilityError("target_changed", "准入前目标通道配置已变化")
            precheck()
        resources = ["device-business"]
        for channel in channels:
            resources.extend(("channel:" + channel.section.rsplit("_", 1)[1],
                              "adapter:" + adapter_alias_from_display(channel.adapter_alias or channel.vlan_name).casefold()))
            from src.core.serial_transport import vlan_to_serial_port
            try:
                port = channel.serial_port or vlan_to_serial_port(adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).lower())
            except ValueError:
                port = ''
            if port:
                resources.append("serial:" + port.upper())
        if snapshot.get('power_serial_port') and identifier.startswith(('power.', 'aging.', 'pipeline.')):
            resources.append('power:' + snapshot['power_serial_port'].upper())
        if identifier.startswith(('aging.', 'pipeline.')):
            if identifier == 'aging.resume' and self.latest_aging:
                session = self.latest_aging[2].power_test_resume_session
                wifi_enabled = bool(getattr(getattr(session, 'request', None), 'connect_wifi_enable', False))
            elif power_test:
                from src.services.project_execution import power_test_needs_wifi
                wifi_enabled = power_test_needs_wifi(self.config_path.parent, channels)
            else:
                wifi_enabled = bool(TestItemConfigStore(self.config_path).load().connect_wifi.enable)
            if wifi_enabled:
                resources.append('wifi:host')
        def run_admitted(context):
            if power_test and 'wifi:host' not in resources:
                from src.services.project_execution import power_test_needs_wifi
                root = getattr(context, 'configuration_root', self.root)
                if power_test_needs_wifi(resolve_config_dir(root), channels):
                    raise CapabilityError('configuration_changed', '挂测方案的无线资源已变化，请重新确认')
            return run(context, snapshot, channels)
        return self.service.jobs.start(identifier, dict(arguments, **(recorded_extra or {}), target_binding=binding), authority, resources,
            run_admitted, recheck=recheck,
            risk=self.service.registry.get(identifier).risk)

    def _power(self, arguments, authority, enabled):
        def run(context, snapshot, channels):
            if not snapshot.get("power_serial_port"):
                raise CapabilityError("missing_power_port", "未配置程控电源COM，不会自动选择")
            context.stop.checkpoint()
            context.event("power", "按现有电源业务执行明确目标", dispatched=True)
            # Complete an admitted power sequence; do not kill a half-finished combination.
            result = (turn_on_selected_channels if enabled else turn_off_selected_channels)(
                snapshot["power_serial_port"], arguments["channel_ids"],
                on_output=lambda line: context.event("power", line))
            return dict(ok=result.ok, state="succeeded" if result.ok else "unknown", message=result.message)
        return self._job("power.on" if enabled else "power.off", arguments, authority, run)

    def _pipeline_start(self, arguments, authority):
        if "tasks" not in arguments:
            raise CapabilityError("invalid_parameters", "必须明确全流程子任务，不能默认开启全部")
        return self._pipeline(arguments, authority, arguments["tasks"])

    def _pipeline(self, arguments, authority, tasks):
        identifier = "aging.start" if tasks == ("legacy_power_test",) else "network.line_check" if tasks == ("env_check",) else "pipeline.start"
        def run(context, snapshot, channels):
            projection = PipelineProjection(context, channels, self.service.manager,
                snapshot.get("serial_log_dir") or self.service.jobs.directory / "serial",
                serial_prestart=self.gui_pipeline_serial_prestart if authority.source == "gui" else None)
            if authority.source == "gui" and self.gui_diagnostic_observer is not None:
                projection._observe_ai_power_event = self.gui_diagnostic_observer
            config = PipelineContext(projection, channels, SampleUpgradeSettings(**snapshot["upgrade_settings"]),
                OnuRegistrationConfig(), legacy_tool_root=getattr(context, 'configuration_root', self.root) / "Auto_power_on_off_tool", stop_event=context.stop.event)
            try:
                context.event("pipeline", "复用原编排器，保留版本预检/WiFi/停止/测试判据", dispatched=True)
                hold = self.gui_pipeline_power_scope if authority.source == "gui" and "legacy_power_test" in tasks else None
                with hold(projection) if hold is not None else nullcontext():
                    results = self.pipeline_factory(config, lambda line: context.event("pipeline", line)).run(set(tasks))
                    stopped = context.stop.is_set()
                if projection.power_test_resume_session is not None:
                    self.latest_aging = (context.job_id, authority.principal, projection)
                return dict(ok=all(r.ok for r in results) and not stopped,
                            state="stopped" if stopped else "succeeded" if all(r.ok for r in results) else "failed",
                            items=[asdict(r) for r in results])
            except PipelineError as exc:
                if projection.power_test_resume_session is not None:
                    self.latest_aging = (context.job_id, authority.principal, projection)
                error = str(exc)
                stopped = context.stop.is_set() and error in _POWER_STOP_ERRORS
                return dict(ok=False, state="stopped" if stopped else "failed", error=error)
            finally:
                projection.close()
        return self._job(identifier, arguments, authority, run, power_test='legacy_power_test' in tasks)

    def _resume(self, arguments, authority):
        parent = arguments.get("parent_job_id")
        if not self.latest_aging or self.latest_aging[:2] != (parent, authority.principal):
            raise CapabilityError("resume_unavailable", "仅当前进程最近原批次的同身份任务可续跑；重启不自动恢复")
        session = self.latest_aging[2].power_test_resume_session
        for number in arguments["channel_ids"]:
            if not session.can_resume(number):
                raise CapabilityError("resume_unavailable", f"通道{number}当前不满足原失败续跑条件")
        def run(context, snapshot, channels):
            for number in arguments["channel_ids"]:
                if not session.submit(number):
                    raise CapabilityError("resume_unavailable", "续跑状态已变化，未重复启动")
            while session.is_recovering:
                if context.stop.is_set():
                    session.stop()
                time.sleep(.05)
            return dict(ok=all(c not in session.failed for c in arguments["channel_ids"]),
                        state="stopped" if context.stop.is_set() else "failed" if any(c in session.failed for c in arguments["channel_ids"]) else "succeeded")
        return self._job("aging.resume", arguments, authority, run)

    def _version(self, arguments, authority):
        def check_endpoints(channels, telnet):
            expected = {row[0]: row[1:] for row in authority.target_endpoints}
            if expected and any(expected.get(int(c.section.rsplit('_', 1)[1])) !=
                                (c.network_card_ip, c.device_manage_ip, int(telnet.port or 23)) for c in channels):
                raise CapabilityError("target_changed", "版本查询端点与原会话快照不一致，未下发")
        def precheck():
            if authority.target_endpoints:
                _, channels = self.selected(arguments, authority)
                check_endpoints(channels, TestItemConfigStore(self.config_path).load(required=True).telnet)
        def run(context, snapshot, channels):
            config = TestItemConfigStore(self.config_path).load(required=True)
            check_endpoints(channels, config.telnet)
            values = []
            halted = ""
            for channel in channels:
                row = dict(channel=channel.section, bind_ip=channel.network_card_ip,
                           device_host=channel.device_manage_ip)
                if not halted and context.stop.is_set():
                    halted = "业务已请求停止"
                if not halted:
                    try:
                        current, selected = self.selected(arguments, authority)
                        if (selected != channels or current.get('upgrade_settings') != snapshot.get('upgrade_settings')
                                or TestItemConfigStore(self.config_path).load(required=True).telnet != config.telnet):
                            halted = "目标或登录配置已变化"
                    except Exception as exc:
                        halted = "无法复核目标配置：" + str(exc)
                if halted:
                    row.update(status="not_executed", error=halted)
                else:
                    try:
                        value = query_device_project_info(DeviceProjectInfoQueryRequest(channel.network_card_ip,
                            channel.device_manage_ip, config.telnet), emit=lambda line: context.event("version", line))
                        row.update(asdict(value), status="succeeded")
                    except Exception as exc:
                        row.update(status="failed", error=str(exc))
                values.append(row)
                context.event("version_item", json.dumps(row, ensure_ascii=False))
            ok = all(row["status"] == "succeeded" for row in values)
            return dict(ok=ok, state="stopped" if context.stop.is_set() else "succeeded" if ok else "failed", items=values)
        return self._job("device.version", arguments, authority, run, precheck=precheck)

    def _pretest(self, arguments, authority):
        def run(context, snapshot, channels):
            config = TestItemConfigStore(self.config_path).load(required=True)
            request = prepare_pretest_request(channels, config.order, config.telnet)
            context.event("pretest", "执行已配置命令，不修改正式挂测判据", dispatched=True)
            result = run_pretest(request, context.stop.event, lambda text, tag: context.event("pretest", text))
            ok = not (context.stop.is_set() or result.failed or result.device_errors)
            return dict(ok=ok, state="stopped" if context.stop.is_set() else "succeeded" if ok else "failed", result=asdict(result))
        return self._job("pretest.start", arguments, authority, run)

    def _dut(self, arguments, authority, feature, query):
        identifier = "dut." + feature + (".query" if query else ".enable" if feature == "telnet" else ".configure")
        def run(context, snapshot, channels):
            options = snapshot["upgrade_settings"]
            requests = [DutTelnetEnableRequest(channel=c.label, vlan=adapter_alias_from_display(c.vlan_name or c.adapter_alias).lower(),
                adapter_alias=adapter_alias_from_display(c.adapter_alias or c.vlan_name), bind_ip=c.network_card_ip,
                device_host=c.device_manage_ip, subnet_mask=c.subnet_mask,
                username=options.get("parameter_initial_username", ""), password=options.get("parameter_initial_password", "")) for c in channels]
            kwargs = dict(stop_event=context.stop.event, on_output=lambda line: context.event("dut", line))
            context.event("dut", "准备调用原DUT业务服务")
            if query and feature == "wan":
                values = run_dut_wan_query_batch(requests, **kwargs)
            elif query:
                values = run_dut_status_query_batch(requests, feature, line_index=arguments.get("line_index", "1"),
                                                    ssid_index=arguments.get("ssid_index", "1"), **kwargs)
            elif feature == "telnet":
                context.dispatched = True
                values = run_dut_telnet_enable_batch(requests, **kwargs)
            else:
                if "settings" not in arguments:
                    raise CapabilityError("invalid_parameters", "必须明确配置参数，不能自动提交空白表单")
                model = {"wan": DutWanSettings, "voice": DutVoiceSettings, "tr069": DutTr069Settings,
                         "wifi_2g": DutWifiSettings, "wifi_5g": DutWifiSettings}[feature]
                settings = dict(arguments["settings"])
                if feature.startswith("wifi_"):
                    settings["band"] = "2.4G" if feature == "wifi_2g" else "5G"
                    if "peer_radio" in settings:
                        settings["peer_radio"] = DutWifiRadioSettings(**settings["peer_radio"])
                advanced = [DutAdvancedConfigRequest(**asdict(r), feature=feature, settings=model(**settings)) for r in requests]
                errors = [e for request in advanced for e in validate_dut_advanced_request(request)]
                if errors:
                    raise CapabilityError("invalid_parameters", "; ".join(errors))
                context.dispatched = True
                values = run_dut_advanced_config_batch(advanced, max_workers=arguments.get("parallel_count", 1), **kwargs)
            items = []
            for value in values:
                item = asdict(value)
                item.pop("request", None)  # Do not duplicate execution credentials in tool results.
                items.append(item)
            ok = bool(values) and all(value.ok for value in values)
            return dict(ok=ok, state="stopped" if context.stop.is_set() else "succeeded" if ok else "failed" if query else "unknown", items=items)
        return self._job(identifier, arguments, authority, run)

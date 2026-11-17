"""Business API shared by explicit GUI/Agent adapters; no Tk or model dependency."""
from dataclasses import asdict
from pathlib import Path
import threading
import os

from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.models.dependency_repair import maintenance_operation
from src.services.capability_registry import CapabilityRegistry
from src.services.capability_metrics import CapabilityMetrics
from src.services.capability_jobs import CapabilityJobs
from src.services.resource_lease_service import ResourceLeaseService
from src.services.controlled_file_service import ControlledFiles
from src.services.firmware_upgrade_service import UPGRADE_SCHEMA, dispatch_upgrade, upgrade_result
from src.services.firmware_upgrade_validation_service import FirmwareUpgradeValidation


class CapabilityService:
    def __init__(self, directory, manager, snapshot, admissible=lambda owner, keys: True,
                 network_check=lambda requests: [], emit=lambda line: None, upgrade_dispatch=dispatch_upgrade,
                 released=lambda owner: None, tool_root=None, onu_configuration=None, enabled_modules=None, channel_commit=None, settings_commit=None,
                 resource_coordinator=None, project_context=None, status_service=None):
        available = frozenset(('devices', 'parameters', 'onu', 'configuration', 'channels', 'notifications', 'observations', 'updates', 'ai_data', 'extensions'))
        if enabled_modules is None:
            configured = os.environ.get('LINECHECK_CAPABILITY_MODULES')
            enabled_modules = available if configured is None else {v.strip() for v in configured.split(',') if v.strip()}
        self.enabled_modules = frozenset(enabled_modules)
        if self.enabled_modules - available:
            raise ValueError('未知业务模块开关：' + ','.join(sorted(self.enabled_modules - available)))
        self.registry, self.manager, self.snapshot, self.emit = CapabilityRegistry(), manager, snapshot, emit
        if self.enabled_modules != available:
            self.emit('[能力目录] 本次启动停用模块：' + ','.join(sorted(available - self.enabled_modules)))
        self.resources = ResourceLeaseService(admissible, released, coordinator=resource_coordinator,
            project_id=project_context.identity.project_id if project_context else "",
            project_name=project_context.identity.name if project_context else "")
        self.project_context = project_context
        self.metrics = CapabilityMetrics(directory, emit=emit)
        self.jobs = CapabilityJobs(directory, self.resources, emit, self.metrics, project_context=project_context,
                                   status_service=status_service)
        from src.services.capability_scope_service import CapabilityScopes
        self.scopes = CapabilityScopes(self.jobs)
        self.files = ControlledFiles(Path(directory) / "workspace")
        self.upgrades = FirmwareUpgradeValidation(manager, snapshot, directory, network_check, emit)
        self.upgrade_dispatch = upgrade_dispatch
        self._register()
        from src.services.controlled_host_service import ControlledHost
        self.host = ControlledHost(self)
        self.devices = None
        if tool_root is not None:
            if 'devices' in self.enabled_modules:
                from src.services.capability_device_services import DeviceCapabilities
                self.devices = DeviceCapabilities(self, tool_root)
            if 'configuration' in self.enabled_modules:
                from src.services.capability_configuration_service import ConfigurationCapabilities
                self.configuration = ConfigurationCapabilities(self, tool_root)
                from src.services.capability_settings_service import SettingsCapabilities
                self.settings = SettingsCapabilities(self, tool_root, settings_commit, onu_configuration)
            if 'channels' in self.enabled_modules:
                from src.services.capability_channel_service import ChannelCapabilities
                self.channel_configuration = ChannelCapabilities(self, tool_root, channel_commit)
            if 'notifications' in self.enabled_modules:
                from src.services.capability_notification_service import NotificationCapabilities
                self.notifications = NotificationCapabilities(self, tool_root)
            if 'observations' in self.enabled_modules and self.devices is not None:
                from src.services.capability_observation_service import ObservationCapabilities
                self.observations = ObservationCapabilities(self, tool_root)
            if 'updates' in self.enabled_modules:
                from src.services.capability_update_service import UpdateCapabilities
                self.updates = UpdateCapabilities(self, project_context.source_root if project_context else tool_root)
            if 'parameters' in self.enabled_modules and self.devices is not None:
                from src.services.capability_parameter_services import ParameterCapabilities
                self.parameters = ParameterCapabilities(self)
            if 'onu' in self.enabled_modules:
                from src.services.capability_onu_services import OnuCapabilities
                self.onu = OnuCapabilities(self, tool_root, onu_configuration)
        from src.services.capability_extension_service import CapabilityExtensions
        self.extensions = CapabilityExtensions(self)
        if 'extensions' in self.enabled_modules:
            self.extensions.restore()

    def _register(self):
        add = self.registry.register
        add(CapabilitySpec("firmware.upgrade", "样机升级", "通过原样机升级业务执行全包或页面升级；直接调用即可，内部实时校验。缺少适配依据时返回一次确认要求。",
            UPGRADE_SCHEMA, self._upgrade, risk="dangerous", execution_mode="job",
            resource_requirements=("device-business", "channel", "serial", "adapter", "power"), cancellation="safe_boundary"))
        add(CapabilitySpec("channels.list", "查询通道", "读取当前已授权通道的实时配置。", object_schema(), self._channels))
        add(CapabilitySpec("jobs.resolve_unknown", "核实未知任务结果", "提交现场核实依据，由本地负责人审阅后解除未知状态；不执行设备操作或自动重试。",
            object_schema({"job_id": dict(type="string", minLength=1),
                "outcome": dict(type="string", enum=["succeeded", "failed", "not_executed"]),
                "evidence": dict(type="string", minLength=1, maxLength=4000)}, ("job_id", "outcome", "evidence")),
            lambda a, auth: self.jobs.resolve_unknown(a["job_id"], auth, a["outcome"], a["evidence"]), risk="modify",
            resource_scope=lambda a: dict(id="job-reconciliation:" + a["job_id"] + ":" + fingerprint(a),
                                         job_id=a["job_id"], outcome=a["outcome"], evidence=a["evidence"])))
        add(CapabilitySpec("files.information", "文件信息与哈希", "查询文件大小与SHA256，不执行文件。",
            object_schema({"path": dict(type="string", minLength=1)}, ("path",)),
            lambda a, auth: self.files.information(a["path"])))
        add(CapabilitySpec("files.list", "查找文件", "查询指定目录单层文件名和大小，不执行文件。",
            object_schema({"path": dict(type="string", minLength=1), "pattern": dict(type="string", maxLength=200)}, ("path",)),
            lambda a, auth: self.files.list(a["path"], a.get("pattern", "*"))))
        add(CapabilitySpec("files.write_artifact", "保存文本产物", "在本项目受控工作区保存报告或文本数据；不改源码和业务配置。",
            object_schema({"path": dict(type="string", minLength=1), "content": dict(type="string", maxLength=1024*1024),
                           "expected_sha256": dict(type="string", maxLength=64)}, ("path", "content")),
            lambda a, auth: self.files.write(a["path"], a["content"], a.get("expected_sha256", "")), risk="modify"))

    def _channels(self, arguments, authority):
        return dict(channels=[c for c in self.snapshot()["channels"]
                              if int(c["section"].rsplit("_", 1)[1]) in authority.channels])

    def validate(self, identifier, arguments, authority, *, check_scope=True):
        spec = self.registry.validate(identifier, arguments)
        authority.check(arguments.get("channel_ids", ()))
        if authority.source not in spec.sources:
            raise CapabilityError("source_forbidden", "当前来源不能执行此控制面操作")
        if check_scope and spec.resource_scope is not None:
            self.scopes.require(authority, spec.resource_scope(arguments))
        if identifier == "firmware.upgrade":
            value = self.upgrades.validate(arguments, authority)
            return dict(ok=True, firmware=value["firmware"], resources=value["resources"],
                        channel_ids=value["arguments"]["channel_ids"])
        return dict(ok=True, capability_id=identifier, risk=spec.risk)

    @maintenance_operation
    def execute(self, identifier, arguments, authority):
        spec = self.registry.validate(identifier, arguments)
        authority.check(arguments.get("channel_ids", ()), spec.risk)
        if authority.source not in spec.sources:
            raise CapabilityError("source_forbidden", "当前来源不能执行此控制面操作")
        if spec.resource_scope is not None:
            self.scopes.require(authority, spec.resource_scope(arguments))
        self.emit(f"[能力执行] {identifier}；来源={authority.source}；任务={authority.operation_id[:8]}")
        return spec.handler(arguments, authority)

    def _upgrade(self, arguments, authority):
        prepared = self.upgrades.validate(arguments, authority)
        def recheck():
            current = self.upgrades.validate(arguments, authority)
            if current["binding"] != prepared["binding"]:
                raise CapabilityError("target_changed", "预检后目标或固件发生变化，未启动升级")
        def runner(context):
            context.stop.checkpoint()
            requests = self.upgrades.pin(prepared)
            # Existing engines own all Boot/transfer/write/retry/timing decisions.
            context.event("engine", "调用现有升级引擎；未增加刷后系统登录", dispatched=True)
            phases, phase_lock = {}, threading.RLock()
            def output(*values):
                line = ' '.join(str(v) for v in values)
                target = str(values[0]) if len(values) > 1 else 'batch'
                # Display projection only: recognized original engine messages are
                # evidence of a phase, never a new flash completion criterion.
                phase = None
                if '进入 Boot 方式' in line or '进入 boot' in line or 'UserName 提示符' in line:
                    phase = 'entering_boot'
                if '准备 TFTP 网卡' in line or '准备传输环境' in line:
                    phase = 'preparing_transfer'
                if '服务已监听' in line or '上传固件到设备' in line:
                    phase = 'transferring'
                if '触发 UBUS 升级命令' in line:
                    phase = 'flashing_requested'
                if 'done + write' in line:
                    phase = 'flash_markers_observed'
                if '开始观察 boot 重启标记' in line or '等待设备重启' in line or '已发送 reset' in line:
                    phase = 'waiting_reboot'
                if '尝试重新登录设备' in line or '设备已重新上线' in line:
                    phase = 'engine_verification'
                if '跳过最终系统登录' in line:
                    phase = 'verification_skipped'
                with phase_lock:
                    if phase:
                        phases[target] = phase
                    context.event(phases.get(target, 'engine'), line)
            items = self.upgrade_dispatch(requests, self.manager,
                parallel_count=prepared["arguments"]["parallel_count"], on_output=output,
                stop_control=context.stop)
            result = upgrade_result(items)
            context.event('engine_result', '原业务引擎返回；刷写/上线判据以原引擎结果为准')
            # An ordinary engine failure may be post-flash and cannot establish rollback.
            if result["state"] == "failed":
                result["state"] = "unknown"
                result["notice"] = "原引擎返回失败；设备实际刷写结果需核实，不自动重刷"
            return result
        recorded = dict(prepared["arguments"], firmware_sha256=prepared["firmware"]["sha256"], target_binding=prepared["binding"])
        return self.jobs.start("firmware.upgrade", recorded, authority, prepared["resources"], runner, recheck=recheck)

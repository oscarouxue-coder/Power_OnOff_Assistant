"""Parameter-table and write adapters to the shared application service."""
from dataclasses import asdict
from pathlib import Path

from line_check_assistant.network_ops import adapter_alias_from_display, factory_bind_ip_for, factory_device_host_for
from src.core.sample_parameter_table import load_parameter_records, generate_parameter_records, save_parameter_records_xlsx
from src.models.sample_parameter_models import SampleParameterWriteRequest, ParameterGenerationTemplate
from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema
from src.services.capability_device_services import CHANNEL_PROPERTIES, settings_schema
from src.services.sample_parameter_service import preflight_parameter_targets
from src.services.sample_parameter_application_service import run_sample_parameter_batch


class ParameterCapabilities:
    def __init__(self, service):
        self.service = service
        self.runner = run_sample_parameter_batch
        table = dict(CHANNEL_PROPERTIES, table_path=dict(type="string", minLength=1))
        service.registry.register(CapabilitySpec("parameters.preflight", "参数表预检", "按当前通道和真实参数表预检，不执行设备操作。",
            object_schema(table, ("channel_ids", "table_path")), self.preflight))
        service.registry.register(CapabilitySpec("parameters.generate", "生成批量参数表", "通过现有生成规则在受控工作区保存xlsx参数表。",
            object_schema(dict(CHANNEL_PROPERTIES, output_name=dict(type="string", minLength=1),
                template=object_schema({
                    "sn_prefix": dict(type="string"), "xpon_prefix": dict(type="string"), "mac_prefix": dict(type="string"),
                    "ssid_24_prefix": dict(type="string"), "ssid_5_prefix": dict(type="string"),
                    "suffix_length": dict(type="integer", minimum=1, maximum=64),
                    "fixed_values": dict(type="object", additionalProperties=True)},
                    ("sn_prefix", "xpon_prefix", "mac_prefix", "ssid_24_prefix", "ssid_5_prefix", "suffix_length"))),
                ("channel_ids", "output_name", "template")), self.generate, risk="modify"))
        service.registry.register(CapabilitySpec("parameters.write", "批量写样机参数", "复用GUI的网络准备/UBUS/Telnet/串口及原15项写参流水线，异步返回任务编号。",
            object_schema(dict(table, parallel_count=dict(type="integer", minimum=1, maximum=8),
                              clear_parameters=dict(type="boolean"), exit_aging=dict(type="boolean")),
                          ("channel_ids", "table_path")), self.write, risk="dangerous", execution_mode="job",
            resource_requirements=("device-business", "serial", "adapter"), cancellation="cooperative"))

    def _prepare(self, arguments, authority, snapshot=None, *, records=None):
        snapshot, channels = self.service.devices.selected(arguments, authority, snapshot)
        if records is None:
            records = load_parameter_records(Path(arguments["table_path"]).expanduser().resolve())
        ports, indexed = [], {}
        from src.core.serial_transport import vlan_to_serial_port
        for channel in channels:
            vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).lower()
            port = channel.serial_port or vlan_to_serial_port(vlan)
            ports.append((vlan, port))
            indexed[vlan] = channel
        result = preflight_parameter_targets(records, ports)
        return snapshot, result, indexed

    def preflight(self, arguments, authority):
        snapshot, result, indexed = self._prepare(arguments, authority)
        return dict(ok=result.ok, errors=list(result.errors), warnings=list(result.warnings),
                    targets=[dict(vlan=t.vlan, serial_port=t.serial_port, source_row=t.record.source_row) for t in result.targets])

    def generate(self, arguments, authority):
        snapshot, channels = self.service.devices.selected(arguments, authority)
        output = (self.service.files.workspace / arguments["output_name"]).resolve()
        if self.service.files.workspace not in output.parents or output.suffix.lower() != ".xlsx" or output.exists():
            raise CapabilityError("invalid_output", "参数表须为工作区内新的xlsx文件，不覆盖未经核对的文件")
        values = arguments["template"].get("fixed_values", {})
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
            raise CapabilityError("invalid_parameters", "固定参数必须为文本映射")
        records = generate_parameter_records([adapter_alias_from_display(c.vlan_name or c.adapter_alias).lower() for c in channels],
                                              ParameterGenerationTemplate(**arguments["template"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        save_parameter_records_xlsx(output, records)
        self.service.emit(f"[能力执行] 参数表已生成：{output}，{len(records)}台")
        return dict(ok=True, path=str(output), count=len(records))

    def write(self, arguments, authority, *, confirmed_table=None, observe_serial=None):
        # Capture the exact preflight table, then recheck the file under admission.
        # The worker consumes these records, never a different later file at this path.
        table_info = self.service.files.information(arguments['table_path'])
        records = None
        if confirmed_table is not None:
            expected_digest, records = confirmed_table
            if table_info['sha256'] != expected_digest:
                raise CapabilityError('parameter_table_changed', '参数表自本机确认后发生变化，未写参')
        prepared = self._prepare(arguments, authority, records=records)
        def precheck():
            if self.service.files.information(arguments['table_path'])['sha256'] != table_info['sha256']:
                raise CapabilityError('parameter_table_changed', '参数表自预检后发生变化，未写参')
        precheck()
        if not prepared[1].ok:
            raise CapabilityError("parameter_preflight_failed", "; ".join(prepared[1].errors))
        def run(context, snapshot, channels):
            _, result, indexed = prepared
            if not result.ok:
                raise CapabilityError("parameter_preflight_failed", "; ".join(result.errors))
            options = snapshot["upgrade_settings"]
            requests, network = [], {}
            for target in result.targets:
                channel = indexed[target.vlan.lower()]
                bind_ip, host = channel.network_card_ip.strip(), channel.device_manage_ip.strip()
                if confirmed_table is not None and not host:
                    host = snapshot.get('device_ip', '').strip()
                if bind_ip and host and bind_ip == host:
                    raise CapabilityError("invalid_target", "写参源IP与样机IP相同")
                factory_bind = channel.factory_bind_ip or (factory_bind_ip_for(bind_ip) if bind_ip else "")
                factory_host = channel.factory_device_host or (factory_device_host_for(host) if host else "")
                if bind_ip and host and (not factory_bind or not factory_host):
                    raise CapabilityError("invalid_target", "写参缺少工厂模式网络配置")
                requests.append(SampleParameterWriteRequest(target.vlan, target.serial_port,
                    options.get("parameter_initial_username", ""), options.get("parameter_initial_password", ""),
                    target.record.values, bind_ip=bind_ip, device_host=host, factory_bind_ip=factory_bind,
                    factory_device_host=factory_host, clear_parameters=arguments.get("clear_parameters", False),
                    exit_aging=arguments.get("exit_aging", False)))
                network[target.vlan.lower()] = (channel.adapter_alias or channel.vlan_name, channel.subnet_mask)
            context.stop.checkpoint()
            context.event("parameters", "调用共用写参应用服务，保留原重试/等待/二次登录/读回校验", dispatched=True)
            runner_args = (requests, arguments.get("parallel_count", 1), context.stop.event,
                           self.service.manager, network, lambda line: context.event("parameters", line))
            if observe_serial is None:
                values = self.runner(*runner_args)
            else:
                with observe_serial(requests) as ready:
                    values = self.runner(*runner_args, on_session_ready=ready)
            items = []
            for value in values:
                item = asdict(value)
                item.pop("request", None)
                items.append(item)
            ok = bool(values) and all(v.ok for v in values)
            return dict(ok=ok, state="unknown" if context.stop.is_set() and not ok else "stopped" if context.stop.is_set() else "succeeded" if ok else "unknown", items=items)
        return self.service.devices._job("parameters.write", arguments, authority, run,
            recorded_extra=dict(table_sha256=table_info['sha256']), precheck=precheck)

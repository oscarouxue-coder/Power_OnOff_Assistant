"""Continuous service monitoring runner for an admitted, version-bound project job."""
import hashlib
import ipaddress
import json
import time
from pathlib import Path

from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.network_ops import adapter_alias_from_display
from src.core.aging_lan_ping import bound_echo
from src.core.serial_transport import vlan_to_serial_port
from src.core.wireless_ip import adapters_ipv4, validate_remote_ipv4
from src.models.project_profile import dut_resource_keys
from src.models.project_review import ReviewRequired
from src.models.upgrade_stop import UpgradeStopped
from src.models.wifi_test_models import WifiEnvironmentError
from src.services.project_profile_store import active_project_duts, read_project_profile
from src.services.project_store import configuration_digest
from src.services.service_aging_history import ServiceAgingHistory


CAPABILITY = 'service_aging.start'


def _interface_binding(row, channel, interfaces):
    if channel is None or not channel.enabled:
        raise ValueError('没有已启用的 LAN 通道映射')
    alias = adapter_alias_from_display(channel.adapter_alias or channel.vlan_name)
    expected = adapter_alias_from_display(row['network_adapter'])
    if not alias or (expected and expected.casefold() != alias.casefold()):
        raise ValueError('DUT 与通道的网卡映射不一致')
    if row['vlan'] and channel.vlan_name and row['vlan'].casefold() != channel.vlan_name.casefold():
        raise ValueError('DUT 与通道的 VLAN 映射不一致')
    try:
        source, target = (str(ipaddress.IPv4Address(s)) for s in (channel.network_card_ip, channel.device_manage_ip))
    except ValueError:
        raise ValueError('LAN 通道缺少源地址或 DUT 管理 IPv4') from None
    validate_remote_ipv4(target, interfaces)
    owners = [i for i in interfaces if source in (a for a, _ in i['addresses'])]
    if len(owners) != 1:
        raise ValueError('无法唯一核实源 IPv4 所属网卡')
    nic = owners[0]
    if not nic['up'] or not nic['guid'] or nic['index'] <= 0 or nic['name'].casefold() != alias.casefold():
        raise ValueError('所选网卡与源 IPv4 的当前接口不匹配')
    return dict(name=nic['name'],guid=nic['guid'].strip('{}').casefold(),index=nic['index'],source=source,target=target)


class ServiceAging:
    def __init__(self, context, *, clock=time.time, monotonic=time.monotonic, inventory=adapters_ipv4,
                 probe=bound_echo, sample_interval=30, wait=None, emit=lambda message: None, emit_event=None):
        self.context, self.monotonic, self.inventory = context, monotonic, inventory
        self.probe, self.interval, self.emit = probe, float(sample_interval), emit
        self.emit_event = emit_event
        if self.interval <= 0:
            raise ValueError('采样间隔必须大于零')
        self.wait = wait or (lambda stop, delay: stop.event.wait(delay))
        self.history = ServiceAgingHistory(context, clock)

    def _plan(self, directory, *, require_legacy_identity=False):
        profile = read_project_profile(directory)
        if not profile or profile['test_type'] != 'service_aging':
            raise ReviewRequired('wrong_test_type', '持续监测需要已保存的全业务老化项目', 'wizard', 'test_type')
        settings = profile['type_config']
        collectors = settings['collectors']
        managed = profile.get('environment_channels', False)
        active = active_project_duts(profile, directory)
        if managed and not active:
            raise ReviewRequired('invalid_target', '请先在环境配置启用并保存测试通道', 'channels', 'enabled')
        if not active or not collectors:
            raise ReviewRequired('configuration_incomplete', '请先保存本项目的 DUT 和需要检查的业务',
                                 'wizard' if not collectors else 'channels', 'collectors' if not collectors else 'dut')
        if require_legacy_identity and not managed:
            for dut in active:
                if not dut['hardware_id']:
                    raise ReviewRequired('invalid_target', f"{dut['label']} 缺少 DUT 实物标识，请核对配置",
                                         'channels', 'dut', channels=(dut['channel'],) if dut['channel'] else ())
        channels, interfaces, inventory_error = {}, (), ''
        if managed or 'lan_ping' in collectors:
            for c in ChannelConfigStore(Path(directory) / 'network_card_ip.ini').load():
                suffix = c.section.rsplit('_', 1)[-1]
                if suffix.isdigit():
                    channels[int(suffix)] = c
        if managed:
            missing = {n for n, channel in channels.items() if channel.enabled} - {dut['channel'] for dut in active}
            if missing:
                names = '、'.join(f'CH{number:02d}' for number in sorted(missing))
                raise ReviewRequired('invalid_target', f'{names} 缺少保存的 DUT 映射，请重新确认并保存环境配置',
                                     'channels', 'dut', channels=sorted(missing))
        if 'lan_ping' in collectors:
            try:
                interfaces = self.inventory()
            except (OSError, RuntimeError, ValueError, WifiEnvironmentError) as error:
                inventory_error = '网卡身份无法核实：' + str(error)
        feed_collectors = settings.get('feed_collectors', [])
        if any(c not in collectors or c in ('lan_ping', 'cpu_memory') for c in feed_collectors):
            raise ReviewRequired('invalid_parameters', '现场文件只可订阅本批次已选的业务采集项', 'wizard', 'collectors')
        duts = []
        resources = {'device-business', *dut_resource_keys(active)}
        for row in active:
            binding, reason = None, inventory_error
            channel = channels.get(row['channel'])
            if managed:
                resources.add(f"channel:{row['channel']}")
                alias = adapter_alias_from_display(channel.adapter_alias or channel.vlan_name)
                if alias:
                    resources.add('adapter:' + alias)
                try:
                    port = channel.serial_port or vlan_to_serial_port(alias.lower())
                except ValueError:
                    port = ''
                if port:
                    resources.add('serial:' + port)
            if 'lan_ping' in collectors and not reason:
                try:
                    expected = dict(row, network_adapter='', vlan='') if managed else row
                    binding = _interface_binding(expected, channel, interfaces)
                except (ValueError, RuntimeError, WifiEnvironmentError) as error:
                    reason = str(error)
            if binding:
                resources.update(('adapter:' + binding['name'], 'adapter:' + binding['guid']))
            dut = dict(dut_id=row['dut_id'], label=row['label'], channel=row['channel'], binding=binding, reason=reason)
            if feed_collectors and row.get('hardware_id'):
                dut['hardware_id'] = row['hardware_id']
            duts.append(dut)
        data = dict(project_id=self.context.identity.project_id, revision=self.context.identity.revision,
                    target_hours=settings['target_hours'], collectors=collectors, duts=duts,
                    resources=sorted(resources), channel_ids=sorted(row['channel'] for row in duts if row['channel'] is not None))
        if feed_collectors:
            data['feed_collectors'] = list(feed_collectors)
        data['binding'] = hashlib.sha256((configuration_digest(directory) + json.dumps(data, sort_keys=True)).encode()).hexdigest()
        return data

    def prepare(self, *, require_legacy_identity=False):
        return self._plan(self.context.saved_root / 'Auto_power_on_off_tool/config',
                          require_legacy_identity=require_legacy_identity)

    def _sample(self, dut, job):
        binding = dut['binding']
        def verify():
            live = self.inventory()
            owners = [i for i in live if binding['source'] in (a for a, _ in i['addresses'])]
            if len(owners) != 1 or not owners[0]['up'] or owners[0]['index'] != binding['index'] or (
                    owners[0]['guid'].strip('{}').casefold() != binding['guid']):
                raise ValueError('接口身份或源 IPv4 已变化，无法核实本次采样')
            validate_remote_ipv4(binding['target'], live)
        try:
            verify()
            reply = self.probe(binding, job.stop, lambda msg: job.event('service_aging', msg, dispatched=True,
                dut_id=dut['dut_id'], channel=dut['channel'], step='lan_ping'))
            verify()
            return ('healthy', '收到匹配 ICMP 回包') if reply else ('abnormal', '本次 ICMP Echo 超时')
        except (ValueError, RuntimeError, OSError, WifiEnvironmentError) as error:
            return 'unknown', '采样未能确认：' + str(error)

    def run(self, job, plan):
        if job.project_id != self.context.identity.project_id:
            raise ValueError('监测任务项目不匹配')
        frozen = self._plan(Path(job.configuration_root) / 'Auto_power_on_off_tool/config')
        if frozen != plan:
            raise ValueError('运行快照或网卡身份已变化，请重新核对')
        start = self.monotonic()
        probes = [d for d in plan['duts'] if d['binding']]
        freshness = self.interval * 2 + len(probes) * 2
        started_at = self.history.begin(job.job_id, plan, freshness)
        target = plan['target_hours'] * 3600 if plan['target_hours'] else None
        state = 'interrupted'
        try:
            job.event('service_aging', f"开始持续监测 · {len(plan['duts'])} 台 DUT")
            reader = None
            if plan.get('feed_collectors'):
                from src.services.service_aging_feed import AgingFeedMonitor
                reader = AgingFeedMonitor(self.context, job, plan, self.history, started_at, freshness)
            for dut in plan['duts']:
                if dut['reason']:
                    job.event('service_aging', f"{dut['label']} LAN Ping 未接入：{dut['reason']}",
                              dut_id=dut['dut_id'], channel=dut['channel'], step='lan_ping', level='WARN')
            while not job.stop.is_set():
                elapsed = self.monotonic() - start
                if target is not None and elapsed >= target:
                    state = 'target_reached'
                    break
                for dut in probes:
                    job.stop.checkpoint()
                    outcome, detail = self._sample(dut, job)
                    job.stop.checkpoint()
                    self.history.observe(job.job_id, dut['dut_id'], 'lan_ping', outcome, detail, '',
                                         kind='sample', elapsed=self.monotonic() - start)
                    job.event('service_aging', f"{dut['label']} · {detail}", dut_id=dut['dut_id'],
                              channel=dut['channel'], step='lan_ping', level='INFO' if outcome == 'healthy' else 'WARN')
                if reader is not None:
                    reader.poll()
                elapsed = self.monotonic() - start
                self.history.tick(job.job_id, elapsed)
                self.wait(job.stop, self.interval if target is None else max(0, min(self.interval,target-elapsed)))
            if state != 'target_reached':
                state = 'stopped'
        except UpgradeStopped:
            state = 'stopped'
        finally:
            self.history.tick(job.job_id, self.monotonic() - start, state)
        message = '已到计划时长，待核对末检及原始证据' if state == 'target_reached' else '持续监测已停止'
        job.event('service_aging', message)
        return dict(ok=state=='target_reached',state='succeeded' if state=='target_reached' else 'stopped',
                    message=message,accepted=False)

    def snapshot(self, job_id=None):
        return self.history.snapshot(job_id)

    def history_page(self, job_id, *, before_id=None, kind=None, limit=100):
        return self.history.history_page(job_id, before_id=before_id, kind=kind, limit=limit)

    def list_runs(self, *, before_id=None, limit=50):
        return self.history.list_runs(before_id=before_id, limit=limit)

    def export_history(self, job_id, destination):
        count = self.history.export_history(job_id, destination)
        message = f'[持续老化] {job_id} · 已导出 {count} 条证据记录'
        if self.emit_event:
            self.emit_event(message, job_id=job_id, step='export')
        else:
            self.emit(message)
        return count

    def record(self, job_id, dut_id, collector, outcome, evidence, operator, *, kind='observation'):
        if kind not in ('observation','daily','final'):
            raise ValueError('手动记录类型无效')
        self.history.observe(job_id,dut_id,collector,outcome,evidence,operator,kind=kind)
        message = f'[持续老化] {job_id} · {dut_id} · {collector} · {kind} · {outcome}'
        if self.emit_event:
            self.emit_event(message, job_id=job_id, dut_id=dut_id, step=collector,
                            level='INFO' if outcome == 'healthy' else 'WARN')
        else:
            self.emit(message)
        return self.snapshot(job_id)

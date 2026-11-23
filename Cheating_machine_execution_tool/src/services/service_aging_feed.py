"""Consume opted-in field observations for one frozen, already-admitted aging job."""
from collections import Counter

from src.services.aging_observation_source import JsonlObservationSource, write_observation_manifest


class AgingFeedMonitor:
    MAX_PAGES_PER_TICK = 8

    def __init__(self, context, job, plan, history, started_at, freshness):
        self.context = context
        self.job = job
        self.plan = plan
        self.history = history
        self.started_at = started_at
        self.freshness = freshness
        self.channels = {dut['dut_id']: dut['channel'] for dut in plan['duts']}
        self.source = None
        self.status = ''
        self._open()

    def _open(self):
        try:
            path = write_observation_manifest(self.context, self.job.job_id, self.plan, self.started_at)
            self.source = JsonlObservationSource(self.context, self.job.job_id, self.plan,
                started_at=self.started_at, clock=self.history.clock, max_age=self.freshness)
        except (OSError, ValueError) as error:
            self._status('unavailable', f'现场采集输入不可用：{error}')
            return
        self.job.event('service_aging', f'现场采集端批次映射：{path}', step='observation_feed')

    def _status(self, status, message):
        if self.status != status:
            if self.status and status in ('unavailable', 'waiting', 'reset'):
                self.history.feed_gap(self.job.job_id)
            self.status = status
            self.job.event('service_aging', message, step='observation_feed',
                           level='WARN' if status in ('unavailable', 'reset') else 'INFO')
        elif status == 'reset':
            self.history.feed_gap(self.job.job_id)

    def poll(self):
        self.job.stop.checkpoint()
        if self.source is None:
            self._open()
            if self.source is None:
                return
        for _ in range(self.MAX_PAGES_PER_TICK):
            self.job.stop.checkpoint()
            if not self._read_page():
                break

    def _read_page(self):
        try:
            batch = self.source.poll()
        except (OSError, ValueError) as error:
            self.source = None
            self._status('unavailable', f'现场采集输入不可用：{error}')
            return
        messages = dict(ready='正在读取现场采集记录', waiting='等待当前批次的现场采集文件',
                        unavailable='现场采集输入暂不可读', reset='现场采集文件已更换，重新核验记录')
        if self.status in ('ready', 'reset') and batch.status in ('waiting', 'unavailable'):
            self.source = None  # A removed directory may also have removed the operator's batch manifest.
        self._status(batch.status, messages[batch.status])
        rejected = Counter(batch.rejected)
        for event in batch.events:
            self.job.stop.checkpoint()
            reason = self.history.observe(self.job.job_id, event.dut_id, event.collector, event.outcome,
                                          event.evidence, '', kind='sample', feed_event=event)
            if reason:
                rejected[reason] += 1
                continue
            message = f'现场采集 {event.event_id} · {event.collector} · {event.outcome}'
            if event.collector == 'dut_presence':
                status = {'healthy': '在线', 'abnormal': '离线', 'unknown': '未知'}[event.outcome]
                parts = [f'设备观测 {event.event_id}', status]
                if event.boot_id is not None:
                    parts.append(f'启动标识 {event.boot_id}')
                if event.uptime_seconds is not None:
                    parts.append(f'上报开机时长 {event.uptime_seconds:g} 秒')
                message = ' · '.join(parts)
            self.job.event('service_aging', message,
                           dut_id=event.dut_id, channel=self.channels[event.dut_id], step=event.collector,
                           level='INFO' if event.outcome == 'healthy' else 'WARN')
        if rejected:
            detail = '、'.join(f'{key} {count}' for key, count in sorted(rejected.items()))
            self.job.event('service_aging', '现场采集忽略记录：' + detail, step='observation_feed', level='WARN')
        return self.source is not None and batch.has_more

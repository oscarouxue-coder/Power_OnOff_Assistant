"""Request a safe stop for one persisted job owned by the current process."""
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_jobs import TERMINAL


class QtJobControl:
    def __init__(self, execution):
        self.execution = execution

    def stop_active(self, identifier):
        execution = self.execution
        if execution.closed or execution.closing or execution.workspace_close_requested():
            raise CapabilityError('unavailable', '项目正在关闭，未提交安全停止')

        if execution.capabilities is None:
            raise CapabilityError('job_not_active', '当前进程没有该任务的有效执行记录。')
        jobs = execution.capabilities.jobs
        with jobs.lock:
            row = jobs._row(identifier)
            worker = jobs.threads.get(identifier)
            if row['state'] in TERMINAL or not worker or not worker.is_alive() or identifier not in jobs.controls:
                raise CapabilityError('job_not_active', '该任务已经结束或由其它进程管理，未请求停止。')
            if row['state'] == 'stop_requested':
                return dict(job_id=identifier, state='stop_requested', notice='已请求安全停止，等待原任务收尾。')
            authority = self._authority(row)
        if identifier in execution.jobs:
            return execution.stop(identifier)
        execution._log('[任务历史] 本机已确认，向原任务请求安全停止', job_id=identifier)
        return jobs.cancel(identifier, authority)

    @staticmethod
    def _authority(row):
        channels = tuple(row['request'].get('arguments', {}).get('channel_ids', ()))
        return CapabilityAuthority(row['principal'], 'local-operator', 'local-control', channels,
            source='gui', mode='full_access', grant_id='local-control', approved=True)

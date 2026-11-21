"""Local Qt review of one original durable Job; never submit or replay work."""
from contextlib import closing
import sqlite3
import uuid

from src.services.power_worker_lifetime import POWER_JOB_IDS, guard_power_worker_review
from src.models.capabilities import CapabilityAuthority, CapabilityError, fingerprint
from src.models.qt_log_history import HistoryJobReview, JOB_REVIEW_OUTCOMES
from src.services.capability_jobs import TERMINAL
from src.services.qt_log_history import job_database_path


class QtJobReview:
    def __init__(self, execution):
        self.execution = execution
        self.pending = None

    def _guard(self):
        execution = self.execution
        if execution.closed or execution.closing or execution.workspace_close_requested():
            raise CapabilityError('unavailable', '项目正在关闭，未提交核实')

    def _read(self, jobs, identifier):
        """Derive the same host-local identity as the legacy task manager."""
        row = jobs._row(identifier)
        worker = jobs.threads.get(identifier)
        if row['state'] != 'unknown' or (worker is not None and worker.is_alive()):
            raise CapabilityError('job_not_unknown', '只可核实已完成收尾且结果未知的任务')
        if row['capability_id'] in POWER_JOB_IDS:
            guard_power_worker_review(self.execution.context)
        channels = tuple(row['request'].get('arguments', {}).get('channel_ids', ()))
        authority = CapabilityAuthority(row['principal'], 'local-operator', 'local-control', channels,
            source='gui', mode='full_access', grant_id='local-control', approved=True)
        jobs.status(identifier, authority)
        return row, authority

    def prepare(self, identifier):
        self._guard()
        self.pending = None
        execution = self.execution
        database = job_database_path(execution.context)
        if not database.is_file():
            raise CapabilityError('job_not_found', '当前项目没有该任务的原历史库')
        # Verify the target in this project before opening the original runtime.
        # Its existing exclusive lease and recovery convert interrupted active rows.
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.25)) as connection:
                candidate = connection.execute('SELECT state FROM jobs WHERE id=?', (identifier,)).fetchone()
        except sqlite3.Error as error:
            raise CapabilityError('history_unavailable', '无法读取任务记录，未提交核实') from error
        if candidate is None:
            raise CapabilityError('job_not_found', '此任务不属于当前项目')
        if candidate[0] in TERMINAL - {'unknown'}:
            raise CapabilityError('job_not_unknown', '此任务已有终态，未更改结果')
        execution._ensure_runtime()
        jobs = execution.capabilities.jobs
        with jobs.lock:
            row, authority = self._read(jobs, identifier)
            review = HistoryJobReview(uuid.uuid4().hex, identifier, row['capability_id'], authority.channels)
            self.pending = (review, fingerprint(row))
        execution._log('[任务核实] 已读取待核实任务，等待本机确认', job_id=identifier)
        return review

    def cancel(self, token):
        if self.pending and self.pending[0].token == token:
            identifier = self.pending[0].job_id
            self.pending = None
            self.execution._log('[任务核实] 本机取消，未更改任务结果', job_id=identifier)

    def commit(self, token, outcome, evidence):
        self._guard()
        pending = self.pending
        if not pending or pending[0].token != token:
            raise CapabilityError('confirmation_expired', '任务核实确认已失效，请重新打开')
        self.pending = None
        review, original = pending
        if outcome not in dict(JOB_REVIEW_OUTCOMES) or not evidence.strip() or len(evidence) > 4000:
            raise CapabilityError('invalid_parameters', '请选择现场核实结果并填写 1–4000 字依据')
        execution = self.execution
        jobs = execution.capabilities.jobs
        job_database_path(execution.context)
        with jobs.lock:
            row, authority = self._read(jobs, review.job_id)
            if fingerprint(row) != original:
                raise CapabilityError('job_changed', '任务记录在审阅期间改变，请重新核对')
            execution._log('[任务核实] 本机已确认，提交原任务核实服务', job_id=review.job_id)
            try:
                result = jobs.resolve_unknown(review.job_id, authority, outcome, evidence.strip())
            except (OSError, RuntimeError, sqlite3.Error) as error:
                execution._log('[任务核实] 原服务未确认核实完成，请核对任务及资源保护', 'ERROR', job_id=review.job_id)
                raise CapabilityError('review_unconfirmed', '原服务未确认核实完成，请核对任务及资源保护') from error
        item = execution.jobs.get(review.job_id)
        if item is not None:
            item['drained'] = False
        execution._log('[任务核实] 原服务已保存现场核实结论', job_id=review.job_id)
        return result['state']

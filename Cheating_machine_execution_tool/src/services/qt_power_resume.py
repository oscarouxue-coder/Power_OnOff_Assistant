"""Bind Qt recovery to the original live or finished power-test session."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import RLock
import time
import uuid

from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.project_review import ReviewRequired
from src.services.capability_jobs import TERMINAL
from src.services.power_test_resume_service import ResumeRejected


@dataclass(frozen=True)
class ResumeConfirmation:
    token: str
    parent: str
    run: str
    channel: int
    completed: int
    total: int
    live: bool
    created: float


class QtPowerResume:
    def __init__(self, execution):
        self.execution = execution
        self.lock = RLock()
        self.projection = None
        self.live = False
        self.pending = None
        self.submitted = set()
        self.recovery_job = ''
        self.recovery_channel = 0
        self.waiting = deque()
        self.series_jobs = set()

    @property
    def has_waiting(self):
        return bool(self.waiting)

    def register(self):
        runtime = self.execution.capabilities
        runtime.devices.gui_pipeline_power_scope = self.pipeline_scope
        runtime.registry.register(CapabilitySpec('aging.qt_resume.confirm', '确认本机失败轮次续跑',
            '确认本机已预检的单通道，复用原批次续跑和停止服务',
            object_schema({'token': dict(type='string', minLength=32, maxLength=32)}, ('token',)),
            self.confirm, risk='dangerous', sources=('gui',), execution_mode='job', cancellation='cooperative',
            resource_requirements=('device-business', 'channel', 'adapter', 'power')))

    @contextmanager
    def pipeline_scope(self, projection):
        with self.lock:
            self.projection = projection
            self.live = True
            self.submitted.clear()
            self.recovery_job = ''
            self.series_jobs.clear()
        try:
            yield
        finally:
            with self.lock:
                self.live = False
                session = projection.power_test_resume_session
            # A live submission may fall back just as its original process
            # exits. Keep the original job, stop event and lease until it ends.
            while session is not None and session.is_recovering:
                time.sleep(.05)

    def _session(self):
        projection = self.projection
        if projection is None:
            return '', None
        return projection.context.job_id, projection.power_test_resume_session

    def log_session(self, owner):
        with self.lock:
            parent, session = self._session()
            return session if parent == owner else None

    def _own_recovery(self, parent):
        return bool(self.recovery_job and self.execution.latest == parent
                    and (self.waiting or not self.execution.jobs_idle))

    def _candidate(self, number):
        parent, session = self._session()
        execution = self.execution
        if (execution.closing or execution.closed or execution.workspace_close_requested()
                or execution.editor_open or execution.workspace.maintenance.active
                or execution.other_power_blocked() or session is None or parent not in execution.jobs
                or execution.jobs[parent]['binding'] is None or not session.can_resume(number)):
            raise ReviewRequired('resume_unavailable', '所选通道当前不满足原续跑条件，请等待或重新核对',
                                 'project', 'channel', channels=(number,))
        if any(request.channel == number for request, _ in self.waiting):
            raise ReviewRequired('resume_duplicate', '该通道已在等待续跑', 'project', 'channel', channels=(number,))
        if self.live:
            if session.original_done or parent != execution.latest:
                raise CapabilityError('resource_busy', '原全流程仍在收尾，请等待后重新确认')
        elif not session.original_done or (not execution.jobs_idle and not self._own_recovery(parent)):
            raise CapabilityError('resource_busy', '本项目任务仍在收尾，请等待后重新确认')
        elif self._own_recovery(parent) and number == self.recovery_channel and not execution.jobs_idle:
            raise CapabilityError('resume_duplicate', '该通道的续跑任务仍在收尾')
        elif session.is_recovering and not self._own_recovery(parent):
            raise CapabilityError('resource_busy', '原续跑仍在收尾，请等待后重新确认')
        return parent, session

    def preview(self, number):
        if type(number) is not int or not 1 <= number <= 16:
            raise CapabilityError('invalid_target', '必须明确选择一个通道')
        with self.lock:
            self.pending = None
            parent, session = self._candidate(number)
            binding = self.execution.jobs[parent]['binding']
            if self.execution.workspace.projects.dirty(self.execution.context) or self.execution._binding() != binding:
                raise ReviewRequired('configuration_changed', '项目配置与原批次不同，请重新发起完整测试', 'project', 'start')
            with session.lock:
                if not session.can_resume(number):
                    raise ReviewRequired('resume_unavailable', '续跑资格已变化', 'project', 'channel', channels=(number,))
                completed, total = session.completed[number], session.request.number_of_tests
                pending = ResumeConfirmation(uuid.uuid4().hex, parent, session.run_id, number,
                    completed, total, self.live, time.monotonic())
            self.pending = pending
            waiting = not self.live and self._own_recovery(parent)
        self.execution._log(f'[Qt通道续跑] 等待本机确认 CH{number:02d} 第 {completed + 1}/{total} 轮', job_id=parent)
        summary = '\n'.join(filter(None, (self.execution.context.identity.name,
            f'仅对 CH{number:02d} 执行上下电测试。保留已完成的 {completed} 轮，从第 {completed + 1}/{total} 轮继续。',
            '核对原配置。三项版本基准全空时跳过预检，部分填写时阻止启动，全部填写时须通过三项版本预检。',
            '确认后加入等待队列，前面的续跑收尾后再核对配置及资源。' if waiting else '',
            '前置全流程任务不会重跑。是否继续？')))
        return pending.token, summary

    def cancel(self, token):
        if self.pending and self.pending.token == token:
            self.pending = None
            self.execution._log('[Qt通道续跑] 已取消，未提交原任务')

    def confirm(self, arguments, authority):
        execution = self.execution
        with self.lock:
            pending, self.pending = self.pending, None
            if not pending or pending.token != arguments['token'] or time.monotonic() - pending.created > 120:
                raise CapabilityError('confirmation_expired', '续跑确认已失效，请重新核对')
            queue_request = not pending.live and self._own_recovery(pending.parent)
            original, session = self._validate(pending, authority, starting=not queue_request)
            parent, number = pending.parent, pending.channel
            if queue_request:
                self.waiting.append((pending, authority))
                execution._log(f'[Qt通道续跑] 已确认 CH{number:02d}，排队第 {len(self.waiting)} 位', job_id=parent)
                return self.recovery_job
            with session.lock:
                if self.live:
                    if session.original_done or session.completed[number] != pending.completed or not session.submit(number):
                        raise CapabilityError('resume_changed', '原批次已收尾或续跑状态变化，请重新确认')
                    self.submitted.add(number)
                    execution._log(f'[Qt通道续跑] 已确认 CH{number:02d}，由原批次续跑', job_id=parent)
                    return parent
            self.series_jobs.clear()
            return self._start_after_run(original, pending, session, authority)

    def _validate(self, request, authority, *, starting):
        execution = self.execution
        number = request.channel
        authority.check((number,), 'dangerous')
        parent, session = self._candidate(number)
        if (parent, session.run_id, self.live) != (request.parent, request.run, request.live):
            raise CapabilityError('resume_changed', '原批次或运行阶段已变化，请重新确认')
        original = execution.jobs[parent]
        owner = original['authority']
        if (authority.principal, authority.session_id) != (owner.principal, owner.session_id):
            raise CapabilityError('job_forbidden', '续跑确认与原操作员会话不符')
        if starting and not self.live:
            execution._prepare_guard(resume_handoff=True)
        binding = original['binding']
        if execution.workspace.projects.dirty(execution.context) or execution._binding() != binding:
            raise ReviewRequired('configuration_changed', '项目配置与原批次不同，未提交续跑', 'project', 'start')
        if starting:
            execution._verify_nics((number,), binding, expected=original['adapters'])
        try:
            session.ensure_config_unchanged()
        except ResumeRejected as error:
            raise CapabilityError('configuration_changed', str(error)) from None
        with session.lock:
            if not session.can_resume(number) or session.completed[number] != request.completed:
                raise ReviewRequired('resume_changed', '已完成轮次或通道资格变化，请重新确认',
                                     'project', 'channel', channels=(number,))
        return original, session

    def _discard_waiting(self, reason):
        if self.waiting:
            channels = '、'.join(f'CH{request.channel:02d}' for request, _ in self.waiting)
            self.waiting.clear()
            self.execution._log(f'[Qt通道续跑] {reason}，取消等待中的 {channels}', 'WARN', job_id=self.recovery_job)

    def stop_target(self, identifier):
        with self.lock:
            parent, session = self._session()
            if identifier not in self.series_jobs or not self._own_recovery(parent):
                return identifier
            self.pending = None
            self._discard_waiting('收到停止请求')
            # Also process a queued UI stop for the previous job if handoff
            # already happened before the refreshed run identifier was shown.
            session.stop()
            return self.recovery_job

    def begin_close(self):
        with self.lock:
            self.pending = None
            self._discard_waiting('项目正在关闭')

    def advance(self):
        execution = self.execution
        with self.lock:
            if not self.waiting:
                return
            if execution.closing or execution.workspace_close_requested():
                self._discard_waiting('工作区正在关闭')
                return
            if not execution.jobs_idle:
                return
            status = execution.jobs[self.recovery_job]['status'] or {}
            state = status.get('state')
            # The last worker may release its lease after poll read its state.
            # Revisit the queue on the next refresh with the terminal record.
            if state not in TERMINAL:
                return
            if state not in ('succeeded', 'failed'):
                self._discard_waiting('前一条续跑已停止或结果未知')
                return
            while self.waiting:
                request, authority = self.waiting.popleft()
                try:
                    original, session = self._validate(request, authority, starting=True)
                    self._start_after_run(original, request, session, authority)
                except CapabilityError as error:
                    execution._log(f'[Qt通道续跑] CH{request.channel:02d} 未启动：{error}', 'WARN', job_id=request.parent)
                except Exception as error:
                    execution._log(f'[Qt通道续跑] CH{request.channel:02d} 准入失败（{type(error).__name__}）', 'ERROR', job_id=request.parent)
                    self._discard_waiting('续跑任务准入异常')
                else:
                    return

    def _start_after_run(self, original, pending, session, authority):
        execution = self.execution
        parent, number, binding = pending.parent, pending.channel, original['binding']

        def check_closing():
            if execution.closing or execution.workspace_close_requested():
                raise CapabilityError('closing', '工作区正在关闭，未提交续跑')

        def run(context, _snapshot, _channels):
            context.stop.checkpoint()
            if execution.workspace_close_requested():
                return dict(ok=False, state='stopped', message='工作区正在关闭，未提交续跑')
            if not session.submit(number):
                state = 'stopped' if session.stop_event.is_set() else 'failed'
                return dict(ok=False, state=state, message='续跑状态已变化，未执行')
            try:
                context.event('aging_resume', f'已提交 CH{number:02d} 至原续跑会话', dispatched=True)
            finally:
                while session.is_recovering:
                    if context.stop.is_set() and not session.stop_event.is_set():
                        session.stop()
                    time.sleep(.05)
            with session.lock:
                ok = session.completed[number] == pending.total and number not in session.failed
            stopped = context.stop.is_set() or session.stop_event.is_set()
            state = 'stopped' if stopped else 'succeeded' if ok else 'failed'
            return dict(ok=state == 'succeeded', state=state)

        execution._admission_binding = binding
        try:
            job = execution.capabilities.devices._job('aging.resume',
                {'parent_job_id': parent, 'channel_ids': [number]}, authority, run, precheck=check_closing)['job_id']
        finally:
            execution._admission_binding = None
        execution.jobs[job] = dict(authority=authority, after=0, status=None, channels={}, progress=None,
            title='失败轮次续跑', operation='aging.resume')
        original['drained'] = False
        execution.latest = parent
        execution.parameters = original['parameters']
        self.recovery_job, self.recovery_channel = job, number
        self.series_jobs.add(job)
        execution._log(f'[Qt通道续跑] 已确认 CH{number:02d}，原批次结束后单通道续跑', job_id=job)
        return job

    def present(self, project):
        with self.lock:
            parent, session = self._session()
            execution = self.execution
            if session is None or parent not in execution.jobs:
                return project
            waiting = tuple(request.channel for request, _ in self.waiting)
            available = not (execution.closing or execution.workspace_close_requested() or execution.editor_open or project.dirty
                or execution.other_power_blocked() or execution.workspace.maintenance.active)
            if available and (self.live or execution.jobs_idle or self._own_recovery(parent)):
                reserved = set(waiting)
                if self._own_recovery(parent) and not execution.jobs_idle:
                    reserved.add(self.recovery_channel)
                with session.lock:
                    available = not session.original_done if self.live else session.original_done
                    channels = tuple(replace(c, can_resume=available and c.number not in reserved and session.can_resume(c.number))
                        for c in project.channels)
                project = replace(project, channels=channels)
            if execution.latest != parent:
                return project
            if self.recovery_job:
                status = execution.jobs[self.recovery_job]['status'] or {}
                state = status.get('state', 'queued')
                active = state not in TERMINAL or not execution.jobs_idle or bool(waiting)
                label = {'queued': '等待续跑', 'running': '续跑中', 'stop_requested': '停止中',
                    'succeeded': '续跑完成', 'failed': '续跑失败', 'stopped': '续跑已停止', 'unknown': '续跑结果未知'}
                detail = f'CH{self.recovery_channel:02d} · {label.get(state, state)}'
                if waiting:
                    detail += ' · 排队 ' + '、'.join(f'CH{number:02d}' for number in waiting)
                project = replace(project, resume_detail=detail,
                    resume_waiting=waiting,
                    active_task_count=max(project.active_task_count, int(active)),
                    run_id=self.recovery_job if active else project.run_id,
                    can_stop=state in ('queued', 'running') or bool(waiting))
            elif self.submitted:
                with session.lock:
                    total = session.request.number_of_tests
                    states = {number: ('续跑中' if number in session.busy else
                        '续跑完成' if session.completed[number] == total else
                        '续跑已停止' if session.stop_event.is_set() else '续跑未完成') for number in self.submitted}
                project = replace(project, resume_detail=' · '.join(f'CH{number:02d} {states[number]}' for number in sorted(states)))
            return project

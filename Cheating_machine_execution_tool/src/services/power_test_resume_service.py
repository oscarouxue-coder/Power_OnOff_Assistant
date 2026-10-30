"""One test session's channel recovery, independent of Tk and the old GUI."""
from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import replace

from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.services.device_project_info_service import (
    DeviceProjectInfoQueryRequest, project_info_mismatches, query_device_project_info,
    power_test_version_precheck_required,
)


class ResumeRejected(Exception):
    """An operator-safe rejection message."""


class PowerTestResumeSession:
    def __init__(self, request, channels, stop_event, emit, **callbacks):
        self.request = request
        self.channels = {int(c.section.split('_')[-1]): c for c in channels}
        self.stop_event = stop_event
        self.emit = emit
        self.callbacks = callbacks
        self.run_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.process_lock = threading.Lock()
        self.transport = None
        self.transport_done = threading.Event()
        self.transport_done.set()
        self.completed = {c.number: 0 for c in request.channels}
        self.failed = set()
        self.cancelled = set()
        self.ready = set()
        self.busy = set()
        self.attempts = {c.number: 0 for c in request.channels}
        self.accepted = {}
        self.owned_channels = set()
        self.active_started = set()
        self.recovery_jobs = 0
        self.original_done = False
        self.fingerprint = self._fingerprint()

    def _fingerprint(self):
        root = self.request.tool_root / 'config'
        return tuple(hashlib.sha256((root / name).read_bytes()).digest() for name in
                     dict.fromkeys(('config.ini', 'network_card_ip.ini', self.request.profile_filename)))

    def can_resume(self, channel):
        with self.lock:
            return (not self.stop_event.is_set() and channel in self.failed
                    and channel in self.ready and channel not in self.busy
                    and self.completed[channel] < self.request.number_of_tests)

    @property
    def is_recovering(self):
        with self.lock:
            return bool(self.busy or self.recovery_jobs)

    def attach(self, transport, channels=None):
        with self.lock:
            self.transport = transport
            self.owned_channels = set(self.completed if channels is None else channels)
            self.transport_done = threading.Event()

    def detach(self):
        with self.lock:
            self.transport = None
            for channel in self.owned_channels:
                completed = self.completed[channel]
                self.ready.add(channel)
                if completed < self.request.number_of_tests and channel not in self.cancelled:
                    self.failed.add(channel)
                if channel in self.active_started:
                    self.busy.discard(channel)
                    self.active_started.discard(channel)
            self.transport_done.set()

    def accepts(self, message):
        with self.lock:
            channel = message.get('channel')
            return (message.get('run_id', self.run_id) == self.run_id and
                    (channel not in self.attempts or
                     message.get('attempt', 0) == self.attempts[channel]))

    def observe(self, message):
        channel = message.get('channel')
        with self.lock:
            if message['type'] == 'channel_started':
                self.cancelled.discard(channel)
                self.active_started.add(channel)
                self.ready.discard(channel)
                self.failed.discard(channel)
                event = self.accepted.get(channel)
                if event:
                    event.set()
            elif message['type'] == 'channel_ready':
                self.active_started.discard(channel)
                self.ready.add(channel)
                if message.get('cancelled'):
                    self.cancelled.add(channel)
                    self.failed.discard(channel)
                elif message['ok']:
                    self.completed[channel] = self.request.number_of_tests
                    self.failed.discard(channel)
                else:
                    self.failed.add(channel)
                self.busy.discard(channel)

    def progress(self, channel, completed):
        with self.lock:
            self.completed[channel] = max(self.completed.get(channel, 0), completed)

    def stop(self):
        self.stop_event.set()
        self.emit('[通道续跑] 收到停止请求，取消待启动任务并停止正在执行的通道。')

    def submit(self, channel):
        with self.lock:
            if not self.can_resume(channel):
                return False
            self.busy.add(channel)
            self.recovery_jobs += 1
            try:
                threading.Thread(target=self._resume, args=(channel,), daemon=True,
                                 name=f'power-resume-{channel}').start()
            except Exception:
                self.busy.discard(channel)
                self.recovery_jobs -= 1
                self.emit(f'[通道续跑] 通道 {channel} 启动失败：无法创建后台线程。')
                return False
        return True

    def ensure_config_unchanged(self):
        try:
            unchanged = self._fingerprint() == self.fingerprint
        except OSError:
            raise ResumeRejected('无法读取原测试配置，未执行上下电') from None
        if not unchanged:
            raise ResumeRejected('配置已变化，请恢复原配置或重新发起完整测试；未执行上下电')

    def _validate(self, channel):
        if self.stop_event.is_set():
            raise ResumeRejected('已停止，跳过续跑')
        self.ensure_config_unchanged()
        config = TestItemConfigStore(self.request.tool_root / 'config' /
                                   self.request.profile_filename).load(required=True)
        expected = config.project_info
        try:
            needs_precheck = power_test_version_precheck_required(expected)
        except ValueError as exc:
            raise ResumeRejected(f'{exc} 未执行上下电') from None
        if needs_precheck:
            target = self.channels[channel]
            self.emit(f'[通道续跑] 通道 {channel} 开始三项版本只读预检。')
            actual = query_device_project_info(DeviceProjectInfoQueryRequest(
                bind_ip=target.network_card_ip.strip(), device_host=target.device_manage_ip.strip(),
                telnet=config.telnet), emit=lambda line: self.emit(f'[通道续跑][{channel}] {line}'))
            if project_info_mismatches(expected, actual):
                raise ResumeRejected('三项版本不一致，未执行上下电')
        else:
            self.emit(f'[通道续跑] 通道 {channel} 三项版本基准均为空，跳过开始前版本校验。')
        if self._fingerprint() != self.fingerprint or self.stop_event.is_set():
            raise ResumeRejected('预检期间配置变化或收到停止请求，未执行上下电')
        if needs_precheck:
            self.emit(f'[通道续跑] 通道 {channel} 三项版本预检通过。')

    def _resume(self, channel):
        accepted = threading.Event()
        try:
            self.emit(f'[通道续跑] 请求通道 {channel} 从第 {self.completed[channel] + 1}/'
                      f'{self.request.number_of_tests} 轮继续。')
            self._validate(channel)
            with self.lock:
                self.attempts[channel] += 1
                attempt = self.attempts[channel]
                self.accepted[channel] = accepted
                command = dict(type='resume', run_id=self.run_id, channel=channel,
                               attempt=attempt, completed=self.completed[channel])
                transport, done = self.transport, self.transport_done
                if transport is not None:
                    transport.put(command)
            if transport is not None:
                while not done.wait(0.05):
                    if accepted.is_set():
                        return
            if accepted.is_set() or self.stop_event.is_set():
                return
            # The original process has exited and released its serial port. All
            # after-run recoveries share this lock, including their preflight.
            with self.process_lock:
                if self.stop_event.is_set():
                    return
                self._validate(channel)
                from src.services.legacy_power_test_service import run_legacy_power_test
                request = replace(self.request, channels=tuple(
                    c for c in self.request.channels if c.number == channel))
                callbacks = dict(self.callbacks)
                overall = callbacks.get('on_progress')
                if overall is not None:
                    callbacks['on_progress'] = lambda _completed, total: overall(
                        min(self.completed.values()), total)
                result = run_legacy_power_test(
                    request, self.emit, self.stop_event, resume_session=self,
                    initial_completed={channel: self.completed[channel]},
                    initialize_power=False, **callbacks)
                outcome = '已停止' if self.stop_event.is_set() else ('成功' if result.ok else '失败')
                self.emit(f'[通道续跑] 独立恢复结果：通道 {channel} '
                          f'{outcome}；保留原全流程结论。')
        except Exception as exc:
            # Avoid propagating transport/config/login exception text (credentials).
            reason = str(exc) if isinstance(exc, ResumeRejected) else '执行或预检异常，未启动新的上下电任务'
            self.emit(f'[通道续跑] 通道 {channel} 失败/跳过：{reason}。')
        finally:
            with self.lock:
                if not accepted.is_set():
                    self.busy.discard(channel)
                if self.accepted.get(channel) is accepted:
                    self.accepted.pop(channel, None)
                self.recovery_jobs = max(0, self.recovery_jobs - 1)

"""Serialize project commands and controlled execution off the GUI thread.

This adapter supplies data and file-management commands, not a replacement
project database, scheduler, capability authority or device execution engine.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from pathlib import Path
import os
import queue
import threading
import time

from src.models.workbench_presentation import (ChannelView, LogView, ProjectView,
    WorkspaceHealthView, WorkspaceResourceView)
from src.models.qt_ai_chat import CHAT_OPERATIONS
from src.models.qt_ai_cases import CASE_OPERATIONS
from src.models.qt_ai_reports import REPORT_HANDOFF_OPERATIONS, REPORT_OPERATIONS
from src.models.qt_device_inventory import DeviceInventoryView, DeviceLeaseView
from src.services.qt_host_inventory import read_host_inventory
from src.services.qt_window_state import (MODULE_WINDOW_NAMES, read_dut_window_state, read_module_window_sizes,
    read_window_placement, save_window_placement)


RECENT_CHANGES = frozenset(('create', 'open', 'import_legacy', 'save', 'rename', 'duplicate', 'forget_recent'))
ARCHIVE_READS = frozenset(('archive_workspace_log', 'archive_serial_files', 'archive_serial_log',
                           'archive_project_files', 'archive_project_log', 'history_result_files',
                           'channel_history', 'history_legacy_runs'))
GUI_UNKNOWN_OPERATIONS = frozenset(('gui_unknown_list', 'gui_unknown_resolve'))
PAIRING_OPERATIONS = frozenset(('gateway_pairing_code', 'gateway_pairing_slot', 'gateway_pair_instance'))
STARTUP_OPERATIONS = frozenset(('gateway_startup_read', 'gateway_startup_save'))
GATEWAY_OPERATIONS = PAIRING_OPERATIONS | STARTUP_OPERATIONS | frozenset(('gateway_instances', 'gateway_start', 'gateway_stop',
                                'gateway_revoke', 'gateway_read_config', 'gateway_save_config'))
JOB_REVIEW_OPERATIONS = frozenset(('job_review_prepare', 'job_review_cancel', 'job_review_commit'))
MODEL_PROBES = frozenset(('ai_model_refresh', 'ai_model_test'))
MODEL_OPERATIONS = MODEL_PROBES | {'ai_model_open', 'ai_model_save', 'ai_model_select', 'ai_model_provider',
    'ai_model_delete', 'ai_model_sources', 'ai_model_source_check'}
AI_WORKSPACE_OPERATIONS = CHAT_OPERATIONS | CASE_OPERATIONS | REPORT_OPERATIONS | REPORT_HANDOFF_OPERATIONS


def _started_text(record):
    value = record.get('started_at')
    if value is None:
        return '尚无开始时间'
    if type(value) not in (int, float):
        return '开始时间待核实'
    try:
        return datetime.fromtimestamp(value).strftime('开始于 %Y-%m-%d %H:%M:%S')
    except (ValueError, OverflowError, OSError):
        return '开始时间待核实'


@dataclass(frozen=True)
class ProjectCommandResult:
    identifier: int
    operation: str
    project_id: str = ''
    error: str = ''
    payload: object = None


class QtWorkspaceAdapter:
    MAX_PENDING = 32

    def __init__(self, source_root, *, directory=None, service_factory=None, display_log=None, start_configured_gateway=False):
        self.source_root = Path(source_root).resolve()
        self._start_configured_gateway = start_configured_gateway
        self.directory = Path(directory) if directory is not None else None
        self.service_factory = service_factory
        self._display_log = display_log
        self.commands = queue.Queue(maxsize=self.MAX_PENDING)
        self.results = queue.Queue(maxsize=self.MAX_PENDING + 2)
        self.capacity = threading.BoundedSemaphore(self.MAX_PENDING)
        self.lock = threading.RLock()
        self._next_id = 0
        self._accepting = True
        self._snapshot = ()
        self._logs = deque(maxlen=500)
        self._log_chars = 0
        self._logs_omitted = 0
        self._log_write_failures = 0
        self._last_log_write = None
        self._last_task_log = None
        self._last_inventory_check = None
        self._last_worker_tick = None
        self._resource_sample = None
        self._device_inventory = DeviceInventoryView()
        self._device_leases = DeviceLeaseView()
        self._refresh_pending = False
        self._inventory_replies = None
        self._inventory_requests = []
        self._inventory_ports = ()
        self._inventory_adapters = ()
        self._archive_read = None
        self._remote_scope = None
        self._gateway_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-gateway-management')
        self._gateway_request = None
        self._gateway_project = ''
        self._service_close_started = False
        # Admission is bounded by the same workspace command tickets as foreground operations.
        self._history_reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-job-history')
        self._history_reads = {}
        self._model_settings = None
        self._ai_chats = {}
        self._executions = {}
        self._power_worker_checks = {}
        self._adapter_rename = None
        self._project_closes = {}
        self._close_receipts = {}
        self._window_placements = {}
        self._module_window_sizes = {}
        self._file_log_lock = threading.Lock()
        self._close_choices = {}
        self._closing = threading.Event()
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._worker, name='qt-workspace-files', daemon=False)
        self.thread.start()

    def submit(self, operation, *args):
        if operation not in ('create', 'open', 'import_legacy', 'save', 'rename', 'duplicate', 'close', 'refresh', 'refresh_inventory', 'export_logs',
                             'history_jobs', 'history_events', 'open_power_log', 'open_history_result', 'open_project_directory',
                             'single_power_options', 'forget_recent', 'instance_status', 'remote_scope_read', 'remote_scope_save',
                             'imported_connection_choices', 'imported_connection_select',
                             *GUI_UNKNOWN_OPERATIONS,
                             *GATEWAY_OPERATIONS,
                             *JOB_REVIEW_OPERATIONS,
                             *MODEL_OPERATIONS,
                             *AI_WORKSPACE_OPERATIONS,
                             *ARCHIVE_READS,
                             'prepare_execution', 'confirm_execution', 'cancel_confirmation', 'stop_execution', 'stop_and_close',
                             'pipeline_status',
                             'configuration_open', 'configuration_reload', 'configuration_close', 'configuration_checkpoint', 'configuration_save', 'configuration_defaults',
                             'configuration_pretest_preview', 'configuration_pretest_execute', 'configuration_pretest_cancel',
                             'configuration_pretest_stop',
                             'configuration_version_preview', 'configuration_version_execute', 'configuration_version_cancel',
                             'configuration_push_preview', 'configuration_push_execute', 'configuration_push_cancel',
                             'configuration_wifi_interfaces', 'channels_editor_open', 'channels_editor_reload', 'channels_editor_close',
                             'channels_editor_resources', 'channels_editor_preview', 'channels_editor_save', 'channels_editor_cancel',
                             'channels_editor_rename_preview', 'channels_editor_rename_confirm', 'channels_editor_rename_cancel',
                             'serial_show', 'serial_poll', 'serial_diagnostics', 'serial_open_all', 'serial_stop_all', 'serial_detach',
                             'serial_close_tab', 'serial_preview_send', 'serial_send', 'serial_cancel', 'serial_directory', 'serial_folder',
                             'dut_show', 'dut_poll', 'dut_preview', 'dut_execute', 'dut_cancel', 'dut_stop', 'dut_detach',
                             'upgrade_show', 'upgrade_poll', 'upgrade_preview', 'upgrade_execute', 'upgrade_cancel',
                             'upgrade_stop', 'upgrade_detach', 'upgrade_save', 'upgrade_logs',
                             'parameter_show', 'parameter_poll', 'parameter_preflight', 'parameter_select_table', 'parameter_preview',
                             'parameter_execute', 'parameter_cancel', 'parameter_save', 'parameter_generate',
                             'parameter_stop', 'parameter_detach', 'parameter_logs',
                             'onu_show', 'onu_poll', 'onu_preview', 'onu_execute', 'onu_cancel',
                             'onu_stop', 'onu_detach', 'onu_save_profile',
                             'onu_save_business', 'onu_prepare_registration', 'onu_register',
                             'onu_prepare_delete', 'onu_delete', 'onu_save_olt', 'onu_prepare_cleanup'):
            raise ValueError('不支持的项目操作')
        command_args = deepcopy(args) if operation in MODEL_OPERATIONS or operation in GATEWAY_OPERATIONS or operation == 'prepare_execution' or operation.startswith(
            ('configuration_', 'channels_editor_', 'serial_', 'dut_', 'upgrade_', 'parameter_', 'onu_')) else args
        with self.lock:
            if not self._accepting:
                raise RuntimeError('工作区正在关闭，不再接受项目操作')
            if operation == 'refresh' and self._refresh_pending:
                return None
            if not self.capacity.acquire(blocking=False):
                raise RuntimeError('项目操作正在处理中，请稍后重试')
            self._next_id += 1
            identifier = self._next_id
            self.commands.put_nowait((identifier, operation, command_args))
            if operation == 'refresh':
                self._refresh_pending = True
            return identifier

    def take_updates(self):
        with self.lock:
            projects = self._snapshot
            logs = tuple(self._logs)
            self._logs.clear()
            self._log_chars = 0
        results = []
        while True:
            try:
                result = self.results.get_nowait()
            except queue.Empty:
                break
            results.append(result)
            if result.identifier:
                self.capacity.release()
        return projects, logs, tuple(results)

    def health_snapshot(self):
        """Read this workspace's in-memory observations without touching a device or file."""
        with self.lock:
            return WorkspaceHealthView(self._last_worker_tick, self.commands.qsize(), self.MAX_PENDING,
                self._logs_omitted, self._log_write_failures, self._last_log_write,
                self._last_task_log, self._last_inventory_check, self._resource_sample)

    def device_inventory_snapshot(self):
        with self.lock:
            return self._device_inventory, self._device_leases

    def _sample_resources(self, now):
        resources = self._service.resources
        if not resources.lock.acquire(blocking=False):
            return
        try:
            keys = {key for _, held in resources.owners.values() for key in held}
            aliases = {key.removeprefix('adapter:') for key in keys if key.startswith('adapter:')}
            adapters = {resources.aliases.get(alias, alias) for alias in aliases}
            serial = sum(key.startswith('serial:') for key in keys)
            other = sum(not key.startswith(('serial:', 'adapter:')) for key in keys)
            sample = WorkspaceResourceView(now, serial, len(adapters), other, bool(resources.hardware_error))
            owners = {}
            for owner, (project_id, held) in resources.owners.items():
                for key in held:
                    if key.startswith(('serial:', 'power:', 'adapter:')):
                        owners.setdefault(key, set()).add(resources.labels.get(owner, project_id))
            leases = DeviceLeaseView(tuple((key, tuple(sorted(names))) for key, names in sorted(owners.items())),
                                     datetime.now(), sample.protection_unavailable)
        finally:
            resources.lock.release()
        with self.lock:
            self._resource_sample = sample
            self._device_leases = leases

    def begin_close(self, choices=None):
        with self.lock:
            self._accepting = False
            self._close_choices = dict(choices or {})
            self._closing.set()

    def wait_closed(self, timeout=5):
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _emit(self, message, level='INFO'):
        # Original project management emits names/operations, not credential
        # fields. Do not introduce raw configuration or exception dumps here.
        text = str(message)
        entry = LogView(datetime.now().strftime('%H:%M:%S'), level, '', '项目管理', text)
        self._record(entry)

    def record_update_log(self, message):
        self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', '', '软件更新', message))

    def remember_window_placement(self, project_id, window, placement=None, *, status_heights=None):
        with self.lock:
            if self._accepting:
                if window in MODULE_WINDOW_NAMES:
                    sizes = self._module_window_sizes.get(project_id)
                    if sizes is None or placement is None:
                        return
                    sizes[window] = placement
                pending = self._window_placements.setdefault((project_id, window), {})
                if placement is not None:
                    pending['placement'] = placement
                if status_heights is not None:
                    pending.setdefault('status_heights', {}).update(status_heights)

    def module_window_placement(self, project_id, window):
        with self.lock:
            return self._module_window_sizes.get(project_id, {}).get(window)

    def _flush_window_placements(self):
        with self.lock:
            pending, self._window_placements = self._window_placements, {}
        for (identifier, window), preferences in pending.items():
            context = self._service.projects.opened.get(identifier)
            if context is None:
                continue
            module = MODULE_WINDOW_NAMES.get(window, '串口终端' if window == 'serial' else 'DUT 配置')
            try:
                save_window_placement(context, window, **preferences)
            except (OSError, ValueError, TypeError):
                detail, level = '窗口状态保存失败，关闭仍可继续', 'WARN'
            else:
                detail, level = '已保存窗口状态', 'INFO'
            self._record(LogView(datetime.now().strftime('%H:%M:%S'), level,
                identifier, context.identity.name, '[' + module + '] ' + detail))

    def _record(self, entry):
        display = self._display_log(entry) if self._display_log is not None else entry
        with self.lock:
            if display is not None:
                self._append_display_log(display)
            if entry.run_id:
                self._last_task_log = datetime.now()
        directory = self._service.directory
        with self._file_log_lock:
            try:
                with (directory / 'workspace.log').open('a', encoding='utf-8') as stream:
                    stream.write(entry.time + ' [' + entry.project_id + '] ' + entry.message + '\n')
            except OSError as error:
                warning = LogView(entry.time, 'ERROR', entry.project_id, entry.project_name,
                    '工作区日志写盘失败：' + type(error).__name__ + '，不能确认本次记录完整落盘')
            else:
                warning = None
            with self.lock:
                self._last_log_write = (datetime.now(), warning is None)
                if warning is not None:
                    self._log_write_failures += 1
                    self._append_display_log(warning)

    def _append_display_log(self, entry):
        # Call with self.lock held. The counters measure only this UI handoff buffer.
        if len(self._logs) == self._logs.maxlen:
            self._log_chars -= len(self._logs.popleft().message)
            self._logs_omitted += 1
        self._logs.append(entry)
        self._log_chars += len(entry.message)
        while self._logs and self._log_chars > 128 * 1024:
            self._log_chars -= len(self._logs.popleft().message)
            self._logs_omitted += 1

    def _remember(self, context):
        self._service.remember(context)
        self._service.status.attach(context)
        if self._start_configured_gateway:
            self._open_gateway_project(context)
        identifier = context.identity.project_id
        with self.lock:
            missing_sizes = identifier not in self._module_window_sizes
        if missing_sizes:
            sizes = read_module_window_sizes(context)
            with self.lock:
                self._module_window_sizes[identifier] = sizes
        return identifier

    def _recent_projects(self):
        return tuple((item.get('name') or item['path'], item['path'])
            for item in self._service.recent if isinstance(item['path'], str) and item['path'])

    def _project_chat(self, context):
        key = context.identity.project_id
        if key not in self._ai_chats:
            from src.services.qt_ai_chat import QtAiChat
            def emit(line):
                self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', key, context.identity.name, line))
            execution = self._execution(context)
            chat = QtAiChat(self._models().store(context), self._service, emit, context, execution)
            self._ai_chats[key] = chat
            execution.ai_event_listener = chat.diagnostic.observe
        return self._ai_chats[key]

    def _open_gateway_project(self, context):
        service = self._service
        if getattr(getattr(service, 'gateway_runtime', None), 'mode', '') != 'project_peers':
            service.open_project_gateway(context)
            return
        key = context.identity.project_id
        service.gateway_runtime.bridge.open_project_controls(context)
        if key in service.remote_projects:
            try:
                chat = self._project_chat(context)
                chat.enable_project_peer(self._execution(context))
                service.gateway_runtime.bridge.attach(chat, context)
                service.controllers[key] = chat
            except Exception as error:
                self._emit('[项目路由] 项目业务尚未就绪 ' + key + ' · ' + type(error).__name__, 'WARN')

    def _context(self, identifier):
        context = self._service.projects.opened.get(identifier)
        if context is None:
            raise ValueError('项目未打开')
        return context

    def _close_project(self, context, choice):
        project_id = context.identity.project_id
        controller = self._service.controllers.get(project_id)
        if controller is not None and controller is not self._ai_chats.get(project_id):
            raise ValueError('项目仍由其他业务控制器管理，不能关闭')
        if self._gateway_project == context.identity.project_id:
            self._project_closes[context.identity.project_id] = choice
            return
        execution = self._executions.get(context.identity.project_id)
        if execution is not None and execution.editor_open:
            raise ValueError('请先关闭本项目配置编辑器，再关闭项目')
        if execution is not None and not execution.ready_to_close:
            raise ValueError('测试业务仍在安全收尾，项目未关闭')
        if self._service.projects.dirty(context):
            if choice == 'save':
                self._service.projects.save(context)
            elif choice == 'discard':
                self._service.projects.discard(context)
            else:
                raise ValueError('项目草稿未保存，需要本机操作员明确保存或放弃')
        if not self._service.prepare_project_close(context) or self._cancel_history(project_id):
            self._project_closes[project_id] = choice
            return
        chat = self._ai_chats.get(project_id)
        if chat is not None:
            if not chat.begin_close():
                self._project_closes[project_id] = choice
                return
            self._ai_chats.pop(project_id)
        self._service.detach_controller(context)
        if execution is not None:
            execution.close()
            self._executions.pop(context.identity.project_id)
        if self._model_settings is not None:
            self._model_settings.close_project(context)
        self._service.projects.close(context)
        with self.lock:
            self._module_window_sizes.pop(project_id, None)
            self._power_worker_checks.pop(project_id, None)

    def _models(self):
        if self._model_settings is None:
            from src.services.qt_model_settings import QtModelSettings
            self._model_settings = QtModelSettings(self._service, self._emit)
        return self._model_settings

    def _other_active(self, identifier):
        return [item for key, item in self._executions.items() if key != identifier and not item.idle]

    def _execution(self, context):
        from src.services.qt_execution_adapter import QtExecutionAdapter
        from src.services.qt_adapter_rename import QtAdapterRename
        if self._adapter_rename is None:
            self._adapter_rename = QtAdapterRename(self._service, self._guard_adapter_rename, self._publish_adapter_rename)
        identifier = context.identity.project_id
        if identifier not in self._executions:
            self._executions[identifier] = QtExecutionAdapter(self._service, context, self._record,
                other_jobs_active=lambda: bool(self._other_active(identifier)),
                other_power_blocked=lambda: any(not item.has_only_power_tasks() for item in self._other_active(identifier)),
                workspace_close_requested=self._closing.is_set, adapter_rename=self._adapter_rename)
        return self._executions[identifier]

    def _guard_adapter_rename(self, editor):
        from src.models.capabilities import CapabilityError
        if self._closing.is_set() or self._project_closes or self._service.maintenance.active:
            raise CapabilityError('rename_unavailable', '工作区正在退出、关闭项目或维护，未改名')
        if not self._service.idle or any(not execution.idle for execution in self._executions.values()):
            raise CapabilityError('resource_busy', '仍有设备任务等待或运行，请等待收尾后再改名')
        if any(execution.editor_open and execution.channel_editor is not editor for execution in self._executions.values()):
            raise CapabilityError('editor_open', '请先关闭其他项目的配置窗口，并按提示处理未保存的输入')
        if self._inventory_requests:
            raise CapabilityError('inventory_pending', '网卡正在刷新，请等待刷新完成')

    def _publish_adapter_rename(self, adapters, old, new, guid):
        resources = self._service.resources
        resources.register_adapter(old, guid)
        resources.register_adapter(new, guid)
        self._inventory_adapters = tuple(row.alias for row in adapters)
        with self.lock:
            self._device_inventory = replace(self._device_inventory, adapters=tuple(adapters),
                adapters_at=datetime.now(), adapters_failed=False)

    def _request_inventory(self, identifier, operation, args):
        if self._closing.is_set():
            raise ValueError('工作区正在退出，已取消资源刷新')
        project_id = ''
        if operation == 'channels_editor_resources':
            self._execute(operation, args)  # Validate the existing local editor token.
            project_id = args[0]
        if self._inventory_replies is None:
            resources = self._service.resources
            with resources.lock:
                self._inventory_binding = (dict(resources.aliases), resources.inventory_ready)
            replies = queue.SimpleQueue()
            self._emit('[串口/网卡] 开始只读刷新')
            # The reader owns only its reply mailbox. Discarding that mailbox
            # on exit cannot leave a callback into a closed project or GUI.
            threading.Thread(target=lambda: replies.put(read_host_inventory()),
                name='qt-host-inventory', daemon=True).start()
            self._inventory_replies = replies
        self._inventory_requests.append((identifier, operation, project_id))

    def _complete_inventory(self, reading=None):
        requests, self._inventory_requests = self._inventory_requests, []
        self._inventory_replies = None
        if not requests:
            return
        if reading is None or self._closing.is_set():
            message = '工作区正在退出，已跳过候选更新'
            self._emit('[串口/网卡] ' + message)
            for identifier, operation, project_id in requests:
                self.results.put_nowait(ProjectCommandResult(identifier, operation, project_id, error=message))
            return
        errors = []
        if reading.ports is None:
            errors.append('串口枚举失败，保留上次候选')
        else:
            self._inventory_ports = reading.ports
        if reading.adapters is None:
            errors.append('网卡枚举失败，保留上次候选')
        else:
            self._inventory_adapters = tuple(item.alias for item in reading.adapters)
        checked_at = datetime.now()
        with self.lock:
            self._last_inventory_check = (checked_at, not errors)
            previous = self._device_inventory
            self._device_inventory = DeviceInventoryView(
                self._inventory_ports, previous.adapters if reading.adapters is None else reading.adapters,
                previous.ports_at if reading.ports is None else checked_at,
                previous.adapters_at if reading.adapters is None else checked_at,
                reading.ports is None, reading.adapters is None)
        resources = self._service.resources
        idle = all(execution.idle for execution in self._executions.values())
        with resources.lock:
            register = (idle and not resources.owners
                        and (resources.aliases, resources.inventory_ready) == self._inventory_binding)
            if register:
                if reading.adapters is not None:
                    for item in reading.adapters:
                        resources.register_adapter(item.alias, item.interface_guid)
                resources.inventory_ready = reading.adapters is not None
        message = (f'[串口/网卡] 只读刷新完成，串口候选 {len(self._inventory_ports)} 个，'
                   f'网卡候选 {len(self._inventory_adapters)} 个')
        if errors:
            message += '；' + '；'.join(errors)
        if not register:
            message += '；任务占用或准入信息已更新，本次仅刷新候选'
        self._emit(message, level='WARN' if errors else 'INFO')
        for identifier, operation, project_id in requests:
            payload = dict(adapters=list(self._inventory_adapters), ports=list(self._inventory_ports), errors=list(errors))
            self.results.put_nowait(ProjectCommandResult(identifier, operation, project_id, payload=payload))

    def _poll_inventory(self):
        if self._inventory_replies is not None:
            try:
                reading = self._inventory_replies.get_nowait()
            except queue.Empty:
                return
            self._complete_inventory(reading)

    def _history_result_record(self, job):
        with self._service.status.lock:
            return dict(self._service.status.records.get(job, {}))

    def _request_history(self, identifier, operation, args):
        from src.services.qt_log_history import read_log_history
        project_id, *options = args
        if self._closing.is_set() or project_id in self._project_closes:
            raise ValueError('项目或工作区正在关闭，已取消任务历史读取')
        context = replace(self._context(project_id))
        cancel = threading.Event()
        self._emit('[任务历史] 开始读取：' + context.identity.name)
        future = self._history_reader.submit(read_log_history, context, *options, closing_event=cancel)
        self._history_reads[identifier] = (operation, context.identity, cancel, future)

    def _cancel_history(self, project_id=None):
        pending = False
        for _, project, cancel, future in self._history_reads.values():
            if project_id is None or project_id == project.project_id:
                cancel.set()
                future.cancel()
                pending = True
        return pending

    def _poll_history(self):
        if self._closing.is_set():
            self._cancel_history()
        for identifier, (operation, project, cancel, future) in tuple(self._history_reads.items()):
            if not future.done():
                continue
            del self._history_reads[identifier]
            error = ''
            page = None
            if cancel.is_set():
                error = '项目或工作区正在关闭，已取消任务历史读取'
            else:
                try:
                    page = future.result()
                except ValueError as problem:
                    error = str(problem)
                except Exception:
                    error = '项目历史暂时无法读取，请核对数据库后重试'
            if error:
                self._emit(f'[任务历史] {project.name}：{error}', 'WARN')
            else:
                self._emit(f'[任务历史] 已读取 {len(page.entries)} 条：{project.name}')
            self.results.put_nowait(ProjectCommandResult(identifier, operation, project.project_id, error, page))

    def _request_archive(self, identifier, operation, args):
        from src.services.qt_archived_logs import read_serial_log, read_workspace_log, serial_log_files
        if self._closing.is_set():
            raise ValueError('工作区正在退出，已取消归档读取')
        if self._archive_read is not None:
            raise ValueError('已有归档正在读取，请稍后重试')
        project_id, *options = args
        if operation == 'archive_workspace_log':
            read = partial(read_workspace_log, self._service.directory, *options)
        elif operation in ('archive_project_files', 'archive_project_log'):
            from src.services.qt_archived_logs import project_log_files, read_project_log
            context = replace(self._context(project_id))
            self._emit('[归档日志] 开始读取项目主日志：' + context.identity.name)
            read = partial(project_log_files if operation == 'archive_project_files' else read_project_log, context, *options)
        elif operation == 'history_legacy_runs':
            from src.services.qt_log_history import read_legacy_runs
            context = self._context(project_id)
            self._emit('[运行记录] 开始读取旧工作台运行记录：' + context.identity.name)
            read = partial(read_legacy_runs, self._service.status, project_id, *options)
        elif operation == 'history_result_files':
            from src.services.qt_power_logs import history_result_files
            context = replace(self._context(project_id))
            job, = options
            read = partial(history_result_files, context, job, self._history_result_record(job))
        elif operation == 'channel_history':
            from src.services.qt_log_history import read_channel_history
            context = replace(self._context(project_id))
            job, number, before = options
            execution = self._executions.get(project_id)
            if execution is None or project_id in self._project_closes:
                raise ValueError('当前项目没有可读取的开关机批次')
            execution.validate_channel_history(job, number)
            read = partial(read_channel_history, context, job, number, before)
        else:
            context = replace(self._context(project_id))
            read = partial(serial_log_files if operation == 'archive_serial_files' else read_serial_log, context, *options)
        replies = queue.SimpleQueue()

        def fetch():
            try:
                replies.put((read(), ''))
            except ValueError as error:
                replies.put((None, str(error)))
            except Exception:
                replies.put((None, '归档无法读取，请核对日志文件或目录后重试'))

        threading.Thread(target=fetch, name='qt-archive-reader', daemon=True).start()
        self._archive_read = (identifier, operation, project_id, replies)

    def _poll_archive(self, *, cancel=False):
        if self._archive_read is None:
            return
        identifier, operation, project_id, replies = self._archive_read
        if cancel:
            payload, error = None, '工作区正在退出，已取消归档读取'
        else:
            try:
                payload, error = replies.get_nowait()
            except queue.Empty:
                return
        self._archive_read = None
        if operation in ('archive_project_files', 'archive_project_log'):
            if error:
                self._emit('[归档日志] ' + error, 'WARN')
            else:
                detail = f'{len(payload)} 个文件' if operation == 'archive_project_files' else f'{len(payload.entries)} 行原文'
                self._emit(f'[归档日志] 项目 {project_id} 已读取 {detail}')
        if operation == 'history_legacy_runs':
            if error:
                self._emit('[运行记录] ' + error, 'WARN')
            else:
                self._emit(f'[运行记录] 已读取 {len(payload.entries)} 条旧工作台记录 · {project_id}')
        self.results.put_nowait(ProjectCommandResult(identifier, operation, project_id, error, payload))

    def _request_gateway(self, identifier, operation, args):
        if self._closing.is_set() or self._gateway_request is not None:
            raise ValueError('网关管理正在处理或退出，请稍后重试')
        management = self._service.management()
        registry = None
        if operation in STARTUP_OPERATIONS:
            project, *args = args
            if project:
                if project in self._project_closes:
                    raise ValueError('项目正在关闭，请重新打开启动配置')
                registry = self._execution(self._context(project)).instance_registry()
        def perform():
            if self._closing.is_set():
                raise ValueError('网关管理正在退出')
            if operation == 'gateway_startup_read':
                from src.services.qt_instance_startup import startup_review
                return startup_review(management, registry, *args)
            elif operation == 'gateway_startup_save':
                from src.services.qt_instance_startup import save_startup
                save_startup(management, registry, *args)
            elif operation == 'gateway_start':
                management.start_gateway()
            elif operation == 'gateway_stop':
                management.stop_gateway()
            elif operation == 'gateway_revoke':
                instance, = args
                management.revoke(instance)
            elif operation == 'gateway_read_config':
                return management.gateway_config()
            elif operation == 'gateway_pairing_code':
                expires = time.monotonic() + 300
                return management.create_pairing(), expires
            elif operation == 'gateway_pairing_slot':
                from src.services.remote_instance_management import read_startup
                number, = args
                return management.slot(read_startup(management.app_dir)['slot'] if number is None else number)
            elif operation == 'gateway_pair_instance':
                number, expected_id, url, name, vpn, code = args
                with management.lock:
                    current = management.slot(number)
                    if current['instance_id'] != expected_id or current['paired']:
                        raise ValueError('槽位状态已变化，请重新读取')
                    return management.pair(number, url, name, vpn, code)
            elif operation == 'gateway_save_config':
                original, changes, scopes = args
                with management.lock:
                    if management.gateway_config() != original:
                        raise ValueError('保存期间配置已变化，请重新读取')
                    management.save_gateway(dict(original, **changes), scopes)
            else:
                return management.host.instances()
        self._emit('[网关管理] 开始 ' + operation)
        self._gateway_request = (identifier, operation, self._gateway_worker.submit(perform))
        self._gateway_project = project if operation in STARTUP_OPERATIONS else ''

    def _poll_gateway(self):
        if self._gateway_request is None:
            return
        identifier, operation, future = self._gateway_request
        if not future.done():
            return
        self._gateway_request = None
        self._gateway_project = ''
        try:
            payload = future.result()
        except Exception as error:
            message = '操作未确认，请刷新状态并核对本机网关配置'
            if operation in PAIRING_OPERATIONS:
                message = '配对操作未确认，请核对槽位、保存的成员范围、网关地址和配对码后重新读取'
            if operation in STARTUP_OPERATIONS:
                message = '启动配置操作未完成，请核对槽位配对、网关地址及本机选择的通道和能力'
            if isinstance(error, ValueError) and str(error).startswith(('保存期间配置已变化', '网关端口', 'WSS证书', '网关由外部进程', '请先完成', '请先在远程管理')):
                message = str(error)
            self._emit('[网关管理] ' + operation + ' 失败：' + type(error).__name__, 'ERROR')
            self.results.put_nowait(ProjectCommandResult(identifier, operation, error=message))
        else:
            self._emit('[网关管理] 已完成 ' + operation)
            self.results.put_nowait(ProjectCommandResult(identifier, operation, payload=payload))

    def _execute(self, operation, args):
        store = self._service.projects
        if operation == 'instance_status':
            self._emit('[多实例状态] 开始读取本机实例和网关状态')
            status = self._service.management().status()
            if status.get('current_mode') == 'direct' and self._service.gateway_slot is not None:
                status = dict(status, current_mode='gateway_pending', current_slot=self._service.gateway_slot)
            self._emit('[多实例状态] 已读取本机实例和网关状态')
            return status
        if operation in ('remote_scope_read', 'remote_scope_save'):
            from src.services.qt_remote_project_scope import QtRemoteProjectScope
            if self._closing.is_set() or operation == 'remote_scope_save' and self._project_closes:
                raise ValueError('工作区或项目正在关闭，请在收尾后重新核对远程项目范围')
            if self._remote_scope is None:
                self._remote_scope = QtRemoteProjectScope(self._service)
            if operation == 'remote_scope_save':
                self._emit('[远程项目范围] 正在复核本机操作员确认的授权变更')
                review = self._remote_scope.save(*args)
                if self._start_configured_gateway:
                    for project_id, _, allowed in review.rows:
                        if allowed and project_id in store.opened:
                            self._open_gateway_project(store.opened[project_id])
                return review
            self._emit('[远程项目范围] 开始读取本机保存的授权范围')
            review = self._remote_scope.read()
            self._emit(f'[远程项目范围] 读取完成，已打开 {len(store.opened)} 个，已授权 {len(self._service.remote_projects)} 个')
            return review
        if operation == 'export_logs':
            from src.services.qt_log_export import export_log_snapshot
            self._emit('[日志] 开始导出当前筛选记录')
            count = export_log_snapshot(*args)
            self._emit(f'[日志] 已导出 {count} 项筛选记录')
            return count
        if operation == 'create':
            path, name = args
            return self._remember(store.create(path, name))
        if operation == 'open':
            context = store.open(args[0])
            if context.identity.project_id in self._project_closes:
                raise ValueError('项目正在关闭，请在关闭完成后重新打开')
            return self._remember(context)
        if operation in ('imported_connection_choices', 'imported_connection_select'):
            from src.services.qt_imported_connections import QtImportedConnections
            if self._closing.is_set():
                raise ValueError('工作区正在退出，接入配置未更换')
            connections = QtImportedConnections(self._service)
            return connections.choices() if operation == 'imported_connection_choices' else connections.select(args[0])
        if operation in GUI_UNKNOWN_OPERATIONS:
            if self._closing.is_set():
                raise ValueError('工作区正在退出，已取消核实未知任务')
            entries = tuple(self._service.resources.unknown_gui())
            if operation == 'gui_unknown_list':
                return entries
            owner, label, evidence = args
            if (owner, label) not in entries:
                raise ValueError('所选记录已变化，请重新打开核实窗口')
            # The legacy ticket embeds its project ID. Load its ledger via an
            # existing project open before asking the original service to reconcile it.
            project_id = owner.split(':', 2)[1]
            if project_id not in ('qt-configuration', 'qt-channel') and project_id not in store.opened:
                raise ValueError('请先打开该任务所属项目，再核实并解除保护')
            with self._service.status.lock:
                record = self._service.status.records.get(owner)
                if record and record['state'] in ('prepared', 'queued', 'running', 'stopping'):
                    raise ValueError('项目记录仍处于未完成状态，保护已保留')
            self._service.resolve_gui_unknown(owner, evidence.strip())
            return None
        if operation == 'import_legacy':
            from src.services.project_import_service import legacy_root
            source, destination, name = args
            legacy = legacy_root(source).resolve()
            destination = Path(destination).resolve()
            if destination.is_relative_to(legacy) or legacy.is_relative_to(destination):
                raise ValueError('旧程序与新项目目录须独立，不能包含彼此')
            return self._remember(self._service.import_project(source, destination, name))
        if operation == 'refresh':
            return ''
        context = self._context(args[0])
        if operation == 'open_project_directory':
            root = context.root
            if self._closing.is_set() or args[0] in self._project_closes or not root.is_dir() or root.resolve() != root:
                raise ValueError('项目正在关闭或目录已变化，请重新核对项目位置')
            try:
                os.startfile(str(root), 'explore')
            except OSError as error:
                raise ValueError('Windows 无法打开项目目录，请检查目录是否可访问') from error
            message = f'已请求 Windows 打开项目目录：{root}'
            self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', args[0], context.identity.name, message))
            return message
        if operation == 'open_power_log':
            return self._execution(context).open_power_log(*args[1:])
        if operation == 'open_history_result':
            from src.services.qt_power_logs import open_history_result_file
            job, path = args[1:]
            try:
                if self._closing.is_set():
                    raise ValueError('工作区正在关闭，未打开结果文件')
                channel = open_history_result_file(context, job, self._history_result_record(job), path)
            except (OSError, ValueError) as error:
                detail = str(error) if isinstance(error, ValueError) else '批次文件无法读取，请核对归档位置'
                self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'WARN', context.identity.project_id,
                                     context.identity.name, '[批次结果] ' + detail, job))
                raise ValueError(detail) from error
            detail = f'已打开 CH{channel:02d} 的批次文件'
            self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', context.identity.project_id,
                                 context.identity.name, f'[批次结果] {detail}：{path.name}', job, channel))
            return detail
        if operation in JOB_REVIEW_OPERATIONS:
            review = self._execution(context).job_review
            if operation == 'job_review_prepare':
                return review.prepare(args[1])
            if operation == 'job_review_cancel':
                return review.cancel(args[1])
            return review.commit(*args[1:])
        if operation == 'forget_recent':
            self._service.forget(context.root)
            return context.identity.project_id
        if operation.startswith('upgrade_'):
            execution = self._execution(context)
            if execution.closing or self._closing.is_set():
                raise ValueError('工作区正在退出，升级操作未执行')
            if operation in ('upgrade_preview', 'upgrade_execute', 'upgrade_save') and any(
                    key != context.identity.project_id and not item.idle for key, item in self._executions.items()):
                raise ValueError('当前Qt阶段仅准入一个设备任务，请等待其它项目收尾')
            return execution.upgrade_command(operation[len('upgrade_'):], args[1])
        if operation.startswith('parameter_'):
            if operation in ('parameter_preview', 'parameter_execute', 'parameter_save', 'parameter_select_table') and any(
                    key != context.identity.project_id and not item.idle for key, item in self._executions.items()):
                from src.models.capabilities import CapabilityError
                raise CapabilityError('resource_busy', '其它项目仍在执行设备任务，请等待收尾')
            return self._execution(context).parameter_command(operation[len('parameter_'):], args[1])
        if operation.startswith('onu_'):
            if operation in ('onu_preview', 'onu_execute', 'onu_save_profile', 'onu_save_business',
                             'onu_prepare_registration', 'onu_register', 'onu_prepare_delete', 'onu_delete',
                             'onu_prepare_cleanup') and any(
                    key != context.identity.project_id and not item.idle for key, item in self._executions.items()):
                from src.models.capabilities import CapabilityError
                raise CapabilityError('resource_busy', '其它项目仍在执行设备任务，请等待收尾')
            return self._execution(context).onu_command(operation[len('onu_'):], args[1])
        if operation.startswith('dut_'):
            execution = self._execution(context)
            if execution.closing or self._closing.is_set():
                raise ValueError('工作区正在退出，DUT操作未执行')
            if operation in ('dut_preview', 'dut_execute') and any(key != context.identity.project_id and not item.idle
                    for key, item in self._executions.items()):
                raise ValueError('当前Qt阶段仅准入一个设备任务，请等待其它项目收尾')
            payload = execution.dut_command(operation[len('dut_'):], args[1] if len(args) > 1 else {})
            if operation == 'dut_show':
                payload.update(read_dut_window_state(context))
            return payload
        if operation.startswith('serial_'):
            execution = self._execution(context)
            if execution.closing or self._closing.is_set():
                raise ValueError('工作区正在退出，串口操作未执行')
            payload = execution.serial_command(operation[len('serial_'):], args[1] if len(args) > 1 else {})
            if operation == 'serial_show':
                payload['placement'] = read_window_placement(context, 'serial')
            return payload
        if operation.startswith('channels_editor_'):
            execution = self._execution(context)
            if execution.closing:
                raise ValueError('项目正在收尾，通道配置操作未执行')
            return execution.channel_command(operation[len('channels_editor_'):], args[1] if len(args) > 1 else {})
        if operation.startswith('configuration_'):
            execution = self._execution(context)
            if execution.closing:
                raise ValueError('项目正在收尾，配置操作未执行')
            return execution.configuration_command(operation[len('configuration_'):], args[1] if len(args) > 1 else {})
        if operation in ('prepare_execution', 'confirm_execution'):
            others = self._other_active(context.identity.project_id)
            if others:
                from src.models.capabilities import CapabilityError
                kind = args[1] if operation == 'prepare_execution' else self._execution(context).pending_operation(args[1])
                if kind not in ('aging.start', 'aging.resume') or not all(item.has_only_power_tasks() for item in others):
                    raise CapabilityError('qt_parallel_pending', '其它项目有设备任务正在执行，请等待收尾后再启动此操作')
        if operation == 'pipeline_status':
            return self._execution(context).pipeline_status()
        if operation == 'single_power_options':
            return self._execution(context).single_power.selection(self._inventory_ports)
        if operation == 'prepare_execution':
            return self._execution(context).prepare(*args[1:], detected_ports=self._inventory_ports)
        if operation == 'confirm_execution':
            if self._closing.is_set():
                raise ValueError('工作区正在退出，本次测试未启动')
            self._execution(context).confirm(args[1])
            return context.identity.project_id
        if operation == 'cancel_confirmation':
            self._execution(context).discard_confirmation(args[1])
            return context.identity.project_id
        if operation == 'stop_execution':
            self._execution(context).stop(args[1])
            return context.identity.project_id
        if operation == 'stop_and_close':
            choice = args[1] if len(args) > 1 else ''
            if store.dirty(context) and choice not in ('save', 'discard'):
                raise ValueError('关闭前须明确保存或放弃草稿')
            execution = self._executions.get(context.identity.project_id)
            if execution is not None:
                execution.begin_close()
            self._project_closes[context.identity.project_id] = choice
            self._cancel_history(context.identity.project_id)
            return context.identity.project_id
        execution = self._executions.get(context.identity.project_id)
        if execution is not None and execution.editor_open and operation in ('save', 'rename', 'duplicate', 'close'):
            raise ValueError('请先保存或关闭本项目配置编辑器')
        if execution is not None and not execution.idle and operation in ('save', 'rename', 'duplicate', 'close'):
            raise ValueError('项目任务仍在执行或收尾，请先停止并等待；配置和项目保留')
        if operation == 'save':
            store.save(context)
            return self._remember(context)
        if operation == 'rename':
            store.rename(context, args[1])
            return self._remember(context)
        if operation == 'duplicate':
            if store.dirty(context):
                if len(args) < 3 or args[2] != 'save':
                    raise ValueError('复制前请明确保存当前项目')
                store.save(context)
            return self._remember(store.duplicate(context, args[1]))
        if operation == 'close':
            self._close_project(context, args[1] if len(args) > 1 else '')
            return context.identity.project_id
        raise ValueError('不支持的项目操作')

    def _publish(self):
        from line_check_assistant.config_store import ChannelConfigStore
        from src.services.workbench_status_service import TASK_NAMES
        rows = []
        for context in tuple(self._service.projects.opened.values()):
            self._service.refresh_status(context)
            execution = self._executions.get(context.identity.project_id)
            if execution is not None and execution.capabilities is not None:
                self._service.status.set_activity(context.identity.project_id, jobs=execution.capabilities.jobs.runtime_states(),
                    unknown_owners=self._service.resources.unknown_for(context.identity.project_id))
            status = self._service.status.snapshot(context)
            with self._service.status.lock:
                records = [dict(r) for r in self._service.status.records.values() if r['project_id'] == context.identity.project_id]
            latest = max(records, key=lambda r: r.get('updated_at', 0), default={})
            # Persisted nonterminal records alone cannot establish a live worker.
            historical_active = any(r['state'] in ('prepared', 'queued', 'running', 'stopping') for r in records)
            state = 'unknown' if historical_active else status.state
            state_text = '历史任务待核实' if historical_active else status.label
            if state == 'unknown' and (execution is None or execution.idle):
                from src.services.power_worker_lifetime import POWER_JOB_IDS, power_worker_notice
                identifier = context.identity.project_id
                checked, notice = self._power_worker_checks.get(identifier, (0., ''))
                now = time.monotonic()
                if now - checked >= 3:
                    unresolved = [r for r in records if r['state'] in ('unknown', 'prepared', 'queued', 'running', 'stopping')]
                    power_possible = any(r.get('operation') in POWER_JOB_IDS or r.get('operation') == '_on_start'
                                         for r in unresolved)
                    unknown_owners = self._service.resources.unknown_for(identifier)
                    missing_record = set(unknown_owners).difference(r.get('owner') for r in records)
                    notice = power_worker_notice(context) if power_possible or missing_record else ''
                    self._power_worker_checks[identifier] = (now, notice)
                if notice:
                    state_text = notice
            config_dir = execution.configuration_dir if execution is not None else context.config_dir
            store = ChannelConfigStore(config_dir / 'network_card_ip.ini')
            from line_check_assistant.config_store import ChannelConfig
            from src.services.qt_channel_configuration import channel_slots
            if execution is not None and execution.channel_editor is not None and not execution.latest:
                channels = [ChannelConfig(**c) for c in execution.channel_editor.snapshot()['channels']]
            else:
                channels = channel_slots(store.load())
            display = tuple(ChannelView(int(c.section.rsplit('_', 1)[1]), 'unknown' if c.enabled else 'disabled',
                                        vlan=c.vlan_name, port=c.serial_port) for c in channels)
            selected = [c for c in channels if c.enabled]
            config = (
                ('项目版本', (('配置版本', context.identity.revision[:12]), ('历史任务', str(len(records))))),
                ('基础参数', (('程控电源串口', store.load_power_serial_port() or '未配置'),
                           ('样机管理IP', next((c.device_manage_ip for c in selected if c.device_manage_ip), '未配置')),
                           ('已选通道', str(len(selected))))),
                ('VLAN / COM', tuple((c.label, (c.vlan_name or '未配置') + ' / ' + (c.serial_port or '未配置')) for c in selected)),
            )
            project = ProjectView(context.identity.project_id, context.identity.name,
                TASK_NAMES.get(latest.get('operation'), '尚无已知测试类型'), '—', state, state_text,
                '待核实' if state == 'unknown' else '—', '尚无实时轮次数据', None,
                f'已选 {len(selected)} 通道 · 尚无执行快照', int(status.last_result == 'failed'),
                run_id=latest.get('run_id', ''), channels=display, configuration=config,
                active_task_count=0, dirty=self._service.projects.dirty(context), can_start=state != 'unknown')
            if execution is not None:
                project = execution.present(project)
                if execution.push_trial is not None:
                    project = replace(project, push_trial=execution.push_trial.snapshot())
            if project.run_id:
                # The historical view uses a run directory ID. Live jobs (including
                # a post-run resume) use the owner ID from the same project ledger.
                record = (next((row for row in records if row.get('owner') == project.run_id), {})
                          if execution and project.run_id in execution.jobs else latest)
                project = replace(project, started_text=_started_text(record))
            opened = bool(execution and execution.editor_open)
            kind = ('channels' if execution and execution.channel_editor and execution.channel_editor.opened else
                'configuration' if opened else '')
            project = replace(project, can_configure=execution is None or (execution.idle and not execution.closing),
                editor_open=opened, editor_kind=kind, can_start=project.can_start and not opened)
            others = self._other_active(context.identity.project_id)
            if others:
                project = replace(project, can_start=False, parallel_power_available=project.can_start
                                  and all(item.has_only_power_tasks() for item in others))
            rows.append(project)
        with self.lock:
            self._snapshot = tuple(rows)

    def _shutdown(self):
        contexts = tuple(self._service.projects.opened.values())
        if not self._service_close_started:
            if any(controller is not self._ai_chats.get(key) for key, controller in self._service.controllers.items()):
                raise RuntimeError('仍有其他业务控制器在运行，不能释放项目')
            for context in contexts:
                if self._service.projects.dirty(context) and self._close_choices.get(context.identity.project_id) not in ('save', 'discard'):
                    raise ValueError('有未确认的配置草稿，关闭已取消')
        for execution in self._executions.values():
            execution.begin_close()
        if self._gateway_request is not None:
            return False
        if not self._service_close_started:
            self._service.begin_close()
            self._service_close_started = True
        if not self._service.idle or any(not execution.ready_to_close for execution in self._executions.values()):
            self._publish()
            return False
        chats_closed = all([chat.begin_close() for chat in self._ai_chats.values()])
        models_closed = self._model_settings is None or self._model_settings.begin_close()
        if not chats_closed or not models_closed or self._history_reads or self._close_receipts:
            return False
        for context in contexts:
            self._close_project(context, self._close_choices.get(context.identity.project_id, ''))
        if self._service.projects.opened:
            return False
        self._complete_inventory()
        self._poll_archive(cancel=True)
        self._service.close()
        return True

    def _finish_project_closes(self):
        for identifier, choice in tuple(self._project_closes.items()):
            execution = self._executions.get(identifier)
            if execution is None or execution.ready_to_close:
                self._project_closes.pop(identifier)
                error_text = ''
                try:
                    self._close_project(self._context(identifier), choice)
                    if identifier in self._project_closes:
                        continue
                    self._publish()
                except Exception as error:
                    error_text = type(error).__name__ + '：项目未关闭，请核对草稿和收尾状态'
                    self._emit(error_text, 'ERROR')
                receipts = self._close_receipts.pop(identifier, ())
                if receipts and not error_text:
                    self._emit('[Qt项目管理] 项目关闭完成：' + identifier)
                for request in receipts:
                    self.results.put_nowait(ProjectCommandResult(request, 'close', identifier, error_text))

    def _worker(self):
        try:
            if self.service_factory is None:
                from src.services.workspace_service import WorkspaceService
                factory = WorkspaceService
            else:
                factory = self.service_factory
            # Buffer constructor events until the service exposes its path.
            initial = []
            self._service = factory(self.source_root, directory=self.directory, emit=initial.append)
            self._service.emit = self._emit
            self._service.projects.emit = self._emit
            self._service.status.emit = self._emit
            peer_file = os.environ.get('DUTPILOT_PROJECT_PEERS') if self._start_configured_gateway else None
            if peer_file:
                try:
                    if (self._service.gateway_slot is not None or self._service.gateway_error
                            or os.environ.get('LINECHECK_DISABLE_CAPABILITIES') == '1'):
                        raise ValueError('启动模式冲突或本机已停用接入')
                    from src.services.project_peer_runtime import ProjectPeerRuntime
                    self._service.gateway_runtime = ProjectPeerRuntime(self._service, peer_file)
                except Exception as error:
                    self._service.gateway_error = '项目路由未启动，请核对模式、实例配置和群绑定'
                    detail = str(error) if isinstance(error, ValueError) else type(error).__name__
                    self._emit('[项目路由] ' + self._service.gateway_error + ' · ' + detail, 'ERROR')
            for message in initial:
                self._emit(message)
            if self._service.recent_error:
                self._emit(self._service.recent_error, 'WARN')
            self.results.put_nowait(ProjectCommandResult(0, 'ready',
                payload=(self._recent_projects(), self._service.recent_error)))
            next_sample = 0.0
            while True:
                now = time.monotonic()
                with self.lock:
                    self._last_worker_tick = now
                if now >= next_sample:
                    self._sample_resources(now)
                    next_sample = now + 1
                self._poll_inventory()
                self._poll_archive()
                self._poll_gateway()
                self._poll_history()
                for project_id, chat in self._ai_chats.items():
                    if not self._closing.is_set() and project_id not in self._project_closes:
                        chat.finish_intent()
                if self._model_settings is not None:
                    model_result = self._model_settings.take_result()
                    if model_result is not None:
                        request, action, project, view, problem = model_result
                        self.results.put_nowait(ProjectCommandResult(request, action, project, problem, view))
                try:
                    identifier, operation, args = self.commands.get(timeout=.1)
                except queue.Empty:
                    self._flush_window_placements()
                    self._finish_project_closes()
                    if not self._closing.is_set():
                        continue
                    try:
                        finished = self._shutdown()
                    except Exception as error:
                        self.results.put_nowait(ProjectCommandResult(0, 'close_rejected', error=type(error).__name__ + '：关闭未完成，请核对草稿与活动任务'))
                        with self.lock:
                            self._accepting = True
                            self._closing.clear()
                        self._publish()
                        continue
                    if not finished:
                        continue
                    break
                project_id = ''
                error_text = ''
                payload = None
                deferred = False
                previous_ids = set(self._service.projects.opened)
                try:
                    self._flush_window_placements()
                    if operation in GATEWAY_OPERATIONS:
                        self._request_gateway(identifier, operation, args)
                        deferred = True
                        continue
                    if operation in AI_WORKSPACE_OPERATIONS:
                        project_id = args[0]
                        context = self._context(project_id)
                        chat = self._ai_chats.get(project_id)
                        if self._closing.is_set() or project_id in self._project_closes:
                            raise ValueError('项目正在关闭，AI 会话操作已取消')
                        if chat is None:
                            if operation != 'ai_chat_open':
                                raise ValueError('请先在本机打开项目 AI 诊断')
                            chat = self._project_chat(context)
                        payload = chat.execute(operation, args[1:])
                        continue
                    if operation in MODEL_OPERATIONS:
                        project_id = args[0]
                        if self._closing.is_set():
                            raise ValueError('工作区正在退出，模型配置操作已取消')
                        context = self._context(project_id)
                        models = self._models()
                        if operation in MODEL_PROBES:
                            payload = models.start_probe(identifier, context, operation, args[1:])
                            deferred = payload is None
                        else:
                            payload = models.execute(context, operation, args[1:])
                        continue
                    if operation in ARCHIVE_READS:
                        project_id = args[0]
                        self._request_archive(identifier, operation, args)
                        deferred = True
                        continue
                    if operation in ('refresh_inventory', 'channels_editor_resources'):
                        self._request_inventory(identifier, operation, args)
                        deferred = True
                        continue
                    if operation in ('history_jobs', 'history_events'):
                        project_id = args[0]
                        self._request_history(identifier, operation, args)
                        deferred = True
                        continue
                    if operation in ('gui_unknown_list', 'open_power_log', 'open_history_result',
                                     'open_project_directory', 'instance_status', 'remote_scope_read', 'remote_scope_save'):
                        project_id = args[0] if args and operation != 'remote_scope_save' else ''
                        payload = self._execute(operation, args)
                        continue
                    if operation not in ('refresh', 'configuration_checkpoint', 'serial_poll', 'dut_poll', 'upgrade_poll', 'upgrade_logs', 'parameter_poll', 'parameter_logs', 'onu_poll'):
                        self._emit('[Qt项目管理] 开始项目操作：' + operation)
                    if operation == 'close' and args[0] in self._project_closes:
                        value = args[0]  # Join the accepted close and report only after the lease is released.
                    else:
                        value = self._execute(operation, args)
                    if operation == 'close' and value in self._project_closes:
                        self._close_receipts.setdefault(value, []).append(identifier)
                        deferred = True
                        continue
                    if operation in ('export_logs', 'imported_connection_choices', 'imported_connection_select', 'gui_unknown_resolve'):
                        payload = value
                    elif operation == 'prepare_execution':
                        payload, project_id = value, value.project_id
                    elif operation in JOB_REVIEW_OPERATIONS:
                        payload, project_id = value, args[0]
                    elif operation in ('pipeline_status', 'single_power_options') or operation.startswith(('configuration_', 'channels_editor_', 'serial_', 'dut_', 'upgrade_', 'parameter_', 'onu_')):
                        payload, project_id = value, args[0]
                    else:
                        project_id = value
                        if operation in RECENT_CHANGES:
                            payload = self._recent_projects()
                    if operation not in ('configuration_checkpoint', 'serial_poll', 'dut_poll', 'upgrade_poll', 'upgrade_logs', 'parameter_poll', 'parameter_logs', 'onu_poll'):
                        self._publish()
                    if operation not in ('refresh', 'configuration_checkpoint', 'serial_poll', 'dut_poll', 'upgrade_poll', 'upgrade_logs', 'parameter_poll', 'parameter_logs', 'onu_poll'):
                        context = self._service.projects.opened.get(project_id)
                        self._record(LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', project_id,
                            context.identity.name if context is not None else '项目管理',
                            '项目操作已完成：' + operation))
                except Exception as error:
                    # Match the original window admission: an opened project
                    # whose view data cannot load must not retain a hidden
                    # write lease. Leave its files intact for inspection.
                    for identifier_to_close in set(self._service.projects.opened) - previous_ids:
                        self._service.projects.close(self._service.projects.opened[identifier_to_close])
                    from src.models.capabilities import CapabilityError
                    error_text = (str(error) if isinstance(error, CapabilityError) or
                        isinstance(error, ValueError) and not operation.startswith(('configuration_', 'channels_editor_', 'dut_', 'upgrade_', 'parameter_', 'onu_')) else
                        type(error).__name__ + '：项目操作未完成，原文件和当前草稿保留，请核对输入与目录')
                    self._emit('[项目管理] ' + operation + '失败：' + type(error).__name__, level='ERROR')
                finally:
                    if operation == 'refresh':
                        with self.lock:
                            self._refresh_pending = False
                    if not deferred:
                        self.results.put_nowait(ProjectCommandResult(identifier, operation, project_id, error_text, payload))
        except Exception as error:
            self.results.put_nowait(ProjectCommandResult(0, 'initialization_failed', error=type(error).__name__ + '：项目服务不可用'))
            peer = getattr(getattr(self, '_service', None), 'gateway_runtime', None)
            if getattr(peer, 'mode', '') == 'project_peers':
                peer.close()
            # Fail closed without claiming that jobs stopped when a file/UI
            # adapter fails. Keep this owner thread alive until safe cleanup.
            for execution in self._executions.values():
                execution.begin_close()
            while any(not execution.ready_to_close for execution in self._executions.values()):
                time.sleep(.05)
            for execution in self._executions.values():
                execution.close()
        finally:
            self._gateway_worker.shutdown(wait=True, cancel_futures=True)
            self._poll_gateway()
            self._cancel_history()
            self._history_reader.shutdown(wait=True, cancel_futures=True)
            self._poll_history()
            for project_id, receipts in self._close_receipts.items():
                for request in receipts:
                    self.results.put_nowait(ProjectCommandResult(request, 'close', project_id, '工作区已退出，未确认项目关闭完成'))
            self.closed.set()

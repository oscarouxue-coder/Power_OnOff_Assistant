"""Project-bound GUI admission; existing engines keep their own stop semantics."""
from functools import wraps
from configparser import Error as ConfigError
from src.services.project_runtime import current_run, report_project_result


def project_operation(function):
    @wraps(function)
    def execute(view, *args, **kwargs):
        target = vars(view).get('project_view', view)
        workspace = vars(target).get('workspace')
        if workspace is None:
            return function(view, *args, **kwargs)
        ticket = workspace.admit_operation(target, function.__name__)
        if ticket is None:
            return False
        token = current_run.set((workspace.service.status, ticket))
        try:
            result = function(view, *args, **kwargs)
            if result is False:
                report_project_result(state='skipped')
            return result
        except BaseException:
            workspace.tickets[ticket]['uncertain'] = True
            report_project_result(state='unknown')
            raise
        finally:
            current_run.reset(token)
            workspace.track_operation(target, ticket)
    return execute


def project_busy(view):
    values = vars(view)
    if any(value is True for name, value in values.items()
           if name == 'running' or name.endswith('_running')):
        return True
    pipeline = values.get('pipeline_window')
    if pipeline is not None and pipeline.is_running():
        return True
    pretest = values.get('test_item_pretest_controls')
    if pretest is not None and getattr(pretest, 'running', False):
        return True
    resume = values.get('power_test_resume_session')
    if resume is not None and getattr(resume, 'is_recovering', False):
        return True
    rename = values.get('adapter_rename_dialog')
    if rename is not None and getattr(rename, 'running', False):
        return True
    manager = values.get('serial_session_manager')
    if manager is not None:
        with manager._lock:
            if manager._sessions or manager._closing:
                return True
    assistant = values.get('ai_assistant')
    if assistant is not None:
        capabilities = getattr(assistant, 'capabilities', None)
        if capabilities is not None and not capabilities.jobs.idle:
            return True
        if getattr(assistant.service, 'active_jobs', 0) or assistant.conversation.running:
            return True
    return any(worker.is_alive() for worker in values.get('_background_workers', ()))


def project_stopping(view):
    values = vars(view)
    pipeline = values.get('pipeline_window')
    if pipeline is not None and pipeline.is_running() and getattr(pipeline, '_stop_requested', False):
        return True
    for flag, cancel in (('parameter_write_running', 'parameter_cancel_event'),
                         ('dut_config_running', 'dut_config_cancel_event')):
        event = values.get(cancel)
        if values.get(flag) and event is not None and event.is_set():
            return True
    onu_cancel = values.get('onu_cancel_event')
    if onu_cancel is not None and onu_cancel.is_set() and any(
            value is True for key, value in values.items() if key.startswith('onu_') and key.endswith('_running')):
        return True
    pretest = values.get('test_item_pretest_controls')
    if pretest is not None and pretest.running and pretest.cancel.is_set():
        return True
    resume = values.get('power_test_resume_session')
    if resume is not None and getattr(resume, 'is_recovering', False) and resume.stop_event.is_set():
        return True
    run = values.get('_sample_upgrade_run')
    return bool(values.get('sample_upgrade_running') and run is not None and run.control.is_set())


def power_test_needs_wifi(config_dir, channels):
    from src.services.legacy_power_test_service import LegacyPowerChannel, prepare_legacy_power_test_request

    selected = [LegacyPowerChannel(int(c.section.rsplit('_', 1)[1]), c.network_card_ip)
                for c in channels if c.enabled]
    try:
        return prepare_legacy_power_test_request(config_dir.parent, selected).connect_wifi_enable
    except (ConfigError, OSError, ValueError):
        # An incomplete legacy profile still goes through its original preflight.
        # Reserve the shared radio until the selected profile can be resolved.
        return True


def project_resources(view, operation=''):
    if operation.startswith(('_on_onu', '_on_c300_cleanup')):
        config = view._current_onu_registration_config()
        family = str(config.olt_family).lower()
        host = getattr(config, ('c600' if '600' in family else 'c300') + '_olt_ip', '')
        return ['olt:' + host] if host else []
    keys = []
    for channel in view.channels:
        if not channel.enabled:
            continue
        alias = channel.adapter_alias or channel.vlan_name
        if alias:
            keys.append('adapter:' + alias.split(' [', 1)[0])
        if channel.serial_port and operation in ('_on_start', '_start_page_upgrade', '_start_full_package_upgrade'):
            keys.append('serial:' + channel.serial_port)
        if channel.network_card_ip and operation in ('_start_page_upgrade', '_start_full_package_upgrade'):
            keys.append('tftp:' + channel.network_card_ip + ':69')
    if view.power_serial_port and operation in ('_on_start', '_launch_power_on', '_start_page_upgrade', '_start_full_package_upgrade'):
        keys.append('power:' + view.power_serial_port)
    if operation == '_on_start' and power_test_needs_wifi(view.project_context.config_dir, view.channels):
        keys.append('wifi:host')
    return keys

"""Project-bound GUI admission; existing engines keep their own stop semantics."""
from functools import wraps


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
        try:
            return function(view, *args, **kwargs)
        except BaseException:
            workspace.tickets[ticket]['uncertain'] = True
            raise
        finally:
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


def project_resources(view, operation=''):
    if operation.startswith('_on_onu'):
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
    from line_check_assistant.test_item_config_store import TestItemConfigStore
    config = TestItemConfigStore(view.project_context.config_dir / 'test_project_config.ini').load()
    if config.connect_wifi.enable and operation == '_on_start':
        keys.append('wifi:host')
    return keys

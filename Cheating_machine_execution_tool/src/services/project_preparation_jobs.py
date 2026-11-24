"""Read existing job receipts without starting a job, changing a verdict, or opening a device."""
from contextlib import closing
import json
import sqlite3
import time

from src.services.qt_log_history import job_database_path
from src.services.project_profile_store import active_project_duts, read_project_profile


def _original_target(context, dut, job_id, capability):
    runs = context.root / 'runs'
    match = None
    for path in runs.glob('*/run.json'):
        if path.resolve() != path:
            continue
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or row.get('owner') != job_id:
            continue
        if (match is not None or row.get('project_id') != context.identity.project_id
                or row.get('revision') != context.identity.revision or row.get('state') != 'succeeded'
                or row.get('operation') != capability or row.get('run_id') != path.parent.name):
            raise ValueError('任务批次、保存版本或终态与当前项目不一致')
        directory = path.parent / 'Auto_power_on_off_tool/config'
        if directory.resolve() != directory:
            raise ValueError('任务快照路径已重定向')
        profile = read_project_profile(directory)
        matches = [d for d in (profile or {}).get('duts', ()) if d.get('dut_id') == dut['dut_id']]
        managed = profile and profile.get('environment_channels')
        if (len(matches) != 1 or matches[0] != dut
                or (type(dut.get('channel')) is not int if managed else not dut.get('hardware_id'))):
            raise ValueError('任务快照中的 DUT 身份或映射不一致')
        match = path.parent.name
    if match is None:
        raise ValueError('缺少可匹配的项目运行快照')
    return match


def _select_target(step, capability, arguments, result, dut):
    if step == 'onu':
        sns = arguments.get('serial_numbers')
        if (capability != 'onu.register' or not isinstance(sns, list) or len(sns) != 1
                or not dut.get('hardware_id') or str(sns[0]).casefold() != dut['hardware_id'].casefold()):
            raise ValueError('注册回执缺少唯一匹配的 ONU SN，可人工记录现场现状')
        return step
    channel = dut.get('channel')
    ids = arguments.get('channel_ids')
    if type(channel) is not int or not isinstance(ids, list) or any(type(n) is not int for n in ids) or channel not in ids:
        raise ValueError('任务目标不含当前 DUT 的明确通道')
    rows = result.get('items')
    if step in ('firmware', 'parameters'):
        expected = 'firmware.upgrade' if step == 'firmware' else 'parameters.write'
        if capability != expected or not isinstance(rows, list) or not rows:
            raise ValueError('缺少该步骤的逐目标执行回执')
        if ids == [channel] and len(rows) == 1:
            targets = rows
        else:
            vlan = dut.get('vlan', '').strip().casefold()
            targets = [r for r in rows if vlan and isinstance(r, dict) and str(r.get('vlan', '')).casefold() == vlan]
        if len(targets) != 1 or not isinstance(targets[0], dict):
            raise ValueError('无法确定该批次中当前 DUT 的结果')
        ok = targets[0].get('state') == 'succeeded' if step == 'firmware' else targets[0].get('ok') is True
        if not ok:
            raise ValueError('当前 DUT 未上报成功')
        return step
    if step == 'pretest' and capability == 'pretest.start':
        counts = result.get('result')
        if (ids != [channel] or not isinstance(counts, dict) or type(counts.get('passed')) is not int
                or counts['passed'] < 1 or any(type(counts.get(k)) is not int or counts[k] != 0
                                               for k in ('failed', 'unchecked', 'device_errors'))):
            raise ValueError('预测试缺少当前单台 DUT 的已校验成功记录')
        return step
    actions = {'telnet': ('enable',), 'wan': ('wan_configure',), 'voice': ('voice_configure',),
               'tr069': ('tr069_configure',), 'wifi': ('wifi_2g_configure', 'wifi_5g_configure')}
    action = arguments.get('action')
    if capability != 'dut.editor.execute' or action not in actions.get(step, ()):
        raise ValueError('任务操作与准备步骤不符')
    targets = [r for r in (rows or ()) if isinstance(r, dict) and type(r.get('number')) is int and r['number'] == channel]
    if len(targets) != 1 or targets[0].get('ok') is not True or targets[0].get('state') != 'success':
        raise ValueError('缺少当前通道的成功执行回执')
    return action


def preparation_job_receipt(context, dut, step, job_id, started):
    path = job_database_path(context)
    if not path.is_file():
        raise ValueError('本项目无持久任务库')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.25)) as db:
            row = db.execute('SELECT capability,state,created,updated,payload,result FROM jobs WHERE id=?',
                             (job_id,)).fetchone()
    except sqlite3.Error as exc:
        raise ValueError('任务记录暂时无法读取') from exc
    if row is None:
        raise ValueError('所选任务不属于本项目')
    capability, state, created, updated, raw_request, raw_result = row
    if (state != 'succeeded' or type(created) not in (float, int) or type(updated) not in (float, int)
            or not (started <= created <= updated <= time.time())):
        raise ValueError('请使用本次准备开始后执行并成功收尾的任务')
    try:
        request, result = json.loads(raw_request), json.loads(raw_result)
    except (TypeError, ValueError) as exc:
        raise ValueError('任务缺少结构化回执') from exc
    arguments = request.get('arguments') if isinstance(request, dict) else None
    if not isinstance(arguments, dict) or not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('任务回执缺少操作参数或确认结果')
    run = _original_target(context, dut, job_id, capability)
    if step in ('firmware', 'parameters', 'onu'):
        from line_check_assistant.config_store import ChannelConfigStore
        directory = context.root / 'runs' / run / 'Auto_power_on_off_tool/config'
        profile = read_project_profile(directory)
        if step == 'onu':
            sn = dut['hardware_id'].casefold()
            candidates = [row for row in active_project_duts(profile, directory) if row['hardware_id'].casefold() == sn]
            if not sn or len(candidates) != 1:
                raise ValueError('注册回执无法关联唯一的 DUT，请使用现场人工记录')
        elif profile.get('environment_channels'):
            channel = next((row for row in ChannelConfigStore(directory / 'network_card_ip.ini').load()
                            if row.enabled and row.section == f"channel_{dut['channel']}"), None)
            dut = dict(dut, vlan=(channel.vlan_name or channel.adapter_alias) if channel else '')
    part = _select_target(step, capability, arguments, result, dut)
    return part, f'{capability} · Job {job_id} · 批次 {run}'

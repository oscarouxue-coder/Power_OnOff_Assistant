"""Read-only presentation of existing runs and channel snapshots; no execution."""
from datetime import datetime


TASK_NAMES = {'_on_start': '开关机挂测', 'aging.start': '开关机挂测',
              '_launch_power_on': '电源控制', '_run_checks': '环境检查',
              '_start_page_upgrade': '页面升级', '_start_full_package_upgrade': '全包升级',
              '_start_sample_parameter_write': '写样机参数', 'pipeline.start': '全流程测试'}


def run_channel_snapshot(progress, states, channel_ids):
    """The legacy view can retain other runs' channels; use the known batch only."""
    if channel_ids is None:
        return {}, {}
    allowed = set(channel_ids)
    return ({key: value for key, value in progress.items() if key in allowed},
            {key: value for key, value in states.items() if key in allowed})


def workbench_projects(status_service, projects, channel_snapshots):
    with status_service.lock:
        records = tuple(dict(record) for record in status_service.records.values())
    rows = []
    for project in projects:
        row = dict(project)
        owned = [record for record in records if record['project_id'] == project['project_id']]
        active = [record for record in owned if record['state'] in ('queued', 'running', 'stopping')]
        latest = max(active or owned, key=lambda record: record.get('updated_at', 0), default={})
        operation = latest.get('operation', '')
        row['task_label'] = TASK_NAMES.get(operation, '项目任务' if operation else '尚无任务记录')
        try:
            row['started_text'] = ('开始于 ' + datetime.fromtimestamp(latest['started_at']).strftime('%m-%d %H:%M:%S')
                                   if latest.get('started_at') else '尚无开始时间')
        except (ValueError, TypeError, OSError, OverflowError):
            row['started_text'] = '开始时间待核实'
        progress, states = channel_snapshots.get(project['project_id'], ({}, {}))
        values = list(progress.values())
        row.update(progress_text='尚无开关机轮次数据', fraction=None, channel_text='尚无通道检测结果')
        if values:
            completed = [value[0] for value in values]
            totals = {value[1] for value in values}
            if len(totals) == 1 and min(completed) == max(completed):
                total = next(iter(totals))
                row['progress_text'] = f'开关机轮次 {completed[0]} / {total} · {len(values)}通道'
                row['fraction'] = completed[0] / total if total else None
            else:
                row['progress_text'] = f'各通道已完成 {min(completed)}–{max(completed)}轮'
            normal = sum(states.get(number, ('unknown', ''))[0] == 'success' for number in progress)
            failed = sum(states.get(number, ('unknown', ''))[0] == 'failed' for number in progress)
            retry = sum(states.get(number, ('unknown', ''))[0] == 'retry' for number in progress)
            row['channel_text'] = f'最近通道结果  正常 {normal}  失败 {failed}  重试 {retry}'
        rows.append(row)
    return rows

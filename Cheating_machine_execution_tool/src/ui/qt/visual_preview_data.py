"""Fictional workbench snapshots shared by both visual preview versions."""
from dataclasses import asdict, replace
from datetime import datetime

from src.models.workbench_presentation import ChannelView, LogView, ProjectView, WorkspaceHealthView, WorkspaceResourceView
from src.models.qt_configuration import ConfigurationDraft


POWER = 'preview-power'
AGING = 'preview-aging'
STAMP = 1795396800


def preview_snapshots():
    rounds = (
        (1, 'running', 324, '等待启动完成', 0, 0),
        (2, 'success', 326, '本轮检查通过', 0, 0),
        (3, 'failed', 320, 'PON 注册超时', 1, 2),
        (4, 'retry', 322, '等待重试 PON 检查', 0, 1),
        (5, 'running', 324, '检查业务状态', 0, 0),
        (6, 'success', 325, '本轮检查通过', 0, 0),
        (7, 'running', 323, '等待供电稳定', 0, 0),
        (8, 'stopped', 320, '本通道已停止', 0, 0),
    )
    channels = tuple(ChannelView(n, state, completed, 500, f'VLAN{115 + n}', f'COM{15 + n}',
                                 state == 'failed', stage, stage, selected=True)
                     for n, state, completed, stage, _, _ in rounds)
    power_rows = [
        dict(dut_id=f'DUT-{n:02}', label=f'DUT-{n:02}', channel=n, stage=stage, cycle=completed + (state in ('running', 'retry')),
             completed=completed, success=completed - failures, failure=failures, retries=retries, duration=62.4 + n)
        for n, state, completed, stage, failures, retries in rounds
    ]
    power = ProjectView(
        POWER, '千兆网关 · 开关机挂测', '自动开关机', 'GW-1800', 'running', '运行中',
        '06:21:38', '整批已完成 320 / 500 轮', 64, '8 个通道 · 1 个异常',
        attention_count=1, success_count=sum(row['success'] for row in power_rows), failure_count=1,
        run_id='DEMO-PWR-07', channels=channels, active_task_count=1, project_type='power_cycle',
        can_stop=True, task_stage='CH03 PON 注册超时，CH04 正在重试', count_unit='轮',
        configuration=(('运行参数', (('每台目标', '500 轮'), ('已选通道', 'CH01–CH08'))),
                       ('设备资源', (('程控电源', 'COM102'), ('通道网卡', 'VLAN116–VLAN123')))),
        test_overview=dict(target=500, rows=power_rows),
    )
    aging = ProjectView(
        AGING, '双频网关 · 业务老化', '全业务老化', 'GW-2400', 'running', '监测中',
        '27:46:00', '目标 168 小时', None, '4 台 DUT · 4 项业务',
        attention_count=1, run_id='DEMO-AGE-12', active_task_count=1, project_type='service_aging', can_stop=True,
        configuration=(('监测计划', (('计划时长', '168 小时'), ('现场终端', '4 台'))),),
        test_overview=_aging_overview(),
    )
    queue = ProjectView(
        'preview-queued', '光网关 · 升级验证', '样机升级', 'GW-3100', 'queued', '等待资源',
        '尚未开始', '等待串口 COM16', None, '4 台 DUT', active_task_count=1,
    )
    done = ProjectView(
        'preview-done', '千兆网关 · 兼容性检查', '自动开关机', 'GW-1800', 'completed', '已完成',
        '04:18:31', '已完成 200 / 200 轮', 100, '4 个通道', success_count=800, failure_count=0, count_unit='轮',
    )
    ready = replace(
        power, project_id='preview-ready', name='家庭网关 · 多通道开关机验证与业务恢复回归',
        dut='GW-2700', state='idle', state_text='待启动', elapsed='—', progress_text='准备完成', progress=None,
        channel_text='8 个通道', attention_count=0, success_count=None, failure_count=None, run_id='',
        channels=(), active_task_count=0, can_start=True, can_stop=False, task_stage='', test_overview={},
    )
    offline = ProjectView(
        'preview-offline', '机顶盒 · 现场采集接入', '全业务老化', 'STB-460', 'pending', '未接入',
        '—', '等待现场数据', None, '暂无设备观测',
    )
    projects = power, aging, queue, done, ready, offline
    logs = (
        LogView('14:38:42', 'INFO', POWER, power.name, 'CH01 下发本轮上电请求', power.run_id, 1),
        LogView('14:38:46', 'SUCCESS', POWER, power.name, 'CH02 完成本轮检查 · 326 / 500 轮', power.run_id, 2),
        LogView('14:38:49', 'ERROR', POWER, power.name, 'CH03 PON 注册超时 · 已记录失败', power.run_id, 3),
        LogView('14:38:52', 'WARN', POWER, power.name, 'CH04 等待本轮重试 · 轮次保持 322', power.run_id, 4),
        LogView('14:38:55', 'INFO', AGING, aging.name, 'DUT-01 收到 LAN Ping 应答', aging.run_id),
        LogView('14:38:58', 'WARN', AGING, aging.name, 'DUT-02 IPTV 观测报告播放冻结', aging.run_id),
        LogView('14:39:00', 'INFO', AGING, aging.name, 'DUT-03 未收到近期在线心跳', aging.run_id),
        LogView('14:39:03', 'INFO', queue.project_id, queue.name, '等待串口 COM16 释放'),
    )
    time = datetime.fromtimestamp(STAMP)
    health = WorkspaceHealthView(
        worker_tick=0.0, commands_pending=0, command_limit=32, logs_omitted=0, log_write_failures=0,
        log_write=(time, True), task_log_at=time, inventory_check=(time, True),
        resources=WorkspaceResourceView(0.0, 9, 8, 1, False),
    )
    return projects, logs, health


def _aging_overview():
    rows = [
        _observation(1, 'lan_ping', 'icmp', 'healthy', '绑定网卡收到应答', packet_loss=0.003),
        _observation(2, 'iptv', 'jsonl', 'abnormal', '播放冻结', failures=3),
        _observation(3, 'voice', 'jsonl', 'unknown', '等待近期观测'),
        _observation(4, 'tr069', 'unavailable', 'unavailable', '尚无采集来源'),
    ]
    presence = []
    for number, state in enumerate(('online', 'online', 'unknown', 'unknown'), 1):
        known = state == 'online'
        presence.append(dict(
            dut_id=f'DUT-{number:02}', label=f'DUT-{number:02}', subscribed=number != 4, state=state,
            last_observation=STAMP if known else None, last_heartbeat=STAMP if known else None,
            last_boot_id=f'demo-{number}' if known else None, last_boot_at=STAMP if known else None,
            last_uptime_seconds=99960 if known else None, last_uptime_at=STAMP if known else None,
            reboot_count=0 if known else None, last_reboot_at=None,
            detail='采集端报告在线' if known else '暂无近期设备观测',
        ))
    return dict(
        state='running', target_hours=168, elapsed_seconds=99960, job_id='DEMO-AGE-12', rows=rows, dut_presence=presence,
        feed_path='示例项目 / history / aging-input / DEMO-AGE-12.jsonl',
        daily_checks=[dict(kind='daily', at=STAMP, operator='演示操作员', evidence='LAN 连通，已记录 IPTV 异常')],
    )


def _observation(number, collector, source, state, detail, *, failures=0, packet_loss=None):
    sampled = state in ('healthy', 'abnormal')
    return dict(
        dut_id=f'DUT-{number:02}', label=f'DUT-{number:02}', collector=collector, source=source,
        state=state, checks=96 if sampled else 0, success_rate=(96 - failures) / 96 if sampled else None,
        last_success=STAMP - 120 if sampled else None, consecutive_failures=failures,
        abnormal_seconds=120 if failures else 0, observed_seconds=99740 if sampled else 0,
        last_heartbeat=STAMP if sampled else None, last_observation=STAMP if sampled else None,
        recoveries=0, detail=detail, packet_loss=packet_loss,
    )


def module_preview_snapshots():
    """Inputs for the same five real Qt dialogs, without a workspace or worker."""
    from line_check_assistant.test_item_config_store import ProjectInfoSettings, TestProjectConfig
    from src.models.boot_entry import BOOT_ENTRY_OPTIONS

    project = '千兆网关 · 业务窗口评审样例'
    token = 'visual-preview'
    identity = dict(token=token, project_id=token, project_name=project)
    log_dir = r'C:\DUTPilot-Preview\serial'
    serial = dict(
        identity, log_dir=log_dir, closing=False, dropped_events=0, failures=['COM18 示例占用'],
        tabs=[
            dict(target='vlan116', port='COM16', writable=True, state='监控中', dropped=0,
                 path=log_dir + r'\vlan116.log', text=(
                     '[14:38:42] CH01 接收启动日志\n[14:38:44] Boot sequence completed\n'
                     '[14:38:48] PON registered\n[14:38:50] WAN address ready\n'
                     '[14:39:00] 等待下一轮观测\n')),
            dict(target='vlan118', port='COM18', writable=False, state='打开失败', dropped=0,
                 path='', text='[14:38:48] 示例串口被其他会话占用\n'),
        ],
    )
    targets = [dict(number=n, vlan=f'VLAN{115 + n}', source=f'192.0.2.{15 + n}', host='192.0.2.1',
                    adapter=f'VLAN{115 + n}', port=f'COM{15 + n}') for n in range(1, 4)]
    upgrade = dict(
        identity, project=project, username='demo', password='demo-sample', power='COM102',
        defaults=dict(upgrade_mode='全包升级', firmware_path=r'C:\DUTPilot-Preview\sample.bin',
                      transfer_method='Tftp Put', boot_entry_method=BOOT_ENTRY_OPTIONS[0],
                      parallel_count=3, restore_factory=False),
        targets=targets, active=False, stoppable=False, job='DEMO-FW-08', state='failed',
        notice='1 台失败 · 请核对失败原因', items=[
            dict(vlan='VLAN116', state='succeeded', message='固件版本已读回'),
            dict(vlan='VLAN117', state='failed', message='等待设备启动超时'),
            dict(vlan='VLAN118', state='succeeded', message='固件版本已读回'),
        ],
    )
    dut = dict(
        identity, username='demo', password='demo-sample', saved_parameter_login=('demo', 'demo-sample'),
        targets=targets, active=False, can_execute=True, job_id='DEMO-DUT-04', state='failed', error='1 台设备未响应',
        rows=[dict(target, stage='completed' if target['number'] != 2 else 'query',
                   message='TCP 23 可达' if target['number'] != 2 else '等待设备响应超时') for target in targets],
    )
    settings = asdict(TestProjectConfig(project_info=ProjectInfoSettings(
        project_name=project, software_version='V1.3.0-DEMO', internal_software_version='20261123.01')))
    settings['runtime'] = dict(startup_time='90', interval_time='25', number_of_tests='500', wait_command_done='15')
    settings['push'] = dict(dingtalk_flag='0', webhook='', secret='', at_all='0')
    configuration = ConfigurationDraft(token, project, token, '', settings)
    channels = [dict(section=f'channel_{n}', enabled=n <= 8, vlan_name=f'VLAN{115 + n}',
                     serial_port=f'COM{15 + n}', network_card_ip=f'192.0.2.{15 + n}') for n in range(1, 17)]
    channel_configuration = ConfigurationDraft(token, project, token, '', dict(
        device_ip='192.0.2.1', power_serial_port='COM102', channels=channels))
    return serial, upgrade, dut, configuration, channel_configuration

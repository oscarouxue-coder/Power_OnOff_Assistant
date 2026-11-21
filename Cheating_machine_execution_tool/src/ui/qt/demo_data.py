"""Explicitly fictional display data. Never a device service or saved project."""
from src.models.workbench_presentation import ChannelView, LogView, ProjectView


def projects():
    selected = {1, 2, 7}
    channels = tuple(ChannelView(n, 'running' if n in selected else 'disabled',
        68 if n in selected else None, 100 if n in selected else None,
        f'VLAN{115+n}', f'COM{15+n}') for n in range(1, 17))
    config = (
        ('基础参数', (('程控电源串口', 'COM102'), ('样机管理IP', '192.168.1.1'), ('运行通道', '3 / 16'))),
        ('网络与 VLAN', tuple((f'channel_{n}', f'VLAN{115+n}') for n in (1, 2, 7))),
        ('通道对应 COM 口', tuple((f'channel_{n}', f'COM{15+n}') for n in (1, 2, 7))),
    )
    return (
        ProjectView('demo-a', '上下电测试_A', '自动上下电', 'NP7287XGS', 'running', '运行中',
            '02:36:18', '第 68 / 100 轮', 68, '3 通道', 0, 204, 0, 'DEMO-RUN-A', channels, config, active_task_count=1),
        ProjectView('demo-b', '上下电测试_B', '自动上下电', 'NP7287XGS', 'running', '运行中',
            '05:12:03', '第 42 / 100 轮', 42, '8 通道', 0, 336, 0, 'DEMO-RUN-B', active_task_count=1),
        ProjectView('demo-c', '样机升级测试_C', '固件升级', 'NP7287XGS', 'running', '运行中 · 有异常',
            '00:18:20', '已处理 6 / 8 台', 75, '8 台设备', 1, 6, 1, 'DEMO-RUN-C', active_task_count=1),
        ProjectView('demo-d', 'ONU注册测试_D', 'ONU 批量注册', 'ONU', 'queued', '等待资源',
            '尚未开始', '0 / 16 台', 0, '等待串口 COM14 释放'),
        ProjectView('demo-e', '全业务老化', '持续开机业务检测', '—', 'pending', '待接入',
            '—', '尚未实现独立执行服务', None, '暂无可信检测项与健康数据'),
    )


def logs():
    return (
        LogView('22:19:36', 'INFO', 'demo-a', '上下电测试_A', '通道1 开始第68轮测试（演示）', 'DEMO-RUN-A', 1),
        LogView('22:19:37', 'INFO', 'demo-b', '上下电测试_B', '通道7 检测结果到达（演示）', 'DEMO-RUN-B', 7),
        LogView('22:19:38', 'WARN', 'demo-c', '样机升级测试_C', '设备10.10.1.25 升级失败：校验超时（演示）', 'DEMO-RUN-C'),
        LogView('22:19:44', 'INFO', 'demo-a', '上下电测试_A', '第68轮执行中，等待设备启动（演示）', 'DEMO-RUN-A'),
    )

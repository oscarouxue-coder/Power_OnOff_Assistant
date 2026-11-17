"""Immutable, data-only project runtime summary shared by GUI and capabilities."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ProjectStatus:
    state: str = 'idle'
    active_task_count: int = 0
    unknown_task_count: int = 0
    last_result: str = ''
    updated_at: float = 0.0

    def public(self):
        return asdict(self)

    @property
    def label(self):
        label = {'stopping': '停止中', 'running': '运行中', 'unknown': '结果未知',
                 'failed': '失败', 'stopped': '已停止', 'idle': '空闲'}[self.state]
        return label + (' !' if self.state in ('running', 'stopping') and
                        (self.unknown_task_count or self.last_result == 'failed') else '')

    @property
    def detail(self):
        result = {'succeeded': '成功', 'failed': '失败', 'stopped': '已停止',
                  'skipped': '未执行', 'unknown': '结果未知', 'unchecked': '已执行，未配置结果校验'}.get(self.last_result, '无')
        if self.last_result == 'unknown' and not self.unknown_task_count:
            result = '已核实（原结果未知）'
        return f'活动任务：{self.active_task_count}\n结果未知：{self.unknown_task_count}\n最近结果：{result}'

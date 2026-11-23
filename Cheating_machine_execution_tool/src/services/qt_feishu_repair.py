"""Project the existing source-environment repair onto the Qt worker."""
from importlib.util import find_spec
from queue import Empty
import sys

from src.models.dependency_repair import RepairResult
from src.services.feishu_dependency_repair import FeishuDependencyRepair


class QtFeishuRepair:
    def __init__(self, root, maintenance, emit):
        self.service = FeishuDependencyRepair(root, maintenance)
        self.emit = emit
        self.status = ('', None)

    def start(self, busy):
        if getattr(sys, 'frozen', False):
            raise ValueError('当前便携包缺少飞书 SDK，请下载并完整解压新版 ZIP。')
        if find_spec('lark_oapi') is not None:
            raise ValueError('当前环境已有飞书 SDK，无需执行缺包修复。')
        self.service.start(busy)
        self.status = ('正在准备飞书 SDK 安装…', None)

    def poll(self):
        for _ in range(64):
            try:
                event = self.service.events.get_nowait()
            except Empty:
                break
            if not isinstance(event, RepairResult):
                self.emit(str(event))
                self.status = (str(event), None)
                continue
            if self.service.busy:
                self.service.events.put(event)
                break
            self.emit('[飞书依赖] ' + event.message)
            self.status = (event.message, event.ok)
            if not event.ok:
                self.service.release()
            break
        return self.status

    def release(self):
        if self.service.busy:
            raise ValueError('飞书 SDK 正在安装，请等待当前操作完成。')
        self.service.release()
        self.status = ('', None)

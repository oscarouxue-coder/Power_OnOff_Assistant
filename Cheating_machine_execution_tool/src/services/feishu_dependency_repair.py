"""Locally authorized repair orchestration; never exposed as an AI capability."""
from pathlib import Path
import queue
import threading

from src.core.feishu_dependency_install import install_feishu, source_environment
from src.core.dingtalk_stream import InstanceLease
from src.models.dependency_repair import RepairResult
from scripts.source_environment_guard import repair_identity


class FeishuDependencyRepair:
    def __init__(self, root, gate, installer=install_feishu, lease_factory=InstanceLease):
        self.root, self.gate = Path(root), gate
        self.installer, self.lease_factory = installer, lease_factory
        self.events = queue.Queue()
        self.thread, self.lease = None, None
        self.ready = False

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, busy):
        # Check existing activity before making maintenance visible to workers.
        self.gate.begin(busy)
        try:
            self.ready = False
            source_environment(self.root)
            self.lease = self.lease_factory(repair_identity())
            try:
                self.lease.acquire()
            except RuntimeError:
                raise RuntimeError("当前Python环境正在修复或无法建立安装保护，请稍后重试") from None
            self.thread = threading.Thread(target=self._run, name="feishu-sdk-repair", daemon=False)
            self.thread.start()
        except Exception:
            self.release()
            raise

    def _run(self):
        try:
            self.installer(self.root, self.events.put)
            self.ready = True
            self.events.put(RepairResult(True, "飞书SDK安装及验证成功，正在准备安全重启"))
        except Exception as exc:
            self.events.put(RepairResult(False, str(exc)))

    def release(self):
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        self.gate.end()

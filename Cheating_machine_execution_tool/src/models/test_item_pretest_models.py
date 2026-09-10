"""测试项预备测试的独立请求及结果。"""
from dataclasses import dataclass

from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import OrderConfig, TelnetSettings


@dataclass(frozen=True)
class PretestRequest:
    channels: tuple[ChannelConfig, ...]
    order: OrderConfig
    telnet: TelnetSettings


@dataclass
class PretestResult:
    total: int
    executed: int = 0
    passed: int = 0
    failed: int = 0
    unchecked: int = 0
    device_errors: int = 0
    cancelled: bool = False

    @property
    def skipped(self) -> int:
        return self.total - self.executed

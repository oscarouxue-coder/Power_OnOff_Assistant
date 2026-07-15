"""ParameterSession 协议。

`SampleParameterWriteRequest` 的业务编排只关心\"按字节收发、等待提示符、能读取最近一段历史\"这套最小契约。
这是为了让 service 层能够同时被 `PySerialSession`（串口）和 `TelnetSession`（网络）满足，便于后续
\"传输层由串口切换为 Telnet\" 的批量写样机参数改造。

具体行为契约：
- `cursor()`：返回历史中下一个\"未消费\"的位置（整型字节偏移）。
- `write(data, sensitive=False)`：向底层写入原始字节；可选 `sensitive` 用于决定是否在
   日志显示中把写入内容替换为脱敏字符串。
- `send_line(text, sensitive=False)`：在 `write` 之外，对文本追加 `\\r`（或样机能识别的换行）后下发。
- `wait_for_any(markers, timeout_seconds, cursor)`：阻塞至任一 marker（bytes/str，大小写不敏感）出现或超时；
   返回命中的 marker 或 None。`cursor` 是起始位置（与 `cursor()` 同语）。
- `wait_for_all(markers, timeout_seconds, cursor)`：等待全部 marker 都出现。
- `peek_since(cursor)`：从指定 cursor 起读取到当前的全部历史，**不消费**。用于诊断 & 解析读回值。
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, Union


Marker = Union[bytes, str]


class ParameterSession(Protocol):
    """\"按字节收发串行字节流\"会话的最薄契约。

    生产实现：
        PySerialSession（src/core/serial_transport.py）
        TelnetSession  （切片 3 引入）

    测试/伪造实现：
        tests/test_sample_parameter_service.py 中的 FakeParameterSession
    """

    def cursor(self) -> int:
        ...

    def write(self, data: bytes, sensitive: bool = False) -> None:
        ...

    def send_line(self, text: str, sensitive: bool = False) -> None:
        ...

    def wait_for_any(
        self,
        markers: Iterable[Marker],
        timeout_seconds: float,
        cursor: int,
    ) -> Optional[str]:
        ...

    def wait_for_all(
        self,
        markers: Iterable[Marker],
        timeout_seconds: float,
        cursor: int,
    ) -> bool:
        ...

    def peek_since(self, cursor: int) -> str:
        ...

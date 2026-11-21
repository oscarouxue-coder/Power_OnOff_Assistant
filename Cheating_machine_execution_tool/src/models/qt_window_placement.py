"""Window size and optional outer position, independent of either widget toolkit."""
from dataclasses import dataclass
from typing import Optional


DUT_STATUS_FEATURES = ('telnet', 'wan', 'wifi_2g', 'wifi_5g', 'voice', 'tr069')
DUT_STATUS_MIN_ROWS = 2
DUT_STATUS_MAX_ROWS = 16
DUT_STATUS_DEFAULT_ROWS = 4


def dut_status_rows(value):
    try:
        rows = int(value)
    except (TypeError, ValueError, OverflowError):
        return DUT_STATUS_DEFAULT_ROWS
    return max(DUT_STATUS_MIN_ROWS, min(rows, DUT_STATUS_MAX_ROWS))


@dataclass(frozen=True)
class WindowPlacement:
    width: int
    height: int
    x: Optional[int] = None
    y: Optional[int] = None
    legacy: bool = False

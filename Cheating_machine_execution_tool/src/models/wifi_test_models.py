"""正式 WiFi 测试的数据和可分类异常；不依赖旧 GUI。"""
from dataclasses import dataclass, field
import re
import time


class WifiCancelled(Exception):
    pass


class WifiEnvironmentError(Exception):
    pass


class WifiScanError(WifiEnvironmentError):
    """扫描故障保留来源/数值原因，服务层决定是否消耗一次尝试重试。"""

    def __init__(self, source, reason_code=None, *, retryable=False, reason=''):
        self.source = source
        self.reason_code = reason_code
        self.retryable = retryable
        self.reason = reason
        code = '未提供' if reason_code is None else f'{reason_code}/0x{reason_code:08X}'
        super().__init__(f'无线扫描失败（来源={source}，错误码={code}；{reason or "原因未提供"}）')


class WifiVerificationError(Exception):
    pass


def check_stop(stop):
    if stop.is_set():
        raise WifiCancelled()


def wait(seconds, stop, guard=None, clock=time.monotonic):
    deadline = clock() + seconds
    while True:
        check_stop(stop)
        if guard:
            guard()
        remaining = deadline - clock()
        if remaining <= 0:
            return
        stop.wait(min(0.2, remaining))


def normalize_bssid(value):
    token = str(value).strip().replace('-', ':').lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', token):
        raise WifiEnvironmentError('样机BSSID格式无效')
    raw = bytes.fromhex(token.replace(':', ''))
    if raw[0] & 1 or not any(raw):
        raise WifiEnvironmentError('样机BSSID不是有效的单播地址')
    return token


def frequency_band(khz):
    if 2400000 <= khz < 2500000:
        return '2.4G'
    if 4900000 <= khz < 5925000:
        return '5G'
    return '未知'


@dataclass(frozen=True)
class WifiTestOptions:
    connection_test_mode: str = 'per_band'
    security_source: str = 'auto'
    wireless_ping_enable: bool = False
    wireless_ping_target: str = ''


@dataclass(frozen=True)
class WifiBandTarget:
    band: str
    ssid: str
    bssid: str
    password: str = field(repr=False)
    security: str = ''


@dataclass(frozen=True)
class WifiSnapshot:
    targets: tuple
    dual_band_enabled: object = None

    def __getitem__(self, key):
        # 兼容已授权的旧 logger 双频凭据摘要，未读取的频段显示为空。
        lookup = {t.band: t for t in self.targets}
        values = tuple(v for band in ('2.4G', '5G') for v in
                       ((lookup[band].ssid, lookup[band].password) if band in lookup else ('', '')))
        return values[key]


@dataclass(frozen=True)
class WifiInterface:
    guid: str
    name: str
    index: int


@dataclass(frozen=True)
class WifiObservation:
    ssid: str
    bssid: str
    frequency: int
    pairs: tuple = ()  # (Windows authentication ID, cipher ID)


@dataclass(frozen=True)
class WifiConnection:
    ssid: str
    bssid: str
    auth: int
    cipher: int


@dataclass(frozen=True)
class WirelessPingResult:
    target_ip: str
    sent: int
    times_ms: tuple

    @property
    def ok(self):
        return bool(self.times_ms)

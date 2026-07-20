"""测试项配置 ini 的读写服务。

把 ``Auto_power_on_off_tool/config/test_project_config.ini`` 解析为 dataclass 内存模型,
也可以把内存模型写回 ini。当前实现只提供"加载 + 编辑 + 保存"入口,主程序不会消费 ini 内容,
不会驱动任何 telnet/上下电/测试项执行流程(参考 PROJECT_STATUS.md 的 Q1=A 决策)。
"""
from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


TELNET_SECTION = "telnet"
ORDER_SECTION = "order"
CONNECT_WIFI_SECTION = "connect_wifi"

# ``[order]`` 段顶部独立 key,语义对齐老工具 ``config.ini`` 中 ``command_fail_retry_interval_time``:
# 表示两次失败重试之间的等待秒数。
ORDER_GLOBAL_RETRY_INTERVAL_KEY = "command_fail_retry_interval_time"

# 默认值:与老工具 ``config.ini`` 的 ``command_fail_retry_interval_time = 60`` 保持一致。
DEFAULT_COMMAND_FAIL_RETRY_INTERVAL = 60

# ``[order]`` 每条命令的默认重试次数;老工具不写 retry_times 时也按 5 次处理。
DEFAULT_ORDER_RETRY_TIMES = 5

# ``[order]`` 命令 key 末尾的 ``retry_times_N`` 后缀匹配。允许命令中包含空格。
RETRY_TIMES_PATTERN = re.compile(r"\s+retry_times_(\d+)\s*$")


@dataclass
class TelnetSettings:
    """``[telnet]`` 段字段。密码按 Q4 决策保持明文,UI 上无遮显。"""

    request_url: str = "http://192.168.29.1"
    port: int = 23
    user: str = "root"
    password: str = ""
    timeout: int = 10
    input_user_flag: str = "ogin:"
    input_password_flag: str = "Password:"
    login_success_flag: str = "#"
    telnet_need_enter_password_flag: int = 0
    telnet_no_user_password_flag: int = 0
    only_power_off_on: int = 0


@dataclass
class ExpectedSegment:
    """期望匹配的一段。多段之间是 AND 关系;每段独立勾选「否定」时,本段反向匹配。

    设计依据:老工具 ``fuzzy_match.py`` 在遇到 ``&&`` 时按段切分,每段单独处理 ``!`` 前缀,
    因此 per-segment 否定更贴近老工具真实语义,优于早先的命令级单标志。
    """

    text: str = ""
    negate: bool = False


@dataclass
class OrderItem:
    """``[order]`` 段里的一条测试命令。"""

    command: str = ""
    expected_segments: List[ExpectedSegment] = field(default_factory=list)
    retry_times: int = DEFAULT_ORDER_RETRY_TIMES


@dataclass
class OrderConfig:
    """``[order]`` 段。``command_fail_retry_interval_time`` 写在段顶部第一行。"""

    command_fail_retry_interval_time: int = DEFAULT_COMMAND_FAIL_RETRY_INTERVAL
    items: List[OrderItem] = field(default_factory=list)


@dataclass
class ConnectWifiSettings:
    """``[connect_wifi]`` 段。"""

    enable: int = 0
    product_solution: str = "openwrt"


@dataclass
class TestProjectConfig:
    """整个 ini 文件的内存模型。"""

    telnet: TelnetSettings = field(default_factory=TelnetSettings)
    order: OrderConfig = field(default_factory=OrderConfig)
    connect_wifi: ConnectWifiSettings = field(default_factory=ConnectWifiSettings)


def _parse_int(value: object, default: int) -> int:
    """把任意输入安全转换为 int;失败回退默认值。"""
    if value is None:
        return default
    try:
        return int(str(value).strip())  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _split_expected(value: str) -> List[tuple[bool, str]]:
    """把 ``!段A&&段B&&!段C`` 拆成 ``[(True, "段A"), (False, "段B"), (True, "段C")]``。

    每段独立解析 ``!`` 前缀;空字符串返回单个空段,由调用方过滤。
    """
    if not value:
        return [(False, "")]
    result: List[tuple[bool, str]] = []
    for part in value.split("&&"):
        negate = False
        if part.startswith("!"):
            negate = True
            part = part[1:]
        result.append((negate, part))
    return result


def _join_expected(segments: List[ExpectedSegment]) -> str:
    """把内存里的 segments 拼回 ini 的期望值字符串。每段独立加 ``!`` 前缀(若 negate=True)。

    空段不写入拼接结果,与老工具 ``fuzzy_match.py`` 的 AND 语义保持一致。
    """
    parts: List[str] = []
    for seg in segments:
        if not seg.text:
            continue
        parts.append(f"!{seg.text}" if seg.negate else seg.text)
    return "&&".join(parts)


def _parse_order_key(raw_key: str) -> tuple[str, int]:
    """把 ``命令 retry_times_5`` 拆成 (命令, retry_times);缺 retry_times 走默认。"""
    match = RETRY_TIMES_PATTERN.search(raw_key)
    if match:
        parsed = _parse_int(match.group(1), DEFAULT_ORDER_RETRY_TIMES)
        # retry_times_0 在老 ini 里语义不清,回退到默认以保证主程序不会下发"失败 0 次"。
        retry_times = parsed if parsed >= 1 else DEFAULT_ORDER_RETRY_TIMES
        command = raw_key[: match.start()].rstrip()
        return command, retry_times
    return raw_key.strip(), DEFAULT_ORDER_RETRY_TIMES


def _build_order_key(command: str, retry_times: int) -> str:
    """序列化时构造 ``命令 retry_times_N`` key。retry_times < 1 时不写后缀。"""
    command = (command or "").rstrip()
    if retry_times and retry_times >= 1:
        return f"{command} retry_times_{retry_times}"
    return command


class TestItemConfigStore:
    """测试项 ini 的读写服务,接口风格与 ``SampleUpgradeSettingsStore`` 一致。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> TestProjectConfig:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(self.config_path, encoding="utf-8")

        return TestProjectConfig(
            telnet=self._load_telnet(parser),
            order=self._load_order(parser),
            connect_wifi=self._load_connect_wifi(parser),
        )

    def save(self, config: TestProjectConfig) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser[TELNET_SECTION] = self._dump_telnet(config.telnet)
        parser[ORDER_SECTION] = self._dump_order(config.order)
        parser[CONNECT_WIFI_SECTION] = self._dump_connect_wifi(config.connect_wifi)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)

    # -- 解析 ------------------------------------------------------------

    def _load_telnet(self, parser: configparser.RawConfigParser) -> TelnetSettings:
        section = TELNET_SECTION
        return TelnetSettings(
            request_url=parser.get(section, "request_url", fallback="http://192.168.29.1"),
            port=_parse_int(parser.get(section, "port", fallback="23"), 23),
            user=parser.get(section, "user", fallback="root"),
            password=parser.get(section, "password", fallback=""),
            timeout=_parse_int(parser.get(section, "timeout", fallback="10"), 10),
            input_user_flag=parser.get(section, "input_user_flag", fallback="ogin:"),
            input_password_flag=parser.get(section, "input_password_flag", fallback="Password:"),
            login_success_flag=parser.get(section, "login_success_flag", fallback="#"),
            telnet_need_enter_password_flag=_parse_int(
                parser.get(section, "telnet_need_enter_password_flag", fallback="0"), 0
            ),
            telnet_no_user_password_flag=_parse_int(
                parser.get(section, "telnet_no_user_password_flag", fallback="0"), 0
            ),
            only_power_off_on=_parse_int(
                parser.get(section, "only_power_off_on", fallback="0"), 0
            ),
        )

    def _load_order(self, parser: configparser.RawConfigParser) -> OrderConfig:
        section = ORDER_SECTION
        interval = _parse_int(
            parser.get(section, ORDER_GLOBAL_RETRY_INTERVAL_KEY, fallback=str(DEFAULT_COMMAND_FAIL_RETRY_INTERVAL)),
            DEFAULT_COMMAND_FAIL_RETRY_INTERVAL,
        )
        items: List[OrderItem] = []
        if not parser.has_section(section):
            return OrderConfig(
                command_fail_retry_interval_time=interval,
                items=items,
            )
        for raw_key, raw_value in parser.items(section=section, raw=True):
            if raw_key.strip() == ORDER_GLOBAL_RETRY_INTERVAL_KEY:
                continue
            if not raw_key.strip():
                continue
            command, retry_times = _parse_order_key(raw_key)
            parsed_segments = _split_expected(raw_value)
            items.append(
                OrderItem(
                    command=command,
                    expected_segments=[
                        ExpectedSegment(text=text, negate=negate)
                        for negate, text in parsed_segments
                    ],
                    retry_times=retry_times,
                )
            )
        return OrderConfig(
            command_fail_retry_interval_time=interval,
            items=items,
        )

    def _load_connect_wifi(self, parser: configparser.RawConfigParser) -> ConnectWifiSettings:
        section = CONNECT_WIFI_SECTION
        return ConnectWifiSettings(
            enable=_parse_int(parser.get(section, "enable", fallback="0"), 0),
            product_solution=parser.get(section, "product_solution", fallback="openwrt"),
        )

    # -- 序列化 ----------------------------------------------------------

    def _dump_telnet(self, telnet: TelnetSettings) -> dict:
        return {
            "request_url": telnet.request_url or "",
            "port": str(_parse_int(telnet.port, 23)),
            "user": telnet.user or "",
            "password": telnet.password or "",
            "timeout": str(_parse_int(telnet.timeout, 10)),
            "input_user_flag": telnet.input_user_flag or "",
            "input_password_flag": telnet.input_password_flag or "",
            "login_success_flag": telnet.login_success_flag or "",
            "telnet_need_enter_password_flag": str(_parse_int(telnet.telnet_need_enter_password_flag, 0)),
            "telnet_no_user_password_flag": str(_parse_int(telnet.telnet_no_user_password_flag, 0)),
            "only_power_off_on": str(_parse_int(telnet.only_power_off_on, 0)),
        }

    def _dump_order(self, order: OrderConfig) -> dict:
        result: dict = {}
        interval = _parse_int(order.command_fail_retry_interval_time, DEFAULT_COMMAND_FAIL_RETRY_INTERVAL)
        result[ORDER_GLOBAL_RETRY_INTERVAL_KEY] = str(interval)
        for item in order.items:
            key = _build_order_key(item.command, _parse_int(item.retry_times, DEFAULT_ORDER_RETRY_TIMES))
            value = _join_expected(list(item.expected_segments))
            result[key] = value
        return result

    def _dump_connect_wifi(self, wifi: ConnectWifiSettings) -> dict:
        # enable 字段统一为 0/1,即便 UI 传入 Python bool 也强制转换,避免保存为 "True"/"False"。
        enable_int = 1 if bool(wifi.enable) else 0
        return {
            "enable": str(enable_int),
            "product_solution": (wifi.product_solution or "openwrt").strip().lower(),
        }


__all__ = [
    "CONNECT_WIFI_SECTION",
    "DEFAULT_COMMAND_FAIL_RETRY_INTERVAL",
    "DEFAULT_ORDER_RETRY_TIMES",
    "ConnectWifiSettings",
    "ExpectedSegment",
    "ORDER_GLOBAL_RETRY_INTERVAL_KEY",
    "ORDER_SECTION",
    "OrderConfig",
    "OrderItem",
    "TELNET_SECTION",
    "TelnetSettings",
    "TestItemConfigStore",
    "TestProjectConfig",
]
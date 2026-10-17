"""测试项配置 ini 的读写服务。

把 ``Auto_power_on_off_tool/config/test_project_config.ini`` 解析为 dataclass 内存模型,
也可以把内存模型写回 ini。配置窗口本身只负责“加载 + 编辑 + 保存”；全流程执行
通过 service 消费加载后的内存模型，配置存储层本身不驱动 telnet 或上下电。
"""
from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .legacy_ui_defaults_store import LegacyUiDefaultsStore


TELNET_SECTION = "telnet"
ORDER_SECTION = "order"
CONNECT_WIFI_SECTION = "connect_wifi"
# ``[project_info]`` 段包含项目名称 / 软件版本 / ONU 软件编译时间等参考信息。
# 项目信息 Tab 可通过只读 Telnet 查询回填版本字段，仍由操作员点击保存后写入配置。
PROJECT_INFO_SECTION = "project_info"
LEGACY_UI_CONFIG_FILENAME = "config.ini"

# 全局指令重试间隔的内存字段名。持久化唯一来源是同目录
# ``config.ini [other_config] command_fail_retry_interval_time``；测试项目
# ``[order]`` 只保存命令。加载历史测试项目文件时仍忽略同名残留键。
ORDER_GLOBAL_RETRY_INTERVAL_KEY = "command_fail_retry_interval_time"

# 默认值:与老工具 ``config.ini`` 的 ``command_fail_retry_interval_time = 60`` 保持一致。
DEFAULT_COMMAND_FAIL_RETRY_INTERVAL = 60
WIFI_AUTH_MODE_OPTIONS = (
    "WPA2-PSK",
    "WPA-PSK",
    "WPA-PSK/WPA2-PSK",
    "WPA3-PSK",
    "WPA2-PSK/WPA3-PSK",
    "None",
)
WIFI_CIPHER_OPTIONS = ("AES", "TKIP", "TKIP+AES")

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
    # ``telnet_default_on``:Telnet 段在测试项配置中是否默认启用(Q1=A,仅编辑器)。
    # 默认 1 = 勾选;老 ini 没有该 key 时 ``_load_telnet`` 也回退 1,保持向后兼容。
    telnet_default_on: int = 1
    # 追加到末尾以保留旧的位置参数顺序；显式空串仍保留，只发送回车。
    login_after_input_str: str = "sh"


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
    """``[order]`` 命令及从 ``config.ini`` 加载的全局重试间隔。"""

    command_fail_retry_interval_time: int = DEFAULT_COMMAND_FAIL_RETRY_INTERVAL
    items: List[OrderItem] = field(default_factory=list)


@dataclass
class ConnectWifiSettings:
    """``[connect_wifi]`` 段。"""

    enable: int = 0
    test_2g_enable: int = 1
    test_5g_enable: int = 1
    product_solution: str = "openwrt"
    auth_mode: str = "WPA2-PSK"
    cipher: str = "AES"
    choose_wireless_card: int = 0
    wireless_card_name: str = ""


@dataclass
class ProjectInfoSettings:
    """``[project_info]`` 段。

    字段含义:
        project_name: 项目名称。
        software_version: 软件版本(对外版本号)。
        internal_software_version: 内部软件版本(内部构建号,可与对外版本号不同)。
        onu_compile_time: ONU 软件编译时间(自由文本,可由 /proc/version 查询回填)。
    """

    project_name: str = ""
    software_version: str = ""
    internal_software_version: str = ""
    onu_compile_time: str = ""


@dataclass
class TestProjectConfig:
    """整个 ini 文件的内存模型。"""

    telnet: TelnetSettings = field(default_factory=TelnetSettings)
    order: OrderConfig = field(default_factory=OrderConfig)
    connect_wifi: ConnectWifiSettings = field(default_factory=ConnectWifiSettings)
    project_info: ProjectInfoSettings = field(default_factory=ProjectInfoSettings)


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

    def load(self, *, required: bool = False) -> TestProjectConfig:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        if required:
            # 执行前判断空版本基准时，读取失败不能回退为空配置。
            with self.config_path.open("r", encoding="utf-8") as config_file:
                parser.read_file(config_file)
        else:
            parser.read(self.config_path, encoding="utf-8")

        return TestProjectConfig(
            telnet=self._load_telnet(parser),
            order=self._load_order(parser),
            connect_wifi=self._load_connect_wifi(parser),
            project_info=self._load_project_info(parser),
        )

    def save(self, config: TestProjectConfig) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        dumped_order = self._dump_order(config.order)
        parser[TELNET_SECTION] = self._dump_telnet(config.telnet)
        parser[ORDER_SECTION] = dumped_order
        parser[CONNECT_WIFI_SECTION] = self._dump_connect_wifi(config.connect_wifi)
        parser[PROJECT_INFO_SECTION] = self._dump_project_info(config.project_info)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            parser.write(file)
        self._sync_legacy_values(
            config.telnet.telnet_default_on,
            config.order.command_fail_retry_interval_time,
        )

    def _sync_legacy_values(
        self,
        telnet_default_on: object,
        command_fail_retry_interval: object,
    ) -> None:
        """把共用值写入 ``config.ini``，并保留其它原始内容。"""
        legacy_config_path = self.config_path.with_name(LEGACY_UI_CONFIG_FILENAME)
        legacy_store = LegacyUiDefaultsStore(legacy_config_path)
        legacy_store.update_telnet_enable_mirror(telnet_default_on)
        legacy_store.update_command_fail_retry_interval(
            command_fail_retry_interval
        )

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
            # 老 ini 没有 telnet_default_on 时回退 1(默认勾选,行为与 dataclass 默认一致)。
            telnet_default_on=_parse_int(
                parser.get(section, "telnet_default_on", fallback="1"), 1
            ),
            login_after_input_str=parser.get(section, "login_after_input_str", fallback="sh"),
        )

    def _load_order(self, parser: configparser.RawConfigParser) -> OrderConfig:
        section = ORDER_SECTION
        interval = LegacyUiDefaultsStore(
            self.config_path.with_name(LEGACY_UI_CONFIG_FILENAME)
        ).load_command_fail_retry_interval(
            DEFAULT_COMMAND_FAIL_RETRY_INTERVAL
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
            test_2g_enable=_parse_int(
                parser.get(section, "test_2g_enable", fallback="1"), 1
            ),
            test_5g_enable=_parse_int(
                parser.get(section, "test_5g_enable", fallback="1"), 1
            ),
            product_solution=parser.get(section, "product_solution", fallback="openwrt"),
            auth_mode=parser.get(section, "auth_mode", fallback="WPA2-PSK"),
            cipher=parser.get(section, "cipher", fallback="AES"),
            choose_wireless_card=_parse_int(
                parser.get(section, "choose_wireless_card", fallback="0"), 0
            ),
            wireless_card_name=parser.get(
                section, "wireless_card_name", fallback=""
            ),
        )

    def _load_project_info(self, parser: configparser.RawConfigParser) -> ProjectInfoSettings:
        # 老 ini 缺 [project_info] 段时容错:4 字段全部回退空串,不抛 NoSectionError;
        # 老 ini 仅有 3 字段(无 internal_software_version)时该字段也回退空串。
        section = PROJECT_INFO_SECTION
        return ProjectInfoSettings(
            project_name=parser.get(section, "project_name", fallback=""),
            software_version=parser.get(section, "software_version", fallback=""),
            internal_software_version=parser.get(section, "internal_software_version", fallback=""),
            onu_compile_time=parser.get(section, "onu_compile_time", fallback=""),
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
            "login_after_input_str": telnet.login_after_input_str or "",
            "telnet_need_enter_password_flag": str(_parse_int(telnet.telnet_need_enter_password_flag, 0)),
            "telnet_no_user_password_flag": str(_parse_int(telnet.telnet_no_user_password_flag, 0)),
            "only_power_off_on": str(_parse_int(telnet.only_power_off_on, 0)),
            # telnet_default_on 统一为 0/1,即便 UI 传入 Python bool 也强制转换,避免保存为 "True"/"False"。
            "telnet_default_on": str(1 if bool(telnet.telnet_default_on) else 0),
        }

    def _dump_order(self, order: OrderConfig) -> dict:
        result: dict = {}
        for item in order.items:
            key = _build_order_key(item.command, _parse_int(item.retry_times, DEFAULT_ORDER_RETRY_TIMES))
            value = _join_expected(list(item.expected_segments))
            result[key] = value
        return result

    def _dump_connect_wifi(self, wifi: ConnectWifiSettings) -> dict:
        # enable 字段统一为 0/1,即便 UI 传入 Python bool 也强制转换,避免保存为 "True"/"False"。
        return {
            "enable": str(1 if bool(wifi.enable) else 0),
            "test_2g_enable": str(1 if bool(wifi.test_2g_enable) else 0),
            "test_5g_enable": str(1 if bool(wifi.test_5g_enable) else 0),
            "product_solution": (wifi.product_solution or "openwrt").strip().lower(),
            "auth_mode": (wifi.auth_mode or "WPA2-PSK").strip(),
            "cipher": (wifi.cipher or "AES").strip(),
            "choose_wireless_card": str(1 if bool(wifi.choose_wireless_card) else 0),
            "wireless_card_name": (wifi.wireless_card_name or "").strip(),
        }

    def _dump_project_info(self, info: ProjectInfoSettings) -> dict:
        # 全部按字符串存取;空串 / None 都落盘为空,便于老 ini 缺段时回填。
        return {
            "project_name": info.project_name or "",
            "software_version": info.software_version or "",
            "internal_software_version": info.internal_software_version or "",
            "onu_compile_time": info.onu_compile_time or "",
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
    "PROJECT_INFO_SECTION",
    "ProjectInfoSettings",
    "TELNET_SECTION",
    "TelnetSettings",
    "TestItemConfigStore",
    "TestProjectConfig",
]

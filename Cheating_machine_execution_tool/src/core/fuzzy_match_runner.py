"""per-segment fuzzy match 工具（移植自老工具 fuzzy_match.py）。

背景：
- AGENTS.md 硬规则：``Auto_Power_On_Off_Tool.py`` 等老工具源码不可改；
  ``Auto_power_on_off_tool/common/fuzzy_match.py`` 也不能改。
- 本模块提供与老工具 ``Fuzzy_Match`` 相同的 per-segment 语义（``!A&&B`` 拆分、每段独立 ``!`` 否定），
  供新工具「全流程执行」管道中的「测试项配置」子任务复用，落地逻辑保留独立可单测。

语义（与老工具 [``common/fuzzy_match.py``] 一致）：
- ``!段A&&段B&&!段C`` 拆为 ``[(True,"段A"), (False,"段B"), (True,"段C")]``，
  按段独立判定（``flag=1`` 仅当所有非空段都匹配）。
- 肯定段：用 ``in`` 子串匹配（不区分大小写，由调用方预先归一化或自行 lower）。
- 否定段：用 ``re.search`` 子串搜索（老工具用 ``re.findall``，本实现简化为 ``re.search``，
  在「段不含正则元字符」的实际场景下结果一致；老工具 fuzzy_match.py:67 的 ``re.findall``
  对 ``00:00:00:00:00:00`` 这类无 ``(`` ``)`` 字符串等价于 ``in``）。
- 空段：跳过（不参与判定）。
- IPv6 特例（老工具中仅 ``tcapi get WanInfo_Entry`` 走该分支）：**不移植**，新工具测试项配置
  不下发 ``tcapi`` 命令，调用方按需要自行预处理。

实现取舍：
- 纯函数，无 IO，无全局状态；可被 ``unittest`` 直接调。
- ``match_expected`` 返回 ``bool``；调用方负责「真值 / 假值 → 匹配成功 / 失败」的主日志输出。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple


# 每段前缀「!」在老工具 fuzzy_match.py:61-74 中用 ``value.split("!")[1]`` 解析；
# 本实现用更稳的 ``startswith("!")`` + 截断，与 ``test_item_config_store._split_expected`` 对齐。
NEGATE_PREFIX = "!"

# 与老工具一致：空段在拼接结果中不写入（[``test_item_config_store._join_expected``] 的同款约定）。
EMPTY_SEGMENT_MARKER = ""


def _split_expected(value: str) -> List[Tuple[bool, str]]:
    """把 ``!段A&&段B&&!段C`` 拆成 ``[(True,"段A"), (False,"段B"), (True,"段C")]``。

    空字符串返回单个空段，由调用方过滤。语义与 ``test_item_config_store._split_expected`` 对齐。
    """
    if not value:
        return [(False, "")]
    result: List[Tuple[bool, str]] = []
    for part in value.split("&&"):
        negate = False
        if part.startswith(NEGATE_PREFIX):
            negate = True
            part = part[1:]
        result.append((negate, part))
    return result


def match_expected(result: str, expected: str) -> bool:
    """per-segment && + per-segment ! 否定；空段跳过。

    Args:
        result: 命令回显原文（来自 telnet 读回 / 串口读回）。
        expected: ini [order] 中命令的「期望」值，形如 ``ONU State: O5`` 或 ``!A&&B``。

    Returns:
        True = 所有非空段都满足；False = 至少一段不满足。
        若 expected 为空 / 全空段：返回 True（视为「无期望」= 默认通过）。

    Notes:
        - 移植自老工具 ``common/fuzzy_match.py:Fuzzy_Match + Fuzzy_Match_01``；
        - IPv6 特殊分支（``tcapi get WanInfo_Entry``）不移植。
        - 老工具用 ``re.findall``，本实现用 ``re.search``；无正则元字符的实际场景等价。
    """
    if result is None:
        result = ""
    for negate, segment in _split_expected(expected):
        if segment == EMPTY_SEGMENT_MARKER:
            continue
        if negate:
            if re.search(re.escape(segment), result):
                return False
        else:
            if segment not in result:
                return False
    return True


def iter_segments(expected: str) -> Iterable[Tuple[bool, str]]:
    """暴露 ``_split_expected`` 供单测 / 调试使用（与 ``_split_expected`` 同语义）。"""
    return iter(_split_expected(expected))


__all__ = [
    "NEGATE_PREFIX",
    "iter_segments",
    "match_expected",
]

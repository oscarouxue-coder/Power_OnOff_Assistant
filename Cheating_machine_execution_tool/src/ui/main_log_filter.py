"""主界面日志适配；AI/DUT仅精简显示，开关机WiFi摘要与文件记录共用。"""
from __future__ import annotations

import json
import re

from src.utils.wifi_log_summary import WifiLogSummary


_AI_PREFIX = re.compile(r'^\[AI(?:诊断|对话|监控|配置|案例|界面| Debug|采集|执行|网络检查)\](?= |\[)')
_CHAT = '[AI对话] '
_SESSION = r'会话[0-9a-f]{8}'
_ROUTINE = tuple(re.compile(pattern) for pattern in (
    _SESSION + r'请求模型（第\d+次交互）；估算输入\d+ Token',
    _SESSION + r'模型请求成功',
    _SESSION + r'最近请求用量：输入\d+，输出\d+，合计\d+ Token；(?:接口返回|UTF-8字节估算)',
    _SESSION + r'开始读取模型上下文容量：[^\r\n]+',
    _SESSION + r'上下文容量：(未知容量：最近50轮 / 100000字符|\d+ Token，来源=(?:手动填写|模型接口（缓存）)；'
               r'输入按UTF-8字节保守估算，输出预留\d+ Token及5%余量)',
    _SESSION + r'独立风险审查请求；模型=[^\r\n]+，估算输入\d+ Token',
    r'操作[0-9a-f]{8}风险审查开始：\w+',
))
_COLLECTION = re.compile(
    r'(?P<state>' + _SESSION + r'采集状态：[^\r\n]+?；权限=[^；\r\n]+)；'
    r'真实诊断信息（含材料中的账号、密码）发送至(?P<recipient>[^\r\n]+?)；请求工具：[^\r\n]+')
_JSON_EVENT = re.compile(
    r'(?P<event>等待操作员批准|实际执行操作|操作[0-9a-f]{8}(?:审查结果|结束))：(?P<payload>.*)', re.S)
_ACTION_STATES = {
    'succeeded': ('执行完成', 'success'), 'failed': ('执行失败', 'error'),
    'unknown': ('结果待核实', 'warning'), 'cancelled': ('已取消', 'warning'),
    'blocked': ('已拦截', 'warning'), 'rejected': ('已拒绝', 'warning'),
}
_RESULT = re.compile(r'^\[AI对话\] 操作[0-9a-f]{8}结束：[^；\r\n]+（(?P<state>\w+)）(?:；|$)')
_REVIEW = re.compile(r'^\[AI对话\] 操作[0-9a-f]{8}审查结果：(?P<risk>ordinary|dangerous|unknown|blocked)；')
_DUT_PREFIX = re.compile(r'^\[DUT配置\](?= |\[)')
_DUT_MESSAGE = re.compile(r'^\[DUT配置\](?:\[[^\]\r\n]+\])* (?P<body>[^\r\n]*)')
_DUT_DETAILS = tuple(re.compile(pattern) for pattern in (
    r'RX UBUS Device\.WiFi\.(?:X_SDMC_(?:Mapping_2G|Mapping_5G|DualBandEnable)|'
    r'(?:SSID|Radio)\.(?:\d+\.)?|AccessPoint\.(?:\d+\.(?:Security\.)?)?)：\{.*\}',
    r"RX UBUS (?:2\.4G|5G) WiFi当前状态：DutWifiSettings\(band='(?:2\.4G|5G)', .*peer_radio=None\)",
    r"RX UBUS 双频Radio当前状态：(?:2\.4G|5G)=DutWifiRadioSettings\(band='(?:2\.4G|5G)', .*\)，"
    r"(?:2\.4G|5G)=DutWifiRadioSettings\(band='(?:2\.4G|5G)', .*\)",
    r'RX UBUS WAN 完整信息：\[.*\]',
    r'RX UBUS (?:语音|TR069)当前状态：\{.*\}',
))


def is_ai_log_message(message: str) -> bool:
    """只识别程序现有AI前缀，避免把设备回显或其它业务当作AI日志。"""
    return _AI_PREFIX.match(message) is not None


def is_dut_log_message(message: str) -> bool:
    """DUT原文独立落盘；不识别其它模块或设备回显中的嵌套前缀。"""
    return _DUT_PREFIX.match(message) is not None


def ai_main_log_tag(message: str) -> str | None:
    """结果状态优先于输出正文中的成功/失败字样；其它行沿用既有颜色规则。"""
    result = _RESULT.match(message)
    if result is None:
        review = _REVIEW.match(message)
        return ('' if review['risk'] == 'ordinary' else 'warning') if review else None
    if '；错误=' in message:
        return 'error'
    if '；进程清理未确认' in message:
        return 'warning'
    state = _ACTION_STATES.get(result['state'])
    return state[1] if state else None


def _action_summary(event: str, value: dict) -> str | None:
    if event in ('等待操作员批准', '实际执行操作'):
        identifier, name = value.get('id'), value.get('name')
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier) or not isinstance(name, str):
            return None
        parts = [f'{event}：{name}', '操作' + identifier[:8]]
        if event == '等待操作员批准':
            assessment = value.get('assessment')
            if not isinstance(assessment, dict) or not isinstance(assessment.get('reason'), str):
                return None
            parts.append('原因=' + assessment['reason'])
        else:
            target, params = value.get('target'), value.get('params')
            if not isinstance(target, dict) or not isinstance(params, dict):
                return None
            if name in ('run_local_command', 'read_local_file', 'write_local_file', 'read_serial_status'):
                parts.append('本机')
                if name == 'read_serial_status':
                    parts.append('串口=' + str(target.get('port', '未知')))
            else:
                parts.append(f"通道{target.get('channel', '未知')}；目标={target.get('host', '未知')}")
            for key, label in (('path', '文件'), ('cwd', '工作目录')):
                if isinstance(params.get(key), str):
                    parts.append(label + '=' + params[key])
        return '；'.join(parts)
    if event.endswith('审查结果'):
        risk, reason = value.get('risk'), value.get('reason')
        if risk not in ('ordinary', 'dangerous', 'unknown', 'blocked') or not isinstance(reason, str):
            return None
        return f'{event}：{risk}；原因={reason}'
    state = value.get('action_state')
    if not isinstance(state, str) or state not in _ACTION_STATES:
        return None
    parts = [f'{event}：{_ACTION_STATES[state][0]}（{state}）']
    for key, label in (('status', '进程状态'), ('exit_code', '返回码'), ('error', '错误'), ('notice', '说明')):
        if value.get(key) is not None:
            parts.append(f'{label}={value[key]}')
    if value.get('dispatched') is False:
        parts.append('未下发操作命令')
    if value.get('process_cleanup_confirmed') is False:
        parts.append('进程清理未确认')
    if state == 'failed' and isinstance(value.get('stderr'), str) and value['stderr'].strip():
        error = value['stderr'].strip()
        first = error.splitlines()[0][:240]
        parts.append('错误=' + first + ('…（完整输出见主日志文件）' if first != error else ''))
    if value.get('truncated') is True:
        parts.append('原始输出已截断')
    return '；'.join(parts)


def _format_ai_message(message: str) -> str | None:
    # 实际TX/登录信息等其它AI前缀作为不透明文本保留，禁止按正文关键词过滤。
    if not message.startswith(_CHAT):
        return message
    body = message[len(_CHAT):]
    if any(pattern.fullmatch(body) for pattern in _ROUTINE):
        return None
    collection = _COLLECTION.fullmatch(body)
    if collection:
        return _CHAT + collection['state'] + '；发送至=' + collection['recipient']
    event = _JSON_EVENT.fullmatch(body)
    if event:
        try:
            value = json.loads(event['payload'])
            if isinstance(value, dict):
                result = _action_summary(event['event'], value)
                if result is not None:
                    return _CHAT + result
        except (ValueError, TypeError):
            pass  # 损坏或新格式原样可见，不能因显示摘要丢失异常。
    return message


def format_main_log_message(message: str, summary: WifiLogSummary | None = None) -> str | None:
    """保留既有入口；有状态的调用者传入自己的摘要器。"""
    if is_ai_log_message(message):
        return _format_ai_message(message)
    if is_dut_log_message(message):
        # 只收起core已校验/解析后发出的已知详情；命令、配置结果、异常与新格式保持可见。
        event = _DUT_MESSAGE.fullmatch(message)
        if event and any(pattern.fullmatch(event['body']) for pattern in _DUT_DETAILS):
            return None
        return message
    return (summary if summary is not None else WifiLogSummary()).format(message)

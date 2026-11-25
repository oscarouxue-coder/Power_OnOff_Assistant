"""主界面日志适配；AI/DUT仅精简显示，开关机WiFi摘要与文件记录共用。"""
from __future__ import annotations

import json
import re

from src.utils.wifi_log_summary import WifiLogSummary


_AI_PREFIX = re.compile(r'^\[(?:AI(?:诊断|对话|监控|配置|案例|界面| Debug|采集|执行|网络检查|资料|证据)'
                        r'|Ai助手|AI 诊断|钉钉接入|飞书接入)\](?= |\[)')
_CHAT = '[AI对话] '
_MONITOR = '[AI监控] '
_SESSION = r'会话[0-9a-f]{8}'
_COLLECTION_TOOL = (r'(?:read_test_evidence|read_pc_environment|read_serial_log|read_dut_state|'
                    r'read_network_state|probe_connectivity|capture_packets|follow_logs|kernel_debug)')
_QUIET_COLLECTION_REASONS = (
    '默认允许主动采集', '本机电脑独立排障，仅开放本机工具',
    '普通问答未绑定排查目标，不执行工具', '历史批次仅分析留存材料，请为当前批次新建会话',
    '目标或登录配置已变化，仅分析留存材料，请新建会话', '模型配置已变更或删除，请新建会话',
    '模型未通过工具能力验证，仅分析已有材料',
    '本轮工具额度已用尽，仅根据已获得证据回答；可发送下一条消息继续',
)
_ROUTINE = tuple(re.compile(pattern) for pattern in (
    _SESSION + r'请求模型（第\d+次交互）；估算输入\d+ Token',
    _SESSION + r'模型请求成功',
    _SESSION + r'最近请求用量：输入\d+，输出\d+，合计\d+ Token；(?:接口返回|UTF-8字节估算)',
    _SESSION + r'开始读取模型上下文容量：[^\r\n]+',
    _SESSION + r'上下文容量：(未知容量：最近50轮 / 100000字符|\d+ Token，来源=(?:手动填写|模型接口（缓存）)；'
               r'输入按UTF-8字节保守估算，输出预留\d+ Token及5%余量)',
    _SESSION + r'独立风险审查请求；模型=[^\r\n]+，估算输入\d+ Token',
    r'操作[0-9a-f]{8}风险审查开始：\w+',
    _SESSION + r'开始采集：' + _COLLECTION_TOOL + r'，目标=[^；\r\n]+',
    _SESSION + r'工具完成：(?:' + _COLLECTION_TOOL + r'|run_local_command|run_dut_command|'
               r'read_local_file|write_local_file|read_serial_status|update_diagnostic_plan)',
    _SESSION + r'连续诊断计划更新：\[[^\r\n]*\]',
    _SESSION + r'收到诊断补充；(?:下一安全检查点采用|等待下一安全检查点)，不授予新操作权限',
    _SESSION + r'(?:已采用|已留存)\d+条诊断补充，原始记录保留',
    _SESSION + r'跳过重复诊断检查：\w+，证据=[0-9a-f]{32}',
    r'操作[0-9a-f]{8}已跳过独立审查：完全访问，授权=[0-9a-f]{32}',
    r'开始识别对话目标；仅发送目标标识和最近对话，不执行操作',
    r'路由(?:新建|续接)' + _SESSION + r'，目标=(?:通道\d+|本机电脑|普通问答)',
    _SESSION + r'完全访问已自动生效；目标/模型/批次已校验，跳过独立审查',
    _SESSION + r'完全访问暂未生效：(?:' + '|'.join(map(re.escape, _QUIET_COLLECTION_REASONS)) + r')',
    _SESSION + r'完全访问暂未生效：批量目标配置已变化，停止执行',
    r'创建会话 [0-9a-f]{8}，批次=[^，\r\n]*，目标=(?:通道\d+|本机电脑|普通问答)，模型=[^；\r\n]+',
    r'文件读取完成：[^，\r\n]+，字节=\d+，截断=False',
    r'开始只读串口诊断：COM\d+',
))
# 已知正常整行才收起；TX后的命令/登录值是不透明载荷，可包含换行或“失败”等字样。
_AI_DETAILS = tuple(re.compile(pattern) for pattern in (
    r'\[AI资料\] 检索完成：已确认案例\d+，操作员章节\d+；未命中不补入无关资料',
    r'\[AI证据\] 开始整理本次目标证据与样机故障线索',
    r'\[AI证据\] 完成：候选\d+，选取\d+，省略\d+，隔离\d+，截断\d+；来源=[^\r\n]+',
    r'\[AI案例\] 开始(?:汇集旧库及项目库中的人工确认案例|导入随包案例快照)',
    r'\[AI案例\] [^；\r\n]+导入完成：新增\d+，跳过\d+',
    r'\[AI案例\] 旧库汇集成功：新增\d+',
    r'\[AI采集\] 开始：' + _COLLECTION_TOOL + r'，通道\d+',
    r'\[AI采集\] 完成：' + _COLLECTION_TOOL,
    r'\[AI采集\] 开始读取本机电脑环境；未绑定样机',
    r'\[AI采集\] 本机电脑环境读取完成；无目标网卡推断',
    r'\[AI监控\] 状态更新：AI自动监控：(?:已关闭|诊断中|诊断排队中|监控中|已开启，待测试)',
    r'\[AI监控\] 操作[0-9a-f]{8}独立风险审查请求；模型=[^；\r\n]+',
    r'\[AI监控\] 操作[0-9a-f]{8}(?:风险审查开始：\w+|已跳过独立审查：完全访问，授权=[0-9a-f]{32})',
    r'\[钉钉接入\] 已接收群消息 [^\r\n]{1,12}，等待会话处理',
    r'\[钉钉接入\] 群成员会话已关联：[0-9a-f]{8}，通道\d+',
    r'\[钉钉接入\] 群回复发送成功（钉钉已接受）',
    r'\[飞书接入\] 已接收(?:群聊|单聊)消息 [^\r\n]{1,12}',
    r'\[飞书接入\] 飞书成员会话已关联：[0-9a-f]{8}，通道\d+',
    r'\[飞书接入\] 下发飞书回复：POST /open-apis/im/v1/messages（凭据省略）',
    r'\[飞书接入\] 飞书回复发送成功（接口已接受）',
    r'\[飞书接入\] 飞书回复跳过：本轮无临时修改；完整恢复记录保留本地',
    r'\[飞书接入\] (?:正在连接飞书（HTTPS注册 / WSS）|飞书长连接已连接)',
    r'\[钉钉接入\] (?:正在连接|已连接)',
    r'\[AI Debug\] 尝试 Telnet：通道\d+，源IP=[^，\r\n]+，目标=[^:\r\n]+:\d+',
    r'\[AI Debug\] Telnet 登录成功',
    r'\[AI Debug\] 已复用通道\d+ COM\d+，Shell已确认',
    r'\[AI Debug\] TX 登录(?:用户名|密码)：[\s\S]*',
    r'\[AI Debug\]\[(?:Telnet|telnet|串口|serial)\] TX：[\s\S]*',
    r'\[AI(?:采集|网络检查)\] PC TX：[\s\S]*',
    r'\[AI执行\] PC TX（cwd=[^\r\n]+，超时=\d+秒）：[\s\S]*',
    r'\[AI(?:采集|网络检查)\] PC RX：[^；\r\n]+；(?:成功；)?返回码=0；编码=[\w.-]+',
))
_COLLECTION = re.compile(
    r'(?P<state>' + _SESSION + r'采集状态：(?P<reason>[^\r\n]+?)；权限=[^；\r\n]+)；'
    r'真实诊断信息（含材料中的账号、密码）发送至(?P<recipient>[^\r\n]+?)；请求工具：[^\r\n]+')
_CHAT_START = re.compile(r'(?P<session>' + _SESSION + r')收到问题，进入排查队列；其它会话继续')
_CHAT_FINISH = re.compile(
    r'(?P<session>' + _SESSION + r')本轮结束；恢复状态：(?P<fixed>固定采集：)?'
    r'(?P<recovery>无临时修改|已恢复，临时文件已清理|已恢复/已停止本次采集进程)'
    r'(?P<notice>；本轮通用操作的实际变更不自动回滚，结果待核实的操作须人工核对。)?')
_JSON_EVENT = re.compile(
    r'(?P<event>读取本机文件|等待操作员批准|实际执行操作|操作[0-9a-f]{8}(?:审查结果|结束))：(?P<payload>.*)', re.S)
_ACTION_STATES = {
    'succeeded': ('执行完成', 'success'), 'failed': ('执行失败', 'error'),
    'unknown': ('结果待核实', 'warning'), 'cancelled': ('已取消', 'warning'),
    'blocked': ('已拦截', 'warning'), 'rejected': ('已拒绝', 'warning'),
}
_NORMAL_ACTION_NOTICES = (
    '命令返回Shell提示符；业务是否成功须依据实际输出或后续查询核对',
    '停止/超时只清理本次进程，不代表其已产生的系统或设备变更已回滚',
)
_RESULT = re.compile(r'^\[AI(?:对话|监控)\] 操作[0-9a-f]{8}结束：[^；\r\n]+（(?P<state>\w+)）(?:；|$)')
_REVIEW = re.compile(r'^\[AI(?:对话|监控)\] 操作[0-9a-f]{8}审查结果：(?P<risk>ordinary|dangerous|unknown|blocked)；')
_SERIAL_RESULT = re.compile(r'^\[AI(?:对话|监控)\] COM\d+ 串口诊断完成；')
_INVALID_CONNECTION = ('命令已下发但连接失效，执行结果待核实；'
                       '未自动切换通道或重新登录，请重新请求查询并确认新连接')
_SHORT_CONNECTION = '连接失效，已下发结果待核实；不自动重试，请重新查询确认连接'
_COLLECTION_FAILURE = re.compile(
    r'(?P<head>\[AI采集\] 跳过/失败：' + _COLLECTION_TOOL + r'|'
    + _SESSION + r'工具跳过/失败：' + _COLLECTION_TOOL + r')；' + re.escape(_INVALID_CONNECTION))
_TEXT_FAILURE = re.compile(
    r'(?P<head>操作[0-9a-f]{8}结束：(?:执行失败（failed）|结果待核实（unknown）))；错误='
    + re.escape(_INVALID_CONNECTION) + r'(?P<undispatched>；(?:说明=)?未下发操作命令){0,2}')
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


_RESOURCE_MONITOR_START = re.compile(
    r'\[资源监测\] 开始：每\d+(?:\.\d+)?秒只读采样；记录=[^\r\n]+[\\/]'
    r'transport_history_\d{8}_\d{6}_\d{6}\.jsonl')
_RESOURCE_MONITOR_STOP = '[资源监测] 已停止采样，未清理原始日志或历史缓冲'


def is_ai_log_message(message: str) -> bool:
    """只识别程序现有AI前缀，避免把设备回显或其它业务当作AI日志。"""
    return _AI_PREFIX.match(message) is not None


def is_dut_log_message(message: str) -> bool:
    """DUT原文独立落盘；不识别其它模块或设备回显中的嵌套前缀。"""
    return _DUT_PREFIX.match(message) is not None


def is_resource_monitor_log_message(message: str) -> bool:
    """资源监测原文保留落盘，显示层仅隐藏已知正常生命周期提示。"""
    return message.startswith('[资源监测] ')


def ai_main_log_tag(message: str) -> str | None:
    """结果状态优先于输出正文中的成功/失败字样；其它行沿用既有颜色规则。"""
    if _SERIAL_RESULT.match(message):
        if any(text in message for text in ('；串口枚举失败', '；PnP查询失败', '；打开错误=')):
            return 'error'
        if any(text in message for text in ('；未枚举到目标', '；PnP异常=', '；控制占用',
                                            '；正在关闭', '；电源串口冲突', '；内部占用状态未知')):
            return 'warning'
        return ''  # 只读查询完成不代表串口可打开或设备健康。
    result = _RESULT.match(message)
    if result is None:
        review = _REVIEW.match(message)
        return ('' if review['risk'] == 'ordinary' else 'warning') if review else None
    if '；错误=' in message:
        return 'error'
    if '；进程清理未确认' in message:
        return 'warning'
    if result['state'] == 'succeeded':
        exit_code = re.search(r'；返回码=(-?\d+)', message)
        status = re.search(r'；进程状态=([^；\r\n]+)', message)
        notice = message.partition('；说明=')[2]
        if (any(text in message for text in ('；标准错误=', '；原始输出已截断', '；未下发操作命令'))
                or exit_code is not None and int(exit_code[1]) != 0
                or status is not None and status[1] not in ('completed', 'succeeded')
                or notice and notice not in _NORMAL_ACTION_NOTICES):
            return 'warning'
    state = _ACTION_STATES.get(result['state'])
    return state[1] if state else None


def _serial_summary(value: dict) -> str | None:
    """只压缩已知串口快照；未知结构保留原文，查询错误不展开命令/驱动JSON。"""
    known = {'configured_com', 'ports', 'pnp', 'external_owner', 'internal', 'notice',
             'enumerated', 'enumeration_error', 'pnp_error'}
    internal_keys = {'port', 'opened_in_program', 'closing_in_program', 'monitor_owners',
                     'control_owner', 'last_open_error', 'power_port_conflict', 'notice'}
    port, internal = value.get('configured_com'), value.get('internal')
    if (set(value) - known or not isinstance(port, str) or not re.fullmatch(r'COM\d+', port, re.I)
            or not isinstance(internal, dict)
            or set(internal) - internal_keys
            or not isinstance(internal.get('port', port), str)
            or internal.get('port', port).upper() != port.upper()
            or any(key in internal and type(internal[key]) is not bool
                   for key in ('opened_in_program', 'closing_in_program', 'power_port_conflict'))
            or internal.get('notice') not in (None, '', '未接入内部占用快照')
            or value.get('notice') not in (None, '', '管理员身份不排除访问限制；设备存在也不等于可打开。查询不打开COM。')
            or not all(isinstance(value.get(key), list) and all(isinstance(item, dict) for item in value[key])
                       for key in ('ports', 'pnp'))
            or ('enumerated' in value and type(value['enumerated']) is not bool)
            or ('enumerated' not in value and 'enumeration_error' not in value)):
        return None
    parts = [port.upper() + ' 串口诊断完成']
    if 'enumeration_error' in value:
        parts.append('串口枚举失败（详情见主日志文件）')
    else:
        parts.append('已枚举' if value['enumerated'] else '未枚举到目标')
    if internal.get('opened_in_program') is True:
        parts.append('程序内已打开')
    if internal.get('closing_in_program') is True:
        parts.append('正在关闭')
    if internal.get('control_owner'):
        parts.append('控制占用')
    if internal.get('power_port_conflict') is True:
        parts.append('电源串口冲突')
    if internal.get('notice'):
        parts.append('内部占用状态未知')
    if internal.get('last_open_error'):
        error = internal['last_open_error']
        if not isinstance(error, str):
            return None
        first = error.splitlines()[0][:120] if error.splitlines() else ''
        parts.append('打开错误=' + first + ('…（详情见主日志文件）' if first != error else ''))
    if 'pnp_error' in value:
        parts.append('PnP查询失败（详情见主日志文件）')
    abnormal = sum(item.get('present') is False or item.get('problem_code') not in (None, 0)
                   or item.get('status') not in (None, '', 'OK') for item in value['pnp'])
    if abnormal:
        parts.append(f'PnP异常={abnormal}项（详情见主日志文件）')
    external = value.get('external_owner')
    if external not in (None, '', '未知'):
        return None  # 当前生产者不识别外部占用者；新格式不能擅自解释。
    return '；'.join(parts)


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
            if key == 'notice' and (value[key] == value.get('error')
                                   or value[key] == '未下发操作命令' and value.get('dispatched') is False):
                continue
            content = _SHORT_CONNECTION if key == 'error' and value[key] == _INVALID_CONNECTION else value[key]
            parts.append(f'{label}={content}')
    if value.get('dispatched') is False:
        parts.append('未下发操作命令')
    if value.get('process_cleanup_confirmed') is False:
        parts.append('进程清理未确认')
    if state in ('failed', 'succeeded') and isinstance(value.get('stderr'), str) and value['stderr'].strip():
        error = value['stderr'].strip()
        first = error.splitlines()[0][:240]
        parts.append(('错误=' if state == 'failed' else '标准错误=') + first
                     + ('…（完整输出见主日志文件）' if first != error else ''))
    if value.get('truncated') is True:
        parts.append('原始输出已截断')
    return '；'.join(parts)


def _format_ai_message(message: str) -> str | None:
    prefix = next((p for p in (_CHAT, _MONITOR) if message.startswith(p)), None)
    body = message[len(prefix):] if prefix else message
    if any(pattern.fullmatch(candidate) for pattern in _AI_DETAILS for candidate in (message, body)):
        return None
    failure = _COLLECTION_FAILURE.fullmatch(body)
    if failure:
        return (prefix or '') + failure['head'] + '；' + _SHORT_CONNECTION
    if prefix is None:
        return message
    text_failure = _TEXT_FAILURE.fullmatch(body)
    if text_failure:
        return (prefix + text_failure['head'] + '；错误=' + _SHORT_CONNECTION
                + ('；未下发操作命令' if text_failure['undispatched'] else ''))
    if body.startswith('串口诊断完成：'):
        try:
            value = json.loads(body[len('串口诊断完成：'):])
            result = _serial_summary(value) if isinstance(value, dict) else None
            return prefix + result if result is not None else message
        except (ValueError, TypeError):
            return message
    if any(pattern.fullmatch(body) for pattern in _ROUTINE):
        return None
    start = _CHAT_START.fullmatch(body)
    if start:
        return prefix + start['session'] + '开始排查（已入队）'
    finish = _CHAT_FINISH.fullmatch(body)
    if finish and bool(finish['fixed']) == bool(finish['notice']):
        result = prefix + finish['session'] + '本轮结束'
        if finish['recovery'] != '无临时修改':
            result += '；临时操作已恢复'
        if finish['notice']:
            result += '；通用操作不自动回滚，待核实结果请人工核对'
        return result
    collection = _COLLECTION.fullmatch(body)
    if collection:
        if collection['reason'] in _QUIET_COLLECTION_REASONS:
            return None
        return prefix + collection['state'] + '；发送至=' + collection['recipient']
    event = _JSON_EVENT.fullmatch(body)
    if event:
        try:
            value = json.loads(event['payload'])
            if isinstance(value, dict):
                if event['event'] == '读取本机文件':
                    if (set(value) == {'path', 'offset_bytes', 'max_bytes'}
                            and isinstance(value['path'], str) and type(value['offset_bytes']) is int
                            and value['offset_bytes'] >= 0 and type(value['max_bytes']) is int and value['max_bytes'] > 0):
                        return None
                    return message
                result = _action_summary(event['event'], value)
                if result is not None:
                    if event['event'] == '实际执行操作':
                        return None
                    if event['event'].endswith('审查结果') and value['risk'] == 'ordinary':
                        return None
                    if (event['event'].endswith('结束') and value.get('action_state') == 'succeeded'
                            and not value.get('error') and not value.get('stderr')
                            and value.get('exit_code') in (None, 0)
                            and value.get('status') in (None, 'completed', 'succeeded')
                            and value.get('notice') in (None, '') + _NORMAL_ACTION_NOTICES
                            and value.get('process_cleanup_confirmed') is not False
                            and value.get('dispatched') is not False and value.get('truncated') is not True):
                        return None
                    return prefix + result
        except (ValueError, TypeError):
            pass  # 损坏或新格式原样可见，不能因显示摘要丢失异常。
    return message


class FeishuConnectionLogState:
    """仅合并主界面同一次断线提示；原始日志和实际连接状态不受影响。"""
    def __init__(self):
        self.failed = False

    def format(self, message: str) -> str | None:
        prefix = next((p for p in (_CHAT, _MONITOR) if message.startswith(p)), '')
        body = message[len(prefix):]
        platform = '[飞书接入] '
        if not body.startswith(platform):
            return message
        event = body[len(platform):]
        if event in ('飞书连接失败或断开，稍后重连（凭据省略）', '飞书连接已断开，稍后重连（凭据省略）'):
            if self.failed:
                return None
            self.failed = True
        elif event == '飞书长连接已连接':
            recovering = self.failed
            self.failed = False
            if recovering:
                return prefix + platform + '飞书连接已恢复'
        elif event == '飞书连接已停止':
            self.failed = False
        return message


def format_main_log_message(message: str, summary: WifiLogSummary | None = None, *,
                            feishu_state: FeishuConnectionLogState | None = None) -> str | None:
    """保留既有入口；有状态的调用者传入自己的摘要器。"""
    if message == _RESOURCE_MONITOR_STOP or _RESOURCE_MONITOR_START.fullmatch(message):
        return None
    if feishu_state is not None:
        message = feishu_state.format(message)
        if message is None:
            return None
    if is_ai_log_message(message):
        return _format_ai_message(message)
    if is_dut_log_message(message):
        # 只收起core已校验/解析后发出的已知详情；命令、配置结果、异常与新格式保持可见。
        event = _DUT_MESSAGE.fullmatch(message)
        if event and any(pattern.fullmatch(event['body']) for pattern in _DUT_DETAILS):
            return None
        return message
    return (summary if summary is not None else WifiLogSummary()).format(message)

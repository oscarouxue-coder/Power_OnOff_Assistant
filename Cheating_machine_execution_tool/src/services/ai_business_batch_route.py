"""Fast, explicit multi-channel business intent; never grants targets or executes an action."""
import re


def fast_business_batch(text, current, targets, fresh=False):
    if fresh:
        return None
    text = text.strip()
    current_business = bool((current or {}).get('capability_business_batch'))
    if current_business and re.fullmatch(r'确认固件适配\s+[0-9a-f]{8}', text):
        return dict(intent='continue', scope='batch', channel=None,
            channels=[t['channel'] for t in current['batch_targets']], question=text, clarification='', workflow='business')
    if current_business and re.fullmatch(r'(?:请|帮我)?(?:继续|查询任务状态|查询升级状态|查看任务结果|停止升级|停止挂测|取消业务)[。！!\s]*', text):
        return dict(intent='continue', scope='batch', channel=None,
            channels=[t['channel'] for t in current['batch_targets']], question=text, clarification='', workflow='business')
    if re.search(r'原因|为什么|分析|排查|不要|不能|是否|日志|昨天|上次|曾经', text):
        return None
    if not re.match(r'^(?:(?:请|帮我|麻烦|给我|给|把|对|将)\s*)*(?:升级|上电|下电|挂测|启动|执行|老化|写参|写入|查询|读取|核对|通道|全部|所有)', text):
        return None
    action = re.search(r'升级|上电|下电|挂测|老化|开关机测试|写参|写入参数|(?:查询|读取|核对).{0,20}版本', text)
    if action is None:
        return None
    listed = re.search(r'通道\s*(\d{1,2}(?:\s*[、,，和及与]\s*(?:通道\s*)?\d{1,2})+)(?!\d)', text)
    if listed:
        channels = [int(n) for n in re.findall(r'\d+', listed[1])]
    elif re.search(r'(?:全部|所有)(?:当前|已选)?(?:通道|样机|设备)', text):
        channels = [target.channel for target in targets]
    else:
        return None
    if len(channels) < 2:
        return None
    # The existing batch router validates every channel against current targets.
    return dict(intent='switch', scope='batch', channel=None, channels=channels,
                question=text, clarification='', workflow='business')

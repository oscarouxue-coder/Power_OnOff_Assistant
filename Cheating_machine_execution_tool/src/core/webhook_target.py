"""识别受支持的群机器人地址；错误信息不包含原始地址。"""
import re
from urllib.parse import parse_qs, urlsplit


def detect_platform(webhook):
    try:
        value = webhook.strip()
        parts = urlsplit(value)
        safe = (parts.scheme == 'https' and parts.port in (None, 443)
                and not parts.username and not parts.password and not parts.fragment
                and not any(char.isspace() or ord(char) < 32 for char in value))
        if safe:
            if (parts.hostname == 'oapi.dingtalk.com' and parts.path == '/robot/send'
                    and any(token.strip() for token in parse_qs(parts.query).get('access_token', []))):
                return 'dingtalk'
            if (parts.hostname == 'open.feishu.cn' and not parts.query
                    and re.fullmatch(r'/open-apis/bot/v2/hook/[A-Za-z0-9_-]+', parts.path)):
                return 'feishu'
    except (AttributeError, ValueError):
        pass
    raise ValueError('请填写完整的钉钉或飞书机器人 HTTPS Webhook 地址。')


PLATFORM_NAMES = {'dingtalk': '钉钉', 'feishu': '飞书'}
SAFE_ENDPOINTS = {
    'dingtalk': 'https://oapi.dingtalk.com/robot/send',
    'feishu': 'https://open.feishu.cn/open-apis/bot/v2/hook/（凭据省略）',
}

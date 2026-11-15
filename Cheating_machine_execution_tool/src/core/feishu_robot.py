"""飞书群自定义机器人单次发送，不使用应用凭据，不自动重试。"""
import base64
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.core.webhook_target import detect_platform


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_text(webhook, secret, content, at_all=False):
    if detect_platform(webhook) != 'feishu':
        raise ValueError('请填写完整的飞书机器人 HTTPS Webhook 地址。')
    if at_all:
        content += '\n<at user_id="all">所有人</at>'
    payload = {'msg_type': 'text', 'content': {'text': content}}
    if secret.strip():
        timestamp = str(int(time.time()))
        key = f'{timestamp}\n{secret.strip()}'.encode('utf-8')
        payload.update(timestamp=timestamp,
                       sign=base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode('ascii'))
    request = Request(webhook.strip(), data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            body = response.read(65537)
            if response.status != 200:
                raise RuntimeError('飞书接口返回非成功 HTTP 状态。')
        if len(body) > 65536:
            raise RuntimeError('飞书返回内容过长，发送结果未知。')
        result = json.loads(body)
    except HTTPError as exc:
        raise RuntimeError(f'飞书接口 HTTP 错误：{exc.code}。') from None
    except (OSError, URLError):
        raise RuntimeError('飞书网络连接失败或超时，发送结果未知；请先检查群消息，避免重复发送。') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('飞书返回内容无法解析，发送结果未知。') from None
    code = result.get('code') if isinstance(result, dict) else None
    if type(code) is not int:
        raise RuntimeError('飞书返回内容缺少有效的错误码，发送结果未知。')
    if code != 0:
        raise RuntimeError(f'飞书拒绝发送，错误码 {code}；请检查机器人安全设置、密钥和关键词。')

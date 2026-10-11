"""钉钉自定义机器人单次发送；异常与日志不携带凭据。"""
import base64
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_text(webhook, secret, content, at_all=False):
    try:
        parts = urlsplit(webhook.strip())
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        valid = (parts.scheme == 'https' and parts.hostname == 'oapi.dingtalk.com'
                 and parts.path == '/robot/send' and parts.port in (None, 443)
                 and not parts.username and not parts.password and not parts.fragment
                 and bool(query.get('access_token', '').strip()))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('请填写完整的钉钉机器人 HTTPS Webhook 地址（包含 access_token）。')
    query.pop('timestamp', None)
    query.pop('sign', None)
    if secret.strip():
        secret = secret.strip()
        timestamp = str(int(time.time() * 1000))
        signature = hmac.new(secret.encode(), f'{timestamp}\n{secret}'.encode(), hashlib.sha256).digest()
        query.update(timestamp=timestamp, sign=base64.b64encode(signature).decode())
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
    payload = {'msgtype': 'text', 'text': {'content': content}, 'at': {'isAtAll': at_all}}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            body = response.read(65537)
            if response.status != 200:
                raise RuntimeError('钉钉接口返回非成功 HTTP 状态。')
        result = json.loads(body)
    except HTTPError as exc:
        raise RuntimeError(f'钉钉接口 HTTP 错误：{exc.code}。') from None
    except (OSError, URLError):
        raise RuntimeError('网络连接失败或超时，发送结果未知；请先检查群消息，避免重复发送。') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('钉钉返回内容无法解析，发送结果未知。') from None
    code = result.get('errcode') if isinstance(result, dict) else None
    if type(code) is not int:
        raise RuntimeError('钉钉返回内容缺少有效的错误码，发送结果未知。')
    if code != 0:
        raise RuntimeError(f'钉钉拒绝发送，错误码 {code}；请检查机器人安全设置、密钥和关键词。')

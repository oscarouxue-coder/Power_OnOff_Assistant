"""Shared simulated notification destinations and HTTP replies."""
import json
from unittest.mock import Mock


FEISHU = 'https://open.feishu.cn/open-apis/bot/v2/hook/demo-token'
DINGTALK = 'https://oapi.dingtalk.com/robot/send?access_token=demo-token'


def response(payload, status=200):
    result = Mock(status=status)
    result.read.return_value = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=result)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    return opener

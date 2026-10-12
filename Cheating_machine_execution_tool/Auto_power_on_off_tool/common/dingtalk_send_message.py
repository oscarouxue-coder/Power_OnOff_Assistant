# https://open.dingtalk.com/document/orgapp/robot-sends-nail-message
import json

import requests
import time
import hmac
import base64
import hashlib
import urllib
from pathlib import Path

from config.config_driver import OperationConfig
from src.services.message_push_config_service import load_push_project_name


class DingTalk(object):
    def __init__(self):
        self.cf = OperationConfig()
        self.log = print

    def create_sign(self, access_code, secret):
        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        # print(timestamp)
        # print(sign)
        sign_enc = '%s&timestamp=%s&sign=%s' % (access_code, timestamp, sign)
        return sign_enc

    def webhook_send_message(self, device_type, message,normal_flag=0):
        try:
            dingtalk_flag = int(
                self.cf.read_ini('dingtalk_config', 'dingtalk_flag',
                                 path='./config/config.ini').strip())
            if dingtalk_flag == 0:
                self.log('[消息推送] 自动推送关闭，跳过发送。')
                return True
            try:
                project_name = load_push_project_name(Path('./config/test_project_config.ini'), log=self.log)
            except ValueError as exc:
                self.log(f'[消息推送] 正式发送失败：{exc}')
                return exc
            dingtalk_config = self.cf.read_config_file('./config/config.ini', 'dingtalk_config')
            remote_tool_name = self.cf.read_ini('remote_config', 'remote_tool_name',
                                                path='./config/config.ini').strip()
            remote_identification_code = self.cf.read_ini('remote_config', 'remote_identification_code',
                                                          path='./config/config.ini').strip()
            remote_verification_code = self.cf.read_ini('remote_config', 'remote_verification_code',
                                                        path='./config/config.ini').strip()

            access_code = dingtalk_config['webhook'].split('=')[1].strip()
            secret = dingtalk_config['secret'].strip()
            at_all = dingtalk_config['at_all'].strip()
            if at_all == "0":
                at_all = False
            else:
                at_all = True
            sign_enc = self.create_sign(access_code, secret)
            url = f'https://oapi.dingtalk.com/robot/send?access_token={sign_enc}'

            if normal_flag:
                data = {
                    "msgtype": "markdown",
                    "markdown": {
                        'title': f'## {project_name} 挂测开关机完成',
                        "text": f"## <font color='#339933'>{project_name} 挂测开关机完成</font>  \n\n"
                                f"> #### <font color='#339933'>{message}</font>    \n\n\n\n"
                                f"> ###### 远程客户端信息  \n\n"
                                f"> ###### 远程工具名称：{remote_tool_name} \n"
                                f"> ###### 识别码：{remote_identification_code} \n"
                                f"> ###### 验证码：{remote_verification_code}"
                    },
                    "at": {
                        "isAtAll": at_all  # 如果需要@所有人，设置为True
                    }
                }
            else:
                data = {
                    "msgtype": "markdown",
                    "markdown": {
                        'title': f'## {project_name} 挂测开关机出现异常',
                        "text": f"## <font color='#FFA500'>{project_name} 挂测开关机出现异常</font>  \n\n"
                                f"> #### <font color='#FF0000'>{message}</font>    \n\n\n\n"
                                f"> ###### 远程客户端信息  \n\n"
                                f"> ###### 远程工具名称：{remote_tool_name} \n"
                                f"> ###### 识别码：{remote_identification_code} \n"
                                f"> ###### 验证码：{remote_verification_code}"
                    },
                    "at": {
                        "isAtAll": at_all  # 如果需要@所有人，设置为True
                    }
                }

            self.log('[消息推送] 下发正式消息：POST https://oapi.dingtalk.com/robot/send（凭据省略）。')
            res = requests.post(url, json=data)
            # print(res.json()['errcode'])
            result = res.json()['errcode']
            if result == 0:
                self.log('[消息推送] 正式发送成功（钉钉已接受）。')
                return True
            else:
                detail = f'钉钉接口拒绝消息，错误码：{result}'
                self.log(f'[消息推送] 正式发送失败：{detail}')
                return detail
        except Exception as e:
            detail = '正式发送失败，结果未知；请检查配置和群消息。'
            self.log(f'[消息推送] {detail}')
            return RuntimeError(detail)

    def post_image(self):
        # 钉钉机器人的 Webhook URL
        webhook_url = 'https://oapi.dingtalk.com/robot/send?access_token=685addef60205dbc25f92de22295f4f225e7488abe1852373eefc81bcc0fa5dc'

        # 本地图片路径
        image_path = '/path/to/your/local/image.png'

        # 上传图片
        with open(image_path, 'rb') as f:
            files = {'media': f}
            response = requests.post(webhook_url, files=files)
            result = response.json()

        # 获取图片 URL
        image_url = result.get('url')


if __name__ == "__main__":
    secret = 'SECd9e35f3125c0ae2e8b8366f65c3d119056556bfde372471b06dff882222359a6'
    dingtalk = DingTalk()
    dingtalk.webhook_send_message('大王饶命')

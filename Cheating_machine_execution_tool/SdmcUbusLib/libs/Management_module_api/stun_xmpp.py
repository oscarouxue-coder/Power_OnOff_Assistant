import os
import json
import time
import requests

from SdmcLog import log
from SdmcCode import ERR_SUCCESS
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class StunXmppManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def upload_file(self, device_url, local_file_path, device_save_path):
        """
        【功能描述】
        上传文件到设备（纯上传功能，不包含登录）

        【入参】
        device_url: 上传接口URL（str / 必填）
        local_file_path: 本地文件路径（str / 必填）
        device_save_path: 设备端保存路径（str / 必填）

        【返回值】
        status_code  : 执行状态码
        response_text : 执行结果

        【示例】
        Example:
        |  Some Keyword  |  device_url=  |  local_file_path=  |  device_save_path=  |

        """

        if not os.path.isfile(local_file_path):
            raise FileNotFoundError(f"本地文件不存在: {local_file_path}")

        filenameOnly = os.path.basename(device_save_path)
        with open(local_file_path, 'rb') as f:
            files = {'file': (filenameOnly, f, 'application/octet-stream')}
            data = {'sessionid': self.ubus.ubus_rpc_session, 'filename': device_save_path}
            response = requests.post(device_url, files=files, data=data, timeout=30)
            response.raise_for_status()
            return response.status_code, response.text

    def upload_file_to_device(self, device_url, local_file_path, device_save_path):
        """
        【功能描述】
        上传固件文件到设备（包含错误处理和日志记录）

        【入参】
        device_url: 设备接收文件的 URL（str / 必填）
        local_file_path: 本地证书文件路径（str / 必填）
        device_save_path: 设备保存路径（str / 必填）

        【返回值】
        status_code  : 执行状态码
        response_text : 执行结果

        【示例】
        Example:
        |  Some Keyword  |  device_url=http://192.168.1.1/cgi-bin/cgi-upload  |  local_file_path=cwmp.crt  |  device_save_path=/etc/icwmpd/ca-certificates.crt  |

        """

        try:
            status_code, msg = self.upload_file(device_url, local_file_path, device_save_path)
            return status_code, msg
        except FileNotFoundError as e:
            print(f"文件未找到: {e}")
            raise
        except requests.RequestException as e:
            print(f"上传请求失败: {e} (URL: {device_url})")
            return 500, f"Upload failed: {str(e)}"
        except Exception as e:
            print(f"未知错误: {e}")
            return 500, f"Internal error: {str(e)}"

    def get_stun_setting_info(self):
        try:
            params = {
                "path": "Device.ManagementServer.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]
            management_server = data.get('ManagementServer', {})

            stun_enable = management_server.get('STUNEnable')
            stun_server_port = management_server.get('STUNServerPort')
            stun_server_address = management_server.get('STUNServerAddress')
            stun_username = management_server.get('STUNUsername')
            stun_password = management_server.get(f'{VENDOR_PREFIX}STUNPassword')
            stun_max_keep_alive_period = management_server.get('STUNMaximumKeepAlivePeriod')
            stun_min_keep_alive_period = management_server.get('STUNMinimumKeepAlivePeriod')

            stun_setting_info = {
                'STUNEnable': stun_enable,
                'STUNServerPort': stun_server_port,
                'STUNServerAddress': stun_server_address,
                'STUNUsername': stun_username,
                'STUNPassword': stun_password,
                'STUNMaximumKeepAlivePeriod': stun_max_keep_alive_period,
                'STUNMinimumKeepAlivePeriod': stun_min_keep_alive_period,
            }

            return stun_setting_info
        except Exception as e:
            log.info(str(e))
            return 0

    def set_stun_setting(self, enable=1, server_port=3478, server_address='172.18.18.123', username='cpe',
                         password='cpe', maximum_keep_alive_period=300, minimum_keep_alive_period=30):
        """
        【功能描述】
        设置STUN服务器配置

        【入参】
        enable=1: 是否开启STUN服务
        server_port=3478: STUN服务器端口
        server_address='172.18.18.123': STUN服务器URL
        username='cpe': STUN用户名
        password='cpe': STUN密码
        maximum_keep_alive_period=300: 发送STUN绑定请求最长间隔时间（秒，-1表示无最长时间间隔要求）
        minimum_keep_alive_period=30: 发送STUN绑定请求最短间隔时间（秒 ）

        【返回值】
        ubus调用结果：成功
        0：失败

        【示例】
        Example:
        |  Some Keyword  |  enable=1  |  server_port=3478  |  server_address='172.18.18.123'  |  username='cpe'  |
                            password='cpe'  |  maximum_keep_alive_period=300  |  minimum_keep_alive_period=30  |

        【注意事项】
        - 参数必须符合格式，否则返回 False
        - 如果设备未启动，该关键字会失败
        """

        try:
            if (enable):
                EnableUbus = True
            else:
                EnableUbus = False

            set_params = {
                "path": "Device.ManagementServer.",
                "obj_path": {
                    "STUNEnable": EnableUbus,
                    "STUNServerPort": int(server_port),
                    "STUNServerAddress": server_address,
                    "STUNUsername": username,
                    f"{VENDOR_PREFIX}STUNPassword": password,
                    "STUNMaximumKeepAlivePeriod": int(maximum_keep_alive_period),
                    "STUNMinimumKeepAlivePeriod": int(minimum_keep_alive_period)
                },
                "optional": {"proto": "web"}
            }

            return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        except Exception as e:
            log.info(str(e))
            return 0

    def get_xmpp_setting_info(self):
        try:
            params = {
                "path": "Device.XMPP.Connection.1.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]['Connection'][0]
            management_server = data

            xmpp_enable = management_server.get('Enable')
            xmpp_dns_srv_port = management_server.get(f'{VENDOR_PREFIX}DnsSrvPort')
            xmpp_domain = management_server.get('Domain')
            xmpp_username = management_server.get('Username')
            xmpp_password = management_server.get(f'{VENDOR_PREFIX}Password')
            xmpp_resource = management_server.get('Resource')
            xmpp_server_connection_algorithm = management_server.get('ServerConnectAlgorithm')
            xmpp_use_tls = management_server.get('UseTLS')

            xmpp_setting_info = {
                'XMPPEnable': xmpp_enable,
                'XMPPDnsSrvPort': xmpp_dns_srv_port,
                'XMPPDomain': xmpp_domain,
                'XMPPUsername': xmpp_username,
                'XMPPPassword': xmpp_password,
                'XMPPResource': xmpp_resource,
                'XMPPServerConnectAlgorithm': xmpp_server_connection_algorithm,
                'XMPPUseTLS': xmpp_use_tls,
            }

            return xmpp_setting_info
        except Exception as e:
            log.info(str(e))
            return 0

    def set_xmpp_setting(self, enable=1, dns_srv_port=5222, server_address='172.18.18.123', username='cpe',
                         password='cpe', resource='cpe', server_conn_algorithm='DNS-SRV', use_tls=1):
        """
        【功能描述】
        设置XMPP服务器配置

        【入参】
        enable=1: 是否开启XMPP服务
        dns_srv_port=5222: XMPP服务器端口
        server_address='172.18.18.123': XMPP服务器URL（允许空字符串）
        username='cpe': XMPP用户名（允许空字符串）
        password='cpe': XMPP密码（允许空字符串）
        resource='cpe': XMPP资源
        server_conn_algorithm='DNS-SRV': XMPP算法
        use_tls=1: 是否开启TLS校验

        【返回值】
        ubus调用结果：成功
        0：失败

        【示例】
        Example:
        |  Some Keyword  |  enable=1  |  dns_srv_port=5222  |  server_address='172.18.18.123'  |  username='cpe'  |
                            password='cpe'  |  resource='cpe'  |  server_conn_algorithm='DNS-SRV'  |  use_tls=1  |

        【注意事项】
        - 参数必须符合格式，否则返回 False
        - 如果设备未启动，该关键字会失败
        """
        try:
            if (enable):
                enable_ubus = True
            else:
                enable_ubus = False

            if (use_tls):
                use_tls_ubus = True
            else:
                use_tls_ubus = False

            set_params = {
                "path": "Device.XMPP.Connection.1.",
                "obj_path": {
                    "Enable": enable_ubus,
                    f"{VENDOR_PREFIX}DnsSrvPort": int(dns_srv_port),
                    "Domain": server_address,
                    "Username": username,
                    f"{VENDOR_PREFIX}Password": password,
                    "Resource": resource,
                    "ServerConnectAlgorithm": server_conn_algorithm,
                    "UseTLS": use_tls_ubus
                },
                "optional": {"proto": "web"}
            }

            return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        except Exception as e:
            log.info(str(e))
            return 0

    def debug_test(self):
        try:
            ret = self.ubus.Ubus_Login(self.username, self.password)
            if ret != ERR_SUCCESS:
                print("ubus 登录失败")
                return None
            print("ubus 登录成功")

            # result = self.set_stun_setting(1, 3478, '172.18.18.123', 'cpe', 'cpe', 300, 30)
            # result = self.set_stun_setting(0, 1111, '172.18.18.111', '111', '111', 111, 60)
            # print(result)

            # result = self.set_xmpp_setting(1, 5222, '172.18.18.123', 'cpe', 'cpe', 'cpe', 'DNS-SRV', 1)
            # result = self.set_xmpp_setting(0, 5333, '172.18.18.111', '111', '111', '111', 'DNS-SRV', 0)
            # print(result)

            # local_cert_path = "cwmp.crt"
            # remote_cert_path = "/etc/xmppc/ca-certificates.pem"
            # device_url = "http://192.168.29.1/cgi-bin/cgi-upload"
            # result = self.upload_file_to_device(device_url, local_cert_path, remote_cert_path)
            # print(result)

            # result = self.get_stun_setting_info()
            # result = json.dumps(result, indent=4, ensure_ascii=False)
            # print(result)

            result = self.get_xmpp_setting_info()
            # result = json.dumps(result, indent=4, ensure_ascii=False)
            print(result)

            ret = self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed: ", str(e))


if __name__ == '__main__':
    Cwmp = StunXmppManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    Cwmp.debug_test()

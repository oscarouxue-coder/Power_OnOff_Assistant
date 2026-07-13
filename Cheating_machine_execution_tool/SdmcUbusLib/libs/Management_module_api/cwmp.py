import os
import json
import time

from SdmcLog import log
from SdmcCode import ERR_SUCCESS
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class CwmpManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        # 映射结果状态
        self.result_mapping = {
            "0_uploading": ("processing", "上传中"),
            "1_icwmpd_not_running": ("error", "进程未运行"),
            "2_empty_acs_url": ("error", "ACS URL为空"),
            "3_tr069_wan_error": ("error", "WAN连接异常"),
            "4_curl_connect_acs_fail": ("error", "连接ACS失败"),
            "5_authentication_fail": ("error", "认证失败"),
            "9_unknow_fail": ("error", "未知错误"),
            "10_success": ("success", "成功")
        }


    def get_tr069_setting_info(self):
        """
        【功能描述】
        获取TR069参数并返回结果

        【入参】


        【返回值】
        tr069_setting_info : {'PeriodicInformEnable':true,'inform_interval'=86400,....}

        【示例】
        Example:

        """
        try:
            params = {
                "path": "Device.ManagementServer.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]
            management_server = data.get('ManagementServer', {})

            period_inform_enable = management_server.get('PeriodicInformEnable')
            inform_interval = management_server.get('PeriodicInformInterval')
            certifi_enable = management_server.get(f'{VENDOR_PREFIX}CertificateEnable')
            acs_url = management_server.get('URL')
            acs_account = management_server.get('Username')
            acs_password = management_server.get('Password')
            connection_request_enable = management_server.get('HTTPConnectionRequestEnable')
            user_name = management_server.get('ConnectionRequestUsername')
            password = management_server.get('ConnectionRequestPassword')
            ConnectionRequestURL = management_server.get('ConnectionRequestURL')
            acs_regist_status = management_server.get(f'{VENDOR_PREFIX}InformResult')

            tr069_setting_info = {
                'PeriodicInformEnable': period_inform_enable,
                'PeriodicInformInterval': inform_interval,
                'CertificateEnable': certifi_enable,
                'URL': acs_url,
                'ACS Account': acs_account,
                'ACS Password': acs_password,
                'Connection Requeset': connection_request_enable,
                'ConnectionRequestUsername': user_name,
                'ConnectionRequestPassword': password,
                'ConnectionRequestURL': ConnectionRequestURL,
                'InformResult': acs_regist_status
            }

            return tr069_setting_info
        except Exception as e:
            log.info(str(e))
            return 0

    def set_tr069_setting(self, Url='http://172.18.18.101:7547/ACS-server/ACS', Username='hgw',
                                  Password='hgw', Period_Inform_Enable=1, Periodic_Inform_Interval=86400,
                                  HTTP_Connection_Request_Enable=1, Connection_Request_Username='itms',
                                  Connection_Request_Password='itms', Certificate_Enable=0):
        """
        【功能描述】
        设置TR069管理服务器配置

        【入参】
        Period_Inform_Enable=1 : 是否启用周期上报
        Periodic_Inform_Interval=86400 : 上报间隔(秒)
        URL='http://172.18.18.101:7547/ACS-server/ACS' : ACS服务器URL（允许空字符串）
        Username='hgw' : ACS用户名（允许空字符串）
        Password='hgw' : ACS密码（允许空字符串）
        HTTP_Connection_Request_Enable=1 : 是否启用HTTP连接请求
        Connection_Request_Username='itms' : 连接请求用户名（允许空字符串）
        Connection_Request_Password='itms' : 连接请求密码（允许空字符串）
        Certificate_Enable=0 : 是否启用证书

        【返回值】
        ubus调用结果：成功
        0：失败

        【示例】
        Example:
        |  Some Keyword  |  Url='http://172.18.18.101:7547/ACS-server/ACS'  |  Username='hgw'  |
                            Password='hgw'  |  Period_Inform_Enable=1  |  Periodic_Inform_Interval=86400  |
                            HTTP_Connection_Request_Enable=1  |  Connection_Request_Username='itms'  |
                            Connection_Request_Password='itms'  |  Certificate_Enable=0  |

        【注意事项】
        - 如果设备未启动，该关键字会失败
        """

        try:
            if (Period_Inform_Enable):
                PeriodInformEnableUbus = True
            else:
                PeriodInformEnableUbus = False

            if (HTTP_Connection_Request_Enable):
                HTTPConnectionRequestEnableUbus = True
            else:
                HTTPConnectionRequestEnableUbus = False

            if (Certificate_Enable):
                CertificateEnableUbus = True
            else:
                CertificateEnableUbus = False

            set_params = {
                "path": "Device.ManagementServer.",
                "obj_path": {
                        "PeriodicInformEnable": PeriodInformEnableUbus,
                        "PeriodicInformInterval": int(Periodic_Inform_Interval),
                        "URL": Url,
                        "Username": Username,
                        "Password": Password,
                        "HTTPConnectionRequestEnable": HTTPConnectionRequestEnableUbus,
                        "ConnectionRequestUsername": Connection_Request_Username,
                        "ConnectionRequestPassword": Connection_Request_Password,
                        f"{VENDOR_PREFIX}CertificateEnable": CertificateEnableUbus
                    },
                "optional": {"proto": "web"}
            }

            log.info(set_params)
            return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        except Exception as e:
            log.info(str(e))
            return 0

    def inform_tr069(self, timeout=60, interval=1):
        """
        【功能描述】
        触发TR069 Inform并轮询结果状态

        【入参】
        timeout=60: 超时时间(秒)，默认60秒
        interval=1: 轮询间隔(秒)，默认1秒

        【返回值】
        tuple: (最终状态, 结果代码)
        状态值: "success"、"timeout"、"error"
        结果代码: 对应各种错误码或成功码(10_success)

        【示例】
        Example:
        |  Some Keyword  |  timeout=60  |  interval=1  |

        """
        try:
            # 1. 触发Inform
            inform_params = {
                "path": f"Device.ManagementServer.{VENDOR_PREFIX}ManualInformStage",
                "value": "1_wait_inform",
                "optional": {"proto": "web"}
            }
            trigger_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", inform_params)
            if not trigger_result or trigger_result[0] != 0:
                return "error", "trigger_failed"

            # 2. 状态轮询
            start_time = time.time()
            get_params = {
                "path": f"Device.ManagementServer.{VENDOR_PREFIX}ManualInformStage",
                "optional": {"proto": "web"}
            }

            while time.time() - start_time < timeout:
                # 获取当前状态
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", get_params)
                if not result or len(result) < 2:
                    time.sleep(interval)
                    continue

                data = result[1]
                current_status = data.get(f'{VENDOR_PREFIX}ManualInformStage')

                # 3. 检查完成状态
                if current_status == "3_finish_inform":
                    # 获取最终结果
                    result_params = {
                        "path": f"Device.ManagementServer.{VENDOR_PREFIX}InformResult",
                        "optional": {"proto": "web"}
                    }
                    result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", result_params)
                    if result and len(result) > 1:
                        result_data = result[1]
                        inform_result = result_data.get(f'{VENDOR_PREFIX}InformResult', '0_uploading')

                        return self.result_mapping.get(inform_result, ("error", "unknown_status"))

                time.sleep(interval)

            return "error", "operation_timeout"
        except Exception as e:
            log.info(str(e))
            return "error", str(e)

    def get_tr069_inform_status(self, timeout=60):
        """
        【功能描述】
        查询TR069 inform状态，并返回查询结果

        【入参】
        timeout=60 : 等待 finish_inform 时间

        【返回值】
        inform_status(元组) : inform 成功返回 ("success", "成功")/inform 失败返回 ('error', '失败类型')

        【示例】
        Example:
        |  Some Keyword  |  timeout=60  |

        """
        try:
            interval = 1
            # 1. 状态轮询
            start_time = time.time()
            get_params = {
                "path": f"Device.ManagementServer.{VENDOR_PREFIX}ManualInformStage",
                "optional": {"proto": "web"}
            }

            while time.time() - start_time < timeout:
                # ２、获取当前状态
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", get_params)
                if not result or len(result) < 2:
                    time.sleep(interval)
                    continue

                data = result[1]
                current_status = data.get(f'{VENDOR_PREFIX}ManualInformStage')

                # ３. 检查完成状态
                if current_status == "3_finish_inform":
                    # 获取最终结果
                    result_params = {
                        "path": f"Device.ManagementServer.{VENDOR_PREFIX}InformResult",
                        "optional": {"proto": "web"}
                    }
                    result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", result_params)
                    if result and len(result) > 1:
                        result_data = result[1]
                        inform_result = result_data.get(f'{VENDOR_PREFIX}InformResult', '0_uploading')

                        log.info(f'inform_result:{self.result_mapping.get(inform_result, ("error", "unknown_status"))}')
                        inform_status = self.result_mapping.get(inform_result, ("error", "unknown_status"))
                        return inform_status

        except Exception as e:
            log.info(str(e))
            return "error", str(e)

    def debug_test(self):
        try:
            ret = self.ubus.Ubus_Login(self.username, self.password)
            if ret != ERR_SUCCESS:
                print("ubus 登录失败")
                return None
            print("ubus 登录成功")

            # result = self.set_tr069_setting('http://172.18.18.101:7547/ACS-server/ACS', 'hgw', 'hgw', 1, 300, 1, 'itms', 'itms', 0)
            # result = self.set_tr069_setting('http://172.18.18.101:7547', '111', '111', 0, 86400, 0, '111', '111', 1)
            # print(result)

            # local_cert_path = "cwmp.crt"
            # remote_cert_path = "/etc/icwmpd/ca-certificates.crt"
            # device_url = "http://192.168.29.1/cgi-bin/cgi-upload"
            # result = self.upload_file_to_device(device_url, local_cert_path, remote_cert_path)
            # print(result)

            # result = self.get_tr069_inform_status()
            # print(result)

            # result = self.inform_tr069()

            result = self.get_tr069_setting_info()
            result = json.dumps(result, indent=4, ensure_ascii=False)
            print(result)

            ret = self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed: ", str(e))


if __name__ == '__main__':
    Cwmp = CwmpManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    Cwmp.debug_test()

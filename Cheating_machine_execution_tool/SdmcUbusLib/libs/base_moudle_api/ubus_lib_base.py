"""
测试库 ubus for OpenWRT

20241202   v1.0
1 新建 基础 接口 API




"""

import os
import sys
import datetime
import traceback
from datetime import datetime
import time
from time import sleep
import string
import ipaddress
import telnetlib

import logging
from SdmcLog import log
from SdmcCode import *

import pycurl
from multiprocessing import Process
import subprocess
import concurrent.futures
from functools import partial

import yaml
import requests
import json
import urllib3

from sdmcstart import PROJECT_HOME

VENDOR_PREFIX = "X_SDMC_"
UBUS_SERVICE_BBFDM = "bbf.shell"

def switch_ubus_service(new_service: str):
    """
    【功能描述】
        切换调用ubus_call使用的方法

    【入参】
        new_service: 切换的方法

    【返回值】
        执行成功无返回值，执行失败会报异常

    【示例】
        Example:
        |  Ubus_Switch_ubus_service |  new_service=bbfdm  |

    """

    try:
        global UBUS_SERVICE_BBFDM
        UBUS_SERVICE_BBFDM = str(new_service)
    except Exception as e:
        raise ValueError(e)

class SdmcUbusLibBase(object):
    """
    测试库 demo for class
    """
    Url = "http://192.168.29.1/ubus/"
    ubus_rpc_session = None
    Username = "root"
    Password = "password"

    ubus_call_fault_flag = 0  # 使用Ubus接口验证参数错误的场景使用，默认0：正常场景，1：错误场景

    def __init__(self):
        """
        """
        pass

    def Ubus_Switch(self, url):
        """
        功能描述：切换一些配置

        参数：
        url:

        Example:
        | Ubus_Switch| http://192.168.29.1/ubus/ |

        """
        SdmcUbusLibBase.Url = url
        log.info(f"切换url:{url}")

    def Ubus_call_fault_switch(self, ubus_call_fault_flag):
        """
        功能描述： 使用Ubus接口验证参数错误的场景使用，默认0：正常场景，1：错误场景

        参数：
        ubus_call_fault_flag：0/1

        Example:
            | Ubus_call_fault_switch| 1 |
        """
        SdmcUbusLibBase.ubus_call_fault_flag = int(ubus_call_fault_flag)


    def Ubus_Login(self, username="root", password="password"):
        """
        功能描述：登录 OpenWRT 页面

        参数：
        username:   用户名
        password:   密码

        Example:
        | Ubus_Login| root  | admin123  |

        """

        try:

            SdmcUbusLibBase.Username = username
            SdmcUbusLibBase.Password = password

            url = SdmcUbusLibBase.Url

            desc = f'登录 OpenWRT 页面 (username={username} {url})'
            log.info(desc)

            payload = {"jsonrpc": "2.0",
                       "id": 1,
                       "method": "call",
                       "params": ["00000000000000000000000000000000",
                                  "session",
                                  "login", {"username": str(username),
                                            "password": str(password)}
                                  ]
                       }

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.post(url, json=payload, verify=False)

            response_data = response.json()

            result = response_data.get("result")
            result_ret = result[0]
            if (result_ret != 0):
                desc = f"result={result_ret} !=0, 登录OpenWRT页面失败"
                log.info(desc)
                raise AssertionError(f"登录失败: result={result_ret}")

            ubus_rpc_session = result[1].get("ubus_rpc_session")
            SdmcUbusLibBase.ubus_rpc_session = ubus_rpc_session

            return ERR_SUCCESS


        except Exception as e:
            log.exception(str(e))
            raise

    def Ubus_get_menu(self,primary_menu):
        """
        功能描述：获取设备功能菜单列表

        入参：status/network/security/application/management

        返回值：返回对应一级菜单下的二级菜单列表
        ['internet', 'device', 'clients']/
       ['wan', 'lan', 'lanPort', 'wlan', 'wlanAdvanced', 'guest', 'wlanScan', 'wlanTimeOff', 'route', 'vpn']/
        ['mac', 'ip', 'accessControl', 'url', 'parental', 'dos', 'firewall']/
        ['easyMesh', 'dmz', 'portForward', 'portTrigger', 'ddns', 'alg', 'upnp', 'voip', 'voipApplication', 'voipHistory', 'cwmp', 'usp', 'stunXmpp', 'qos', 'igmpMld', 'vlanBinding', 'broadbandAuthentication']/
         ['restoreBackup', 'upgrade', 'maintenance', 'log', 'time', 'password', 'speed', 'portMirror', 'tcpdumpTest']}

        Example:
        | ubus_get_menu | status
        """

        try:
            # 1. 获取 Session ID
            url = SdmcUbusLibBase.Url

            desc = f'调用 {UBUS_SERVICE_BBFDM} unauthenticated_operate (user={SdmcUbusLibBase.Username}, url={url})'
            log.info(desc)

            # 2. 构造 Payload
            # 根据指令: ubus call bbf.shell unauthenticated_operate '{"command": "...", "command_key": "...", "input": {...}}'
            payload = {
                "jsonrpc": "2.0",
                "id": 2,  # 建议 ID 与登录接口区分开，或者动态生成
                "method": "call",
                "params": [
                    SdmcUbusLibBase.ubus_rpc_session,
                    UBUS_SERVICE_BBFDM,
                    "unauthenticated_operate",
                    {
                        "command": "Device.X_SDMC_Login.Login()",
                        "command_key": "Login",
                        "input": {
                            "Username": str(SdmcUbusLibBase.Username),
                            "Password": str(SdmcUbusLibBase.Password)
                        },
                        "optional": {
                            "proto": "web"
                        }
                    }
                ]
            }

            # 3. 发送请求
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.post(url, json=payload, verify=False)

            log.info(f"unauthenticated_operate_response: {response.text}")

            # 4. 处理响应
            response_data = response.json()
            result = response_data.get("result")

            if not result:
                raise AssertionError(f"调用失败: 响应中无 result 字段, response={response_data}")

            result_code = result[0]

            # 检查 ubus 状态码，0 通常代表 UBUS_STATUS_OK
            if result_code != 0:
                desc = f"result_code={result_code} != 0, 执行 unauthenticated_operate 失败"
                log.error(desc)
                raise AssertionError(f"执行失败: result_code={result_code}, detail={result}")

            menu = result[1]['results'][0]['output'][0]["menu"]
            data = json.loads(menu)

            # 核心逻辑：遍历 menu 列表，构建字典
            # 键是父菜单的 keyMenu，值是子菜单 keyMenu 组成的列表
            result = {}
            for item in data['menu']:
                parent_name = item['keyMenu']
                # 提取 children 中的 keyMenu 字段，生成列表
                children_list = [child['keyMenu'] for child in item['children']]
                result[parent_name] = children_list

            secondary_menu=result.get(primary_menu, "None")
            if secondary_menu!= "None":
                log.info(f"获取一级菜单：{primary_menu} 的二级菜单成功：{secondary_menu}")
                return secondary_menu
            else:
                desc=f"获取一级菜单：{primary_menu} 的二级菜单失败：{result}"
                raise ValueError()

        except Exception as e:
            desc=f"获取功能菜单失败：{str(e)}"
            log.exception(desc)
            raise ValueError(desc)

    def _Ubus_check_error(self, echo):
        """
        功能描述：

        参数：
        echo:   ubus post 返回值, dict 对象
        eg   {'id': 1, 'jsonrpc': '2.0', 'result': [0]}

        Example:
        |  _Ubus_check_error | {"jsonrpc": "2.0","id": 9,"error": {"code": -32002, "message": "Access denied"} }  |
        """
        if "error" in echo:
            log.error(str(echo))
            desc = f"ubus post返回错误:{str(echo)}"
            raise Exception(desc)

    def _Ubus_check_fault(self, results):
        """
        功能描述：

        参数：
        results:   ubus post 返回值, dict 对象

        Example:
        |  _Ubus_check_fault |  {"path": "Device.ManagementServer.PeriodicInformInterval", "fault": 9007, "fault_msg": "The requested value is outside the allowed range" } |
        """
        results_value = results.get("results")

        if (results_value):
            for result in results_value:
                if SdmcUbusLibBase.ubus_call_fault_flag:
                    if "fault" in result:
                        # log.error(str(results_value[0]))
                        desc = f"ubus post返回错误:{result}"
                        log.warning(desc)
                        # raise Exception(desc)
                else:
                    if "fault" in result:
                        # log.error(str(results_value[0]))
                        desc = f"ubus post返回错误:{result}"
                        log.warning(desc)
                        raise Exception(desc)

    def Ubus_Call(self, ubus_object, ubus_func, params):
        """
        功能描述：

        参数：
        ubus_object:   bbfdm
        ubus_func:     get / set /add
        params:     dict 参数

        Example:
        |  ${result}  | Ubus_Call | bbfdm  |  get |  {"path":"Device.ManagementServer.PeriodicInformInterval"}  |
        |  ${result}  | Ubus_Call | bbfdm  |  set |  {"path":"Device.ManagementServer.PeriodicInformInterval" ,"value":"1808" }   |
        |  ${result}  | Ubus_Call | bbfdm  |  add |  {"optional": {"proto": "web"},  "paths":[ {"addr":"Device.Ethernet.Link."  }, {"addr":"Device.Ethernet.VLANTermination." }, {"addr":"Device.IP.Interface." } ]  }  |
        """
        ret = ERR_FAIL
        result = None
        response_data = {"error": "error"}

        for nwf in [1]:

            url = SdmcUbusLibBase.Url

            if (isinstance(params, str)):
                params = json.loads(params)

            payload = {"jsonrpc": "2.0",
                       "id": 1,
                       "method": "call",
                       "params": [SdmcUbusLibBase.ubus_rpc_session,
                                  ubus_object,
                                  ubus_func,
                                  params
                                  ]
                       }

            print("payload is", payload)

            response = requests.post(url, json=payload, verify=False)
            # print(params)

            try:
                # get {'id': 1, 'jsonrpc': '2.0', 'result': [0, {'results': [{'data': '1', 'path': 'Device.DHCPv4.Relay.Enable'}]}]}
                # set {'id': 1, 'jsonrpc': '2.0', 'result': [0]}
                response_data = response.json()
                print(response_data)
            except Exception as e:
                desc = f"ubus 返回=({response.text}) 解析 json 出错"
                log.error(desc)

                log.exception(str(e))

                raise Exception(desc)

                # get [0, {'results': [{'data': '1', 'path': 'Device.DHCPv4.Relay.Enable'}]}]
            # set [0]
            result = response_data.get("result")
            print(result)

            if (len(result) > 1):
                check_fault = self._Ubus_check_fault(result[1])

            self._Ubus_check_error(response_data)

            return result

    def Ubus_Logout(self):
        """
            功能描述：登出当前用户会话，释放 ubus session。

            参数：
            无

            Example:
            | Ubus_Logout |
        """
        try:
            session_id = SdmcUbusLibBase.ubus_rpc_session
            if not session_id:
                print("无有效 session，跳过登出")
                return

            payload = {
                "command": "Device.X_SDMC_Login.logout()",
                "input": {
                    "SessionId": session_id
                }
            }

            result = self.Ubus_Call(UBUS_SERVICE_BBFDM, "unauthenticated_operate", payload)
            print("登出成功")
            SdmcUbusLibBase.ubus_rpc_session = ""  # 清除本地会话
        except Exception as e:
            print(f"登出失败: {e}")


    def unit_test(self):
        """单元测试入口"""
        try:
            print("\n=== 开始单元测试 ===")
            switch_ubus_service("bbfdm")
            self.Ubus_Switch(f"https://{'192.168.1.1'}/ubus/")

            # 测试用例1：基础登录
            print("测试登录...")
            ret = self.Ubus_Login("sdmc", "1234")
            assert ret == ERR_SUCCESS, "登录失败"
            print(f"当前会话: {self.ubus_rpc_session}")
            self.Ubus_get_menu('status')
            # # 测试用例2：获取配置
            # print("\n测试获取配置...")
            # result = self.Ubus_Call(UBUS_SERVICE_BBFDM, "get",
            #                         {"path": "Device.ManagementServer.PeriodicInformInterval"})
            # print("获取结果:", json.dumps(result, indent=2))
            # # 测试用例3：错误路径测试
            # print("\n测试错误路径...")
            # try:
            #     self.Ubus_Call(UBUS_SERVICE_BBFDM, "get",
            #                    {"path": "Invalid.Path"})
            # except Exception as e:
            #     # print("预期中的错误:", str(e))
            #     # # 测试用例4：登出
            #     # print("\n测试登出...")
            #     # self.Ubus_Logout()
            #     # print("当前会话:", self.ubus_rpc_session)
            #     # print("\n=== 所有测试通过 ===")
            #     return ERR_SUCCESS

        except Exception as e:
            print("\n!!! 测试失败 !!!")
            traceback.print_exc()
            return ERR_FAIL

        
    def validate_password(self, password):

        if len(password) < 8 or len(password) > 32:
            log.info("密码长度应在8到32个字符之间")
            raise

        if not any(c.islower() for c in password):
            log.info("密码必须包含小写字母")
            raise

        if not any(c.isupper() for c in password):
            log.info("密码必须包含大写字母")
            raise

        if not any(c.isdigit() for c in password):
            log.info("密码必须包含数字")
            raise

        if not any(c in "!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~" for c in password):
            log.info("密码必须包含特殊字符")
            raise


if __name__ == '__main__':
    """
    主程序入口，只进行登录
    """
    n_ret = 0

    print("start ---------------------------\n")

    # 只调用登录函数
    c1 = SdmcUbusLibBase()
    c1.unit_test()

    print("\nfinish ------------------")

import json

from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class LogManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_log_ubus(self):
        """
        【功能描述】
        获取 log 相关参数信息

        【入参】
        无

        【返回值】
        {'X_SDMC_Enable': True, 'X_SDMC_LogRecordLevel': 'info', 'X_SDMC_LogRecordModule': 'ALL', 'X_SDMC_LogDisplayLevel': 'info', 'X_SDMC_LogDisplayModule': 'ALL', 'X_SDMC_LogLevelList': 'emerg,alert,crit,err,warning,notice,info,debug', 'X_SDMC_LogModuleList': 'ALL,Kernel,TR-069,WAN-DHCP,HTTP,DHCP-Server,Wireless,Mesh,Voice,OMCI'}


        【示例】
        Example:
        |  Get IGMP Snooping  |

        """
        params = {
            "path": "Device.DeviceInfo.VendorLogFile.1.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get('VendorLogFile')[0]

        return data

    def get_log_info(self):
        """
        【功能描述】
        获取设备的日志配置信息，包括日志功能是否启用、日志记录等级以及日志记录模块。

        【入参】
        无

        【返回值】
        {'Enable': True, 'Log Level': 'info', 'Log Mode': 'ALL'}

        【示例】
        Example:
        |  get_log_info  |

        """
        ubus_data = self.get_log_ubus()
        info = {
            "Enable": ubus_data.get(f'{VENDOR_PREFIX}Enable'),
            "Log Level": ubus_data.get(f'{VENDOR_PREFIX}LogRecordLevel'),
            "Log Mode": ubus_data.get(f'{VENDOR_PREFIX}LogRecordModule')
        }
        return info

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            data = self.get_log_ubus()
            self.get_log_info()
            info = json.dumps(data, indent=4, ensure_ascii=False)
            print(info)
            # print("json is " + str(data))
        except Exception as e:
            print("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))


if __name__ == '__main__':
    log = LogManager(ip="192.168.29.1", username="sdmc", password="1234")
    log.debug_test()

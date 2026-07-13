from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class IptvManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_igmp_snooping(self):
        """
        【功能描述】
        获取 IGMP Snooping（组播侦听）功能启用状态。

        【入参】
        无

        【返回值】
        {'Enable': True}

        【示例】
        Example:
        |  Get IGMP Snooping  |

        """
        params = {
            "path": f"Device.{VENDOR_PREFIX}Multicast.Snooping.Enable",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        return data

    def get_igmp_proxy(self):
        """
        【功能描述】
        获取 IGMP Proxy（组播代理）相关配置信息，包括启用状态、上行接口、健壮性参数及各类查询间隔时间。

        【入参】
        无

        【返回值】
        {'Enable': False, 'Uplink': '', 'Robustness': 2, 'QueryInterval': 30, 'QueryResponseInterval': 25, 'LastMemberQueryInterval': 3, 'UnsolicitedReportInterval': 1, 'MinRobustness': 1, 'MaxRobustness': 7, 'MinQueryInterval': 30, 'MaxQueryInterval': 300, 'MinQueryResponseInterval': 1, 'MaxQueryResponseInterval': 25, 'MinLastListenerQueryInterval': 1, 'MaxLastListenerQueryInterval': 7, 'MinUnsolicitedReportInterval': 1, 'MaxUnsolicitedReportInterval': 60}


        【示例】
        Example:
        |  Get IGMP Proxy  |

        """
        params = {
            "path": f"Device.{VENDOR_PREFIX}Multicast.Proxy.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get('Proxy')

        return data

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            print("Debug test completed successfully")
        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            print("Unit test completed successfully")
        except Exception as e:
            print("uint test failed: ", str(e))

if __name__ == '__main__':
    iptv = IptvManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    iptv.debug_test()
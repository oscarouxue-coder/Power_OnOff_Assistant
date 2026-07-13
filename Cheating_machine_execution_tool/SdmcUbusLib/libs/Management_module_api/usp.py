from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class UspManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_ups_ubus(self):
        """
        【功能描述】
        获取 USP 相关参数信息

        【入参】
        无

        【返回值】
        {'Enable': False, 'BrokerAddress': '172.18.18.xxx', 'BrokerPort': 1883, 'MQTT_Username': 'usp', 'MQTT_Password': 'usp', 'Agent_EndpointID': 'proto::agent-1', 'Agent_ResponseTopicConfigured': '/usp/agent/1', 'Controller_EndpointID': 'proto::controller-1', 'Controller_Topic': '/usp/controller/1', 'Controller_PeriodicNotifInterval': 86400}


        【示例】
        Example:
        |  Get IGMP Snooping  |

        """
        params = {
            "path": f"Device.{VENDOR_PREFIX}USP.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get(f'{VENDOR_PREFIX}USP')

        return data


    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            data = self.get_ups_ubus()
            # info = json.dumps(data, indent=4, ensure_ascii=False)
            print("json is " + str(data))
            # print(info)
        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))

if __name__ == '__main__':
    usp = UspManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    usp.debug_test()
import json
from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class QosManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_qos_json(self):
        """
        【功能描述】
        获取设备的 QoS（Quality of Service，服务质量）相关配置信息。
        该节点包含带宽管理、优先级规则、队列控制等网络性能调度参数。


        【返回值】
        | 返回值类型 | 说明                                 |
        | ---------- | ------------------------------------ |
        | dict       | 返回包含 QoS 配置信息的字典结构。   |

        【异常】
        Exception : 当调用 ubus 接口失败或返回结果结构异常时抛出。

        【示例】
        Example (Robot Framework):
        |  Get Qos Json  |
        |  ${qos_info}=  |  Get Qos Json  |

        """
        params = {
            "path": "Device.QoS.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        return data

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            data = self.get_qos_json()
            # info = json.dumps(data, indent=4, ensure_ascii=False)
            print("json is "+ str(data))
            # print(info)
        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))


if __name__ == '__main__':
    qos = QosManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    qos.debug_test()
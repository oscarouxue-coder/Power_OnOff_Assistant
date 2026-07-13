import json

from SdmcLog import log

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class MirrorManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_port_mirror_status(self):
        """
        【功能描述】
            获取镜像开启状态
        【入参】
            无
        【返回值】

        【示例】
        Example:

        """
        info = {}
        params = {
            "path": f"Device.DeviceInfo.{VENDOR_PREFIX}PortMirroring",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        status = result[1].get(f"{VENDOR_PREFIX}PortMirroring", "false")
        info["PortMirror"] = status
        return info

    def set_port_mirror_status(self, status="0"):
        """
        【功能描述】
            设置镜像开启关闭状态
        【入参】
            param status: str - 状态0表示关闭，1表示开启（默认值="0"）
        【返回值】

        【示例】
        Example:

        """
        info = {}

        params = {
            "path": f"Device.DeviceInfo.{VENDOR_PREFIX}PortMirroring",
            "value": status
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

        return result

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            result = self.set_port_mirror_status("0")
            result = json.dumps(result, indent=4, ensure_ascii=False)
            print(result)

        except Exception as e:
            print("debug test failed: ", str(e))

if __name__ == '__main__':
    Mirror = MirrorManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    Mirror.debug_test()
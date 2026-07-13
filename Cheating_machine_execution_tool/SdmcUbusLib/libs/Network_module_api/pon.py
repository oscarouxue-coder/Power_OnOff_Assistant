from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcUbusLib.libs.base_moudle_api.status import StatusManager

class PonManager:
    def __init__(self, ip, username, password):
        """

        """
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_broadband_authentication_ubus(self):
        """
        【功能描述】
        通过 UBUS 获取宽带认证信息，主要用于获取 XPON ONU 的认证相关参数。

        【入参】
        无

        【返回值】
        dict : 返回一个字典，包含宽带认证信息，例如：
            {
                "Authentication": {
                    "Username": "xxxx",
                    "Password": "xxxx",
                    "SerialNumber": "XXXXXX",
                    ...
                },
                ...
            }
            获取失败时返回 None 或空字典。

        【示例】
        Example:
        |  get_broadband_authentication_ubus  |
        返回示例:
        {
            "Authentication": {
                "Username": "user123",
                "Password": "pass123",
                "SerialNumber": "XPON12345678"
            }
        }
        """
        params = {
            "path": "Device.XPON.ONU.1.ANI.1.TC.Authentication.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        return data

    def debug_test(self):
        """
        功能描述：调试测试接口
        """
        self.ubus.Ubus_Login("root", "t*hEQ#BHu7z%3n")
        ret = self.get_broadband_authentication_ubus()
        print(f"{ret}")

if __name__ == '__main__':
    pon = PonManager(ip="192.168.29.1", username="sdmc", password="1234")
    pon.debug_test()

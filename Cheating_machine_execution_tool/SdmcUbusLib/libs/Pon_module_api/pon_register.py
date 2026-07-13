import json

from SdmcLog import log

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class PonRegisterManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_auth_type(self):
        """
        【功能描述】
            获取当前认证方式
        【入参】
            无
        【返回值】
            返回当前认证方式
        【示例】
        Example:
            [0, {'X_SDMC_AuthType': 'Password'}]
        """
        info = {}
        params = {
            "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}AuthType",
            "optional": {"proto": "web"}
        }
        info = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        return info

    def set_auth_type(self, auth_type="Password"):
        """
        【功能描述】
            设置当前认证方式
        【入参】
            auth_type:str 认证方式 Password LOID 默认Password
        【返回值】

        【示例】
        Example:
        """
        info = {}

        params = {
            "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}AuthType",
            "value": auth_type
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

        return result

    def get_sn_info(self):
        """
        【功能描述】
            获取当前sn,密码模式 ascii或者hex,密码
        【入参】
            无
        【返回值】
            返回当前密码模式和密码
        【示例】
        Example:
            {'password_mode': 'hex', 'password': '31323334', 'sn': 'SSSS78541254'}
        """
        info = {}
        params = {
            "path": "Device.XPON.ONU.1.ANI.1.TC.Authentication.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("Authentication", []).get("HexadecimalPassword")
        password = result[1].get("Authentication", []).get("Password")
        sn = result[1].get("Authentication", []).get(f"{VENDOR_PREFIX}SerialNumber")
        if data is True:
            info["password_mode"] = "hex"
        else:
            info["password_mode"] = "ascii"
        info["password"] = password
        info["sn"] = sn

        return info

    def set_sn_info(self, password_mode="ascii", password="1234", sn="ZTEG10125280"):
        """
                【功能描述】
                    设置当前密码模式和密码
                【入参】
                    password_mode:str 密码模式 hex ascii 默认ascii
                    password:str 密码 默认1234 ，hex 20位，ascii 10位
                    sn:str sn 12位 默认ZTEG10125280
                【返回值】

                【示例】
                Example:
                """
        try:
            lenth = len(password)
            if password_mode == "hex":
                hex_mode="True"
                if lenth > 20:
                    raise
            else:
                hex_mode="False"
                if lenth > 10:
                    raise

            sn_lenth = len(sn)
            if sn_lenth != 12:
                raise
            hex_mode_params = {
                "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.HexadecimalPassword",
                "value": hex_mode
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", hex_mode_params)

            password_params = {
                "path": "Device.XPON.ONU.1.ANI.1.TC.Authentication.Password",
                "value": password
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", password_params)

            sn_params = {
                "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}SerialNumber",
                "value": sn
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", sn_params)

            return result
        except Exception as e:
            return False
            raise

    def get_loid_info(self):
        """
        【功能描述】
            获取当前loid 信息
        【入参】
            无
        【返回值】
            返回前loid 信息
        【示例】
        Example:
           {'loid': 'mtk1234', 'loid_password': '1234'}
        """
        info = {}
        params = {
            "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        loid = result[1].get("Authentication", []).get(f"{VENDOR_PREFIX}LOID")
        loid_password = result[1].get("Authentication", []).get(f"{VENDOR_PREFIX}LOIDPassword")
        info["loid"] = loid
        info["loid_password"] = loid_password
        print(info)
        return info

    def set_loid_info(self, loid="mtk1234", loid_password="1234"):
        """
        【功能描述】
            设置loid和loid password
        【入参】
            loid:str sn 0-24位 默认mtk1234
            loid_password:str 0-12位 默认1234
        【返回值】

        【示例】
        Example:
        """
        try:
            loid_len = len(loid)
            loid_password_len = len(loid_password)
            if loid_len > 24:
                raise
            if loid_password_len > 12:
                raise

            loid_params = {
                "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}LOID",
                "value": loid
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", loid_params)
            loid_password_params = {
                "path": f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}LOIDPassword",
                "value": loid_password
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", loid_password_params)

            return result
        except Exception as e:
            return False
            raise

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            #result = self.get_sn_info()
            #result = json.dumps(result, indent=4, ensure_ascii=False)
            #print(result)

        except Exception as e:
            print("debug test failed: ", str(e))

if __name__ == '__main__':
    Mirror = PonRegisterManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    Mirror.debug_test()
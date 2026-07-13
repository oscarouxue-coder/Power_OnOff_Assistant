import time

from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
from SdmcUbusLib.libs.Wlan_moudle_api.wlan import WlanManager
from SdmcCode import *
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class GuestNetworkManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        self.wlan = WlanManager(ip, username, password)

    def get_guest_path(self):
        """
        【功能描述】
        获取访客网络映射路径
        
        【返回值】
        path: 访客网络映射路径
        
        """

        path = {}
        path_2g = self.wlan.get_mapping2g_info()
        ret = self.wlan.parse_mapping(path_2g)
        path["guest_2g_path"] = ret[-1]

        path_5g = self.wlan.get_mapping5g_info()
        ret = self.wlan.parse_mapping(path_5g)
        path["guest_5g_path"] = ret[-1]

        return path

    def get_guest_ssid_info(self, path):
        """
        【功能描述】
        获取访客网络SSID信息
        
        【入参】
        path: 访客网络映射路径
        
        【返回值】
        ssidinfo: 访客网络SSID信息
        
        """

        if not path:
            log.error("[ERROR] mapping2g_str is empty or None")
            return []

        ssidpath = path.get('SSIDPath')
        params = {
            "path": ssidpath,
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get('SSID')[0]

        ssidinfo = {
            "Enable": data.get("Enable"),
            "SSID": data.get("SSID")
        }
        return ssidinfo

    def get_guest_accesspoint_info(self, path):
        """
        【功能描述】
        获取访客网络accesspoint信息

        【入参】
        path: 访客网络映射路径

        【返回值】
        ssidinfo: 访客网络accesspoint信息

        """
        if not path:
            log.error("[ERROR] mapping2g_str is empty or None")
            return {}

        accesspointpath = path.get('AccessPointPath')
        params = {
            "path": accesspointpath,
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        AccessPointData = result[1].get('AccessPoint')[0]

        info = {
            "BroadcastSSID": AccessPointData.get('SSIDAdvertisementEnabled'),
            "AuthorizationMode": AccessPointData.get('Security', {}).get('ModeEnabled'),
            "WPAPreSharedKey": AccessPointData.get('Security', {}).get(f'{VENDOR_PREFIX}Key'),
            "Speedlimit": AccessPointData.get(f'{VENDOR_PREFIX}WiFiIFRatelimit')
        }

        return info

# ===================robot api===========================

    def get_guest_wifi_info(self):
        """
        【功能描述】
        获取访客网络信息
        
        【返回值】
        访客网络信息
        {'guest_2g_ssid_Enable': True, 'guest_2g_ssid_SSID': 'Sdmc_guest_2g', 'guest_2g_ap_BroadcastSSID': True, 'guest_2g_ap_AuthorizationMode': 'WPA2-Personal', 'guest_2g_ap_WPAPreSharedKey': 'Sdmc@123', 'guest_2g_ap_Speedlimit': 0, 'guest_5g_ssid_Enable': True, 'guest_5g_ssid_SSID': 'Sdmc_guest_5g', 'guest_5g_ap_BroadcastSSID': False, 'guest_5g_ap_AuthorizationMode': 'WPA2-Personal', 'guest_5g_ap_WPAPreSharedKey': 'Sdmc@123', 'guest_5g_ap_Speedlimit': 0}

        
        """

        path = self.get_guest_path()

        # 2.4G 信息
        ssid_info_2g = self.get_guest_ssid_info(path["guest_2g_path"])
        ap_info_2g = self.get_guest_accesspoint_info(path["guest_2g_path"])

        # 5G 信息
        ssid_info_5g = self.get_guest_ssid_info(path["guest_5g_path"])
        ap_info_5g = self.get_guest_accesspoint_info(path["guest_5g_path"])

        # 平铺字典
        wifi_info = {
            # 2.4G SSID 信息
            **{f"guest_2g_ssid_{k}": v for k, v in ssid_info_2g.items()},

            # 2.4G AP 信息
            **{f"guest_2g_ap_{k}": v for k, v in ap_info_2g.items()},

            # 5G SSID 信息
            **{f"guest_5g_ssid_{k}": v for k, v in ssid_info_5g.items()},

            # 5G AP 信息
            **{f"guest_5g_ap_{k}": v for k, v in ap_info_5g.items()},
        }

        return wifi_info

    def set_guest_wifi_2g(self, ssid, key,
                          ratelimit=0,
                          mode="WPA2-Personal",
                          enable=True,
                          broadcast=True,
                          wait_time=90):
        """
        【功能描述】
        通过 ubus 设置 2G 访客网络 WiFi

        【入参】
         ssid: 2G SSID
         key: 2G 密码
         ratelimit: 2G 限速
         mode: 2G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable: 是否启用
         broadcast: 是否广播 SSID
         wait_time: wifi重启等待时间

        【返回值】
        ERR_SUCCESS  : 执行成功
        ERR_FAIL : 执行失败 或 抛出异常

        【示例】
        Example:
        |  set_guest_wifi_2g  |  ssid=sdmc_2g  |  key=Sdmc@123  |
        """
        ret = ERR_FAIL
        try:

            path = self.get_guest_path()["guest_2g_path"]

            paths = [
                # SSID
                {
                    "addr": path["SSIDPath"],
                    "obj_path": {
                        "Enable": enable,
                        "SSID": ssid,
                        f"{VENDOR_PREFIX}MODE": "guest"
                    }
                },
                # AccessPoint
                {
                    "addr": path["AccessPointPath"],
                    "obj_path": {
                        "SSIDAdvertisementEnabled": "1" if broadcast else "0",
                        f"{VENDOR_PREFIX}WiFiIFRatelimit": ratelimit
                    }
                },
                # AccessPoint Security
                {
                    "addr": path["AccessPointPath"] + "Security.",
                    "obj_path": {
                        "ModeEnabled": mode,
                        f"{VENDOR_PREFIX}Key": key
                    }
                }
            ]

            params = {
                "paths": paths,
                "optional": {
                    "proto": "web"
                }
            }

            wifi_set = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            log.info(f"等待{wait_time}S WiFi重启..........")
            time.sleep(int(wait_time))
            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def set_guest_wifi_5g(self, ssid, key,
                          ratelimit=0,
                          mode="WPA2-Personal",
                          enable=True,
                          broadcast=True,
                          wait_time=90):
        """
        【功能描述】
        通过 ubus 设置 5G 访客网络 WiFi
        
        【入参】
         ssid: 5G SSID
         key: 5G 密码
         ratelimit: 5G 限速
         mode: 5G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable: 是否启用
         broadcast: 是否广播 SSID
         wait_time: wifi重启等待时间
        
        【返回值】
        ERR_SUCCESS  : 执行成功
        ERR_FAIL : 执行失败 或 抛出异常
        
        【示例】
        Example:
        |  set_guest_wifi_5g  |  ssid=sdmc_5g  |  key=Sdmc@123  |
        
        """
        ret = ERR_FAIL
        try:
            path = self.get_guest_path()["guest_5g_path"]

            paths = [
                # SSID
                {
                    "addr": path["SSIDPath"],
                    "obj_path": {
                        "Enable": enable,
                        "SSID": ssid,
                        f"{VENDOR_PREFIX}MODE": "guest"
                    }
                },
                # AccessPoint
                {
                    "addr": path["AccessPointPath"],
                    "obj_path": {
                        "SSIDAdvertisementEnabled": "1" if broadcast else "0",
                        f"{VENDOR_PREFIX}WiFiIFRatelimit": ratelimit
                    }
                },
                # AccessPoint Security
                {
                    "addr": path["AccessPointPath"] + "Security.",
                    "obj_path": {
                        "ModeEnabled": mode,
                        f"{VENDOR_PREFIX}Key": key
                    }
                }
            ]

            params = {
                "paths": paths,
                "optional": {
                    "proto": "web"
                }
            }

            wlan_set = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            log.info(f"等待{wait_time}S WiFi重启..........")
            time.sleep(int(wait_time))
            ret = ERR_SUCCESS
        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def set_guest_wifi(self, ssid_2g, ssid_5g, key_2g, key_5g,
                       ratelimit_2g=0, ratelimit_5g=0,
                       mode_2g="WPA3-Personal-Transition",
                       mode_5g="WPA2-Personal",
                       enable_2g=True, enable_5g=True,
                       broadcast_2g=True, broadcast_5g=False, wait_time=90):
        """
        【功能描述】
        通过 ubus 同时设置 2.4G 和 5G 访客网络 WiFi

        【入参】
         ssid_2g: 2.4G SSID
         key_2g: 2.4G 密码
         ratelimit_2g: 2.4G 限速
         mode_2g: 2.4G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable_2g: 是否启用 2.4G
         broadcast_2g: 是否广播 2.4G SSID

         ssid_5g: 5G SSID
         key_5g: 5G 密码
         ratelimit_5g: 5G 限速
         mode_5g: 5G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable_5g: 是否启用 5G
         broadcast_5g: 是否广播 5G SSID
         wait_time: wifi重启等待时间

        【返回值】
        ERR_SUCCESS : 执行成功
        ERR_FAIL    : 执行失败 或 抛出异常

        【示例】
        Example:
        |  set_guest_wifi  |  ssid_2g=sdmc_2g  |  key_2g=Sdmc@123  |  ssid_5g=sdmc_5g  |  key_5g=Sdmc@123  |
        """
        ret = ERR_FAIL
        try:
            result_2g = self.set_guest_wifi_2g(
                ssid=ssid_2g, key=key_2g,
                ratelimit=ratelimit_2g,
                mode=mode_2g,
                enable=enable_2g,
                broadcast=broadcast_2g
            )
            result_5g = self.set_guest_wifi_5g(
                ssid=ssid_5g, key=key_5g,
                ratelimit=ratelimit_5g,
                mode=mode_5g,
                enable=enable_5g,
                broadcast=broadcast_5g
            )
            log.info(f"等待{wait_time}S WiFi重启..........")
            time.sleep(int(wait_time))
            ret = ERR_SUCCESS
        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            path = self.get_guest_wifi_info()
            # result = self.set_guest_wifi(
            #     ssid_2g="SDMC_E42220_Guest",
            #     ssid_5g="SDMC_E42220_5G_Guest222",
            #     key_2g="Sdmc@123",
            #     key_5g="Sdmc@123111",
            #     ratelimit_2g=0,
            #     ratelimit_5g=0,
            #     mode_2g="WPA2-Personal",
            #     mode_5g="WPA3-Personal-Transition"
            # )
            # result = json.dumps(result, indent=4, ensure_ascii=False)
            self.set_guest_wifi_2g("SDMC_E42220_Guest", "Sdmc@123", enable=1, broadcast=0)
            # print(path)
            # info = self.get_guest_wifi_info()
            # info = json.dumps(info, indent=4, ensure_ascii=False)
            # log.info(info)

        except Exception as e:
            log.info("debug test failed: ", str(e))


if __name__ == '__main__':
    Guest = GuestNetworkManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    Guest.debug_test();

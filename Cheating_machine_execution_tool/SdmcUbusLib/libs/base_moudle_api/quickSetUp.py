"""
测试库 ubus for OpenWRT
author = JWB
20241209   v1.0
1 新建 基础 接口 API




"""

from SdmcLog import log

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class SdmcUbusLibQuickSetUp(SdmcUbusLibBase):
    """
    测试库 demo for class
    """

    ROBOT_LIBRARY_SCOPE = 'GLOBAL'

    def __init__(self):
        """
        """
        SdmcUbusLibBase.__init__(self)

    def quickSetUp(self, timezone, bandSteering_enable, wlan2G_enable, wlan2G_SSID, wlan2G_password, wlan5G_enable,
                   wlan5G_SSID, wlan5G_password, quickSetup_enable):
        """
        功能描述：快速设置功能quickSetup

        参数：
        timezone： 默认： UTC  #设置时区

        bandSteering_enable: 0/1 默认： 0 #设置双频合一关闭/开启

        wlan2G_enable: true/false 默认： true #开启/关闭 2.4G WiFi

        wlan2G_SSID: 默认：AN7551_2.4G_jwb #设置 2.4G WiFi  SSID

        wlan2G_password: 默认：12345678  #设置 2.4G WiFi 密码

        wlan5G_enable: true/false 默认： true #开启/关闭 5G WiFi

        wlan5G_SSID: 默认：AN7551_5G_jwb #设置 5G WiFi  SSID

        wlan5G_password: 默认：12345678  #设置 5G WiFi 密码

        quickSetup_enable： 0/1 默认： 0 #关闭/开启 quickSetup快速设置

        """
        set_quickSetup_list = [
            {
                "addr": "Device.Time.",
                "obj_path": {"LocalTimeZone": timezone}
            },
            {
                "addr": "Device.WiFi.",
                "obj_path": {f"{VENDOR_PREFIX}DualBandEnable": bandSteering_enable}
            },
            {
                "addr": "Device.WiFi.SSID.1.",
                "obj_path": {"Enable": wlan2G_enable, "SSID": wlan2G_SSID}
            },
            {
                "addr": "Device.WiFi.SSID.4.",
                "obj_path": {"Enable": wlan5G_enable, "SSID": wlan5G_SSID}
            },
            {
                "addr": "Device.WiFi.AccessPoint.1.Security.",
                "obj_path": {f"{VENDOR_PREFIX}Key": wlan2G_password}
            },
            {
                "addr": "Device.WiFi.AccessPoint.3.Security.",
                "obj_path": {f"{VENDOR_PREFIX}Key": wlan5G_password}
            },
            {
                "addr": "Device.",
                "obj_path": {f"{VENDOR_PREFIX}QuickSetup": quickSetup_enable}
            }
        ]
        set_quickSetup = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'set', {"paths": set_quickSetup_list, "optional": {"proto": "web"}})
        print(set_quickSetup)

    def quiickSetup_get(self):
        """
        功能描述：
        """
        get_quickSetup_list_2G = ["Device.Time.LocalTimeZone", "Device.WiFi.X_SDMC_DualBandEnable",
                                  "Device.WiFi.SSID.1.Enable", "Device.WiFi.SSID.1.SSID",
                                  "Device.WiFi.AccessPoint.1.Security.X_SDMC_Key",
                                  "Device.X_SDMC_QuickSetup"]
        get_quickSetup_list_5G = ["Device.WiFi.SSID.4.Enable",
                                  "Device.WiFi.SSID.4.SSID", "Device.WiFi.AccessPoint.3.Security.X_SDMC_Key"]
        get_quickSetup_2G = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'get',
                                           {"paths": get_quickSetup_list_2G, "optional": {"proto": "web"}})
        get_quickSetup_5G = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'get',
                                           {"paths": get_quickSetup_list_5G, "optional": {"proto": "web"}})
        log.info("2.4GWiFi信息：" + str(get_quickSetup_2G[1]) + ";" + "5GWiFi信息：" + str(get_quickSetup_5G[1]))

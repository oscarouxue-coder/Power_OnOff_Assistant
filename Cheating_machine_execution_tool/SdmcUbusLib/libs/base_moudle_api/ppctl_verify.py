from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcUbusLib.libs.base_moudle_api.status import StatusManager
from SdmcUbusLib.libs.Network_module_api.pon import PonManager
from SdmcUbusLib.libs.Network_module_api.Lan_moudle_api.Lan import LanManager
from SdmcUbusLib.libs.Wlan_moudle_api.wlan import WlanManager
from SdmcUbusLib.libs.Security_module_api.enable_telnet import SdmcUbusLibEnableTelnet


class PpctlVerifyManager:
    def __init__(self, ip, username, password):
        """

        """
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        self.status = StatusManager(self.ip, self.username, self.password)
        self.pon = PonManager(self.ip, self.username, self.password)
        self.lan = LanManager(self.ip, self.username, self.password)
        self.wlan = WlanManager(self.ip, self.username, self.password)

    def ubus_get_sn(self):
        """
        【功能描述】
        获取设备序列号（SN）。

        【入参】
        无

        【返回值】
        str : 返回设备序列号字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_sn  |
        返回示例: "SN1234567890"
        """
        try:
            status_info = self.status.get_device_info()
            sn = status_info.get('Device SN')
            return sn
        except Exception as e:
            raise


    def ubus_get_lan_mac(self):
        """
        【功能描述】
        获取设备 LAN 接口的 MAC 地址。

        【入参】
        无

        【返回值】
        str : 返回 LAN MAC 地址字符串，例如 "00:11:22:33:44:55"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_lan_mac  |
        返回示例: "00:11:22:33:44:55"
        """
        try:
            status_info = self.status.get_device_info()
            lan_mac = status_info.get('MAC Address')
            return lan_mac
        except Exception as e:
            raise

    def ubus_get_xpon_sn(self):
        """
        【功能描述】
        获取光猫/ONU 的 XPON 认证序列号。

        【入参】
        无

        【返回值】
        str : 返回 XPON 认证序列号字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_xpon_sn  |
        返回示例: "XPON1234567890"
        """
        try:
            pon_info = self.pon.get_broadband_authentication_ubus()
            xpon_sn = pon_info.get('Authentication').get(f'{VENDOR_PREFIX}SerialNumber')
            return xpon_sn
        except Exception as e:
            raise

    def ubus_get_lan_ip(self):
        """
        【功能描述】
        获取 LAN 接口的 IP 地址。

        【入参】
        无

        【返回值】
        str : 返回 LAN IP 地址字符串，例如 "192.168.1.1"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_lan_ip  |
        返回示例: "192.168.1.1"
        """
        try:
            lan_info = self.lan.get_host_info()
            lan_ip = lan_info.get('Address')
            return lan_ip
        except Exception as e:
            raise

    def ubus_get_24G_ssid(self):
        """
        【功能描述】
        获取 2.4GHz 无线网络的 SSID。

        【入参】
        无

        【返回值】
        str : 返回 2.4G SSID 字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_24G_ssid  |
        返回示例: "MyWifi_2.4G"
        """
        try:
            wlan_24G_info = self.wlan.ubus_get_all_2g_info()
            wlan_24G_ssid = wlan_24G_info.get('SSID')
            return wlan_24G_ssid
        except Exception as e:
            raise

    def ubus_get_24G_key(self):
        """
        【功能描述】
        获取 2.4GHz 无线网络的 WPA 预共享密钥。

        【入参】
        无

        【返回值】
        str : 返回 2.4G WPA 密钥，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_24G_key  |
        返回示例: "12345678"
        """
        try:
            wlan_24G_info = self.wlan.ubus_get_all_2g_info()
            wlan_24G_key = wlan_24G_info.get('WPAPreSharedKey')
            return wlan_24G_key
        except Exception as e:
            raise

    def ubus_get_5G_ssid(self):
        """
        【功能描述】
        获取 5GHz 无线网络的 SSID。

        【入参】
        无

        【返回值】
        str : 返回 5G SSID 字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_5G_ssid  |
        返回示例: "MyWifi_5G"
        """
        try:
            wlan_5G_info = self.wlan.ubus_get_all_5g_info()
            wlan_5G_ssid = wlan_5G_info.get('SSID')
            return wlan_5G_ssid
        except Exception as e:
            raise

    def ubus_get_5G_key(self):
        """
        【功能描述】
        获取 5GHz 无线网络的 WPA 预共享密钥。

        【入参】
        无

        【返回值】
        str : 返回 5G WPA 密钥，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_5G_key  |
        返回示例: "87654321"
        """
        try:
            wlan_5G_info = self.wlan.ubus_get_all_5g_info()
            wlan_5G_key = wlan_5G_info.get('WPAPreSharedKey')
            return wlan_5G_key
        except Exception as e:
            raise

    def get_wifi_band_map(self, wireless_output):
        """
        【功能描述】
        解析无线配置，识别各 wifi-device 对应的频段（2.4G / 5G）。

        【入参】
        wireless_output : str
            从命令 `cat /etc/config/wireless | grep wifi-device` 获取的输出内容。

        【返回值】
        dict :
            返回各频段对应的设备名称，格式示例：
            {
                "2.4G": "phy0",
                "5G": "phy1"
            }
            如果某个频段没有设备，则不包含该键。

        【示例】
        Example:
        |  get_wifi_band_map  |  wireless_output=<输出字符串>  |
        返回示例:
        {'2.4G': 'phy0', '5G': 'phy1'}
        """
        result = {"2.4G": set(), "5G": set()}
        device_list = []
        remote = SdmcUbusLibEnableTelnet()

        for line in wireless_output.splitlines():
            line = line.strip()
            if line.startswith("config wifi-device"):
                parts = line.split("'")
                if len(parts) >= 2:
                    device_name = parts[1]
                    device_list.append(device_name)

        for dev in device_list:
            cmd = f"uci get wireless.{dev}.band"
            try:
                band_info = remote.telnet_run_cmd(self.ip, self.username, self.password, cmd)
            except Exception as e:
                print(f"[WARN] 获取 {dev} 频段失败: {e}")
                continue

            if not band_info:
                continue

            band_info = band_info.strip().lower()

            if "2.4" in band_info or "2g" in band_info:
                result["2.4G"].add(dev)
            elif "5" in band_info:
                result["5G"].add(dev)
            else:
                log.info(f"[WARN] 未识别频段: {band_info} (device={dev})")

        final_result = {}
        for band, dev_set in result.items():
            if dev_set:
                final_result[band] = next(iter(dev_set))

        return final_result

    def parse_telnet_output(self, output: str, cmd: str):
        """
        【功能描述】
        从 telnet 返回的字符串中提取有效结果，去掉命令行和提示符行。

        【入参】
        output : str
            telnet 执行命令返回的原始字符串
        cmd : str
            执行的命令，用于过滤命令行本身

        【返回值】
        str :
            返回命令实际输出内容（去掉提示符和命令本身）
            如果解析失败或为空，返回 None。

        【示例】
        Example:
        |  parse_telnet_output  |  output=<原始字符串>  |  cmd=<命令>  |
        返回示例: "US"
        """
        if not output:
            return None

        lines = [line.strip() for line in output.splitlines() if line.strip()]

        for line in lines:
            if line == cmd:
                continue
            if line.endswith("#") or line.endswith("$"):
                continue
            return line

        return None

    def ubus_telnet_get_24G_ccode(self):
        """
        【功能描述】
        通过 telnet 获取 2.4GHz 无线网络的国家码 (country code)。

        【入参】
        无

        【返回值】
        str : 返回 2.4G 国家码，例如 "US"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_telnet_get_24G_ccode  |
        返回示例: "US"
        """
        try:
            remote = SdmcUbusLibEnableTelnet()
            wlan_device_info = remote.telnet_run_cmd(self.ip, self.username, self.password,
                                                     "cat /etc/config/wireless | grep wifi-device")
            devices = self.get_wifi_band_map(wlan_device_info)
            cmd_get_24G_ccode = f"uci get wireless.{devices.get('2.4G')}.country"
            wlan_24G_ccode = remote.telnet_run_cmd(self.ip, self.username, self.password, cmd_get_24G_ccode)
            wlan_24G_ccode = self.parse_telnet_output(wlan_24G_ccode, cmd_get_24G_ccode)

            return wlan_24G_ccode
        except Exception as e:
            raise

    def ubus_telnet_get_5G_ccode(self):
        """
        【功能描述】
        通过 telnet 获取 5GHz 无线网络的国家码 (country code)。

        【入参】
        无

        【返回值】
        str : 返回 5G 国家码，例如 "US"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_telnet_get_5G_ccode  |
        返回示例: "US"
        """
        try:
            remote = SdmcUbusLibEnableTelnet()
            wlan_device_info = remote.telnet_run_cmd(self.ip, self.username, self.password, "cat /etc/config/wireless | grep wifi-device")
            devices = self.get_wifi_band_map(wlan_device_info)
            cmd_get_5G_ccode = f"uci get wireless.{devices.get('5G')}.country"
            wlan_5G_ccode = remote.telnet_run_cmd(self.ip, self.username, self.password, cmd_get_5G_ccode)
            wlan_5G_ccode = self.parse_telnet_output(wlan_5G_ccode, cmd_get_5G_ccode)

            return wlan_5G_ccode
        except Exception as e:
            raise

    def debug_test(self):
        """
        功能描述：调试测试接口
        """
        self.ubus.Ubus_Login("root", "t*hEQ#BHu7z%3n")
        ret = self.ubus_telnet_get_5G_ccode()
        print(f"{ret}")

if __name__ == '__main__':
    ppctlverify = PpctlVerifyManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    ppctlverify.debug_test()

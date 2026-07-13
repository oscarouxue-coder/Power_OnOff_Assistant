"""
测试库 ubus for OpenWRT

20241202   v1.0
1 新建 基础 接口 API




"""
import inspect
import ping3

from SdmcLog import log
from SdmcCode import *

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcNetcardLib import SdmcNetcardLib
from SdmcNetworkLib import SdmcNetworkLib
from time import sleep


from SdmcUbusLib.libs.Network_module_api import SdmcNetworkLib
from SdmcUbusLib.libs.Wlan_moudle_api import SdmcWlanLib
from SdmcUbusLib.libs.base_moudle_api import SdmcBasesLib
from SdmcUbusLib.libs.Management_module_api import SdmcManagementLib
from SdmcUbusLib.libs.Performance_module_api import SdmcPerformanceLib
from SdmcUbusLib.libs.Security_module_api import SdmcSecurityLib
from SdmcUbusLib.libs.IPTV_module_api import SdmcIPTVLib
from SdmcUbusLib.libs.Pon_module_api import SdmcPonLib
from SdmcUbusLib.libs.Voice_moudle_api import SdmcVoiceLib


class SdmcUbusLib(SdmcUbusLibBase):
    """
    测试库 demo for class
    """

    def __init__(self):
        """
        """
        SdmcUbusLibBase.__init__(self)

        self.netcard = SdmcNetcardLib()
        self.network = SdmcNetworkLib()
        self.password = ""
        self.libs = [SdmcNetworkLib(),SdmcWlanLib(),SdmcBasesLib(),SdmcManagementLib(),SdmcSecurityLib(),SdmcSecurityLib(),SdmcIPTVLib(),SdmcPonLib(),SdmcVoiceLib()]
        self._get_self_keywords()

    def _get_self_keywords(self):
        """
        """
        self.keywords = []

        # ✅ 自动发现：所有以 "MyLibrary_" 开头的方法
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("Ubus_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)

    def _validate_password(self, password):

        if len(password) < 8 or len(password) > 32:
            log.info("密码长度应在8到32个字符之间")
            raise

        if not any(c.islower() for c in password):
            log.info("密码必须包含小写字母")
            raise

        if not any(c.isupper() for c in password):
            log.info("密码必须包含大写字母")
            raise

        if not any(c.isdigit() for c in password):
            log.info("密码必须包含数字")
            raise

        if not any(c in "!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~" for c in password):
            log.info("密码必须包含特殊字符")
            raise


    def debug_test(self):
        super().Ubus_Switch("http://192.168.0.1/ubus/")
        self.Ubus_Login("root", "1234")
        # self.Ubus_Network_WAN_Delete("5")
        info = self.Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4("0", "INTERNET")
        # info = self.Ubus_Network_Wlan_Get_All_2G_info()
        log.info(info)

    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        for lib in self.libs:
            names.extend(lib.get_keyword_names())
        return names

    def run_keyword(self, name, args, kwargs={}):
        """
        """
        # ✅ 先查主类关键字（匹配 "MyLibrary xxx"）
        method_name = name
        if hasattr(self, method_name):
            return getattr(self, method_name)(*args, **kwargs)

        for lib in self.libs:
            if name in lib.get_keyword_names():
                return lib.run_keyword(name, args, kwargs)
        raise Exception(f"Unknown keyword: {name}")

    def get_keyword_documentation(self, name):
        """返回关键字的文档说明"""

        # ✅ 主类关键字 docstring
        method_name = name
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            doc = inspect.getdoc(method)
            return doc if doc else "No documentation provided."

        # ✅ 子库关键字 docstring
        for lib in self.libs:
            if name in lib.get_keyword_names() and hasattr(lib, "get_keyword_documentation"):
                return lib.get_keyword_documentation(name)

        return "No documentation provided."

    def get_keyword_arguments(self, name):
        """返回关键字的参数列表"""
        method_name = name
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            sig = inspect.signature(method)
            # 过滤掉 self 参数
            return [p.name for p in sig.parameters.values() if p.name != "self"]

        for lib in self.libs:
            if name in lib.get_keyword_names() and hasattr(lib, "get_keyword_arguments"):
                return lib.get_keyword_arguments(name)

        return []



def te2st(tag=""):
    """
    unit test
    """
    n_ret = ERR_FAIL
    n_ret_api = 0
    desc = ""

    for nwf in [1]:

        try:

            c1 = SdmcUbusLib()
            ret = c1.Ubus_Switch("http://192.168.29.1/ubus/")
            ret = c1.Ubus_Login("sdmc", "1234")
            c1.Ubus_Network_Wlan_Set_BandSteering(bandsteering="1", ssid="Test_2G_01", password="Sdmc@123")
            info = c1.Ubus_Network_Wlan_Get_All_Bandsteering_info()
            print("info" + str(info))
            c1.Ubus_Logout()

            if (0):
                ret = c1.Ubus_Network_LAN_Set_DHCPv4_Relay()
                print(ret)

            if (0):
                ret = c1.Ubus_Network_LAN_Set_DHCPv4_Service()
                print(ret)

            if (0):
                ret = c1.Ubus_Network_LAN_Get()
                print(ret)

            if (0):
                ret = c1.Ubus_Network_WAN_Delete("5")
                print(ret)

            if (0):
                names = c1.Ubus_Network_WAN_Get_Connection_Names()
                configs = c1.Ubus_Network_WAN_Get(names[0])
                print(configs)

            if (0):
                names = c1.Ubus_Network_WAN_Get_Connection_Names()
                print(names)

            if (0):
                Iptv_config = {
                    "Method": "add",
                    "VLAN": 123,
                    "Mode": "router",
                    "ServiceType": "IPTV",
                    "PortBind": "0",
                    "IPoE": "1",
                    "IPv4Type": "Dynamic",
                    "IPProtocol": "IPv4",
                    "MulticastVLANID": "222",
                }
                n_ret = c1.Ubus_Network_WAN_Set(Iptv_config)
                print(n_ret)

            if (0):
                n_ret = c1.Ubus_Upgrade("e:/tclinux_trxheader_upg.bin")

            if (0):
                # c1.Ubus_WLAN_2G()
                c1.Ubus_get_wan_ipv4_address('200')

            if (0):
                c1.Ubus_Switch("http://192.168.29.1/ubus222/")
                ret = c1.Ubus_Login("root", "admin1234")
                print(ret)

                ret = c1.Ubus_Call("bbfdm", "get", {"path": "Device.ManagementServer.PeriodicInformInterval"})
                print(ret)

                ret = c1.Ubus_Call("bbfdm", "add",
                                   {"optional": {"proto": "web"},
                                    "paths": [
                                        {"addr": "Device.Ethernet.Link."},
                                        {"addr": "Device.Ethernet.VLANTermination."},
                                        {"addr": "Device.IP.Interface."}
                                    ]})
                print(ret)

                ret = c1.Ubus_Call("bbfdm", "get", {"path": "Device.ManagementServer.PeriodicInformIntervalXXX"})
                print(ret)

                ret = c1.Ubus_Call("bbfdm", "set",
                                   {"path": "Device.ManagementServer.PeriodicInformIntervalXXX", "value": "1808X"})
                print(ret)

            # ret = c1.Ubus_lan_test(10)
            # print(ret)

        except Exception as e:
            log.exception(str(e))

    return n_ret


if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    print("start ---------------------------\n")

    restult = SdmcUbusLib()
    restult.debug_test()

    print("\nfinish ------------------")
    # os.system("pause")

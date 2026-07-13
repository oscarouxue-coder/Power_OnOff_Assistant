"""
wan,lan模块api
"""
import json

from SdmcUbusLib.libs.Network_module_api.Wan_moudle_api import SdmcWanLib
from SdmcUbusLib.libs.Network_module_api.Lan_moudle_api import SdmcLanLib
import inspect
from SdmcUbusLib.libs.Network_module_api.vpn import VpnManager
from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcLog import log
from SdmcCode import *
from SdmcUbusLib.libs.Network_module_api.ntp import NtpManager
from SdmcUbusLib.libs.Network_module_api.upnp import UpnpManager


class SdmcNetworkLib(object):

    def __init__(self):
        """
        """
        self.libs = [SdmcWanLib(),SdmcLanLib()]
        self._get_self_keywords()


    def _get_self_keywords(self):
        """
        """
        self.keywords = []

        # ✅ 自动发现：所有以 "MyLibrary_" 开头的方法
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("robot_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)
            if name.startswith("Ubus_"):
                self.keywords.append(name)

    def _Ubus_ntp_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.ntp = NtpManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_get_ntp_info(self):
        """
        【功能描述】
        获取 time 相关参数信息

        【入参】
        无

        【返回值】
        {'Enable': True, 'Status': 'Synchronized', 'NTPServer1': '0.openwrt.pool.ntp.org', 'NTPServer2': '1.openwrt.pool.ntp.org', 'NTPServer3': '2.openwrt.pool.ntp.org', 'NTPServer4': '3.openwrt.pool.ntp.org', 'NTPServer5': '', 'CurrentLocalTime': '2025-10-12T16:18:44+00:00', 'LocalTimeZone': 'UTC', 'X_SDMC_CalendarTime': 1760285924, 'ConvertedLocalTime': '2025-10-13 00:18:44'}


        【示例】
        Example:
        |  Ubus_get_ntp_info  |

        """
        self._Ubus_ntp_init()
        ret = self.ntp.get_ntp_ubus()
        return ret

    def Ubus_set_ntp_info(self, time_zone="UTC", ntp_service_enable=True, primary_ntp_server="0.openwrt.pool.ntp.org", secondary_ntp_server="1.openwrt.pool.ntp.org", third_ntp_server="2.openwrt.pool.ntp.org", fourth_ntp_server="3.openwrt.pool.ntp.org"):
        """
        【功能描述】
        设置 NTP 相关参数信息

        【入参】
        time_zone: 时区设置，默认 "UTC"
        ntp_service_enable: NTP服务启用状态，默认 True
        primary_ntp_server: 主要NTP服务器地址，默认 "0.openwrt.pool.ntp.org"
        secondary_ntp_server: 次要NTP服务器地址，默认 "1.openwrt.pool.ntp.org"
        third_ntp_server: 第三NTP服务器地址，默认 "2.openwrt.pool.ntp.org"
        fourth_ntp_server: 第四NTP服务器地址，默认 "3.openwrt.pool.ntp.org"

        【返回值】
        设置成功返回 True，设置失败返回 False

        【示例】
        Example:
        |  Ubus_set_ntp_info  | time_zone="UTC" | ntp_service_enable=True | primary_ntp_server="0.openwrt.pool.ntp.org" |

        """
        self._Ubus_ntp_init()
        ret = self.ntp.set_ntp_ubus(
            time_zone=time_zone,
            ntp_service_enable=ntp_service_enable,
            primary_ntp_server=primary_ntp_server,
            secondary_ntp_server=secondary_ntp_server,
            third_ntp_server=third_ntp_server,
            fourth_ntp_server=fourth_ntp_server
        )
        return ret


    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        for lib in self.libs:
            names.extend(lib.get_keyword_names())

        return names

    def run_keyword(self, name, args, kwargs=None):
        """
        """
        method_name = name
        if hasattr(self, method_name):
            return getattr(self, method_name)(*args, **kwargs)

        for lib in self.libs:
            if name in lib.get_keyword_names():
                return lib.run_keyword(name, args, kwargs)
        raise  Exception(f"Unknown keyword: {name}")

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
    def _Ubus_upnp_init(self):
        """
        功能描述：初始化 UPnP 管理器

        参数： \n

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:

        """
        n_ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.upnp_manager = UpnpManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_upnp_set_enable(self, enable=True):
        """
        【功能描述】
        设置 UPnP 功能的开关状态

        【入参】
        enable: True 表示开启 UPnP，False 表示关闭 UPnP

        【返回值】
        成功返回 True，失败返回 False

        【示例】
        Example:
        |  Ubus_upnp_set_enable  True  |
        |  Ubus_upnp_set_enable  False  |

        """
        self._Ubus_upnp_init()
        return self.upnp_manager.set_upnp_enable(enable)

    def Ubus_upnp_get_status(self):
        """
        【功能描述】
        获取 UPnP 功能的当前状态

        【入参】
        无

        【返回值】
        返回 UPnP 状态信息，格式为字典

        【示例】
        Example:
        |  ${status} |  Ubus_upnp_get_status  |

        """
        self._Ubus_upnp_init()
        return self.upnp_manager.get_upnp_status()

    def Ubus_upnp_get_rules(self):
        """
        【功能描述】
        获取当前 UPnP 规则列表

        【入参】
        无

        【返回值】
        返回 UPnP 规则列表，包含协议、外部端口、客户端IP、内部端口和描述信息
        格式为字典，包含 item_count 和 rules 两个字段

        【示例】
        Example:
        |  ${rules} |  Ubus_upnp_get_rules  |

        """
        self._Ubus_upnp_init()
        return self.upnp_manager.get_upnp_rules()

    def _Ubus_Network_VPN_Init(self):
        """
        功能描述：

        参数： \n

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:

        """
        n_ret = ERR_FAIL

        for nwf in [1]:

            try:

                parsed_url = urlparse(SdmcUbusLibBase.Url)
                ip = parsed_url.hostname

                username = SdmcUbusLibBase.Username
                password = SdmcUbusLibBase.Password

                self.vpn_manager = VpnManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_Network_VPN_Get(self):
        """
        功能描述：获取 VPN 客户端

        参数： \n
            no parameter
        返回值：
            默认返回成功;
            异常 是 失败的一种;

        Example:
        | ${ret} |  Ubus_Network_VPN_Get  |

        """

        self._Ubus_Network_VPN_Init()
        return self.vpn_manager.get_vpn_client()

    def Ubus_Network_VPN_Set(self, enable=1, username=None, password=None, server=None):
        """
        功能描述：设置 VPN 客户端

        参数： \n
            enable  1 表示  True;  0 表示 False
            username: username
            password: password
            server: vpn server ip or domain

        返回值：
            默认返回成功;
            异常 是 失败的一种;

        Example:
        | ${ret} |  Ubus_Network_VPN_Set  |

        """

        self._Ubus_Network_VPN_Init()
        self.vpn_manager.set_vpn_client(enable=enable, username=username, password=password, server=server)
        return True


if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    # logging.getLogger().setLevel(logging.DEBUG)
    # logging.basicConfig(filename='example.log',level=logging.INFO)

    print("start ---------------------------\n")

    # n_ret_api = test()

    print("\nfinish ------------------")
    # os.system("pause")



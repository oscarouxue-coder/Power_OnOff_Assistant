"""

"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcLog import log
from SdmcCode import *
from SdmcUbusLib.libs.Management_module_api.cwmp import CwmpManager
import inspect
from time import sleep
import time
from SdmcUbusLib.libs.IPTV_module_api.iptv import IptvManager


class SdmcIPTVLib(object):
    """
    """

    def __init__(self):
        """
        """

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

    def _Ubus_iptv_Init(self):
        """
        """
        n_ret = ERR_FAIL

        for nwf in [1]:

            try:

                parsed_url = urlparse(SdmcUbusLibBase.Url)
                ip = parsed_url.hostname

                username = SdmcUbusLibBase.Username
                password = SdmcUbusLibBase.Password

                self.iptv = IptvManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_get_igmp_snooping(self):
        """
        【功能描述】
        获取 IGMP Snooping（组播侦听）功能启用状态。

        【入参】
        无

        【返回值】
        {'Enable': True}

        【示例】
        Example:
        |  Ubus_get_igmp_snooping  |

        """
        self._Ubus_iptv_Init()
        ret = self.iptv.get_igmp_snooping()
        return ret

    def Ubus_get_igmp_proxy(self):
       """
       【功能描述】
       获取 IGMP Proxy（组播代理）相关配置信息，包括启用状态、上行接口、健壮性参数及各类查询间隔时间。

       【入参】
       无

       【返回值】
       {'Enable': False, 'Uplink': '', 'Robustness': 2, 'QueryInterval': 30, 'QueryResponseInterval': 25, 'LastMemberQueryInterval': 3, 'UnsolicitedReportInterval': 1, 'MinRobustness': 1, 'MaxRobustness': 7, 'MinQueryInterval': 30, 'MaxQueryInterval': 300, 'MinQueryResponseInterval': 1, 'MaxQueryResponseInterval': 25, 'MinLastListenerQueryInterval': 1, 'MaxLastListenerQueryInterval': 7, 'MinUnsolicitedReportInterval': 1, 'MaxUnsolicitedReportInterval': 60}


       【示例】
       Example:
       |  Ubus_get_igmp_proxy  |

       """
       self._Ubus_iptv_Init()
       ret = self.iptv.get_igmp_proxy()
       return ret

    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        return names

    def run_keyword(self, name, args, kwargs=None):
        """
        """
        method_name = name
        if hasattr(self, method_name):
            return getattr(self, method_name)(*args, **kwargs)

    def get_keyword_documentation(self, name):
        """
        """
        method_name = name.replace(" ", "_")
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            doc = inspect.getdoc(method)
            return doc if doc else "No documentation provided."

    def get_keyword_arguments(self, name):
        """返回关键字参数列表"""
        method_name = name
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            sig = inspect.signature(method)

            args = []
            for p in sig.parameters.values():
                if p.name == "self":
                    continue
                if p.kind == p.VAR_POSITIONAL:
                    args.append("*" + p.name)  # *args
                elif p.kind == p.VAR_KEYWORD:
                    args.append("**" + p.name)  # **kwargs
                elif p.default is inspect._empty:
                    args.append(p.name)  # 必填参数
                else:
                    args.append(f"{p.name}={p.default!r}")  # 带默认值参数
            return args



if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    # logging.getLogger().setLevel(logging.DEBUG)
    # logging.basicConfig(filename='example.log',level=logging.INFO)

    print("start ---------------------------\n")
    
    # 创建实例
    sdmc_iptv_lib = SdmcIPTVLib()

    base = SdmcUbusLibBase()
    base.Ubus_Login("root", "t*hEQ#BHu7z%3n")
    
    print("\nfinish ------------------")
    # os.system("pause")

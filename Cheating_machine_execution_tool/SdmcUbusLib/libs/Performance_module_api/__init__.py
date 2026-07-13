"""
设备Status相关api
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.status import StatusManager
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcPerformanceLib(object):
    """
    测试库 demo for class
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

    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        return names

    def _Ubus_Status_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.status = StatusManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_Status_get_device_info(self):
        """
        功能描述：\n
        获取Status中的device info

        返回值：\n
        返回一个字典，为所有device info中的各个信息

        {'Model': 'NPE3039GB', 'MAC Address': '2C:EC:F7:BB:4C:56', 'Hardware Version': 'V1.0', 'Software Version': 'S13.4B.01.001', 'Uptime': '1 Day 02 Hour 14 Minute 28 Seconds', 'System Time': '2025/07/30 05:52:06', 'Firmware Time': 'Thu Jul 10 04:15:44 UTC 2025', 'Device SN': '24C0010191000078', 'CPU Usage': '9 %', 'Memory Usage': '59 %', 'Temperature': '61 ℃'}

        Example:
        | ${ret} |  Ubus_Status_get_device_info  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        device_info = Status_info.get_device_info()
        if device_info == 0:
            raise ValueError("获取Device info失败")
        return device_info

    def Ubus_Status_get_wan_info(self):
        """
        功能描述：\n
        获取status中的wan的详细信息

        返回值：\n
        以字典的形式返回所有wan的信息
        {
            "2": {
                "Name": "3_INTERNET_R_VID_200",
                "MAC": "2C:EC:F7:BB:4C:57",
                "IPv4": "172.18.18.54",
                "IPv4Gateway": "172.18.18.1",
                "Status": "Up",
                "Uptime": "0 Day 00 Hour 11 Minute 57 Seconds",
                "PrimaryDNSv4": "202.96.134.133",
                "SecondaryDNSv4": "152.152.152.222"
            },
            "3": {
                "Name": "4_TR069_R_VID_50",
                "MAC": "2C:EC:F7:BB:4C:58",
                "IPv4": "10.50.100.113",
                "IPv4Gateway": "10.50.100.1",
                "Status": "Up",
                "Uptime": "0 Day 00 Hour 07 Minute 46 Seconds",
                "PrimaryDNSv4": "152.152.152.222",
                "SecondaryDNSv4": ""
            }
        }

        Example:
        | ${ret} |  Ubus_Status_get_wan_info  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        wan_info = Status_info.get_wan_info()
        if wan_info == 0:
            raise ValueError("获取WAN info失败")
        return wan_info

    def Ubus_Status_manage_wan(self, method, wan_index):
        """
        功能描述：\n
        设置wan的release和renew

        入参：\n
        method：操作类型，"Release" 或 "Renew" \n
        wan_index: WAN 接口索引号

        Example:
        |  Ubus_Status_get_wan_info  | Release | 2 |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        manage_wan = Status_info.manage_wan(method, wan_index)
        if manage_wan == 0:
            raise ValueError("设置release renew失败")

    def Ubus_Status_get_wan_index(self, wan_name):
        """
        功能描述：\n
        获取wan index

        入参：\n
        wan_name:WAN的名称，可以通过 Ubus_Status_get_wan_info 获取

        返回值：\n
        wan_index: wan 序号

        Example:
        | ${ret} |  Ubus_Status_get_wan_index  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        wan_index = Status_info.get_interface_instance_by_name(wan_name)
        if wan_index == False:
            raise ValueError("获取wan_index失败")
        return wan_index


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
        """返回关键字的参数列表"""
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
                    args.append(f"{p.name}={p.default!r}")  # 带默认值的参数
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

    print("\nfinish ------------------")
    # os.system("pause")



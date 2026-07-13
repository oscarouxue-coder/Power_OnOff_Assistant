"""
lan模块
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.Network_module_api.Lan_moudle_api.Lan import LanManager
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcLanLib(object):
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

    def _Ubus_Network_LAN_Init(self):
        """
        功能描述：

        参数： \n

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:

        """
        n_ret = ERR_FAIL

        parsed_url = urlparse(SdmcUbusLibBase.Url)
        ip = parsed_url.hostname

        username = SdmcUbusLibBase.Username
        password = SdmcUbusLibBase.Password

        self.lan_manager = LanManager(ip, username, password)

        n_ret = ERR_SUCCESS

        return n_ret

    def Ubus_Network_LAN_Get(self):
        """
        功能描述：获取 LAN 配置

        参数： \n

        返回值：
        {'Address': '192.168.29.1', 'DHCPForwardInterface': None, 'DHCPMode': 'Server', 'DHCPRelayServer': None, 'DHCPStaticIP': {}, 'DHCP_Enable': True, 'DHCPv6ServerEnable': True, 'DHCPv6State': 'stateless', 'End_IP': '192.168.29.249', 'Ipv6StaticDNSEable': False, 'Lease_Time_Minutes': 1440, 'PreferredLifeTime': 12, 'RAEable': True, 'RAFlag': {'EnableManagedFlag': False, 'EnableotherFlag': True}, 'SLAACEnable': True, 'Start_IP': '192.168.29.100', 'Static_DNS_Enable': False, 'SubnetMask': '255.255.255.0', 'ULAPrefix': 'fdea:e111:ce6b::/48', 'ValidLifeTime': 12}

        Example:
        | ${lan_config} |  Ubus_Network_LAN_Get |

        """
        info = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.Network_LAN_Get()

        return info

    def Ubus_Network_LAN_Get_IPv4_LAN_IP(self):
        """
        【功能描述】
            获取LAN IP地址
        【入参】
            \n
        【返回值】
            {'Address': '192.168.29.1', 'SubnetMask': '255.255.255.0'}
        【示例】
        Example:
        """
        info = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.get_host_info()

        return info


    def Ubus_Network_LAN_Set_IPv4_LAN_IP(self, ip_address="192.168.29.1", subnet_mask="255.255.255.0"):
        """
        功能描述： 设置IPv4的Host IP和子网掩码

        参数：\n
            ip_address：网关IP，默认192.168.29.1
            subnet_mask： 子网掩码，默认255.255.255.0

        返回值：0 成功，1 失败
        Example:
        | ${ret} |  Ubus_Network_Lan_Set_IPv4_Host  | ip_address="192.168.29.1" | subnet_mask="255.255.255.0"
        """
        self._Ubus_Network_LAN_Init()
        ret = self.lan_manager.set_ipv4_host(ip_address, subnet_mask)

        return ret

    def Ubus_Network_LAN_Get_DHCPv4_Service(self):
        """
        【功能描述】
            获取 LAN DHCP 地址池 租期等消息
        【入参】
            \n
        【返回值】
            {'DHCP_Enable': True, 'Start_IP': '192.168.29.2', 'End_IP': '192.168.29.254', 'Lease_Time_Minutes': 1440, 'Static_DNS_Enable': False, 'DHCPStaticIP': {}}
        【示例】
        Example:
        """
        info = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.get_Dhcpv4Service_info()

        return info

    def Ubus_Network_LAN_Set_DHCPv4_Service(self, enable=1, min_address="192.168.29.2", max_address="192.168.29.249",
                                            lease_time=86400, dns_enable=1, dns_servers="", **kwargs):
        """
        【功能描述】
            设置LAN侧IPV4的配置
        【入参】
            param enable: int 是否开启dhcp server （默认值=1）
            param min_address: str 地址池的开始（默认值=192.168.29.2）
            param max_address: str 地址池的结束（默认值=192.168.29.254）
            param lease_time: int 地址租期（默认值=86400）
            param dns_enable: int 是否手动配置DNS（默认值=1）
            param dns_servers：str  手动配置的DNS
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """
        self._Ubus_Network_LAN_Init()
        self.lan_manager.set_dhcpv4_service(enable=enable, min_address=min_address, max_address=max_address,
                                            lease_time=lease_time, dns_enable=dns_enable, dns_servers=dns_servers,
                                            **kwargs)
        return ERR_SUCCESS

    def Ubus_Network_LAN_Get_DHCPv4_Relay(self):
        """
        【功能描述】
            获取DHCP中继配置信息
        【入参】
            无
        【返回值】
            返回DHCP中继配置信息
        【示例】
        Example:
            {
                "DHCPMode": "relay",
                "DHCPRelayServer": "192.168.60.5",
                "DHCPForwardInterface": "3_INTERNET_R_VID_171"
            }
        """
        info = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.get_Dhcpv4Relay_info()

        return info

    def Ubus_Network_LAN_Set_DHCPv4_Relay(self, enable=1, dhcp_server_ip="None", interface_index="None", dns_servers=""):
        """
        【功能描述】
            设置LAN侧IPV4 中继功能的配置
        【入参】
            param enable: int 是否开启中继功能 （默认值=1）
            param dhcp_server_ip: str dhcp服务器IP（默认值=None）
            param interface_index: str wan的名称的index （默认值=None），"3"
            param dns_servers: str 手动配置的DNS（默认值=""）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        if (enable):
            enableUbus = True
        else:
            enableUbus = False

        ret = lan_manager.set_dhcpv4_relay(enableUbus, dhcp_server_ip, interface_index, dns_servers)

        return ret

    def Ubus_Network_LAN_Set_DHCPv4_Static_IP(self, method="add", index=1, macaddr="", ipaddr="192.168.29.1"):
        """
        【功能描述】
            设置LAN侧根据mac地址分配给下挂设备的IP地址
        【入参】
            param method: str 设置的方法，‘add’、’del‘、’modify‘（默认值=add）
            param index: int 选择第几条记录做操作（默认值=1）
            param macaddr: str 设置下挂设备的mac地址（默认值=None）
            param ipaddr: str 设置下挂设备的IP地址（默认值=None）

        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """

        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.set_dhcpv4_static_ip(method, index, macaddr, ipaddr)

        return ret

    def Ubus_Network_LAN_Set_DHCPv6_Service(self, mode="stateless", enable=1, **kwargs):
        """
        功能描述：设置 LAN IPv6 DHCP Service

        参数： \n
            mode stateless，stateful
            enable  1 表示  True;  0 表示 False
            kwargs,可变参数lease_time，min_id，max_id，参数=值
        返回值：

        Example:

        """
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        if (enable):
            enableUbus = True
        else:
            enableUbus = False

        ret = lan_manager.set_dhcpv6_service(mode, enableUbus, **kwargs)

        return ret

    def Ubus_Network_LAN_Set_DHCPv6_Static_DNS(self, method="add", primary_dns="2001:4860:4860::8888",
                                               secondary_dns=""):
        """
        配置DHCPv6静态DNS设置

        Args:
            method: str - 操作类型 'add', 'modify' 或 'del'
            primary_dns: str - 主DNS服务器IPv6地址 (默认: '2001:4860:4860::8888')
            secondary_dns: str - 辅DNS服务器IPv6地址，可为None表示不设置 (默认: None)
        """
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.set_dhcpv6_static_dns(method, primary_dns, secondary_dns)

        return ret

    def Ubus_Network_LAN_Set_DHCPv6_RA_Service(self, managed_flag="1", other_config_flag="1", ra_enable="1",
                                               preferred_lifetime_hours=12, valid_lifetime_hours=24, raslaac=1):
        """
        【功能描述】
            设置LAN侧IPV6的RA参数
        【入参】
            param managed_flag: str 控制RA报文中的M flag（默认值=1）
            param other_config_flag: str 控制RA报文中的 O flag（默认值=1）
            param ra_enable: str 是否启用RA（默认值=1）
            param preferred_lifetime_hours: int 设置IPV6的首选寿命（默认值=12）
            param valid_lifetime_hours: int 设置IPV6的有效寿命（默认值=24）
            param raslaac: int 控制RA报文中的A flag （默认值=1）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        if (raslaac):
            raslaacUbus = True
        else:
            raslaacUbus = False

        ret = lan_manager.set_dhcpv6_RA_service(managed_flag, other_config_flag, ra_enable,
                                                preferred_lifetime_hours, valid_lifetime_hours, raslaacUbus)

        return ret

    def Ubus_Network_LAN_Set_ula_prefix(self, ULAPrefix="fdea:e111:ce6b::/48"):
        """
        【功能描述】
            设置LAN侧IPV6的前缀
        【入参】
            param ULAPrefix: str 要设置的前缀（默认值=fdea:e111:ce6b::/48）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.set_ula_prefix(ULAPrefix)

        return ret

    def Ubus_Network_LAN_Get_WorkMode(self):
        """
        function:
            获取LAN口模式
        Args:
            无
        return:
            返回所有LAN口对应的模式，形式 LAN1:router
        """

        info = {}

        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.Network_LANPortWorkMode_Get()

        return info

    def Ubus_Network_LAN_Set_WorkMode(self, lan_port=1, lan_mode="router"):
        """
        function:
            配置LAN口模式
        Args:
            lan_port: int - LAN口序号，默认为 1
            lan_mode: str - LAN口模式 ‘router’或者‘bridge’，默认为‘router’
        return:
            返回ubus执行结果
        """

        ret = {}

        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.Network_LANPortWorkMode_Set(lan_port, lan_mode)

        return ret

    def Ubus_Network_LAN_Get_Status(self):
        """
        【功能描述】
            获取LAN口使能状态
        【入参】
            无
        【返回值】
            返回所有LAN口状态
        【示例】
        Example:
            {
                "LAN1": "Enable",
                "LAN2": "Enable",
                "LAN3": "Enable",
                "LAN4": "Enable",
                "LAN5": "Enable"
            }
        """

        info = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.Network_LANPortStatus_Get()

        return info

    def Ubus_Network_LAN_Set_Status(self, lan_port=1, lan_enable="true"):
        """
        【功能描述】
            设置LAN口使能状态
        【入参】
            param lan_port: int - LAN口序号（默认值=1）
            param lan_enable: str - LAN口是否使能 'true’或者’false‘（默认值=true）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """

        ret = {}
        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.Network_LANPortStatus_Set(lan_port, lan_enable)

        return ret

    def Ubus_Network_LAN_Get_LinkMode(self):
        """
        【功能描述】
            获取LAN口速率和双工模式
        【入参】
            无
        【返回值】
            返回所有LAN口速率和双工模式
        【示例】
        Example:
            {
                "LAN1": {
                    "MaxBitRate": 1000,
                    "DuplexMode": "Auto"
                }
            }
        """

        info = {}

        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        info = lan_manager.Network_LANPortLinkMode_Get()

        return info

    def Ubus_Network_LAN_Set_LinkMode(self, lan_port=1, lan_speed=1000, lan_duplexmode="Auto"):
        """
        【功能描述】
            设置LAN口速率和双工模式
        【入参】
            param lan_port: int - LAN口序号（默认值=1）
            param lan_speed: int - LAN口速率 （默认值=1000）
            param lan_duplexmode: str - LAN口双工模式 ‘Auto’、‘Half’、‘Full’ （默认值=Auto）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """

        ret = {}

        self._Ubus_Network_LAN_Init()

        lan_manager = self.lan_manager

        ret = lan_manager.Network_LANPortLinkMode_Set(lan_port, lan_speed, lan_duplexmode)

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



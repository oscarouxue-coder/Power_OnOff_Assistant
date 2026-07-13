"""
wan 模块
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.Network_module_api.Wan_moudle_api.multiWan import multiWanManager
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcWanLib(object):
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

    def _Ubus_Network_WAN_Init(self):
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

                self.wan_manager = multiWanManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_Network_WAN_Delete(self, Connection_Name_or_Index):
        """
        功能描述：删除 WAN

        参数： \n
        Connection_Name_or_Index     Connection_Name 或者 Connection_Name的序号

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:
        | ${ret} |  Ubus_Network_WAN_Delete |  5_IPTV_R_VID_123 |
        | ${ret} |  Ubus_Network_WAN_Delete |  5 |

        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager

        n_ret = wan_manager.ubus_wan_delete(Connection_Name_or_Index)

        return n_ret

    def Ubus_Network_WAN_Get(self, Connection_Name):
        """
        功能描述：获取 WAN 配置

        参数： \n
        Connection_Name   当前 wan 的 Connection Name

        返回值：
        {'Connection Name': '3_TR069_INTERNET_R_VID_200', 'Enable': True, 'ServiceType': 'TR069_INTERNET', 'MTU': 1500, 'PortBind': None, 'WANType': 'IPoE', 'PPPoE': {}, 'VLANID': 200, 'VLANPriority': 0, 'IPProtocol': 'IPv4', 'IPv4Info': {'AddressingType': 'Dynamic', 'Option60VendorID': '', 'Option121Enable': False, 'Option120Enable': False}, 'IPv6Info': {}, 'Index': 3, 'Mode': 'Router', 'NAT': True, 'MSS': 'Auto'}


        Example:
        | ${wan_config} |  Ubus_Network_WAN_Get  | 3_TR069_INTERNET_R_VID_200 |

        """
        info = {}
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager

        info = wan_manager.ubus_wan_get(Connection_Name)

        return info

    def Ubus_Network_WAN_Get_Connection_Names(self):
        """
        功能描述：获取 WAN 配置 (Connection Name List)

        返回值：Connection Name List
        eg  ['3_TR069_INTERNET_R_VID_200', '4_VOICE_R_VID_335', '5_IPTV_R_VID_123']

        Example:
        | ${names} |  Ubus_Network_WAN_Get_Connection_Names  |

        """
        names = []

        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        names = wan_manager.ubus_wan_get_connection_names()

        return names

    def Ubus_Network_WAN_Set(self, wan_config):
        """
        功能描述：设置 WAN 页面功能

        参数： \n
        wan_config          wan 配置, 字典 形式

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:
        | &{Iptv_config} |  create dictionary  | Method=add | VLAN=123 | Mode=router | ServiceType=IPTV | PortBind=0  | IPoE=1  | IPv4Type=Dynamic | IPProtocol=IPv4 | MulticastVLANID=222  |
        | ${ret} |  Ubus_Network_WAN_Set |  ${Iptv_config}  |

        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        ret = wan_manager.ubus_wan_get(wan_config)

        return ret

    def Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4(self, vlan_id, wan_server_type="INTERNET", **kwargs):

        """
        【功能描述】：创建DHCP IPv4 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0
        
        Option60Vendor="": DHCP Option60 的厂商字符串，默认空字符串
        
        Option120Enable=0: 启 DHCP Option120，默认0（关闭），1为开启
        
        Option121Enable=0: 启 DHCP Option121，默认0（关闭），1为开启

        【返回值】
       0: 成功
        1：失败

        Example:

        1、vlan:200,type:INTERNET;绑定Lan 1端口
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1 |

        2、vlan:200,type:INTERNET;绑定Lan 1和Lan 4端口和2.4GWiFi，启用Option120
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1&&8&&256 | | | 1 |

        3、vlan:200,type:INTERNET;绑定Lan 1和Lan 4端口和2.4GWiFi，设置Option60厂商
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1&&8&&256 | | | | myvendor |

        4、vlan:200,type:INTERNET;绑定Lan 1和Lan 4端口和2.4GWiFi，启用Option120和Option121
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1&&8&&256 | | | 1 | 1 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoe_dhcp_ipv4(vlan_id=vlan_id, wan_server_type=wan_server_type, **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_Static_IPv4(self, vlan_id, wan_server_type="INTERNET",
                                                     ipv4_address='172.18.18.43',
                                                     ipv4_subnetMask='255.255.255.0',
                                                     ipv4_gateway='172.18.18.1', ipv4_primary_DNS='202.96.134.133',
                                                     ipv4_second_DNS='8.8.8.8', lan_bind_port=0,
                                                     mtu=1500,
                                                     vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创建 DHCP 静态 IPv4 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        ipv4_address : IPv4 静态IP地址，默认 172.18.18.43，对应Vlan 200

        ipv4_subnetMask : IPv4 静态子网掩码，默认 255.255.255.0

        ipv4_gatewaty  : IPv4 静态网关，默认 172.18.18.1

        ipv4_primary_DNS : IPv4  主DNS，默认 202.96.134.133

        ipv4_sencond_DNS : IPv4 备DNS，默认 8.8.8.8

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_Static_IPv4 | 200 | 3 | 172.18.18.43 | 255.255.255.0 | 172.18.18.1 | 202.96.134.133 | 8.8.8.8 | 1&&2 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoe_static_ipv4(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                               ipv4_address=ipv4_address,
                                                               ipv4_subnetMask=ipv4_subnetMask,
                                                               ipv4_gateway=ipv4_gateway,
                                                               ipv4_primary_DNS=ipv4_primary_DNS,
                                                               ipv4_second_DNS=ipv4_second_DNS,
                                                               lan_bind_port=lan_bind_port, mtu=mtu,
                                                               vlan_priority=vlan_priority, multicastvlan_id=multicastvlan_id)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_Static_IPv6(self, vlan_id, wan_server_type="INTERNET",
                                                     ipv6_address='2001:171:101::24',
                                                     ipv6_perfix='2001:171:111:10::/64',
                                                     ipv6_gateway='2001:171:101::10', ipv6_primary_DNS='240E:1F:1::1',
                                                     ipv6_second_DNS=' ', lan_bind_port=0,
                                                     mtu=1500,
                                                     vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创建DHCP 静态 IPv6 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        ipv6_address :  IPv6 静态IP地址，默认 2001:171:101::24，对应vlan171

        ipv6_perfix ： IPV6 前缀，默认 2001:171:111:10::/64 ，对应vlan 171

        ipv6_gatewaty ： IPV6 网关，默认 2001:171:101::10，对应 171

        ipv6_primary_DNS ：IPV6 主DNS，默认  240E:1F:1::1

        ipv6_sencond_DNS : IPV6 备DNS，默认 空

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_Static_IPv6 | 171 | 3 | 2001:171:101::24 | 2001:171:111:10::/64 | 2001:171:101::10 | 240E:1F:1::1 | lan_bind_port=1&&2 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoe_static_ipv6(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                               ipv6_address=ipv6_address, ipv6_perfix=ipv6_perfix,
                                                               ipv6_gateway=ipv6_gateway,
                                                               ipv6_primary_DNS=ipv6_primary_DNS,
                                                               ipv6_second_DNS=ipv6_second_DNS,
                                                               lan_bind_port=lan_bind_port, mtu=mtu,
                                                               vlan_priority=vlan_priority, multicastvlan_id=multicastvlan_id)
        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv6_DHCPv6(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv6单栈 有状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv6 | 171 | 3 |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_set_router_ipoE_dhcp_ipv6_dhcpv6(vlan_id=vlan_id,
                                                                         wan_server_type=wan_server_type, **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv6_SLAAC(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv6单栈 无状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv6_SLAAC | 170 | 3 |
        """

        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoE_dhcp_ipv6_slaac(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                                   **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4IPv6_SLAAC(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv4&IPv6双栈 无状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4IPv6_SLAAC | 170 | 3 |
        """

        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoE_dhcp_ipv4ipv6_slaac(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                                       **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4IPv6_DHCPv6(self, vlan_id, wan_server_type, **kwargs):
        """
        【功能描述】：创建路由DHCP IPv4&IPv6双栈 有状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4IPv6_DHCPv6 | 171 | 3 |
        """

        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_ipoe_dhcp_ipv4_ipv6_dhcpv6(vlan_id=vlan_id,
                                                                         wan_server_type=wan_server_type, **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_PPPoE_IPv4(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由PPPoE IPv4 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        pppoe_username=111 : PPPoe 用户名，默认 1111

        pppoe_password=111 ： pppoe 密码，默认 111

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_PPPoE_IPv4 | 200 | 3 | 111 | 111 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_pppoe_ipv4(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                         **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_PPPoE_IPv6_DHCPv6(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv6单栈  pppoe  有状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        pppoe_username=111 : PPPoe 用户名，默认 1111

        pppoe_password=111 ： pppoe 密码，默认 111

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_PPPoE_IPv6_DHCPv6 | 171 | 3 | 111 | 111 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_pppoe_ipv6_dhcpv6(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                                **kwargs)
        return wan_set

    def Ubus_Network_WAN_Set_Router_PPPoE_IPv6_SLAAC(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv4IPv6 双栈  pppoe  无状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        pppoe_username=111 : PPPoe 用户名，默认 1111

        pppoe_password=111 ： pppoe 密码，默认 111

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_PPPoE_IPv4IPv6_DHCPv6 | 171 | 3 | 111 | 111 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_pppoe_ipv6_slaac(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                               **kwargs)
        return wan_set

    def Ubus_Network_WAN_Set_Router_PPPoE_IPv4IPv6_DHCPv6(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv4 IPv6双栈  pppoe  有状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        pppoe_username=111 : PPPoe 用户名，默认 1111

        pppoe_password=111 ： pppoe 密码，默认 111

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_PPPoE_IPv6_SLAAC | 171 | 3 | 111 | 111 |
        """
        self._Ubus_Network_WAN_Init()
        wan_manager = self.wan_manager
        wan_set = wan_manager.ubus_set_router_pppoe_ipv4ipv6_dhcpv6(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                                    **kwargs)
        return wan_set

    def Ubus_Network_WAN_Set_Router_PPPoE_IPv4IPv6_SLAAC(self, vlan_id, wan_server_type="INTERNET", **kwargs):
        """
        【功能描述】：创建路由DHCP IPv4IPv6 双栈  pppoe  无状态 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        pppoe_username=111 : PPPoe 用户名，默认 1111

        pppoe_password=111 ： pppoe 密码，默认 111

        DSLiteEnable=0 : DSLite 开关，默认0 关闭，1 打开

        PrefixDelegation=1 ： PrefixDelegation 开关，默认1 打开，0 关闭

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_PPPoE_IPv4IPv6_SLAAC | 171 | 3 | 111 | 111 |
        """

        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_set_router_pppoe_ipv4ipv6_slaac(vlan_id=vlan_id,
                                                                        wan_server_type=wan_server_type, **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Bridge(self, vlan_id, wan_server_type="IPTV", lan_bind_port=1, **kwargs):
        """
        【功能描述】：创建桥接 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认IPTV，对应IPTV，另外 INTERNET / OTHER/ IPTV

        lan_bind_port=1 : 绑定的lan口，默认1，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        multicastvlan_id : 跨组播VLAN ID ，默认为空


        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Bridge | 600 |

        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_set_bridge(vlan_id=vlan_id, wan_server_type=wan_server_type,
                                                   lan_bind_port=lan_bind_port, **kwargs)

        return wan_set

    def Ubus_Network_WAN_Set_Router_IPoE_Static_IPv4IPv6(self, vlan_id, wan_server_type="INTERNET",
                                                         ipv4_address='172.18.18.43',
                                                         ipv4_subnetMask='255.255.255.0',
                                                         ipv4_gateway='172.18.18.1',
                                                         ipv4_primary_DNS='202.96.134.133',
                                                         ipv4_second_DNS='8.8.8.8',
                                                         ipv6_address='2001:171:101::24',
                                                         ipv6_perfix='2001:171:111:10::/64',
                                                         ipv6_gateway='2001:171:101::10',
                                                         ipv6_primary_DNS='240E:1F:1::1',
                                                         ipv6_second_DNS=' ', lan_bind_port=0,
                                                         mtu=1500,
                                                         vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创建DHCP 静态 IPv6 WAN

        【入参】
        vlan_id  ： vlan id

        wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        ipv4_address : IPv4 静态IP地址，默认 172.18.18.43，对应Vlan 200

        ipv4_subnetMask : IPv4 静态子网掩码，默认 255.255.255.0

        ipv4_gatewaty  : IPv4 静态网关，默认 172.18.18.1

        ipv4_primary_DNS : IPv4  主DNS，默认 202.96.134.133

        ipv4_sencond_DNS : IPv4 备DNS，默认 8.8.8.8

        ipv6_address :  IPv6 静态IP地址，默认 2001:171:101::24，对应vlan171

        ipv6_perfix ： IPV6 前缀，默认 2001:171:111:10::/64 ，对应vlan 171

        ipv6_gatewaty ： IPV6 网关，默认 2001:171:101::10，对应 171

        ipv6_primary_DNS ：IPV6 主DNS，默认  240E:1F:1::1

        ipv6_sencond_DNS : IPV6 备DNS，默认 空

        lan_bind_port=0 : 绑定的lan口，默认0，0表示不绑定；当输入1&&4 ，会绑定1和3口；当输入1&&8，会绑定Lan1和Lan4;
        各个端口对应的数字：
                "LAN1": 1；
                "LAN2": 2；
                "LAN3": 4；
                "LAN4": 8；
                "LAN5": 16；
                "LAN6": 32；
                "LAN7": 64；
                "LAN8": 128；
                "2.4Gwifi": 256；
                "2.4Gguest": 512；
                "5Gwifi": 2048；
                "5Gguest": 4096；

        mtu=1500 ：mtu 值，默认1500

        vlan_priority=0 ： vlan 优先级 0-7，默认0

        【返回值】
       0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_Set_Router_IPoE_Static_IPv4IPv6 | 171 | 3 | 172.18.18.43 | 255.255.255.0 | 172.18.18.1 | 202.96.134.133 | 8.8.8.8 | 2001:171:101::24 | 2001:171:111:10::/64 | 2001:171:101::10 | 240E:1F:1::1 | lan_bind_port=1&&2 |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_set_router_ipoe_static_ipv4ipv6(vlan_id=vlan_id,
                                                                        wan_server_type=wan_server_type,
                                                                        ipv4_address=ipv4_address,
                                                                        ipv4_subnetMask=ipv4_subnetMask,
                                                                        ipv4_gateway=ipv4_gateway,
                                                                        ipv4_primary_DNS=ipv4_primary_DNS,
                                                                        ipv4_second_DNS=ipv4_second_DNS,
                                                                        ipv6_address=ipv6_address,
                                                                        ipv6_perfix=ipv6_perfix,
                                                                        ipv6_gateway=ipv6_gateway,
                                                                        ipv6_primary_DNS=ipv6_primary_DNS,
                                                                        ipv6_second_DNS=ipv6_second_DNS,
                                                                        lan_bind_port=lan_bind_port, mtu=mtu,
                                                                        vlan_priority=vlan_priority, multicastvlan_id=multicastvlan_id)

        return wan_set

    def Ubus_Network_WAN_delete_all(self):
        """
        【功能描述】： 删除所有存在的WAN

        【返回值】
        0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_delete_all |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_wan_delete_all()

        return wan_set

    def Ubus_Network_WAN_delete_specify_type_WAN(self, wan_type):
        """
        【功能描述】：删除指定的类型的WAN

        【入参】\n
        wan_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        【返回值】
        0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_delete_specify_type_WAN | 3 |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_delete_specify_type_wan(wan_type)

        return wan_set

    def Ubus_Network_WAN_delete_specify(self, wan_type, wan_mode, vlan_id):
        """
        【功能描述】：删除指定的类型的WAN

        【入参】\n
        wan_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV

        wan_mode :  WAN模式，Bridge：B， Router : R

        vlan_id : vlan ID

        【返回值】
        0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_delete_specify | 3 | R | 200 |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_delete_specify_wan(wan_type=wan_type, wan_mode=wan_mode, vlan_id=vlan_id)

    def Ubus_Network_WAN_Modify_NAT(self, wan_name, enable):
        """
        【功能描述】：修改WAN的NAT配置

        【入参】\n
        wan_name : WAN连接名称，如 "3_TR069_INTERNET_R_VID_200"
        enable : NAT启用状态，"1"表示启用，"0"表示禁用

        【返回值】
        0: 成功
        1：失败

        Example:
            | ${ret} |  Ubus_Network_WAN_Modify_NAT | 3_INTERNET_R_VID_200 | 1 |
            | ${ret} |  Ubus_Network_WAN_Modify_NAT | 3_INTERNET_R_VID_200 | 0 |
        """
        self._Ubus_Network_WAN_Init()
        wan_set = self.wan_manager.ubus_wan_modify_nat(wan_name, enable)

        return wan_set
    
    def Ubus_Network_get_wan_config(self):
        self._Ubus_Network_WAN_Init()
        ret = self.wan_manager.get_wan_parameters_history()

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
    base = SdmcUbusLibBase()
    base.Ubus_Login("sdmc", "1234")
    wan = SdmcWanLib()
    wan.Ubus_Network_WAN_delete_specify("TR069", "R", "200")
    print(wan.Ubus_Network_get_wan_config())
    wan.Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4(wan_server_type="TR069", vlan_id="200")
    print(wan.Ubus_Network_get_wan_config())
    wan.Ubus_Network_WAN_Modify_NAT("3_TR069_R_VID_200", "0")
    print(wan.Ubus_Network_get_wan_config())
    base.Ubus_Logout()

    print("\nfinish ------------------")
    # os.system("pause")



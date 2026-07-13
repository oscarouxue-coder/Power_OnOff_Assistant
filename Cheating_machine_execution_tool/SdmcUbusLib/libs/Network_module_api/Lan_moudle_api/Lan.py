import json
import binascii

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log

class LanManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_host_info(self):
        """
        【功能描述】
            获取当前br-lan的IP和掩码
        【入参】
            无
        【返回值】
            返回当前br-lan的IP和掩码
        【示例】
        Example:
            host = {
                "Address": "192.168.29.1",
                "SubnetMask": "255.255.255.0"
            }
        """

        params = {
            "path": "Device.IP.Interface.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        target_interface = next(
            (iface for iface in data.get('Interface', [])
             if iface.get(f'{VENDOR_PREFIX}Instance') == 1),
            None
        )
        host_info = target_interface.get("IPv4Address", [])
        host_ip_address = host_info[0].get("IPAddress")
        host_subnet_mask = host_info[0].get("SubnetMask")

        host = {
            "Address": host_ip_address,
            "SubnetMask": host_subnet_mask
        }

        return host

    def hex_to_ipv6(self, hex_ascii):
        bytes_data = binascii.unhexlify(hex_ascii)
        ipv6_str = bytes_data.decode('ascii')
        return ipv6_str

    def get_Dhcpv4Service_info(self):
        """
        【功能描述】
            获取当前的LAN的配置
        【入参】
            无
        【返回值】
            返回当前LAN的配置
        【示例】
        Example:
            {
                "DHCP_Enable": true,
                "Start_IP": "192.168.29.2",
                "End_IP": "192.168.29.254",
                "Lease_Time_Minutes": 1440,
                "Static_DNS_Enable": true,
                "DHCPStaticIP": {
                    "F8:E4:3B:8D:F9:ED": "192.168.29.66"
                },
                "Primary_IPv4_DNS_Server": "3.3.3.3"
            }
        """

        params = {
            "path": "Device.DHCPv4.Server.Pool.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("Pool", [])
        active_pool = next((p for p in data if p.get("Enable") is True), None)

        dhcp_enable = active_pool.get("Enable")
        start_ip_addr = active_pool.get("MinAddress")
        end_ip_addr = active_pool.get("MaxAddress")
        leasetime = int(active_pool.get("LeaseTime") / 60)
        static_dns_enable = active_pool.get(f"{VENDOR_PREFIX}Enable_Static_DNS")
        DHCPStaticIP_data = active_pool.get("StaticAddress", None)
        DHCPStaticIP = {}
        DHCPStaticIPW_Mac = None
        DHCPStaticIPW_Ip = None
        DHCPStaticIPW_Instance = None
        if DHCPStaticIP_data:
            DHCPStaticIP = {entry["Chaddr"]: entry["Yiaddr"] for entry in DHCPStaticIP_data}
            DHCPStaticIPW_Mac = [ entry["Chaddr"] for entry in DHCPStaticIP_data ]
            DHCPStaticIPW_Ip =  [ entry["Yiaddr"] for entry in DHCPStaticIP_data ]
            DHCPStaticIPW_Instance =  [ entry[ f'{VENDOR_PREFIX}Instance' ] for entry in DHCPStaticIP_data ]

        dhcpservice_info = {
            "DHCP_Enable": dhcp_enable,
            "Start_IP": start_ip_addr,
            "End_IP": end_ip_addr,
            "Lease_Time_Minutes": leasetime,
            "Static_DNS_Enable": static_dns_enable,
            "DHCPStaticIP": DHCPStaticIP,
            "DHCPStaticIPW_Mac": DHCPStaticIPW_Mac,
            "DHCPStaticIPW_Ip": DHCPStaticIPW_Ip,
            "DHCPStaticIPW_Instance": DHCPStaticIPW_Instance
        }

        if static_dns_enable:
            dns_servers = active_pool.get("DNSServers", "")
            dns_list = [dns.strip() for dns in dns_servers.split(",") if dns.strip()]
            if len(dns_list) > 0:
                dhcpservice_info["Primary_IPv4_DNS_Server"] = dns_list[0]
            if len(dns_list) > 1:
                dhcpservice_info["Secondary_IPv4_DNS_Server"] = dns_list[1]

        return dhcpservice_info

    def get_interface_info(self):
        params = {
            "path": "Device.IP.Interface.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        return data

    def get_Dhcpv4Relay_info(self):
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

        params = {
            "path": "Device.DHCPv4.Relay.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("Relay", [])
        relay_enable = data.get("Enable", [])
        DHCPServerIPAddress = None
        DHCPForwardInterface = None
        DHCPMode = "Server"
        if relay_enable:
            DHCPMode = "relay"
            forwarding_list = data.get("Forwarding", [])
            relay = next((p for p in forwarding_list if p.get("Enable") is True), None)
            Interface = relay.get("Interface")
            interface_index = int(Interface.rsplit('.', 1)[-1])
            DHCPServerIPAddress = relay.get("DHCPServerIPAddress")

            ip_interface_data = self.get_interface_info()
            for ip_interface in ip_interface_data.get('Interface', []):
                if ip_interface.get(f'{VENDOR_PREFIX}Instance', []) == interface_index:
                    DHCPForwardInterface = ip_interface.get('Name', [])

        dhcprelay_info = {
            "DHCPMode": DHCPMode,
            "DHCPRelayServer": DHCPServerIPAddress,
            "DHCPForwardInterface": DHCPForwardInterface
        }

        return dhcprelay_info

    def get_Dhcpv6Service_info(self):
        """
        【功能描述】
            获取LAN侧的IPv6的配置
        【入参】
            无
        【返回值】
            返回LAN侧的IPv6的配置
        【示例】
        Example:
            {
                "DHCPv6ServerEnable": true,
                "DHCPv6State": "stateful",
                "StartInterfaceID": "1:1:1:2",
                "EndInterfaceID": "1:1:1:254",
                "LeaseTime": 1,
                "Ipv6StaticDNSEable": false
            }
        """

        Dhcpv6Service_info = {}
        params = {
            "path": "Device.DHCPv6.Server.Pool.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("Pool", [])
        pool = data[0]

        Dhcpv6Service_info["DHCPv6ServerEnable"] = pool.get("Enable")

        DHCPv6State = pool.get("IANAEnable")
        DHCPv6State = "stateful" if DHCPv6State else "stateless"
        Dhcpv6Service_info["DHCPv6State"] = DHCPv6State
        if DHCPv6State == "stateful":
            Dhcpv6Service_info["StartInterfaceID"] = pool.get(f"{VENDOR_PREFIX}MinInterfaceID")
            Dhcpv6Service_info["EndInterfaceID"] = pool.get(f"{VENDOR_PREFIX}MaxInterfaceID")
            Dhcpv6Service_info["LeaseTime"] = int(int(pool.get(f"{VENDOR_PREFIX}IANALeaseTime")) / 60 / 60)

        params = {
            "path": "Device.RouterAdvertisement.InterfaceSetting.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("InterfaceSetting", [])
        InterfaceSetting = data[0]

        Ipv6StaticDNSEable = InterfaceSetting.get("OptionNumberOfEntries", 0) != 0
        Dhcpv6Service_info["Ipv6StaticDNSEable"] = Ipv6StaticDNSEable
        PrimaryDNSServer = None
        SecondaryDNSServer = None
        if Ipv6StaticDNSEable:
            options = InterfaceSetting.get("Option", [])
            if len(options) >= 1:
                Dhcpv6Service_info["PrimaryDNSServer"] = self.hex_to_ipv6(options[0].get("Value", ""))
            if len(options) >= 2:
                Dhcpv6Service_info["SecondaryDNSServer"] = self.hex_to_ipv6(options[1].get("Value", ""))
        return Dhcpv6Service_info

    def get_ipv6_RAService_info(self):
        """
        【功能描述】
            获取LAN侧IPV6的RA配置
        【入参】
            无
        【返回值】
            返回LAN侧IPV6的RA配置
        【示例】
        Example:
            {
                "RAEable": true,
                "SLAACEnable": true,
                "RAFlag": {
                    "EnableManagedFlag": true,
                    "EnableotherFlag": true
                },
                "PreferredLifeTime": 12,
                "ValidLifeTime": 24
            }
        """

        RAService_info = {}
        params = {
            "path": "Device.RouterAdvertisement.InterfaceSetting.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("InterfaceSetting", [])
        InterfaceSetting = data[0]

        RAService_info["RAEable"] = InterfaceSetting.get("Enable")
        RAService_info["SLAACEnable"] = InterfaceSetting.get(f"{VENDOR_PREFIX}RASlaac")

        AdvManagedFlag = InterfaceSetting.get("AdvManagedFlag")
        AdvOtherConfigFlag = InterfaceSetting.get("AdvOtherConfigFlag")
        RAFlag = {
            "EnableManagedFlag": AdvManagedFlag,
            "EnableotherFlag": AdvOtherConfigFlag
        }
        RAService_info["RAFlag"] = RAFlag

        RAService_info["PreferredLifeTime"] = int(
            InterfaceSetting.get(f"{VENDOR_PREFIX}AdvPreferredLifetime") / 60 / 60)
        RAService_info["ValidLifeTime"] = int(InterfaceSetting.get(f"{VENDOR_PREFIX}AdvValidLifetime") / 60 / 60)

        return RAService_info

    def get_ULA_Prefix(self):
        """
        【功能描述】
            获取LAN侧IPV6前缀信息
        【入参】
            无
        【返回值】
            返回LAN侧IPV6前缀信息
        【示例】
        Example:
            {
                "ULAPrefix": "FE80:45FE:74EF:777E::99/64"
            }
        """

        params = {
            "path": "Device.IP.ULAPrefix",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get("ULAPrefix", [])

        GlobalNetworkOption_info = {
            "ULAPrefix": data
        }

        return GlobalNetworkOption_info

    def set_ipv4_host(self, ip_address=None, subnet_mask=None):
        """
        【功能描述】
            设置LAN侧br-lan 的地址和掩码
        【入参】
            param ip_address: str 设置的IP地址（默认值=None）
            param subnet_mask: str 设置的掩码（默认值=None）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """

        default_params = {
            "paths": [
                {
                    "addr": "Device.IP.Interface.1.IPv4Address.1.",
                    "obj_path": {
                        "IPAddress": "192.168.29.1",
                        "SubnetMask": "255.255.255.0"
                    }
                }
            ]
        }
        obj_path = {
            "IPAddress": ip_address,
            "SubnetMask": subnet_mask
        }
        params = {
            "paths": [
                {
                    "addr": "Device.IP.Interface.1.IPv4Address.1.",
                    "obj_path": obj_path
                }
            ]
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
        return result

    def get_forwarding_config(self, ubus_response):

        if not isinstance(ubus_response, dict):
            print("not dic")
            return None

        forwarding = ubus_response.get("Forwarding")

        if not isinstance(forwarding, list):
            return None

        valid_configs = [
            cfg for cfg in forwarding
            if isinstance(cfg, dict) and cfg.get("Interface")
        ]

        return valid_configs if valid_configs else None
    def set_dhcpv4_service(self,enable=1, min_address="192.168.29.2", max_address="192.168.29.254",
                      lease_time=86400, dns_enable=1, dns_servers="", **kwargs):
        """
                【功能描述】
                    设置LAN侧IPV4的配置
                【入参】
                    param enable: int  是否开启dhcp server， 1 开启，0 关闭（默认值=1）
                    param min_address: str 地址池的开始（默认值=192.168.29.2）
                    param max_address: str 地址池的结束（默认值=192.168.29.254）
                    param lease_time: int 地址租期（默认值=86400）
                    param dns_enable: int 是否手动配置DNS，1 是，2 否（默认值=True）
                    param dns_servers：str  手动配置的DNS
                【返回值】
                    True  : 执行成功
                    False : 执行失败 或 抛出异常
                【示例】
                Example:

        """
        try:
            check_params = {"path": "Device.DHCPv4.Relay.Forwarding."}
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", check_params)
            ret = self.get_forwarding_config(result[1]) if result and len(result) > 1 else None
            del_params = {
                "path": "Device.DHCPv4.Relay.Forwarding.1.",
                "optional": {"proto": "web"}
            }
            relay_params = {
                "paths": [
                    {
                        "addr": "Device.DHCPv4.Relay.",
                        "obj_path": {"Enable": False}
                    }
                ]
            }

            if (enable):
                enableDhcpServer = True
            else:
                enableDhcpServer = False

            if dns_enable:
                dnsenable = True
            else:
                dnsenable = False

            if not ret == None:
                self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

            self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", relay_params)

            if not dnsenable:
                dns_servers = ""

            # default_params = {
            #     "paths": [
            #         {
            #             "addr": "Device.DHCPv4.Server.Pool.1.",
            #             "obj_path": {
            #                 "Enable": True,
            #                 "MinAddress": "192.168.29.3",
            #                 "MaxAddress": "192.168.29.254",
            #                 "LeaseTime": 86400,
            #                 "DNSServers": ""
            #             }
            #         }
            #     ]
            # }
            obj_path = {
                "Enable": enableDhcpServer,
                "MinAddress": min_address,
                "MaxAddress": max_address,
                "LeaseTime": lease_time,
                "DNSServers": dns_servers
            }
            params = {
                "paths": [
                    {
                        "addr": "Device.DHCPv4.Server.Pool.1.",
                        "obj_path": obj_path
                    }
                ]
            }
            ret = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

        except Exception as e:
            log.exception(str(e))
            desc = str(e)
            raise Exception(desc)

        return ret

    def set_dhcpv4_relay(self, enable=1, dhcp_server_ip=None, interface_index=None, dns_servers=""):
        """
                【功能描述】
                    设置LAN侧IPV4 中继功能的配置
                【入参】
                    param enable: int  是否开启中继功能， 1 开启 0关闭（默认值=1）
                    param dhcp_server_ip: str dhcp服务器IP（默认值=None）
                    param interface_index: int wan的 instance （默认值=None）
                    param dns_servers: str 手动配置的DNS（默认值=""）
                【返回值】
                    True  : 执行成功
                    False : 执行失败 或 抛出异常
                【示例】
                Example:

        """
        try:
            if (enable):
                enable_relay = True
            else:
                enable_relay = False

            dhcp_server_ip = "" if dhcp_server_ip is None or str(dhcp_server_ip).lower() == "none" else dhcp_server_ip
            interface_path = f"Device.IP.Interface.{interface_index}" if interface_index is not None and str(
                interface_index).lower() != "none" else ""

            check_params = {"path": "Device.DHCPv4.Relay.Forwarding."}
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", check_params)
            ret = self.get_forwarding_config(result[1]) if result and len(result) > 1 else None

            relay_params = {
                "paths": [
                    {
                        "addr": "Device.DHCPv4.Relay.",
                        "obj_path": {"Enable": enable_relay}
                    }
                ]
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", relay_params)

            add_params = {
                "path": "Device.DHCPv4.Relay.Forwarding.",
                "optional": {"proto": "web"}
            }

            if ret == None:
                print("add relay")
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

            interface_params = {
                "paths": [
                    {
                        "addr": "Device.DHCPv4.Relay.Forwarding.1.",
                        "obj_path": {
                            "DHCPServerIPAddress": dhcp_server_ip,
                            "Enable": "1",
                            "Interface": interface_path
                        },
                    }
                ]
            }
            ret = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", interface_params)
            
            # 设置DNS服务器配置到Device.DHCPv4.Server.Pool.1.
            dns_params = {
                "paths": [
                    {
                        "addr": "Device.DHCPv4.Server.Pool.1.",
                        "obj_path": {
                            "DNSServers": dns_servers
                        }
                    }
                ]
            }
            ret = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", dns_params)

        except Exception as e:
            log.exception(str(e))
            desc = str(e)
            raise Exception(desc)

        return ret

    def set_dhcpv4_static_ip(self, method="add", index=1, macaddr=None, ipaddr=None):
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

        result = {}
        base_path = f"Device.DHCPv4.Server.Pool.1.StaticAddress.{index}."

        if method == "add":
            add_params = {
                "path": "Device.DHCPv4.Server.Pool.1.StaticAddress.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

            set_params = {
                "paths": [
                    {
                        "addr": base_path,
                        "obj_path": {
                            "Chaddr": macaddr,
                            "Enable": "1",
                            "Yiaddr": ipaddr
                        },
                    }
                ]
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        elif method == "modify":
            set_params = {
                "paths": [
                    {
                        "addr": base_path,
                        "obj_path": {
                            "Chaddr": macaddr,
                            "Enable": "1",
                            "Yiaddr": ipaddr
                        },
                    }
                ]
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        elif method == "del":
            del_params = {
                "path": base_path,
                "optional": {
                    "proto": "web"
                }
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

    def set_dhcpv6_service(self, mode="stateless", enable=True, **kwargs):
        """
        功能描述：设置 LAN IPv6 DHCP Service

        参数： \n
            mode stateless，stateful
            enable  1 表示  True;  0 表示 False
            kwargs,可变参数lease_time，min_id，max_id，参数=值
        返回值：

        Example:

        """
        PARAM_MAPPING = {
            'lease_time': f'{VENDOR_PREFIX}IANALeaseTime',
            'max_id': f'{VENDOR_PREFIX}MaxInterfaceID',
            'min_id': f'{VENDOR_PREFIX}MinInterfaceID'
        }

        base_config = {
            "Enable": enable,
            "IANAEnable": mode.lower() == "stateful"
        }
        if 'lease_time' in kwargs:
            kwargs['lease_time'] = int(kwargs['lease_time']) * 3600
        mapped_params = {}
        for new_name, old_name in PARAM_MAPPING.items():
            if new_name in kwargs:
                mapped_params[old_name] = kwargs.pop(new_name)

        if mode.lower() == "stateful":
            stateful_params = {
                f"{VENDOR_PREFIX}IANALeaseTime": mapped_params.get(f"{VENDOR_PREFIX}IANALeaseTime", 43200),
                f"{VENDOR_PREFIX}MaxInterfaceID": mapped_params.get(f"{VENDOR_PREFIX}MaxInterfaceID", "0:0:0:254"),
                f"{VENDOR_PREFIX}MinInterfaceID": mapped_params.get(f"{VENDOR_PREFIX}MinInterfaceID", "0:0:0:2")
            }
            base_config.update(stateful_params)

        base_config.update(kwargs)

        params = {
            "paths": [{
                "addr": "Device.DHCPv6.Server.Pool.1.",
                "obj_path": base_config
            }]
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

    def set_dhcpv6_static_dns(self, method="add", primary_dns="2001:4860:4860::8888", secondary_dns=None):
        """
        配置DHCPv6静态DNS设置

        Args:
            method: str - 操作类型 'add', 'modify' 或 'del'
            primary_dns: str - 主DNS服务器IPv6地址 (默认: '2001:4860:4860::8888')
            secondary_dns: str - 辅DNS服务器IPv6地址，可为None表示不设置 (默认: None)
        """
        result = {}
        primary_hex = primary_dns.encode('utf-8').hex()
        primary_path = "Device.RouterAdvertisement.InterfaceSetting.1.Option.1."

        if method == "add":
            if primary_dns is not None:
                add_primary_params = {
                    "path": "Device.RouterAdvertisement.InterfaceSetting.1.Option.",
                    "optional": {"proto": "web"}
                }
                self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_primary_params)

            if secondary_dns is not None:
                add_secondary_params = {
                    "path": "Device.RouterAdvertisement.InterfaceSetting.1.Option.",
                    "optional": {"proto": "web"}
                }
                self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_secondary_params)

            if primary_dns is not None:
                primary_hex = primary_dns.encode('utf-8').hex()
                primary_path = "Device.RouterAdvertisement.InterfaceSetting.1.Option.1."

                set_primary = {
                    "paths": [{
                        "addr": primary_path,
                        "obj_path": {"Value": primary_hex}
                    }]
                }
                self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_primary)

            if secondary_dns is not None:
                secondary_hex = secondary_dns.encode('utf-8').hex()
                secondary_path = "Device.RouterAdvertisement.InterfaceSetting.1.Option.2."

                set_secondary = {
                    "paths": [{
                        "addr": secondary_path,
                        "obj_path": {"Value": secondary_hex}
                    }]
                }
                self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_secondary)

        elif method == "modify":
            set_primary = {
                "paths": [{
                    "addr": primary_path,
                    "obj_path": {"Value": primary_hex}
                }]
            }
            self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_primary)

            secondary_path = "Device.RouterAdvertisement.InterfaceSetting.1.Option.2."

            if secondary_dns:
                secondary_hex = secondary_dns.encode('utf-8').hex()
                set_secondary = {
                    "paths": [{
                        "addr": secondary_path,
                        "obj_path": {"Value": secondary_hex}
                    }]
                }
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_secondary)
            else:
                del_params = {"path": secondary_path}
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

        elif method == "del":

            dns_info = self.get_Dhcpv6Service_info()

            if 'PrimaryDNSServer' in dns_info and dns_info['PrimaryDNSServer']:
                del_primary = {"path": primary_path}
                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_primary)

            if 'SecondaryDNSServer' in dns_info and dns_info['SecondaryDNSServer']:
                del_secondary = {"path": "Device.RouterAdvertisement.InterfaceSetting.1.Option.2."}

            result = self.ubus.Ubus_Call("bbfdm", "del", del_secondary)

        return result

    def set_dhcpv6_RA_service(self,
                              managed_flag="1",
                              other_config_flag="1",
                              ra_enable="1",
                              preferred_lifetime_hours=12,
                              valid_lifetime_hours=24,
                              raslaac=True):
        """
        【功能描述】
            设置LAN侧IPV6的RA参数
        【入参】
            param managed_flag: str 控制RA报文中的M flag（默认值=1）
            param other_config_flag: str 控制RA报文中的 O flag（默认值=1）
            param ra_enable: str 是否启用RA（默认值=1）
            param preferred_lifetime_hours: int 设置IPV6的首选寿命（默认值=12）
            param valid_lifetime_hours: int 设置IPV6的有效寿命（默认值=24）
            param raslaac: bool 控制RA报文中的A flag （默认值=True）
        【返回值】
            True  : 执行成功
            False : 执行失败 或 抛出异常
        【示例】
        Example:

        """


        preferred_lifetime_seconds = preferred_lifetime_hours * 3600
        valid_lifetime_seconds = valid_lifetime_hours * 3600

        set_params = {
            "paths": [
                {
                    "addr": "Device.RouterAdvertisement.InterfaceSetting.1.",
                    "obj_path": {
                        "AdvManagedFlag": managed_flag,
                        "AdvOtherConfigFlag": other_config_flag,
                        "Enable": ra_enable,
                        f"{VENDOR_PREFIX}AdvPreferredLifetime": preferred_lifetime_seconds,
                        f"{VENDOR_PREFIX}AdvValidLifetime": valid_lifetime_seconds,
                        f"{VENDOR_PREFIX}RASlaac": raslaac
                    }
                }
            ]
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        return result

    def set_ula_prefix(self, ULAPrefix="fdea:e111:ce6b::/48"):
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

        set_params = {
            "paths": [
                {
                    "addr": "Device.IP.",
                    "obj_path": {
                        "ULAPrefix": ULAPrefix
                    }
                }
            ]
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        return result

    def Network_LAN_Get(self):
        host_info = self.get_host_info()
        Dhcpv4Service_info = self.get_Dhcpv4Service_info()
        Dhcpv4Relay_info = self.get_Dhcpv4Relay_info()
        Dhcpv6Service_info = self.get_Dhcpv6Service_info()
        RAService_info = self.get_ipv6_RAService_info()
        GlobalNetworkOption = self.get_ULA_Prefix()

        LAN_info = {
            **host_info,
            **Dhcpv4Service_info,
            **Dhcpv4Relay_info,
            **Dhcpv6Service_info,
            **RAService_info,
            **GlobalNetworkOption
        }

        return LAN_info

    def Network_LANPortWorkMode_Get(self):
        """
        function:
            获取LAN口模式
        Args:
            无
        return:
            返回所有LAN口对应的模式，形式 LAN1:router
        """
        params = {
            "path": "Device.Ethernet.Interface.",
            "optional": {"proto": "web"}
        }
        lan_info = {}
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        for interface in result[1].get("Interface", []):
            if isinstance(interface, dict):
                lan_index = interface.get(f'{VENDOR_PREFIX}Instance', None)
                lan_mode = interface.get(f'{VENDOR_PREFIX}LANMode', None)

            if lan_index is not None and lan_mode is not None:
                key_name = f'LAN{lan_index}'
                lan_info[key_name] = lan_mode

        return lan_info

    def Network_LANPortWorkMode_Set(self, lan_port=1, lan_mode="router"):
        """
        function:
            配置LAN口模式
        Args:
            lan_port: int - LAN口序号，默认为 1
            lan_mode: str - LAN口模式 ‘router’或者‘bridge’，默认为‘router’
        return:
            返回ubus执行结果
        """
        set_params = {
            "path": f"Device.Ethernet.Interface.{lan_port}.{VENDOR_PREFIX}LANMode",
            "value": lan_mode
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        return result

    def Network_LANPortStatus_Get(self):
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

        params = {
            "path": "Device.Ethernet.Interface.",
            "optional": {"proto": "web"}
        }
        lan_info = {}
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        for interface in result[1].get("Interface", []):
            if isinstance(interface, dict):
                lan_index = interface.get(f'{VENDOR_PREFIX}Instance', None)
                lan_status = interface.get("Enable", None)

            if lan_index is not None and lan_status is not None:
                key_name = f'LAN{lan_index}'
                lan_status = "Enable" if lan_status else "Disable"
                lan_info[key_name] = lan_status

        return lan_info

    def Network_LANPortStatus_Set(self, lan_port=1, lan_enable="true"):
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

        set_params = {
            "path": f"Device.Ethernet.Interface.{lan_port}.Enable",
            "value": lan_enable,
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        return result

    def Network_LANPortLinkMode_Get(self):
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

        params = {
            "path": "Device.Ethernet.Interface.",
            "optional": {"proto": "web"}
        }
        lan_info = {}
        lan_mode = {}
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        for interface in result[1].get("Interface", []):
            if isinstance(interface, dict):
                lan_index = interface.get(f'{VENDOR_PREFIX}Instance', None)
                lan_speed = interface.get("MaxBitRate", None)
                lan_duplexmode = interface.get("DuplexMode", None)

            if lan_speed is not None and lan_duplexmode is not None:
                key_name = f'LAN{lan_index}'
                lan_speed = 1000 if lan_speed == -1 else lan_speed
                lan_mode["MaxBitRate"] = lan_speed
                lan_mode["DuplexMode"] = lan_duplexmode
                lan_info[key_name] = lan_mode

        return lan_info

    def Network_LANPortLinkMode_Set(self, lan_port=1, lan_speed=1000, lan_duplexmode="Auto"):
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

        speed_params = {
            "path": f"Device.Ethernet.Interface.{lan_port}.MaxBitRate",
            "value": f"{lan_speed}",
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", speed_params)

        mode_params = {
            "path": f"Device.Ethernet.Interface.{lan_port}.DuplexMode",
            "value": lan_duplexmode,
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", mode_params)

        return result

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            result = self.set_dhcpv4_relay(1, "None", "None","192.168.2.31,192.168.2.33")
            #self.set_dhcpv4_service( 1, "192.168.29.5", "192.168.29.100",
            #                       86400, 1, "")
            result = json.dumps(result, indent=4, ensure_ascii=False)
            print(result)

        except Exception as e:
            print("debug test failed: ", str(e))


if __name__ == '__main__':
    Lan = LanManager(ip="192.168.29.1", username="sdmc", password="1234")
    Lan.debug_test()

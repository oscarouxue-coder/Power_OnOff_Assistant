import json

from SdmcLog import log
from urllib.parse import urlparse
from SdmcUbusLib.libs.Security_module_api.enable_telnet import SdmcUbusLibEnableTelnet
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class StatusManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
    def get_acsline_status(self):
        params = {
            "path": f"Device.ManagementServer.{VENDOR_PREFIX}AcsLineStatus",
            "optional": {"proto": "web"}
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        acsline = data.get(f'{VENDOR_PREFIX}AcsLineStatus')

        return acsline

    def get_internetline_status(self):
        ipv4addr_params = {
            "path": f"Device.IP.{VENDOR_PREFIX}Internet_IPv4Address_Path",
            "optional": {"proto": "web"}
        }

        ipv6addr_params = {
            "path": f"Device.IP.{VENDOR_PREFIX}Internet_IPv6Address_Path",
            "optional": {"proto": "web"}
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", ipv4addr_params)
        data = result[1]
        ipv4address = data.get(f'{VENDOR_PREFIX}Internet_IPv4Address_Path')

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", ipv6addr_params)
        data = result[1]
        ipv6address = data.get(f'{VENDOR_PREFIX}Internet_IPv6Address_Path')

        if ipv4address or ipv6address:
            return True
        else:
            return False

    def get_voipline_status(self):
        params = {
            "path": f"Device.Services.VoiceService.1.SIP.{VENDOR_PREFIX}VoipLineStatus",
            "optional": {"proto": "web"}
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        voipline = data.get(f'{VENDOR_PREFIX}VoipLineStatus')

        return voipline

    def get_interface_instance_by_name(self, target_name):
        try:
            params = {
                "path": "Device.IP.Interface.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]

            interfaces = data.get("Interface", [])
            for iface in interfaces:
                name = iface.get("Name", "")
                instance = iface.get(f"{VENDOR_PREFIX}Instance")
                if name == target_name:
                    return instance

            return None  # 未找到匹配项
        except Exception as e:
            log.info(str(e))
            return False

    def get_mac_from_ethernet_link(self, target_name):
        params = {
            "path": "Device.Ethernet.Link.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or len(result) < 2:
            return ""

        data = result[1]
        links = data.get("Link", [])
        for link in links:
            if link.get("Name") == target_name:
                return link.get("MACAddress", "")
        return ""

    def get_device_info_and_time_ubus(self):
        params = {
            "paths": [
                "Device.DeviceInfo.",
                "Device.Time."
            ],
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or len(result) < 2:
            return None

        data = result[1]

        device_info = data.get("DeviceInfo", {})
        time_info = data.get("Time", {})
        serial_number = data.get("Device.DeviceInfo.SerialNumber", "")
        xpon_sn = data.get(f"Device.XPON.ONU.1.ANI.1.TC.Authentication.{VENDOR_PREFIX}SerialNumber", "")

        return {
            "DeviceInfo": device_info,
            "Time": time_info,
            "SerialNumber": serial_number,
            "XPON_SN": xpon_sn
        }

    def get_device_info(self):
        """
        获取 Device Information
        """
        try:
            data = self.get_device_info_and_time_ubus()
            if not data:
                return None

            device_info = data.get("DeviceInfo", {})
            time_info = data.get("Time", {})

            # 设备型号
            model = device_info.get("ModelName", "")

            # MAC 地址，先尝试从 Ethernet Link 获取（需要调用单独函数）
            mac = getattr(self, "get_mac_from_ethernet_link", lambda x: "")("br-lan")
            if not mac:
                mac = device_info.get("MACAddress", "")

            # 硬件版本
            hw_version = device_info.get("HardwareVersion", "")

            # 软件版本
            sw_version = device_info.get("SoftwareVersion", "")

            # Uptime，device_info里是秒，格式化成“0 Day 03 Hour 24 Minute 20 Seconds”
            uptime_seconds = device_info.get("UpTime", 0)
            days = uptime_seconds // (24 * 3600)
            hours = (uptime_seconds % (24 * 3600)) // 3600
            minutes = (uptime_seconds % 3600) // 60
            seconds = uptime_seconds % 60
            uptime_str = f"{days} Day {hours:02d} Hour {minutes:02d} Minute {seconds:02d} Seconds"

            # 系统时间，取 Time.CurrentLocalTime，格式调整为 “YYYY/MM/DD HH:MM:SS”
            system_time_raw = time_info.get("CurrentLocalTime", "")
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(system_time_raw.replace("Z", "+00:00"))
                system_time = dt.strftime("%Y/%m/%d %H:%M:%S")
            except Exception:
                system_time = system_time_raw

            # 固件编译时间
            firmware_time = device_info.get(f"{VENDOR_PREFIX}BuildTimeStamp", "")

            # 设备序列号
            device_sn = device_info.get("SerialNumber", "")

            # CPU 使用率
            cpu_usage = device_info.get("ProcessStatus", {}).get("CPUUsage", 0)

            # 内存使用率，用内存总量和剩余计算百分比
            mem_total = device_info.get("MemoryStatus", {}).get("Total", 0)
            mem_free = device_info.get("MemoryStatus", {}).get("Free", 0)
            mem_usage_percent = 0
            if mem_total > 0:
                mem_usage_percent = int(100 * (mem_total - mem_free) / mem_total)

            # 温度
            temperature = device_info.get("ProcessStatus", {}).get(f"{VENDOR_PREFIX}cpuTemperature", 0)

            return {
                "Model": model,
                "MAC Address": mac,
                "Hardware Version": hw_version,
                "Software Version": sw_version,
                "Uptime": uptime_str,
                "System Time": system_time,
                "Firmware Time": firmware_time,
                "Device SN": device_sn,
                "CPU Usage": f"{cpu_usage} %",
                "Memory Usage": f"{mem_usage_percent} %",
                "Temperature": f"{temperature} ℃"
            }
        except Exception as e:
            log.info(str(e))
            return 0
    def format_uptime(self,seconds):
        seconds = int(seconds)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{days} Day {hours:02d} Hour {minutes:02d} Minute {secs:02d} Seconds"

    def get_wan_info(self):
        """
        【功能描述】
            获取status界面wan相关信息

        【返回值】
            {2: {'Name': '3_INTERNET_R_VID_35', 'MAC': 'B2:B3:69:60:1C:A1', 'IPv4': '', 'IPv4Gateway': '', 'Status': 'Down', 'Uptime': '0 Day 00 Hour 00 Minute 00 Seconds', 'PrimaryDNSv4': '', 'SecondaryDNSv4': '', 'IPv6': '', 'IPv6Gateway': '', 'PrimaryDNSv6': '', 'SecondaryDNSv6': ''}, 3: {'Name': '4_TR069_R_VID_2501', 'MAC': 'B2:B3:69:60:1C:A2', 'IPv4': '', 'IPv4Gateway': '', 'Status': 'Down', 'Uptime': '0 Day 00 Hour 00 Minute 00 Seconds', 'PrimaryDNSv4': '', 'SecondaryDNSv4': '', 'IPv6': '', 'IPv6Gateway': '', 'PrimaryDNSv6': '', 'SecondaryDNSv6': ''}}


        【示例】
        Example:
        |  result  |  get_wan_info  |
        """

        try:
            params = {
                "path": "Device.IP.Interface.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]

            wan_info = {}
            prefix = None

            interfaces = data.get("Interface", [])
            for idx, iface in enumerate(interfaces):
                if iface.get(f"{VENDOR_PREFIX}InterfaceType") in ("lan", "transp"):
                    continue  # 跳过 LAN 和透明接口

                name = iface.get("Name", "")
                mac = iface.get(f"{VENDOR_PREFIX}MacAddress", "")
                status = iface.get(f"{VENDOR_PREFIX}Status", "")
                uptime_seconds = iface.get(f"{VENDOR_PREFIX}Ipv4ConnectionTime", 0)
                uptime = self.format_uptime(uptime_seconds)

                # IPv4 信息处理
                ipv4_list = iface.get("IPv4Address", [])
                ipv4 = ipv4_list[0].get("IPAddress", "") if ipv4_list else ""
                ipv4_gateway = ipv4_list[0].get(f"{VENDOR_PREFIX}DefaultGateway", "") if ipv4_list else ""
                net_info_v4 = ipv4_list[0].get(f"{VENDOR_PREFIX}NetInfo", "") if ipv4_list else ""

                dns_v4_1, dns_v4_2 = "", ""
                if net_info_v4:
                    dns_list = net_info_v4.split(",")
                    if len(dns_list) >= 2:
                        dns_v4_1 = dns_list[1]
                    if len(dns_list) >= 3:
                        dns_v4_2 = dns_list[2]

                # IPv6 信息处理
                ipv6_list = iface.get("IPv6Address", [])
                ipv6 = ipv6_list[0].get("IPAddress", "") if ipv6_list else ""
                # ipv6_gateway = ipv6_list[0].get(f"{VENDOR_PREFIX}DefaultGateway", "") if ipv6_list else ""
                net_info_v6 = ipv6_list[0].get(f"{VENDOR_PREFIX}NetInfo", "") if ipv6_list else ""

                ipv6_prefix = iface.get("IPv6Prefix",[])
                log.debug(ipv6_prefix)
                if ipv6_prefix:
                    prefix = ipv6_prefix[0].get("Prefix")

                # 解析 IPv6 DNS，仅在存在时添加字段
                dns_v6_1, dns_v6_2 = "", ""
                ipv6_gateway = ""
                has_dns_v6 = False
                if net_info_v6:
                    dns_list_v6 = net_info_v6.split(",")
                    if len(dns_list_v6) >= 1:
                        ipv6_gateway = dns_list_v6[0]
                    if len(dns_list_v6) >= 2:
                        dns_v6_1 = dns_list_v6[1]
                        has_dns_v6 = True
                    if len(dns_list_v6) >= 3:
                        dns_v6_2 = dns_list_v6[2]

                info = {
                    "Name": name,
                    "MAC": mac,
                    "IPv4": ipv4,
                    "IPv4Gateway": ipv4_gateway,
                    "Status": status,
                    "Uptime": uptime,
                    "PrimaryDNSv4": dns_v4_1,
                    "SecondaryDNSv4": dns_v4_2,
                    "IPv6": ipv6,
                    "IPv6Gateway": ipv6_gateway,
                    "PrimaryDNSv6": dns_v6_1,
                    "SecondaryDNSv6": dns_v6_2
                }
                if prefix:
                    info["Prefix"] = prefix

                wan_info[idx] = info

            return wan_info
        except Exception as e:
            log.info(str(e))
            return 0

    def get_lan_port_status(self):
        params = {
            "path": "Device.Ethernet.Interface.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        print(result)
        data = result[1]
        print(data)

        lan_status_list = []
        interfaces = data.get("Interface", [])

        for idx, iface in enumerate(interfaces):
            port = {
                "port": f"LAN{idx + 1}",
                "mode": iface.get("DuplexMode", ""),
                "speed": iface.get("CurrentBitRate", 0),
                "link": iface.get("Status", ""),
                "rxbytes": iface.get("Stats", {}).get("BytesReceived", 0),
                "rxpackets": iface.get("Stats", {}).get("PacketsReceived", 0),
                "txbytes": iface.get("Stats", {}).get("BytesSent", 0),
                "txpackets": iface.get("Stats", {}).get("PacketsSent", 0)
            }
            lan_status_list.append(port)

        return lan_status_list

    def get_connected_hosts_info(self):
        """
        【功能描述】
            获取 client 下 Router 模式连接的 host信息

        【返回值】
            [{'hostname': 'H1148', 'ip': '192.168.29.221', 'mac': 'f8:e4:3b:6f:0a:21', 'type': 'Ethernet', 'linkport': 'eth2.0', "Active": true}, {'hostname': 'H1148', 'ip': '192.168.29.8', 'mac': 'bc:cd:99:f7:c3:62', 'type': 'Wi-Fi', 'linkport': '!!!SDMC_221100_5G',"Active": true}]


        【示例】
            Example:
            |  result  |  get_connected_hosts_info  |
        """
        host_list = []
        try:
            params = {
                "path": "Device.Hosts.Host.",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            data = result[1]

            hosts = data.get("Host", [])

            for host in hosts:
                info = {
                    "hostname": host.get("HostName", ""),
                    "ip": host.get("IPAddress", ""),
                    "mac": host.get("PhysAddress", ""),
                    "type": host.get("InterfaceType", ""),
                    "linkport": host.get(f"{VENDOR_PREFIX}LinkMode", ""),
                    "Active": host.get("Active")
                }
                host_list.append(info)
        except Exception as e:
            log.info(f"get_hosts failed: {e}")
            return []

        return host_list

    def manage_wan(self, method, index):
        """
        统一管理 WAN 接口：支持 Release 和 Renew 操作

        参数：
            method (str): 操作类型，"Release" 或 "Renew"
            index (int): WAN 接口索引号

        返回：
            ubus 调用结果
        """
        try:
            if method not in ["Release", "Renew"]:
                raise ValueError("Unsupported method, only 'Release' or 'Renew' allowed.")

            input_data = {
                "Method": method,
                "Index": index,
                "Enable": 1,
                "Mode": "",
                "ServiceType": "",
                "IPoE": 0,
                "PPPoE": 0,
                "IPProtocol": "",
                "IPv4Type": "",
                "IPv4Address": "",
                "IPv4Gateway": "",
                "IPv4Netmask": "",
                "IPv4PrimaryDNS": "",
                "IPv4SecondDNS": "",
                "IPv6Type": "",
                "IPv6Address": "",
                "IPv6Gateway": "",
                "IPv6Prefix": "",
                "IPv6PrimaryDNS": "",
                "IPv6SecondDNS": "",
                "DHCPv6AddressAssignment": 0,
                "DHCPv6PrefixDelegation": 0,
                "SLAAC": 0,
                "DSLiteEnable": 0,
                "DSLiteAddress": "",
                "DSLiteType": "",
                "Option60Vendor": "",
                "Option121Enable": "",
                "Nat": 0,
                "Username": "",
                "Password": "",
                "MTU": "",
                "VLAN": "",
                "VLANPriority": "",
                "PortBind": 0,
                "MulticastVLANID": ""
            }

            params = {
                "command": f"Device.{VENDOR_PREFIX}CreateWAN()",
                "input": input_data,
                "optional": {"proto": "web"}
            }

            return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)

        except Exception as e:
            log.info(str(e))
            return 0

    def get_poninfo(self):
        """
        【功能描述】
        获取光模块（PON模块）的运行信息，包括注册状态、工作温度、光功率、电压、电流等。

        【入参】
        无

        【返回值】
        pon_info : dict
            返回光模块的状态信息，示例如下：
            {
                "ONT Registration Status": "Online",
                "Working Temperature": "45.2℃",
                "TX Optical Power": "-1.23 dBm",
                "RX Optical Power": "-18.56 dBm",
                "Working Voltage": "3300 mV",
                "Working Current": "12.5 mA"
            }

            若未获取到 Optical.Interface 信息，则返回空字典 {}

        【示例】
        Example:
        |  Get Pon Info  |  |  |
        |  返回结果: {'ONT Registration Status': 'Online', 'Working Temperature': '42.8℃', 'TX Optical Power': '-2.10 dBm', 'RX Optical Power': '-17.88 dBm', 'Working Voltage': '3300 mV', 'Working Current': '12.3 mA'}  |
        """

        params = {
            "path": "Device.Optical.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        interface = data.get("Optical", {}).get("Interface", [])
        if not interface:
            return {}

        info = interface[0]

        pon_info = {
            "ONT Registration Status": info.get("Status", ""),
            "Working Temperature": f"{info.get(f'{VENDOR_PREFIX}TransceiverTemperature', '')}℃",
            "TX Optical Power": f"{info.get(f'{VENDOR_PREFIX}TxOpticalPower', '')} dBm",
            "RX Optical Power": f"{info.get(f'{VENDOR_PREFIX}RxOpticalPower', '')} dBm",
            "Working Voltage": f"{info.get(f'{VENDOR_PREFIX}SupplyVoltage', '')} mV",
            "Working Current": f"{info.get(f'{VENDOR_PREFIX}BiasCurrent', '')} mA",
        }

        return pon_info

    def get_chip_name(self):
        """
        【功能描述】
            获取产品方案名称

        【返回值】
            airoha或者bcmxxx(xxx为芯片名称)

        【示例】
        Example:
        |  chip_name  |  get_chip_name  |

        """

        telnet = SdmcUbusLibEnableTelnet()
        parsed_url = urlparse(SdmcUbusLibBase.Url)
        ip = parsed_url.hostname
        ret = telnet.telnet_run_cmd(ip, SdmcUbusLibBase.Username, SdmcUbusLibBase.Password, "uci get deviceinfo.deviceinfo.chip")
        log.info("chip name is "+ str(ret))

        return ret

    def get_voip_info(self):
        """
        【功能描述】
            获取 VoIP 相关信息，包括 Name、DisplayName、RegistrationStatus 和 SubscriberLineStatus
        
        【入参】
            无
        
        【返回值】
            dict: 包含 VoIP 信息的字典，格式如下：
                {
                    "Name": "LineIndex",
                    "DisplayName": "DisplayName",
                    "RegistrationStatus": "LineStatus",
                    "SubscriberLineStatus": "CallStatus"
                }
        
        【示例】
            Example:
            |  result  |  get_voip_info  |
        """
        try:
            # 导入 VoipManager
            from SdmcUbusLib.libs.Voice_moudle_api.voip import VoipManager
            
            # 创建 VoipManager 实例
            voip_manager = VoipManager(self.ip, self.username, self.password)
            
            # 获取 SIP 账户设置信息
            sip_info = voip_manager.get_sip_account_setting_info()[0]
            
            # 获取通话状态信息
            call_info = voip_manager.get_call_status()
            
            # 提取所需信息
            voip_data = {
                "Name": sip_info.get("LineIndex", ""),
                "DisplayName": sip_info.get("DisplayName", ""),
                "RegistrationStatus": sip_info.get("LineStatus", ""),
                "SubscriberLineStatus": call_info
            }
            
            return voip_data
            
        except Exception as e:
            log.info(f"获取 VoIP 信息失败: {str(e)}")
            return {}

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)

            # # 1. 获取 WAN 信息
            # wan_info = self.get_wan_info()

            # # 2. Release/Renew WAN IP
            # info = self.manage_wan("Renew", 4)
            #
            # # 3. 获取 PON 信息
            # pon_info = self.get_poninfo()
            #
            # # 4. 获取设备信息
            # device_info = self.get_device_info()
            #
            # # 5. 获取 LAN 口状态
            # lan_info = self.get_lan_port_status()
            #
            # # 6. 获取连接客户信息
            # client_info = self.get_connected_hosts_info()

            # info = {
            #     "WANInfo": wan_info,
            #     "PONInfo": pon_info,
            #     "DeviceInfo": device_info,
            #     "LANStatus": lan_info,
            #     "ClientList": client_info
            # }

            info = self.get_wan_info()

            # 输出调试信息
            info_json = json.dumps(info, indent=4, ensure_ascii=False)
            print(info_json)

        except Exception as e:
            print("debug test failed:", str(e))


    def unit_test(self):
        """
        单元测试前要确保已经仅创建一条路由wan用于验证Release/Renew WAN IP的功能
        """

        try:
            self.ubus.Ubus_Login(self.username, self.password)

            # 1. Release/Renew WAN IP
            result = self.manage_wan("Release", 3)

            result = self.manage_wan("Renew", 3)

            # 2. 获取 WAN 信息
            wan_info = self.get_wan_info()

            # 3. 获取 PON 信息
            pon_info = self.get_poninfo()

            # 4. 获取设备信息
            device_info = self.get_device_info()

            # 5. 获取 LAN 口状态
            lan_info = self.get_lan_port_status()

            # 6. 获取连接客户信息
            client_info = self.get_connected_hosts_info()

            info = {
                "WANInfo": wan_info,
                "PONInfo": pon_info,
                "DeviceInfo": device_info,
                "LANStatus": lan_info,
                "ClientList": client_info
            }

            # 输出调试信息
            info_json = json.dumps(info, indent=4, ensure_ascii=False)
            print(info_json)

        except Exception as e:
            print("debug test failed:", str(e))



if __name__ == '__main__':
    Status = StatusManager(ip="192.168.29.1", username="sdmc", password="1234")
    Status.debug_test()
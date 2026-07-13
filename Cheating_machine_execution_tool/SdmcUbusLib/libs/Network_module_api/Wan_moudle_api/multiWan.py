import json
import re
from datetime import datetime
from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcCode import *

portbind_flag = {
    "LAN1": 1,
    "LAN2": 2,
    "LAN3": 4,
    "LAN4": 8,
    "LAN5": 16,
    "LAN6": 32,
    "LAN7": 64,
    "LAN8": 128,
    "2.4Gwifi": 256,
    "2.4Gguest": 512,
    "5Gwifi": 2048,
    "5Gguest": 4096
}

class multiWanManager:
    router_wan_server_type = {
        1: "TR069",
        2: "VOICE",
        3: "INTERNET",
        4: "TR069-VOICE",
        5: "TR069-INTERNET",
        6: "VOICE_INTERNET",
        7: "TR069-VOICE-INTERNET",
        8: "OTHER",
        9: "IPTV"
    }
    
    # 使用类级别的字典来存储所有WAN参数，避免实例化时重置
    __wan_parameters_history = {}
    __wan_counter = 0

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        self.last_wan_parms = {}

    def get_default_input(self) -> dict:
        return {
            "Method": "Add",
            "Index": "",
            "Enable": 1,
            "Mode": "router",
            "ServiceType": "INTERNET",
            "IPoE": 0,
            "PPPoE": 0,
            "DHCPv6AddressAssignment": 0,
            "DHCPv6PrefixDelegation": 0,
            "DSLiteAddress": "",
            "DSLiteEnable": 0,
            "DSLiteType": "",
            "IPProtocol": "",
            "IPv4Address": "",
            "IPv4Gateway": "",
            "IPv4Netmask": "",
            "IPv4PrimaryDNS": "",
            "IPv4SecondDNS": "",
            "IPv4Type": "",
            "IPv6Address": "",
            "IPv6Gateway": "",
            "IPv6Prefix": "",
            "IPv6PrimaryDNS": "",
            "IPv6SecondDNS": "",
            "IPv6Type": "",
            "MTU": 1500,
            "MulticastVLANID": "",
            "Nat": 1,
            "Option60Vendor": "",
            "Option120Enable": 0,
            "Option121Enable": 0,
            "Password": "",
            "PortBind": 0,
            "SLAAC": 0,
            "TCPMSS": 0,
            "Username": "",
            "VLAN": "",
            "VLANPriority": 0
        }

    def is_ipv6(self, address):
        """
        功能描述：
        判断是否为IPv6地址

        入参：
        IP地址

        返回值：
        True或False
        """
        return ':' in address if address else False

    def initialize_info(self, target_interface):
        """
        功能描述：
        初始化基础WAN结构信息

        入参：
        target_interface：Device.IP.Interface.中对应wan的ubus接口信息

        返回值：
        wan基础配置字典
        """
        return {
            'Connection Name': None,
            'Enable': target_interface.get('Enable'),
            'ServiceType': target_interface.get(f'{VENDOR_PREFIX}ServiceType', ''),
            'MTU': target_interface.get('MaxMTUSize'),
            'PortBind': None,
            'WANType': None,
            'PPPoE': {},
            'VLANID': None,
            'VLANPriority': None,
            'IPProtocol': 'None',
            'IPv4Info': {},
            'IPv6Info': {}
        }

    def get_port_bind_info(self, target_interface, result):
        """
        功能描述：
        解析 PortBind 字符串

        入参：
        target_interface：Device.IP.Interface.中对应wan的ubus接口信息字典
        result: get_all_base_paths()返回的ubus信息字典

        返回值：
        端口绑定信息
        """
        output = []

        try:
            # 参数校验
            if not isinstance(target_interface, dict):
                raise TypeError("target_interface 应为字典类型")
            if not isinstance(result, dict):
                raise TypeError("result 应为字典类型")

            bind_string = target_interface.get(f'{VENDOR_PREFIX}PortBind')

            items = [s.strip() for s in bind_string.split(',') if s.strip()]
            ssid_list = result.get('SSID', [])

            for item in items:
                if item.startswith("Device.Ethernet.Interface."):
                    # 取最后一个数字作为端口号
                    port_num = item.rsplit('.', 1)[-1]
                    output.append(f"lan{port_num}")
                elif item.startswith("Device.WiFi.SSID."):
                    ssid_index = item.rsplit('.', 1)[-1]
                    ssid_obj = next(
                        (s for s in ssid_list if str(s.get(f'{VENDOR_PREFIX}Instance')) == ssid_index),
                        None
                    )
                    if not ssid_obj:
                        raise ValueError(f"未找到对应的 SSID 实例: {item}")
                    ssid_name = ssid_obj.get('SSID')
                    if not ssid_name:
                        raise ValueError(f"SSID 对象中缺少 SSID 字段: {ssid_obj}")
                    output.append(ssid_name)
                else:
                    raise ValueError(f"不支持的绑定类型: {item}")

        except Exception as e:
            log.info(f"get_port_bind_info 异常: {e}")
            raise

        return output

    def get_dns_info(self, result, interface_path):
        """
        提取并分离IPv4/IPv6 DNS信息。

        参数：
            result: dict 类型，包含所有的 DNS 配置信息（通常来源于 get_all_base_paths() 等）。
            interface_path: str 类型，指定的接口路径，例如 "Device.IP.Interface.1"

        返回：
            ipv4_dns: List[str] 类型，所有 IPv4 DNS 地址。
            ipv6_dns: List[str] 类型，所有 IPv6 DNS 地址。
        """
        ipv4_dns = []
        ipv6_dns = []

        try:
            # 参数校验
            if not isinstance(result, dict):
                raise TypeError("参数 result 必须是 dict 类型")
            if not isinstance(interface_path, str):
                raise TypeError("参数 interface_path 必须是 str 类型")

            dns_servers = [
                srv for srv in result.get('Server', [])
                if isinstance(srv, dict) and srv.get('Interface') == interface_path
            ]

            for srv in dns_servers:
                dns = srv.get('DNSServer')
                if not dns:
                    log.warning(f"忽略无效的 DNSServer 项: {srv}")
                    continue
                if self.is_ipv6(dns):
                    ipv6_dns.append(dns)
                else:
                    ipv4_dns.append(dns)

        except Exception as e:
            log.error(f"get_dns_info 解析出错: {e}")
            raise

        return ipv4_dns, ipv6_dns

    def get_tcpmss_mode(self, target_interface):
        """
        提取 TCP MSS 模式信息：
        - 如果为 0，返回 "Auto"
        - 否则返回 "Custom: xxx"
        """
        mss_value = target_interface.get(f'{VENDOR_PREFIX}TCPMSS', 0)
        if mss_value == 0:
            return 'Auto'
        return f'Custom: {mss_value}'

    def get_Multicast_VlanId(self, target_interface):

        return target_interface.get(f'{VENDOR_PREFIX}Multicast_VLANID')

    def get_interface_names(self, json_data):
        """
        获取接口名
        """
        names = []
        interfaces = json_data.get("Interface", [])
        skip_names = {"LAN", "2_OTHER_B_VID_TRANSP"}
        for interface in interfaces:
            instance = interface.get("Name", "")
            if instance in skip_names:
                continue
            names.append(instance)
        return names

    def handle_bridge_case(self, target_interface, result):
        """处理桥接WAN类型"""
        wan_info = {
            'Mode': 'Bridge',
            'VLANID': None,
            'VLANPriority': None
        }
        lower_layers = target_interface.get('LowerLayers', '')
        link_instance = lower_layers.split('.')[-1]
        # 查找Ethernet Link配置
        link_config = next(
            (link for link in result.get('Ethernet', {}).get('Link', [])
             if str(link.get(f'{VENDOR_PREFIX}Instance')) == link_instance),
            None
        )
        if link_config:
            bridge_path = link_config.get('LowerLayers', '')
            if bridge_path.startswith('Device.Bridging.Bridge.'):
                bridge_id = bridge_path.split('.')[3]
                # 查找桥接配置
                bridge_config = next(
                    (b for b in result.get('Bridge', [])
                     if str(b.get(f'{VENDOR_PREFIX}Instance')) == bridge_id),
                    None
                )
                # 提取VLAN信息
                if bridge_config:
                    vlan_list = bridge_config.get('VLAN', [])
                    if vlan_list:
                        wan_info['VLANID'] = vlan_list[0].get('VLANID')
                        wan_info['VLANPriority'] = vlan_list[0].get(f'{VENDOR_PREFIX}VLANPriority')
        return wan_info

    def handle_ipoe_case(self, target_interface, result):
        """处理IPoE WAN类型"""
        wan_info = {
            'Mode': 'Router',
            'WANType': 'IPoE',
            'VLANID': None,
            'VLANPriority': None
        }
        lower_layers = target_interface.get('LowerLayers', '')

        # 提取VLAN Termination配置
        vlan_term = next(
            (v for v in result.get('Ethernet', {}).get('VLANTermination', [])
             if f"Device.Ethernet.VLANTermination.{v.get(f'{VENDOR_PREFIX}Instance')}" in lower_layers),
            None
        )
        if vlan_term:
            wan_info['VLANID'] = vlan_term.get('VLANID')
            wan_info['VLANPriority'] = vlan_term.get('VLANPriority')
        return wan_info

    def handle_pppoe_case(self, target_interface, result):
        """处理PPPoE WAN类型，新增VLAN信息提取"""
        wan_info = {
            'Mode': 'Router',
            'WANType': 'PPPoE',
            'PPPoE': {},
            'VLANID': None,
            'VLANPriority': None
        }
        lower_layers = target_interface.get('LowerLayers', '')
        ppp_instance = lower_layers.split('.')[-1]
        try:
            # 解析PPP配置
            ppp_instance = int(ppp_instance)
            ppp_config = next(
                (p for p in result.get('PPP', {}).get('Interface', [])
                 if p.get(f'{VENDOR_PREFIX}Instance') == ppp_instance),
                None
            )
            if ppp_config:
                wan_info['PPPoE'] = {
                    'Username': ppp_config.get('Username'),
                    'Password': ppp_config.get(f'{VENDOR_PREFIX}Password')
                }

                # 新增：解析VLAN Termination信息
                vlan_termination_path = ppp_config.get('LowerLayers', '')
                if 'VLANTermination' in vlan_termination_path:
                    # 提取VLANTermination实例号
                    vlan_term_instance = vlan_termination_path.split('.')[-1]
                    try:
                        vlan_term_instance = int(vlan_term_instance)
                        # 在Ethernet配置中查找对应实例
                        vlan_term = next(
                            (v for v in result.get('Ethernet', {}).get('VLANTermination', [])
                             if v.get(f'{VENDOR_PREFIX}Instance') == vlan_term_instance),
                            None
                        )
                        if vlan_term:
                            wan_info['VLANID'] = vlan_term.get('VLANID')
                            wan_info['VLANPriority'] = vlan_term.get('VLANPriority')
                    except (ValueError, IndexError):
                        pass
        except ValueError:
            pass
        return wan_info

    def determine_wan_info(self, target_interface, result):
        """综合判断WAN类型及相关配置"""
        lower_layers = target_interface.get('LowerLayers', '')

        if lower_layers.startswith('Device.Ethernet.Link.'):
            return self.handle_bridge_case(target_interface, result)
        elif lower_layers.startswith('Device.Ethernet.VLANTermination.'):
            return self.handle_ipoe_case(target_interface, result)
        elif lower_layers.startswith('Device.PPP.Interface.'):
            return self.handle_pppoe_case(target_interface, result)
        return {'WANType': None}

    def determine_ip_protocol(self, target_interface):
        """判断IP协议类型"""
        ipv4_enabled = target_interface.get('IPv4Enable', False)
        ipv6_enabled = target_interface.get('IPv6Enable', False)

        if ipv4_enabled and ipv6_enabled:
            return 'IPv4/IPv6'
        elif ipv4_enabled:
            return 'IPv4'
        elif ipv6_enabled:
            return 'IPv6'
        return 'None'

    def hex_to_char(self, hex_str):
        """
        将十六进制字符串还原为原始字符串。

        参数：
            hex_str (str): 输入的十六进制字符串（长度应为偶数）

        返回：
            str: 转换后的原始字符串，若输入非法则返回空字符串
        """
        if not isinstance(hex_str, str) or len(hex_str) % 2 != 0:
            return ''

        try:
            chars = [
                chr(int(hex_str[i:i + 2], 16))  # 每两个字符转成整数，再转成字符
                for i in range(0, len(hex_str), 2)
            ]
            return ''.join(chars)
        except ValueError:
            return ''

    def get_dhcp_options(self, dhcp_config):
        """提取DHCP客户端选项，包含Option60和Option121"""
        # 从SentOption中获取Option60
        option60 = next(
            (opt for opt in dhcp_config.get('SentOption', [])
             if opt.get('Tag') == 60),
            {}
        )
        option60_value = option60.get('Value')
        option60_value = self.hex_to_char(option60_value)
        # 从ReqOption中获取Option121
        option121 = next(
            (opt for opt in dhcp_config.get('ReqOption', [])
             if opt.get('Tag') == 121),
            {}
        )

        option120 = next(
            (opt for opt in dhcp_config.get('ReqOption', [])
             if opt.get('Tag') == 120),
            {}
        )
        return {
            'Option60VendorID': option60_value,
            'Option121Enable': option121.get('Enable', False),
            'Option120Enable': option120.get('Enable', False)
        }

    def parse_dhcpv6_config(self, dhcpv6):
        """解析DHCPv6配置，判断Prefix Delegation和IPv6地址获取方式"""
        result = {}
        # 处理Prefix Delegation
        if dhcpv6.get('RequestPrefixes', False):
            result['Prefix Delegation'] = True

        # 处理IPv6地址获取方式
        request_addr = dhcpv6.get('RequestAddresses', False)
        accept_ra = dhcpv6.get(f'{VENDOR_PREFIX}AcceptRAPrefixes', False)

        if request_addr and not accept_ra:
            result['Get IPv6 Address'] = 'DHCPv6'
        elif not request_addr and accept_ra:
            result['Get IPv6 Address'] = 'SLAAC'

        return result

    def process_ipv4_info(self, target_interface, result, interface_path, ipv4_dns):
        """处理IPv4信息（先判断类型，再按需填充字段）"""
        ipv4_data = {}

        if not target_interface.get('IPv4Enable', False):
            return ipv4_data  # 返回空字典

        # 先根据 DNS 推断地址类型
        has_dns = len(ipv4_dns) > 0
        addr_type = 'Static' if has_dns else 'Dynamic'
        ipv4_data['AddressingType'] = addr_type

        if addr_type == 'Dynamic':
            dhcp_client_list = result.get('DHCPv4', {}).get('Client', [])
            dhcp_config = next(
                (c for c in dhcp_client_list if c.get('Interface') == interface_path),
                None
            )
            if dhcp_config:
                ipv4_data.update(self.get_dhcp_options(dhcp_config))

        if addr_type == 'Static':
            ipv4_list = target_interface.get('IPv4Address', [])
            if ipv4_list:
                ipv4_config = ipv4_list[0]
                ipv4_data.update({
                    'IPAddress': ipv4_config.get('IPAddress'),
                    'SubnetMask': ipv4_config.get('SubnetMask'),
                    'Gateway': ipv4_config.get(f'{VENDOR_PREFIX}DefaultGateway', ''),
                    'PrimaryDNS': ipv4_dns[0] if has_dns else None,
                    'SecondaryDNS': ipv4_dns[1] if len(ipv4_dns) > 1 else None
                })

        return ipv4_data

    def process_ipv6_info(self, target_interface, result, interface_path, ipv6_dns):
        """处理IPv6信息（根据 DNS 判断是否为静态，仅静态时填充详细信息）"""
        ipv6_data = {}

        if not target_interface.get('IPv6Enable', False):
            return ipv6_data  # 返回空字典

        has_dns = len(ipv6_dns) > 0
        addr_type = 'Static' if has_dns else 'Dynamic'
        ipv6_data['AddressingType'] = addr_type

        if addr_type == 'Static':
            ipv6_list = target_interface.get('IPv6Address', [])
            ipv6_prefix_list = target_interface.get('IPv6Prefix', [])
            ipv6_config = next((addr for addr in ipv6_list if addr.get('Origin') == 'Static'), None)

            if ipv6_config:
                instance_id = ipv6_config.get(f'{VENDOR_PREFIX}Instance')
                prefix_value = None

                if instance_id is not None:
                    prefix_entry = next(
                        (p for p in ipv6_prefix_list if p.get(f'{VENDOR_PREFIX}Instance') == instance_id),
                        None
                    )
                    if prefix_entry:
                        prefix_value = prefix_entry.get('Prefix')

                ipv6_data.update({
                    'IPAddress': ipv6_config.get('IPAddress'),
                    'Gateway': ipv6_config.get(f'{VENDOR_PREFIX}DefaultGateway', ''),
                    'Prefix': prefix_value,
                    'PrimaryDNS': ipv6_dns[0] if has_dns else None,
                    'SecondaryDNS': ipv6_dns[1] if len(ipv6_dns) > 1 else None
                })

        if addr_type == 'Dynamic':
            dhcp_client_list = result.get('DHCPv6', {}).get('Client', [])
            dhcp_config = next(
                (c for c in dhcp_client_list if c.get('Interface') == interface_path),
                None
            )
            if dhcp_config:
                ipv6_data.update(self.parse_dhcpv6_config(dhcp_config))
        return ipv6_data

    def filter_bridge_info(self, info):
        """过滤桥接WAN的返回字段"""
        allowed_keys = ['Connection Name','Enable', 'ServiceType', 'Mode', 'PortBind', 'VLANID', 'VLANPriority', 'Index']
        filtered_dict = {k: v for k, v in info.items() if k in allowed_keys}

        return json.dumps(filtered_dict, indent=4, ensure_ascii=False)

    def get_nat_status(self, data, wan_name):
        """获取指定WAN接口的NAT启用状态"""
        # 获取主数据结构
        result = data[1]
        if not result:
            return None

        # 查找目标接口
        target_interface = next(
            (iface for iface in result.get('Interface', [])
             if iface.get('Name') == wan_name),
            None
        )
        if not target_interface:
            return None

        # 获取接口实例号
        interface_instance = target_interface.get(f'{VENDOR_PREFIX}Instance')

        # 在NAT配置中查找匹配项
        nat_settings = result.get('NAT', {}).get('InterfaceSetting', [])
        nat_config = next(
            (n for n in nat_settings
             if n.get(f'{VENDOR_PREFIX}Instance') == interface_instance),
            {}
        )

        return nat_config.get('Enable', False)

    def get_wan_info(self, data, wan_name):
        """主函数：获取WAN接口完整信息"""
        result = data[1]
        if not result:
            return None

        target_interface = next(
            (iface for iface in result.get('Interface', [])
             if iface.get('Name') == wan_name),
            None
        )
        if not target_interface:
            return None

        info = self.initialize_info(target_interface)
        info['Connection Name'] = wan_name

        interface_instance = target_interface.get(f'{VENDOR_PREFIX}Instance')
        interface_path = f"Device.IP.Interface.{interface_instance}"
        info['Index'] = interface_instance

        ipv4_dns, ipv6_dns = self.get_dns_info(result, interface_path)

        wan_info = self.determine_wan_info(target_interface, result)
        info.update(wan_info)

        info['IPProtocol'] = self.determine_ip_protocol(target_interface)

        ipv4_info = self.process_ipv4_info(target_interface, result, interface_path, ipv4_dns)
        info['IPv4Info'] = ipv4_info

        ipv6_info = self.process_ipv6_info(target_interface, result, interface_path, ipv6_dns)
        info['IPv6Info'] = ipv6_info

        info['NAT'] = self.get_nat_status(data, wan_name)
        info['MSS'] = self.get_tcpmss_mode(target_interface)

        if info['ServiceType'] == 'INTERNET' or info['Mode'] == 'Bridge' or info['ServiceType'] == 'IPTV' or info['ServiceType'] == 'OTHER':
            info['PortBind'] = self.get_port_bind_info(target_interface, result)

        if info['ServiceType'] == 'IPTV':
            info['Multicast_VLAN_ID'] = self.get_Multicast_VlanId(target_interface)

        if info['Mode'] == 'Bridge':
            return self.filter_bridge_info(info)

        #if info['Mode'] == 'Router':
            #del info['PortBind']

        #info = json.dumps(info, indent=4, ensure_ascii=False)

        return info

    def _store_wan_parameters(self, parameters: dict) -> str:
        """
        存储WAN参数到历史记录中，返回唯一的WAN ID
        """
        # 生成唯一的WAN ID
        self.__class__.__wan_counter += 1
        wan_id = f"WAN_{self.__class__.__wan_counter}"
        
        # 创建参数副本，避免引用问题
        stored_parameters = parameters.copy()
        
        # 提取WAN索引（如果有的话）
        wan_index = None
        if 'Index' in parameters:
            wan_index = parameters['Index']
        elif isinstance(parameters, dict) and 'Index' in parameters:
            wan_index = parameters['Index']
        
        # 添加时间戳和其他元数据
        stored_parameters.update({
            '_wan_id': wan_id,
            '_created_time': str(datetime.now()),
            '_ip': self.ip,
            '_wan_index': wan_index
        })
        
        # 存储到历史记录中
        self.__class__.__wan_parameters_history[wan_id] = stored_parameters
        
        log.info(f"WAN参数已存储，ID: {wan_id}, 索引: {wan_index}")
        return wan_id

    def get_wan_parameters_history(self) -> dict:
        """
        获取所有WAN参数历史记录
        """
        return self.__class__.__wan_parameters_history.copy()

    def get_wan_parameters_by_id(self, wan_id: str) -> dict:
        """
        根据WAN ID获取特定的WAN参数
        """
        return self.__class__.__wan_parameters_history.get(wan_id, {}).copy()

    def _delete_wan_parameters_by_index(self, wan_index: int) -> bool:
        """
        根据WAN索引删除存储的WAN参数
        """
        deleted = False
        wan_ids_to_delete = []
        
        # 查找匹配的WAN记录
        for wan_id, wan_data in self.__class__.__wan_parameters_history.items():
            stored_index = wan_data.get('_wan_index')
            if stored_index == wan_index:
                wan_ids_to_delete.append(wan_id)
        
        # 删除找到的记录
        for wan_id in wan_ids_to_delete:
            del self.__class__.__wan_parameters_history[wan_id]
            deleted = True
            log.info(f"已删除存储的WAN参数，ID: {wan_id}, 索引: {wan_index}")
        
        if not deleted:
            log.warning(f"未找到索引为 {wan_index} 的存储WAN参数")
        
        return deleted

    def _delete_wan_parameters_by_id(self, wan_id: str) -> bool:
        """
        根据WAN ID删除存储的WAN参数
        """
        if wan_id in self.__class__.__wan_parameters_history:
            wan_data = self.__class__.__wan_parameters_history[wan_id]
            del self.__class__.__wan_parameters_history[wan_id]
            log.info(f"已删除存储的WAN参数，ID: {wan_id}")
            return True
        else:
            log.warning(f"未找到ID为 {wan_id} 的存储WAN参数")
            return False

    def get_latest_wan_parameters(self) -> dict:
        """
        获取最新创建的WAN参数
        """
        if not self.__class__.__wan_parameters_history:
            return {}
        
        latest_id = max(self.__class__.__wan_parameters_history.keys())
        return self.__class__.__wan_parameters_history[latest_id].copy()

    def _remove_wan_parameters_records(self, wan_name: str) -> int:
        """
        根据WAN名称删除对应的存储配置记录
        
        参数:
            wan_name: WAN连接名称
            
        返回:
            删除的记录数量
        """
        removed_count = 0
        try:
            history = self.__class__.__wan_parameters_history

            if not history:
                return 0
            
            # 获取WAN名称的索引部分(如果名称包含数字前缀)
            wan_index = None
            if '_' in wan_name:
                parts = wan_name.split('_')
                if parts[0].isdigit():
                    wan_index = int(parts[0])

            # 查找并删除匹配的记录
            records_to_remove = []
            for wan_id, record in history.items():

                # 1. Connection Name 精确匹配
                if record.get('Connection Name') == wan_name:
                    records_to_remove.append(wan_id)

                # 2. Index 匹配
                elif wan_index is not None and record.get('Index') == wan_index:
                    records_to_remove.append(wan_id)

                # 3. IP 匹配并进一步检查类型
                elif record.get('_ip') == self.ip:
                    record_service_type = record.get('ServiceType', '')
                    record_wan_type = record.get('WANType', '')
                    record_vlan = record.get('VLAN', '')

                    if (wan_name.endswith(f'_{record_service_type}') or
                        wan_name.endswith(f'_{record_wan_type}') or
                        (record_vlan and f'VID_{record_vlan}' in wan_name)):
                        records_to_remove.append(wan_id)

            # 执行删除
            for wan_id in records_to_remove:
                del history[wan_id]
                removed_count += 1
                log.info(f"已删除WAN配置记录: {wan_id}")

        except Exception as e:
            log.warning(f"删除WAN配置记录时出错: {e}")
        
        return removed_count

    def _delete_stored_wan_parameters(self, connection_name: str = None, wan_index: int = None) -> bool:
        """
        根据WAN信息删除对应的存储记录
        
        参数:
        connection_name: WAN连接名称，如 "3_TR069_INTERNET_R_VID_200"
        wan_index: WAN索引号，如 3
        
        返回:
        bool: 是否成功删除存储记录
        """
        try:
            deleted = False
            
            # 如果提供了连接名称，解析其中的信息
            if connection_name:
                parts = connection_name.split('_')
                if len(parts) >= 1:
                    wan_index = int(parts[0]) if parts[0].isdigit() else None
            
            # 如果有WAN索引，查找并删除对应的存储记录
            if wan_index is not None:
                # 遍历存储历史记录，查找匹配的WAN索引
                wan_ids_to_delete = []
                for wan_id, stored_params in self.__class__.__wan_parameters_history.items():
                    if stored_params.get('_wan_index') == wan_index:
                        wan_ids_to_delete.append(wan_id)
                
                # 删除匹配的记录
                for wan_id in wan_ids_to_delete:
                    del self.__class__.__wan_parameters_history[wan_id]
                    log.info(f"已删除WAN存储记录: {wan_id}")
                    deleted = True
                    
                if not deleted:
                    log.info(f"未找到索引为 {wan_index} 的WAN存储记录")
            else:
                log.warning("无法确定WAN索引，未删除任何存储记录")
                
            return deleted
            
        except Exception as e:
            log.error(f"删除WAN存储记录时发生错误: {e}")
            return False

    def _find_matching_wan_records(self, connection_name_or_index) -> list:
        """
        根据连接名或索引查找匹配的WAN存储记录
        
        参数：
            connection_name_or_index: 连接名或索引号，支持格式如 "3_TR069_R_VID_200"
            
        返回：
            匹配的WAN记录ID列表
        """
        matched_ids = []
        
        try:
            # 解析输入参数
            input_str = str(connection_name_or_index).strip()
            
            # 如果是数字索引，尝试匹配Index字段
            if input_str.isdigit():
                target_index = int(input_str)
                log.debug(f"按数字索引查找WAN记录: {target_index}")
                for wan_id, wan_data in self.__class__.__wan_parameters_history.items():
                    if wan_data.get('Index') == target_index:
                        matched_ids.append(wan_id)
                        log.debug(f"找到匹配的WAN记录: {wan_id}")
            else:
                # 尝试作为连接名匹配
                connection_name = input_str
                log.debug(f"解析连接名: {connection_name}")
                
                # 提取连接名中的关键信息
                # 支持格式: "3_TR069_R_VID_200" 或 "3_TR069_INTERNET_R_VID_200"
                parts = connection_name.split('_')
                log.debug(f"连接名分割结果: {parts}")
                
                # 提取WAN索引（第一个部分）
                wan_index = None
                if parts[0].isdigit():
                    wan_index = int(parts[0])
                    log.debug(f"解析到WAN索引: {wan_index}")
                
                # 解析ServiceType（第二部分）
                service_type = ""
                if len(parts) > 1:
                    # 处理各种TR069相关类型
                    if parts[1] == "TR069":
                        service_type = "TR069"
                    elif parts[1].startswith("TR069"):
                        service_type = parts[1]  # 如 TR069_INTERNET, TR069_VOICE 等
                    else:
                        service_type = parts[1]  # INTERNET, VOICE, IPTV 等
                    log.debug(f"解析到ServiceType: {service_type}")
                
                # 解析WAN模式和VLAN ID
                wan_mode = ""
                # 新逻辑：解析 VID + VLAN ID（两段）
                vlan_id = None
                for i, part in enumerate(parts):
                    if part == "VID" and i + 1 < len(parts):
                        try:
                            vlan_id = int(parts[i + 1])
                            wan_mode = parts[i - 1] if i > 0 else ""
                            log.debug(f"解析到VLAN ID: {vlan_id}, Mode: {wan_mode}")
                        except ValueError:
                            pass                
                # 解析Mode（R=Router, B=Bridge）
                expected_mode = None
                if wan_mode:
                    if wan_mode == "R":
                        expected_mode = "Router"
                    elif wan_mode == "B":
                        expected_mode = "Bridge"
                    log.debug(f"解析到WAN模式: {wan_mode} -> {expected_mode}")
                
                # 在存储的记录中查找匹配项
                log.debug(f"开始在{len(self.__class__.__wan_parameters_history)}条记录中查找匹配项")
                for wan_id, wan_data in self.__class__.__wan_parameters_history.items():
                    log.debug(f"检查记录 {wan_id}: {wan_data}")
                    
                    # 检查VLAN ID匹配
                    if vlan_id is not None:
                        stored_vlan = wan_data.get('VLANID') or wan_data.get('VLAN')
                        try:
                            stored_vlan = int(stored_vlan)
                        except:
                            stored_vlan = None

                        if stored_vlan != vlan_id:
                            log.debug(f"VLAN ID不匹配: 期望{vlan_id}, 实际{stored_vlan}")
                            continue

                        log.debug(f"VLAN ID匹配: {vlan_id}")

                    
                    # 检查ServiceType匹配
                    if service_type:
                        stored_service_type = wan_data.get('ServiceType', '')
                        # 支持部分匹配，如TR069_INTERNET匹配TR069
                        type_match = (service_type == stored_service_type or
                                    (service_type == "TR069" and stored_service_type.startswith("TR069")) or
                                    (stored_service_type.startswith("TR069") and service_type.startswith("TR069")))
                        if not type_match:
                            log.debug(f"ServiceType不匹配: 期望{service_type}, 实际{stored_service_type}")
                            continue
                        log.debug(f"ServiceType匹配: {service_type}")
                    
                    # 检查Mode匹配
                    if expected_mode:
                        stored_mode = wan_data.get('Mode', '')
                        if stored_mode.lower() != expected_mode.lower():
                            log.debug(f"Mode不匹配: 期望{expected_mode}, 实际{stored_mode}")
                            continue
                        log.debug(f"Mode匹配: {expected_mode}")
                    
                    # 如果所有条件都匹配，添加到结果中
                    matched_ids.append(wan_id)
                    log.debug(f"找到匹配的WAN记录: {wan_id}")
                
                # 如果没有通过解析匹配到，尝试直接匹配连接名（备用方案）
                if not matched_ids:
                    log.debug("解析匹配未找到结果，尝试备用匹配方案")
                    for wan_id, wan_data in self.__class__.__wan_parameters_history.items():
                        # 查找包含连接名的记录
                        if ('_connection_name' in wan_data and
                            connection_name in wan_data['_connection_name']):
                            matched_ids.append(wan_id)
                            log.debug(f"通过备用方案找到匹配的WAN记录: {wan_id}")
            
            log.info(f"连接名 '{connection_name_or_index}' 匹配到 {len(matched_ids)} 条WAN记录: {matched_ids}")
        
        except Exception as e:
            log.error(f"查找匹配的WAN记录时出错: {e}")
        
        return matched_ids

    # def _remove_wan_parameters_records(self, connection_name_or_index) -> int:
    #     """
    #     根据连接名或索引删除对应的WAN参数存储记录
        
    #     参数：
    #         connection_name_or_index: 连接名或索引号
            
    #     返回：
    #         删除的记录数量
    #     """
    #     removed_count = 0
        
    #     try:
    #         # 查找匹配的记录
    #         matched_ids = self._find_matching_wan_records(connection_name_or_index)
            
    #         # 删除匹配的记录
    #         for wan_id in matched_ids:
    #             if wan_id in self.__class__.__wan_parameters_history:
    #                 del self.__class__.__wan_parameters_history[wan_id]
    #                 removed_count += 1
    #                 log.info(f"已删除WAN存储记录: {wan_id}")
        
    #     except Exception as e:
    #         log.error(f"删除WAN存储记录时出错: {e}")
        
    #     return removed_count

    def Network_WAN_Set(self, input_overrides: dict) -> dict:
        default_input = self.get_default_input()

        # 检查非法字段
        invalid_keys = [key for key in input_overrides if key not in default_input]
        if invalid_keys:
            log.warning(f"发现无效字段：{invalid_keys}")

        # 修复参数合并逻辑
        final_parameters = default_input.copy()
        final_parameters.update(input_overrides)
        self.last_wan_parms = final_parameters.copy()  # 保存副本到实例变量

        # 只有在添加WAN时才存储参数，删除操作不存储
        wan_id = None
        method = final_parameters.get('Method', '').lower()
        if method in ['add', 'create']:
            wan_id = self._store_wan_parameters(final_parameters)
            log.info(f"已存储WAN参数，ID: {wan_id}")
        else:
            log.debug(f"跳过WAN参数存储，操作类型: {method}")

        params = {
            "command": f"Device.{VENDOR_PREFIX}CreateWAN()",
            "input": final_parameters,
            "optional": {
                "proto": "web"
            }
        }

        log.info(f"正在执行 [{final_parameters.get('Method', '未知')}] 操作：\n{json.dumps(params, indent=2)}")

        try:
            response = self.ubus.Ubus_Call(
                ubus_object=ubus_base.UBUS_SERVICE_BBFDM,
                ubus_func="operate",
                params=params
            )
            result_flag = response[1]["results"][0]["output"][0]["Result"]
            # log.info(f'result_flag:{result_flag}')

            if result_flag != "OK":
                # log.error(f"WAN 配置失败：{result_flag}")
                return {"success": False, "error_msg": f"WAN 配置失败: {result_flag}", "response": response}

            log.info("WAN 配置成功")
            # 在成功响应中也包含WAN ID（如果存在）
            result = {"success": True, "error_msg": "", "response": response}
            if wan_id:
                result["wan_id"] = wan_id
            return result

        except Exception as e:
            log.error(f"配置异常，详细信息：{e}")
            return {"success": False, "error_msg": str(e), "response": None}

    def get_all_base_paths(self):
        paths = [
            f"Device.WiFi.{VENDOR_PREFIX}Mapping_2G",
            f"Device.WiFi.{VENDOR_PREFIX}Mapping_5G",
            "Device.WiFi.SSID.",
            "Device.Ethernet.",
            "Device.IP.Interface.",
            "Device.PPP.",
            "Device.Bridging.Bridge.",
            "Device.DHCPv4.",
            "Device.DHCPv6.",
            "Device.DNS.Client.Server.",
            "Device.DSLite.InterfaceSetting.",
            "Device.NAT."
        ]

        params = {
            "paths": paths,
            "optional": {"proto": "web"}
        }

        return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)

    def Network_WAN_Get(self, wan_name):
        result = self.get_all_base_paths()
        info = self.get_wan_info(result, wan_name)
        return info

    def ubus_wan_delete(self, Connection_Name_or_Index):
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
        n_ret = ERR_FAIL

        try:
            # 保存原始输入参数，用于后续删除存储记录
            original_input = Connection_Name_or_Index
            connection_name = Connection_Name_or_Index.strip()

            num = Connection_Name_or_Index
            match = re.match(r"(\d+)", connection_name)
            if (match):
                num = int(match.group(1))

            delete_config = {
                "Method": "Delete",
                "Index": num,
            }

            # {'results': [{'data': '', 'output': [{'Result': 'OK'}], 'path': 'Device.X_SDMC_CreateWAN()'}]}
            # 默认成功 失败 = raise
            ret_api = self.Network_WAN_Set(delete_config)
            if ret_api["success"]:
                ret = ERR_SUCCESS
                
                # 在WAN删除成功后，删除对应的存储配置记录
                try:
                    removed_count = self._remove_wan_parameters_records(original_input)
                    if removed_count > 0:
                        log.info(f"已删除 {removed_count} 条对应的WAN存储配置记录")
                    else:
                        log.info(f"未找到对应的WAN存储配置记录: {original_input}")
                except Exception as storage_e:
                    # 存储记录删除失败不影响WAN删除操作的结果
                    log.warning(f"删除WAN存储配置记录时出错: {storage_e}")
                    
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(ret_api["error_msg"])

            n_ret = ERR_SUCCESS

        except Exception as e:
            raise

        return n_ret

    def ubus_wan_get(self, Connection_Name):
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

        try:
            info = self.Network_WAN_Get(Connection_Name)

        except Exception as e:
            raise

        return info

    def ubus_wan_get_connection_names(self):
        """
        功能描述：获取 WAN 配置 (Connection Name List)

        返回值：Connection Name List
        eg  ['3_TR069_INTERNET_R_VID_200', '4_VOICE_R_VID_335', '5_IPTV_R_VID_123']

        Example:
        | ${names} |  Ubus_Network_WAN_Get_Connection_Names  |

        """
        names = []

        try:
            datas = self.get_all_base_paths()
            data = datas[1]

            names = self.get_interface_names(data)

        except Exception as e:
            log.exception(str(e))

        return names

    def ubus_wan_modify_nat(self, wan_name: str, enable: str) -> int:
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
        ret = ERR_FAIL
        
        try:
            # 参数验证
            if not wan_name or not enable:
                log.error("wan_name和enable参数不能为空")
                return ERR_FAIL
                
            if enable not in ["0", "1"]:
                log.error("enable参数必须是'0'或'1'")
                return ERR_FAIL
            
            # 查找匹配的WAN记录
            matched_ids = self._find_matching_wan_records(wan_name)
            if not matched_ids:
                log.error(f"未找到WAN配置记录: {wan_name}")
                return ERR_FAIL
            
            # 获取第一个匹配的记录
            wan_id = matched_ids[0]
            stored_params = self.get_wan_parameters_by_id(wan_id)
            if not stored_params:
                log.error(f"获取WAN参数失败: {wan_id}")
                return ERR_FAIL
            
            # 获取默认参数字典
            modify_params = self.get_default_input()
            
            # 从存储的配置中复制所有相关参数
            # 复制所有非元数据字段
            for key, value in stored_params.items():
                if not key.startswith('_') and key in modify_params:
                    modify_params[key] = value
            
            # 设置修改操作的特定参数
            modify_params["Method"] = "Modify"
            
            # 从wan_name中解析出Index参数（从"3_TR069_INTERNET_R_VID_200"中解析出"3"）
            wan_index = None
            if wan_name:
                # 使用正则表达式匹配wan_name开头的数字
                import re
                match = re.match(r'^(\d+)', wan_name.strip())
                if match:
                    wan_index = int(match.group(1))
            
            if wan_index is not None:
                modify_params["Index"] = wan_index
                log.debug(f"从wan_name '{wan_name}' 解析出Index: {wan_index}")
            else:
                log.warning(f"无法从wan_name '{wan_name}' 中解析出Index")
            
            modify_params["Nat"] = int(enable)
            
            log.info(f"正在修改WAN {wan_name} 的NAT配置为: {enable}")
            log.info(f"修改参数: {json.dumps(modify_params, indent=2, ensure_ascii=False)}")
            
            # 调用Network_WAN_Set进行修改
            wan_set = self.Network_WAN_Set(modify_params)
            if wan_set["success"]:
                log.info(f"WAN {wan_name} NAT配置修改成功")
                ret = ERR_SUCCESS
            else:
                log.error(f"WAN {wan_name} NAT配置修改失败: {wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])
                
        except Exception as e:
            log.exception(str(e))
            raise
            
        return ret


    def ubus_set_router_ipoe_dhcp_ipv4(self, vlan_id, wan_server_type="INTERNET", lan_bind_port=0, mtu=1500,
                                                   vlan_priority=0, multicastvlan_id="", Option60Vendor="",
                                                   Option120Enable="", Option121Enable=""):
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
        
        multicastvlan_id="" : 组播VLAN ID，默认为空字符串
        
        Option60Vendor="": DHCP Option60 的厂商字符串，默认空字符串
        
        Option120Enable=0: 启 DHCP Option120，默认0（关闭），1为开启
        
        Option121Enable=0: 启 DHCP Option121，默认0（关闭），1为开启

        【返回值】
        0: 成功
        1：失败

        Example:

        1、vlan:200,type:INTERNET;绑定Lan 1端口
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1 |

        2、vlan:200,type:INTERNET;绑定Lan 1和Lan 4端口和2.4GWiFi
        | Ubus_Network_WAN_Set_Router_IPoE_DHCP_IPv4 | 200 | 3 | 1&&8&&256 |
        """

        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            log.info(portbind_num)

            Router_IPoE_DHCP_IPv4_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "ServiceType": f"{wan_server_type}",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPv4Type": "Dynamic",
                "IPProtocol": "IPv4",
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority),
            }
            if multicastvlan_id != "":
                Router_IPoE_DHCP_IPv4_config["MulticastVLANID"] = int(multicastvlan_id)
            if Option60Vendor:
                hex_option60 = Option60Vendor.encode("ascii").hex()
                Router_IPoE_DHCP_IPv4_config["Option60Vendor"] = hex_option60
            if Option120Enable:
                Router_IPoE_DHCP_IPv4_config["Option120Enable"] = Option120Enable
            if Option121Enable:
                Router_IPoE_DHCP_IPv4_config["Option121Enable"] = Option121Enable

            wan_set = self.Network_WAN_Set(Router_IPoE_DHCP_IPv4_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoe_static_ipv4(self, vlan_id, wan_server_type="INTERNET", ipv4_address='172.18.18.43',
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)

            Router_IPoE_Static_IPv4_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv4",
                "ServiceType": f"{wan_server_type}",
                "IPv4Address": f"{ipv4_address}",
                "IPv4Gateway": f"{ipv4_gateway}",
                "IPv4Netmask": f"{ipv4_subnetMask}",
                "IPv4PrimaryDNS": f"{ipv4_primary_DNS}",
                "IPv4SecondDNS": f"{ipv4_second_DNS}",
                "IPv4Type": "Static",
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_Static_IPv4_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_IPoE_Static_IPv4_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoe_static_ipv6(self, vlan_id, wan_server_type="INTERNET",
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)

            Router_IPoE_Static_IPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv6Address": f"{ipv6_address}",
                "IPv6Gateway": f"{ipv6_gateway}",
                "IPv6Prefix": f"{ipv6_perfix}",
                "IPv6PrimaryDNS": f"{ipv6_primary_DNS}",
                "IPv6SecondDNS": f"{ipv6_second_DNS}",
                "IPv6Type": "Static",
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_Static_IPv6_config["MulticastVLANID"] = int(multicastvlan_id)

            wan_set = self.Network_WAN_Set(Router_IPoE_Static_IPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoE_dhcp_ipv6_slaac(self, vlan_id, wan_server_type="INTERNET", lan_bind_port=0,
                                             DSLiteEnable=0, PrefixDelegation=1, mtu=1500,
                                             vlan_priority=0, multicastvlan_id=""):
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_IPoE_DHCP_IPv6_SLAAC_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv6Type": "Dynamic",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 0,
                "SLAAC": 1,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_DHCP_IPv6_SLAAC_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_IPoE_DHCP_IPv6_SLAAC_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoE_dhcp_ipv4ipv6_slaac(self, vlan_id, wan_server_type="INTERNET", lan_bind_port=0,
                                                 DSLiteEnable=0, PrefixDelegation=1, mtu=1500,
                                                 vlan_priority=0, multicastvlan_id=""):
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

        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_IPoE_DHCP_IPv4IPv6_SLAAC_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "IPv6Type": "Dynamic",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 0,
                "SLAAC": 1,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_DHCP_IPv4IPv6_SLAAC_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_IPoE_DHCP_IPv4IPv6_SLAAC_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoE_dhcp_ipv6_dhcpv6(self, vlan_id, wan_server_type="INTERNET", lan_bind_port=0,
                                              DSLiteEnable=0, PrefixDelegation=1, mtu=1500,
                                              vlan_priority=0, multicastvlan_id=""):
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_IPoE_DHCP_IPv6_DHCPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv6Type": "Dynamic",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 1,
                "SLAAC": 0,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_DHCP_IPv6_DHCPv6_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_IPoE_DHCP_IPv6_DHCPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoe_dhcp_ipv4_ipv6_dhcpv6(self, vlan_id, wan_server_type="INTERNET", lan_bind_port=0,
                                              DSLiteEnable=0, PrefixDelegation=1, mtu=1500, vlan_priority=0, multicastvlan_id=""):
        """
        创建路由 DHCP IPv4&IPv6 双栈 有状态 WAN

        参数：
            vlan_id : VLAN ID
            wan_server_type : server type 类型，默认INTERNET，另外 TR069 / VOICE / INTERNET / TR069_VOICE / TR069_INTERNET / VOICE_INTERNET / TR069_VOICE_INTERNET / OTHER / IPTV
            lan_bind_port : 绑定的 LAN 口，可以是数字或 '1&&8' 这种组合
            DSLiteEnable : DSLite 开关，0=关闭，1=开启
            PrefixDelegation : PrefixDelegation 开关，1=开启，0=关闭
            mtu : MTU 值
            vlan_priority : VLAN 优先级 0-7

        返回：
            0: 成功
            1: 失败
        """
        ret = ERR_FAIL
        try:
            # 处理 LAN 绑定端口
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                portbind_num = sum(int(num) for num in numbers)
            else:
                portbind_num = int(lan_bind_port)

            Router_IPoE_DHCP_IPv4IPv6_DHCPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "IPv6Type": "Dynamic",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 1,
                "SLAAC": 0,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_DHCP_IPv4IPv6_DHCPv6_config["MulticastVLANID"] = int(multicastvlan_id)

            wan_set = self.Network_WAN_Set(Router_IPoE_DHCP_IPv4IPv6_DHCPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_pppoe_ipv4(self, vlan_id, wan_server_type="INTERNET", pppoe_username=111,
                                   pppoe_password=111, lan_bind_port=0, mtu=1492,
                                   vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创创建路由PPPoE IPv4 WAN

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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_PPPoE_IPv4_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "PPPoE": "1",
                "IPProtocol": "IPv4",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "Username": f"{pppoe_username}",
                "Password": f"{pppoe_password}",
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_PPPoE_IPv4_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_PPPoE_IPv4_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_pppoe_ipv6_dhcpv6(self, vlan_id, wan_server_type="INTERNET", pppoe_username=111,
                                          pppoe_password=111, DSLiteEnable=0, PrefixDelegation=1,
                                          lan_bind_port=0, mtu=1492,
                                          vlan_priority=0, multicastvlan_id=""):
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_PPPoE_IPv6_DHCPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "PPPoE": "1",
                "IPProtocol": "IPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "Username": f"{pppoe_username}",
                "Password": f"{pppoe_password}",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 1,
                "SLAAC": 0,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_PPPoE_IPv6_DHCPv6_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_PPPoE_IPv6_DHCPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_pppoe_ipv6_slaac(self, vlan_id, wan_server_type="INTERNET", pppoe_username=111,
                                         pppoe_password=111, DSLiteEnable=0, PrefixDelegation=1,
                                         lan_bind_port=0, mtu=1492,
                                         vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创建路由DHCP IPv6单栈  pppoe  无状态 WAN

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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_PPPoE_IPv6_SLAAC_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "PPPoE": "1",
                "IPProtocol": "IPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "Username": f"{pppoe_username}",
                "Password": f"{pppoe_password}",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 0,
                "SLAAC": 1,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_PPPoE_IPv6_SLAAC_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_PPPoE_IPv6_SLAAC_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_pppoe_ipv4ipv6_dhcpv6(self, vlan_id, wan_server_type="INTERNET", pppoe_username=111,
                                              pppoe_password=111, DSLiteEnable=0, PrefixDelegation=1,
                                              lan_bind_port=0, mtu=1492,
                                              vlan_priority=0, multicastvlan_id=""):
        """
        【功能描述】：创建路由DHCP IPv4IPv6 双栈  pppoe  有状态 WAN

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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_PPPoE_IPv4IPv6_DHCPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "PPPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "IPv6Type": "Dynamic",
                "Username": f"{pppoe_username}",
                "Password": f"{pppoe_password}",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 1,
                "SLAAC": 0,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_PPPoE_IPv4IPv6_DHCPv6_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_PPPoE_IPv4IPv6_DHCPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_pppoe_ipv4ipv6_slaac(self, vlan_id, wan_server_type="INTERNET", pppoe_username=111,
                                            pppoe_password=111, DSLiteEnable=0, PrefixDelegation=1,
                                            lan_bind_port=0, mtu=1492,
                                            vlan_priority=0, multicastvlan_id=""):
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Router_PPPoE_IPv4IPv6_SLAAC_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "PPPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Type": "Dynamic",
                "IPv6Type": "Dynamic",
                "Username": f"{pppoe_username}",
                "Password": f"{pppoe_password}",
                "DSLiteEnable": f"{int(DSLiteEnable)}",
                "DHCPv6PrefixDelegation": f"{int(PrefixDelegation)}",
                "DHCPv6AddressAssignment": 0,
                "SLAAC": 1,
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_PPPoE_IPv4IPv6_SLAAC_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_PPPoE_IPv4IPv6_SLAAC_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_bridge(self, vlan_id, wan_server_type="IPTV", lan_bind_port=1, multicastvlan_id="",
                        vlan_priority=0):
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                portbind_num = sum(int(num) for num in numbers)
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)
            Bridge_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "bridge",
                "ServiceType": f"{wan_server_type}",
                "PortBind": portbind_num,
                "VLANPriority": int(vlan_priority)
            }

            if multicastvlan_id != "":
                Bridge_config["MulticastVLANID"] = int(multicastvlan_id)

            wan_set = self.Network_WAN_Set(Bridge_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_set_router_ipoe_static_ipv4ipv6(self, vlan_id, wan_server_type="INTERNET",
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
        ret = ERR_FAIL
        try:
            if '&&' in str(lan_bind_port):
                numbers = lan_bind_port.split('&&')
                final_sum = sum(int(num) for num in numbers)
                portbind_num = final_sum
            else:
                portbind_num = int(lan_bind_port)

            print(portbind_num)

            Router_IPoE_Static_IPv4IPv6_config = {
                "Method": "add",
                "VLAN": f"{int(vlan_id)}",
                "Mode": "router",
                "PortBind": portbind_num,
                "IPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": f"{wan_server_type}",
                "IPv4Address": f"{ipv4_address}",
                "IPv4Gateway": f"{ipv4_gateway}",
                "IPv4Netmask": f"{ipv4_subnetMask}",
                "IPv4PrimaryDNS": f"{ipv4_primary_DNS}",
                "IPv4SecondDNS": f"{ipv4_second_DNS}",
                "IPv4Type": "Static",
                "IPv6Address": f"{ipv6_address}",
                "IPv6Gateway": f"{ipv6_gateway}",
                "IPv6Prefix": f"{ipv6_perfix}",
                "IPv6PrimaryDNS": f"{ipv6_primary_DNS}",
                "IPv6SecondDNS": f"{ipv6_second_DNS}",
                "IPv6Type": "Static",
                "MTU": int(mtu),
                "VLANPriority": int(vlan_priority)
            }
            if multicastvlan_id != "":
                Router_IPoE_Static_IPv4IPv6_config["MulticastVLANID"] = int(multicastvlan_id)
            wan_set = self.Network_WAN_Set(Router_IPoE_Static_IPv4IPv6_config)
            if wan_set["success"]:
                ret = ERR_SUCCESS
            else:
                # log.error(f"wan 设置失败：{wan_set['error_msg']}")
                raise Exception(wan_set["error_msg"])

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_wan_delete_all(self):
        """
        【功能描述】： 删除所有存在的WAN

        【返回值】
        0: 成功
        1：失败

        Example:
            | Ubus_Network_WAN_delete_all |
        """
        ret = ERR_FAIL
        try:
            wan_names = self.ubus_wan_get_connection_names()
            if wan_names:
                for i in wan_names:
                    self.ubus_wan_delete(i)
                    log.info(f"已经删除{i} WAN")
                
                # 清理所有存储的WAN参数记录
                # try:
                #     history = self.get_wan_parameters_history()
                #     if history:
                #         # 清空所有历史记录
                #         self.__class__.__wan_parameters_history.clear()
                #         log.info(f"已清理 {len(history)} 条WAN存储配置记录")
                # except Exception as storage_e:
                #     log.warning(f"清理WAN存储配置记录时出错: {storage_e}")
                
                ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_delete_specify_type_wan(self, wan_type):
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
        ret = ERR_FAIL
        try:
            wan_names = self.ubus_wan_get_connection_names()
            log.info(wan_names)
            if wan_names:
                for i in wan_names:
                    if f"{wan_type}" in i:
                        self.ubus_wan_delete(i)
    
                        log.info(f"已经删除{i} WAN")
                        ret = ERR_SUCCESS
                
            else:
                log.info("没有WAN存在")

            if ret == 1:
                log.info(f"不存在{wan_type}类型的WAN")

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def ubus_delete_specify_wan(self, wan_type, wan_mode, vlan_id):
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
        ret = ERR_FAIL
        try:
            if wan_mode == "Router" or wan_mode == "R":
                wan_mode = "R"
            elif wan_mode == "Bridge" or wan_mode == "B":
                wan_mode = "B"
            else:
                log.info(f"{wan_mode}出错")
            wan_names = self.ubus_wan_get_connection_names()
            log.info(wan_names)
            if wan_names:
                for i in wan_names:
                    if f"{wan_type}_{wan_mode}_VID_{vlan_id}" in i:
                        self.ubus_wan_delete(i)
                        log.info(f"已经删除{i} WAN")
                        ret = ERR_SUCCESS
                        break            
            else:
                log.info("没有WAN存在")

            if ret == 1:
                log.info(f"不存在{wan_type}_{wan_mode}_VID_{vlan_id}类型的WAN")

        except Exception as e:
            log.exception(str(e))
            raise

        return ret

    def Debug_test(self):
        try:
            self.ubus.Ubus_Login(username=self.username, password=self.password)
            # data = self.get_all_base_paths()
            # data = data[1]
            # names = self.get_interface_names(data)
            # info = self.Network_WAN_Get(names)
            self.ubus_wan_delete_all()
            self.ubus_set_router_ipoe_dhcp_ipv4(wan_server_type="TR069", vlan_id="200")
            print(self.__class__.__wan_parameters_history)
            # self.ubus_delete_specify_type_wan("INTERNET")
            info = self._find_matching_wan_records("3_TR069_R_VID_200")
            print(info)
            # self.Ubus_WAN_Delete("3")

        except Exception as e:
            print("配置失败：", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)

            # 桥接wan配置
            Bridge_config = {
                "Method": "add",
                "VLAN": 200,
                "Mode": "bridge",
                "ServiceType": "INTERNET",
                "PortBind": "2048",  # 端口绑定对应关系参考portbind_flag
            }

            # tr069，语音只需要修改ServiceType即可
            Dhcp_config = {
                "Method": "add",
                "VLAN": 200,
                "Mode": "router",
                "ServiceType": "INTERNET",
                "PortBind": "0",
                "IPoE": "1",
                "IPv4Type": "Dynamic",
                "IPProtocol": "IPv4",
            }

            # 静态ipv4和ipv6的配置，根据需要修改
            Static_config = {
                "Method": "add",
                "VLAN": 200,
                "Mode": "router",
                "PortBind": "0",
                "IPoE": "1",
                "IPProtocol": "IPv4AndIPv6",
                "ServiceType": "INTERNET",
                "IPv4Address": "172.18.18.206",
                "IPv4Gateway": "172.18.18.1",
                "IPv4Netmask": "255.255.255.0",
                "IPv4PrimaryDNS": "8.8.8.8",
                "IPv4SecondDNS": "8.8.8.8",
                "IPv4Type": "Static",
                "IPv6Address": "2001:170:101:0:6203:47ff:fe40:e001/64",
                "IPv6Gateway": "2001:170:101:0::1",
                "IPv6Prefix": "2001:170:111:75::/64",
                "IPv6PrimaryDNS": "2001:4860:4860::8888",
                "IPv6SecondDNS": "2001:4860:4860::8844",
                "IPv6Type": "Static"
            }

            # pppoe wan
            pppoe_config = {
                "Method": "add",
                "VLAN": 200,
                "Mode": "router",
                "ServiceType": "INTERNET",
                "PortBind": "0",
                "IPoE": "1",
                "IPv4Type": "Dynamic",
                "IPProtocol": "IPv4",
                "Username": "111",
                "Password": "111"
            }

            # 语音wan配置
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
            ret = self.Network_WAN_Set(Iptv_config)
            print(ret)
            datas = self.get_all_base_paths()
            data = datas[1]
            names = self.get_interface_names(data)
            info = self.Network_WAN_Get(names)
            print(info)

        except Exception as e:
            print(str(e))


if __name__ == '__main__':
    # multiWan = multiWanManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    multiWan = multiWanManager(ip="192.168.29.1", username="sdmc", password="1234")
    multiWan.Debug_test()

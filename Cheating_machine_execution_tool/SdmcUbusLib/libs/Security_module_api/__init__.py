"""
设备Status相关api
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.Security_module_api.enable_telnet import SdmcUbusLibEnableTelnet
from SdmcUbusLib.libs.Security_module_api.ipfilter import IpfilterManager
from SdmcUbusLib.libs.Security_module_api.dmz import DmzManager
from SdmcUbusLib.libs.Security_module_api.urlfilter import UrlfilterManager
from SdmcUbusLib.libs.Security_module_api.macfilter import MacfilterManager
from SdmcUbusLib.libs.Security_module_api.parentcontrol import ParentalControlManager
from SdmcUbusLib.libs.Security_module_api.accesscontrol import AccessControlManager
from SdmcUbusLib.libs.Security_module_api.portforward import PortForwardManager
from SdmcUbusLib.libs.Security_module_api.porttrigger import PortTriggerManager
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcSecurityLib(object):
    """
    测试库 demo for class
    """

    def __init__(self):
        """
        """

        self._get_self_keywords()
        self._init_ipfilter()
        self._init_dmz()
        self._init_urlfilter()
        self._init_macfilter()
        self._init_parental_control()
        self._init_access_control()
        self._init_port_forward()
        self._init_port_trigger()

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

    def _Ubus_Telnet_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.Telnet = SdmcUbusLibEnableTelnet()

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def _init_ipfilter(self):
        """
        初始化 ipfilter manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.Ipfilter = IpfilterManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_dmz(self):
        """
        初始化 dmz manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.Dmz = DmzManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_urlfilter(self):
        """
        初始化 urlfilter manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.ubus_urlfilter = UrlfilterManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_macfilter(self):
        """
        初始化 macfilter manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.Macfilter = MacfilterManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_parental_control(self):
        """
        初始化 parental control manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.ParentalControl = ParentalControlManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_access_control(self):
        """
        初始化 access control manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.AccessControl = AccessControlManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_port_forward(self):
        """
        初始化 port forward manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.PortForward = PortForwardManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def _init_port_trigger(self):
        """
        初始化 port trigger manager
        """
        ret = ERR_FAIL
        
        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname
            
            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password
            
            self.PortTrigger = PortTriggerManager(ip, username, password)
            
            ret = ERR_SUCCESS
            
        except Exception as e:
            log.exception(str(e))
        
        return ret

    def Ubus_set_macfilter_enable(self, enable):
        """
        功能描述： 设置 MAC Filter 开关状态
        参数：
        - enable: bool, True=启用, False=禁用
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_macfilter_enable | True |
        """
        try:
            self._init_macfilter()
            if enable=='True':
                result = self.Macfilter.enable_macfilter()
            else:
                result = self.Macfilter.disable_macfilter()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置 MAC Filter 开关失败: {str(e)}")

    def Ubus_set_macfilter_mode(self, mode):
        """
        功能描述： 设置 MAC Filter 黑白名单模式
        参数：
        - mode: str, "black"=黑名单, "white"=白名单
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_macfilter_mode | black |
        """
        try:
            self._init_macfilter()
            result = self.Macfilter.set_macfilter_mode(mode)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置 MAC Filter 模式失败: {str(e)}")

    def Ubus_add_macfilter_rule(self, mac_addr, description=""):
        """
        功能描述： 添加一条 MAC Filter 规则
        参数：
        - mac_addr: str, MAC 地址（如 F8:E4:3B:6F:0A:21）
        - description: str, 描述信息（如设备名），默认为空字符串
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_macfilter_rule | mac_addr=F8:E4:3B:6F:0A:21 | description=测试设备 |
        """
        try:
            self._init_macfilter()
            result = self.Macfilter.add_macfilter_rule(mac_addr, description)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 MAC Filter 规则失败: {str(e)}")

    def Ubus_modify_macfilter_rule(self, instance_id, new_mac, description=""):
        """
        功能描述： 修改一条已存在的 MAC Filter 规则
        参数：
        - instance_id: int/str, 要修改的规则实例编号（如 1 或 "1"）
        - new_mac: str, 新的 MAC 地址
        - description: str, 可选的描述信息，默认空字符串
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_modify_macfilter_rule | instance_id=1 | new_mac=F8:E4:3B:6F:0A:22 | description=修改后的设备 |
        """
        try:
            self._init_macfilter()
            result = self.Macfilter.modify_macfilter_rule(instance_id, new_mac, description)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"修改 MAC Filter 规则失败: {str(e)}")

    def Ubus_delete_macfilter_rule(self, instance_id):
        """
        功能描述： 删除一条 MAC Filter 规则
        参数：
        - instance_id: int/str, 要删除的规则实例编号（如 1、2…）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_macfilter_rule | instance_id=1 |
        """
        try:
            self._init_macfilter()
            result = self.Macfilter.delete_macfilter_rule(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除 MAC Filter 规则失败: {str(e)}")

    def Ubus_delete_all_macfilter_rules(self):
        """
        功能描述： 删除所有 MAC Filter 规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_macfilter_rules |
        """
        try:
            self._init_macfilter()
            result = self.Macfilter.delete_all_macfilter_rules()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有 MAC Filter 规则失败: {str(e)}")

    def Ubus_set_ipfilter(self, value):
        """
        功能描述： 设置 ipfilter 开关状态
        参数：
        - value: str, "1"=启用, "0"=禁用或其他值
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_ipfilter | 1 |
        """
        try:
            self._init_ipfilter()
            result = self.Ipfilter.set_ipfilter(value)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置 ipfilter 失失败: {str(e)}")

    def Ubus_add_ipfilter_rule(self, description="", source_ip="", dest_ip="", source_port=None, dest_port=None,
                              ip_version=4, protocol="TCP", source_interface="", direction="1"):
        """
        功能描述： 添加一条 IPFilter 规规则
        参数：
        - description: 描述信息
        - source_ip: 源 IP 地址
        - dest_ip: 目的 IP 地址
        - source_port: 源端口（int）
        - dest_port: 目的端口（int）
        - ip_version: IP 版数，默认4
        - protocol: 协议类型，默认"TCP"
        - source_interface: 类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3"
        - direction: 方向，默认"1"（入方向），"0"为outcoming
        返回：新增规则 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_ipfilter_rule | description=测试规则 | source_ip=192.168.1.100 | dest_ip=192.168.1.200 | protocol=TCP |
        """
        try:
            self._init_ipfilter()
            result = self.Ipfilter.add_ipfilter_rule(
                description=description,
                source_ip=source_ip,
                dest_ip=dest_ip,
                source_port=source_port,
                dest_port=dest_port,
                ip_version=ip_version,
                protocol=protocol,
                source_interface=source_interface,
                direction=direction
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 IPFilter 规规则失败: {str(e)}")

    def Ubus_delete_all_ipfilter_rules(self):
        """
        功能描述： 删除所有 IPFilter 规规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_ipfilter_rules |
        """
        try:
            self._init_ipfilter()
            result = self.Ipfilter.delete_all_ipfilter_rules()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有 IPFilter 规规则失败: {str(e)}")

    def Ubus_add_dmz_entry(self, wan_name="", enable_dmz="1", lan_host_addr=""):
        """
        功能描述： 添加一条 DMZ 条目
        参数：
        - wan_name: WAN 接口名称，类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3"
        - enable_dmz: 是否启用 DMZ，"1"=启用，"0"=禁用
        - lan_host_addr: LAN 主机 IP 地址
        返回：新增条目 instance 编号（int 类型）
        
        示例：
            | ${entry_id} | Ubus_add_dmz_entry | wan_name=3_INTERNET_B_VID_200 | enable_dmz=1 | lan_host_addr=192.168.1.100 |
        """
        try:
            self._init_dmz()
            result = self.Dmz.add_dmz_entry(
                wan_name=wan_name,
                enable_dmz=enable_dmz,
                lan_host_addr=lan_host_addr
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 DMZ 条目失败: {str(e)}")

    def Ubus_delete_all_dmz_entries(self):
        """
        功能描述： 删除所有 DMZ 条目
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_dmz_entries |
        """
        try:
            self._init_dmz()
            result = self.Dmz.delete_all_dmz_entries()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有 DMZ 条目失败: {str(e)}")

    def Ubus_modify_dmz_entry(self, instance_id="", enable_dmz=None, lan_host_addr=None, wan_name=None):
        """
        功能描述： 修改指定的 DMZ 条目
        参数：
        - instance_id: 要修改的 DMZ 条目实例 ID（整数或字符串）
        - enable_dmz: 是否启用 DMZ，布尔值 True/False（可选）
        - lan_host_addr: LAN 主机 IP 地址（可选）
        - wan_name: WAN 接口名称，类似"3_INTERNET_B_VID_200"（可选）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_modify_dmz_entry | instance_id=1 | enable_dmz=False | lan_host_addr=192.168.1.100 |
        """
        try:
            self._init_dmz()
            result = self.Dmz.modify_dmz_entry(
                instance_id=instance_id,
                enable_dmz=enable_dmz,
                lan_host_addr=lan_host_addr,
                wan_name=wan_name
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"修改 DMZ 条目失败: {str(e)}")

    def Ubus_set_urlfilter_enable(self, enable):
        """
        功能描述： 设置 URL Filter 开关状态
        参数：
        - enable: bool, True=启用, False=禁用
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_urlfilter_enable | True |
        """
        try:
            self._init_urlfilter()
            log.info("enable is " + str(enable))
            result = self.ubus_urlfilter.set_urlfilter_enable(enable)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置 URL Filter 开关失败: {str(e)}")

    def Ubus_add_urlfilter_entry(self, web_url):
        """
        功能描述： 添加一条 URL Filter 条目
        参数：
        - web_url: str, 要过滤的网站URL
        返回：新增条目 instance 编号（int 类型）
        
        示例：
            | ${entry_id} | Ubus_add_urlfilter_entry | web_url=www.example.com |
        """
        try:
            self._init_urlfilter()
            result = self.ubus_urlfilter.add_urlfilter_entry(web_url)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 URL Filter 条目失败: {str(e)}")

    def Ubus_modify_urlfilter_entry(self, instance_id, web_url):
        """
        功能描述： 编辑已存在的 URL Filter 条目
        参数：
        - instance_id: int, 要编辑的条目实例ID
        - web_url: str, 新的网站URL
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_edit_urlfilter_entry | instance_id=1 | web_url=www.newsite.com |
        """
        try:
            self._init_urlfilter()
            result = self.ubus_urlfilter.edit_urlfilter_entry(instance_id, web_url)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"编辑 URL Filter 条目失败: {str(e)}")

    def Ubus_delete_urlfilter_entry(self, instance_id):
        """
        功能描述： 删除指定的 URL Filter 条目
        参数：
        - instance_id: int, 要删除的条目实例ID
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_urlfilter_entry | instance_id=1 |
        """
        try:
            self._init_urlfilter()
            result = self.ubus_urlfilter.delete_urlfilter_entry(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除 URL Filter 条目失败: {str(e)}")

    def Ubus_delete_all_urlfilter_entries(self):
        """
        功能描述： 删除所有 URL Filter 条目
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_urlfilter_entries |
        """
        try:
            self._init_urlfilter()
            result = self.ubus_urlfilter.delete_all_urlfilter_entries()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有 URL Filter 条目失败: {str(e)}")

    def Ubus_set_parental_control_enable(self, enable):
        """
        功能描述： 设置家长控制使能开关
        参数：
        - enable: str, 'True'=启用, 'False'=禁用
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_parental_control_enable | True |
        """
        try:
            self._init_parental_control()
            result = self.ParentalControl.set_parental_control_enable(enable)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置家长控制开关失败: {str(e)}")

    def Ubus_add_parental_control_rule(self, source_mac, description="", start_time="00:00", stop_time="23:59", weekdays="Everyday"):
        """
        功能描述： 新增家长控制规则
        参数：
        - source_mac: str,, 源MAC地址（如 F8:E4:3B:6F:0A:21）
        - description: str, 规则描述，默认为空字符串
        - start_time: str, 开始时间，格式"HH:MM"，默认为"00:00"
        - stop_time: str, 结束时间，格式"HH:MM"，默认为"23:59"
        - weekdays: str, 星期几，默认为"Everyday"
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_parental_control_rule | source_mac=F8:E4:3B:6F:0A:21 | description=测试设备 | start_time=08:00 | stop_time=18:00 | weekdays=Monday |
        """
        try:
            self._init_parental_control()
            result = self.ParentalControl.add_parental_control_rule(
                source_mac=source_mac,
                description=description,
                start_time=start_time,
                stop_time=stop_time,
                weekdays=weekdays
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加家长控制规则失败: {str(e)}")

    def Ubus_edit_parental_control_rule(self, instance_id, source_mac=None, description=None, start_time=None, stop_time=None, weekdays=None):
        """
        功能描述： 编辑已存在的家长控制规则
        参数：
        - instance_id: int/str, 要编辑的规则实例 ID
        - source_mac: str, 源MAC地址（可选）
        - description: str, 规则描述（可选）
        - start_time: str, 开始时间（可选）
        - stop_time: str, 结束时间（可选）
        - weekdays: str, 星期几（可选）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_edit_parental_control_rule | instance_id=1 | description=修改后的描述 | stop_time=20:00 |
        """
        try:
            self._init_parental_control()
            result = self.ParentalControl.edit_parental_control_rule(
                instance_id=instance_id,
                source_mac=source_mac,
                description=description,
                start_time=start_time,
                stop_time=stop_time,
                weekdays=weekdays
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"编辑家长控制规则失败: {str(e)}")

    def Ubus_delete_parental_control_rule(self, instance_id):
        """
        功能描述： 删除指定的家长控制规则
        参数：
        - instance_id: int/str, 要删除的规则实例 ID
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_parental_control_rule | instance_id=1 |
        """
        try:
            self._init_parental_control()
            result = self.ParentalControl.delete_parental_control_rule(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除家长控制规则失败: {str(e)}")

    def Ubus_delete_all_parental_control_rules(self):
        """
        功能描述： 删除所有家长控制规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_parental_control_rules |
        """
        try:
            self._init_parental_control()
            result = self.ParentalControl.delete_all_parental_control_rules()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有家长控制规则失败: {str(e)}")

    def Ubus_telnet_enable(self):
        """
        功能描述： 开启OpenWrt telnet
        Returns: 成功返回True，失败返回False

        示例：
            | ${result} | Ubus_enable_telnet

        """
        self._Ubus_Telnet_init()
        enableinfo = self.Telnet.Enable_telnet()
        if enableinfo == False:
            raise ValueError("开启telnet失败")
        return enableinfo

    def Ubus_set_access_control_enable(self, enable):
        """
        功能描述： 设置访问控制使能开关
        参数：
        - enable: str, 'True'=启用, 'False'=禁用
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_set_access_control_enable | True |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.set_access_control_enable(enable)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"设置访问控制开关失败: {str(e)}")

    def Ubus_add_lan_access_rule(self, application="telnet,ssh,ftp", source_ip="0.0.0.0", description="", ip_version=4):
        """
        功能描述： 新增 LAN 侧访问控制规则
        参数：
        - application: str, 应用类型，如 "telnet,ssh,ftp" (默认为 "telnet,ssh,ftp")
        - source_ip: str, 源IP地址 (默认为 "0.0.0.0")
        - description: str, 规则描述 (默认为空字符串)
        - ip_version: int, IP版本，4表示IPv4，6表示IPv6 (默认为 4)
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_lan_access_rule | application=telnet,ssh,ftp | source_ip=192.168.1.100 | description=LAN侧规则测试 |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.add_lan_access_rule(
                application=application,
                source_ip=source_ip,
                description=description,
                ip_version=ip_version
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 LAN 侧访问控制规则失败: {str(e)}")

    def Ubus_add_wan_access_rule(self, application="telnet,ssh,http,https,icmp,ftp", source_ip="0.0.0.0", description="", ip_version=4, wan_index=3):
        """
        功能描述： 新增 WAN 侧访问控制规则
        参数：
        - application: str, 应用类型，如 "telnet,ssh,http,https,icmp,ftp" (默认为 "telnet,ssh,http,https,icmp,ftp")
        - source_ip: str, 源IP地址 (默认为 "0.0.0.0")
        - description: str, 规则描述 (默认为空字符串)
        - ip_version: int, IP版本，4表示IPv4，6表示IPv6 (默认为 4)
        - wan_index: int, WAN接口索引 (默认为 3)
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_wan_access_rule | application=telnet,ssh,http,https,icmp,ftp | source_ip=192.168.1.100 | description=WAN侧规则测试 | wan_index=3 |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.add_wan_access_rule(
                application=application,
                source_ip=source_ip,
                description=description,
                ip_version=ip_version,
                wan_index=wan_index
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"添加 WAN 侧访问控制规则失败: {str(e)}")

    def Ubus_edit_access_rule(self, instance_id, application=None, source_ip=None, description=None, ip_version=None, source_interface=None):
        """
        功能描述： 编辑已存在的访问控制规则
        参数：
        - instance_id: int/str, 要编辑的规则实例 ID
        - application: str, 应用类型（可选）
        - source_ip: str, 源IP地址（可选）
        - description: str, 规则描述（可选）
        - ip_version: int, IP版本（可选）
        - source_interface: str, 源接口路径（可选）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_edit_access_rule | instance_id=1 | description=编辑后的访问控制规则 | source_ip=192.168.1.200 |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.edit_access_rule(
                instance_id=instance_id,
                application=application,
                source_ip=source_ip,
                description=description,
                ip_version=ip_version,
                source_interface=source_interface
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"编辑访问控制规则失败: {str(e)}")

    def Ubus_delete_single_access_rule(self, instance_id):
        """
        功能描述： 删除指定的访问控制规则
        参数：
        - instance_id: int/str, 要删除的规则实例 ID
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_single_access_rule | instance_id=1 |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.delete_single_rule(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除访问控制规则失败: {str(e)}")

    def Ubus_delete_all_access_rules(self):
        """
        功能描述： 删除所有访问控制规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_access_rules |
        """
        try:
            self._init_access_control()
            result = self.AccessControl.delete_all_rules()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有访问控制规则失败: {str(e)}")

    def Ubus_add_port_forward_rule(self, interface="3_INTERNET_B_VID_200", enable="0", description="",
                                  protocol="TCP", external_port="1111", internal_client="192.168.29.221",
                                  internal_port=2222, external_port_end_range=0):
        """
        功能描述： 新增端口转发规则
        参数：
        - interface: 接口标识，类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3" (str, 默认为 "3_INTERNET_B_VID_200")
        - enable: 启用状态，"0"表示禁用，"1"表示启用，默认为 "0"
        - description: 规则描述，默认为空字符串
        - protocol: 协议类型，"TCP"或"UDP"，默认为 "TCP"
        - external_port: 外部端口，默认为 "1111"
        - internal_client: 内部客户端IP地址，默认为 "192.168.29.221"
        - internal_port: 内部端口，默认为 2222
        - external_port_end_range: 外部端口结束范围，默认为 0
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_port_forward_rule | interface=Device.IP.Interface.3 | enable=0 | description=测试端口转发 | protocol=TCP | external_port=8080 | internal_client=192.168.1.100 | internal_port=80 |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.add_port_forward_rule(
                interface=interface,
                enable=enable,
                description=description,
                protocol=protocol,
                external_port=external_port,
                internal_client=internal_client,
                internal_port=internal_port,
                external_port_end_range=external_port_end_range
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"新增端口转发规则失败: {str(e)}")

    def Ubus_edit_port_forward_rule(self, instance_id, interface=None, enable=None, description=None,
                                   protocol=None, external_port=None, internal_client=None,
                                   internal_port=None, external_port_end_range=None):
        """
        功能描述： 编辑已存在的端口转发规则
        参数：
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - interface: 接口路径（可选）
        - enable: 启用状态（可选）
        - description: 规则描述（可选）
        - protocol: 协议类型（可选）
        - external_port: 外部端口（可选）
        - internal_client: 内部客户端IP地址（可选）
        - internal_port: 内部端口（可选）
        - external_port_end_range: 外部端口结束范围（可选）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_edit_port_forward_rule | instance_id=1 | description=编辑后的端口转发规则 | external_port=9090 |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.edit_port_forward_rule(
                instance_id=instance_id,
                interface=interface,
                enable=enable,
                description=description,
                protocol=protocol,
                external_port=external_port,
                internal_client=internal_client,
                internal_port=internal_port,
                external_port_end_range=external_port_end_range
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"编辑端口转发规则失败: {str(e)}")

    def Ubus_delete_single_port_forward(self, instance_id):
        """
        功能描述： 删除指定的端口转发规则
        参数：
        - instance_id: 要删除的规则实例 ID (str 或 int)
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_single_port_forward | instance_id=1 |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.delete_single_port_forward(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除端口转发规则失败: {str(e)}")

    def Ubus_delete_all_port_forwards(self):
        """
        功能描述： 删除所有端口转发规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_port_forwards |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.delete_all_port_forwards()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有端口转发规则失败: {str(e)}")

    def Ubus_get_all_port_forwards(self):
        """
        功能描述： 获取所有端口转发规则
        返回：一个列表，每个元素为一个规则字典
        
        示例：
            | ${rules} | Ubus_get_all_port_forwards |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.get_all_port_forwards()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"获取所有端口转发规则失败: {str(e)}")

    def Ubus_enable_port_forward_rule(self, instance_id, enable="1"):
        """
        功能描述： 启用或禁用指定的端口转发规则
        参数：
        - instance_id: 要操作的规则实例 ID (str 或 int)
        - enable: "1"表示启用，"0"表示禁用，默认为 "1"
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_enable_port_forward_rule | instance_id=1 | enable=1 |
        """
        try:
            self._init_port_forward()
            result = self.PortForward.enable_port_forward_rule(instance_id, enable)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"启用/禁用端口转发规则失败: {str(e)}")

    def Ubus_add_port_trigger_rule(self, enable="0", trigger_protocol="TCP", open_protocol="TCP", trigger_port="1111", trigger_port_end_range="22222", open_port="3333", open_port_end_range="4444"):
        """
        功能描述： 新增端口触发规则
        参数：
        - enable: 启用状态，"0"表示禁用，"1"表示启用，默认为 "0"
        - trigger_protocol: 触发协议类型，"TCP"或"UDP"，默认为 "TCP"
        - open_protocol: 开放协议类型，"TCP"或"UDP"，默认为 "TCP"
        - trigger_port: 触发端口起始范围，默认为 "1111"
        - trigger_port_end_range: 触发端口结束范围，默认为 "22222"
        - open_port: 开放端口起始范围，默认为 "3333"
        - open_port_end_range: 开放端口结束范围，默认为 "4444"
        返回：新增规则的 instance 编号（int 类型）
        
        示例：
            | ${rule_id} | Ubus_add_port_trigger_rule | enable=0 | trigger_protocol=TCP | open_protocol=TCP | trigger_port=8080 | trigger_port_end_range=8090 | open_port=9000 | open_port_end_range=9010 |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.add_port_trigger_rule(
                enable=enable,
                trigger_protocol=trigger_protocol,
                open_protocol=open_protocol,
                trigger_port=trigger_port,
                trigger_port_end_range=trigger_port_end_range,
                open_port=open_port,
                open_port_end_range=open_port_end_range
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"新增端口触发规则失败: {str(e)}")

    def Ubus_edit_port_trigger_rule(self, instance_id, enable=None, trigger_protocol=None, open_protocol=None, trigger_port=None, trigger_port_end_range=None, open_port=None, open_port_end_range=None):
        """
        功能描述： 编辑已存在的端口触发规则
        参数：
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - enable: 启用状态（可选）
        - trigger_protocol: 触发协议类型（可选）
        - open_protocol: 开放协议类型（可选）
        - trigger_port: 触发端口起始范围（可选）
        - trigger_port_end_range: 触发端口结束范围（可选）
        - open_port: 开放端口起始范围（可选）
        - open_port_end_range: 开放端口结束范围（可选）
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_edit_port_trigger_rule | instance_id=1 | trigger_protocol=UDP | open_protocol=TCP | trigger_port=3000 | open_port=4000 |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.edit_port_trigger_rule(
                instance_id=instance_id,
                enable=enable,
                trigger_protocol=trigger_protocol,
                open_protocol=open_protocol,
                trigger_port=trigger_port,
                trigger_port_end_range=trigger_port_end_range,
                open_port=open_port,
                open_port_end_range=open_port_end_range
            )
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"编辑端口触发规则失败: {str(e)}")

    def Ubus_delete_single_port_trigger(self, instance_id):
        """
        功能描述： 删除指定的端口触发规则
        参数：
        - instance_id: 要删除的规则实例 ID (str 或 int)
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_single_port_trigger | instance_id=1 |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.delete_single_port_trigger(instance_id)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除端口触发规则失败: {str(e)}")

    def Ubus_delete_all_port_triggers(self):
        """
        功能描述： 删除所有端口触发规则
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_delete_all_port_triggers |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.delete_all_port_triggers()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"删除所有端口触发规则失败: {str(e)}")

    def Ubus_get_all_port_triggers(self):
        """
        功能描述： 获取所有端口触发规则
        返回：一个列表，每个元素为一个规则字典
        
        示例：
            | ${rules} | Ubus_get_all_port_triggers |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.get_all_port_triggers()
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"获取所有端口触发规则失败: {str(e)}")

    def Ubus_enable_port_trigger_rule(self, instance_id, enable="1"):
        """
        功能描述： 启用或禁用指定的端口触发规则
        参数：
        - instance_id: 要操作的规则实例 ID (str 或 int)
        - enable: "1"表示启用，"0"表示禁用，默认为 "1"
        返回：成功返回True，失败返回False
        
        示例：
            | ${result} | Ubus_enable_port_trigger_rule | instance_id=1 | enable=1 |
        """
        try:
            self._init_port_trigger()
            result = self.PortTrigger.enable_port_trigger_rule(instance_id, enable)
            return result
        except Exception as e:
            log.exception(str(e))
            raise ValueError(f"启用/禁用端口触发规则失败: {str(e)}")

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
    sec = SdmcSecurityLib()
    sec.Ubus_set_macfilter_enable("False")

    print("\nfinish ------------------")
    # os.system("pause")



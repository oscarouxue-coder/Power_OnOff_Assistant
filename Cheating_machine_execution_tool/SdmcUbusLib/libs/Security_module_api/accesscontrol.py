import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log


class AccessControlManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def set_param(self, path, value, proto="web"):
        """
        通用设置 UBUS 参数的函数

        参数:
        - path: 节点路径 (str)
        - value: 设置值 (str/int/bool)
        - proto: 可选协议 (默认 "web")

        返回:
        - ubus 调用返回结果
        """
        params = {
            "path": path,
            "value": str(value),
            "optional": {
                "proto": proto
            }
        }
        return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

    def set_access_control_enable(self, enable='True'):
        """
        控制访问控制使能开关
        
        参数:
        - enable: 'True' 表示启用，'False' 表示禁用 (str)
        
        返回:
        - ubus 调用返回结果
        """
        value = "1" if enable == 'True' else "0"
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable", value)

    def add_lan_access_rule(self, application="telnet,ssh,ftp", source_ip="0.0.0.0", description="", ip_version=4):
        """
        新增 LAN 侧访问控制规则
        
        参数:
        - application: 应用类型，如 "telnet,ssh,ftp" (str, 默认为 "telnet,ssh,ftp")
        - source_ip: 源IP地址 (str, 默认为 "0.0.0.0")
        - description: 规则描述 (str, 可选，默认为空字符串)
        - ip_version: IP版本，4表示IPv4，6表示IPv6 (int, 默认为 4)
        
        返回:
        - 新增规则的 instance 编号 (int)
        """
        # 第一步：添加规则条目
        add_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加LAN侧访问控制规则失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置规则内容
        obj_path = {
            "Application": application,
            "Description": description,
            "IPVersion": ip_version,
            "SourceIP": source_ip,
            "SourceInterface": "Device.IP.Interface.1"  # LAN侧接口
        }
        
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置LAN侧访问控制规则实例 {instance_id} 内容失败")
        
        return int(instance_id)

    def add_wan_access_rule(self, application="telnet,ssh,http,https,icmp,ftp", source_ip="0.0.0.0", description="", ip_version=4, wan_index=3):
        """
        新增 WAN 侧访问控制规则
        
        参数:
        - application: 应用类型，如 "telnet,ssh,http,https,icmp,ftp" (str, 默认为 "telnet,ssh,http,https,icmp,ftp")
        - source_ip: 源IP地址 (str, 默认为 "0.0.0.0")
        - description: 规则描述 (str, 可选，默认为空字符串)
        - ip_version: IP版本，4表示IPv4，6表示IPv6 (int, 默认为 4)
        - wan_index: WAN接口索引 (int, 默认为 3)
        
        返回:
        - 新增规则的 instance 编号 (int)
        """
        # 第一步：添加规则条目
        add_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加WAN侧访问控制规则失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置规则内容
        obj_path = {
            "Application": application,
            "Description": description,
            "IPVersion": ip_version,
            "SourceIP": source_ip,
            "SourceInterface": f"Device.IP.Interface.{wan_index}"  # WAN侧接口
        }
        
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置WAN侧访问控制规则实例 {instance_id} 内容失败")
        
        return int(instance_id)

    def delete_single_rule(self, instance_id):
        """
        删除指定的访问控制规则
        
        参数:
        - instance_id: 要删除的规则实例 ID (str 或 int)
        
        返回:
        - True 表示删除成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        del_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }
        
        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
        
        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除访问控制规则实例 {instance_id} 失败")
        
        return True

    def delete_all_rules(self):
        """
        删除所有访问控制规则
        
        返回:
        - True 表示删除成功
        """
        # 首先获取所有规则
        entries = self.get_all_access_rules()
        log.info(entries)
        
        if not entries:
            return True  # 没有规则可删除
        
        # 逐个删除所有规则
        for entry in entries:
            # 确保 entry 是字典类型
            if isinstance(entry, dict):
                instance_id = entry.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_single_rule(instance_id)
        
        return True

    def get_all_access_rules(self):
        """
        获取所有访问控制规则
        
        返回:
        - 一个列表，每个元素为一个规则字典，字段包括：
          X_SDMC_Instance、Application、Description、IPVersion、SourceIP、SourceInterface 等
        """
        params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取访问控制规则失败: {result}")
        
        # 检查 result 是否有足够的元素
        if len(result) < 2:
            return []
        
        entries = result[1].get("Rule", [])
        
        # 处理没有规则时返回 [0] 的情况
        if entries == [0]:
            return []
        
        return entries

    def edit_access_rule(self, instance_id, application=None, source_ip=None, description=None, ip_version=None, source_interface=None):
        """
        编辑已存在的访问控制规则
        
        参数:
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - application: 应用类型 (str, 可选)
        - source_ip: 源IP地址 (str, 可选)
        - description: 规则描述 (str, 可选)
        - ip_version: IP版本 (int, 可选)
        - source_interface: 源接口路径 (str, 可选)
        
        返回:
        - True 表示编辑成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        # 至少需要一个参数来更新
        if not any([application, source_ip, description, ip_version, source_interface]):
            raise ValueError("必须提供至少一个要更新的参数")
        
        obj_path = {}
        
        if application is not None:
            obj_path["Application"] = application
        if source_ip is not None:
            obj_path["SourceIP"] = source_ip
        if description is not None:
            obj_path["Description"] = description
        if ip_version is not None:
            obj_path["IPVersion"] = ip_version
        if source_interface is not None:
            obj_path["SourceInterface"] = source_interface
        
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"编辑访问控制规则实例 {instance_id} 失败")
        
        return True

    def debug_test(self):
        """
        调试测试函数，用于测试访问控制功能
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试使能/禁用访问控制
            # print("测试启用访问控制...")
            # enable_result = self.set_access_control_enable('True')
            # print(f"启用结果: {enable_result}")
            
            # # 测试添加LAN侧规则
            # print("\n测试添加LAN侧访问控制规则...")
            # lan_rule_id = self.add_lan_access_rule(
            #     application="telnet,ssh,ftp",
            #     source_ip="0.0.0.0",
            #     description="LAN侧规则测试"
            # )
            # print(f"添加LAN侧规则结果，实例 ID: {lan_rule_id}")
            
            # 测试添加WAN侧规则
            # print("\n测试添加WAN侧访问控制规则...")
            # wan_rule_id = self.add_wan_access_rule(
            #     application="telnet,ssh,http,https,icmp,ftp",
            #     source_ip="0.0.0.0",
            #     description="WAN侧规则测试",
            #     wan_index=3
            # )
            # print(f"添加WAN侧规则结果，实例 ID: {wan_rule_id}")
            
            # 测试获取所有规则
            print("\n测试获取所有访问控制规则...")
            entries = self.get_all_access_rules()
            entries_json = json.dumps(entries, indent=4, ensure_ascii=False)
            print(f"所有规则: {entries_json}")
            
            # 测试编辑规则
            # if entries:
            #     first_instance = entries[0].get("X_SDMC_Instance")
            #     # if first_instance:
            #     #     print(f"\n测试编辑规则 {first_instance}...")
            #     #     edit_result = self.edit_access_rule(
            #     #         first_instance,
            #     #         description="编辑后的访问控制规则"
            #     #     )
            #     #     print(f"编辑结果: {edit_result}")
            
            # # 测试修改规则（新增接口）
            # if entries:
            #     second_instance = entries[1].get("X_SDMC_Instance") if len(entries) > 1 else first_instance
            #     if second_instance:
            #         print(f"\n测试修改规则 {second_instance}...")
            #         modify_result = self.modify_access_rule(
            #             second_instance,
            #             application="telnet",
            #             description="修改后的访问控制规则"
            #         )
            #         print(f"修改结果: {modify_result}")
            
            # # 测试删除单个规则
            # print("\n测试删除单个访问控制规则...")
            # if entries:
            #     delete_instance = entries[0].get("X_SDMC_Instance")
            #     if delete_instance:
            #         delete_result = self.delete_single_rule(delete_instance)
            #         print(f"删除单个规则结果: {delete_result}")
            
            # # 测试删除所有规则
            # print("\n测试删除所有访问控制规则...")
            # delete_all_result = self.delete_all_rules()
            # print(f"删除所有规则结果: {delete_all_result}")
            
            # # 再次获取所有规则，确认已清空
            # print("\n确认所有规则已删除...")
            # entries_after_delete = self.get_all_access_rules()
            # entries_after_delete_json = json.dumps(entries_after_delete, indent=4, ensure_ascii=False)
            # print(f"删除后所有规则: {entries_after_delete_json}")
            
            # 测试禁用访问控制
            print("\n测试禁用访问控制...")
            disable_result = self.set_access_control_enable('False')
            print(f"禁用结果: {disable_result}")
            
        except Exception as e:
            print("debug test failed:", str(e))


if __name__ == '__main__':
    AccessControl = AccessControlManager(ip="192.168.29.1", username="sdmc", password="1234")
    AccessControl.debug_test()
import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log


class PortForwardManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def add_port_forward_rule(self, interface="3_INTERNET_B_VID_200", enable="0", description="",
                             protocol="TCP", external_port="1111", internal_client="192.168.29.221",
                             internal_port=2222, external_port_end_range=0):
        """
        新增端口转发规则
        
        参数:
        - interface: 接口标识，类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3" (str, 默认为 "3_INTERNET_B_VID_200")
        - enable: 启用状态，"0"表示禁用，"1"表示启用 (str, 默认为 "0")
        - description: 规则描述 (str, 可选，默认为空字符串)
        - protocol: 协议类型，"TCP"或"UDP" (str, 默认为 "TCP")
        - external_port: 外部端口 (str)
        - internal_client: 内部客户端IP地址 (str)
        - internal_port: 内部端口 (int)
        - external_port_end_range: 外部端口结束范围 (int, 默认为 0)
        
        返回:
        - 新增规则的 instance 编号 (int)
        """
        # 处理 interface：提取前面数字作为接口 ID
        interface_id = interface.split('_')[0] if interface else ""
        interface_path = f"Device.IP.Interface.{interface_id}" if interface_id else ""
        
        # 第一步：添加规则条目
        add_params = {
            "path": "Device.NAT.PortMapping.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加端口转发规则失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置规则内容
        obj_path = {
            "Interface": interface_path,
            "Enable": enable,
            "Description": description,
            "Protocol": protocol,
            "ExternalPort": str(external_port),
            "ExternalPortEndRange": external_port_end_range,
            "InternalClient": internal_client,
            "InternalPort": internal_port
        }
        
        set_params = {
            "path": f"Device.NAT.PortMapping.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置端口转发规则实例 {instance_id} 内容失败")
        
        return int(instance_id)

    def edit_port_forward_rule(self, instance_id, interface=None, enable=None, description=None,
                             protocol=None, external_port=None, internal_client=None,
                             internal_port=None, external_port_end_range=None):
        """
        编辑已存在的端口转发规则
        
        参数:
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - interface: 接口标识，类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3" (str, 可选)
        - enable: 启用状态，"0"表示禁用，"1"表示启用 (str, 可选)
        - description: 规则描述 (str, 可选)
        - protocol: 协议类型，"TCP"或"UDP" (str, 可选)
        - external_port: 外部端口 (str, 可选)
        - internal_client: 内部客户端IP地址 (str, 可选)
        - internal_port: 内部端口 (int, 可选)
        - external_port_end_range: 外部端口结束范围 (int, 可选)
        
        返回:
        - True 表示编辑成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        # 至少需要一个参数来更新
        if not any([interface, enable, description, protocol, external_port,
                   internal_client, internal_port, external_port_end_range]):
            raise ValueError("必须提供至少一个要更新的参数")
        
        obj_path = {}
        
        if interface is not None:
            # 处理 interface：提取前面数字作为接口 ID
            interface_id = interface.split('_')[0] if interface else ""
            interface_path = f"Device.IP.Interface.{interface_id}" if interface_id else ""
            obj_path["Interface"] = interface_path
        if enable is not None:
            obj_path["Enable"] = str(enable)
        if description is not None:
            obj_path["Description"] = description
        if protocol is not None:
            obj_path["Protocol"] = protocol
        if external_port is not None:
            obj_path["ExternalPort"] = str(external_port)
        if internal_client is not None:
            obj_path["InternalClient"] = internal_client
        if internal_port is not None:
            obj_path["InternalPort"] = internal_port
        if external_port_end_range is not None:
            obj_path["ExternalPortEndRange"] = external_port_end_range
        
        set_params = {
            "path": f"Device.NAT.PortMapping.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"编辑端口转发规则实例 {instance_id} 失败")
        
        return True

    def delete_single_port_forward(self, instance_id):
        """
        删除指定的端口转发规则
        
        参数:
        - instance_id: 要删除的规则实例 ID (str 或 int)
        
        返回:
        - True 表示删除成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        del_params = {
            "path": f"Device.NAT.PortMapping.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }
        
        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
        
        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除端口转发规则实例 {instance_id} 失败")
        
        return True

    def delete_all_port_forwards(self):
        """
        删除所有端口转发规则
        
        返回:
        - True 表示删除成功
        """
        # 首先获取所有规则
        entries = self.get_all_port_forwards()
        log.info(entries)
        
        if not entries:
            return True  # 没有规则可删除
        
        # 逐个删除所有规则
        for entry in entries:
            # 确保 entry 是字典类型
            if isinstance(entry, dict):
                instance_id = entry.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_single_port_forward(instance_id)
        
        return True

    def get_all_port_forwards(self):
        """
        获取所有端口转发规则
        
        返回:
        - 一个列表，每个元素为一个规则字典，字段包括：
          X_SDMC_Instance、Interface、Enable、Description、Protocol、ExternalPort、
          ExternalPortEndRange、InternalClient、InternalPort 等
        """
        params = {
            "path": "Device.NAT.PortMapping.",
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取端口转发规则失败: {result}")
        
        # 检查 result 是否有足够的元素
        if len(result) < 2:
            return []
        
        entries = result[1].get("PortMapping", [])
        
        # 处理没有规则时返回 [0] 的情况
        if entries == [0]:
            return []
        
        return entries

    def enable_port_forward_rule(self, instance_id, enable="1"):
        """
        启用或禁用指定的端口转发规则
        
        参数:
        - instance_id: 要操作的规则实例 ID (str 或 int)
        - enable: "1"表示启用，"0"表示禁用 (str, 默认为 "1")
        
        返回:
        - True 表示操作成功
        """
        return self.edit_port_forward_rule(instance_id, enable=enable)

    def debug_test(self):
        """
        调试测试函数，用于测试端口转发功能
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试添加端口转发规则
            # print("\n测试添加端口转发规则...")
            # rule_id = self.add_port_forward_rule(
            #     interface="3_INTERNET_B_VID_200",
            #     enable="0",  # 先禁用
            #     description="测试端口转发规则",
            #     protocol="TCP",
            #     external_port="1111",
            #     internal_client="192.168.29.221",
            #     internal_port=2222
            # )
            # print(f"添加端口转发规则结果，实例 ID: {rule_id}")
            
            # # 测试启用规则
            # print(f"\n测试启用端口转发规则 {rule_id}...")
            # enable_result = self.enable_port_forward_rule(rule_id, "1")
            # print(f"启用结果: {enable_result}")
            
            # 测试获取所有规则
            print("\n测试获取所有端口转发规则...")
            entries = self.get_all_port_forwards()
            entries_json = json.dumps(entries, indent=4, ensure_ascii=False)
            print(f"所有规则: {entries_json}")
            
            # # 测试编辑规则
            # if entries:
            #     first_instance = entries[0].get("X_SDMC_Instance")
            #     if first_instance:
            #         print(f"\n测试编辑规则 {first_instance}...")
            #         edit_result = self.edit_port_forward_rule(
            #             first_instance,
            #             description="编辑后的端口转发规则",
            #             external_port="3333"
            #         )
            #         print(f"编辑结果: {edit_result}")
            
            # # 测试删除单个规则
            # print("\n测试删除单个端口转发规则...")
            # if entries:
            #     delete_instance = entries[0].get("X_SDMC_Instance")
            #     if delete_instance:
            #         delete_result = self.delete_single_port_forward(delete_instance)
            #         print(f"删除单个规则结果: {delete_result}")
            
            # 测试删除所有规则
            print("\n测试删除所有端口转发规则...")
            delete_all_result = self.delete_all_port_forwards()
            print(f"删除所有规则结果: {delete_all_result}")
            
            # # 再次获取所有规则，确认操作结果
            # print("\n确认当前所有端口转发规则...")
            # entries_after = self.get_all_port_forwards()
            # entries_after_json = json.dumps(entries_after, indent=4, ensure_ascii=False)
            # print(f"当前所有规则: {entries_after_json}")
            
        except Exception as e:
            print("debug test failed:", str(e))


if __name__ == '__main__':
    PortForward = PortForwardManager(ip="192.168.29.1", username="sdmc", password="1234")
    PortForward.debug_test()
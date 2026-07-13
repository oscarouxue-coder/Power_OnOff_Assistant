import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log


class PortTriggerManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def add_port_trigger_rule(self, enable="0", trigger_protocol="TCP", open_protocol="TCP", trigger_port="1111", trigger_port_end_range="22222", open_port="3333", open_port_end_range="4444"):
        """
        新增端口触发规则
        
        参数:
        - enable: 启用状态，"0"表示禁用，"1"表示启用 (str, 默认为 "0")
        - trigger_protocol: 触发协议类型，"TCP"或"UDP" (str, 默认为 "TCP")
        - open_protocol: 开放协议类型，"TCP"或"UDP" (str, 默认为 "TCP")
        - trigger_port: 触发端口起始范围 (str, 默认为 "1111")
        - trigger_port_end_range: 触发端口结束范围 (str, 默认为 "22222")
        - open_port: 开放端口起始范围 (str, 默认为 "3333")
        - open_port_end_range: 开放端口结束范围 (str, 默认为 "4444")
        
        返回:
        - 新增规则的 instance 编号 (int)
        """
        # 第一步：添加端口触发条目
        add_params = {
            "path": "Device.NAT.PortTrigger.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加端口触发规则失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置端口触发规则基本内容
        obj_path = {
            "Enable": enable,
            "Protocol": trigger_protocol,
            "Port": int(trigger_port),
            "PortEndRange": int(trigger_port_end_range)
        }
        
        set_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置端口触发规则实例 {instance_id} 内容失败")
        
        # 第三步：添加规则条目
        rule_add_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        rule_add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", rule_add_params)
        
        if not rule_add_result or rule_add_result[0] != 0:
            raise RuntimeError(f"添加端口触发规则 {instance_id} 的规则条目失败")
        
        # 第四步：设置规则参数 - 协议
        rule_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.Protocol",
            "value": open_protocol,
            "optional": {
                "proto": "web"
            }
        }
        
        protocol_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", rule_params)
        
        if not protocol_result or protocol_result[0] != 0:
            raise RuntimeError(f"设置端口触发规则 {instance_id} 协议失败")
        
        # 第五步：设置开放端口起始范围
        open_port_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.Port",
            "value": str(open_port),
            "optional": {
                "proto": "web"
            }
        }
        
        open_port_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", open_port_params)
        
        if not open_port_result or open_port_result[0] != 0:
            raise RuntimeError(f"设置端口触发规则 {instance_id} 开放端口起始范围失败")
        
        # 第六步：设置开放端口结束范围
        open_port_end_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.PortEndRange",
            "value": str(open_port_end_range),
            "optional": {
                "proto": "web"
            }
        }
        
        open_port_end_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", open_port_end_params)
        
        if not open_port_end_result or open_port_end_result[0] != 0:
            raise RuntimeError(f"设置端口触发规则 {instance_id} 开放端口结束范围失败")
        
        return int(instance_id)

    def edit_port_trigger_rule(self, instance_id, enable=None, trigger_protocol=None, open_protocol=None, trigger_port=None, trigger_port_end_range=None, open_port=None, open_port_end_range=None):
        """
        编辑已存在的端口触发规则
        
        参数:
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - enable: 启用状态，"0"表示禁用，"1"表示启用 (str, 可选)
        - trigger_protocol: 触发协议类型，"TCP"或"UDP" (str, 可选)
        - open_protocol: 开放协议类型，"TCP"或"UDP" (str, 可选)
        - trigger_port: 触发端口起始范围 (str, 可选)
        - trigger_port_end_range: 触发端口结束范围 (str, 可选)
        - open_port: 开放端口起始范围 (str, 可选)
        - open_port_end_range: 开放端口结束范围 (str, 可选)
        
        返回:
        - True 表示编辑成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        # 至少需要一个参数来更新
        if not any([enable, trigger_protocol, open_protocol, trigger_port, trigger_port_end_range, open_port, open_port_end_range]):
            raise ValueError("必须提供至少一个要更新的参数")
        
        obj_path = {}
        
        if enable is not None:
            obj_path["Enable"] = str(enable)
        if trigger_protocol is not None:
            obj_path["Protocol"] = trigger_protocol
        if trigger_port is not None:
            obj_path["Port"] = str(trigger_port)
        if trigger_port_end_range is not None:
            obj_path["PortEndRange"] = str(trigger_port_end_range)
        
        set_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"编辑端口触发规则实例 {instance_id} 失败")
        
        # 如果需要更新开放端口范围或开放协议，需要通过规则条目来设置
        if any([open_port, open_port_end_range, open_protocol]):
            # 获取当前规则信息
            current_rules = self.get_all_port_triggers()
            rule_found = False
            for rule in current_rules:
                if str(rule.get("X_SDMC_Instance")) == str(instance_id):
                    rule_found = True
                    break
            
            if rule_found:
                # 设置开放端口起始范围
                if open_port is not None:
                    open_port_params = {
                        "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.Port",
                        "value": str(open_port),
                        "optional": {
                            "proto": "web"
                        }
                    }
                    
                    open_port_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", open_port_params)
                    
                    if not open_port_result or open_port_result[0] != 0:
                        raise RuntimeError(f"设置端口触发规则 {instance_id} 开放端口起始范围失败")
                
                # 设置开放协议
                if open_protocol is not None:
                    protocol_params = {
                        "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.Protocol",
                        "value": open_protocol,
                        "optional": {
                            "proto": "web"
                        }
                    }
                    
                    protocol_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", protocol_params)
                    
                    if not protocol_result or protocol_result[0] != 0:
                        raise RuntimeError(f"设置端口触发规则 {instance_id} 开放协议失败")
                
                # 设置开放端口结束范围
                if open_port_end_range is not None:
                    open_port_end_params = {
                        "path": f"Device.NAT.PortTrigger.{instance_id}.Rule.1.PortEndRange",
                        "value": str(open_port_end_range),
                        "optional": {
                            "proto": "web"
                        }
                    }
                    
                    open_port_end_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", open_port_end_params)
                    
                    if not open_port_end_result or open_port_end_result[0] != 0:
                        raise RuntimeError(f"设置端口触发规则 {instance_id} 开放端口结束范围失败")
        
        return True

    def delete_single_port_trigger(self, instance_id):
        """
        删除指定的端口触发规则
        
        参数:
        - instance_id: 要删除的规则实例 ID (str 或 int)
        
        返回:
        - True 表示删除成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        del_params = {
            "path": f"Device.NAT.PortTrigger.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }
        
        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
        
        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除端口触发规则实例 {instance_id} 失败")
        
        return True

    def delete_all_port_triggers(self):
        """
        删除所有端口触发规则
        
        返回:
        - True 表示删除成功
        """
        # 首先获取所有规则
        entries = self.get_all_port_triggers()
        log.info(entries)
        
        if not entries:
            return True  # 没有规则可删除
        
        # 逐个删除所有规则
        for entry in entries:
            # 确保 entry 是字典类型
            if isinstance(entry, dict):
                instance_id = entry.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_single_port_trigger(instance_id)
        
        return True

    def get_all_port_triggers(self):
        """
        获取所有端口触发规则
        
        返回:
        - 一个列表，每个元素为一个规则字典，字段包括：
          X_SDMC_Instance、Enable、Protocol、Port、PortEndRange 等
        """
        params = {
            "path": "Device.NAT.PortTrigger.",
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取端口触发规则失败: {result}")
        
        # 检查 result 是否有足够的元素
        if len(result) < 2:
            return []
        
        entries = result[1].get("PortTrigger", [])
        
        # 处理没有规则时返回 [0] 的情况
        if entries == [0]:
            return []
        
        return entries

    def enable_port_trigger_rule(self, instance_id, enable="1"):
        """
        启用或禁用指定的端口触发规则
        
        参数:
        - instance_id: 要操作的规则实例 ID (str 或 int)
        - enable: "1"表示启用，"0"表示禁用 (str, 默认为 "1")
        
        返回:
        - True 表示操作成功
        """
        return self.edit_port_trigger_rule(instance_id, enable=enable)

    def debug_test(self):
        """
        调试测试函数，用于测试端口触发功能
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试添加端口触发规则 - 参考用户提供的成功示例
            # print("\n测试添加端口触发规则...")
            # rule_id = self.add_port_trigger_rule(
            #     enable="0",  # 先禁用
            #     trigger_protocol="TCP",    # 触发协议
            #     open_protocol="TCP",       # 开放协议
            #     trigger_port="1111",      # 触发端口起始范围
            #     trigger_port_end_range="22222",  # 触发端口结束范围
            #     open_port="3333",         # 开放端口起始范围
            #     open_port_end_range="4444"  # 开放端口结束范围
            # )
            # print(f"添加端口触发规则结果，实例 ID: {rule_id}")
            
            # # 测试启用规则
            # print(f"\n测试启用端口触发规则 {rule_id}...")
            # enable_result = self.enable_port_trigger_rule(rule_id, "1")
            # print(f"启用结果: {enable_result}")
            
            # 测试获取所有规则
            print("\n测试获取所有端口触发规则...")
            entries = self.get_all_port_triggers()
            entries_json = json.dumps(entries, indent=4, ensure_ascii=False)
            print(f"所有规则: {entries_json}")
            
            # 测试编辑规则
            if entries:
                first_instance = entries[0].get("X_SDMC_Instance") 
                if first_instance:
                    print(f"\n测试编辑规则 {first_instance}...")
                    edit_result = self.edit_port_trigger_rule(
                        first_instance,
                        trigger_protocol="UDP",    # 更新触发协议
                        open_protocol="TCP",       # 更新开放协议
                        trigger_port="3000",
                        trigger_port_end_range="3005",
                        open_port="4000",
                        open_port_end_range="4010"
                    )
                    print(f"编辑结果: {edit_result}")
            
            # # 测试删除单个规则
            # print("\n测试删除单个端口触发规则...")
            # if entries:
            #     delete_instance = entries[0].get("X_SDMC_Instance")
            #     if delete_instance:
            #         delete_result = self.delete_single_port_trigger(delete_instance)
            #         print(f"删除单个规则结果: {delete_result}")
            
            # # 测试删除所有规则
            # print("\n测试删除所有端口触发规则...")
            # delete_all_result = self.delete_all_port_triggers()
            # print(f"删除所有规则结果: {delete_all_result}")
            
            # # 再次获取所有规则，确认操作结果
            # print("\n确认当前所有端口触发规则...")
            # entries_after = self.get_all_port_triggers()
            # entries_after_json = json.dumps(entries_after, indent=4, ensure_ascii=False)
            # print(f"当前所有规则: {entries_after_json}")
            
        except Exception as e:
            print("debug test failed:", str(e))


if __name__ == '__main__':
    PortTrigger = PortTriggerManager(ip="192.168.29.1", username="sdmc", password="1234")
    PortTrigger.debug_test()
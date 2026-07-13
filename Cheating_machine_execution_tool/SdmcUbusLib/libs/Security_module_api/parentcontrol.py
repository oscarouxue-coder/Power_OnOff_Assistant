import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log


class ParentalControlManager:
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

    def set_parental_control_enable(self, enable='True'):
        """
        控制家长控制使能开关
        
        参数:
        - enable: 'True' 表示启用，'False' 表示禁用 (str)
        
        返回:
        - ubus 调用返回结果
        """
        value = "1" if enable == 'True' else "0"
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Enable", value)

    def add_parental_control_rule(self, source_mac, description="", start_time="00:00", stop_time="23:59", weekdays="Everyday"):
        """
        新增家长控制规则
        
        参数:
        - source_mac: 源MAC地址 (str)
        - description: 规则描述 (str, 可选，默认为空字符串)
        - start_time: 开始时间，格式"HH:MM" (str, 默认为 "00:00")
        - stop_time: 结束时间，格式"HH:MM" (str, 默认为 "23:59")
        - weekdays: 星期几，如"Monday" (str, 默认为 "Everyday")
        
        返回:
        - 新增规则的 instance 编号 (int)
        """
        if not source_mac:
            raise ValueError("必须提供源MAC地址")
        
        # 处理weekdays参数，将"Everyday"转换为完整的星期列表
        if weekdays.upper() == "EVERYDAY":
            weekdays = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
        
        # 第一步：添加规则条目
        add_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加家长控制规则失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置规则内容
        obj_path = {
            "SourceMAC": source_mac,
            "Description": description,
            f"{VENDOR_PREFIX}StartTime": start_time,
            f"{VENDOR_PREFIX}StopTime": stop_time,
            f"{VENDOR_PREFIX}WeekDays": weekdays
        }
        
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置家长控制规则实例 {instance_id} 内容失败")
        
        return int(instance_id)

    def edit_parental_control_rule(self, instance_id, source_mac=None, description=None, start_time=None, stop_time=None, weekdays=None):
        """
        编辑已存在的家长控制规则
        
        参数:
        - instance_id: 要编辑的规则实例 ID (str 或 int)
        - source_mac: 源MAC地址 (str, 可选)
        - description: 规则描述 (str, 可选)
        - start_time: 开始时间，格式"HH:MM" (str, 可选)
        - stop_time: 结束时间，格式"HH:MM" (str, 可选)
        - weekdays: 星期几，如"Monday" (str, 可选)
        
        返回:
        - True 表示编辑成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        # 至少需要一个参数来更新
        if not any([source_mac, description, start_time, stop_time, weekdays]):
            raise ValueError("必须提供至少一个要更新的参数")
        
        obj_path = {}
        
        if source_mac is not None:
            obj_path["SourceMAC"] = source_mac
        if description is not None:
            obj_path["Description"] = description
        if start_time is not None:
            obj_path[f"{VENDOR_PREFIX}StartTime"] = start_time
        if stop_time is not None:
            obj_path[f"{VENDOR_PREFIX}StopTime"] = stop_time
        if weekdays is not None:
            # 处理weekdays参数，将"Everyday"转换为完整的星期列表
            if weekdays.upper() == "EVERYDAY":
                weekdays = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
            obj_path[f"{VENDOR_PREFIX}WeekDays"] = weekdays
        
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"编辑家长控制规则实例 {instance_id} 失败")
        
        return True

    def delete_parental_control_rule(self, instance_id):
        """
        删除指定的家长控制规则
        
        参数:
        - instance_id: 要删除的规则实例 ID (str 或 int)
        
        返回:
        - True 表示删除成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        del_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Rule.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }
        
        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
        
        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除家长控制规则实例 {instance_id} 失败")
        
        return True

    def delete_all_parental_control_rules(self):
        """
        删除所有家长控制规则
        
        返回:
        - True 表示删除成功
        """
        # 首先获取所有规则
        entries = self.get_all_parental_control_rules()
        log.info(entries)
        
        if not entries:
            return True  # 没有规则可删除
        
        # 逐个删除所有规则
        for entry in entries:
            # 确保 entry 是字典类型
            if isinstance(entry, dict):
                instance_id = entry.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_parental_control_rule(instance_id)
        
        return True

    def get_all_parental_control_rules(self):
        """
        获取所有家长控制规则
        
        返回:
        - 一个列表，每个元素为一个规则字典，字段包括：
          X_SDMC_Instance、SourceMAC、Description、X_SDMC_StartTime、X_SDMC_StopTime、X_SDMC_WeekDays 等
        """
        params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.ParentalCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取家长控制规则失败: {result}")
        
        # 检查 result 是否有足够的元素
        if len(result) < 2:
            return []
        
        entries = result[1].get("Rule", [])
        
        # 处理没有规则时返回 [0] 的情况
        if entries == [0]:
            return []
        
        return entries

    def debug_test(self):
        """
        调试测试函数，用于测试家长控制功能
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试使能/禁用家长控制
            # print("测试启用家长控制...")
            # enable_result = self.set_parental_control_enable('True')
            # print(f"启用结果: {enable_result}")
            
            # print("\n测试禁用家长控制...")
            # disable_result = self.set_parental_control_enable('False')
            # print(f"禁用结果: {disable_result}")
            
            # # 测试添加规则
            # print("\n测试添加家长控制规则...")
            # add_result = self.add_parental_control_rule(
            #     source_mac="f8:e4:3b:6f:0a:21",
            #     description="H1148",
            #     start_time="00:00",
            #     stop_time="02:00",
            #     weekdays="Monday"
            # )
            # print(f"添加规则结果，实例 ID: {add_result}")
            
            # 测试添加规则（使用默认参数）
            print("\n测试添加家长控制规则（使用默认参数）...")
            add_result2 = self.add_parental_control_rule("f8:e4:3b:6f:0a:22")
            print(f"添加规则结果（默认参数），实例 ID: {add_result2}")
            
            # # 测试显式传入Everyday
            # print("\n测试显式传入Everyday参数...")
            # add_result3 = self.add_parental_control_rule(
            #     source_mac="f8:e4:3b:6f:0a:23",
            #     description="Everyday测试",
            #     weekdays="Everyday"
            # )
            # print(f"添加规则结果（显式Everyday），实例 ID: {add_result3}")
            
            # 测试获取所有规则
            print("\n测试获取所有家长控制规则...")
            entries = self.get_all_parental_control_rules()
            entries_json = json.dumps(entries, indent=4, ensure_ascii=False)
            print(f"所有规则: {entries_json}")
            
            # # 测试编辑规则
            # if entries:
            #     first_instance = entries[0].get("X_SDMC_Instance")
            #     if first_instance:
            #         print(f"\n测试编辑规则 {first_instance}...")
            #         edit_result = self.edit_parental_control_rule(
            #             first_instance,
            #             description="编辑后的H1148",
            #             stop_time="03:00",
            #             weekdays="Everyday"  # 测试编辑时使用Everyday
            #         )
            #         print(f"编辑结果: {edit_result}")
            
            # # 测试删除所有规则
            # print("\n测试删除所有家长控制规则...")
            # delete_all_result = self.delete_all_parental_control_rules()
            # print(f"删除所有规则结果: {delete_all_result}")
            
            # # 再次获取所有规则，确认已清空
            # print("\n确认所有规则已删除...")
            # entries_after_delete = self.get_all_parental_control_rules()
            # entries_after_delete_json = json.dumps(entries_after_delete, indent=4, ensure_ascii=False)
            # print(f"删除后所有规则: {entries_after_delete_json}")
            
        except Exception as e:
            print("debug test failed:", str(e))


if __name__ == '__main__':
    ParentalControl = ParentalControlManager(ip="192.168.29.1", username="sdmc", password="1234")
    ParentalControl.debug_test()
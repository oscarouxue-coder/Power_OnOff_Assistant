import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log


class UrlfilterManager:
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

    def set_urlfilter_enable(self, enable='True'):
        """
        控制 URL Filter 使能开关
        
        参数:
        - enable: True 表示启用，False 表示禁用
        
        返回:
        - ubus 调用返回结果
        """
        value = "1" if enable=='True' else "0"
        return self.set_param(f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.Enable", value)

    def add_urlfilter_entry(self, web_url):
        """
        新增 URL Filter 条目
        
        参数:
        - web_url: 要过滤的网站 URL (str)
        
        返回:
        - 新增条目的 instance 编号 (int)
        """
        if not web_url:
            raise ValueError("必须提供网站 URL")
        
        # 第一步：添加条目
        add_params = {
            "path": f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.{VENDOR_PREFIX}Server.",
            "optional": {
                "proto": "web"
            }
        }
        
        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        
        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加 URL Filter 条目失败（add）")
        
        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")
        
        # 第二步：设置条目内容
        obj_path = {
            f"{VENDOR_PREFIX}Website": web_url
        }
        
        set_params = {
            "path": f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.{VENDOR_PREFIX}Server.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置 URL Filter 条目实例 {instance_id} 内容失败")
        
        return int(instance_id)

    def edit_urlfilter_entry(self, instance_id, web_url):
        """
        编辑已存在的 URL Filter 条目
        
        参数:
        - instance_id: 要编辑的条目实例 ID (int 或 str)
        - web_url: 新的网站 URL (str)
        
        返回:
        - True 表示编辑成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        if not web_url:
            raise ValueError("必须提供网站 URL")
        
        obj_path = {
            f"{VENDOR_PREFIX}Website": web_url
        }
        
        set_params = {
            "path": f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.{VENDOR_PREFIX}Server.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"编辑 URL Filter 条目实例 {instance_id} 失败")
        
        return True

    def delete_urlfilter_entry(self, instance_id):
        """
        删除指定的 URL Filter 条目
        
        参数:
        - instance_id: 要删除的条目实例 ID (int 或 str)
        
        返回:
        - True 表示删除成功
        """
        if not instance_id:
            raise ValueError("必须提供实例 ID")
        
        del_params = {
            "path": f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.{VENDOR_PREFIX}Server.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }
        
        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
        
        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除 URL Filter 条目实例 {instance_id} 失败")
        
        return True

    def delete_all_urlfilter_entries(self):
        """
        删除所有 URL Filter 条目
        
        返回:
        - True 表示删除成功
        """
        # 首先获取所有条目
        entries = self.get_all_urlfilter_entries()
        
        if not entries:
            return True  # 没有条目可删除
        
        # 逐个删除所有条目
        for entry in entries:
            # 确保 entry 是字典类型
            if isinstance(entry, dict):
                instance_id = entry.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_urlfilter_entry(instance_id)
        
        return True

    def get_all_urlfilter_entries(self):
        """
        获取所有 URL Filter 条目
        
        返回:
        - 一个列表，每个元素为一个条目字典，字段包括：
          X_SDMC_Instance、X_SDMC_Website、X_SDMC_Order 等
        """
        params = {
            "path": f"Device.DNS.{VENDOR_PREFIX}Dnsmasq.{VENDOR_PREFIX}Server.",
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call("bbfdm", "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取 URL Filter 条目失败: {result}")
        
        # 检查 result 是否有足够的元素
        if len(result) < 2:
            return []
        
        entries = result[1].get(f"{VENDOR_PREFIX}Server", [])
        
        # 处理没有条目时返回 [0] 的情况
        if entries == [0]:
            return []
        
        return entries

    def debug_test(self):
        """
        调试测试函数，用于测试 URL Filter 功能
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试使能/禁用 URL Filter
            # print("测试启用 URL Filter...")
            # enable_result = self.set_urlfilter_enable(True)
            # print(f"启用结果: {enable_result}")
            
            # print("\n测试禁用 URL Filter...")
            # disable_result = self.set_urlfilter_enable(False)
            # print(f"禁用结果: {disable_result}")
            
            # # 测试添加条目
            # print("\n测试添加 URL Filter 条目...")
            # add_result = self.add_urlfilter_entry("www.example.com")
            # print(f"添加条目结果，实例 ID: {add_result}")
            
            # add_result2 = self.add_urlfilter_entry("www.test.com")
            # print(f"添加第二个条目结果，实例 ID: {add_result2}")
            
            # # 测试获取所有条目
            # print("\n测试获取所有 URL Filter 条目...")
            # entries = self.get_all_urlfilter_entries()
            # entries_json = json.dumps(entries, indent=4, ensure_ascii=False)
            # print(f"所有条目: {entries_json}")
            
            # # 测试编辑条目
            # if entries:
            #     first_instance = entries[0].get(f"{VENDOR_PREFIX}Instance")
            #     if first_instance:
            #         print(f"\n测试编辑条目 {first_instance}...")
            #         edit_result = self.edit_urlfilter_entry(first_instance, "www.edited-example.com")
            #         print(f"编辑结果: {edit_result}")
            
            # # 测试删除单个条目
            # if entries:
            #     second_instance = entries[1].get(f"{VENDOR_PREFIX}Instance") if len(entries) > 1 else entries[0].get(f"{VENDOR_PREFIX}Instance")
            #     if second_instance:
            #         print(f"\n测试删除条目 {second_instance}...")
            #         delete_result = self.delete_urlfilter_entry(second_instance)
            #         print(f"删除结果: {delete_result}")
            
            # 测试删除所有条目
            print("\n测试删除所有 URL Filter 条目...")
            delete_all_result = self.delete_all_urlfilter_entries()
            print(f"删除所有条目结果: {delete_all_result}")
            
            # # 再次获取所有条目，确认已清空
            # print("\n确认所有条目已删除...")
            # entries_after_delete = self.get_all_urlfilter_entries()
            # entries_after_delete_json = json.dumps(entries_after_delete, indent=4, ensure_ascii=False)
            # print(f"删除后所有条目: {entries_after_delete_json}")
            
        except Exception as e:
            print("debug test failed:", str(e))


if __name__ == '__main__':
    Urlfilter = UrlfilterManager(ip="192.168.29.1", username="sdmc", password="1234")
    Urlfilter.debug_test()

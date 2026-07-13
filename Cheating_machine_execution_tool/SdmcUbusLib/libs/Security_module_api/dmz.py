import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class DmzManager:
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

    def add_dmz_entry(self, wan_name, enable_dmz, lan_host_addr):
        """
        添加一条 DMZ 条目。

        参数：
        - wan_name: WAN 接口名称，类似"3_INTERNET_B_VID_200"，会自动转换为"Device.IP.Interface.3"
        - enable_dmz: 是否启用 DMZ，布尔值 True/False
        - lan_host_addr: LAN 主机 IP 地址

        返回：
        - 新增 DMZ 条目 instance 编号（int 类型）
        """

        # 处理 wan_name：提取前面数字作为接口 ID
        interface_id = wan_name.split('_')[0] if wan_name else ""
        interface_path = f"Device.IP.Interface.{interface_id}" if interface_id else ""

        # 第一步：添加 DMZ 条目
        add_params = {
            "path": f"Device.Firewall.DMZ.",
            "optional": {
                "proto": "web"
            }
        }

        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加 DMZ 条目失败（add）")

        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")

        # 第二步：设置 DMZ 条目内容
        obj_path = {
            "Enable": enable_dmz,
            "DestIP": lan_host_addr,
        }

        if interface_path:
            obj_path["Interface"] = interface_path

        set_params = {
            "path": f"Device.Firewall.DMZ.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }

        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置 DMZ 条目实例 {instance_id} 内容失败")

        return int(instance_id)

    def modify_dmz_entry(self, instance_id, enable_dmz=None, lan_host_addr=None, wan_name=None):
        """
        修改指定的 DMZ 条目。

        参数：
        - instance_id: 要修改的 DMZ 条目实例 ID（整数或字符串）
        - enable_dmz: 是否启用 DMZ，布尔值 True/False（可选）
        - lan_host_addr: LAN 主机 IP 地址（可选）
        - wan_name: WAN 接口名称，类似"3_INTERNET_B_VID_200"（可选）

        返回：
        - True 表示修改成功
        - 抛出异常表示失败
        """
        if not instance_id:
            raise ValueError("必须提供 instance_id")
        
        # 检查是否至少提供了一个要修改的参数
        if enable_dmz is None and lan_host_addr is None and wan_name is None:
            raise ValueError("必须至少提供一个要修改的参数（enable_dmz、lan_host_addr 或 wan_name）")

        # 构建要修改的参数对象
        obj_path = {}
        
        if enable_dmz is not None:
            obj_path["Enable"] = enable_dmz
            
        if lan_host_addr is not None:
            obj_path["DestIP"] = lan_host_addr
            
        if wan_name is not None:
            # 处理 wan_name：提取前面数字作为接口 ID
            interface_id = wan_name.split('_')[0] if wan_name else ""
            interface_path = f"Device.IP.Interface.{interface_id}" if interface_id else ""
            if interface_path:
                obj_path["Interface"] = interface_path

        # 设置 DMZ 条目内容
        set_params = {
            "path": f"Device.Firewall.DMZ.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }

        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"修改 DMZ 条目实例 {instance_id} 失败")

        return True

    def delete_dmz_entry(self, instance_id):
        """
        删除指定的 DMZ 条目。

        参数：
        - instance_id: 要删除的 DMZ 条目实例 ID（整数或字符串）

        返回：
        - True 表示删除成功
        - 抛出异常表示失败
        """
        if not instance_id:
            raise ValueError("必须提供 instance_id")

        del_params = {
            "path": f"Device.Firewall.DMZ.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }

        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除 DMZ 条目实例 {instance_id} 失败")

        return True

    def get_all_dmz_entries(self):
        """
        获取所有 DMZ 条目。

        返回：
        - 一个列表，每个元素为一个 DMZ 条目字典，包含数字实例 ID
        """

        params = {
            "path": f"Device.Firewall.DMZ.",
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取 DMZ 条目失败: {result}")

        # 安全地处理 result[1] 可能不存在的情况
        if len(result) < 2 or result[1] is None:
            print("没有找到 DMZ 条目数据，返回空列表")
            return []

        # 安全地获取 DMZ 列表，处理各种边界情况
        entries = []
        if isinstance(result[1], dict):
            entries = result[1].get("DMZ", [])
        elif isinstance(result[1], list):
            entries = result[1]
        else:
            print(f"意外的 result[1] 数据格式: {type(result[1])}, 返回空列表")
            return []
        
        # 确保 entries 是列表类型
        if not isinstance(entries, list):
            print(f"DMZ 数据不是列表格式: {type(entries)}，返回空列表")
            return []
        
        # 为每个条目添加数字实例 ID
        for i, entry in enumerate(entries):
            if isinstance(entry, dict):
                # 假设条目的顺序对应于数字实例 ID
                entry["instance_id"] = str(i + 1)
            else:
                print(f"条目格式异常: {entry}，跳过此条目")
                
        return entries

    def delete_all_dmz_entries(self):
        """
        删除所有 DMZ 条目。

        返回：
        - True 表示删除成功
        - 抛出异常表示失败
        """
        # 第一步：获取所有 DMZ 条目
        entries = self.get_all_dmz_entries()
        
        if not entries:
            print("没有找到 DMZ 条目，无需删除")
            return True

        # 第二步：逐个删除 DMZ 条目
        for entry in entries:
            try:
                # 使用 instance_id 字段
                instance_id = entry.get("instance_id")
                if instance_id:
                    self.delete_dmz_entry(instance_id)
                    print(f"成功删除 DMZ 条目 {instance_id} (Alias: {entry.get('Alias', 'N/A')})")
                else:
                    print(f"条目缺少 instance_id: {entry}")
            except Exception as e:
                print(f"删除 DMZ 条目失败: {str(e)}")
                continue

        return True

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试添加 DMZ 条目
            # print("测试添加 DMZ 条目...")
            # try:
            #     entry_id = self.add_dmz_entry(
            #         wan_name="3_INTERNET_B_VID_200",
            #         enable_dmz=True,
            #         lan_host_addr="192.168.29.221"
            #     )
            #     print("添加 DMZ 条目成功，条目ID:", entry_id)
            # except Exception as e:
            #     print("添加 DMZ 条目失败:", str(e))
            
            # # 测试获取所有 DMZ 条目
            # print("测试获取所有 DMZ 条目...")
            # try:
            #     entries = self.get_all_dmz_entries()
            #     print(f"获取到 {len(entries)} 个 DMZ 条目")
            #     for entry in entries:
            #         print(f"条目: {entry}")
            # except Exception as e:
            #     print("获取 DMZ 条目失败:", str(e))

            # self.modify_dmz_entry(instance_id="1", enable_dmz=True)
            self.delete_all_dmz_entries()

            self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
        dmz = DmzManager(ip="192.168.29.1", username="sdmc", password="1234")
        dmz.debug_test()
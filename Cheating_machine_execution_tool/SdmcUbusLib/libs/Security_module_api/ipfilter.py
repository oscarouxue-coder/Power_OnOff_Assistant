import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class IpfilterManager:
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

    def set_ipfilter(self, value):
        """
        设置 ipfilter 开关状态
        
        参数:
        - value: str, "1"=启用, "0"=禁用或其他值
        
        返回:
        - ubus 调用返回结果
        """
        return self.set_param(
            f"Device.Firewall.{VENDOR_PREFIX}Security.IpFilter.Enable",
            value,
        )

    def add_ipfilter_rule(self, description="", source_ip="", dest_ip="", source_port=None, dest_port=None,
                          ip_version=4, protocol="TCP", source_interface="", direction="1"):
        """
        添加一条 IPFilter 规规则。

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

        返回：
        - 新增规则 instance 编号（int 类型）
        """

        # 处源 source_interface：提取前面数字作为接口 ID
        interface_id = source_interface.split('_')[0] if source_interface else ""
        source_interface_path = f"Device.IP.Interface.{interface_id}" if interface_id else ""

        # 第一步：添加规则
        add_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.IpFilter.Rule.",
            "optional": {
                "proto": "web"
            }
        }

        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加 IPFilter 规规则失败（add）")

        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")

        # 第二步：设置规则内容
        obj_path = {
            "Description": description,
            "IPVersion": ip_version,
            "Protocol": protocol,
            f"{VENDOR_PREFIX}direction": direction,
        }

        if source_ip:
            obj_path["SourceIP"] = source_ip
        if dest_ip:
            obj_path["DestIP"] = dest_ip
        if source_port is not None:
            obj_path["SourcePort"] = source_port
        if dest_port is not None:
            obj_path["DestPort"] = dest_port
        if source_interface_path and direction != "0":
            obj_path["SourceInterface"] = source_interface_path

        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.IpFilter.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }

        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置 IPFilter 规规则实例 {instance_id} 内容失败")

        return int(instance_id)

    def delete_ipfilter_rule(self, instance_id):
        """
        删除指定的 IPFilter 规规则。

        参数：
        - instance_id: 要删除的规则实例 ID（整数或字符串）

        返回：
        - True 表示删除成功
        - 抛出异常表示失败
        """
        if not instance_id:
            raise ValueError("必须提供 instance_id")

        del_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.IpFilter.Rule.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }

        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除 IPFilter 规规则实例 {instance_id} 失败")

        return True

    def delete_all_ipfilter_rules(self):
        """
        删除所有 IPFilter 规规则。

        返回：
        - True 表示删除成功
        - 抛出异常表示失败
        """
        # 第一步：获取所有规则
        rules = self.get_all_ipfilter_rules()
        
        if not rules:
            print("没有找到 IPFilter 规规则，无需删除")
            return True

        # 第二步：逐个删除规则
        for rule in rules:
            try:
                instance_id = rule.get("X_SDMC_Instance")
                if instance_id:
                    self.delete_ipfilter_rule(instance_id)
                    print(f"成功删除规则实例 {instance_id}")
            except Exception as e:
                print(f"删除规则实例 {instance_id} 失败: {str(e)}")
                continue

        return True

    def get_all_ipfilter_rules(self):
        """
        获取所有 IPFilter 规规则。

        返回：
        - 一个列表，每个元素为一个规则字典，字段包括：
          X_SDMC_Instance、Description、SourceInterface、IPVersion、
          Protocol、SourceIP、DestIP、SourcePort、DestPort、X_SDMC_direction 等。
        """

        params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.IpFilter.",
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取 IPFilter 规规则失败: {result}")

        rules = result[1].get("IpFilter", {}).get("Rule", [])
        return rules

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # 测试设置 ipfilter 开关
            self.set_ipfilter("1")
            
            # 测试添加 ipfilter 规规则
            print("测试添加 ipfilter 规规则...")
            try:
                rule_id = self.add_ipfilter_rule(
                    description="测试规则",
                    source_ip="192.168.29.240",
                    dest_ip="172.18.18.85",
                    source_port=4000,
                    dest_port=5000,
                    protocol="TCP",
                    ip_version=4,
                    source_interface="3_INTERNET_B_VID_200",
                    direction="0"
                )
                print("添加 ipfilter 规规则成功，规则ID:", rule_id)
            except Exception as e:
                print("添加 ipfilter 规规则失败:", str(e))
            
            # # 测试删除指定规则
            # print("测试删除指定规则...")
            # try:
            #     if 'rule_id' in locals():
            #         self.delete_ipfilter_rule(rule_id)
            #         print(f"删除规则 {rule_id} 成成功")
            # except Exception as e:
            #     print("删除指定规则失败:", str(e))
            
            # # 测试添加多个规则
            # print("测试添加多个规则...")
            # try:
            #     rule_id1 = self.add_ipfilter_rule(
            #         description="规则1",
            #         source_ip="192.168.1.101",
            #         dest_ip="192.168.1.201",
            #         protocol="TCP"
            #     )
            #     rule_id2 = self.add_ipfilter_rule(
            #         description="规则2",
            #         source_ip="192.168.1.102",
            #         dest_ip="192.168.1.202",
            #         protocol="UDP"
            #     )
            #     print(f"添加多个规则成功，规则ID: {rule_id1}, {rule_id2}")
            # except Exception as e:
            #     print("添加多个规则失败:", str(e))
            
            # # 测试删除所有规则
            # print("测试删除所有规则...")
            # try:
            #     self.delete_all_ipfilter_rules()
            #     print("删除所有规则成功")
            # except Exception as e:
            #     print("删除所有规则失败:", str(e))

            self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
        Ipfilter = IpfilterManager(ip="192.168.29.1", username="sdmc", password="1234")
        Ipfilter.debug_test()
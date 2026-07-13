import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class AccessctrlManager:
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

    def enable_accessctrl(self):
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable", True)

    def disable_accessctrl(self):
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable", False)

    def add_accessctrl_rule(self, application, ip_version, source_ip, source_interface, description=""):
        """
        添加一个新的 AccessCtrl 规则。

        参数：
        - application (str): 应用名称，多个使用逗号分隔，如 "telnet,ssh,ftp"
        - ip_version (int): IP 版本（如 4 或 6）
        - source_ip (str): 源 IP 地址（如 "0.0.0.0" 表示任意）
        - source_interface (str): 接口标识符，如 "2_INTERNET_R_VID_200" 或 "LAN"
        - description (str): 可选描述

        返回：
        - instance_id (int): 新增规则的实例 ID（例如 1 表示 Rule.1）
        """

        # 接口转换逻辑
        if source_interface.upper() == "LAN":
            source_interface_path = "Device.IP.Interface.1"
        else:
            try:
                interface_index = int(source_interface.split('_')[0])
                source_interface_path = f"Device.IP.Interface.{interface_index}"
            except (ValueError, IndexError):
                raise ValueError(f"无效的接口格式: {source_interface}")

        # 第一步：添加新规则对象
        add_params = {
            "path": "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.",
            "optional": {
                "proto": "web"
            }
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)
        if not result or result[0] != 0:
            raise RuntimeError(f"添加规则失败: {result}")

        # 获取新增规则的实例号
        instance_id = result[1]["results"][0]["data"]

        # 第二步：设置规则参数
        set_params = {
            "path": f"Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.{instance_id}.",
            "obj_path": {
                "Application": application,
                "Description": description,
                "IPVersion": ip_version,
                "SourceIP": source_ip,
                "SourceInterface": source_interface_path
            },
            "optional": {
                "proto": "web"
            }
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        if not result or result[0] != 0:
            raise RuntimeError(f"设置规则失败: {result}")

        return int(instance_id)

    def set_accessctrl_rule(self, instance_id, application=None, ip_version=None,
                            source_ip=None, source_interface=None, description=None):
        """
        修改已有的 AccessCtrl 规则。

        参数：
        - instance_id (int): 规则实例号（如 1 表示 Rule.1）
        - application (str): 应用名称（多个用逗号，如 "telnet,ssh"）
        - ip_version (int): IP 版本（4 或 6）
        - source_ip (str): 源 IP 地址
        - source_interface (str): 接口标识（如 "2_INTERNET_R_VID_200"、"LAN"）
        - description (str): 规则描述

        所有字段都为可选，传入哪个修改哪个。
        """

        obj_path = {}

        if application is not None:
            obj_path["Application"] = application

        if ip_version is not None:
            obj_path["IPVersion"] = ip_version

        if source_ip is not None:
            obj_path["SourceIP"] = source_ip

        if source_interface is not None:
            # 转换为 Device.IP.Interface.x 格式
            if source_interface.upper() == "LAN":
                obj_path["SourceInterface"] = "Device.IP.Interface.1"
            else:
                try:
                    index = int(source_interface.split('_')[0])
                    obj_path["SourceInterface"] = f"Device.IP.Interface.{index}"
                except (ValueError, IndexError):
                    raise ValueError(f"无效的接口格式: {source_interface}")

        if description is not None:
            obj_path["Description"] = description

        if not obj_path:
            raise ValueError("至少需要指定一个要修改的字段。")

        params = {
            "path": f"Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.{instance_id}.",
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"修改规则失败: {result}")

        return True

    def delete_accessctrl_rule(self, instance_id):
        """
        删除指定的 AccessCtrl 规则。

        参数：
        - instance_id (int): 要删除的规则实例号（如 1 表示 Rule.1）
        """

        params = {
            "path": f"Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"删除规则失败: {result}")

        return True

    def get_all_accessctrl_rules(self):
        """
        获取所有 AccessCtrl 规则。

        返回：
        - 一个列表，每个元素为一个规则字典，包含如 X_SDMC_Instance、Description、SourceInterface、IPVersion、SourceIP、Application 等字段。
        """

        params = {
            "path": "Device.Firewall.X_SDMC_Security.AccessCtrl.",
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if not result or result[0] != 0:
            raise RuntimeError(f"获取 AccessCtrl 规则失败: {result}")

        rules = result[1].get("AccessCtrl", {}).get("Rule", [])
        return rules

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            # info = self.enable_accessctrl()
            # info = self.disable_accessctrl()

            # rule_id = self.add_accessctrl_rule(
            #     application="telnet",
            #     ip_version=4,
            #     source_ip="192.168.1.100",
            #     source_interface="LAN",
            #     description="Block telnet from LAN"
            # )
            # print(rule_id)

            # result = self.set_accessctrl_rule(
            #     instance_id=1,
            #     application="telnet,ssh",
            #     description="Block telnet from LAN"
            # )
            # print(result)

            # result = self.delete_accessctrl_rule(instance_id=1)
            # print(result)

            rules = self.get_all_accessctrl_rules()

            info_json = json.dumps(rules, indent=4, ensure_ascii=False)
            print(info_json)

        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
        AccessCtl = AccessctrlManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
        AccessCtl.debug_test();
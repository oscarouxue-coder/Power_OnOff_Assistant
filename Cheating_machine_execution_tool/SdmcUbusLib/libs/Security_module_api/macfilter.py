import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class MacfilterManager:
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

    def enable_macfilter(self):
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Enable", "1")

    def disable_macfilter(self):
        return self.set_param(f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Enable", "0")

    def set_macfilter_mode(self, mode):
        """
        设置 MAC 过滤模式为黑名单或白名单。
        在切换前，会先清空已有的 MACFilter.Rule 条目。

        参数：
        - mode: "black" 或 "white"
        """
        if mode not in ("black", "white"):
            raise ValueError("mode 参数必须为 'black' 或 'white'")

        # 第一步：获取当前规则
        get_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.",
            "optional": {
                "proto": "web"
            }
        }

        get_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", get_params)

        if not get_result or get_result[0] != 0:
            raise RuntimeError("获取 MacFilter 配置失败")

        rules = get_result[1].get("MacFilter", {}).get("Rule", [])

        # 第二步：删除已有规则
        for rule in rules:
            instance = rule.get(f"{VENDOR_PREFIX}Instance")
            if instance is not None:
                del_params = {
                    "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Rule.{instance}.",
                    "optional": {
                        "proto": "web"
                    }
                }
                del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
                if not del_result or del_result[0] != 0:
                    raise RuntimeError(f"删除规则实例 {instance} 失败")

        # 第三步：设置黑名单或白名单模式
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.",
            "obj_path": {
                "BlackWhiteList": mode
            },
            "optional": {
                "proto": "web"
            }
        }

        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置 MACFilter 模式为 '{mode}' 失败")

        return set_result

    def add_macfilter_rule(self, mac_addr, description=""):
        """
        添加一条 MAC 过滤规则。

        参数：
        - mac_addr: MAC 地址（如 F8:E4:3B:6F:0A:21）
        - description: 描述信息（如设备名），默认为空字符串

        返回：
        - 新增规则的 instance 编号（int 类型）
        """
        # 第一步：添加规则
        add_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Rule.",
            "optional": {
                "proto": "web"
            }
        }

        add_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

        if not add_result or add_result[0] != 0:
            raise RuntimeError("添加 MACFilter 规则失败（add）")

        try:
            instance_id = add_result[1]["results"][0]["data"]
        except (KeyError, IndexError):
            raise RuntimeError("解析 add 返回结果失败，无法获取 instance ID")

        # 第二步：设置规则内容
        set_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Rule.{instance_id}.",
            "obj_path": {
                "Description": description,
                "SourceMAC": mac_addr
            },
            "optional": {
                "proto": "web"
            }
        }

        set_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        if not set_result or set_result[0] != 0:
            raise RuntimeError(f"设置 MACFilter 规则实例 {instance_id} 内容失败")

        return int(instance_id)

    def modify_macfilter_rule(self, instance_id, new_mac, description=""):
        """
        修改一条已存在的 MACFilter 规则

        参数：
        - instance_id: 要修改的规则实例编号（如 1 或 "1"）
        - new_mac: 新的 SourceMAC 地址
        - description: 可选的描述信息，默认空字符串
        """
        # 确保 instance_id 是字符串
        instance_id = str(instance_id)

        set_params = {
            "path": f"Device.Firewall.X_SDMC_Security.MacFilter.Rule.{instance_id}.",
            "obj_path": {
                "Description": description,
                "SourceMAC": new_mac
            },
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

        if not result or result[0] != 0:
            raise RuntimeError(f"修改 MACFilter 规则实例 {instance_id} 失败")

        return True

    def delete_macfilter_rule(self, instance_id):
        """
        删除一条 MAC 过滤规则

        参数：
        - instance_id: 要删除的规则实例编号（如 1、2…）
        """
        del_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Rule.{instance_id}.",
            "optional": {
                "proto": "web"
            }
        }

        del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

        if not del_result or del_result[0] != 0:
            raise RuntimeError(f"删除 MACFilter 规则实例 {instance_id} 失败")

        return True

    def delete_all_macfilter_rules(self):
        """
        删除所有 MAC 过滤规则

        返回：
        - 成功返回 True
        """
        # 第一步：获取当前规则
        get_params = {
            "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.",
            "optional": {
                "proto": "web"
            }
        }

        get_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", get_params)

        if not get_result or get_result[0] != 0:
            raise RuntimeError("获取 MacFilter 配置失败")

        rules = get_result[1].get("MacFilter", {}).get("Rule", [])

        # 第二步：删除所有规则
        for rule in rules:
            instance = rule.get(f"{VENDOR_PREFIX}Instance")
            if instance is not None:
                del_params = {
                    "path": f"Device.Firewall.{VENDOR_PREFIX}Security.MacFilter.Rule.{instance}.",
                    "optional": {
                        "proto": "web"
                    }
                }
                del_result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)
                if not del_result or del_result[0] != 0:
                    raise RuntimeError(f"删除规则实例 {instance} 失败")

        return True

    def get_macfilter_config(self):
        """
        获取 MACFilter 的完整配置信息

        返回：
        {
            "Enable": True,
            "BlackWhiteList": "black",
            "Rules": [
                {
                    "Instance": 1,
                    "Description": "",
                    "L1Interface": "",
                    "SourceMAC": "f8:e4:3b:6f:0a:13"
                },
                ...
            ]
        }
        """
        get_params = {
            "path": "Device.Firewall.X_SDMC_Security.MacFilter.",
            "optional": {
                "proto": "web"
            }
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", get_params)

        if not result or result[0] != 0:
            raise RuntimeError("获取 MACFilter 配置信息失败")

        raw_data = result[1].get("MacFilter", {})
        config = {
            "Enable": raw_data.get("Enable", False),
            "BlackWhiteList": raw_data.get("BlackWhiteList", ""),
            "Rules": []
        }

        for rule in raw_data.get("Rule", []):
            config["Rules"].append({
                "Instance": rule.get("X_SDMC_Instance"),
                "Description": rule.get("Description", ""),
                # "L1Interface": rule.get("L1Interface", ""),
                "SourceMAC": rule.get("SourceMAC", "")
            })

        return config

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            # self.enable_macfilter()
            # self.set_macfilter_mode("white")
            # info = self.add_macfilter_rule("F2:E4:3B:6F:0A:21", "H1148")

            # info = self.delete_macfilter_rule("1")
            # info = self.disable_macfilter()

            # info = self.modify_macfilter_rule("1", "f8:e4:3b:6f:0a:13")

            info = self.delete_all_macfilter_rules()

            info = self.get_macfilter_config()
            info_json = json.dumps(info, indent=4, ensure_ascii=False)
            print(info_json)

        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
    Macfilter = MacfilterManager(ip="192.168.29.1", username="sdmc", password="1234")
    Macfilter.debug_test();
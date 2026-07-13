from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
import json

class UpnpManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def set_upnp_enable(self, enable=True):
        """
        【功能描述】
        设置 UPnP 功能的开关状态

        【入参】
        enable: 布尔值，True 表示开启 UPnP，False 表示关闭 UPnP

        【返回值】
        成功返回 UBUS 调用结果，失败抛出异常

        【示例】
        Example:
        |  set_upnp_enable  |  True  |
        |  set_upnp_enable  |  False  |

        """
        try:
            # 构造参数
            params = {
                "path": "Device.UPnP.Device.Enable",
                "value": str(enable).lower(),  # 转换为字符串 "true" 或 "false"
                "optional": {"proto": "web"}
            }
            
            # 调用 UBUS 接口设置 UPnP 状态
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            
            log.info(f"UPnP 设置为 {'开启' if enable else '关闭'}")
            return result
            
        except Exception as e:
            log.error(f"设置 UPnP 状态失败: {str(e)}")
            raise

    def get_upnp_status(self):
        """
        【功能描述】
        获取当前 UPnP 功能的状态

        【入参】
        无

        【返回值】
        返回 UPnP 的当前状态信息，包括 Enable 状态

        【示例】
        Example:
        |  get_upnp_status  |

        """
        try:
            # 构造参数
            params = {
                "path": "Device.UPnP.Device.",
                "optional": {"proto": "web"}
            }
            
            # 调用 UBUS 接口获取 UPnP 状态
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            
            # 提取 UPnP 设备信息
            upnp_data = result[1].get('Device', {}).get('Enable', {})
            
            log.info(f"获取 UPnP 状态成功: {upnp_data}")
            return upnp_data
            
        except Exception as e:
            log.error(f"获取 UPnP 状态失败: {str(e)}")
            raise

    def get_upnp_rules(self):
        """
        【功能描述】
        获取当前 UPnP 规则列表

        【入参】
        无

        【返回值】
        返回 UPnP 规则列表，包含协议、外部端口、客户端IP、内部端口和描述信息

        【示例】
        Example:
        |  get_upnp_rules  |

        """
        try:
            # 构造参数
            params = {
                "path": "Device.UPnP.Device.",
                "optional": {"proto": "web"}
            }
            
            # 调用 UBUS 接口获取 UPnP 设备信息
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            
            # 提取 UPnP 规则信息
            upnp_data = result[1].get('Device', {})
            redirection_str = upnp_data.get(f'{VENDOR_PREFIX}ActiveUPnPRedirection', '{}')
            
            # 解析 JSON 字符串
            try:
                redirection_data = json.loads(redirection_str)
                rules = redirection_data.get('item', [])
                item_count = redirection_data.get('item_count', 0)
                
                log.info(f"获取 UPnP 规则成功，共 {item_count} 条规则")
                return {
                    "item_count": item_count,
                    "rules": rules
                }
            except json.JSONDecodeError as e:
                log.info(f"解析 UPnP 规则 JSON 失败: {str(e)}")
                return {
                    "item_count": 0,
                    "rules": []
                }
            
        except Exception as e:
            log.info(f"获取 UPnP 规则失败: {str(e)}")
            raise

    def debug_test(self):
        """
        【功能描述】
        调试测试函数，用于测试 UPnP 功能

        【入参】
        无

        【返回值】
        无

        【示例】
        Example:
        |  debug_test  |

        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            # 获取当前状态
            print("获取当前 UPnP 状态...")
            current_status = self.get_upnp_status()
            print(f"当前状态: {current_status}")
            
            # 测试开启 UPnP
            print("测试开启 UPnP...")
            self.set_upnp_enable(True)
            
            # 再次获取状态验证
            print("验证 UPnP 开启状态...")
            status_after_enable = self.get_upnp_status()
            print(f"开启后状态: {status_after_enable}")
            
            # 测试关闭 UPnP
            print("测试关闭 UPnP...")
            self.set_upnp_enable(False)
            
            # 再次获取状态验证
            print("验证 UPnP 关闭状态...")
            status_after_disable = self.get_upnp_status()
            print(f"关闭后状态: {status_after_disable}")
            
            # 测试获取 UPnP 规则
            print("获取 UPnP 规则...")
            rules = self.get_upnp_rules()
            print(f"当前 UPnP 规则: {rules}")

            self.ubus.Ubus_Logout()
            
        except Exception as e:
            log.error(f"调试测试失败: {str(e)}")

if __name__ == '__main__':
    # 示例用法
    upnp = UpnpManager(ip="192.168.29.1", username="sdmc", password="1234")
    upnp.debug_test()
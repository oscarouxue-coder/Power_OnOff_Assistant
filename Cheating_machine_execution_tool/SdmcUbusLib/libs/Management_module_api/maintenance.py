import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class MaintenanceManager:
    def __init__(self, ip, username, password):
        """
        初始化维护管理类
        
        参数:
        - ip: 路由器IP地址 (str)
        - username: 登录用户名 (str)
        - password: 登录密码 (str)
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def _convert_wan_name_to_interface(self, wan_name):
        """
        将wan名称转换为Device.IP.Interface格式
        
        参数:
        - wan_name: wan名称，如"3_INTERNET_B_VID_200"
        
        返回:
        - 接口路径，如"Device.IP.Interface.3"
        """
        if not wan_name:
            raise ValueError("wan名称不能为空")
        
        # 提取前面的数字作为接口ID
        interface_id = wan_name.split('_')[0]
        
        if not interface_id.isdigit():
            raise ValueError(f"wan名称格式错误：{wan_name}，应该以数字开头")
        
        return f"Device.IP.Interface.{interface_id}"

    def _validate_diagnosis_type(self, diagnosis_type):
        """
        验证诊断类型
        
        参数:
        - diagnosis_type: 诊断类型 (str)
        
        返回:
        - 验证结果 (bool)
        """
        valid_types = [
            "ipv4_ping", "ipv6_ping", 
            "ipv4_traceroute", "ipv6_traceroute"
        ]
        return diagnosis_type in valid_types

    def _get_protocol_version(self, diagnosis_type):
        """
        根据诊断类型获取协议版本
        
        参数:
        - diagnosis_type: 诊断类型 (str)
        
        返回:
        - 协议版本字符串 (str)
        """
        if diagnosis_type in ["ipv4_ping", "ipv4_traceroute"]:
            return "IPv4"
        elif diagnosis_type in ["ipv6_ping", "ipv6_traceroute"]:
            return "IPv6"
        else:
            raise ValueError(f"不支持的诊断类型: {diagnosis_type}")

    def _get_command(self, diagnosis_type):
        """
        根据诊断类型获取命令
        
        参数:
        - diagnosis_type: 诊断类型 (str)
        
        返回:
        - 命令字符串 (str)
        """
        if diagnosis_type in ["ipv4_ping", "ipv6_ping"]:
            return "Device.IP.Diagnostics.X_SDMC_IPPing()"
        elif diagnosis_type in ["ipv4_traceroute", "ipv6_traceroute"]:
            return "Device.IP.Diagnostics.X_SDMC_TraceRoute()"
        else:
            raise ValueError(f"不支持的诊断类型: {diagnosis_type}")

    def start_diagnosis(self, wan_name, target_host, diagnosis_type):
        """
        开始网络诊断（ping或traceroute）
        
        参数:
        - wan_name: wan名称，如"3_INTERNET_B_VID_200" (str)
        - target_host: 目标IP或域名，如"www.baidu.com" (str)
        - diagnosis_type: 诊断类型，支持"ipv4_ping"、"ipv6_ping"、"ipv4_traceroute"、"ipv6_traceroute" (str)
        
        返回:
        - 诊断结果字典，包含诊断输出信息
        """
        # 验证诊断类型
        if not self._validate_diagnosis_type(diagnosis_type):
            raise ValueError(f"诊断类型必须是以下之一: ipv4_ping, ipv6_ping, ipv4_traceroute, ipv6_traceroute")
        
        # 验证参数
        if not target_host:
            raise ValueError("目标主机不能为空")
        
        # 转换wan名称为接口路径
        if not wan_name:
            interface_path = ""
        else:
            interface_path = self._convert_wan_name_to_interface(wan_name)
        
        # 获取协议版本和命令
        protocol_version = self._get_protocol_version(diagnosis_type)
        command = self._get_command(diagnosis_type)
        
        # 构建参数
        params = {
            "command": command,
            "input": {
                "Host": target_host,
                "ProtocolVersion": protocol_version,
                "Interface": interface_path
            },
            "optional": {
                "proto": "web"
            }
        }
        
        # 发送诊断请求
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)
        
        if not result or result[0] != 0:
            return result
        
        
        # 提取stdout输出内容
        stdout_content = ""
        
        # 解析results数组
        if isinstance(result[1], dict) and "results" in result[1]:
            results = result[1]["results"]
            if results and len(results) > 0:
                first_result = results[0]
                
                # 提取stdout输出
                output = first_result.get("output", [])
                if output:
                    for output_item in output:
                        if "stdout" in output_item:
                            stdout_content += output_item["stdout"]
        
        # 将字符串中的\n转换为实际的换行符
        stdout_content = stdout_content.replace('\\n', '\n')
        
        return stdout_content

    def debug_test(self):
        """调试测试函数"""
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            wan_name = "3_INTERNET_B_VID_200"
            target_host = "1.2.3.4"
            
            print("开始测试IPv4 Ping诊断...")
            # 测试IPv4 Ping
            # try:
            #     result = self.start_diagnosis(wan_name, target_host, "ipv4_ping")
            #     print("IPv4 Ping诊断结果:")
            #     print(result)
                
            # except Exception as e:
            #     print("IPv4 Ping诊断失败:", str(e))
            
            print("\n开始测试IPv4 Traceroute诊断...")
            # 测试IPv4 Traceroute
            try:
                result = self.start_diagnosis(wan_name, target_host, "ipv4_traceroute")
                print("IPv4 Traceroute诊断结果:")
                print(result)
                
            except Exception as e:
                print("IPv4 Traceroute诊断失败:", str(e))
            
            self.ubus.Ubus_Logout()
            
        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
    maintenance = MaintenanceManager(ip="192.168.29.1", username="sdmc", password="1234")
    maintenance.debug_test()
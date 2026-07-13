import time
import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class SpeedtestManager:
    def __init__(self, ip, username, password):
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

    def start_speedtest(self, test_url, test_direction, wan_name):
        """
        开始speedtest测速
        
        参数:
        - test_url: 测速URL (str)
        - test_direction: 测试方向，"download" 或 "upload" (str)
        - wan_name: wan名称，如"3_INTERNET_B_VID_200" (str)
        
        返回:
        - 成功返回True，失败抛出异常
        """
        if test_direction not in ["download", "upload"]:
            raise ValueError("测试方向必须是 'download' 或 'upload'")
        
        # 转换wan名称为接口路径
        interface_path = self._convert_wan_name_to_interface(wan_name)
        
        # 根据测试方向选择不同的路径
        if test_direction == "download":
            path = "Device.IP.Diagnostics.DownloadDiagnostics."
            rate_field = f"{VENDOR_PREFIX}DownloadRate"
        else:  # upload
            path = "Device.IP.Diagnostics.UploadDiagnostics."
            rate_field = f"{VENDOR_PREFIX}UploadRate"
        
        # 设置测试参数
        obj_path = {
            "DiagnosticsState": "Requested",
            "Interface": interface_path,
            "TimeBasedTestDuration": "6",
            "NumberOfConnections": "2"
        }
        
        # 根据测试方向设置URL
        if test_direction == "download":
            obj_path["DownloadURL"] = test_url
        else:  # upload
            obj_path["UploadURL"] = test_url
        
        params = {
            "path": path,
            "obj_path": obj_path,
            "optional": {
                "proto": "web"
            }
        }
        
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
        
        if not result or result[0] != 0:
            raise RuntimeError(f"启动{test_direction}测速失败: {result}")
        
        return True

    def get_speedtest_result(self, test_direction, wan_name, timeout=60):
        """
        获取speedtest测速结果
        
        参数:
        - test_direction: 测试方向，"download" 或 "upload" (str)
        - wan_name: wan名称，如"3_INTERNET_B_VID_200" (str)
        - timeout: 超时时间（秒），默认60秒 (int)
        
        返回:
        - SpeedRate: 测速结果速率
        
        异常:
        - 当测速未在超时时间内完成时抛出RuntimeError
        """
        if test_direction not in ["download", "upload"]:
            raise ValueError("测试方向必须是 'download' 或 'upload'")
        
        # 转换wan名称为接口路径
        interface_path = self._convert_wan_name_to_interface(wan_name)
        
        # 根据测试方向选择不同的路径
        if test_direction == "download":
            path = "Device.IP.Diagnostics.DownloadDiagnostics."
            rate_field = f"{VENDOR_PREFIX}DownloadRate"
        else:  # upload
            path = "Device.IP.Diagnostics.UploadDiagnostics."
            rate_field = f"{VENDOR_PREFIX}UploadRate"
        
        # 开始计时
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            params = {
                "path": path,
                "optional": {
                    "proto": "web"
                }
            }
            
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            
            if not result or result[0] != 0:
                raise RuntimeError(f"获取{test_direction}测速结果失败: {result}")
            
            # 解析返回结果
            if len(result) < 2:
                raise RuntimeError(f"测速结果格式错误: {result}")
            
            diagnostics_data = result[1].get(test_direction.capitalize() + "Diagnostics", {})
            
            if not diagnostics_data:
                raise RuntimeError(f"未找到{test_direction}测速数据")
            
            # 检查DiagnosticsState状态
            diagnostics_state = diagnostics_data.get("DiagnosticsState", "")
            
            if diagnostics_state == "Complete":
                # 状态已完成，返回速率结果
                speed_result = {
                    "DiagnosticsState": diagnostics_state,
                    "Interface": diagnostics_data.get("Interface", ""),
                    "TestURL": diagnostics_data.get("DownloadURL" if test_direction == "download" else "UploadURL", ""),
                    "TestFileLength": diagnostics_data.get("TestFileLength", 0),
                    "TimeBasedTestDuration": diagnostics_data.get("TimeBasedTestDuration", 0),
                    "NumberOfConnections": diagnostics_data.get("NumberOfConnections", 0),
                    "SpeedRate": diagnostics_data.get(rate_field, "None")
                }
                
                return speed_result["SpeedRate"]
            elif diagnostics_state in ["Error", "None"]:
                # 测速出现错误
                raise RuntimeError(f"{test_direction}测速失败，状态: {diagnostics_state}")
            else:
                # 测速进行中，等待后重试
                time.sleep(2)
        
        # 超时未完成
        raise RuntimeError(f"{test_direction}测速在{timeout}秒内未完成，当前状态: {diagnostics_state}")

    def debug_test(self):
        """调试测试函数"""
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            test_url = "http://172.18.18.239:8080/1G.txt"
            wan_name = "3_INTERNET_B_VID_200"
            
            print("开始测试download测速...")
            # 测试download方向
            try:
                self.start_speedtest(test_url, "download", wan_name)
                print("启动download测速成功")
                
                # 等待一段时间后获取结果
                import time
                time.sleep(5)
                
                result = self.get_speedtest_result("download", wan_name)
                print("Download测速结果:", result)
                
            except Exception as e:
                print("Download测速失败:", str(e))
            
            print("\n开始测试upload测速...")
            # 测试upload方向
            try:
                self.start_speedtest(test_url, "upload", wan_name)
                print("启动upload测速成功")
                
                # 等待一段时间后获取结果
                time.sleep(5)
                
                result = self.get_speedtest_result("upload", wan_name)
                print("Upload测速结果:", result)
                
            except Exception as e:
                print("Upload测速失败:", str(e))
            
            self.ubus.Ubus_Logout()
            
        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
    speedtest = SpeedtestManager(ip="192.168.29.1", username="sdmc", password="1234")
    speedtest.debug_test()
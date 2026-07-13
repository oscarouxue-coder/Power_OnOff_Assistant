import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase, VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcLog import log
from time import sleep
import urllib3
import requests

class TcpdumpManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        self.capture_file_path = "/tmp/webcapt.pcapng"
        self.capture_filename = "webcapt.pcapng"

    def start_tcpdump_capture(self, duration=60, interface="any", packet_type="All"):
        """
        【功能描述】
            开始TCPDump抓包
        
        【入参】
            duration: 抓捕时长（秒），默认60秒
            interface: 抓包接口，默认"any"（所有接口）
            packet_type: 抓包类型，默认"All"（所有包）
        
        【返回值】
            抓包开始的结果数据
        
        【示例】
            | ${result} | start_tcpdump_capture | duration=30 | interface="eth0" |
        """
        try:
            params = {
                "command": f"Device.DeviceInfo.{VENDOR_PREFIX}TcpDump.Capture()",
                "input": {
                    "Duration": int(duration),
                    "Interface": str(interface),
                    "Type": str(packet_type)
                },
                "optional": {"proto": "web"}
            }
            
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)
            log.info(f"开始抓包，时长: {duration}秒，接口: {interface}")
            
            # 如果指定了时长，启动定时停止机制
            if duration > 0:
                sleep(duration)
                self.stop_tcpdump_capture()
                
            return result
            
        except Exception as e:
            log.exception(f"开始抓包失败: {str(e)}")
            raise

    def stop_tcpdump_capture(self):
        """
        【功能描述】
            停止TCPDump抓包（支持手动停止和时长自动停止）
        
        【入参】
            无
        
        【返回值】
            抓包停止的结果数据
        
        【示例】
            | ${result} | stop_tcpdump_capture |
        """
        try:
            params = {
                "command": f"Device.DeviceInfo.{VENDOR_PREFIX}TcpDump.Stop()",
                "optional": {"proto": "web"}
            }
            
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)
            log.info("停止抓包")
            
            return result
            
        except Exception as e:
            log.exception(f"停止抓包失败: {str(e)}")
            raise

    def download_capture_file(self, download_path="./"):
        """
        【功能描述】
            下载抓包文件到指定路径
        
        【入参】
            download_path: 下载文件保存路径，默认当前目录
        
        【返回值】
            下载结果信息，包含文件路径等
        
        【示例】
            | ${result} | download_capture_file | download_path="/tmp/" |
        """
        try:
            # 确保下载目录存在
            if not os.path.exists(download_path):
                os.makedirs(download_path)
                
            # 获取sessionid从ubus对象
            session_id = self.ubus.ubus_rpc_session
            if not session_id:
                raise ValueError("未找到有效的UBUS session ID，请先登录")
            
            # 构建cgi-download的URL
            download_url = f"http://{self.ip}/cgi-bin/cgi-download"
            
            # 构建form数据
            form_data = {
                "sessionid": session_id,
                "path": self.capture_file_path,
                "filename": self.capture_filename
            }
            
            # 发起POST请求到cgi-download
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = requests.post(
                download_url,
                data=form_data,
                verify=False,
                stream=True
            )
            
            # 检查响应状态
            if response.status_code == 200:
                local_file_path = os.path.join(download_path, self.capture_filename)
                
                # 将文件内容保存到本地
                with open(local_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                log.info(f"抓包文件已下载到: {local_file_path}")
                
                return {
                    "status": "success",
                    "file_path": local_file_path,
                    "original_path": self.capture_file_path,
                    "download_path": download_path,
                    "session_id": session_id,
                    "file_size": os.path.getsize(local_file_path)
                }
            else:
                log.error(f"下载失败，HTTP状态码: {response.status_code}")
                return {
                    "status": "failed",
                    "error": f"HTTP {response.status_code}",
                    "response_text": response.text[:500]  # 限制错误信息长度
                }
                
        except Exception as e:
            log.exception(f"下载抓包文件失败: {str(e)}")
            raise

    def get_capture_status(self):
        """
        【功能描述】
            获取当前抓包状态
        
        【入参】
            无
        
        【返回值】
            抓包状态信息
        
        【示例】
            | ${result} | get_capture_status |
        """
        try:
            params = {
                "path": f"Device.DeviceInfo.{VENDOR_PREFIX}TcpDump.",
                "optional": {"proto": "web"}
            }
            
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            return result
            
        except Exception as e:
            log.exception(f"获取抓包状态失败: {str(e)}")
            raise

    def debug_test(self):
        """
        【功能描述】
            调试测试接口
        
        【入参】
            无
        
        【返回值】
            无
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # # 测试获取状态
            # print("=== 测试获取抓包状态 ===")
            # status = self.get_capture_status()
            # print(f"抓包状态: {status}")
            
            # # 测试开始抓包（短时间）
            # print("\n=== 测试开始抓包（5秒）===")
            # capture_result = self.start_tcpdump_capture(duration=5)
            # print(f"抓包结果: {capture_result}")
            
            # # 测试停止抓包
            # print("\n=== 测试停止抓包 ===")
            # stop_result = self.stop_tcpdump_capture()
            # print(f"停止结果: {stop_result}")
            
            # 测试下载文件
            print("\n=== 测试下载抓包文件 ===")
            download_result = self.download_capture_file("D:")
            print(f"下载结果: {download_result}")
            
        except Exception as e:
            print(f"调试测试失败: {str(e)}")

    def unit_test(self):
        """
        【功能描述】
            单元测试接口
        
        【入参】
            无
        
        【返回值】
            无
        """
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            # 这里可以添加更详细的单元测试逻辑
            
        except Exception as e:
            print(f"单元测试失败: {str(e)}")

if __name__ == '__main__':
    # 创建TCPDump管理器实例
    tcpdump_mgr = TcpdumpManager(ip="192.168.29.1", username="sdmc", password="1234")
    
    # 运行调试测试
    tcpdump_mgr.debug_test()
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase, VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcUbusLib.libs.base_moudle_api.upgrade import UpgradeManager
from SdmcLog import log
from SdmcCode import *
import urllib3
import requests
from datetime import datetime
import json

class RestoreArchiveManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()
        self.upgrade_manager = UpgradeManager(ip, username, password)
        self.backup_filename = f"backup-OpenWrt-{datetime.now().strftime('%Y-%m-%d')}.tar.gz"
        self.backup_url = f"http://{self.ip}/cgi-bin/cgi-backup"

    def generate_config_backup(self, download_path="./"):
        """
        【功能描述】
            生成配置文件备份并下载到本地
        
        【入参】
            download_path: 备份文件保存路径，默认当前目录
        
        【返回值】
            备份生成和下载的结果信息
        
        【示例】
            | ${result} | generate_config_backup | download_path="/tmp/" |
        """
        try:
            # 确保下载目录存在
            if not os.path.exists(download_path):
                os.makedirs(download_path)
            
            # 禁用SSL警告（用于测试环境）
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # 构建POST请求数据（参考用户提供的HTTP请求信息）
            form_data = {
                "sessionid": self._get_session_id()
            }
            
            log.info(f"开始生成配置文件备份，保存路径: {download_path}")
            
            # 发起POST请求到cgi-backup
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = requests.post(
                self.backup_url,
                data=form_data,
                verify=False,
                stream=True
            )
            
            # 检查响应状态
            if response.status_code == 200:
                # 从Content-Disposition头获取实际文件名
                content_disposition = response.headers.get('content-disposition', '')
                if 'filename=' in content_disposition:
                    actual_filename = content_disposition.split('filename="')[1].split('"')[0]
                else:
                    actual_filename = self.backup_filename
                
                local_file_path = os.path.join(download_path, actual_filename)
                
                # 将文件内容保存到本地
                with open(local_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                log.info(f"配置文件备份已生成并下载到: {local_file_path}")
                
                return {
                    "status": "success",
                    "message": f"配置文件备份成功生成并下载到: {local_file_path}"
                }
            else:
                log.error(f"生成配置文件备份失败，HTTP状态码: {response.status_code}")
                return {
                    "status": "failed",
                    "message": f"HTTP {response.status_code}"
                }
                
        except Exception as e:
            log.exception(f"生成配置文件备份失败: {str(e)}")
            raise

    def _get_session_id(self):
        """
        【功能描述】
            获取当前UBUS会话的session ID
        
        【入参】
            无
        
        【返回值】
            str: 当前UBUS会话的session ID
        
        【示例】
            | ${session_id} | _get_session_id | |
        """
        try:
            # 从UBUS基础库获取session ID
            session_id = self.ubus.ubus_rpc_session
            if not session_id:
                raise ValueError("UBUS session ID为空，请先执行登录")
            return session_id
        except Exception as e:
            log.exception(f"获取session ID失败: {str(e)}")
            raise

    def upload_and_restore_config(self, config_file_path):
        """
        【功能描述】
            上传配置文件到设备并触发恢复配置操作
        
        【入参】
            config_file_path: 本地配置文件路径
        
        【返回值】
            dict: 包含上传和恢复操作的结果信息
        
        【示例】
            | ${result} | upload_and_restore_config | /path/to/config.tar.gz | |
        """
        try:
            # 确保配置文件存在
            if not os.path.isfile(config_file_path):
                raise FileNotFoundError(f"配置文件不存在: {config_file_path}")
            
            log.info(f"开始上传配置文件: {config_file_path}")
            
            # 获取session ID
            session_id = self._get_session_id()
            
            # 设备端保存路径
            device_save_path = "/tmp/x_sdmc_backupall.tar.gz"
            
            # 上传接口URL
            device_url = f"http://{self.ip}/cgi-bin/cgi-upload"
            
            # 使用UpgradeManager上传文件
            status_code, msg = self.upgrade_manager.upload_file_to_device(
                device_url=device_url,
                local_file_path=config_file_path,
                device_save_path=device_save_path,
                sessionid=session_id
            )
            
            if status_code != 200:
                error_msg = f"文件上传失败: {msg}"
                log.error(error_msg)
                return {
                    "status": "failed",
                    "message": error_msg
                }
            
            log.info("配置文件上传成功，开始触发恢复配置操作")
            
            # 触发恢复配置操作
            restore_result = self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "operate",
                {
                    "command": f"Device.DeviceInfo.{VENDOR_PREFIX}RestoreAll()",
                    "input": {"URL": "local"},
                    "optional": {"proto": "web"}
                }
            )
            
            # log.info(f"恢复配置操作结果: {restore_result}")
            
            return {
                "status": "success",
                "message": "配置文件上传并触发恢复配置成功",
                "upload_result": {
                    "status_code": status_code,
                    "message": msg
                },
                "restore_result": restore_result
            }
            
        except Exception as e:
            error_msg = f"上传并恢复配置失败: {str(e)}"
            log.exception(error_msg)
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
            self.upload_and_restore_config("D:/backup-OpenWrt-2025-11-21.tar.gz")

            
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
            # 这里可以添加更详细的单元测试逻辑
            print("=== 开始单元测试 ===")
            
            # 测试初始化
            print(f"IP地址: {self.ip}")
            print(f"备份URL: {self.backup_url}")
            print(f"默认备份文件名: {self.backup_filename}")
            
            # 测试UBUS连接
            self.ubus.Ubus_Login(self.username, self.password)
            print("UBUS连接测试成功")
            self.upload_and_restore_config("D:/backup-OpenWrt-2025-11-21.tar.gz")
            
            print("单元测试完成")
            
        except Exception as e:
            print(f"单元测试失败: {str(e)}")

if __name__ == '__main__':
    restore_mgr = RestoreArchiveManager(ip="192.168.29.1", username="sdmc", password="1234")
    
    restore_mgr.debug_test()
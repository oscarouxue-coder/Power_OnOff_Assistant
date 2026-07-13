import json

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class AccountManagement:
    def __init__(self, ip, username, password):
        """
        初始化账户管理
        
        参数:
        - ip: 路由器IP地址 (str)
        - username: 登录用户名 (str)
        - password: 登录密码 (str)
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def _check_password_strength(self, password):
        """
        检查密码强度
        
        参数:
        - password: 密码 (str)
        
        返回:
        - 密码强度是否符合要求 (bool)
        """
        if not password or len(password) < 8:
            return False
            
        # 检查是否包含字母和数字
        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)
        
        # 至少包含一个字母和一个数字，长度不少于8位
        return has_letter and has_digit and len(password) >= 8

    def get_users(self):
        """
        获取用户列表
        
        返回:
        - 成功返回用户列表，失败抛出异常
        """
        params = {
            "path": "Device.Users.User.",
            "optional": {
                "proto": "web"
            }
        }
        
        # 发送请求
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        
        if not result or result[0] != 0:
            raise RuntimeError(f"获取用户列表失败: {result}")
        
        if len(result) < 2:
            raise RuntimeError(f"获取用户列表响应格式错误: {result}")
        
        response_data = result[1]
        if "User" in response_data:
            return response_data["User"]
        else:
            raise RuntimeError(f"未找到用户数据: {response_data}")

    def get_user_info(self, username):
        """
        获取指定用户的信息
        
        参数:
        - username: 用户名 (str)
        
        返回:
        - 用户信息字典 (dict)
        """
        users = self.get_users()
        
        for user in users:
            if user.get("Username") == username:
                return user
                
        raise ValueError(f"用户 {username} 不存在")

    def get_user_level(self, username):
        """
        获取用户权限级别
        
        参数:
        - username: 用户名 (str)
        
        返回:
        - 用户权限级别字符串，如果用户不存在则返回None (str)
        """
        try:
            user_info = self.get_user_info(username)
            return user_info.get(f"{VENDOR_PREFIX}UserLevel")
        except ValueError:
            return None

    def change_password(self, username, old_password, new_password, confirm_password=None):
        """
        修改用户密码
        
        参数:
        - username: 用户名 (str)
        - old_password: 旧密码 (str)
        - new_password: 新密码 (str)
        - confirm_password: 确认密码（可选，如果提供则验证一致性）(str)
        
        返回:
        - 成功返回True，失败抛出异常
        """
        # 验证参数
        if not username or not old_password or not new_password:
            raise ValueError("用户名、旧密码和新密码不能为空")
        
        # 如果提供了确认密码，验证一致性
        if confirm_password and new_password != confirm_password:
            raise ValueError("新密码与确认密码不匹配")
        
        # 验证密码强度
        if not self._check_password_strength(new_password):
            raise ValueError("密码强度不符合要求：密码长度至少8位，必须包含字母和数字")
        
        # 根据用户名获取用户实例ID
        try:
            user_info = self.get_user_info(username)
        except ValueError as e:
            raise ValueError(f"用户 {username} 不存在") from e
        
        user_instance = user_info.get(f"{VENDOR_PREFIX}Instance")
        if not user_instance:
            raise ValueError(f"无法获取用户 {username} 的实例ID")
        
        params = {
            "command": f"Device.Users.User.{user_instance}.{VENDOR_PREFIX}ModifyPasswd()",
            "input": {
                "OldPassword": old_password,
                "NewPassword": new_password,
                "ConfirmPasswd": confirm_password or new_password
            },
            "optional": {
                "proto": "web"
            }
        }
        
        # 发送请求
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)
        
        if not result or result[0] != 0:
            raise RuntimeError(f"修改密码请求失败: {result}")
        
        if len(result) < 2:
            raise RuntimeError(f"修改密码响应格式错误: {result}")
        
        response_data = result[1]
        if "results" in response_data:
            operation_data = response_data["results"][0]
            
            error_num = operation_data.get("error_num")
            if error_num == "2":
                raise ValueError("旧密码验证失败")
            elif error_num == "3":
                raise RuntimeError("修改密码失败：系统内部错误")
            elif error_num == "1":
                fault_msg = operation_data.get("fault_msg", "参数验证失败")
                raise ValueError(f"参数验证失败: {fault_msg}")
            else:
                # 成功
                return True
        else:
            raise RuntimeError(f"修改密码响应格式错误: {response_data}")

    def debug_test(self):
        """调试测试函数"""
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            test_username = "admin"
            old_password = "1234"
            new_password = "Sdmc@123"
            
            print("开始测试获取用户列表...")
            try:
                users = self.get_users()
                print("用户列表:", users)
                
            except Exception as e:
                print("获取用户列表失败:", str(e))
            
            print("\n开始测试获取用户信息...")
            try:
                user_info = self.get_user_info(test_username)
                print(f"用户 {test_username} 信息:", user_info)
                
            except Exception as e:
                print("获取用户信息失败:", str(e))
            
            print("\n开始测试修改密码...")
            try:
                result = self.change_password(
                    username=test_username,
                    old_password=old_password,
                    new_password=new_password,
                    confirm_password=new_password
                )
                print("修改密码成功:", result)
                
            except Exception as e:
                print("修改密码失败:", str(e))
            
            self.ubus.Ubus_Logout()
            
        except Exception as e:
            print("debug test failed:", str(e))

if __name__ == '__main__':
    account_mgr = AccountManagement(ip="192.168.29.1", username="sdmc", password="1234")
    account_mgr.debug_test()
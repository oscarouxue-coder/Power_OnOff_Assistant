import json
from datetime import datetime
import pytz
from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

class NtpManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_ntp_ubus(self):
        """
        【功能描述】
        获取 time 相关参数信息

        【入参】
        无

        【返回值】
        {'Enable': True, 'Status': 'Synchronized', 'NTPServer1': '0.openwrt.pool.ntp.org', 'NTPServer2': '1.openwrt.pool.ntp.org', 'NTPServer3': '2.openwrt.pool.ntp.org', 'NTPServer4': '3.openwrt.pool.ntp.org', 'NTPServer5': '', 'CurrentLocalTime': '2025-10-12T16:18:44+00:00', 'LocalTimeZone': 'UTC', 'X_SDMC_CalendarTime': 1760285924, 'ConvertedLocalTime': '2025-10-13 00:18:44'}


        【示例】
        Example:
        |  get_ntp_ubus  |

        """
        params = {
            "path": "Device.Time.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get('Time')

        # 转换毫秒数为对应时区的本地时间
        if data and 'X_SDMC_CalendarTime' in data and 'LocalTimeZone' in data:
            try:
                # 获取时区信息
                time_zone_str = data.get('LocalTimeZone', 'UTC')
                
                # 将毫秒转换为datetime对象
                timestamp_s = data['X_SDMC_CalendarTime']
                dt_utc = datetime.fromtimestamp(timestamp_s, tz=pytz.UTC)
                
                # 根据时区字符串创建时区对象
                if time_zone_str.upper() == 'UTC':
                    tz_target = pytz.UTC
                else:
                    # 尝试直接使用时区字符串，如果失败则使用UTC
                    try:
                        tz_target = pytz.timezone(time_zone_str)
                    except:
                        tz_target = pytz.UTC
                        log.warning(f"无法识别时区 '{time_zone_str}'，使用UTC时区")
                
                # 转换到目标时区
                dt_local = dt_utc.astimezone(tz_target)
                
                # 添加转换后的本地时间到返回数据中
                data['ConvertedLocalTime'] = dt_local.strftime('%Y-%m-%d %H:%M:%S')
                
            except Exception as e:
                log.error(f"时区转换失败: {str(e)}")
                # 转换失败时添加错误信息
                data['ConvertedLocalTime'] = '转换失败'

        return data

    def set_ntp_ubus(self, time_zone="UTC", ntp_service_enable=True, primary_ntp_server="0.openwrt.pool.ntp.org", secondary_ntp_server="1.openwrt.pool.ntp.org", third_ntp_server="2.openwrt.pool.ntp.org", fourth_ntp_server="3.openwrt.pool.ntp.org"):
        """
        【功能描述】
        设置 NTP 相关参数信息

        【入参】
        time_zone: 时区设置，默认 "UTC"
        ntp_service_enable: NTP服务启用状态，默认 True
        primary_ntp_server: 主要NTP服务器地址，默认 "0.openwrt.pool.ntp.org"
        secondary_ntp_server: 次要NTP服务器地址，默认 "1.openwrt.pool.ntp.org"
        third_ntp_server: 第三NTP服务器地址，默认 "2.openwrt.pool.ntp.org"
        fourth_ntp_server: 第四NTP服务器地址，默认 "3.openwrt.pool.ntp.org"

        【返回值】
        设置成功返回 True，设置失败返回 False

        【示例】
        Example:
        | set_ntp_ubus | time_zone="UTC" | ntp_service_enable=True | primary_ntp_server="0.openwrt.pool.ntp.org" |
        """
        try:
            # 构建设置参数
            ntp_params = {
                "Enable": ntp_service_enable,
                "LocalTimeZone": time_zone,
                "NTPServer1": primary_ntp_server,
                "NTPServer2": secondary_ntp_server,
                "NTPServer3": third_ntp_server,
                "NTPServer4": fourth_ntp_server
            }
            
            # 构建 UBUS 调用参数
            set_params = {
                "paths": [
                    {
                        "addr": "Device.Time.",
                        "obj_path": ntp_params
                    }
                ],
                "optional": {"proto": "web"}
            }
            
            # 执行 UBUS 设置调用
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)
            
            # 检查设置结果
            if result and len(result) > 1:
                # 根据实际返回结构调整判断逻辑
                return True
            else:
                log.error(f"NTP设置失败: 返回结果 {result}")
                return False
                
        except Exception as e:
            log.error(f"设置NTP参数时发生错误: {str(e)}")
            return False

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            
            # 获取当前NTP设置
            print("=== 获取当前NTP设置 ===")
            data = self.get_ntp_ubus()
            print("json is " + str(data))
            
            # # 测试设置NTP参数
            # print("\n=== 测试设置NTP参数 ===")
            # set_result = self.set_ntp_ubus(
            #     time_zone="UTC",
            #     ntp_service_enable=True,
            #     primary_ntp_server="0.openwrt.pool.ntp.org",
            #     secondary_ntp_server="1.openwrt.pool.ntp.org",
            #     third_ntp_server="2.openwrt.pool.ntp.org",
            #     fourth_ntp_server="3.openwrt.pool.ntp.org"
            # )
            # print(f"设置NTP参数结果: {set_result}")
            
            # # 再次获取NTP设置验证
            # print("\n=== 验证设置结果 ===")
            # verify_data = self.get_ntp_ubus()
            # print("设置后的NTP参数: " + str(verify_data))
            
        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))

if __name__ == '__main__':
    ntp = NtpManager(ip="192.168.29.1", username="sdmc", password="1234")
    ntp.debug_test()
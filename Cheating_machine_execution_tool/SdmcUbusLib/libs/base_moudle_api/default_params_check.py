from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class DefaultCheckManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def is_equal(self, value1, value2):
        """
        【功能描述】
        比较两个入参的值是否相同。

        【入参】
        param value1: 任意类型，第一个比较值。
        param value2: 任意类型，第二个比较值。

        【返回值】
        bool 类型：
            - True：两个值相同
            - False：两个值不同

        【示例】
        Example:
            is_equal(10, 10)           -> True
            is_equal("abc", "ABC")     -> False
            is_equal([1, 2], [1, 2])   -> True
            is_equal(None, 0)          -> False
        """
        result = str(value1) == str(value2)
        if not result :
            log.info(f"[DIFF] value1 = {value1}, value2 = {value2}")
            raise AssertionError(f"Values not equal: {value1} != {value2}")
        return result

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            # ntp = NtpManager(self.ip, self.username, self.password)
            # data = ntp.get_ntp_ubus()
            # ret = self.is_equal(data.get('Enable'), "True")

        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))


if __name__ == '__main__':
    default = DefaultCheckManager(ip="192.168.1.1", username="sdmc", password="1234")
    default.ubus.Ubus_Switch('https://192.168.1.1/ubus/')
    default.debug_test()

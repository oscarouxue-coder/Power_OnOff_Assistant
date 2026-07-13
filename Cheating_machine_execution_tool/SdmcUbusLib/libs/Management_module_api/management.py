from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from time import sleep

class ManagementManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def reboot_device(self):
        """
        【功能描述】
            通过 ubus 调用设备重启

        【返回值】
            调用重启节点返回的ubus数据

        """
        params = {
            "command": "Device.Reboot()",
            "optional": {"proto": "web"}
        }

        return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)

    def reset_device(self):
        """
        【功能描述】
            通过 ubus 调用设备恢复出厂

        【返回值】
            调用恢复出厂节点返回的ubus数据

        """
        params = {
            "command": "Device.FactoryReset()",
            "optional": {"proto": "web"}
        }

        return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)


#========================================robot API============================================
    def ubus_reset_device(self, wait_time=180):
        """
        【功能描述】
            设备恢复出厂

        【入参】
            wait_time:默认180s，重启等待时间

        【返回值】
            调用恢复出厂节点返回的ubus数据

        【Example】
            | ${result} | ubus_reset_device

        """

        try:
            self.reset_device()
            sleep(int(wait_time))
            log.info(f"设备重启中，等待{wait_time}s")

        except Exception as e:
            log.exception(str(e))
            raise

    def ubus_reboot_device(self, wait_time=180):
        """
        【功能描述】
            设备重启

        【入参】
            wait_time:默认180s，重启等待时间

        【返回值】
            调用重启节点返回的ubus数据

        【Example】
            | ${result} | ubus_reboot_device

        """

        try:
            self.reboot_device()
            sleep(int(wait_time))
            log.info(f"设备重启中，等待{wait_time}s")

        except Exception as e:
            log.exception(str(e))
            raise

    def debug_test(self):
        try:
            self.ubus.Ubus_Switch('https://192.168.1.1/ubus/')

            self.ubus.Ubus_Login(self.username, self.password)
            self.reset_device()
            self.ubus.Ubus_Logout()



        except Exception as e:
            print("debug test failed: ", str(e))

if __name__ == '__main__':
    Manage = ManagementManager(ip="192.168.1.1", username="sdmc", password="1234")
    Manage.debug_test();
import os
import json

import requests
import struct
import time
from SdmcLog import log
from SdmcCode import *
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base

UPGRADE_STATUS_MSG = {
    1: "输入参数错误",
    2: "下载固件错误",
    3: "文件不存在",
    4: "固件验证错误",
    5: "软件版本不匹配",
    6: "硬件版本不匹配",
    7: "CRC校验错误",
    8: "固件写入错误",
    9: "升级成功",
    11: "没有固件",
    12: "签名错误"
}


class UpgradeManager:
    def __init__(self, ip, username, password):
        """
        功能描述：初始化升级管理器。

        参数：
        | ip        | 设备 IP 地址（如 "192.168.1.1"）             |
        | username  | 登录用户名                     z              |
        | password  | 登录密码                                     |

        Example:
        | ${mgr}=  |  Create Instance  |  UpgradeManager  |  192.168.1.1  |  admin  |  admin123  |
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    # ==================== 原子接口 ====================
    def login(self):
        """
        功能描述：执行ubus登录

        返回：
        | int | 登录结果，ERR_SUCCESS表示成功 |
        """
        return self.ubus.Ubus_Login(self.username, self.password)

    def upload_file(self, device_url, local_file_path, device_save_path="/tmp/x_sdmc_firmware.pkgtb"):
        """
        功能描述：上传文件到设备（纯上传功能，不包含登录）

        参数：
        | device_url       | 上传接口URL                     |
        | local_file_path  | 本地文件路径                    |
        | device_save_path | 设备端保存路径                  |

        返回：
        | tuple | (status_code, response_text) |
        """

        if not os.path.isfile(local_file_path):
            raise FileNotFoundError(f"本地文件不存在: {local_file_path}")

        filename_only = os.path.basename(device_save_path)
        with open(local_file_path, 'rb') as f:
            files = {'file': (filename_only, f, 'application/octet-stream')}
            data = {'sessionid': self.ubus.ubus_rpc_session, 'filename': device_save_path}
            response = requests.post(device_url, files=files, data=data, timeout=30,verify=False)
            response.raise_for_status()
            return response.status_code, response.text

    def call_upgrade(self):
        """
        功能描述：调用升级接口
        """

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", {
            "command": f"Device.DeviceInfo.{VENDOR_PREFIX}Upgrade()",
            "input": {"URL": "local"}
        })
        return result

    def query_upgrade_status(self):
        """
        功能描述：查询升级状态

        返回：
        | dict | 包含upgrade和status的状态字典 |
        """
        response = self.ubus.Ubus_Call(
            ubus_base.UBUS_SERVICE_BBFDM,
            "get",
            {"path": f"Device.DeviceInfo.{VENDOR_PREFIX}GetUpgradeStatus"},
        )

        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("查询返回格式不正确")

        data = response[1] if isinstance(response[1], dict) else {}
        upgrade_info_str = data.get(f"{VENDOR_PREFIX}GetUpgradeStatus", "")
        if not upgrade_info_str:
            raise ValueError("查询返回无升级信息")

        return json.loads(upgrade_info_str)

    def query_sw_version(self):
        """
        功能描述：查询设备软件版本

        返回：
        | str | 软件版本字符串 |
        """
        response = self.ubus.Ubus_Call(
            ubus_base.UBUS_SERVICE_BBFDM,
            "get",
            {"path": "Device.DeviceInfo.SoftwareVersion"},
        )

        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("查询返回格式不正确")

        data = response[1] if isinstance(response[1], dict) else {}
        version = data.get("SoftwareVersion", "")
        if not version:
            raise ValueError("未获取到软件版本信息")

        return version

    def query_hw_version(self):
        """
        功能描述：查询设备硬件版本

        返回：
        | str | 硬件版本字符串 |
        """
        response = self.ubus.Ubus_Call(
            ubus_base.UBUS_SERVICE_BBFDM,
            "get",
            {"path": "Device.DeviceInfo.HardwareVersion"},
        )

        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("查询返回格式不正确")

        data = response[1] if isinstance(response[1], dict) else {}
        version = data.get("HardwareVersion", "")
        if not version:
            raise ValueError("未获取到硬件版本信息")

        return version

    def read_firmware_header(self, firmware_path, FIP_OFFSET=512):
        """
        功能描述：读取固件文件头部信息

        参数：
        | firmware_path | 固件文件路径 |
        | FIP_OFFSET    | 固件头部偏移，默认 512 |

        返回：
        | tuple | 解包后的固件头部信息 |
        """
        header_format = "<IIII32s32s32sIII32sIIII21I"
        header_size = struct.calcsize(header_format)
        with open(firmware_path, "rb") as f:
            f.seek(FIP_OFFSET)
            data = f.read(header_size)
            if len(data) != header_size:
                raise ValueError("固件头部数据不足")
            return struct.unpack(header_format, data)

    # ==================== 组合功能接口 ====================

    def upload_file_to_device(self, device_url, local_file_path, device_save_path, sessionid):
        """
        功能描述：上传固件文件到设备（包含错误处理和日志记录）。

        参数：
        | 参数名           | 类型   | 说明                     |
        |------------------|--------|--------------------------|
        | device_url       | str    | 设备接收文件的 URL       |
        | local_file_path  | str    | 本地固件文件路径         |
        | device_save_path | str    | 设备保存路径             |
        | sessionid        | str    | 当前 ubus 登录 sessionId |

        返回：
        | 返回值类型 | 说明                     |
        | tuple      | (状态码: int, 消息: str) |

        Example:
        | ${code}  | ${msg}=  |  upload_file_to_device  |  http://192.168.1.1/upload  |  firmware.bin  |  /tmp/fw.bin  |  ${sessionid}  |
        """
        try:
            status_code, msg = self.upload_file(device_url, local_file_path, device_save_path)
            return status_code, msg
        except FileNotFoundError as e:
            print(f"文件未找到: {e}")
            raise
        except requests.RequestException as e:
            print(f"上传请求失败: {e} (URL: {device_url})")
            return 500, f"Upload failed: {str(e)}"
        except Exception as e:
            print(f"未知错误: {e}")
            return 500, f"Internal error: {str(e)}"

    def trigger_upgrade(self):
        """
        功能描述：触发设备执行升级操作。

        参数：
        无

        返回：
        无

        Example:
        |  trigger_upgrade  |
        """
        try:
            self.call_upgrade()
            print("升级指令已触发")
        except Exception as e:
            print(f"调用升级指令异常: {e}")
            raise

    def get_upgrade_status(self, timeout=15, interval=1.0):
        """
            功能描述：查询设备当前的升级状态。

        参数：
            | 参数名    | 类型  | 说明                                   |
            | timeout   | int   | 最大等待时间，单位秒，默认15s          |
            | interval  | float | 查询间隔时间，单位秒，默认1s           |

        返回：
            | 返回值类型 | 说明                                   |
            | int        | 升级状态码（失败返回 -1 或 None）      |

        Example:
            | ${status}=  |  get_upgrade_status  |
        """
        try:
            timeout = int(timeout)
            interval = float(interval)
        except Exception as e:
            log.info(f"参数转换错误: timeout={timeout}, interval={interval}, {e}")
            return None

        start_time = time.time()
        last_status, last_msg = -1, "未知状态"

        try:
            while time.time() - start_time < timeout:
                upgrade_info = self.query_upgrade_status()
                upgrade = int(upgrade_info.get("upgrade", -1))
                status = int(upgrade_info.get("status", -1))
                status_msg = UPGRADE_STATUS_MSG.get(status, "未知状态码")

                log.info(f"当前升级进度: upgrade={upgrade}, status={status}（{status_msg}）")

                last_status, last_msg = status, status_msg

                if status == 9:
                    return status, status_msg

                time.sleep(interval)

            log.info(f"查询升级状态超时：{timeout}s 内未出现 status=9，返回最后状态 {last_status}（{last_msg}）")
            return last_status, last_msg

        except Exception as e:
            log.info(f"查询升级状态异常: {e}")
            return None

    def get_device_swversion(self):
        """
        功能描述：获取设备当前的软件版本号。

        参数：
        无

        返回：
        | 返回值类型 | 说明                 |
        | str        | 软件版本号字符串     |

        Example:
        | ${sw_version}=  |  get_device_swversion  |
        """
        try:
            version = self.query_sw_version()
            print(f"当前设备软件版本: {version}")
            return version
        except Exception as e:
            print(f"获取软件版本信息异常: {e}")
            return None

    def get_device_hwversion(self):
        """
        功能描述：获取设备当前的硬件版本。

        参数：
        无

        返回：
        | 返回值类型 | 说明                |
        | str        | 硬件版本号字符串    |

        Example:
        | ${hw_version}=  |  get_device_hwversion  |
        """
        try:
            version = self.query_hw_version()
            print(f"当前设备硬件版本: {version}")
            return version
        except Exception as e:
            print(f"获取硬件版本信息异常: {e}")
            return None

    def get_firmware_swversion(self, firmware_path):
        """
        功能描述：读取固件文件中的软件版本号。

        参数：
        | 参数名        | 类型   | 说明           |
        |---------------|--------|----------------|
        | firmware_path | str    | 固件文件路径   |

        返回：
        | 返回值类型 | 说明                      |
        | str        | 固件中的软件版本号字符串 |

        Example:
        | ${sw_version}=  |  get_firmware_swversion  |  /tmp/fw.bin  |
        """
        try:
            unpacked = self.read_firmware_header(firmware_path)
            customerswversion_raw = unpacked[5]
            customerswversion = customerswversion_raw.split(b'\x00')[0].decode("utf-8", errors="ignore")
            print(f"固件中的软件版本（CustomerSwVersion）: {customerswversion}")
            return customerswversion
        except Exception as e:
            log.error(f"读取固件版本失败: {e}")
            return None

    def get_firmware_hwversion(self, firmware_path):
        """
        功能描述：读取固件文件中的硬件版本号。

        参数：
        | 参数名        | 类型   | 说明           |
        |---------------|--------|----------------|
        | firmware_path | str    | 固件文件路径   |

        返回：
        | 返回值类型 | 说明                      |
        | str        | 固件中的硬件版本号字符串 |

        Example:
        | ${hw_version}=  |  get_firmware_hwversion  |  /tmp/fw.bin  |
        """
        try:
            unpacked = self.read_firmware_header(firmware_path)
            customerhwversion_raw = unpacked[6]
            customerhwversion = customerhwversion_raw.split(b'\x00')[0].decode("utf-8", errors="ignore")
            print(f"固件中的硬件版本（CustomerHwVersion）: {customerhwversion}")
            return customerhwversion
        except Exception as e:
            print(f"读取固件硬件版本失败: {e}")
            return None

    def upload_and_upgrade(self, device_url, local_file_path, device_save_path, timeout=30, interval=1.0):
        """
        功能描述：上传固件并执行设备升级，完整自动流程。

        参数：
        | 参数名           | 类型   | 说明                     |
        |------------------|--------|--------------------------|
        | device_url       | str    | 设备接收文件的 URL       |
        | local_file_path  | str    | 本地固件文件路径         |
        | device_save_path | str    | 设备保存路径             |
        | timeout   | int   | 最大等待时间，单位秒，默认15s          |
        | interval  | float | 查询间隔时间，单位秒，默认1s           |

        返回：
        | 返回值类型 | 说明                            |
        | int        | 升级状态码，失败返回 None       |

        Example:
        | ${status}=  |  upload_and_upgrade  |  http://192.168.1.1/upload  |  firmware.bin  |  /tmp/fw.bin  |
        """
        try:
            # 登录
            ret = self.login()
            if ret != ERR_SUCCESS:
                print("ubus 登录失败")
                return None
            print("ubus 登录成功")
            # 上传文件
            status_code, msg = self.upload_file_to_device(
                device_url, local_file_path, device_save_path, self.ubus.ubus_rpc_session
            )
            if status_code != 200:
                log.info(f"文件上传失败: {msg}")
                return None
            elif status_code == 200:
                log.info("--------文件上传成功-------------")
            # 触发升级
            self.trigger_upgrade()

            # 获取状态
            return self.get_upgrade_status(timeout=timeout, interval=interval)
        except Exception as e:
            print(f"升级流程执行出错: {e}")
            return None

    def wait_device_reboot(self, timeout=240, interval=20):
        """
        功能描述：等待设备重启完成并重新上线。

        参数：
        | 参数名   | 类型 | 说明                   |
        |----------|------|------------------------|
        | timeout  | int  | 最大等待时间（单位：秒）|
        | interval | int  | 检查间隔时间（单位：秒）|

        返回：
        | 返回值类型 | 说明                       |
        | bool       | True 表示设备已上线，False 表示超时 |

        Example:
        | ${ret}=  |  wait_device_reboot  |  timeout=300  |  interval=60  |
        """
        waited = 0
        while waited < timeout + 1:
            try:
                time.sleep(interval)
                waited += interval
                print(f"尝试重新登录设备，第 {waited // interval} 次 ...")
                ret = self.login()
                if ret == ERR_SUCCESS:
                    print("登录成功，设备已上线")
                    return True
            except Exception as e:
                print(f"登录异常{e}")
                continue
        return False

    # ====================robot接口=======================

    def ubus_upgrade(self, local_path, remote_path="/tmp/x_sdmc_firmware.pkgtb",
                     device_url="http://192.168.29.1/cgi-bin/cgi-upload", timeout=30, interval=1.0):
        """
        功能描述：

        参数：
            local_path          本地 bin 升级路径
            remote_path         ONU设备 升级路径
            timeout            最大等待时间，单位秒，默认15s
            interval           查询间隔时间，单位秒，默认1s

        返回值：
            0 表示 升级成功
            非0值 表示升级失败

            UPGRADE_STATUS_MSG = {
                1: "输入参数错误",
                2: "下载固件错误",
                3: "文件不存在",
                4: "固件验证错误",
                5: "软件版本过低",
                6: "硬件版本过低",
                7: "CRC校验错误",
                8: "固件写入错误",
                9: "升级成功",
                11: "没有固件"
            }

        Example:
        | ${ret} | ${status}   |  Ubus_Upgrade |  e:/tclinux_trxheader_upg.bin | /tmp/x_sdmc_firmware.pkgtb  | http://192.168.29.1/cgi-bin/cgi-upload |

        """
        n_ret = ERR_FAIL
        status = 0

        # 调用上传并升级方法
        log.info("文件名称为：" + local_path)
        status, status_msg = self.upload_and_upgrade(device_url, local_path, remote_path, timeout, interval)

        if status == 9:
            print("等待设备重启 ...")
            if not self.wait_device_reboot():
                raise TimeoutError("等待设备上线超时")

        if status is None:
            desc = "升级失败"
            log.error(desc)

        else:
            desc = f"升级状态: {status}"
            log.info(desc)

            if (status == 9):
                n_ret = ERR_SUCCESS

        return n_ret, status, status_msg

    # ==================== 调试接口 ====================
    def debug_test(self, device_url, local_file_path, device_save_path):
        """
        功能描述：调试测试接口
        """
        self.login()
        ret = self.ubus_upgrade(local_path=local_file_path,device_url=device_url, remote_path=device_save_path)
        print(f"{ret}")

    # ==================== 单元测试接口 ====================
    def unit_test(self, device_url, local_file_path, device_save_path):
        """
        功能描述：执行一次完整的固件升级单元测试流程。步骤包括：
        - 获取本地固件的目标软件版本和硬件版本；
        - 登录设备；
        - 上传固件并触发升级；
        - 等待设备重启上线；
        - 对比设备升级后的版本是否与期望一致。

        参数：
        | device_url       | 上传接口 URL（如 http://192.168.1.1/cgi-bin/upload.cgi）     |
        | local_file_path  | 本地固件文件路径（如 /tmp/fw.bin）                            |
        | device_save_path | 上传到设备后的保存路径（如 /tmp/fw.bin）                      |

        返回：
        | 返回值类型 | 说明                                                             |
        | None       | 无返回值，如失败会抛出异常                                        |

        异常：
        | RuntimeError   | 登录失败或升级失败等错误                                     |
        | TimeoutError   | 等待设备上线超时                                             |
        | AssertionError | 版本校验失败，实际版本与期望不一致                          |

        Example:
        | Unit Test  |  http://192.168.1.1/cgi-bin/upload.cgi  |  /tmp/fw.bin  |  /tmp/fw.bin  |
        """

        print("=== [UNIT TEST] 开始 ===")
        try:
            # 1. 获取固件版本信息
            expected_sw = self.get_firmware_swversion(local_file_path)
            expected_hw = self.get_firmware_hwversion(local_file_path)
            print(f"[UNIT] 固件目标版本 - SW: {expected_sw}, HW: {expected_hw}")
            # 2. 登录
            if self.login() != ERR_SUCCESS:
                raise RuntimeError("[UNIT] ubus 登录失败")
            # 3. 执行升级
            print("[UNIT] 调用 upload_and_upgrade 接口进行升级 ...")
            upgrade_status = self.upload_and_upgrade(device_url, local_file_path, device_save_path)
            if upgrade_status != 9:
                raise RuntimeError(f"[UNIT] 升级失败，状态码: {upgrade_status}")
            # 4. 等待重启
            print("[UNIT] 等待设备重启 ...")
            if not self.wait_device_reboot():
                raise TimeoutError("[UNIT] 等待设备上线超时")
            # 5. 版本校验
            current_sw = self.get_device_swversion()
            current_hw = self.get_device_hwversion()
            print(f"[UNIT] 当前设备版本 - SW: {current_sw}, HW: {current_hw}")
            if expected_sw != current_sw or expected_hw != current_hw:
                raise AssertionError(
                    f"[UNIT TEST] 版本校验失败！目标SW/HW: {expected_sw}/{expected_hw}, 实际: {current_sw}/{current_hw}"
                )
            print("[UNIT TEST] 升级成功，版本一致")
        except Exception as e:
            print(f"[UNIT TEST] 测试失败: {e}")
            raise
        finally:
            print("=== [UNIT TEST] 结束 ===")


# 主函数入口
if __name__ == '__main__':
    """
    主函数入口：
    1. 调用 unit_test 方法执行固件升级；
    2. 输出执行结果。
    """
    n_ret_api = 0
    desc = ""

    print("start ---------------------------\n")

    local_path = "tclinux_trxheader_sig_upg.bin"
    remote_path = "/tmp/x_sdmc_firmware.pkgtb"
    device_url = "http://192.168.29.1/cgi-bin/cgi-upload"

    upgrade = UpgradeManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")

    try:
        n_ret_api = upgrade.debug_test(device_url, local_path, remote_path)
        # n_ret_api = upgrade.unit_test(device_url, local_path, remote_path)
    except Exception as e:
        n_ret_api = -1
        desc = f"执行失败: {e}"
        print(desc)
    else:
        desc = "单元测试完成"

    print("\nfinish ------------------")

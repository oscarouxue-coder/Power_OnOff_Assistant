import argparse
import os
import time
from time import sleep

import requests
import json
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

VENDOR_PREFIX = "X_SDMC_"
UBUS_SERVICE_BBFDM = "bbfdm"

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


class AlignedHelpFormatter(argparse.RawTextHelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=40, width=150)


class SourceAddressAdapter(HTTPAdapter):
    """Transport adapter that allows setting the source address (local bind IP)."""

    def __init__(self, source_address, *args, **kwargs):
        self.source_address = source_address
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs['source_address'] = self.source_address
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


class SdmcUbusLibBase(object):
    """
    SDMC UBUS 测试库（支持多 CPE 并行测试）
    """

    # 注意：以下全部改为实例变量，在 __init__ 中初始化
    ubus_call_fault_flag = 0  # 0: 正常, 1: 错误场景（可保留为类变量，因是配置）

    def __init__(self, local_bind_ip=None):
        """
        :param local_bind_ip: 本地网卡 IP 地址，用于绑定请求源地址（如 "192.168.1.101"）
        """
        self.local_bind_ip = local_bind_ip
        self._session = None
        # 实例变量：每个实例独立
        self.Url = "https://192.168.1.1/ubus/"
        self.Username = "root"
        self.Password = "password"
        self.ubus_rpc_session = None  # 关键：不再是类变量！

    def _get_session(self):
        """获取带源 IP 绑定的 requests Session"""
        if self._session is None:
            self._session = requests.Session()
            if self.local_bind_ip:
                adapter = SourceAddressAdapter((self.local_bind_ip, 0))
                self._session.mount('http://', adapter)
                self._session.mount('https://', adapter)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return self._session

    def Ubus_Switch(self, url):
        self.Url = url

    def Ubus_Login(self, username="root", password="password"):
        self.Username = username
        self.Password = password
        ret = False
        for i in range(50):
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "call",
                    "params": [
                        "00000000000000000000000000000000",
                        "session",
                        "login",
                        {"username": username, "password": password}
                    ]
                }

                response = self._session.post(self.Url, json=payload, verify=False)
                response_data = response.json()

                result = response_data.get("result")
                if not isinstance(result, list) or len(result) < 2:
                    print(f"登录返回格式异常: {response_data}")
                    continue

                result_ret = result[0]
                if result_ret != 0:
                    print(f"登录失败，code={result_ret}")
                    continue

                self.ubus_rpc_session = result[1].get("ubus_rpc_session")
                if self.ubus_rpc_session:
                    ret = True
                    print(f"登录成功，session: {self.ubus_rpc_session}")
                else:
                    print("未获取到有效 ubus_rpc_session")

            except Exception as e:
                print(f"登录异常: {e}")
            if ret:
                break
            time.sleep(1)
        return ret

    def _Ubus_check_error(self, echo):
        if "error" in echo:
            desc = f"ubus post返回错误:{str(echo)}"
            raise Exception(desc)

    def _Ubus_check_fault(self, results):
        results_value = results.get("results")
        if results_value:
            for result in results_value:
                if SdmcUbusLibBase.ubus_call_fault_flag:
                    if "fault" in result:
                        print(f"ubus post返回错误（容错模式）:{result}")
                else:
                    if "fault" in result:
                        desc = f"ubus post返回错误:{result}"
                        print(desc)
                        raise Exception(desc)

    def Ubus_Call(self, ubus_object, ubus_func, params):
        if self.ubus_rpc_session is None:
            raise RuntimeError("未登录或 session 已失效，请先调用 Ubus_Login()")

        if isinstance(params, str):
            params = json.loads(params)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [
                self.ubus_rpc_session,  # 使用实例的 session
                ubus_object,
                ubus_func,
                params
            ]
        }

        response = self._session.post(self.Url, json=payload, verify=False)

        try:
            response_data = response.json()
        except Exception as e:
            desc = f"ubus 返回=({response.text}) 解析 json 出错"
            print(desc)
            raise Exception(desc)

        self._Ubus_check_error(response_data)
        result = response_data.get("result")
        return result

    def Ubus_Logout(self):
        """使用当前有效的 session 主动登出（支持设备 logout 接口）"""
        if not self.ubus_rpc_session:
            print("无有效 session，跳过登出")
            return

        try:
            payload = {
                "command": "Device.X_SDMC_Login.logout()",
                "input": {"SessionId": self.ubus_rpc_session}
            }
            # 调用 logout（使用当前 session）
            self.Ubus_Call(UBUS_SERVICE_BBFDM, "unauthenticated_operate", payload)
            print("登出成功")
        except Exception as e:
            # 登出失败可能是 session 已过期或服务临时不可用，但可接受
            print(f"登出失败（可忽略）: {e}")
        finally:
            self.ubus_rpc_session = None  # 清除引用

    def upload_file(self, local_file_path, device_save_path, device_url):
        if not os.path.isfile(local_file_path):
            raise FileNotFoundError(f"本地文件不存在: {local_file_path}")

        filename_only = os.path.basename(device_save_path)
        with open(local_file_path, 'rb') as f:
            files = {'file': (filename_only, f, 'application/octet-stream')}
            data = {
                'sessionid': self.ubus_rpc_session,
                'filename': device_save_path
            }

            response = self._session.post(device_url, files=files, data=data, timeout=30, verify=False)
            response.raise_for_status()
            return response.status_code, response.text

    def call_upgrade(self):
        result = self.Ubus_Call(UBUS_SERVICE_BBFDM, "operate", {
            "command": f"Device.DeviceInfo.{VENDOR_PREFIX}Upgrade()",
            "input": {"URL": "local"}
        })
        return result

    def upload_file_to_device(self, local_file_path, device_save_path="/tmp/x_sdmc_firmware.pkgtb",
                              device_url="https://192.168.1.1/cgi-bin/cgi-upload"):
        try:
            status_code, msg = self.upload_file(local_file_path, device_save_path, device_url)
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
        try:
            self.call_upgrade()
            print("升级指令已触发")
        except Exception as e:
            print(f"调用升级指令异常: {e}")
            raise

    def query_upgrade_status(self):
        response = self.Ubus_Call(
            UBUS_SERVICE_BBFDM,
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

    def get_upgrade_status(self):
        try:
            upgrade_info = self.query_upgrade_status()
            upgrade = int(upgrade_info.get("upgrade", -1))
            status = int(upgrade_info.get("status", -1))
            status_msg = UPGRADE_STATUS_MSG.get(status, "未知状态码")
            print(f"当前升级进度: upgrade={upgrade}, status={status}（{status_msg}）")
            return status
        except Exception as e:
            print(f"查询升级状态异常: {e}")
            return None

    def upload_and_upgrade(self, local_file_path, device_save_path="/tmp/x_sdmc_firmware.pkgtb",
                           device_url="https://192.168.1.1/cgi-bin/cgi-upload"):
        try:
            status_code, msg = self.upload_file_to_device(local_file_path, device_save_path, device_url)
            if status_code != 200:
                print(f"文件上传失败: {msg}")
                return None
            self.trigger_upgrade()
            return self.get_upgrade_status()
        except Exception as e:
            print(f"升级流程执行出错: {e}")
            return None

    def wait_device_reboot(self, timeout=360, interval=30):
        waited = 0
        while waited < timeout + 1:
            try:
                time.sleep(interval)
                waited += interval
                print(f"尝试重新登录设备，第 {waited // interval} 次 ...")
                ret = self.Ubus_Login(self.Username, self.Password)
                if ret:
                    print("登录成功，设备已上线")
                    # 登出新 session（释放 token，避免 5 分钟等待）
                    self.Ubus_Logout()
                    time.sleep(80)
                    return True
            except Exception as e:
                print(f"登录异常: {e}")
                continue
        return False

    def query_fw_version(self):
        response = self.Ubus_Call(
            UBUS_SERVICE_BBFDM,
            "get",
            {"path": f"Device.DeviceInfo.{VENDOR_PREFIX}BuildTimeStamp"},
        )
        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("查询返回格式不正确")

        data = response[1] if isinstance(response[1], dict) else {}
        version = data.get(f"{VENDOR_PREFIX}BuildTimeStamp", "")
        if not version:
            raise ValueError("未获取到编译时间信息")

        return version

    def query_sw_version(self):
        waited = 0
        while waited < 30:
            try:
                response = self.Ubus_Call(
                    UBUS_SERVICE_BBFDM,
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
            except Exception as e:
                print(f"获取版本号异常: {e}")
                sleep(1)
                continue

    def reset_device(self):
        params = {
            "command": "Device.FactoryReset()",
            "optional": {"proto": "web"}
        }
        return self.Ubus_Call(UBUS_SERVICE_BBFDM, "operate", params)

    def upgrade_main(self, ip, username, password, version_path):
        try:
            self._get_session()
        except Exception as e:
            print("绑定IP失败")
            return False
        device_save_path = '/tmp/x_sdmc_firmware.pkgtb'

        # 先尝试 HTTP，失败再尝试 HTTPS
        url_schemes = ["http", "https"]
        login_success = False
        for scheme in url_schemes:
            url = f"{scheme}://{ip}/ubus/"
            self.Ubus_Switch(url)
            print(f"尝试使用 {scheme.upper()} 登录...", flush=True)
            for k in range(3):
                try:
                    self.Ubus_Login(username, password)
                    print(f"获取的Sessionid为 {self.ubus_rpc_session}", flush=True)
                    login_success = True
                    break
                except Exception as e:
                    print(f"测试异常--{e}")
                    time.sleep(10)
            if login_success:
                break

        if not login_success:
            raise Exception("测试异常，无法登陆")

        device_url = f"{scheme}://{ip}/cgi-bin/cgi-upload"

        print("[UNIT] 3.调用 upload_and_upgrade 接口进行升级 .....", flush=True)
        upgrade_status = self.upload_and_upgrade(version_path, device_save_path, device_url)
        if upgrade_status != 9:
            print(f"[升级失败，状态码: {upgrade_status}")
            return False
        print("[UNIT] 4.等待设备重启 .....", flush=True)
        if not self.wait_device_reboot():
            # raise TimeoutError("[等待设备上线超时 ...")
            print(f"[等待设备上线超时 ...")
            return False
        else:
            return True


if __name__ == "__main__":
    # 示例：绑定到本地 IP 192.168.1.101
    c1 = SdmcUbusLibBase('192.168.1.7')
    c1.upgrade_main(
        ip='192.168.1.1',
        username="sdmc",
        password="1234",
        version_path=r"E:\15-firmware\VTT_7287GB\tclinux_trxheader_sig_upg.bin"
    )

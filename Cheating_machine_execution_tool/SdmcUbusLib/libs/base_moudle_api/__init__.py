"""
设备Status相关api
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.status import StatusManager
from SdmcLog import log
from SdmcCode import *
import inspect

from SdmcUbusLib.libs.base_moudle_api.upgrade import UpgradeManager
from SdmcUbusLib.libs.base_moudle_api.port_mirror import MirrorManager
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base
from SdmcUbusLib.libs.base_moudle_api.ppctl_verify import PpctlVerifyManager
from SdmcUbusLib.libs.base_moudle_api.default_params_check import DefaultCheckManager


class SdmcBasesLib(object):
    """
    测试库 demo for class
    """

    def __init__(self):
        """
        """

        self._get_self_keywords()

    def _get_self_keywords(self):
        """
        """
        self.keywords = []

        # ✅ 自动发现：所有以 "MyLibrary_" 开头的方法
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("Ubus_") or name.startswith("Telnet_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)

    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        return names

    def _Ubus_Status_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.status = StatusManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_Status_get_device_info(self):
        """
        功能描述：\n
        获取Status中的device info

        返回值：\n
        返回一个字典，为所有device info中的各个信息

        {'Model': 'NPE3039GB', 'MAC Address': '2C:EC:F7:BB:4C:56', 'Hardware Version': 'V1.0', 'Software Version': 'S13.4B.01.001', 'Uptime': '1 Day 02 Hour 14 Minute 28 Seconds', 'System Time': '2025/07/30 05:52:06', 'Firmware Time': 'Thu Jul 10 04:15:44 UTC 2025', 'Device SN': '24C0010191000078', 'CPU Usage': '9 %', 'Memory Usage': '59 %', 'Temperature': '61 ℃'}

        Example:
        | ${ret} |  Ubus_Status_get_device_info  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        device_info = Status_info.get_device_info()
        if device_info == 0:
            raise ValueError("获取Device info失败")
        return device_info

    def Ubus_Status_get_wan_info(self):
        """
        功能描述：\n
        获取status中的wan的详细信息

        返回值：\n
        以字典的形式返回所有wan的信息
        {
            "2": {
                "Name": "3_INTERNET_R_VID_200",
                "MAC": "2C:EC:F7:BB:4C:57",
                "IPv4": "172.18.18.54",
                "IPv4Gateway": "172.18.18.1",
                "Status": "Up",
                "Uptime": "0 Day 00 Hour 11 Minute 57 Seconds",
                "PrimaryDNSv4": "202.96.134.133",
                "SecondaryDNSv4": "152.152.152.222"
            },
            "3": {
                "Name": "4_TR069_R_VID_50",
                "MAC": "2C:EC:F7:BB:4C:58",
                "IPv4": "10.50.100.113",
                "IPv4Gateway": "10.50.100.1",
                "Status": "Up",
                "Uptime": "0 Day 00 Hour 07 Minute 46 Seconds",
                "PrimaryDNSv4": "152.152.152.222",
                "SecondaryDNSv4": ""
            }
        }

        Example:
        | ${ret} |  Ubus_Status_get_wan_info  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        wan_info = Status_info.get_wan_info()
        if wan_info == 0:
            raise ValueError("获取WAN info失败")
        return wan_info

    def Ubus_Status_manage_wan(self, method, wan_index):
        """
        功能描述：\n
        设置wan的release和renew

        入参：\n
        method：操作类型，"Release" 或 "Renew" \n
        wan_index: WAN 接口索引号

        Example:
        |  Ubus_Status_get_wan_info  | Release | 2 |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        manage_wan = Status_info.manage_wan(method, wan_index)
        if manage_wan == 0:
            raise ValueError("设置release renew失败")

    def Ubus_Status_get_wan_index(self, wan_name):
        """
        功能描述：\n
        获取wan index

        入参：\n
        wan_name:WAN的名称，可以通过 Ubus_Status_get_wan_info 获取

        返回值：\n
        wan_index: wan 序号

        Example:
        | ${ret} |  Ubus_Status_get_wan_index  |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        wan_index = Status_info.get_interface_instance_by_name(wan_name)
        if wan_index == False:
            raise ValueError("获取wan_index失败")
        return wan_index

    def Ubus_Status_get_connect_host_info(self):
        """
        【功能描述】
            获取 client 下 Router 模式连接的 host信息

        【返回值】
            [{'hostname': 'H1148', 'ip': '192.168.29.221', 'mac': 'f8:e4:3b:6f:0a:21', 'type': 'Ethernet', 'linkport': 'eth2.0', "Active": true}, {'hostname': 'H1148', 'ip': '192.168.29.8', 'mac': 'bc:cd:99:f7:c3:62', 'type': 'Wi-Fi', 'linkport': '!!!SDMC_221100_5G',"Active": true}]


        【示例】
            Example:
            |  result  |  get_connected_hosts_info  |
        """
        self._Ubus_Status_init()
        host_list = self.status.get_connected_hosts_info()
        return host_list

    def Ubus_Status_get_pon_info(self):
        """
        【功能描述】
        获取光模块（PON模块）的运行信息
        【入参】
        无

        【返回值】
        pon_info : dict
            返回光模块的状态信息，示例如下：
            {
                "ONT Registration Status": "Online",
                "Working Temperature": "45.2℃",
                "TX Optical Power": "-1.23 dBm",
                "RX Optical Power": "-18.56 dBm",
                "Working Voltage": "3300 mV",
                "Working Current": "12.5 mA"
            }

            若未获取到 Optical.Interface 信息，则返回空字典 {}

        【示例】
        Example:
        |  Get Pon Info  |
        """
        self._Ubus_Status_init()
        pon_info = self.status.get_poninfo()
        return pon_info

    def Telnet_get_chip_name(self):
        """
        【功能描述】
            获取产品方案名称

        【返回值】
            airoha或者bcmxxx(xxx为芯片名称)

        【示例】
        Example:
        |  chip_name  |  get_chip_name  |

        """
        self._Ubus_Status_init()
        chip_name = self.status.get_chip_name()
        return chip_name

    def Ubus_Status_get_lan_port_status(self):
        """
        【功能描述】
            获取 LAN 端口状态信息，包括端口模式、速度、链状态、接收/发送字数和包数
        
        【返回值】
        lan_port_status : list
            返回LAN端口状态信息列表，示例如下：
            [
                {
                    "port": "LAN1",
                    "mode": "Full",
                    "speed": 1000,
                    "link": "Up",
                    "rxbytes": 12345678,
                    "rxpackets": 98765,
                    "txbytes": 87654321,
                    "txpackets": 54321
                },
                {
                    "port": "LAN2",
                    "mode": "Half",
                    "speed": 100,
                    "link": "Down",
                    "rxbytes": 0,
                    "rxpackets": 0,
                    "txbytes": 0,
                    "txpackets": 0
                }
            ]
        
        【示例】
        Example:
        | ${ret} |  Ubus_Status_get_lan_port_status  |
        """
        try:
            self._Ubus_Status_init()
            lan_port_status = self.status.get_lan_port_status()
            return lan_port_status
        except Exception as e:
            log.exception(f"获取LAN端口状态失败: {str(e)}")
            raise RuntimeError(f"获取LAN端口状态失败: {str(e)}")

    def _Ubus_upgrade_init(self):

        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            # 实例化 UpgradeManager 类
            self.upgrade_manager = UpgradeManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_Upload_File(self, device_url, local_file_path, device_save_path="/tmp/x_sdmc_firmware.pkgtb"):
        """
        功能描述：上传文件到设备
        
        参数：
            | device_url       | 上传接口URL                     |
            | local_file_path  | 本地文件路径                    |
            | device_save_path | 设备端保存路径，默认为"/tmp/x_sdmc_firmware.pkgtb" |
        
        返回：
            | tuple | (status_code, response_text) |
            
        Example:
        | ${status} | ${response} | Ubus_Upload_File | http://192.168.1.1/cgi-bin/upload.cgi | /path/to/file.bin | /tmp/destination.bin |
        """
        self._Ubus_upgrade_init()
        status_code, response_text = self.upgrade_manager.upload_file(device_url, local_file_path, device_save_path)
        return status_code, response_text

    def Ubus_Upgrade(self, local_path, remote_path="/tmp/x_sdmc_firmware.pkgtb",
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
        self._Ubus_upgrade_init()
        n_ret, status, status_msg = self.upgrade_manager.ubus_upgrade(local_path, remote_path, device_url, timeout, interval)

        return n_ret, str(f"{status}：{status_msg}")

    def Ubus_Upgrade_Trigger(self):
        """
        【功能描述】
        触发设备执行升级操作。

        【入参】
        无

        【返回值】
        无

        【示例】
        Example:
        |  Ubus_Upgrade_Trigger  |
        """
        self._Ubus_upgrade_init()
        self.upgrade_manager.trigger_upgrade()

    def Ubus_Upgrade_Get_Status(self, timeout=15, interval=1.0):
        """
        【功能描述】
        查询设备当前的升级状态。

        【入参】
        | 参数名    | 类型  | 说明                                   |
        | timeout   | int   | 最大等待时间，单位秒，默认15s          |
        | interval  | float | 查询间隔时间，单位秒，默认1s           |

        【返回值】
        | 返回值类型 | 说明                                   |
        | tuple      | 升级状态码和状态消息，失败返回 (None, None) |

        【示例】
        Example:
        | ${status} | ${message} |  Ubus_Upgrade_Get_Status  |
        """
        self._Ubus_upgrade_init()
        result = self.upgrade_manager.get_upgrade_status(timeout=timeout, interval=interval)
        
        if result is None:
            return None, None
        
        if isinstance(result, tuple) and len(result) == 2:
            return result[0], result[1]
        else:
            return result, "未知状态"

    def Ubus_Switch_ubus_service(self, new_service: str):
        """
        【功能描述】
        切换调用ubus_call使用的方法

        【入参】
        new_service: 切换的方法

        【返回值】
        执行成功无返回值，执行失败会报异常

        【示例】
        Example:
        |  Ubus_Switch_ubus_service |  new_service=bbfdm  |

        """
        ubus_base.switch_ubus_service(new_service)

    def _Ubus_Ppctlverify_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            # 实例化 UpgradeManager 类
            self.ppctlverify_manager = PpctlVerifyManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_get_sn(self):
        """
        【功能描述】
        获取设备序列号（SN）。

        【入参】
        无

        【返回值】
        str : 返回设备序列号字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_sn  |
        返回示例: "SN1234567890"
        """
        self._Ubus_Ppctlverify_init()
        sn = self.ppctlverify_manager.ubus_get_sn()

        return sn

    def Ubus_get_lan_mac(self):
        """
        【功能描述】
        获取设备 LAN 接口的 MAC 地址。

        【入参】
        无

        【返回值】
        str : 返回 LAN MAC 地址字符串，例如 "00:11:22:33:44:55"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_lan_mac  |
        返回示例: "00:11:22:33:44:55"
        """
        self._Ubus_Ppctlverify_init()
        lan_mac = self.ppctlverify_manager.ubus_get_lan_mac()

        return lan_mac

    def Ubus_get_xpon_sn(self):
        """
       【功能描述】
       获取光猫/ONU 的 XPON 认证序列号。

       【入参】
       无

       【返回值】
       str : 返回 XPON 认证序列号字符串，如果获取失败返回 None。

       【示例】
       Example:
       |  ubus_get_xpon_sn  |
       返回示例: "XPON1234567890"
       """
        self._Ubus_Ppctlverify_init()
        xpon_sn = self.ppctlverify_manager.ubus_get_xpon_sn()

        return xpon_sn

    def Ubus_get_lan_ip(self):
        """
        【功能描述】
        获取 LAN 接口的 IP 地址。

        【入参】
        无

        【返回值】
        str : 返回 LAN IP 地址字符串，例如 "192.168.1.1"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_lan_ip  |
        返回示例: "192.168.1.1"
        """
        self._Ubus_Ppctlverify_init()
        lan_ip = self.ppctlverify_manager.ubus_get_lan_ip()

        return lan_ip

    def Ubus_get_24G_ssid(self):
        """
        【功能描述】
        获取 2.4GHz 无线网络的 SSID。

        【入参】
        无

        【返回值】
        str : 返回 2.4G SSID 字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_24G_ssid  |
        返回示例: "MyWifi_2.4G"
        """
        self._Ubus_Ppctlverify_init()
        ssid = self.ppctlverify_manager.ubus_get_24G_ssid()

        return ssid

    def Ubus_get_24G_key(self):
        """
        【功能描述】
        获取 2.4GHz 无线网络的 WPA 预共享密钥。

        【入参】
        无

        【返回值】
        str : 返回 2.4G WPA 密钥，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_24G_key  |
        返回示例: "12345678"
        """
        self._Ubus_Ppctlverify_init()
        key = self.ppctlverify_manager.ubus_get_24G_key()

        return key

    def Ubus_get_5G_ssid(self):
        """
        【功能描述】
        获取 5GHz 无线网络的 SSID。

        【入参】
        无

        【返回值】
        str : 返回 5G SSID 字符串，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_5G_ssid  |
        返回示例: "MyWifi_5G"
        """
        self._Ubus_Ppctlverify_init()
        ssid = self.ppctlverify_manager.ubus_get_5G_ssid()

        return ssid

    def Ubus_get_5G_key(self):
        """
        【功能描述】
        获取 5GHz 无线网络的 WPA 预共享密钥。

        【入参】
        无

        【返回值】
        str : 返回 5G WPA 密钥，如果获取失败返回 None。

        【示例】
        Example:
        |  ubus_get_5G_key  |
        返回示例: "87654321"
        """
        self._Ubus_Ppctlverify_init()
        key = self.ppctlverify_manager.ubus_get_5G_key()

        return key

    def Ubus_get_24G_ccode(self):
        """
        【功能描述】
        通过 telnet 获取 2.4GHz 无线网络的国家码 (country code)。

        【入参】
        无

        【返回值】
        str : 返回 2.4G 国家码，例如 "US"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_telnet_get_24G_ccode  |
        返回示例: "US"
        """
        self._Ubus_Ppctlverify_init()
        ccode = self.ppctlverify_manager.ubus_telnet_get_24G_ccode()

        return ccode

    def Ubus_get_5G_ccode(self):
        """
        【功能描述】
        通过 telnet 获取 5GHz 无线网络的国家码 (country code)。

        【入参】
        无

        【返回值】
        str : 返回 5G 国家码，例如 "US"，获取失败返回 None。

        【示例】
        Example:
        |  ubus_telnet_get_5G_ccode  |
        返回示例: "US"
        """
        self._Ubus_Ppctlverify_init()
        ccode = self.ppctlverify_manager.ubus_telnet_get_5G_ccode()

        return ccode

    def _Ubus_defaultcheck_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            # 实例化 UpgradeManager 类
            self.defaultcheck = DefaultCheckManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_check_param(self, standard, checkparam):
        """
        【功能描述】
        比较两个入参的值是否相同。

        【入参】
        param standard: 任意类型，标准值。
        param checkparam: 任意类型，比较值。

        【返回值】
        bool 类型：
            - True：两个值相同
            - False：两个值不同

        【示例】
        |  Ubus_check_param  | standard | checkparam |
        """
        self._Ubus_defaultcheck_init()
        ret = self.defaultcheck.is_equal(standard, checkparam)
        return ret

    def run_keyword(self, name, args, kwargs=None):
        """
        """
        method_name = name
        if hasattr(self, method_name):
            return getattr(self, method_name)(*args, **kwargs)

    def get_keyword_documentation(self, name):
        """
        """
        method_name = name.replace(" ", "_")
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            doc = inspect.getdoc(method)
            return doc if doc else "No documentation provided."

    def get_keyword_arguments(self, name):
        """返回关键字的参数列表"""
        method_name = name
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            sig = inspect.signature(method)

            args = []
            for p in sig.parameters.values():
                if p.name == "self":
                    continue
                if p.kind == p.VAR_POSITIONAL:
                    args.append("*" + p.name)  # *args
                elif p.kind == p.VAR_KEYWORD:
                    args.append("**" + p.name)  # **kwargs
                elif p.default is inspect._empty:
                    args.append(p.name)  # 必填参数
                else:
                    args.append(f"{p.name}={p.default!r}")  # 带默认值的参数
            return args

    def _Ubus_Management_Port_Mirror_Init(self):
        """
        功能描述：

        参数： \n

        返回值：
        0 表示 设置成功
        非0值 表示设置失败


        Example:

        """
        parsed_url = urlparse(SdmcUbusLibBase.Url)
        ip = parsed_url.hostname

        username = SdmcUbusLibBase.Username
        password = SdmcUbusLibBase.Password

        self.port_mirror = MirrorManager(ip, username, password)

        n_ret = ERR_SUCCESS


        return n_ret

    def Ubus_Management_Get_Port_Mirror_Status(self):
        """
        【功能描述】
            获取镜像开启状态
        【入参】
            无
        【返回值】

        【示例】
        Example:

        """
        self._Ubus_Management_Port_Mirror_Init()
        port_mirror = self.port_mirror
        status = port_mirror.get_port_mirror_status()
        return status

    def Ubus_Management_Set_Port_Mirror_Status(self, status="0"):
        """
        【功能描述】
            设置镜像开启关闭状态
        【入参】
            param status: str - 状态0表示关闭，1表示开启（默认值="0"）
        【返回值】

        【示例】
        Example:

        """
        self._Ubus_Management_Port_Mirror_Init()
        port_mirror = self.port_mirror
        ret = port_mirror.set_port_mirror_status(status)
        return ret


    def Ubus_status_get_voip_info(self):
        """
        【功能描述】
        获取VoIP信息，包括Name、DisplayName、registration status和subscriber line status

        【返回值】
        返回一个字典，包含以下信息：
        {
            "Name": "LineIndex值",
            "DisplayName": "DisplayName值",
            "RegistrationStatus": "LineStatus值",
            "SubscriberLineStatus": "CallStatus值"
        }

        【示例】
        Example:
        | ${ret} | Ubus_status_get_voip_info |
        """
        self._Ubus_Status_init()
        Status_info = self.status
        voip_info = Status_info.get_voip_info()
        if not voip_info:
            raise ValueError("获取VoIP信息失败")
        return voip_info


if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    # logging.getLogger().setLevel(logging.DEBUG)
    # logging.basicConfig(filename='example.log',level=logging.INFO)

    print("start ---------------------------\n")

    print("\nfinish ------------------")
    # os.system("pause")

"""
TR069,TR369,STUN,XMPP相关的api接口
"""

from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcLog import log
from SdmcCode import *
from SdmcUbusLib.libs.Management_module_api.cwmp import CwmpManager
import inspect
from time import sleep
import time
from SdmcUbusLib.libs.Management_module_api.management import ManagementManager
from SdmcUbusLib.libs.Management_module_api.log_fuc import LogManager
from SdmcUbusLib.libs.Management_module_api.usp import UspManager
from SdmcUbusLib.libs.Management_module_api.stun_xmpp import StunXmppManager
from SdmcUbusLib.libs.Management_module_api.tcpdump import TcpdumpManager
from SdmcUbusLib.libs.Management_module_api.speedtest import SpeedtestManager
from SdmcUbusLib.libs.Management_module_api.accountmanagement import AccountManagement
from SdmcUbusLib.libs.Management_module_api.maintenance import MaintenanceManager
from SdmcUbusLib.libs.Management_module_api.restore_archive import RestoreArchiveManager


class SdmcManagementLib(object):
    """
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
            if name.startswith("Ubus_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)

    def _Ubus_Cwmp_Init(self):
        """
        功能描述：
            初始化Cwmp类

        返回值：
            0 表示 设置成功
            非0值 表示设置失败

        """
        n_ret = ERR_FAIL

        for nwf in [1]:

            try:

                parsed_url = urlparse(SdmcUbusLibBase.Url)
                ip = parsed_url.hostname

                username = SdmcUbusLibBase.Username
                password = SdmcUbusLibBase.Password

                self.cwmp = CwmpManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_Management_cwmp_set_TR069_parameters(self, **kwargs):
        """
        功能描述：\n
        设置 CWMP (TR069) 参数

        参数：\n
        Url：ACS服务器地址
        Username：正向连接的用户名，默认 hgw,对应页面 ACS Account
        Password：正向连接的密码，默认 hgw,对应页面 ACS Password
        Period_Inform_Enable：周期上报使能开关，默认开启：1，关闭：0
        Periodic_Inform_Interval：周期上报间隔，默认86400s
        HTTP_Connection_Request_Enable：默认开启:1,关闭:0,对应页面Connection Request
        Connection_Request_Username:默认itms,对应页面 User Name
        Connection_Request_Password:默认 itms,对应页面 Password
        Certificate_Enable:默认关闭:0,开启:1,对应页面 Enable Certificate

        返回值：\n
        ret:设置TR069参数的UBUS 接口返回值

        Example:
        | ${ret} |  Ubus_set_TR069_parameters  |
        | ${ret} |  Ubus_set_TR069_parameters  | Period_Inform_Enable=Fasle
        """
        ret = {}
        self._Ubus_Cwmp_Init()
        cwmp_manager = self.cwmp

        ret = cwmp_manager.set_tr069_setting(**kwargs)
        if ret:
            return ret

        desc = f"设置 TR069 参数失败"
        raise Exception(desc)

    def Ubus_Management_cwmp_get_TR069_parameters(self):
        """
        功能描述：\n
        获取TR069参数并返回

        入参：\n

        返回值：\n
        以字典格式存储当前 TR069 参数
        ret:{'PeriodicInformEnable': False, 'PeriodicInformInterval': 86400, 'CertificateEnable': False,...}

        Example:
        |  ${ret}  |  Ubus_get_TR069_parameters  |
        """
        ret = {}
        self._Ubus_Cwmp_Init()
        ret = self.cwmp.get_tr069_setting_info()
        if ret:
            return ret

        desc = f'get TR069 设置参数失败'
        raise Exception(desc)

    def Ubus_Management_cwmp_TR069_inform(self, inform_times=10):
        """
        功能描述：\n
        TR069 Inform，并获取Inform状态，success后退出返回结果，如果不是 success 则持续等待重新Inform并获取结果

        入参：\n
        inform_times：inform 失败后重试次数

        返回值：\n
        tuple: (最终状态, 结果代码)
        状态值: "success"、"timeout"、"error"
        结果代码: 对应各种错误码或成功码(10_success)

        Example:
        |  ${ret}  |  inform_times=10  |
        """
        ret = ()

        inform_times = int(inform_times)
        self._Ubus_Cwmp_Init()
        count = 1
        while True:
            ret = self.cwmp.inform_tr069()
            log.info(f'第{count}次 inform 的结果是：{ret}')
            if ret[0] == 'success':
                return ret
            if count == inform_times:
                break
            count += 1
            sleep(5)
        if ret and ret[0] != 'error':
            return ret
        desc = f"TR069 Inform 失败:{ret}"
        log.info(desc)
        raise Exception(desc)

    def Ubus_Management_cwmp_TR069_get_inform_status(self, timeout=60):
        """
        功能描述：\n
        查询TR069 inform状态，并返回查询结果

        入参：\n
        timeout: 等待 finish_inform 时间

        返回值：\n
        inform_status(元组):　inform 成功返回 ("success", "成功")/inform 失败返回 ('error', '失败类型')

        Example：
        |  ${ret}  |  ubus_TR069_get_inform_status  |
        """
        self._Ubus_Cwmp_Init()
        cwmp_manager = self.cwmp

        return cwmp_manager.get_tr069_inform_status()

    def _Ubus_Management_init(self):
        """
        功能描述：
            初始化Management类
        返回值：
            0 表示 设置成功
            非0值 表示设置失败

        """
        n_ret = ERR_FAIL

        for nwf in [1]:

            try:

                parsed_url = urlparse(SdmcUbusLibBase.Url)
                ip = parsed_url.hostname

                username = SdmcUbusLibBase.Username
                password = SdmcUbusLibBase.Password

                self.management = ManagementManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_reset_device(self, wait_time):
        """
        【功能描述】
            设备恢复出厂

        【入参】
            wait_time:默认180s，重启等待时间

        【返回值】
            调用恢复出厂节点返回的ubus数据

        【Example】
            | ${result} | Ubus_reset_device

        """
        self._Ubus_Management_init()
        self.management.ubus_reset_device(wait_time)

    def Ubus_reboot_device(self, wait_time):
        """
        【功能描述】
            设备恢复出厂

        【入参】
            wait_time:默认180s，重启等待时间

        【返回值】
            调用重启节点返回的ubus数据

        【Example】
            | ${result} | Ubus_reboot_device

        """
        self._Ubus_Management_init()
        self.management.ubus_reboot_device(wait_time)

    def _Ubus_log_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.log = LogManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_get_log_info(self):
        """
        【功能描述】
        获取设备的日志配置信息，包括日志功能是否启用、日志记录等级以及日志记录模块。

        【入参】
        无

        【返回值】
        {'Enable': True, 'Log Level': 'info', 'Log Mode': 'ALL'}

        【示例】
        Example:
        |  Ubus_get_log_info  |

        """
        self._Ubus_log_init()
        ret = self.log.get_log_info()
        return ret

    def _Ubus_stunxmpp_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.stunxmpp = StunXmppManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_get_stun_setting_info(self):
        """
        【功能描述】
        获取stun配置信息

        【入参】
        无

        【返回值】
        {'STUNEnable': False, 'STUNServerPort': 19302, 'STUNServerAddress': '', 'STUNUsername': '', 'STUNPassword': '', 'STUNMaximumKeepAlivePeriod': 3600, 'STUNMinimumKeepAlivePeriod': 30}

        【示例】
        Example:
        |  Ubus_get_log_info  |

        """
        self._Ubus_stunxmpp_init()
        ret = self.stunxmpp.get_stun_setting_info()
        return ret

    def Ubus_get_xmpp_setting_info(self):
        """
        【功能描述】
        获取stun配置信息

        【入参】
        无

        【返回值】
        {'XMPPEnable': False, 'XMPPDnsSrvPort': 5222, 'XMPPDomain': '', 'XMPPUsername': '', 'XMPPPassword': '', 'XMPPResource': '', 'XMPPServerConnectAlgorithm': 'DNS-SRV', 'XMPPUseTLS': False}

        【示例】
        Example:
        |  Ubus_get_log_info  |

        """
        self._Ubus_stunxmpp_init()
        ret = self.stunxmpp.get_xmpp_setting_info()
        return ret

    def _Ubus_usp_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.usp = UspManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_get_usp_info(self):
        """
        【功能描述】
        获取 USP 相关参数信息

        【入参】
        无

        【返回值】
        {'Enable': False, 'BrokerAddress': '172.18.18.xxx', 'BrokerPort': 1883, 'MQTT_Username': 'usp', 'MQTT_Password': 'usp', 'Agent_EndpointID': 'proto::agent-1', 'Agent_ResponseTopicConfigured': '/usp/agent/1', 'Controller_EndpointID': 'proto::controller-1', 'Controller_Topic': '/usp/controller/1', 'Controller_PeriodicNotifInterval': 86400}


        【示例】
        Example:
        |  Ubus_get_usp_info  |

        """
        self._Ubus_usp_init()
        ret = self.usp.get_ups_ubus()
        return ret

    def _Ubus_tcpdump_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.tcpdump = TcpdumpManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_start_tcpdump_capture(self, duration=60, interface="any", packet_type="All"):
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
            | ${result} | Ubus_start_tcpdump_capture | duration=30 | interface="eth0" |
        """
        self._Ubus_tcpdump_init()
        ret = self.tcpdump.start_tcpdump_capture(duration, interface, packet_type)
        return ret

    def Ubus_stop_tcpdump_capture(self):
        """
        【功能描述】
            停止TCPDump抓包（支持手动停止和时长自动停止）
        
        【入参】
            无
        
        【返回值】
            抓包停止的结果数据
        
        【示例】
            | ${result} | Ubus_stop_tcpdump_capture |
        """
        self._Ubus_tcpdump_init()
        ret = self.tcpdump.stop_tcpdump_capture()
        return ret

    def Ubus_download_tcpdump_file(self, download_path="./"):
        """
        【功能描述】
            下载抓包文件到指定路径
        
        【入参】
            download_path: 下载文件保存路径，默认当前目录
        
        【返回值】
            下载结果信息，包含文件路径等
        
        【示例】
            | ${result} | Ubus_download_tcpdump_file | download_path="/tmp/" |
        """
        self._Ubus_tcpdump_init()
        ret = self.tcpdump.download_capture_file(download_path)
        return ret

    def Ubus_get_tcpdump_status(self):
        """
        【功能描述】
            获取当前抓包状态
        
        【入参】
            无
        
        【返回值】
            抓包状态信息
        
        【示例】
            | ${result} | Ubus_get_tcpdump_status |
        """
        self._Ubus_tcpdump_init()
        ret = self.tcpdump.get_capture_status()
        return ret

    def _Ubus_speedtest_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.speedtest = SpeedtestManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_start_speedtest(self, test_url, test_direction, wan_name):
        """
        【功能描述】
            开始speedtest测速
        
        【入参】
            test_url: 测速URL (str)
            test_direction: 测试方向，"download" 或 "upload" (str)
            wan_name: wan名称，如"3_INTERNET_B_VID_200" (str)
        
        【返回值】
            成功返回True，失败抛出异常
        
        【示例】
            | ${result} | Ubus_start_speedtest | test_url="http://172.18.18.239:8080/1G.txt" | test_direction="download" | wan_name="3_INTERNET_B_VID_200" |
        """
        self._Ubus_speedtest_init()
        ret = self.speedtest.start_speedtest(test_url, test_direction, wan_name)
        return ret

    def Ubus_get_speedtest_result(self, test_direction, wan_name):
        """
        【功能描述】
            获取speedtest测速结果
        
        【入参】
            test_direction: 测试方向，"download" 或 "upload" (str)
            wan_name: wan名称，如"3_INTERNET_B_VID_200" (str)
        
        【返回值】
            DiagnosticsState: 测速状态字符串
        
        【示例】
            | ${result} | Ubus_get_speedtest_result | test_direction="download" | wan_name="3_INTERNET_B_VID_200" |
        """
        self._Ubus_speedtest_init()
        ret = self.speedtest.get_speedtest_result(test_direction, wan_name)
        return ret

    def _Ubus_accountmanagement_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.accountmanagement = AccountManagement(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_modify_user_password(self, username, old_password, new_password):
        """
        【功能描述】
            修改用户密码
        
        【入参】
            username: 用户名
            old_password: 旧密码
            new_password: 新密码
        
        【返回值】
            修改密码操作的结果信息
        
        【示例】
            | ${result} | Ubus_modify_user_password | username="admin" | old_password="admin" | new_password="Sdmc@123" |
        """
        self._Ubus_accountmanagement_init()
        ret = self.accountmanagement.change_password(username, old_password, new_password)
        return ret

    def _Ubus_maintenance_init(self):
        """
        """
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.maintenance = MaintenanceManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_start_network_diagnosis(self, wan_name, target_host, diagnosis_type):
        """
        【功能描述】
            开始网络诊断（ping或traceroute）
        
        【入参】
            wan_name: WAN接口名称，如"3_INTERNET_B_VID_200" (str)
            target_host: 目标IP地址或域名，如"www.baidu.com" (str)
            diagnosis_type: 诊断类型，"ipv4_ping"、"ipv6_ping"、"ipv4_traceroute"、"ipv6_traceroute" (str)
        
        【返回值】
            成功返回诊断结果字符串，失败抛出异常
        
        【示例】
            | ${result} | Ubus_start_network_diagnosis | wan_name="3_INTERNET_B_VID_200" | target_host="www.baidu.com" | diagnosis_type="ipv4_ping" |
        """
        self._Ubus_maintenance_init()
        ret = self.maintenance.start_diagnosis(wan_name, target_host, diagnosis_type)
        return ret

    def _Ubus_restore_archive_init(self):
        """
        初始化RestoreArchiveManager类
        返回值：
            0 表示 设置成功
            非0值 表示设置失败
        """
        n_ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.restore_archive = RestoreArchiveManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_upload_and_restore_config(self, config_file_path):
        """
        【功能描述】
            上传配置文件到设备并触发恢复配置操作
        
        【入参】
            config_file_path: 本地配置文件路径
        
        【返回值】
            dict: 包含上传和恢复操作的结果信息
        
        【示例】
            | ${result} | Ubus_upload_and_restore_config | /path/to/config.tar.gz |
        """
        self._Ubus_restore_archive_init()
        ret = self.restore_archive.upload_and_restore_config(config_file_path)
        return ret


    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        return names

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



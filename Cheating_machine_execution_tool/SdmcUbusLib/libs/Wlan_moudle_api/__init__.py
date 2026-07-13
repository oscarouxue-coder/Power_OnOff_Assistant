"""
WiFi,访客网络,组网相关api
"""

from SdmcUbusLib.libs.Wlan_moudle_api.wlan import WlanManager
from SdmcUbusLib.libs.Wlan_moudle_api.guestnetwork import GuestNetworkManager
from SdmcUbusLib.libs.Wlan_moudle_api.mesh import EasyMeshManager
from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
# from SdmcUbusLib.libs.base_moudle_api import SdmcBasesLib
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcWlanLib(object):
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
            if name.startswith("Ubus_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)

    def _Ubus_wlan_init(self):

        ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.wlan_manager = WlanManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret


    def Ubus_Wlan_Set_2G(self, ssid, password, **kwargs):
        """
        功能描述：设置2.4G WiFi 参数

        参数： \n
        bandsteering:双频合一开关；默认0：关；可填：0：关；1：开；

        ssid: WIFI名称，默认：“Test_2G_01”;

        password: WIFI密码， 默认：“Sdmc@1234_2G”；

        channel: WIFI信道， 默认： auto；可填：auto，1，2，3......，11；

        bandwidth：带宽， 默认： 20/40MHz；可填：20MHz；40MHz；20/40MHz；

        wifi_mode: WiFi模式，默认：b,g,n,ax； 可填：b; b,g; b,g,n; b,g,n,ax; b,g,n,ax,be

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填： None； WPA2-Personal; WPA3-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开； 可填：True 对应 开； False 对应 关；

        max_connect_count: WiFi最大连接数量；默认：32；可填： 0-32；

        broadcast_ssid: 广播WiFi使能开关； 默认： 1 开启； 可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN使能开关； 默认： 1 开启； 可填：0 对应 关； 1 对应 开；

        TransmitPower：WiFi发射功率； 默认： 100； 可填；20，40，60，80，100；

        wait_time: 设置wifi等待时间；默认：90

        index: 指定设置第几组 5G SSID，默认 0 表示第一组

        Example:
        |  Ubus_Network_Wlan_Set_2G  | ssid=jjwwbb6688_2G | password=J@wb1234 | channel=1 | bandwidth=2 | wifi_mode=3 |
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        return wlan_manager.ubus_set_2g_wifi(ssid=ssid, password=password, **kwargs)

    def Ubus_Wlan_Set_5G(self, ssid, password, **kwargs):
        """
        功能描述：设置5G WiFi 参数

        参数： \n
        bandsteering:双频合一开关；默认0：关；可填：0：关；1：开；

        ssid: WIFI名称，默认：“Test_5G_01”;

        password: WIFI密码， 默认：“Sdmc@1234_5G”；

        channel: WIFI信道， 默认： auto；可填：auto...36..64..149...；

        bandwidth：带宽， 默认：160MHZ；可填：20MHz；40MHz；80MHz；160MHz

        wifi_mode: WiFi模式，默认：a,n,ac,ax； 可填： a; a,n;  a,n,ac; a,n,ac,ax;

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填：None；WPA2-Personal; WPA3-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开； 可填：True 对应 开； False 对应 关；

        max_connect_count: WiFi最大连接数量；默认：32；可填： 0-32；

        broadcast_ssid: 广播WiFi使能开关； 默认： 1 开启； 可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN使能开关； 默认： 1 开启； 可填：0 对应 关； 1 对应 开；

        TransmitPower：WiFi发射功率； 默认： 100； 可填；20，40，60，80，100；

        wait_time: 设置wifi等待时间；默认：90

        index: 指定设置第几组 5G SSID，默认 0 表示第一组

        Example:
        |  Ubus_Network_Wlan_Set_5G  | ssid=jjwwbb6688_5G | password=J@wb1234 | channel=1 | bandwidth=2 | wifi_mode=3 |
        """

        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        return wlan_manager.ubus_set_5g_wifi(ssid=ssid, password=password, **kwargs)

    def Ubus_Wlan_Set_BandSteering(self, bandsteering, ssid, password, **kwargs):
        """
        功能描述：\n
        设置双频合一参数

        入参：\n
        bandsteering:双频合一开关；默认0：关；可填：0：关；1：开；

        ssid: WIFI名称，默认：“Test_2G_01”;

        password: WIFI密码， 默认：“Sdmc@1234_2G”；

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填： None；WPA2-Personal; WPA2-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开； 可填：True 对应 开； False 对应 关；

        max_connect_count: WiFi最大连接数量；默认：32；可填： 0-32；

        broadcast_ssid: 广播WiFi使能开关； 默认： 1 开启； 可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN使能开关； 默认： 1 开启； 可填：0 对应 关； 1 对应 开；

        wait_time: 设置wifi等待时间；默认：90

        Example:
        |  Ubus_Network_Wlan_Set_BandSteering  | ssid=jjwwbb6688_5G | password=J@wb1234 |
        """

        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        return wlan_manager.ubus_set_bandsteering(bandsteering=bandsteering, ssid=ssid, password=password, **kwargs)

    def Ubus_Wlan_Set_Mlo_Enable(self,enable):
        """
        功能描述：
        设置 MLO（Multi-Link Operation）开关。
        在配置时会同时对 2.4G 和 5G 对应的 SSID 进行配置。

        入参：
        enable:
            True  -> 开启 MLO（MLDUnit = "0"）
            False -> 关闭 MLO（MLDUnit = "-1"）

        返回值：
        Ubus_Call 的返回结果。
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        return wlan_manager.set_mlo_enable(enable)

    def Ubus_Wlan_Set_Energy_Rule(self, enable, start_time, stop_time,
                                                     weekdays=None, description=""):
        """
        功能描述：设置 WiFi Energy Saving（WiFi 定时开关）规则

        参数： \n
        enable: 规则使能开关；
                默认：True；
                可填：True（开启规则）；False（关闭规则）；

        start_time: 规则开始时间；
                    格式："HH:MM"；
                    示例："00:00"；

        stop_time: 规则结束时间；
                   格式："HH:MM"；
                   示例："02:00"；

        weekdays: 生效星期；
                  默认：None（表示每天生效）；
                  可填：
                      None（每天）；
                      ["Monday","Tuesday"]（指定星期）；
                      "Monday,Tuesday"（字符串格式）；

                  可选值：
                      Monday, Tuesday, Wednesday,
                      Thursday, Friday, Saturday, Sunday；

        description: 规则描述；
                     默认：空字符串；
                     可填：任意字符串；

        返回值：
            ubus 调用返回结果

        Example:
        |  Ubus_WifienergysavingManager_Set_Energy_Rule  |
        |  enable=True  | start_time=00:00  | stop_time=02:00  |
        |  weekdays=["Monday","Tuesday"]  | description=robot test  |
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        instance = wlan_manager.add_energy_rule()
        return wlan_manager.set_energy_rule(instance, enable, start_time, stop_time, weekdays, description)

    def Ubus_Wlan_Del_Energy_Rule(self, instance):
        """
        功能描述：删除指定的 WiFi Energy Saving（WiFi 定时开关）规则

        参数： \n
        instance: 规则实例号；
                  必填；
                  示例：1、2、3...

        返回值：
            True  -> 删除成功
            False -> 删除失败

        对应 ubus 命令：
            ubus call bbfdm delete '{"path":"Device.WiFi.X_SDMC_WlanTimeoff.<instance>."}'

        Example:
        |  Ubus_WifienergysavingManager_Del_Energy_Rule  | instance=2 |
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        return wlan_manager.delete_energy_rule(instance)

    def Ubus_Wlan_Get_All_Bandsteering_info(self,index=0):
        """
        功能描述：\n
        获取Bandsteering 信息

        入参：
        index: 指定设置第几组 SSID，默认 0 表示第一组

        返回值：\n
        Bandsteering_info:Bandsteering的所有信息

        {'DualBandEnable': True, 'Merged_Config': {'Enable SSID': True, 'SSID': 'Test_5G_01', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@1234_5G'}}

        Example:
        | ${ret} |  Ubus_Network_Wlan_Set_BandSteering  |
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        BandSteering_info = wlan_manager.ubus_get_all_bandsteerding_info(index=index)
        return BandSteering_info

    def Ubus_Wlan_Get_All_2G_info(self,index=0):
        """
        功能描述：获取2G WiFi所有信息；

        返回值：
        字典：{'Enable SSID': True, 'SSID': 'SDMC_4D2028', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@123', 'AuthorizationModesSupported': 'None,WPA2-Personal,WPA3-Personal-Transition', 'ChannelEnabled': 'auto', 'Channel': 2, 'ChannelBandwidth': '20/40MHz', 'OperatingMode': 'b,g,n,ax', 'TransmitPower': 100, 'ChannelSupport': 'auto,1,2,3,4,5,6,7,8,9,10,11', 'ModeSupport': ['b', 'b,g', 'b,g,n', 'b,g,n,ax'], 'BandwidthSupport': '20/40MHz,20MHz,40MHz'}

        Example:
        |  ${ret}  | Ubus_Network_Wlan_Get_All_2G_info |
        """
        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        get_2g_info = wlan_manager.ubus_get_all_2g_info(index=index)
        return get_2g_info

    def Ubus_Wlan_Get_All_5G_info(self,index=0):
        """
        功能描述：获取5G WiFi所有信息；

        返回值：
        字典：{'Enable SSID': True, 'SSID': 'SDMC_4D2028_5G', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@123', 'AuthorizationModesSupported': 'None,WPA2-Personal,WPA3-Personal-Transition', 'ChannelEnabled': 'auto', 'Channel': 116, 'ChannelBandwidth': '160MHz', 'OperatingMode': 'a,n,ac,ax', 'TransmitPower': 100, 'ChannelSupport': 'auto,36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,149,153,157,161,165', 'ModeSupport': ['a', 'a,n', 'a,n,ac', 'a,n,ac,ax'], 'BandwidthSupport': '160MHz,20MHz,40MHz,80MHz'}

        Example:
        |  ${ret}  | Ubus_Network_Wlan_Get_All_5G_info |
        """

        self._Ubus_wlan_init()
        wlan_manager = self.wlan_manager
        get_5g_info = wlan_manager.ubus_get_all_5g_info()
        return get_5g_info

    def _Ubus_Network_GuestWlan_Init(self):
        n_ret = ERR_FAIL

        for nwf in [1]:

            try:

                parsed_url = urlparse(SdmcUbusLibBase.Url)
                ip = parsed_url.hostname

                username = SdmcUbusLibBase.Username
                password = SdmcUbusLibBase.Password

                self.guestwlan = GuestNetworkManager(ip, username, password)

                n_ret = ERR_SUCCESS

            except Exception as e:
                log.exception(str(e))

        return n_ret

    def Ubus_GuestWlan_Set_2g(self, ssid, password, **kwargs):
        """
        【功能描述】
        通过 ubus 设置 2G 访客网络 WiFi

        【入参】
         ssid: 2G SSID
         key: 2G 密码
         ratelimit: 2G 限速
         mode: 2G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable: 1表示开启，0表示关闭
         broadcast: 1表示开启，0表示关闭
         wait_time: 默认90，wifi重启等待时间

        【返回值】
        ERR_SUCCESS  : 执行成功
        ERR_FAIL : 执行失败 或 抛出异常

        【示例】
        Example:
        |  set_guest_wifi_2g  |  ssid=sdmc_2g  |  key=Sdmc@123  |
        """
        self._Ubus_Network_GuestWlan_Init()
        guestwlan_set = self.guestwlan.set_guest_wifi_2g(ssid=ssid, key=password, **kwargs)

        return guestwlan_set

    def Ubus_GuestWlan_Set_5g(self, ssid, password, **kwargs):
        """
        【功能描述】
        通过 ubus 设置 5G 访客网络 WiFi

        【入参】
         ssid: 5G SSID
         key: 5G 密码
         ratelimit: 5G 限速
         mode: 5G 认证模式 None/WPA2-Personal/WPA3-Personal-Transition
         enable: 1表示开启，0表示关闭
         broadcast: 1表示开启，0表示关闭
         wait_time: 默认90，wifi重启等待时间

        【返回值】
        ERR_SUCCESS  : 执行成功
        ERR_FAIL : 执行失败 或 抛出异常

        【示例】
        Example:
        |  set_guest_wifi_5g  |  ssid=sdmc_5g  |  key=Sdmc@123  |

        """
        self._Ubus_Network_GuestWlan_Init()
        guestwlan_set = self.guestwlan.set_guest_wifi_5g(ssid=ssid, key=password, **kwargs)

        return guestwlan_set

    def Ubus_GuestWlan_Get_info(self):
        """
        【功能描述】
        获取访客网络信息

        【返回值】
        访客网络信息
        {'guest_2g_ssid_Enable': True, 'guest_2g_ssid_SSID': 'Sdmc_guest_2g', 'guest_2g_ap_BroadcastSSID': True, 'guest_2g_ap_AuthorizationMode': 'WPA2-Personal', 'guest_2g_ap_WPAPreSharedKey': 'Sdmc@123', 'guest_2g_ap_Speedlimit': 0, 'guest_5g_ssid_Enable': True, 'guest_5g_ssid_SSID': 'Sdmc_guest_5g', 'guest_5g_ap_BroadcastSSID': False, 'guest_5g_ap_AuthorizationMode': 'WPA2-Personal', 'guest_5g_ap_WPAPreSharedKey': 'Sdmc@123', 'guest_5g_ap_Speedlimit': 0}

        """
        self._Ubus_Network_GuestWlan_Init()
        guestwlan_info = self.guestwlan.get_guest_wifi_info()

        return guestwlan_info

    def _Ubus_Mesh_Init(self):
        ret = ERR_FAIL
        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.mesh_manager = EasyMeshManager(ip,username,password)

            ret = ERR_SUCCESS
        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_Set_Easymesh_Mode(self, mode):
        """
        【功能描述】
        设置 EasyMesh 开关与角色

        【入参】
        mode:
            Disable - 关闭 EasyMesh
            Agent - 开启 EasyMesh 并设置角色为 Agent
            Controller - 开启 EasyMesh 并设置角色为 Controller

        【返回值】
        ERR_SUCCESS / ERR_FAIL

        """
        self._Ubus_Mesh_Init()
        easymesh_mode_set = self.mesh_manager.set_easymesh_mode(mode)

        return easymesh_mode_set

    def Ubus_Trigger_Mesh_Wps(self):
        """
        【功能描述】
        触发 EasyMesh WPS 按键组网


        【返回值】
        ERR_SUCCESS / ERR_FAIL

        """
        self._Ubus_Mesh_Init()
        wps_trigger = self.mesh_manager.trigger_mesh_wps()

        return wps_trigger

    def Ubus_Get_Mesh_Topology(self):
        """
        【功能描述】
        获取 EasyMesh 组网拓扑信息，构建结构：
        1. topology_map：拓扑结构（父→子:组网方式）
            {
                "parent_mac": {
                    "child_mac1": "wired",
                    "child_mac2": "wireless"
                },
                ...
            }
        2. device_map：MAC → IP
        3. sta_list：所有终端信息

        【返回数据】
        topo_dict = {
            "topology_map": {...},
            "device_map": {...},
            "sta_list": [...]
        }

        """
        self._Ubus_Mesh_Init()
        meshtopo_info = self.mesh_manager.get_mesh_topology()

        return meshtopo_info

    def Ubus_Get_Mesh_Status(self):
        """
        【功能描述】
        获取 EasyMesh 当前状态

        【返回数据】
            {
                "X_SDMC_MultiAP_Mode": mode
            }

        mode:
            0 -> Disable
            1 -> Agent--Enable
            2 -> Controller--Enable
            None -> 获取失败
        """
        self._Ubus_Mesh_Init()
        status = self.mesh_manager.get_mesh_status()

        return status

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

def debug_test():
    ubuslib = SdmcUbusLibBase()
    ubuslib.Ubus_Switch("https://192.168.1.1/ubus/")
    ubuslib.Ubus_Login("sdmc", "1234")

    wlanlib = SdmcWlanLib()
    # info=wlanlib.Ubus_Wlan_Set_2G(ssid="Test_2G_01", password="Sdmc@123",bandsteering="1,0,0,0,0")
    info = wlanlib.Ubus_Wlan_Get_All_2G_info()
    log.info("*"*100)
    log.info(info)




if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    # logging.getLogger().setLevel(logging.DEBUG)
    # logging.basicConfig(filename='example.log',level=logging.INFO)

    print("start ---------------------------\n")
    debug_test()
    print("\nfinish ------------------")
    # os.system("pause")



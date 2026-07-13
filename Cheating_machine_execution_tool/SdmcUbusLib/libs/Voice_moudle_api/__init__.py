"""
测试库 demo
"""

import inspect
from SdmcUbusLib.libs.Voice_moudle_api.voip import VoipManager
from urllib.parse import urlparse
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcLog import log
from SdmcCode import *

class SdmcVoiceLib(object):
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

    def _Ubus_voip_init(self):
        n_ret = ERR_FAIL

        try:

            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.voip = VoipManager(ip, username, password)

            n_ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return n_ret

    def Ubus_get_voip_info(self):
        """
        【功能描述】
        一次性获取所有 VoIP 相关信息（基础配置、服务器、账号、传真、媒体、语音服务），
        并将所有字段统一展开到同一级字典中返回。

        【返回值】
        dict : {'BindingInterface': '', 'SIPMode': 'SIP', 'DTMFSetting': 'RFC2833', 'ExpireTime': 3600, 'RegisterRetryInterval': 120, 'Server1_ServerIndex': 1, 'Server1_RegistrarServer': '', 'Server1_RegistrarServerPort': 5060, 'Server1_ProxyServer': '', 'Server1_ProxyServerPort': 5060, 'Server1_OutboundProxy': '', 'Server1_OutboundProxyPort': 5060, 'Server1_ExpireTime': 3600, 'Server1_RegisterRetryInterval': 120, 'Server2_ServerIndex': 2, 'Server2_RegistrarServer': '', 'Server2_RegistrarServerPort': 5060, 'Server2_ProxyServer': '', 'Server2_ProxyServerPort': 5060, 'Server2_OutboundProxy': '', 'Server2_OutboundProxyPort': 5060, 'Server2_ExpireTime': 3600, 'Server2_RegisterRetryInterval': 120, 'Account1_LineIndex': 1, 'Account1_SipAccountEnable': False, 'Account1_DisplayName': '', 'Account1_Account': '', 'Account1_Password': '', 'Account1_LineStatus': 'Error', 'Fax_T38Enable': False, 'Media1_LineIndex': 1, 'Media1_VADEnable': True, 'Media1_CodecList1_CodecIndex': 1, 'Media1_CodecList1_Enable': True, 'Media1_CodecList1_Codec': 'G.711 U-law', 'Media1_CodecList1_Priority': '1', 'Media1_CodecList2_CodecIndex': 2, 'Media1_CodecList2_Enable': True, 'Media1_CodecList2_Codec': 'G.711 A-law', 'Media1_CodecList2_Priority': '2', 'Media1_CodecList3_CodecIndex': 3, 'Media1_CodecList3_Enable': True, 'Media1_CodecList3_Codec': 'G.729', 'Media1_CodecList3_Priority': '3', 'Media1_CodecList4_CodecIndex': 4, 'Media1_CodecList4_Enable': True, 'Media1_CodecList4_Codec': 'G.722', 'Media1_CodecList4_Priority': '4', 'Media1_CodecList5_CodecIndex': 5, 'Media1_CodecList5_Enable': True, 'Media1_CodecList5_Codec': 'G.723', 'Media1_CodecList5_Priority': '0', 'Media1_CodecList6_CodecIndex': 6, 'Media1_CodecList6_Enable': True, 'Media1_CodecList6_Codec': 'G.726 - 16', 'Media1_CodecList6_Priority': '0', 'Media1_CodecList7_CodecIndex': 7, 'Media1_CodecList7_Enable': True, 'Media1_CodecList7_Codec': 'G.726 - 24', 'Media1_CodecList7_Priority': '0', 'Media1_CodecList8_CodecIndex': 8, 'Media1_CodecList8_Enable': True, 'Media1_CodecList8_Codec': 'G.726 - 32', 'Media1_CodecList8_Priority': '0', 'Media1_CodecList9_CodecIndex': 9, 'Media1_CodecList9_Enable': True, 'Media1_CodecList9_Codec': 'G.726 - 40', 'Media1_CodecList9_Priority': '0', 'Media1_SendGain': 0, 'Media1_ReceiveGain': 0, 'Media1_CallFeatureSetting1_LineIndex': 1, 'Media1_CallFeatureSetting1_CallTransferEnable': False, 'Media1_CallFeatureSetting1_CallWaitingEnable': False, 'Media1_CallFeatureSetting1_CallForwardUnconditionalEnable': False, 'Media1_CallFeatureSetting1_CallForwardOnBusyEnable': False, 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerEnable': False, 'Media1_CallFeatureSetting1_CallForwardUnconditionalNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnBusyNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerRingTimeout': 60, 'Media1_CallFeatureSetting1_WarmlineEnable': False, 'Media1_CallFeatureSetting1_WarmLineNumber': '', 'Media1_CallFeatureSetting1_WarmLineTimeout': 5, 'VoiceService_DigitMap': 'x.'}


        【示例】
        |  ${ret}  |  Ubus_get_voip_info  |
        """

        self._Ubus_voip_init()
        info = self.voip.get_all_voip_info()
        return info

    def Ubus_set_voip_digmap(self, digit_map):
        """
        【功能描述】
            设置 VoIP DigitMap 配uration

        【入参】
            param digit_map: str - DigitMap 值值，例如 "x."

        【返回值】
            UBUS 调调用结果

        【示例】
        Example:
        |  Ubus_set_voip_digmap  | x.  |

        """
        self._Ubus_voip_init()
        ret = self.voip.set_voip_digmap(digit_map)
        return ret

    def Ubus_set_voip_codec(self, line_index="1", codec1="G.711 U-law", codec2="G.711 A-law", codec3="G.729", codec4="G.722", codec5="G.723"):
        """
        【功能描述】
            设置 VoIP 编解码器配置

        【入参】
            param line_index: str - 线路索引，对应 Device.Services.VoiceService.1.SIP中的1
            param codec1: str - 编解码器1，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec2: str - 编解码器2，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec3: str - 编解码器3，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec4: str - 编解码器4，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec5: str - 编解码器5，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40

        【返回值】
            UBUS 调调用结果

        【示例】
        Example:
        |  Ubus_set_voip_codec  | 1 | G.711 U-law | G.711 A-law | G.729 | G.722 | G.723  |

        """
        self._Ubus_voip_init()
        ret = self.voip.set_voip_codec(line_index, codec1, codec2, codec3, codec4, codec5)
        return ret

    def Ubus_set_voip_register_server(self, server_index="1", proxy_server="172.33.5.251", proxy_server_port="5060",
                                     outbound_proxy="172.33.5.251", outbound_proxy_port="5060",
                                     registrar_server="172.33.5.251", registrar_server_port="5060"):
        """
        【功能描述】
            设置 VoIP 注册服务器配置
        
        【入参】
            param server_index: str - 网络索引，对应 Device.Services.VoiceService.1.SIP.Network.1.中1
            param proxy_server: str - 代理服务器地址，默认"172.33.5.251"
            param proxy_server_port: str - 代理服务器端口，默认"5060"
            param outbound_proxy: str - 出bound代理地址，默认"172.33.5.251"
            param outbound_proxy_port: str - 出bound代理端口，默认"5060"
            param registrar_server: str - 注册服务器地址，默认"172.33.5.251"
            param registrar_server_port: str - 注册服务器端口，默认"5060"
        
        【返回值】
            UBUS 调调用结果
        
        【示例】
        Example:
        |  Ubus_set_voip_register_server  | 1 | 172.33.5.251 | 5060 | 172.33.5.251 | 5060 | 172.33.5.251 | 5060  |
        
        """
        self._Ubus_voip_init()
        ret = self.voip.set_voip_register_server(server_index, proxy_server, proxy_server_port,
                                                 outbound_proxy, outbound_proxy_port,
                                                 registrar_server, registrar_server_port)
        return ret

    def Ubus_set_voip_account(self, line_index="1", enable="0", display_name="", auth_user_name="", auth_password=""):
        """
        【功能描述】
            设置 VoIP 账户配置
        
        【入参】
            param line_index: str - 线路索引，对应 Device.Services.VoiceService.1.SIP.Client.1.中Client后面1
            param enable: str - 启状态，填写"1"或"0"
            param display_name: str - 显示名称
            param auth_user_name: str - 认用户名
            param auth_password: str - 认密码
        
        【返回值】
            UBUS 调调用结果
        
        【示例】
        Example:
        |  Ubus_set_voip_account  | 1 | Enable | VoIP Line 1 | test_user | test_password  |
        
        """
        self._Ubus_voip_init()
        ret = self.voip.set_voip_account(line_index, enable, display_name, auth_user_name, auth_password)
        return ret

    def Ubus_set_voip_base(self, dtmf_method="RFC2833", proxy_server_port="5060", register_expires="3600", sip_mode="SIP"):
        """
        【功能描述】
            设置 VoIP 基�配置
        
        【入参】
            param dtmf_method: str - DTMF方法，默认"RFC2833"
            param proxy_server_port: str - 代理服务器端口，默认"5060"
            param register_expires: str - 注册过期时间，默认"3600"
            param sip_mode: str - SIP模式，默认"SIP"
        
        【返回值】
            UBUS 调调用结果
        
        【示例】
        Example:
        |  Ubus_set_voip_base  | RFC2833 | 5060 | 3600 | SIP  |
        
        """
        self._Ubus_voip_init()
        ret = self.voip.set_voip_base(dtmf_method, proxy_server_port, register_expires, sip_mode)
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
    sdmc_voip_lib = SdmcVoiceLib()

    base = SdmcUbusLibBase()
    base.Ubus_Login("root", "t*hEQ#BHu7z%3n")
    sdmc_voip_lib.Ubus_set_voip_codec()
    print("\nfinish ------------------")
    # os.system("pause")



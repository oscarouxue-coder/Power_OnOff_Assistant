import json
from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class VoipManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_sip_json(self):
        """
        【功能描述】
        获取 SIP 节点的原始配置信息（TR-181 模型路径：Device.Services.VoiceService.1.SIP）。
        主要包含 SIP 网络配置、注册服务器、代理服务器等参数。

        【入参】
        无

        【返回值】
        dict : 返回 SIP 节点的完整 JSON 数据。
            常见字段：
            {
                "Network": [...],                     # SIP 网络配置列表
                "X_SDMC_BoundInterfaceList": "...",   # 绑定接口
                "X_SDMC_SIPMode": "...",              # SIP 模式
                ...
            }

        异常：
            - 调用 ubus 接口失败时抛出异常。

        【示例】
        Example:
        |  Get Sip Json  |
        返回结果：
        {
            "Network": [
                {
                    "X_SDMC_Instance": 1,
                    "RegistrarServer": "sip.example.com",
                    "RegistrarServerPort": 5060,
                    ...
                }
            ]
        }
        """
        params = {
            "path": "Device.Services.VoiceService.1.SIP.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        return data

    def get_voipprofile_json(self):
        """
        【功能描述】
        获取 VoIPProfile 节点的原始配置信息（TR-181 模型路径：Device.Services.VoiceService.1.VoIPProfile.1）。
        主要包含 DTMF 设置、编解码器、VoIP 特性配置等参数。

        【入参】
        无

        【返回值】
        dict : 返回 VoIPProfile 节点的完整 JSON 数据。
            常见字段：
            {
                "DTMFMethod": "RFC2833",   # DTMF 配置
                "Codec": [...],           # 编解码器配置
                ...
            }

        异常：
            - 调用 ubus 接口失败时抛出异常。

        【示例】
        Example:
        |  Get VoipProfile Json  |
        返回结果：
        {
            "VoIPProfile": [
                {
                    "DTMFMethod": "RFC2833",
                    "Codec": [...]
                }
            ]
        }
        """
        params = {
            "path": "Device.Services.VoiceService.1.VoIPProfile.1.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        return data

    def get_terminal_json(self):
        params = {
            "path": "Device.Services.VoiceService.1.Terminal.*.Audio.1.VoiceProcessing.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]

        return data

    def get_callcontol_json(self):
        """
        【功能描述】
        获取 VoiceService 下 CallControl → CallingFeatures → Set 节点的配置信息。
        该节点通常用于存储呼叫特性设置，例如呼叫转移、呼叫等待等。

        【入参】
        无

        【返回值】
        | 返回值类型 | 说明                                               |
        | ---------- | -------------------------------------------------- |
        | dict       | 返回包含 CallingFeatures.Set 配置信息的字典结构。 |

        【异常】
        Exception : 当调用 ubus 接口失败，或返回结果结构异常时抛出。

        【示例】
        Example (Robot Framework):
        |  Get Callcontol Json  |
        |  ${callcontrol}=      |  Get Callcontol Json  |
        |  Log To Console       |  ${callcontrol}       |
        """
        params = {
            "path": "Device.Services.VoiceService.1.CallControl.CallingFeatures.Set.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        return data

    def get_interwork_json(self):
        """
        【功能描述】
        获取 VoiceService 下 Interwork → Map 节点的配置信息。
        Interwork.Map 节点通常用于存放 DigitMap（号码映射规则），用于定义拨号计划。

        【入参】
        无

        【返回值】
        | 返回值类型 | 说明                                    |
        | ---------- | --------------------------------------- |
        | dict       | 返回包含 Interwork.Map 配置信息的字典。 |

        【异常】
        Exception : 当调用 ubus 接口失败，或返回结果结构异常时抛出。

        【示例】
        Example (Robot Framework):
        |  Get Interwork Json  |
        |  ${interwork}=       |  Get Interwork Json  |
        |  Log To Console      |  ${interwork}        |
        """
        params = {
            "path": "Device.Services.VoiceService.1.Interwork.1.Map.",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        return data

    def get_voip_base_setting_info(self):
        """
        【功能描述】
        获取 VoIP 基础配置信息，包括绑定接口、SIP 模式、DTMF 设置、注册有效期及注册重试间隔。
        用于提取 VoIP/SIP 相关的核心参数，供后续业务逻辑或测试验证使用。

        【入参】
        无

        【返回值】
        dict : 返回包含基础配置的字典，字段说明如下
            {
                "BindingInterface"       : 绑定的网络接口（str 或 None）
                "SIPMode"                : SIP 工作模式，例如 UDP/TCP/TLS（str 或 None）
                "DTMFSetting"            : DTMF 信令传输方式，例如 RFC2833/InBand/SIPINFO（str 或 None）
                "ExpireTime"             : 注册有效期，单位秒（int 或 None）
                "RegisterRetryInterval"  : 注册失败后的重试间隔，单位秒（int 或 None）
            }

        异常：
            - 调用过程出现异常时，抛出原始异常信息。

        【示例】
        Example:
        |  Get Voip Base Setting Info  |
        返回结果：
        {
            "BindingInterface": "eth0",
            "SIPMode": "UDP",
            "DTMFSetting": "RFC2833",
            "ExpireTime": 3600,
            "RegisterRetryInterval": 120
        }
        """

        base_setting = {}
        try:
            sip_info = self.get_sip_json().get('SIP', {})
            voip_profile = self.get_voipprofile_json().get('VoIPProfile', [{}])[0]
            sip_network = sip_info.get('Network', [{}])

            base_setting = {
                "BindingInterface": sip_info.get(f'{VENDOR_PREFIX}BoundInterfaceList'),
                "SIPMode": sip_info.get(f'{VENDOR_PREFIX}SIPMode'),
                "DTMFSetting": voip_profile.get('DTMFMethod'),
                "ExpireTime": sip_network[0].get('RegisterExpires'),
                "RegisterRetryInterval": sip_network[0].get('RegisterRetryInterval')
            }

            return base_setting
        except Exception as e:
            raise

    def get_voip_register_server_info(self):
        """
        【功能描述】
        获取 VoIP 注册服务器相关配置信息，包括 Registrar、Proxy、OutboundProxy 等服务器信息，
        并返回服务器的索引、地址、端口、注册时间等参数。

        【入参】
        无

        【返回值】
        list : 包含多个服务器信息的列表，每个元素为一个 dict，字段包括：
            - ServerIndex (str/int)              : 服务器索引（由厂商自定义字段标识实例）
            - RegistrarServer (str)              : 注册服务器地址
            - RegistrarServerPort (int/str)      : 注册服务器端口
            - ProxyServer (str)                   : 代理服务器地址
            - ProxyServerPort (int/str)          : 代理服务器端口
            - OutboundProxy (str)                 : 出口代理服务器地址
            - OutboundProxyPort (int/str)        : 出口代理服务器端口
            - ExpireTime (int/str)               : 注册过期时间（秒）
            - RegisterRetryInterval (int/str)    : 注册失败后的重试间隔（秒）

        【示例】
        Example:
        |  Get Voip Register Server Info  |
        返回结果:
        [
            {
                "ServerIndex": 1,
                "RegistrarServer": "sip.example.com",
                "RegistrarServerPort": 5060,
                "ProxyServer": "proxy.example.com",
                "ProxyServerPort": 5060,
                "OutboundProxy": "outbound.example.com",
                "OutboundProxyPort": 5060,
                "ExpireTime": 3600,
                "RegisterRetryInterval": 30
            }
        ]
        """
        server_list = []
        try:
            sip_info = self.get_sip_json().get('SIP')
            sip_network = sip_info.get('Network')
            for net in sip_network:
                server_list.append({
                    "ServerIndex": net.get(f'{VENDOR_PREFIX}Instance'),
                    "RegistrarServer": net.get('RegistrarServer'),
                    "RegistrarServerPort": net.get('RegistrarServerPort'),
                    "ProxyServer": net.get('ProxyServer'),
                    "ProxyServerPort": net.get('ProxyServerPort'),
                    "OutboundProxy": net.get('OutboundProxy'),
                    "OutboundProxyPort": net.get('OutboundProxyPort'),
                    "ExpireTime": net.get('RegisterExpires'),
                    "RegisterRetryInterval": net.get('RegisterRetryInterval'),
                })

            return server_list
        except Exception as e:
            raise

    def get_sip_account_setting_info(self):
        """
        【功能描述】
        获取 SIP 账号的配置信息，包括账号使能状态、显示名称、用户名、密码及线路状态。
        可用于测试或管理 SIP 账号信息。

        【入参】
        无

        【返回值】
        list : 包含多个 SIP 账号信息的列表，每个元素为一个 dict，字段包括：
            - LineIndex (str/int)       : 线路索引
            - SipAccountEnable (bool)   : SIP 账号是否启用
            - DisplayName (str)         : SIP 注册显示名称（RegisterURI）
            - Account (str)             : SIP 用户名（AuthUserName）
            - Password (str)            : SIP 密码（AuthPassword）
            - LineStatus (str)          : 线路状态，例如：Registered、Initializing 等

        【示例】
        Example:
        |  Get Sip Account Setting Info  |
        返回结果:
        [
            {
                "LineIndex": 1,
                "SipAccountEnable": True,
                "DisplayName": "1001@sip.example.com",
                "Account": "1001",
                "Password": "pass123",
                "LineStatus": "Registered"
            },
            {
                "LineIndex": 2,
                "SipAccountEnable": False,
                "DisplayName": "1002@sip.example.com",
                "Account": "1002",
                "Password": "pass456",
                "LineStatus": "Unregistered"
            }
        ]
        """
        sip_account_setting = []
        try:
            sip_info = self.get_sip_json().get('SIP')
            sip_client = sip_info.get('Client')
            for client in sip_client:
                sip_account_setting.append({
                    "LineIndex": client.get(f'{VENDOR_PREFIX}Instance'),
                    "SipAccountEnable": client.get('Enable'),
                    "DisplayName": client.get('RegisterURI'),
                    "Account": client.get('AuthUserName'),
                    "Password": client.get('AuthPassword'),
                    "LineStatus": client.get('Status'),
                })

            return sip_account_setting
        except Exception as e:
            raise

    def get_fax_setting_info(self):
        try:
            sip_info = self.get_sip_json().get('SIP')
            sip_client = sip_info.get('Client')[0]
            T38Enable = sip_client.get('T38Enable')

            return T38Enable

        except Exception as e:
            raise

    def get_media_setting_info(self):
        """
        【功能描述】
        获取 VoIP 媒体相关配置，包括 VAD、Codec 列表、音频增益以及呼叫特性设置。

        【返回值】
        list : 每个元素为一个 dict，包含以下字段：
            - LineIndex (int)       : 线路索引
            - VADEnable (bool)      : 是否启用 VAD
            - CodecList (list)      : 编解码器配置列表
            - SendGain (int/float)  : 发送增益
            - ReceiveGain (int/float): 接收增益
            - CallFeatureSetting (list[dict]): 呼叫特性设置

        """
        media_setting = []
        try:
            sip_info = self.get_sip_json().get('SIP', {})
            sip_client = sip_info.get('Client', [])
            terminal = self.get_terminal_json().get('Terminal', [])
            callcontrol = self.get_callcontol_json().get('Set', [])

            # 取终端的语音增益配置
            SendGain = None
            ReceiveGain = None
            if terminal and terminal[0].get('Audio'):
                vp = terminal[0].get('Audio')[0].get('VoiceProcessing', {})
                SendGain = vp.get('TransmitGain')
                ReceiveGain = vp.get('ReceiveGain')

            # 取呼叫功能配置
            call_feature_setting = []
            for callinfo in callcontrol:
                call_feature_setting.append({
                    "LineIndex": callinfo.get(f'{VENDOR_PREFIX}Instance'),
                    "CallTransferEnable": callinfo.get('CallTransferEnable'),
                    "CallWaitingEnable": callinfo.get('CallWaitingEnable'),
                    "CallForwardUnconditionalEnable": callinfo.get('CallForwardUnconditionalEnable'),
                    "CallForwardOnBusyEnable": callinfo.get('CallForwardOnBusyEnable'),
                    "CallForwardOnNoAnswerEnable": callinfo.get('CallForwardOnNoAnswerEnable'),
                    "CallForwardUnconditionalNumber": callinfo.get('CallForwardUnconditionalNumber'),
                    "CallForwardOnBusyNumber": callinfo.get('CallForwardOnBusyNumber'),
                    "CallForwardOnNoAnswerNumber": callinfo.get('CallForwardOnNoAnswerNumber'),
                    "CallForwardOnNoAnswerRingTimeout": callinfo.get('CallForwardOnNoAnswerRingTimeout'),
                    "WarmlineEnable": callinfo.get(f'{VENDOR_PREFIX}WarmlineEnable'),
                    "WarmLineNumber": callinfo.get(f'{VENDOR_PREFIX}WarmLineNumber'),
                    "WarmLineTimeout": callinfo.get(f'{VENDOR_PREFIX}WarmLineTimeOut')
                })

            # 拼接 SIP Client 配置
            for client in sip_client:
                codec_list = []
                for codec in client.get(f'{VENDOR_PREFIX}Codec', []):
                    codec_list.append({
                        "CodecIndex": codec.get(f'{VENDOR_PREFIX}Instance'),
                        "Enable": codec.get('Enable'),
                        "Codec": codec.get('Codec'),
                        "Priority": codec.get('Priority')
                    })

                media_setting.append({
                    "LineIndex": client.get(f'{VENDOR_PREFIX}Instance'),
                    "VADEnable": client.get(f'{VENDOR_PREFIX}VADEnable'),
                    "CodecList": codec_list,
                    "SendGain": SendGain,
                    "ReceiveGain": ReceiveGain,
                    "CallFeatureSetting": call_feature_setting
                })

            return media_setting
        except Exception as e:
            raise

    def get_voice_service_info(self):
        """
        【功能描述】
        获取 VoiceService 中的 DigitMap 配置信息。
        DigitMap 用于定义拨号规则和号码映射逻辑，是语音业务中的重要参数。

        【入参】
        无

        【返回值】
        | 返回值类型 | 说明                           |
        | ---------- | ------------------------------ |
        | str / None | 返回 DigitMap 字符串；若异常则返回 None 或抛出异常 |

        【异常】
        Exception : 当调用 get_interwork_json() 失败，或数据结构异常时抛出。

        【示例】
        Example (Robot Framework):
        |  Get Voice Service Info  |
        |  ${digit_map}=           |  Get Voice Service Info  |
        |  Log To Console          |  DigitMap: ${digit_map}  |

        """
        try:
            interwork = self.get_interwork_json().get('Map')[0]
            DigitMap = interwork.get('DigitMap')

            return DigitMap

        except Exception as e:
            raise

    def get_all_voip_info(self):
        """
        【功能描述】
        一次性获取所有 VoIP 相关信息（基础配置、服务器、账号、传真、媒体、语音服务），
        并将所有字段统一展开到同一级字典中返回。

        【返回值】
        dict : {'BindingInterface': '', 'SIPMode': 'SIP', 'DTMFSetting': 'RFC2833', 'ExpireTime': 3600, 'RegisterRetryInterval': 120, 'Server1_ServerIndex': 1, 'Server1_RegistrarServer': '', 'Server1_RegistrarServerPort': 5060, 'Server1_ProxyServer': '', 'Server1_ProxyServerPort': 5060, 'Server1_OutboundProxy': '', 'Server1_OutboundProxyPort': 5060, 'Server1_ExpireTime': 3600, 'Server1_RegisterRetryInterval': 120, 'Server2_ServerIndex': 2, 'Server2_RegistrarServer': '', 'Server2_RegistrarServerPort': 5060, 'Server2_ProxyServer': '', 'Server2_ProxyServerPort': 5060, 'Server2_OutboundProxy': '', 'Server2_OutboundProxyPort': 5060, 'Server2_ExpireTime': 3600, 'Server2_RegisterRetryInterval': 120, 'Account1_LineIndex': 1, 'Account1_SipAccountEnable': False, 'Account1_DisplayName': '', 'Account1_Account': '', 'Account1_Password': '', 'Account1_LineStatus': 'Error', 'Fax_T38Enable': False, 'Media1_LineIndex': 1, 'Media1_VADEnable': True, 'Media1_CodecList1_CodecIndex': 1, 'Media1_CodecList1_Enable': True, 'Media1_CodecList1_Codec': 'G.711 U-law', 'Media1_CodecList1_Priority': '1', 'Media1_CodecList2_CodecIndex': 2, 'Media1_CodecList2_Enable': True, 'Media1_CodecList2_Codec': 'G.711 A-law', 'Media1_CodecList2_Priority': '2', 'Media1_CodecList3_CodecIndex': 3, 'Media1_CodecList3_Enable': True, 'Media1_CodecList3_Codec': 'G.729', 'Media1_CodecList3_Priority': '3', 'Media1_CodecList4_CodecIndex': 4, 'Media1_CodecList4_Enable': True, 'Media1_CodecList4_Codec': 'G.722', 'Media1_CodecList4_Priority': '4', 'Media1_CodecList5_CodecIndex': 5, 'Media1_CodecList5_Enable': True, 'Media1_CodecList5_Codec': 'G.723', 'Media1_CodecList5_Priority': '0', 'Media1_CodecList6_CodecIndex': 6, 'Media1_CodecList6_Enable': True, 'Media1_CodecList6_Codec': 'G.726 - 16', 'Media1_CodecList6_Priority': '0', 'Media1_CodecList7_CodecIndex': 7, 'Media1_CodecList7_Enable': True, 'Media1_CodecList7_Codec': 'G.726 - 24', 'Media1_CodecList7_Priority': '0', 'Media1_CodecList8_CodecIndex': 8, 'Media1_CodecList8_Enable': True, 'Media1_CodecList8_Codec': 'G.726 - 32', 'Media1_CodecList8_Priority': '0', 'Media1_CodecList9_CodecIndex': 9, 'Media1_CodecList9_Enable': True, 'Media1_CodecList9_Codec': 'G.726 - 40', 'Media1_CodecList9_Priority': '0', 'Media1_SendGain': 0, 'Media1_ReceiveGain': 0, 'Media1_CallFeatureSetting1_LineIndex': 1, 'Media1_CallFeatureSetting1_CallTransferEnable': False, 'Media1_CallFeatureSetting1_CallWaitingEnable': False, 'Media1_CallFeatureSetting1_CallForwardUnconditionalEnable': False, 'Media1_CallFeatureSetting1_CallForwardOnBusyEnable': False, 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerEnable': False, 'Media1_CallFeatureSetting1_CallForwardUnconditionalNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnBusyNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerNumber': '', 'Media1_CallFeatureSetting1_CallForwardOnNoAnswerRingTimeout': 60, 'Media1_CallFeatureSetting1_WarmlineEnable': False, 'Media1_CallFeatureSetting1_WarmLineNumber': '', 'Media1_CallFeatureSetting1_WarmLineTimeout': 5, 'VoiceService_DigitMap': 'x.'}


        【异常】
        调用过程出现异常时，抛出异常。
        """
        try:
            result = {}

            # --- 1. 基础信息 ---
            base = self.get_voip_base_setting_info()
            result.update(base)

            # --- 2. 注册服务器信息 ---
            servers = self.get_voip_register_server_info()
            for idx, s in enumerate(servers, 1):
                for k, v in s.items():
                    result[f"Server{idx}_{k}"] = v

            # --- 3. SIP 账号信息 ---
            accounts = self.get_sip_account_setting_info()
            for idx, a in enumerate(accounts, 1):
                for k, v in a.items():
                    result[f"Account{idx}_{k}"] = v

            # --- 4. 传真配置 ---
            fax = self.get_fax_setting_info()
            result["Fax_T38Enable"] = fax

            # --- 5. 媒体配置 ---
            medias = self.get_media_setting_info()
            for idx, m in enumerate(medias, 1):
                for k, v in m.items():
                    if isinstance(v, list):  # 展开嵌套 codec/call feature
                        for sub_idx, sub in enumerate(v, 1):
                            for sk, sv in sub.items():
                                result[f"Media{idx}_{k}{sub_idx}_{sk}"] = sv
                    else:
                        result[f"Media{idx}_{k}"] = v

            # --- 6. VoiceService DigitMap ---
            result["VoiceService_DigitMap"] = self.get_voice_service_info()

            return result

        except Exception as e:
            raise Exception(f"获取 VoIP 全量信息失败: {e}")

    def debug_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)
            data = self.get_all_voip_info()
            info = json.dumps(data, indent=4, ensure_ascii=False)
            # print("json is "+ str(data))
            print(info)
        except Exception as e:
            log.info("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)


        except Exception as e:
            print("uint test failed: ", str(e))


    def set_voip_digmap(self, digit_map):
        """
        【功能描述】
            设置 VoIP DigitMap 配uration
        【入参】
            param digit_map: str - DigitMap 值值，例如 "x."
        【返回值】
            UBUS 调调用结果
        【示例】
        Example:
        |  Set VoIP DigitMap  | x.  |
        """
        try:
            params = {
                "path": f"Device.Services.VoiceService.1.Interwork.1.Map.1.",
                "obj_path": {"DigitMap": digit_map},
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            return result
        except Exception as e:
            log.exception(f"set_voip_digmap failed: {str(e)}")
            raise

    def set_voip_codec(self, line_index="1", codec1="G.711 U-law", codec2="G.711 A-law", codec3="G.729", codec4="G.722", codec5="G.723"):
        """
        【功能描述】
            设置 VoIP 编解码器配置
        【入参】
            param line_index: int - 线路索引，对应 Device.Services.VoiceService.1.SIP中1
            param codec1: str - 编解码器1，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec2: str - 编解码器2，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec3: str - 编解码器3，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec4: str - 编解码器4，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
            param codec5: str - 编解码器5，可填写为G.711 U-law,G.711 A-law,G.729,G.722,G.723,G.726 - 16,G.726 - 24,G.726 - 32,G.726 - 40
        【返回值】
            UBUS 调调用结果
        【示例】
        Example:
        |  Set VoIP Codec  | 1 | G.711 U-law | G.711 A-law | G.729 | G.722 | G.723  |
        """
        try:
            # 构编解码器配置路径
            paths = [
                {
                    "addr": f"Device.Services.VoiceService.{line_index}.SIP.Client.1.{VENDOR_PREFIX}Codec.1.Codec",
                    "value": codec1
                },
                {
                    "addr": f"Device.Services.VoiceService.{line_index}.SIP.Client.1.{VENDOR_PREFIX}Codec.2.Codec",
                    "value": codec2
                },
                {
                    "addr": f"Device.Services.VoiceService.{line_index}.SIP.Client.1.{VENDOR_PREFIX}Codec.3.Codec",
                    "value": codec3
                },
                {
                    "addr": f"Device.Services.VoiceService.{line_index}.SIP.Client.1.{VENDOR_PREFIX}Codec.4.Codec",
                    "value": codec4
                },
                {
                    "addr": f"Device.Services.VoiceService.{line_index}.SIP.Client.1.{VENDOR_PREFIX}Codec.5.Codec",
                    "value": codec5
                }
            ]
            
            params = {
                "paths": paths,
                "optional": {"proto": "web"}
            }
            
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            return result
        except Exception as e:
            log.exception(f"set_voip_codec failed: {str(e)}")
            raise

    def set_voip_register_server(self, server_index="1", proxy_server="172.33.5.251", proxy_server_port="5060",
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
        |  Set VoIP Register Server  | 1 | 172.33.5.251 | 5060 | 172.33.5.251 | 5060 | 172.33.5.251 | 5060  |
        """
        try:
            # 在函数内部进行类型转换
            params = {
                "path": f"Device.Services.VoiceService.1.SIP.Network.{server_index}.",
                "obj_path": {
                    "ProxyServer": proxy_server,
                    "ProxyServerPort": int(proxy_server_port),
                    "OutboundProxy": outbound_proxy,
                    "OutboundProxyPort": int(outbound_proxy_port),
                    "RegistrarServer": registrar_server,
                    "RegistrarServerPort": int(registrar_server_port)
                },
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            return result
        except Exception as e:
            log.exception(f"set_voip_register_server failed: {str(e)}")
            raise

    def set_voip_account(self, line_index="1", enable="0", display_name="", auth_user_name="", auth_password=""):
        """
        【功能描述】
            设置 VoIP 账户配置
        
        【入参】
            param line_index: str - 线路索引，对应 Device.Services.VoiceService.1.SIP.Client.1.中1
            param enable: str - 启状态，例如 "1" 启，"0" 禁
            param display_name: str - 显示名称，例如 "VoIP Line 1"
            param auth_user_name: str - 认件用户名，例如 "111"
            param auth_password: str - 认件密码，例如 "111"
        
        【返回值】
            UBUS 调用结果
        
        【示例】
        Example:
        |  Set VoIP Account  | 1 | 0 | VoIP Line 1 | 111 | 111  |
        """
        try:
            params = {
                "path": f"Device.Services.VoiceService.1.SIP.Client.{line_index}.",
                "obj_path": {
                    "Enable": enable,
                    "AuthUserName": auth_user_name,
                    f"{VENDOR_PREFIX}AuthPassword": auth_password,
                    "RegisterURI": display_name
                },
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)
            return result
        except Exception as e:
            log.exception(f"set_voip_account failed: {str(e)}")
            raise
        
    def set_voip_base(self, dtmf_method="RFC2833", proxy_server_port="5060", register_expires="3600", sip_mode="SIP"):
        """
        【功能描述】
            设置 VoIP 基础配置
        
        【入参】
            param dtmf_method: str - DTMF方法，默认"RFC2833"
            param proxy_server_port: str - 代理服务器端口，默认"5060"
            param register_expires: str - 注册过期时间，默认"3600"
            param sip_mode: str - SIP模式，默认"SIP"
        
        【返回值】
            UBUS 调调用结果
        
        【示例】
        Example:
        |  Set VoIP Base  | RFC2833 | 5060 | 3600 | SIP  |
        """
        try:
            # 设置VoIPProfile的DTMF方法
            params1 = {
                "path": "Device.Services.VoiceService.1.VoIPProfile.1.",
                "obj_path": {
                    "DTMFMethod": dtmf_method
                },
                "optional": {"proto": "web"}
            }
            
            # 设置SIP网络配置
            params2 = {
                "path": "Device.Services.VoiceService.1.SIP.Network.1.",
                "obj_path": {
                    "ProxyServerPort": int(proxy_server_port),
                    "RegisterExpires": int(register_expires)
                },
                "optional": {"proto": "web"}
            }
            
            # 设置SIP基本配置
            params3 = {
                "path": "Device.Services.VoiceService.1.SIP.",
                "obj_path": {
                    f"{VENDOR_PREFIX}SIPMode": sip_mode
                },
                "optional": {"proto": "web"}
            }
            
            # 执行三个UBUS调用
            result1 = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params1)
            result2 = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params2)
            result3 = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params3)
            
            # 返回所有结果
            return {
                "dtmf_method_result": result1,
                "network_config_result": result2,
                "sip_config_result": result3
            }
        except Exception as e:
            log.exception(f"set_voip_base failed: {str(e)}")
            raise


if __name__ == '__main__':
    voip = VoipManager(ip="192.168.29.1", username="root", password="t*hEQ#BHu7z%3n")
    voip.debug_test()

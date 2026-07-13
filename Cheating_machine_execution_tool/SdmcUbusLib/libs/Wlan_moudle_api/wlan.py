import json
import time

from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class WlanManager:

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def get_bansteering_value(self):
        """
        功能描述：
        获取双频合一信息

        返回值：
        0：双频合一关闭； 1：双频合一开启
        """
        params = {
            "path": f"Device.WiFi.{VENDOR_PREFIX}DualBandEnable",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        bansteering = data.get(f'{VENDOR_PREFIX}DualBandEnable', {})

        return bansteering

    def get_mapping2g_info(self):
        """
        功能描述：获取2.4G wifi映射信息，并将列表下标替换为真实的X_SDMC_Instance
        """
        params = {
            "path": f"Device.WiFi.{VENDOR_PREFIX}Mapping_2G",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        original_mapping = data.get(f'{VENDOR_PREFIX}Mapping_2G')

        if not original_mapping:
            desc = f'未获取到{VENDOR_PREFIX}Mapping_2G'
            raise ValueError(desc)

        updated_mapping = self._update_mapping_with_instance(original_mapping)
        return updated_mapping

    def get_mapping5g_info(self):
        """
        功能描述：获取5G wifi映射信息，并将列表下标替换为真实的X_SDMC_Instance
        """
        params = {
            "path": f"Device.WiFi.{VENDOR_PREFIX}Mapping_5G",
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1]
        original_mapping = data.get(f'{VENDOR_PREFIX}Mapping_5G')
        log.info(f"5g mapping original result:{result}")

        if not original_mapping:
            desc = f'未获取到{VENDOR_PREFIX}Mapping_5G'
            raise ValueError(desc)

        updated_mapping = self._update_mapping_with_instance(original_mapping)
        log.info(f"update_mapping:{updated_mapping}")
        return updated_mapping

    def _update_mapping_with_instance(self, mapping_str):
        """
        核心逻辑处理函数：
        将映射字符串中的“列表下标”按 Radio, AccessPoint, SSID 的顺序替换为真实的 X_SDMC_Instance 值
        """
        parts = mapping_str.split('@')
        if len(parts) != 2:
            return mapping_str

        # 预先获取三个核心节点的完整原始返回数据
        raw_radio_list = self._get_node_list("Device.WiFi.Radio.")
        raw_ap_list = self._get_node_list("Device.WiFi.AccessPoint.")
        raw_ssid_list = self._get_node_list("Device.WiFi.SSID.")

        # 打印一下真实的数据结构，方便你排查 Ubus 返回的嵌套格式
        log.info(f"Debug raw_radio_list: {raw_radio_list}")

        new_parts = []

        # 遍历 @ 分割后的每一组
        for part in parts:
            indices = part.split(',')
            new_indices = []

            # 严格按照 Radio, AccessPoint, SSID 的顺序对应索引
            # 这里需要根据你实际的 Ubus 返回结构调整提取逻辑
            # 假设返回结构是 [0, { 'Radio': [ {...}, {...} ] }]，则提取真实列表的方法如下：
            try:
                real_radio_list = raw_radio_list[1]['Radio']
                real_ap_list = raw_ap_list[1]['AccessPoint']
                real_ssid_list = raw_ssid_list[1]['SSID']
            except (IndexError, KeyError, TypeError) as e:
                log.error(f"提取节点列表失败，请检查 _get_node_list 返回的数据结构: {e}")
                return False

            node_lists = [real_radio_list, real_ap_list, real_ssid_list]

            for i in range(len(indices)):
                list_index = int(indices[i].strip())  # 获取列表下标 (0, 1, 2...)
                log.info(f"当前处理类型: {['Radio', 'AccessPoint', 'SSID'][i]}, 下标: {list_index}")

                target_list = node_lists[i]

                # 容错处理：防止下标越界
                if 0 <= list_index < len(target_list) + 1:
                    # 直接根据下标拿到对应的节点字典
                    target_node_dict = target_list[list_index - 1]
                    log.info(f"取到的节点数据: {target_node_dict}")

                    # 提取真实的 X_SDMC_Instance 值
                    instance_value = target_node_dict.get("X_SDMC_Instance")

                    if instance_value is not None:
                        new_indices.append(str(instance_value))
                    else:
                        log.warning("未找到 X_SDMC_Instance，保留原下标")
                        new_indices.append(indices[i])
                else:
                    desc = f"Index {list_index} out of range for list length {len(target_list)}"
                    log.warning(f"Index {list_index} out of range for list length {len(target_list)}")
                    new_indices.append(indices[i])
                    raise ValueError(desc)

            new_parts.append(','.join(new_indices))

        return '@'.join(new_parts)

    def _get_node_list(self, base_path):
        """
        辅助方法：获取指定基础路径下的所有节点数据
        """
        try:
            params = {"path": base_path, "optional": {"proto": "web"}}
            res = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
            if res and res:
                return res
        except Exception as e:
            log.error(f"Failed to get node list for path {base_path}: {e}")
        return {}

    # def get_mapping2g_info(self):
    #     """
    #     功能描述：
    #     获取2.4G wifi映射信息

    #     返回值：
    #     映射信息：1,1,1@1,2,2
    #     """
    #     params = {
    #         "path": f"Device.WiFi.{VENDOR_PREFIX}Mapping_2G",
    #         "optional": {"proto": "web"}
    #     }
    #     result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
    #     data = result[1]
    #     # log.info(data)
    #     mapping2g = data.get(f'{VENDOR_PREFIX}Mapping_2G')

    #     return mapping2g

    # def get_mapping5g_info(self):
    #     """
    #     功能描述：
    #     获取5G wifi映射信息

    #     返回值：
    #     映射信息：2,3,4@2,4,5
    #     """
    #     params = {
    #         "path": f"Device.WiFi.{VENDOR_PREFIX}Mapping_5G",
    #         "optional": {"proto": "web"}
    #     }
    #     result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
    #     data = result[1]
    #     mapping5g = data.get(f'{VENDOR_PREFIX}Mapping_5G')
    #     log.info(f"5g mapping:{result}")

    #     return mapping5g

    def parse_mapping(self, mapping_str):
        """
        功能描述：
        解析wifi路径映射

        入参：
        mapping_str：2.4G或5G的路径映射信息

        mapping5g = data.get(f'{VENDOR_PREFIX}Mapping_5G')

        return mapping5g

    def parse_mapping(self, mapping_st
        返回值：
        字典：{'RadioPath': 'Device.WiFi.Radio.1.', 'AccessPointPath': 'Device.WiFi.AccessPoint.1.', 'SSIDPath': 'Device.WiFi.SSID.1.'}
        """
        if not mapping_str:
            log.error("mapping2g_str is empty or None")
            return []

        result = []
        groups = mapping_str.split('@')  # 支持多个 AP

        for group in groups:
            try:
                radio_path, acess_path, ssid_path = group.split(',')
                entry = {
                    "RadioPath": f"Device.WiFi.Radio.{radio_path}.",
                    "AccessPointPath": f"Device.WiFi.AccessPoint.{acess_path}.",
                    "SSIDPath": f"Device.WiFi.SSID.{ssid_path}."
                }
                result.append(entry)
                log.info("parse" + str(result))
            except ValueError:
                log.error(f"Invalid format in group: '{group}', expected 'radio_path, acess_path, ssid_path'")
                continue

        return result

    def get_ssid_info(self, path):
        """
        功能描述：
        获取页面wifi ssid部分配置信息

        返回值：
        页面包含的wifi ssid部分信息
        """
        if not path:
            log.error("mapping2g_str is empty or None")
            return []

        ssidpath = path[0].get('SSIDPath')
        params = {
            "path": ssidpath,
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        data = result[1].get('SSID')[0]

        ssidinfo = {
            "Enable SSID": data.get("Enable"),
            "SSID": data.get("SSID")
        }
        return ssidinfo

    def get_accesspoint_info(self, path):
        """
        功能描述：
        获取页面wifi accesspoint部分配置信息

        返回值：
        页面包含的wifi accesspoint部分信息
        """
        if not path:
            log.error("mapping2g_str is empty or None")
            return {}

        accesspointpath = path[0].get('AccessPointPath')
        params = {
            "path": accesspointpath,
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        AccessPointData = result[1].get('AccessPoint')[0]

        info = {
            "MaxAllowedAssociations": AccessPointData.get('MaxAllowedAssociations'),
            "BroadcastSSID": AccessPointData.get('SSIDAdvertisementEnabled'),
            "WMMEnable": AccessPointData.get('WMMEnable'),
            "AuthorizationMode": AccessPointData.get('Security', {}).get('ModeEnabled'),
            "WPAPreSharedKey": AccessPointData.get('Security', {}).get(f'{VENDOR_PREFIX}Key'),
            "AuthorizationModesSupported": AccessPointData.get('Security', {}).get('ModesSupported')
        }

        return info

    def parse_radio_modebwmap(self, ubus_response):
        """
        【功能描述】
        解析radio ubus response中的modebwmap部分

        【入参】
        ubus_response: radio ubus response中的modebwmap部分

        【返回值】
        Mode  : wifi支持的Mode
        Bandwidth : wifi支持的频宽

        """

        data = json.loads(ubus_response)
        modes = []
        bandwidths = set()

        for entry in data["list"]:
            modes.append(entry["standard"])
            bandwidths.update(entry["bw"].split(','))

        return modes, bandwidths

    def get_radio_info(self, path):
        """
        功能描述：
        获取页面wifi radio部分配置信息

        返回值：
        页面包含的wifi radio部分信息
        """
        if not path:
            log.error("mapping2g_str is empty or None")
            return {}

        radiopath = path[0].get('RadioPath')
        params = {
            "path": radiopath,
            "optional": {"proto": "web"}
        }
        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        Radio = result[1].get('Radio')[0]

        Mode = None
        Bandwidth = None
        ModeBWMap = Radio.get(f"{VENDOR_PREFIX}ModeBWMap")
        # log.info("ModeBWMap is" + str(ModeBWMap))
        Mode, Bandwidth = self.parse_radio_modebwmap(ModeBWMap)

        info = {
            "ChannelEnabled": Radio.get(f'{VENDOR_PREFIX}ChannelEnabled'),
            "Channel": Radio.get('Channel'),
            "ChannelBandwidth": Radio.get('OperatingChannelBandwidth'),
            "OperatingMode": Radio.get('OperatingStandards'),
            "TransmitPower": Radio.get('TransmitPower'),
            "ChannelSupport": Radio.get(f'{VENDOR_PREFIX}ChannelsSupported'),
            "ModeSupport": Mode,
            "BandwidthSupport": ",".join(sorted(Bandwidth)),
            "ChannelSupportAll": Radio.get(f'{VENDOR_PREFIX}ChannelsSupported')
        }
        chan_bw_map_str = Radio.get(f"{VENDOR_PREFIX}ChanBWMap")
        if chan_bw_map_str:
            try:
                chan_bw_map = json.loads(chan_bw_map_str)
                channel_bw = info.get("ChannelBandwidth")
                if channel_bw in chan_bw_map:
                    channels = chan_bw_map[channel_bw]
                    channels = [str(ch) for ch in channels]
                    info["ChannelSupport"] = ",".join(channels)
            except json.JSONDecodeError as e:
                log.error(f"Failed to parse {VENDOR_PREFIX}ChanBWMap: {e}")

        return info

    def get_all_2g_config(self, index=0):
        """
        功能描述：
        获取页面 2G wifi 配置信息

        入参：
        index: 指定获取第几个 AP 的配置，默认=0
               当设备有多个 AP 时（如"1,1,1,1"），可以通过 index 指定获取第几个
               例如：index=0 获取第 1 个 AP，index=1 获取第 2 个 AP

        返回值：
        页面包含的 2G wifi 信息
        """
        try:
            config_2g = {}

            mapping_str = self.get_mapping2g_info()
            mapping_path = self.parse_mapping(mapping_str)
            if not mapping_path:
                log.error("2G mapping_path is empty.")
                return config_2g

            # 根据 index 获取指定的 AP 路径
            if 0 <= index < len(mapping_path):
                target_path = [mapping_path[index]]
                log.info(f"获取 2G 配置，index={index}, 路径：{target_path[0]}")
            else:
                log.error(f"index={index} 超出范围 {len(mapping_path)}")
                return config_2g

            ssid_info = self.get_ssid_info(target_path)
            config_2g.update(ssid_info)

            ap_info = self.get_accesspoint_info(target_path)
            config_2g.update(ap_info)

            radio_info = self.get_radio_info(target_path)
            config_2g.update(radio_info)

            return config_2g
        except Exception as e:
            log.info(str(e))
            return 0

    def get_all_5g_config(self, index=0):
        """
        功能描述：
        获取页面 5G wifi 配置信息

        入参：
        index: 指定获取第几个 AP 的配置，默认=0
               当设备有多个 AP 时（如"1,1,1,1"），可以通过 index 指定获取第几个
               例如：index=0 获取第 1 个 AP，index=1 获取第 2 个 AP

        返回值：
        页面包含的 5G wifi 信息
        """
        try:
            config_5g = {}

            mapping_str = self.get_mapping5g_info()
            mapping_path = self.parse_mapping(mapping_str)
            if not mapping_path:
                log.error("2G mapping_path is empty.")
                return config_5g

            # 根据 index 获取指定的 AP 路径
            if 0 <= index < len(mapping_path):
                target_path = [mapping_path[index]]
                log.info(f"获取 5G 配置，index={index}, 路径：{target_path[0]}")
            else:
                log.error(f"index={index} 超出范围 {len(mapping_path)}")
                return config_5g

            ssid_info = self.get_ssid_info(target_path)
            config_5g.update(ssid_info)

            ap_info = self.get_accesspoint_info(target_path)
            config_5g.update(ap_info)

            radio_info = self.get_radio_info(target_path)
            config_5g.update(radio_info)

            return config_5g

        except Exception as e:
            log.info(str(e))
            return 0

    def _get_all_wifi_config(self):
        """
        功能描述：
        获取页面所有wifi配置信息

        返回值：
        页面包含的所有wifi信息
        """
        try:
            config = {}

            dual_band = self.get_bansteering_value()
            config["DualBandEnable"] = dual_band

            if dual_band:
                mapping_str = self.get_mapping2g_info()
                mapping_path = self.parse_mapping(mapping_str)
                if not mapping_path:
                    log.error("Merged mapping_path is empty.")
                    return config

                ssid_info = self.get_ssid_info(mapping_path)
                config.update(ssid_info)

                ap_info = self.get_accesspoint_info(mapping_path)
                config.update(ap_info)

            else:
                config_2g = self.get_all_2g_config()
                config_2g.pop("DualBandEnable", None)
                config["2G_Config"] = config_2g

                config_5g = self.get_all_5g_config()
                config_5g.pop("DualBandEnable", None)
                config["5G_Config"] = config_5g

            return config
        except Exception as e:
            log.info(str(e))
            return 0

    def get_all_wifi_config(self, index=0):
        """
        功能描述：
        获取页面所有 wifi 配置信息

        入参：
        index: 指定获取第几个 AP 的配置，默认=0
               当设备有多个 AP 时（如"1,1,1,1"），可以通过 index 指定获取第几个

        返回值：
        页面包含的所有 wifi 信息（返回单个 SSID 的信息，DualBandEnable 为对应 index 的状态值）

        示例：
        # index=0 时返回第一个 SSID 的信息，DualBandEnable 为"1"或"0"
        # index=1 时返回第二个 SSID 的信息，DualBandEnable 为对应位置的值
        """
        try:
            config = {}

            # 获取双频合一状态
            dual_band = self.get_bansteering_value()

            # 处理 DualBandEnable 值，获取当前 index 对应的状态
            if isinstance(dual_band, bool):
                dual_band_str = "1" if dual_band else "0"
            else:
                dual_band_str = str(dual_band)

            # 判断当前 index 对应的状态
            if ',' in dual_band_str:
                dual_values = dual_band_str.split(',')
                if 0 <= index < len(dual_values):
                    config["DualBandEnable"] = dual_values[index]
                else:
                    log.error(f"index={index} 超出范围 {len(dual_values)}")
                    config["DualBandEnable"] = dual_values[0] if dual_values else "0"
            else:
                config["DualBandEnable"] = dual_band_str

            if config["DualBandEnable"] == "1":
                mapping_str = self.get_mapping2g_info()
                mapping_path = self.parse_mapping(mapping_str)
                if not mapping_path:
                    log.error("Merged mapping_path is empty.")
                    return config

                # 根据 index 获取指定的 AP 路径
                if 0 <= index < len(mapping_path):
                    target_path = [mapping_path[index]]
                    log.info(f"获取双频合一配置，index={index}, 路径：{target_path[0]}")
                else:
                    log.error(f"index={index} 超出范围 {len(mapping_path)}")
                    raise ValueError(f"index={index} 超出范围 {len(mapping_path)}")

                ssid_info = self.get_ssid_info(target_path)
                config.update(ssid_info)

                ap_info = self.get_accesspoint_info(target_path)
                config.update(ap_info)

            else:
                config_2g = self.get_all_2g_config(index=index)
                config_2g.pop("DualBandEnable", None)
                config["2G_Config"] = config_2g

                config_5g = self.get_all_5g_config(index=index)
                config_5g.pop("DualBandEnable", None)
                config["5G_Config"] = config_5g

            return config
        except Exception as e:
            log.info(str(e))
            return 0

    def set_ssid_config(self, path, config):
        """
        功能描述：
        设置wifi ssid配置

        入参：
        path：2.4G或5G wifi接口的ubus路径
        config：ssid部分的ubus配置

        返回值：
        字典：包含wifi接口的ubus路径和ssid配置字典，用于set_wifi_config统一设置
        """
        obj_path = {}
        if "Enable" in config:
            obj_path["Enable"] = config["Enable"]
        if "SSID" in config:
            obj_path["SSID"] = config["SSID"]
        if not obj_path:
            return None
        return {
            "addr": path,
            "obj_path": obj_path
        }

    def set_accesspoint_config(self, path, config):
        """
        功能描述：
        设置wifi accesspointe配置

        入参：
        path：2.4G或5G wifi接口的ubus路径
        config：accesspoint部分的ubus配置

        返回值：
        字典：包含wifi接口的ubus路径和accesspoint配置字典，用于set_wifi_config统一设置
        """
        obj_path = {}
        if "MaxAllowedAssociations" in config:
            obj_path["MaxAllowedAssociations"] = config["MaxAllowedAssociations"]
        if "SSIDAdvertisementEnabled" in config:
            obj_path["SSIDAdvertisementEnabled"] = config["SSIDAdvertisementEnabled"]
        if "WMMEnable" in config:
            obj_path["WMMEnable"] = config["WMMEnable"]
        if not obj_path:
            return None
        return {
            "addr": path,
            "obj_path": obj_path
        }

    def set_security_config(self, path, config):
        """
        功能描述：
        设置wifi security配置

        入参：
        path：2.4G或5G wifi接口的ubus路径
        config：security部分的ubus配置

        返回值：
        字典：包含wifi接口的ubus路径和security配置字典，用于set_wifi_config统一设置
        """
        obj_path = {}
        if "AuthorizationMode" in config:
            obj_path["ModeEnabled"] = config["AuthorizationMode"]
        if "Password" in config:
            obj_path[f"{VENDOR_PREFIX}Key"] = config["Password"]
        if not obj_path:
            return None
        return {
            "addr": path,
            "obj_path": obj_path
        }

    def set_radio_config(self, path, config):
        """
        功能描述：
        设置wifi radio配置

        入参：
        path：2.4G或5G wifi接口的ubus路径
        config：radio部分的ubus配置

        返回值：
        字典：包含wifi接口的ubus路径和radio配置字典，用于set_wifi_config统一设置
        """
        obj_path = {}
        if "Channel" in config:
            obj_path[f"{VENDOR_PREFIX}ChannelEnabled"] = config["Channel"]
        if "OperatingMode" in config:
            obj_path[f"{VENDOR_PREFIX}OperatingStandards"] = config["OperatingMode"]
        if "ChannelBandwidth" in config:
            obj_path["OperatingChannelBandwidth"] = config["ChannelBandwidth"]
        if "TransmitPower" in config:
            obj_path["TransmitPower"] = config["TransmitPower"]
        if not obj_path:
            return None
        return {
            "addr": path,
            "obj_path": obj_path
        }

    def set_wifi_config(self, config, index=0):
        """
        功能描述：设置 wifi 配置

        入参：
        config：包含所有的 wifi 配置信息，根据需求修改对应部分，配置模板如下：
            wifi_config = {
                "DualBandEnable": "0",  # 双频合一

                "2G_SSID": {
                    "SSID": "SDMC_2G123",
                    "Enable": True
                },
                "2G_AP": {
                    "MaxAllowedAssociations": "32",
                    "SSIDAdvertisementEnabled": "1",
                    "WMMEnable": "1",
                    "AuthorizationMode": "WPA2-Personal",
                    "Password": "Sdmc@456"
                },
                "2G_RADIO": {
                    "Channel": "1",
                    "ChannelBandwidth": "20/40MHz",
                    "OperatingMode": "b,g,n,ax",
                    "TransmitPower": "100"
                }

                "5G_SSID": {
                    "SSID": "!!!SDMC_5G111",
                    "Enable": True
                },
                "5G_AP": {
                    "MaxAllowedAssociations": "20",
                    "SSIDAdvertisementEnabled": "1",
                    "WMMEnable": "0",
                    "AuthorizationMode": "WPA2-Personal",
                    "Password": "Sdmc@1456"
                },
                "5G_RADIO": {
                    "Channel": "auto",
                    "ChannelBandwidth": "160MHz",
                    "OperatingMode": "a,n,ac,ax",
                    "TransmitPower": "100"
                }
            }

        index: 双频合一索引位置，默认=0，与 DualBandEnable 配合使用
               会先获取当前设备的 DualBandEnable 值（如 "1,1,1,1"）
               然后根据 index 修改对应位置的值为 config 中传入的值
               例如：当前="1,1,1,1", config={"DualBandEnable": "0"}, index=0 → 结果="0,1,1,1"
        """
        try:
            index = int(index)
            mapping2g = self.get_mapping2g_info()
            mapping5g = self.get_mapping5g_info()
            path2g = self.parse_mapping(mapping2g)[index]
            path5g = self.parse_mapping(mapping5g)[index]
            # log.info("path2g =" + str(path2g))
            # log.info("path5g =" + str(path5g))

            if not path2g or not path5g:
                log.error("无法获取 2G 或 5G 映射路径")
                return None

            paths = []
            dual_enable = config.get("DualBandEnable", "None")
            processed_dual_enable = None
            if dual_enable != "None":
                # 先获取当前设备的 DualBandEnable 值
                current_info = self._get_all_wifi_config()
                current_dual = current_info.get("DualBandEnable")
                log.info(f"当前 DualBandEnable: {current_dual}")

                # 将当前值转换为字符串处理
                if isinstance(current_dual, bool):
                    current_dual_str = "1" if current_dual else "0"
                else:
                    current_dual_str = str(current_dual)

                # 目标值（要设置的值）
                target_value = str(dual_enable)

                # 判断当前值是单值还是多值
                if ',' in current_dual_str:
                    # 多值情况（如 "1,1,1,1"）
                    dual_values = current_dual_str.split(',')

                    # 修改指定 index 位置的值
                    if 0 <= index < len(dual_values):
                        dual_values[index] = target_value
                        processed_dual_enable = ','.join(dual_values)
                        log.info(
                            f"DualBandEnable: {current_dual_str} -> {processed_dual_enable} (index={index}, target={target_value})")
                    else:
                        log.error(f"index={index} 超出范围 {len(dual_values)}")
                        raise ValueError(f"index={index} 超出范围 {len(dual_values)}")
                else:
                    # 单值情况（如 "1" 或 "0"）
                    # 如果 index=0，直接替换；否则保持原值
                    if index == 0:
                        processed_dual_enable = target_value
                    else:
                        processed_dual_enable = current_dual_str
                    log.info(f"DualBandEnable: {current_dual_str} -> {processed_dual_enable} (index={index})")

                # 设置 DualBandEnable
                paths.append({
                    "addr": "Device.WiFi.",
                    "obj_path": {
                        f"{VENDOR_PREFIX}DualBandEnable": processed_dual_enable
                    }
                })

            if processed_dual_enable == "1" or (
                    isinstance(processed_dual_enable, str) and processed_dual_enable.startswith("1")):
                # 双频合一，统一使用 2G 配置
                ssid_conf = config.get("2G_SSID", {})
                ap_conf = config.get("2G_AP", {})
                radio_conf = config.get("2G_RADIO", {})

                # SSID 设置
                for path in [path2g["SSIDPath"], path5g["SSIDPath"]]:
                    item = self.set_ssid_config(path, ssid_conf)
                    if item: paths.append(item)

                # AP 设置
                for path in [path2g["AccessPointPath"], path5g["AccessPointPath"]]:
                    item = self.set_accesspoint_config(path, ap_conf)
                    if item: paths.append(item)
                    sec_item = self.set_security_config(path + "Security.", ap_conf)
                    if sec_item: paths.append(sec_item)

            else:
                radio_path_set = set()

                # 处理 2G 配置
                ssid_conf = config.get("2G_SSID", {})
                ap_conf = config.get("2G_AP", {})
                radio_conf = config.get("2G_RADIO", {})

                item = self.set_ssid_config(path2g["SSIDPath"], ssid_conf)
                if item: paths.append(item)

                item = self.set_accesspoint_config(path2g["AccessPointPath"], ap_conf)
                if item: paths.append(item)

                sec_item = self.set_security_config(path2g["AccessPointPath"] + "Security.", ap_conf)
                if sec_item: paths.append(sec_item)

                radio_path = path2g["RadioPath"]
                if radio_path not in radio_path_set:
                    radio_item = self.set_radio_config(radio_path, radio_conf)
                    if radio_item:
                        paths.append(radio_item)
                        radio_path_set.add(radio_path)

                # 处理 5G 配置
                ssid_conf = config.get("5G_SSID", {})
                ap_conf = config.get("5G_AP", {})
                radio_conf = config.get("5G_RADIO", {})

                item = self.set_ssid_config(path5g["SSIDPath"], ssid_conf)
                if item: paths.append(item)

                item = self.set_accesspoint_config(path5g["AccessPointPath"], ap_conf)
                if item: paths.append(item)

                sec_item = self.set_security_config(path5g["AccessPointPath"] + "Security.", ap_conf)
                if sec_item: paths.append(sec_item)

                radio_path = path5g["RadioPath"]
                if radio_path not in radio_path_set:
                    radio_item = self.set_radio_config(radio_path, radio_conf)
                    if radio_item:
                        paths.append(radio_item)
                        radio_path_set.add(radio_path)

            ubus_params = {
                "paths": paths,
                "optional": {"proto": "web"}
            }
            return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", ubus_params)
        except Exception as e:
            log.info(str(e))
            return 0

    def set_mlo_enable(self, enable: bool):
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
        try:
            action = "Enable" if enable else "Disable"
            print(f"\n>>> Start to {action} MLO")

            dual_band = self.get_bansteering_value()
            print(f">>> Current DualBandEnable = {dual_band}")

            if dual_band != "1":
                log.error(">>> DualBandEnable is not enabled. Cannot configure MLO.")
                return None

            # 通过已有的 mapping 接口拿到 2.4G / 5G 的 SSID 路径
            mapping2g = self.get_mapping2g_info()
            mapping5g = self.get_mapping5g_info()
            path2g = self.parse_mapping(mapping2g)[0]
            path5g = self.parse_mapping(mapping5g)[0]

            if not path2g or not path5g:
                log.error("Failed to get 2G/5G mapping information.")
                return None

            # SSIDPath 一般类似：Device.WiFi.SSID.1.
            ssid_paths = [path2g["SSIDPath"], path5g["SSIDPath"]]

            # -1 表示关闭；0 表示开启
            mld_value = "0" if enable else "-1"

            paths = []
            for ssid_path in ssid_paths:
                # 防御：确保结尾有 .
                if not ssid_path.endswith("."):
                    ssid_path = ssid_path + "."

                print(f">>> Setting {ssid_path} MLDUnit = {mld_value}")

                paths.append({
                    "addr": ssid_path,
                    "obj_path": {
                        "MLDUnit": mld_value
                    }
                })

            ubus_params = {
                "paths": paths,
                "optional": {"proto": "web"}
            }

            result = self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "set",
                ubus_params
            )

            print(f">>> {action} MLO completed. Result: {result}\n")
            return result

        except Exception as e:
            print(">>> Failed to set MLO:", e)
            return None

    def add_energy_rule(self):
        """
        功能描述：
        新增一条 WlanTimeoff 规则。
        对应 ubus 命令：
            ubus call bbfdm add '{"path":"Device.WiFi.X_SDMC_WlanTimeoff."}'

        返回值：
            instance (int) 新增规则的实例号，如 1 / 2 / 3
            失败返回 None
        """
        try:
            params = {
                "path": "Device.WiFi.X_SDMC_WlanTimeoff.",
            }
            result = self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "add",
                params
            )

            # 实际返回：
            # [0, {'results': [{'path': 'Device.WiFi.X_SDMC_WlanTimeoff.', 'data': '1'}]}]
            if not isinstance(result, (list, tuple)) or len(result) < 2:
                log.error(f"Invalid add result: {result}")
                return None

            data_dict = result[1]
            results_list = data_dict.get("results", [])

            if not results_list:
                log.error(f"No 'results' in add result: {result}")
                return None

            inst_str = results_list[0].get("data")
            if inst_str is None:
                log.error(f"No 'data' in add result item: {results_list[0]}")
                return None

            inst = int(inst_str)
            log.info(f"Add WlanTimeoff instance success, instance = {inst}")
            return inst

        except Exception as e:
            log.exception(f"Add WlanTimeoff instance failed: {e}")
            return None

    def set_energy_rule(self, instance, enable, start_time, stop_time,
                        weekdays=None, description=""):
        """
        功能描述：
        配置指定的 WlanTimeoff 规则。
        对应 ubus 命令示例：

            ubus call bbfdm set '{
                "paths": [
                    {
                        "addr": "Device.WiFi.X_SDMC_WlanTimeoff.<instance>.",
                        "obj_path": {
                            "Description": "xxxxx",
                            "Enable": "1",
                            "StartTime": "00:00",
                            "StopTime": "02:00",
                            "WeekDays": "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
                        }
                    }
                ],
                "optional": {"proto":"web"}
            }'

        入参：
            instance   : int，规则实例号（1、2、3...）
            enable     : bool 或 "0"/"1"
            start_time : "HH:MM"
            stop_time  : "HH:MM"
            weekdays   : list 或 逗号分隔字符串，None 表示每天
            description: 描述字符串，可选

        返回：
            ubus 调用结果，失败返回 None
        """
        try:
            inst = int(instance)
            addr = f"Device.WiFi.X_SDMC_WlanTimeoff.{inst}."

            # WeekDays 处理
            if weekdays is None:
                # 默认：每天
                weekdays_str = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
            elif isinstance(weekdays, (list, tuple)):
                weekdays_str = ",".join(weekdays)
            else:
                weekdays_str = str(weekdays)

            enable_str = "1" if (enable is True or str(enable) == "1") else "0"

            obj = {
                "Enable": enable_str,
                "StartTime": start_time,
                "StopTime": stop_time,
                "WeekDays": weekdays_str
            }
            # Description 为可选项
            if description is not None and description != "":
                obj["Description"] = str(description)

            params = {
                "paths": [
                    {
                        "addr": addr,
                        "obj_path": obj
                    }
                ],
                "optional": {"proto": "web"}
            }

            log.info(
                f"Set WlanTimeoff.{inst}: "
                f"Enable={enable_str}, Start={start_time}, Stop={stop_time}, "
                f"WeekDays={weekdays_str}, Description={description}"
            )

            return self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "set",
                params
            )
        except Exception as e:
            log.exception(f"Set WlanTimeoff.{instance} failed: {e}")
            raise ValueError(f"Set WlanTimeoff.{instance} failed: {e}")

    def delete_energy_rule(self, instance):
        """
        功能描述：
        Delete a specific WiFi Energy Saving (WlanTimeoff) instance.
        对应 ubus 命令：
            ubus call bbfdm delete '{"path":"Device.WiFi.X_SDMC_WlanTimeoff.<instance>."}'

        入参：
            instance : int，规则实例号（如 1、2、3 ...）

        返回：
            True  -> 删除成功
            False -> 删除失败
        """
        try:
            inst = int(instance)
            path = f"Device.WiFi.X_SDMC_WlanTimeoff.{inst}."

            params = {
                "path": path
            }

            log.info(f"Deleting WlanTimeoff instance {inst} ...")

            result = self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "del",
                params
            )

            # 预期返回：
            # [0, {'results': [{'path': '...', 'data': '1'}]}]

            if not isinstance(result, (list, tuple)) or len(result) < 2:
                log.error(f"Invalid delete result: {result}")
                return False

            results_list = result[1].get("results", [])
            if not results_list:
                log.error(f"No 'results' in delete result: {result}")
                return False

            data_val = results_list[0].get("data")

            if str(data_val) == "1":
                log.info(f"Delete WlanTimeoff.{inst} success")
                return True
            else:
                log.error(f"Delete WlanTimeoff.{inst} failed, data={data_val}")
                return False

        except Exception as e:
            log.exception(f"Delete WlanTimeoff.{instance} failed: {e}")
            return False

    # =======================================robot api====================================================

    def ubus_set_2g_wifi(self, bandsteering=0, ssid="Test_2G_01", password="Sdmc@1234_2G", channel="1",
                         bandwidth="20/40MHz", wifi_mode="b,g,n,ax", security_mode="WPA2-Personal", ssid_enable=True,
                         max_connect_count="32", broadcast_ssid="1", WMN_Enable="1", TransmitPower="100",
                         wait_time="90",
                         index=0):
        """
        功能描述：设置 2.4G WiFi 参数，未传入参数则使用默认参数

        参数：

        ssid: WIFI 名称，默认："Test_2G_01";

        password: WIFI 密码，默认："Sdmc@1234_2G"；

        channel: WIFI 信道，默认：auto；可填：auto，1，2，3......，11；

        bandwidth：带宽，默认：20/40MHz；可填：20MHz；40MHz；20/40MHz；

        wifi_mode: WiFi 模式，默认：b,g,n,ax；可填：b; b,g; b,g,n; b,g,n,ax; b,g,n,ax,be

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填：None；WPA2-Personal; WPA3-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开；可填：True 对应 开；False 对应 关；

        max_connect_count: WiFi 最大连接数量；默认：32；可填：0-32；

        broadcast_ssid: 广播 WiFi 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        TransmitPower：WiFi 发射功率；默认：100；可填；20，40，60，80，100；

        wait_time: 设置 wifi 等待时间；默认：90

        index: 指定设置第几组 5G SSID，默认 0 表示第一组

        Example:
        |  Ubus_Network_Wlan_Set_2G  | ssid=jjwwbb6688_2G | password=J@wb1234 | channel=1 | bandwidth=2 | wifi_mode=3 |
        """
        check_password = self.ubus.validate_password(password)
        log.info("check password result")

        wifi_2g_config = {
            # "DualBandEnable": f"{bandsteering}",

            "2G_SSID": {
                "SSID": f"{ssid}",
                "Enable": ssid_enable
            },
            "2G_AP": {
                "MaxAllowedAssociations": f"{max_connect_count}",
                "SSIDAdvertisementEnabled": f"{broadcast_ssid}",
                "WMMEnable": f"{WMN_Enable}",
                "AuthorizationMode": f"{security_mode}",
                "Password": f"{password}"
            },
            "2G_RADIO": {
                "Channel": f"{channel}",
                "ChannelBandwidth": f"{bandwidth}",
                "OperatingMode": f"{wifi_mode}",
                "TransmitPower": f"{TransmitPower}"
            }
        }

        set_2g = self.set_wifi_config(wifi_2g_config, index=index)
        if set_2g == 0:
            raise ValueError("------设置第 {index} 组 2.4G WiFi 失败，请检查参数配置--------")

        log.info(f"设置第 {index} 组 2.4G WiFi 成功，等待{wait_time}S WiFi重启..........")
        time.sleep(int(wait_time))
        return True

    def ubus_set_5g_wifi(self, bandsteering=0, ssid="Test_5G_01", password="Sdmc@1234_5G", channel="36",
                         bandwidth="160MHz", wifi_mode="a,n,ac,ax", security_mode="WPA2-Personal", ssid_enable=True,
                         max_connect_count="32", broadcast_ssid="1", WMN_Enable="1", TransmitPower="100",
                         wait_time="90",
                         index=0):
        """
        功能描述：设置 5G WiFi 参数

        参数：

        ssid: WIFI 名称，默认："Test_5G_01";

        password: WIFI 密码，默认："Sdmc@1234_5G"；

        channel: WIFI 信道，默认：auto；可填：auto...36..64..149...；

        bandwidth：带宽，默认：160MHZ；可填：20MHz；40MHz；80MHz；160MHz

        wifi_mode: WiFi 模式，默认：a,n,ac,ax；可填：a; a,n;  a,n,ac; a,n,ac,ax;

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填：None；WPA2-Personal; WPA3-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开；可填：True 对应 开；False 对应 关；

        max_connect_count: WiFi 最大连接数量；默认：32；可填：0-32；

        broadcast_ssid: 广播 WiFi 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        TransmitPower：WiFi 发射功率；默认：100；可填；20，40，60，80，100；

        wait_time: 设置 wifi 等待时间；默认：90

        index: 指定设置第几组 5G SSID，默认 0 表示第一组
        """

        check_password = self.ubus.validate_password(password)

        wifi_5g_config = {
            # "DualBandEnable": f"{bandsteering}",

            "5G_SSID": {
                "SSID": f"{ssid}",
                "Enable": ssid_enable
            },
            "5G_AP": {
                "MaxAllowedAssociations": f"{max_connect_count}",
                "SSIDAdvertisementEnabled": f"{broadcast_ssid}",
                "WMMEnable": f"{WMN_Enable}",
                "AuthorizationMode": f"{security_mode}",
                "Password": f"{password}"
            },
            "5G_RADIO": {
                "Channel": f"{channel}",
                "ChannelBandwidth": f"{bandwidth}",
                "OperatingMode": f"{wifi_mode}",
                "TransmitPower": f"{TransmitPower}"
            }
        }

        set_5g = self.set_wifi_config(wifi_5g_config, index=index)
        if set_5g == 0:
            raise ValueError("------设置第 {index} 组 5G WiFi 失败，请检查参数配置--------")

        log.info(f"设置第 {index} 组 5G WiFi 成功，等待{wait_time}S WiFi重启..........")
        time.sleep(int(wait_time))
        return True

    def ubus_set_bandsteering(self, bandsteering=1, ssid="Test_2G_01", password="Sdmc@1234_2G",
                              security_mode="WPA2-Personal", ssid_enable=True,
                              max_connect_count="32", broadcast_ssid="1", WMN_Enable="1", wait_time="90",
                              index=0):
        """
        功能描述：
        设置双频合一参数

        入参：
        bandsteering:双频合一开关；默认 0：关；可填：0：关；1：开；

        ssid: WIFI 名称，默认："Test_2G_01";

        password: WIFI 密码，默认："Sdmc@1234_2G"；

        security_mode: 安全认证模式，默认：WPA2-Personal; 可填：None；WPA2-Personal; WPA2-Personal-Transition;

        ssid_enable: WIFI ssid 使能开关；默认：True 对应开；可填：True 对应 开；False 对应 关；

        max_connect_count: WiFi 最大连接数量；默认：32；可填：0-32；

        broadcast_ssid: 广播 WiFi 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        WMN_Enable：WMN 使能开关；默认：1 开启；可填：0 对应 关；1 对应 开；

        wait_time: 设置 wifi 等待时间；默认：90

        index: 指定设置第几组 SSID，默认 0 表示第一组
        """
        check_password = self.ubus.validate_password(password)
        BandSteering_config = {
            "DualBandEnable": f"{bandsteering}",  # 双频合一

            "2G_SSID": {
                "SSID": f"{ssid}",
                "Enable": ssid_enable
            },
            "2G_AP": {
                "MaxAllowedAssociations": f"{max_connect_count}",
                "SSIDAdvertisementEnabled": f"{broadcast_ssid}",
                "WMMEnable": f"{WMN_Enable}",
                "AuthorizationMode": f"{security_mode}",
                "Password": f"{password}"
            }
        }
        set_bandsteering = self.set_wifi_config(BandSteering_config, index=index)
        if set_bandsteering == 0:
            raise ValueError("--------双频合一设置失败---------")

        log.info(f"等待{wait_time}S WiFi 重启..........")
        time.sleep(int(wait_time))
        return True

    def ubus_get_all_bandsteerding_info(self, index=0):
        """
        功能描述：
        获取 Bandsteering 信息

        入参：
        index: 指定获取第几个 AP 的配置，默认=0
               当设备有多个 AP 时（如"1,1,1,1"），可以通过 index 指定获取第几个
               例如：index=0 获取第 1 个 AP，index=1 获取第 2 个 AP

        返回值：
        Bandsteering_info:Bandsteering 的所有信息

        示例：
        # 单频合一模式
        {'DualBandEnable': True, 'Enable SSID': True, 'SSID': 'Test_5G_01', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@1234_5G'}

        # 分离模式（index=0）
        {'DualBandEnable': False, '2G_Config': {...}, '5G_Config': {...}}
        """
        index = int(index)
        Bandsteering_info = self.get_all_wifi_config(index=index)
        if Bandsteering_info == 0:
            raise ValueError("--------获取 Bandsteering 信息失败------")
        return Bandsteering_info

    def ubus_get_all_2g_info(self, index=0):
        """
        功能描述：获取 2G WiFi 所有信息；

        入参：
        index: 指定获取第几个 AP 的配置，默认=0

        返回值：
        字典：{'Enable SSID': True, 'SSID': 'SDMC_4D2028', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@123', 'AuthorizationModesSupported': 'None,WPA2-Personal,WPA3-Personal-Transition', 'ChannelEnabled': 'auto', 'Channel': 2, 'ChannelBandwidth': '20/40MHz', 'OperatingMode': 'b,g,n,ax', 'TransmitPower': 100, 'ChannelSupport': 'auto,1,2,3,4,5,6,7,8,9,10,11', 'ModeSupport': ['b', 'b,g', 'b,g,n', 'b,g,n,ax'], 'BandwidthSupport': '20/40MHz,20MHz,40MHz'}

        """
        index = int(index)
        get_2g_info = self.get_all_2g_config(index=index)
        if get_2g_info == 0:
            raise ValueError("--------获取 2.4G 信息失败------")
        return get_2g_info

    def ubus_get_all_5g_info(self, index=0):
        """
        功能描述：获取 5G WiFi 所有信息；

        入参：
        index: 指定获取第几个 AP 的配置，默认=0

        返回值：
        字典：{'Enable SSID': True, 'SSID': 'SDMC_4D2028_5G', 'MaxAllowedAssociations': 32, 'BroadcastSSID': True, 'WMMEnable': True, 'AuthorizationMode': 'WPA2-Personal', 'WPAPreSharedKey': 'Sdmc@123', 'AuthorizationModesSupported': 'None,WPA2-Personal,WPA3-Personal-Transition', 'ChannelEnabled': 'auto', 'Channel': 116, 'ChannelBandwidth': '160MHz', 'OperatingMode': 'a,n,ac,ax', 'TransmitPower': 100, 'ChannelSupport': 'auto,36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,149,153,157,161,165', 'ModeSupport': ['a', 'a,n', 'a,n,ac', 'a,n,ac,ax'], 'BandwidthSupport': '160MHz,20MHz,40MHz,80MHz'}

        """
        index = int(index)
        get_5g_info = self.get_all_5g_config(index=index)
        if get_5g_info == 0:
            raise ValueError("--------获取 5G 信息失败------")
        return get_5g_info

    def get_wifi_dualband_status(self, index=0):
        """
        功能描述：
        获取WiFi双频合一状态，根据传入的index返回对应SSID的状态

        入参：
        index: 指定获取第几个 AP 的配置，默认=0
               当设备有多个 AP 时（如"1,1,1,1"），可以通过 index 指定获取第几个
               例如：index=0 获取第 1 个 AP，index=1 获取第 2 个 AP

        返回值：
        字典：包含 DualBandEnable 状态和对应 index 的 SSID 信息
              {
                  "DualBandEnable": "1" 或 "0" 或 "1,1,1,1",
                  "CurrentIndexStatus": "1" 或 "0"  # 当前 index 对应的双频合一状态
                  "SSIDInfo": {...}  # 对应 index 的 SSID 配置信息
              }

        示例：
        # 单值模式
        {'DualBandEnable': '1', 'CurrentIndexStatus': '1', 'SSIDInfo': {...}}

        # 多值模式（index=1）
        {'DualBandEnable': '1,1,1,1', 'CurrentIndexStatus': '1', 'SSIDInfo': {...}}
        """
        try:
            index = int(index)
            result = {}

            # 获取双频合一状态
            dual_band = self.get_bansteering_value()
            result["DualBandEnable"] = dual_band

            # 处理 DualBandEnable 值
            if isinstance(dual_band, bool):
                dual_band_str = "1" if dual_band else "0"
            else:
                dual_band_str = str(dual_band)

            # 判断当前 index 对应的状态
            if ',' in dual_band_str:
                # 多值模式（如 "1,1,1,1"）
                dual_values = dual_band_str.split(',')
                if 0 <= index < len(dual_values):
                    current_index_status = dual_values[index]
                    result["CurrentIndexStatus"] = current_index_status
                else:
                    log.error(f"index={index} 超出范围 {len(dual_values)}")
                    # result["CurrentIndexStatus"] = None
                    raise ValueError(f"index={index} 超出范围 {len(dual_values)}")
            else:
                # 单值模式（如 "1" 或 "0"）
                result["CurrentIndexStatus"] = dual_band_str

            # 获取对应 index 的 SSID 信息
            mapping_str = self.get_mapping2g_info()
            mapping_path = self.parse_mapping(mapping_str)

            if mapping_path and 0 <= index < len(mapping_path):
                target_path = [mapping_path[index]]
                ssid_info = self.get_ssid_info(target_path)
                result["SSIDInfo"] = ssid_info
            else:
                result["SSIDInfo"] = {}
                raise ValueError(f"获取WiFi双频状态失败: {mapping_path}")

            return result

        except Exception as e:
            log.error(f"获取WiFi双频状态失败: {str(e)}")
            raise ValueError(f"获取WiFi双频状态失败: {str(e)}")

    def trigger_wps_pbc(self, ap_path="Device.WiFi.AccessPoint.1."):
        """
        功能描述：触发wps

        入参：
        ap_path：2.4G或5G的ap路径

        返回值：
        ubus调用返回的接口信息，没有报错就是成功执行
        """
        params = {
            "command": f"{ap_path}WPS.InitiateWPSPBC()",
            "optional": {
                "proto": "web"
            }
        }
        return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)

    def debug_test(self):
        try:
            ubus_base.switch_ubus_service("bbfdm")
            self.ubus.Ubus_Switch(f"http://{self.ip}/ubus/")
            self.ubus.Ubus_Login(self.username, self.password)

            # 触发wps
            mapping5g = self.get_mapping5g_info()
            path = self.parse_mapping(mapping5g)
            ap_path = path[0].get('AccessPointPath')
            print(ap_path)
            ap_path = path[0].get('RadioPath')
            print(ap_path)

            mapping5g = self.get_mapping2g_info()
            path = self.parse_mapping(mapping5g)
            ap_path = path[0].get('AccessPointPath')
            print(ap_path)
            # self.get_all_2g_config()
            # result = self.trigger_wps_pbc(ap_path)
            # print(result)

            # 设置wifi参数
            wifi_config = {
                "DualBandEnable": "0",  # 双频合一

                "2G_SSID": {
                    "SSID": "SDMC_2G123",
                    "Enable": True
                },
                "2G_AP": {
                    "MaxAllowedAssociations": "32",
                    "SSIDAdvertisementEnabled": "1",
                    "WMMEnable": "1",
                    "AuthorizationMode": "WPA2-Personal",
                    "Password": "Sdmc@456"
                },
                "2G_RADIO": {
                    "Channel": "1",
                    "ChannelBandwidth": "20/40MHz",
                    "OperatingMode": "b,g,n,ax",
                    "TransmitPower": "100"
                }

                # "5G_SSID": {
                #     "SSID": "!!!SDMC_5G111",
                #     "Enable": True
                # },
                # "5G_AP": {
                #     "MaxAllowedAssociations": "20",
                #     "SSIDAdvertisementEnabled": "1",
                #     "WMMEnable": "0",
                #     "AuthorizationMode": "WPA2-Personal",
                #     "Password": "Sdmc@1456"
                # },
                # "5G_RADIO": {
                #     "Channel": "auto",
                #     "ChannelBandwidth": "160MHz",
                #     "OperatingMode": "a,n,ac,ax",
                #     "TransmitPower": "100"
                # }
            }

            info = self.ubus_set_bandsteering(0, security_mode="WPA3-Personal-Transition")
            # info = self.ubus_set_2g_wifi(ssid="BE3600-C54023333333333",password="Sdmc@123", channel="1", bandwidth="20MHz", wifi_mode="b,g,n,ax")
            # self.ubus_set_5g_wifi(ssid="BE3600-C540-5G", password="Sdmc@123", channel="36", wifi_mode="a,n,ac,ax,be")
            # info = json.dumps(info, indent=4, ensure_ascii=False)
            # print(info)

            # info = self.ubus_set_5g_wifi(wifi_mode="a,n", bandwidth="40MHz")

            # ubus_base.switch_ubus_service("bbfdm")
            # info = self.ubus_get_all_5g_info()
            # info=self.ubus_get_all_bandsteerding_info(2)
            # self.ubus_set_bandsteering(bandsteering=0, ssid="Test_2G_544", password="Sdmc@1234_2G",index=0)

            self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed: ", str(e))

    def unit_test(self):
        try:
            self.ubus.Ubus_Login(self.username, self.password)

            # 触发wps
            mapping5g = self.get_mapping5g_info()
            path = self.parse_mapping(mapping5g)
            ap_path = path[0].get('AccessPointPath')
            result = self.trigger_wps_pbc(ap_path)
            print("wps result is :", result)

            # 设置wifi参数
            wifi_config = {
                "DualBandEnable": "0",  # 双频合一

                "2G_SSID": {
                    "SSID": "SDMC_2G123",
                    "Enable": True
                },
                "2G_AP": {
                    "MaxAllowedAssociations": "20",
                    "SSIDAdvertisementEnabled": "1",
                    "WMMEnable": "0",
                    "AuthorizationMode": "WPA2-Personal",
                    "Password": "Sdmc@456"
                },
                "2G_RADIO": {
                    "Channel": "6",
                    "ChannelBandwidth": "40MHz",
                    "OperatingMode": "b,g,n,ax",
                    "TransmitPower": "100"
                },

                "5G_SSID": {
                    "SSID": "!!!SDMC_5G111",
                    "Enable": True
                },
                "5G_AP": {
                    "MaxAllowedAssociations": "20",
                    "SSIDAdvertisementEnabled": "1",
                    "WMMEnable": "0",
                    "AuthorizationMode": "WPA2-Personal",
                    "Password": "Sdmc@1456"
                },
                "5G_RADIO": {
                    "Channel": "auto",
                    "ChannelBandwidth": "160MHz",
                    "OperatingMode": "a,n,ac,ax",
                    "TransmitPower": "100"
                }
            }

            # info = self.set_wifi_config(wifi_config)
            info = self.get_all_wifi_config()
            info = json.dumps(info, indent=4, ensure_ascii=False)
            print(info)
            self.ubus.Ubus_Logout()

        except Exception as e:
            print("debug test failed: ", str(e))


if __name__ == '__main__':
    wlan = WlanManager(ip="192.168.1.1", username="sdmc", password="1234")
    wlan.debug_test()

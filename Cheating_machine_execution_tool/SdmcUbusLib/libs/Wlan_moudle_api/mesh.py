import json
import time

from SdmcLog import log
from SdmcOctoBoxLib.DeviceAPI.common import sleep
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class EasyMeshManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()

    def set_easymesh_mode(self,mode,wait_time=30):
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

        ret = ubus_base.ERR_FAIL
        if mode not in ["Disable", "Agent", "Controller"]:
            log.error(f"非法的 EasyMesh 模式: {mode}")
            return ret

        try:
            role_map = {
                "Disable":"0",
                "Agent":"1",
                "Controller":"2"
            }
            role_value = role_map[mode]

            params = {
                "path": f"Device.WiFi.DataElements.Network.{VENDOR_PREFIX}MultiAP_Mode",
                "value": role_value,
                "optional": {"proto": "web"}
            }

            self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", params)

            log.info(f"等待EasyMesh设置成功...{'设置EasyMesh模式 = ' + mode if int(role_value) else '关闭EasyMesh'}")
            time.sleep(wait_time)
            ret = ubus_base.ERR_SUCCESS
            log.info(f"设置EasyMesh模式成功")
        except Exception as e:
            log.exception(f"设置EasyMesh模式失败: {e}")
            raise

        return ret

    def trigger_mesh_wps(self):
        """
        【功能描述】
        触发 EasyMesh WPS 按键组网


        【返回值】
        ERR_SUCCESS / ERR_FAIL

        """
        ret = ubus_base.ERR_FAIL
        try:
            params = {
                "command": f"Device.WiFi.DataElements.Network.{VENDOR_PREFIX}InitiateMultiAPWPSPBC()",
                "optional": {"proto": "web"}
            }
            self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "operate", params)
            log.info("EasyMesh WPS 触发成功")
            ret = ubus_base.ERR_SUCCESS
        except Exception as e:
            log.exception(str(e))
            raise
        return ret

    def get_mesh_topology(self):
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
        try:
            params = {
                "path": f"Device.IEEE1905.{VENDOR_PREFIX}MeshTopo",
                "optional": {"proto": "web"}
            }
            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)

            topo_raw = result[1].get("X_SDMC_MeshTopo", "{}")
            topo = json.loads(topo_raw)

            # output structure
            topology_map = {}
            device_map = {}
            sta_list = []

            def convert_sta_connect_type(ct):
                if ct == 0:
                    return "wired"
                elif ct == 1:
                    return "2.4G"
                elif ct == 2:
                    return "5G"
                return "unknown"

            def convert_agent_connect_type(ct):
                if ct == 0:
                    return "wired"
                elif ct in [1,2]:
                    return "wireless"
                return "unknown"

            def parse_node(node, parent_mac=None):
                dev = node.get("DevInfo", {})
                mac = dev.get("macAddress", "unknown")
                ip = dev.get("ipAddress", "unknown")

                device_map[mac] = ip

                if mac not in topology_map:
                    topology_map[mac] = {}

                for sta in node.get("STAInfo", []):
                    sta["parent_mac"] = mac
                    ct = sta.get("connectType", -1)
                    sta["connectType"] = convert_sta_connect_type(ct)

                    sta_list.append(sta)

                for child in node.get("MeshInfo", []):
                    cdev = child.get("DevInfo", {})
                    child_mac = cdev.get("macAddress", "unknown")

                    ct = cdev.get("connectType", -1)
                    link_type = convert_agent_connect_type(ct)

                    topology_map[mac][child_mac] = link_type
                    parse_node(child, parent_mac=mac)

            parse_node(topo)

            topo_dict = {
                "topology_map": topology_map,
                "device_map": device_map,
                "sta_list": sta_list
            }

            log.info(f"拓扑结果: {topo_dict}")
            return topo_dict

        except Exception as e:
            log.exception(str(e))
            raise

    def get_mesh_status(self):
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
        try:
            params = {
                "path": f"Device.WiFi.DataElements.Network.{VENDOR_PREFIX}MultiAP_Mode"
            }
            result = self.ubus.Ubus_Call(
                ubus_base.UBUS_SERVICE_BBFDM,
                "get",
                params
            )

            # 预期结构:
            # [0, {"X_SDMC_MultiAP_Mode": 2}]

            if not isinstance(result, (list, tuple)) or len(result) < 2:
                return ubus_base.ERR_FAIL, None

            data_dict = result[1]

            if "X_SDMC_MultiAP_Mode" not in data_dict:
                return ubus_base.ERR_FAIL, None

            mode_value = int(data_dict["X_SDMC_MultiAP_Mode"])

            return mode_value

        except Exception as e:
            log.exception(f"获取 Mesh 状态异常: {e}")
            return None

    def debug_test(self):
        try:
            log.info("开始 EasyMesh 调试...")
            ubus_base.switch_ubus_service("bbfdm")
            self.ubus.Ubus_Switch(f"https://{self.ip}/ubus/")
            self.ubus.Ubus_Login(self.username, self.password)

            # 1. 打开 EasyMesh
            # self.set_easymesh_mode("Controller")

            # # 2. 设置组网角色
            # ret=self.set_mesh_role("Agent")
            # print("设置成功" if ret == ubus_base.ERR_SUCCESS else "设置失败")
            # time.sleep(60)
            # ret = self.set_mesh_role("Controller")
            # print("设置成功" if ret == ubus_base.ERR_SUCCESS else "设置失败")

            # 3. 触发 WPS
            # ret=self.trigger_mesh_wps()
            # print("设置成功" if ret == ubus_base.ERR_SUCCESS else "设置失败")
            # time.sleep(1)
            # ret = self.trigger_mesh_wps()
            # print("设置成功" if ret == ubus_base.ERR_SUCCESS else "设置失败")

            # # 4. 获取拓扑
            # topo = self.get_mesh_topology()
            # log.info(f"调试结果 - EasyMesh 拓扑: {topo}")

            # # 5. 获取 Easy Mesh 开关状态
            status = mesh.get_mesh_status()
            if status == 0:
                print("Easy Mesh 关闭")
            elif status in (1, 2):
                print("Easy Mesh 开启")
            else:
                print("未知状态:", status)

            mesh.set_easymesh_mode('Disable')
        except Exception as e:
            log.error(f"debug_test 失败: {str(e)}")

if __name__ == '__main__':
    mesh = EasyMeshManager(ip="192.168.1.1", username="sdmc", password="1234")
    mesh.debug_test()

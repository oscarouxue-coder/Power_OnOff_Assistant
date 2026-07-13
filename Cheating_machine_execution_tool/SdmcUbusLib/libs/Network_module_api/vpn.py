import json
import binascii

from httplib2.auth import params

from SdmcLog import log
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class VpnManager:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ubus = SdmcUbusLibBase()


    #ubus call bbfdm get '{"path":"Device.L2TPv3.Tunnel"}'
    #ubus call bbfdm get '{"path":"Device.DHCPv4.Server.Pool."}'
    # {'Enable': True, 'InterfaceNumberOfEntries': 1, 'Interface': [{'Enable': True, 'Status': 'Down', 'X_SDMC_Username': '', 'X_SDMC_Password': '', 'X_SDMC_Server': ''}]}

    def get_vpn_client(self):
        params = {
            "path": "Device.L2TPv3.Tunnel.",
            "optional": {"proto": "web"}
        }
        params_IP_Interface = {
            "path": "Device.IP.Interface.",
            "optional": {"proto": "web"}
        }

        result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params)
        if len(result) > 1:
            data = result[1].get("Tunnel", [])[0]

            result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "get", params_IP_Interface)
            data_interfaces = result[1]
            target_interface = next(
                (iface for iface in data_interfaces.get('Interface', [])
                 if iface.get(f'{VENDOR_PREFIX}InterfaceType') == 'l2tp'),
                None
            )
            if target_interface:
                status = target_interface.get(f'{VENDOR_PREFIX}Status')
                IPv4Address = target_interface.get('IPv4Address')
                if IPv4Address and IPv4Address[0] and IPv4Address[0]["IPAddress"]:
                    data.get("Interface")[0]["IPv4Address"] = IPv4Address[0]["IPAddress"]
                else:
                    data.get("Interface")[0]["IPv4Address"] = ""

                if data.get("Interface") and data.get("Interface")[0]:
                    data.get("Interface")[0]["Status"] =  status

        else:
            data = {}
        return data

    def set_vpn_client(self, enable=1, username=None, password=None, server=None):
        """
        function:
            开启/关闭vpn
        Args:
            enable: int - 开启或关闭vpn，0：关闭，1：开启，默认为 1
        return:
            返回ubus执行结果
        """

        try:
            if int(enable) == 1:
                enable_vpn = True
            else:
                enable_vpn = False

            orign = self.get_vpn_client()
            if enable_vpn:
                if orign.get("Enable") == None:
                    # no orign vpn client, add new obj
                    add_params = {
                        "paths": [
                            {
                                "addr": "Device.L2TPv3.Tunnel.1.",
                            },
                            {
                                "addr": "Device.L2TPv3.Tunnel.1.Interface.",
                            }
                        ],
                        "optional": {"proto": "web"}
                    }
                    self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "add", add_params)

                params = {
                    "Enable": enable_vpn
                }
                if username:
                    params[f"{VENDOR_PREFIX}Username"] = username

                if password:
                    params[f"{VENDOR_PREFIX}Password"] = password

                if server:
                    params[f"{VENDOR_PREFIX}Server"] = server

                set_params = {
                    "paths": [
                        {
                            "addr": "Device.L2TPv3.Tunnel.1.Interface.1.",
                                "obj_path": params
                        }
                    ]
                }

                result = self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "set", set_params)

            else:
                # del vpn client
                del_params = {
                    "paths": ["Device.L2TPv3.Tunnel.1.Interface.", "Device.L2TPv3.Tunnel."],
                    "optional": {"proto": "web"}
                }
                return self.ubus.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, "del", del_params)

        except Exception as e:
            log.exception(str(e))
            desc = str(e)
            raise Exception(desc)
        return result

    def debug_test(self):
        try:
            if False:
                self.ubus.Ubus_Login(self.username, self.password)
                result = self.get_vpn_client()
                result = json.dumps(result, indent=4, ensure_ascii=False)
                print(result)

                #result = self.set_vpn_client(enable=1, username=self.username, password=self.password, server=self.ip)
                #result = json.dumps(result, indent=4, ensure_ascii=False)
                #print(result)


        except Exception as e:
            print("debug test failed: ", str(e))


if __name__ == '__main__':
    vpn = VpnManager(ip="192.168.29.1", username="root", password="admin1234")
    vpn.debug_test()

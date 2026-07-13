"""
测试库 ubus for OpenWRT

20241205   v1.0
1 新建 基础 接口 API




"""

import telnetlib
import time

from SdmcLog import log

from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase, VENDOR_PREFIX
import SdmcUbusLib.libs.base_moudle_api.ubus_lib_base as ubus_base


class SdmcUbusLibEnableTelnet(SdmcUbusLibBase):
    """
    测试库 demo for class
    """

    ROBOT_LIBRARY_SCOPE = 'GLOBAL'

    def __init__(self):
        """
        """
        SdmcUbusLibBase.__init__(self)

    def _get_exsit_telnet_rule(self):
        try:
            response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'get',
                                      {"path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule."})
            log.info(f'rule_response:{response}')
            if len(response) > 1:
                exsit_rule = response[1]['Rule']
                log.info(f'exsit_rule:{exsit_rule}')
                log.info(type(exsit_rule))
                for i in exsit_rule:
                    log.info(f'进入循环，判断已存在规则是否是telnet：{i}')
                    # if i['Enable'] is True and i['Application'] == 'telnet':
                    if 'telnet' in i['Application']:
                        log.info(f"已找到相关规则，检查规则是否是lan-telnet")
                        if "lan" == i['SourceInterface'] or "both" == i['SourceInterface'] or "Device.IP.Interface.1" == \
                                i['SourceInterface']:
                            log.info(f"已存在lan侧的telnet规则")
                            rule_enbale = i.get("Enable", "None")
                            if rule_enbale != "None":
                                log.info(f"已存在lan侧telnet规则，但已关闭使能")
                                if i['Enable'] == "True":
                                    log.info(f"已存在lan侧telnet规则，且已开启使能")
                                    return 1
                                else:
                                    log.info(f"已存在lan侧telnet规则，但未开启使能，即将开启使能")
                                    response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'set', {
                                        "path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.{i['X_SDMC_Instance']}.",
                                        "obj_path": {"Enable": "1"}})
                                    return 1
                            else:
                                log.info(f"已存在lan-telnet规则，没有Enable使能key，默认已开启使能")
                                return 1
                log.info('已存在的规则没有lan-telnet，需要重新添加')
                return 2
            else:
                log.info(f"未找到相关规则，可以添加 telnet 规则 开启telnet")
                return 2

        except Exception as e:
            log.info(f"添加规则接口调用失败")
            return False

    def _get_SecurityAccessCtrl_enable(self):
        try:
            response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'get',
                                      {"path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Enable"})
            # log.info(f"获取访问规则总开关失败：{response}")
            enable_data = response[1]['Enable']
            return enable_data
        except Exception as e:
            log.error(f"获取访问规则总开关失败：{e}")
            return False

    def _set_SecurityAccessCtrl_enable(self):
        try:
            response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'set',
                                      {"path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.",
                                       "obj_path": {"Enable": "1"}})
            enable_data = response[1]['results'][0]['data']
            if enable_data == '1':
                log.info('开启telnet：set_SecurityAccessCtrl_enable 成功')
                return True
            else:
                log.error(f"开启telnet：set_SecurityAccessCtrl_enable 失败：enable_data：{enable_data}")
                return False
        except Exception as e:
            log.error(f"开启telnet：set_SecurityAccessCtrl_enable 失败：{e}")
            return False

    def _add_SecurityAccessCtrlRule(self):
        try:
            response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'add',
                                      {"path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.",
                                       "obj_path": {"SourceInterface": "Device.IP.Interface.1",
                                                    "IPVersion": 4,
                                                    "SourceIP": "0.0.0.0", "Application": "telnet"}})
            # log.info(response)
            SourceInterface_rule_data = response[1]['results'][0]['data']
            SourceIP_rule_data = response[1]['results'][1]['data']
            Application_rule_data = response[1]['results'][2]['data']
            if SourceInterface_rule_data == "1" and SourceIP_rule_data == "1" and Application_rule_data == "1":
                log.info('开启telnet：add_SecurityAccessCtrl_enable 成功')
                return True
            else:
                log.error(
                    f"开启telnet ： add_SecurityAccessCtrlRule 失败: SourceInterface_rule_data：{SourceInterface_rule_data}，SourceIP_rule_data：{SourceIP_rule_data},Application_rule_data:{Application_rule_data}")
                return False
        except:
            try:
                response = self.Ubus_Call(ubus_base.UBUS_SERVICE_BBFDM, 'add',
                                          {"path": f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl.Rule.",
                                           "obj_path": {"SourceInterface": "lan",
                                                        "IPVersion": 4,
                                                        "SourceIP": "0.0.0.0", "Application": "telnet"}})
                log.info(response)
                SourceInterface_rule_data = response[1]['results'][0]['data']
                SourceIP_rule_data = response[1]['results'][1]['data']
                Application_rule_data = response[1]['results'][2]['data']
                if SourceInterface_rule_data == "1" and SourceIP_rule_data == "1" and Application_rule_data == "1":
                    log.info('开启telnet：add_SecurityAccessCtrl_enable 成功')
                    return True
                else:
                    log.error(
                        f"开启telnet ： add_SecurityAccessCtrlRule 失败: SourceInterface_rule_data：{SourceInterface_rule_data}，SourceIP_rule_data：{SourceIP_rule_data},Application_rule_data:{Application_rule_data}")
                    return False
            except Exception as e:
                log.error(f"开启telnet ： add_SecurityAccessCtrlRule 失败: {e}")
                return False

    def Enable_telnet(self):
        """
        功能描述： 开启OpenWrt telnet
        Returns: 成功返回True，失败返回False
        -------

        """
        get_acl_enable = self._get_SecurityAccessCtrl_enable()
        time.sleep(2)
        log.info(f"总开关使能：{get_acl_enable}")
        if get_acl_enable:
            log.info("访问规则总开关已经开启。")
        else:
            log.info("访问规则总开关未开启，需开启使能。")
            self._set_SecurityAccessCtrl_enable()
        getrule = self._get_exsit_telnet_rule()
        if getrule == 2:
            if self._add_SecurityAccessCtrlRule():
                return True
            else:
                return False
        elif getrule == 1:
            return True
        else:
            return False

    def telnet_run_cmd(self, host, username, password, cmd):
        try:
            # 开启telnet
            self.Enable_telnet()

            tn = telnetlib.Telnet(host, timeout=10)

            # 登录
            tn.read_until(b"login: ")
            tn.write(username.encode('utf-8') + b"\n")

            # 输入密码
            tn.read_until(b"Password: ")
            tn.write(password.encode('utf-8') + b"\n")

            # 等待提示符，一般是 $ 或 #
            idx, match, text = tn.expect([b"\$", b"#"], timeout=5)
            if idx == -1:
                print("登录失败或没有正确的命令提示符")
                return None

            # 发送命令
            tn.write(cmd.encode('utf-8') + b"\n")

            # 读取返回内容，直到再次出现命令提示符结束
            # 注意要用一个超时时间，防止一直等待
            output = tn.read_until(b"\n", timeout=1)  # 先读一行，清理缓冲
            result = b""
            while True:
                line = tn.read_until(b"\n", timeout=1)
                if not line:
                    break
                result += line
                # 这里判断是否遇到命令提示符结尾，可以根据你的设备改写条件
                if line.strip().endswith(b"$") or line.strip().endswith(b"#"):
                    break

            tn.close()
            return result.decode('utf-8', errors='ignore')

        except Exception as e:
            print("Telnet执行出错:", e)
            return None


if __name__ == "__main__":
    ip = SdmcUbusLibEnableTelnet()
    ubus_base.switch_ubus_service("bbfdm")
    # ip.get_exsit_telnet_rule()
    ip.Ubus_Switch(f"http://{'192.168.1.1'}/ubus/")
    ip.Ubus_Login("sdmc", "1234")
    ip.Enable_telnet()

    # ipubus.Ubus_Login(self.username, self.password)

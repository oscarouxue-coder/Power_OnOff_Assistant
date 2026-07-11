import re

from PyQt5.QtCore import QThread, pyqtSignal


class OpenWrtGetWifiInfo(QThread):
    show_signal = pyqtSignal(str)
    show_signal_error = pyqtSignal(str)

    def __init__(self, client):
        super(OpenWrtGetWifiInfo, self).__init__()
        self.client = client

    def get_wifi_2g_ssid(self):
        try:
            result = self.client.execute_read_until('bbfdmd -c get Device.WiFi.SSID.1.SSID')
            match = re.search(r"=>\s*(.*)", result)
            print(f"match_result:{match.group(1)}")
            result = match.group(1).strip()
            print(f"match_result:{result}")
            return result
        except Exception as e:
            desc = f"未匹配到2g ssid：{e}"
            raise Exception(desc)

    def get_wifi_2g_password(self):
        try:
            result = self.client.execute_read_until('bbfdmd -c get Device.WiFi.AccessPoint.1.Security.X_SDMC_Key')
            match = re.search(r"=>\s*(.*)", result)
            print(f"match_result:{match.group(1)}")
            result = match.group(1).strip()
            print(f"match_result:{result}")
            return result
        except Exception as e:
            desc = f"未匹配到2g password：{e}"
            raise Exception(desc)

    def get_wifi_5g_ssid(self):
        try:
            result = self.client.execute_read_until('bbfdmd -c get Device.WiFi.SSID.4.SSID')
            match = re.search(r"=>\s*(.*)", result)
            result = match.group(1).strip()
            print(f"match_result:{result}")
            return result
        except Exception as e:
            desc = f"未匹配到5g ssid：{e}"
            raise Exception(desc)

    def get_wifi_5g_password(self):
        """

        :param er:
        :return:
        """
        try:
            result = self.client.execute_read_until('bbfdmd -c get Device.WiFi.AccessPoint.3.Security.X_SDMC_Key')
            match = re.search(r"=>\s*(.*)", result)
            result = match.group(1).strip()
            print(f"match_result:{result}")
            return result
        except Exception as e:
            desc = f"未匹配到2g password：{e}"
            raise Exception(desc)

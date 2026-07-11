import time

# hostname = socket.gethostname()
# sysinfo = socket.gethostbyname_ex(hostname)
# ip_addr = sysinfo[2]
# self.logger.info(hostname)
# self.logger.info(ip_addr)
# self.logger.info(sysinfo)
import subprocess
from common.my_logging import creat_logger
import psutil


# import netifaces


class GetNetworkCardInfo():
    def __init__(self, logger):
        self.logger = logger

    def get_wireless_card_info(self):
        result = subprocess.Popen('netsh wlan show interfaces', shell=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        # self.logger.info(result.stdout.readlines())
        results = result.stdout.readlines()
        # self.logger.info(type(results))
        list1 = []
        for i in results:
            if '名称' in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if '描述' in i.decode('GBK', 'ignore') and '本机' not in i.decode('GBK',
                                                                              'ignore') and '支持' not in i.decode(
                'GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if 'SSID' in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if "无线电类型" in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if '身份验证' in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if '信道' in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if '接收速率' in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
            if '传输速率' in i.decode('GBK', 'ignore') and 'BSSID' not in i.decode('GBK', 'ignore'):
                a = i.decode('GBK', 'ignore').split('\r\n')[0].split(': ')[1]
                list1.append(a)
        # self.logger.info(i.decode('GBK', 'ignore'))

        self.logger.info(list1)
        print(list1)
        list2 = self.split_list(list1, len(list1) // 8)
        print(list2)
        return list2

    def split_list(self, lst, n):
        k, m = divmod(len(lst), n)
        return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

    def match_network_card_name(self, lst, api_name):
        """
        根据网卡的描述名称，获取到网卡的名称
        :param lst: 无线网卡列表
        :param api_name:
        :return:
        """
        for i in lst:
            if i[1] == api_name:
                self.logger.info(i[0])
                return i[0]

    # 获取网卡名称和其ip地址，不包括回环
    def get_network_cards_ip(self):
        """
        获取多个网卡IP和名称
        :return:
        """
        network_card_info = []
        info = psutil.net_if_addrs()
        # self.logger.info(info)
        for k, v in info.items():
            for item in v:
                if item[0] == 2 and not item[1] == '127.0.0.1':
                    network_card_info.append((k, item[1]))
        if len(network_card_info) < 2:
            return False
        self.logger.info(network_card_info)
        return network_card_info

    def get_network_card_ip(self, network_card_name):
        """
        获取指定网卡IP
        :return:
        """
        network_card_name_list = self.get_wireless_card_info()
        network_card_name = self.match_network_card_name(network_card_name_list,
                                                         network_card_name)
        match_wlan = self.get_network_cards_ip()
        try:
            for i in match_wlan:
                if network_card_name == i[0]:
                    network_card_ip = i[1]

        except:
            return False
        else:
            if '169.254' in network_card_ip:
                self.logger.error(f'{network_card_name}的IP为：{network_card_ip}')
                return False
            else:
                return network_card_ip

    def get_wlan_ip(self):
        value = self.get_network_cards_ip()
        for i in value:
            if 'WLAN' in i[0] or 'wlan' in i[0]:
                print(i[1])
                if '169.254' in i[1]:
                    return False
                else:
                    return i[1]

if __name__ == '__main__':
    logger = creat_logger('test')
    get = GetNetworkCardInfo(logger)
    get.get_wireless_card_info()
    get.get_wlan_ip()
    time.sleep(10)

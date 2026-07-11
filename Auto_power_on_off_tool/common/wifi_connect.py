# coding: utf-8
import socket
import subprocess
import threading
import time

import pywifi
from pywifi import const
from config.config_driver import OperationConfig
from common.my_logging import creat_logger


class WifiConnect():
    # Define interface status.
    IFACE_DISCONNECTED = 0
    IFACE_SCANNING = 1
    IFACE_INACTIVE = 2
    IFACE_CONNECTING = 3
    IFACE_CONNECTED = 4

    # Define auth algorithms.
    AUTH_ALG_OPEN = 0
    AUTH_ALG_SHARED = 1

    # Define auth key mgmt types.
    AKM_TYPE_NONE = 0
    AKM_TYPE_WPA = 1
    AKM_TYPE_WPAPSK = 2
    AKM_TYPE_WPA2 = 3
    AKM_TYPE_WPA2PSK = 4
    AKM_TYPE_UNKNOWN = 5
    AKM_TYPE_WPA3SAE = 6

    # Define ciphers.
    CIPHER_TYPE_NONE = 0
    CIPHER_TYPE_WEP = 1
    CIPHER_TYPE_TKIP = 2
    CIPHER_TYPE_CCMP = 3
    CIPHER_TYPE_UNKNOWN = 4

    KEY_TYPE_NETWORKKEY = 0
    KEY_TYPE_PASSPHRASE = 1
    wifi_lock = threading.Lock()

    def __init__(self, logger):
        self.logger = logger
        self.wifi = pywifi.PyWiFi()
        self.config = OperationConfig()
        self.iface = self.wifi.interfaces()
        # 新增线程锁

    def wifi_connect_status(self):
        """
        判断本机是否有无线网卡,以及连接状态
        :return: 已连接或存在无线网卡返回1,否则返回0
        """
        # 判断是否连接成功
        if self.iface.status() in [const.IFACE_CONNECTED, const.IFACE_INACTIVE]:
            self.logger.info('wifi connected')
            return True
        else:
            self.logger.info('wifi ununited')
        return False

    def scan_wifi(self, ssid, iface_name):
        """
        扫描WiFi信息
        :param ssid: ssid 为空时，扫描附近ssid，ssid不为空时，扫描指定ssid
        :return:
        """
        times = 0
        for i in self.iface:
            print(i.name())
            if iface_name in i.name():
                iface = i
        while True:
            if ssid:
                # 扫苗附件wifi，并判断是否扫描到2.4G和5G SSID
                time.sleep(0.1)
                self.logger.info('>>>>>正在扫描的ssid是：{}'.format(ssid))
                time.sleep(0.1)
                iface.scan()  # 扫苗附件wifi
                # scan_results() 会打印扫描到的WiFi ，现在手动屏蔽了代码
                base_wifi = iface.scan_results()
                ssid_list = []
                for i in base_wifi:
                    # self.logger.info('wifi扫苗结果:{}'.format(i.bssid))  # ssid 为wifi名称
                    if len(i.ssid) > 0:
                        if i.ssid not in ssid_list:
                            ssid_list.append(i.ssid)
                flag = 0
                if flag:
                    self.logger.info(f'扫描到了ssid:{ssid}')
                    return True
                else:
                    times += 1
                    # sleep_time = random.randint(0, 10)
                    self.logger.error(f'没有扫描到ssid:{ssid}等待10s，再尝试一次！')
                    time.sleep(10)
                    if times > 3:
                        self.logger.error(f'扫描{times}都没有扫描到ssid:{ssid},请检查WiFi是否存在！')
                        return False
                    else:
                        continue

    def connect_wifi(self, ssid, password='', network_card_name='', psk='WPA2-PSK', cipher='AES',
                     check_auto_conn_flag=0):
        if network_card_name == 'All':
            self.logger.info('使用所有无线网卡连接')
            time.sleep(0.1)
            iface = self.wifi.interfaces()
            k = 0
            while True:
                iface_ = iface[k]
                self.connect_wifi_thread(iface_, ssid, password, psk, cipher, check_auto_conn_flag)
                if k == len(iface):
                    break
                print(1231231231231231232123123)
                k += 1

        elif network_card_name == '':
            self.logger.info('未指定网卡，使用第一个无线网卡连接')
            time.sleep(0.1)
            iface = self.wifi.interfaces()[0]
            print(iface)
            connect_result = self.connect_wifi_t(iface, ssid, password, psk, cipher, check_auto_conn_flag)
            if connect_result:
                return True
            else:
                return False

        else:
            self.logger.info('使用指定的无线网卡连接')
            time.sleep(0.1)
            iface = self.wifi.interfaces()
            for i in iface:
                if network_card_name in i.name():
                    connect_result = self.connect_wifi_t(i, ssid, password, psk, cipher, check_auto_conn_flag)
                    if connect_result:
                        return True
                    else:
                        return False

    def connect_wifi_thread(self, iface, ssid, password, psk, cipher, check_auto_conn_flag):
        t1 = threading.Thread(target=self.connect_wifi_t,
                              args=[iface, ssid, password, psk, cipher, check_auto_conn_flag])
        t1.setDaemon(True)
        t1.start()

    def connect_wifi_t(self, iface, ssid, password, psk="WPA2-PSK", cipher='AES', check_auto_conn_flag=0):
        # 使用线程锁确保同一时间只有一个线程可以操作网卡连接
        with self.wifi_lock:
            self.logger.info(f"线程 {threading.current_thread().name} 获取到锁，开始连接WiFi")
            # 取第一个无线网卡

            # 确保接口已开启
            if iface.status() in [const.IFACE_DISCONNECTED, const.IFACE_INACTIVE]:
                iface.disconnect()
                time.sleep(1)
                iface.scan()  # 触发接口激活s

            iface.disconnect()  # 断开网卡连接
            time.sleep(1)  # 缓冲1秒
            profile = pywifi.Profile()
            if password == '':
                # 配置文件
                profile.ssid = ssid  # wifi名称
            else:
                # 注意加密方式对应的akm和cipher是不一样的
                # self.logger.info('准备连接的SSID是：{}'.format(ssid))
                if psk == "WPA-PSK":
                    if cipher == 'TKIP':
                        profile.cipher = const.CIPHER_TYPE_TKIP
                    elif cipher == 'AES' or cipher == 'TKIP+AES':
                        profile.cipher = const.CIPHER_TYPE_CCMP
                    profile.akm.append(const.AKM_TYPE_WPAPSK)
                elif psk == 'WPA2-PSK' or psk == 'WPA-PSK/WPA2PSK' or psk == 'WPA2-PSK/WPA3-PSK':
                    if cipher == 'TKIP':
                        profile.cipher = const.CIPHER_TYPE_TKIP

                    elif cipher == 'AES' or cipher == 'TKIP+AES':
                        # wpa2-psk 对应的加密单元是CIPHER_TYPE_CCMP
                        profile.cipher = const.CIPHER_TYPE_CCMP
                        # wifi的加密算法
                    # wifi的加密算法
                    profile.akm.append(const.AKM_TYPE_WPA2PSK)
                elif psk == 'WPA3-PSK':
                    profile.cipher = const.CIPHER_TYPE_CCMP
                    profile.akm.append(const.AKM_TYPE_WPA3SAE)
                profile.ssid = ssid  # wifi名称
                profile.auth = const.AUTH_ALG_OPEN  # 需要密码
                profile.key = password  # wifi密码
            iface.remove_all_network_profiles()  # 删除其他配置文件
            # tmp_profile = iface.add_network_profile(profile)
            times = 0
            connect_flag = 0
            while True:
                # 加载配置文件
                tmp_profile = iface.add_network_profile(profile)
                iface.connect(tmp_profile)  # 连接
                self.logger.info(f'网卡:{iface.name()} 正在连接{ssid}，等待20s.......')
                # time.sleep(10)  # 尝试10秒能否成功连接
                count = 0
                while True:
                    if iface.status() == const.IFACE_CONNECTED:
                        connect_flag = 1
                        break
                    else:
                        count += 1
                        if count > 20:
                            break
                        time.sleep(1)

                if connect_flag:
                    self.logger.info(f"网卡：{iface.name()} 连接成功")
                    time.sleep(0.2)
                    if check_auto_conn_flag:
                        self.logger.info('勾选自动连接')
                        subprocess.Popen(
                            'Netsh WLAN set profileparameter name="{}" connectionmode=auto'.format(ssid),
                            shell=True)
                    return True

                else:
                    self.logger.info(f"网卡：{iface.name()} 连接失败，重新尝试连接")
                    # 增加连接失败后，删除网卡profile操作
                    iface.disconnect()
                    iface.remove_all_network_profiles()
                    if times == 3:
                        self.logger.error(
                            f"网卡：{iface.name()} 连接{ssid}，尝试{times}次都失败，不再尝试连接，请确认WiFi信息和加密方式是否准确！")
                        iface.remove_all_network_profiles()
                        return False
                    times += 1
                    time.sleep(10)

    def get_network_cards_name(self):
        iface_name = []
        for i in self.wifi.interfaces():
            iface_name.append(i.name())
        return iface_name

    def check_wifi_status(self):
        iface = self.wifi.interfaces()
        for i in iface:
            if i.status() == const.IFACE_CONNECTED:
                self.logger.info(f"{i.name()}网卡 连接正常")
            else:
                self.logger.error(f'{i.name()}网卡 连接异常，请点击"连接wifi"重新连接！')
                # self.connect_wifi(ssid, password, network_card_name, psk, cipher, check_auto_conn_flag)


if __name__ == "__main__":
    logger = creat_logger('aaaaa')
    wifi = WifiConnect(logger)
    wifi.connect_wifi('AN7552_MESH_2G_bb4906', '1234567890')
    # wifi.scan_wifi('GPON_4A36_2.4G',"Intel(R) Wi-Fi 7 BE200 320MHz")

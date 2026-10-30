# coding: utf-8
import socket
from contextlib import contextmanager
import subprocess
import threading
import time

import pywifi
from pywifi import const
from config.config_driver import OperationConfig
from common.my_logging import creat_logger


class WifiConnectionCancelled(Exception):
    """用户取消 WiFi 测试，不是设备连接失败。"""


def check_wifi_stop(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise WifiConnectionCancelled("用户已停止 WiFi 测试")


def wait_wifi(seconds, stop_event):
    check_wifi_stop(stop_event)
    if stop_event is None:
        time.sleep(seconds)
    elif stop_event.wait(seconds):
        raise WifiConnectionCancelled("用户已停止 WiFi 测试")
    check_wifi_stop(stop_event)


@contextmanager
def wifi_lock_with_stop(lock, stop_event):
    acquired = False
    try:
        while not acquired:
            check_wifi_stop(stop_event)
            acquired = lock.acquire(timeout=0.2)
        check_wifi_stop(stop_event)
        yield
    finally:
        if acquired:
            lock.release()


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
                     check_auto_conn_flag=0, *, stop_event=None, on_log=None):
        check_wifi_stop(stop_event)
        emit = on_log or self.logger.info
        wait_wifi(0.1, stop_event)
        try:
            interfaces = self.wifi.interfaces()
            check_wifi_stop(stop_event)
            if network_card_name == 'All':
                # 兼容旧工具入口；正式测试只允许一张选定网卡。
                for iface in interfaces:
                    self.connect_wifi_thread(iface, ssid, password, psk, cipher,
                                             check_auto_conn_flag, stop_event=stop_event,
                                             on_log=on_log)
                return None
            if not network_card_name:
                iface = interfaces[0]
            else:
                iface = next((item for item in interfaces if network_card_name in item.name()), None)
                if iface is None:
                    emit('失败：指定无线网卡不可用')
                    return False
            emit(f'实际网卡={iface.name()}，目标SSID={ssid}')
            return self.connect_wifi_t(iface, ssid, password, psk, cipher,
                                       check_auto_conn_flag, stop_event=stop_event, on_log=on_log)
        except WifiConnectionCancelled:
            raise
        except Exception as exc:
            check_wifi_stop(stop_event)
            if on_log is not None:
                # 驱动异常可能包含 profile/密码；主程序只记录异常类型。
                raise RuntimeError(f'WiFi网卡操作异常：{type(exc).__name__}') from None
            raise

    def connect_wifi_thread(self, iface, ssid, password, psk, cipher, check_auto_conn_flag,
                            *, stop_event=None, on_log=None):
        t1 = threading.Thread(target=self.connect_wifi_t,
                              args=[iface, ssid, password, psk, cipher, check_auto_conn_flag],
                              kwargs=dict(stop_event=stop_event, on_log=on_log))
        t1.setDaemon(True)
        t1.start()

    def connect_wifi_t(self, iface, ssid, password, psk="WPA2-PSK", cipher='AES', check_auto_conn_flag=0,
                       *, stop_event=None, on_log=None):
        emit = on_log or self.logger.info

        def action(description, function, *args):
            check_wifi_stop(stop_event)
            emit(description)
            check_wifi_stop(stop_event)
            result = function(*args)
            check_wifi_stop(stop_event)
            return result

        with wifi_lock_with_stop(self.wifi_lock, stop_event):
            check_wifi_stop(stop_event)
            state = iface.status()
            check_wifi_stop(stop_event)
            if state in [const.IFACE_DISCONNECTED, const.IFACE_INACTIVE]:
                action('下发断开连接（激活接口前）', iface.disconnect)
                wait_wifi(1, stop_event)
                action('下发扫描（激活接口）', iface.scan)
            action('下发断开原连接', iface.disconnect)
            wait_wifi(1, stop_event)
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
            action('清理网卡连接配置', iface.remove_all_network_profiles)
            for attempt in range(1, 5):
                check_wifi_stop(stop_event)
                emit(f'第 {attempt}/4 次连接，等待约20秒')
                tmp_profile = action('下发目标WiFi配置（密码隐藏）', iface.add_network_profile, profile)
                action('下发连接目标SSID', iface.connect, tmp_profile)
                connected = False
                for poll in range(101):
                    check_wifi_stop(stop_event)
                    state = iface.status()
                    check_wifi_stop(stop_event)
                    if state == const.IFACE_CONNECTED:
                        connected = True
                        break
                    if poll < 100:
                        wait_wifi(0.2, stop_event)
                if connected:
                    wait_wifi(0.2, stop_event)
                    if check_auto_conn_flag:
                        action('下发自动连接设置', subprocess.Popen,
                               ['netsh', 'wlan', 'set', 'profileparameter',
                                f'name={ssid}', 'connectionmode=auto'])
                    check_wifi_stop(stop_event)
                    emit(f'第 {attempt}/4 次连接成功')
                    return True
                action('本次未连接，断开并清理配置', iface.disconnect)
                action('清理失败连接配置', iface.remove_all_network_profiles)
                if attempt == 4:
                    emit('失败：第 4/4 次连接仍未成功，不再重试')
                    return False
                emit(f'第 {attempt}/4 次未连接，等待10秒后重试')
                wait_wifi(10, stop_event)

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

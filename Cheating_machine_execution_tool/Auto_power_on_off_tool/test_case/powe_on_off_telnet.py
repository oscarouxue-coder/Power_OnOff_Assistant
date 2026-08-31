import datetime
import os
import random
import re
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

from common.fuzzy_match import Fuzzy_Match

from common.power_on_off import PowerOnOff
from common.execute_network_card_ping import Cmd
from clients.telnet_client import TelnetClient
from common.send_email import SendEmail
from common.web_page_open_telnet import Web_Page_Open_Telnet
from config.config_driver import OperationConfig
from common.new_write_funs import TimestampedFile
from common.dingtalk_send_message import DingTalk
from test_case.wifi_connect_case import OpenWrtGetWifiInfo
from common.wifi_connect import WifiConnect
from test_case.Onu_config import OnuCongfig

# 8.31号
lock = threading.Lock()


class PowerOnOffTelnet(QThread):
    run_status_signal = pyqtSignal(list)
    ping_status_signal = pyqtSignal(list)
    pcie_status_signal = pyqtSignal(list)
    normal_status_signal = pyqtSignal(list)

    wifi_status_signal = pyqtSignal(list)
    eth_status_signal = pyqtSignal(list)
    voip_status_signal = pyqtSignal(list)
    wan_status_signal = pyqtSignal(list)
    pon_status_signal = pyqtSignal(list)
    telnet_status_signal = pyqtSignal(list)
    web_status_signal = pyqtSignal(list)
    command_status_signal = pyqtSignal(list)

    show_signal = pyqtSignal(str)
    show_signal_error = pyqtSignal(str)
    # 重试多次之后指令才执行成功
    show_signal_warning = pyqtSignal(str)

    # 各个通道运行标志
    all_channel_flag = 1
    channel_1_flag = 1
    channel_2_flag = 1
    channel_3_flag = 1
    channel_4_flag = 1
    channel_5_flag = 1
    channel_6_flag = 1
    channel_7_flag = 1
    channel_8_flag = 1
    channel_9_flag = 1
    channel_10_flag = 1
    channel_11_flag = 1
    channel_12_flag = 1
    channel_13_flag = 1
    channel_14_flag = 1
    channel_15_flag = 1
    channel_16_flag = 1

    def __init__(self, ser, logger, startup_time, interval_time, wait_command_done, test_number, config_file_path='',
                 recv_email=[],
                 telnet_enable_flag=0, device_type=''):
        super(PowerOnOffTelnet, self).__init__()

        self.cf = OperationConfig()
        # self.ip_list=get_local_ip()
        self.logger = logger
        self.ser = ser
        self.startup_time = int(startup_time)
        self.interval_time = int(interval_time)
        self.telnet_enable_fail_retry_interval = 10
        self.logger.info(f"间隔时间 {self.interval_time} {telnet_enable_flag}")
        self.test_number = int(test_number)
        self.wait_command_done = int(wait_command_done)
        self.username = ''
        self.password = ''
        self.url = ''
        self.port = 0
        self.only_power_off_on = 0
        self.connect_wifi_enable = 0
        # 产品方案类型
        self.product_solution = ''
        self.onu_ciper = ''
        self.onu_auth_mode = ''

        # 把页面选择的配置传进来做处理 9.7
        self.config_file_path = config_file_path
        self.send_email = SendEmail(self.logger)
        self.recv_email = recv_email
        self.telnet_enable_flag = telnet_enable_flag
        self.device_type = device_type

        self.power_control = PowerOnOff(self.logger)
        # self.ser = Serial(self.serial_num, self.baud_rate, self.logger)
        self.cmd_ping = Cmd(self.logger)
        self.power_control.power_all_off(self.ser)
        self.wifi_connect = WifiConnect(self.logger)

        # 各个通道运行标志
        # self.all_channel_flag = 1
        # self.channel_1_flag = 1
        # self.channel_2_flag = 1
        # self.channel_3_flag = 1
        # self.channel_4_flag = 1
        # self.channel_5_flag = 1
        # self.channel_6_flag = 1
        # self.channel_7_flag = 1
        # self.channel_8_flag = 1
        # self.channel_9_flag = 1
        # self.channel_10_flag = 1
        # self.channel_11_flag = 1
        # self.channel_12_flag = 1
        # self.channel_13_flag = 1
        # self.channel_14_flag = 1
        # self.channel_15_flag = 1
        # self.channel_16_flag = 1

        self.flag = 1

        self.network_card_err = 0
        # 状态值
        # 运行状态
        self.run_status_list = [0] * 17
        self.run_status_list.append("run")
        # ping的状态
        self.ping_status_list = [0] * 17
        self.ping_status_list.append('ping')
        # PCIE报错
        self.pcie_status_list = [0] * 17
        self.pcie_status_list.append('pcie')
        # 正常状态
        self.normal_status_list = [0] * 17
        self.normal_status_list.append('normal')

        # 2.4G/5G error
        self.wifi_status_list = [0] * 17
        self.wifi_status_list.append('wifi')

        # eth error  lan口
        self.eth_status_list = [0] * 17
        self.eth_status_list.append('eth')

        # voip error
        self.voip_status_list = [0] * 17
        self.voip_status_list.append('voip')

        # wan error wan口
        self.wan_status_list = [0] * 17
        self.wan_status_list.append('wan')

        # pon error wan口
        self.pon_status_list = [0] * 17
        self.pon_status_list.append('pon')

        # telnet error
        self.telnet_status_list = [0] * 17
        self.telnet_status_list.append('telnet')

        # web open telnet error
        self.web_status_list = [0] * 17
        self.web_status_list.append('web')

        # command_error
        self.command_status_list = [0] * 17
        self.command_status_list.append('command')

        # 参数列表
        args_list = [['', '', ''] * 16]

        # 创建设备日志文件夹  8.25
        self.timestamp = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
        file_path = f'test_results/'
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        self.results_filename = file_path + 'test_result_error_collection' + '.log'
        # self.cpu_memory_monitor_filename = file_path + portx + '_cpu_memory_monitor' + '.log'
        # 实时写入文件,buffering=0
        # self.results_file = open(self.results_filename, 'wb', buffering=0)

        self.run_flag = 0
        # 检测 提取WAN口 ubus指令数据
        self.pattern = re.compile(r' (\d+)')

        # NME5410
        self.mac_data = ''

        # 钉钉发送群消息

        self.dingtalk = DingTalk()

        self._stop_event = threading.Event()
        self._stop_requested = False

    def request_stop(self):
        """请求线程停止"""
        self._stop_requested = True
        self._stop_event.set()
        # 停止所有通道
        for i in range(1, 17):
            self.set_run_flag_0(i)

    def is_stop_requested(self):
        """检查是否请求停止"""
        return self._stop_requested

    def sleep_with_stop_check(self, timeout):
        """
        可中断的睡眠函数
        :param timeout: 睡眠时间(秒)
        :return: True如果被中断, False如果正常完成睡眠
        """
        return self._stop_event.wait(timeout)

    def __del__(self):
        # self.ser.serial_close()
        pass

    # 8.31
    def write_to_file(self, log_info):
        lock.acquire()
        now_time = time.strftime('%Y_%m_%d_%H:%M:%S', time.localtime(time.time()))
        try:
            log_info = (now_time + log_info + '\n').encode()
            with open(self.results_filename, 'wb', buffering=0) as f:
                f.write(log_info)
                # time.sleep(0.5)
        finally:
            lock.release()

    def create_command_exec_result_file(self, device_num):
        self.timestamp = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
        file_path = f'test_results/device_{device_num}'
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        results_log = file_path + '/' + f'device_{device_num}_command_results_' + self.timestamp + '.log'
        return results_log

    def reset_status(self, num):
        self.run_status_list[num] = 0
        self.ping_status_list[num] = 0
        self.pcie_status_list[num] = 0
        self.normal_status_list[num] = 0
        self.wifi_status_list[num] = 0
        self.eth_status_list[num] = 0
        self.voip_status_list[num] = 0
        self.wan_status_list[num] = 0
        self.pon_status_list[num] = 0
        self.telnet_status_list[num] = 0
        self.command_status_list[num] = 0
        self.web_status_list[num] = 0

    def selected_scheme_path(self):
        """
        从config文件里面读取数据
        :return:
        """
        # self.config_file_path = path
        flag = 0
        try:

            self.username = self.cf.read_ini('telnet', 'user',
                                             path='./config/' + self.config_file_path).strip()
            self.password = self.cf.read_ini_raw('telnet', 'password',
                                                 path='./config/' + self.config_file_path).strip()
            self.url = self.cf.read_ini('telnet', 'request_url',
                                        path='./config/' + self.config_file_path).strip()
            self.port = int(self.cf.read_ini('telnet', 'port',
                                             path='./config/' + self.config_file_path).strip())
            self.only_power_off_on = int(self.cf.read_ini('telnet', 'only_power_off_on',
                                                          path='./config/' + self.config_file_path).strip())

            flag = 1
            # 指令集执行次数
            self.commands_loop_times = int(
                self.cf.read_ini('other_config', 'commands_execute_times', './config/config.ini'))
            self.retry_times = int(
                self.cf.read_ini('other_config', 'telnet_enable_fail_retry_times', './config/config.ini'))
            self.telnet_enable_fail_retry_interval = int(
                self.cf.read_ini('other_config', 'telnet_enable_fail_retry_interval', './config/config.ini'))

            self.logger.info(f'{self.url},{self.password},{self.username}')
        except Exception as e:
            if flag == 0:
                self.logger.error(f'读取{self.config_file_path}信息出现异常：{e}')
                return f'读取{self.config_file_path}信息出现异常：{e}'
            else:
                self.logger.error(f'读取{"config.ini"}信息出现异常：{e}')
                return f'读取{"config.ini"}信息出现异常：{e}'
        else:
            self.logger.info(self.password)
            return True

    def get_wifi_info(self, power_num, tel):
        """
        获取设备的 WiFi ssid/password
        :param power_num: 设备序号
        :param tel: 通讯client
        :return:ssid_2g, password_2g, ssid_5g, password_5g

        """
        try:
            # 在此对设备型号进行判断，进而选择使用那一个方案的类
            if self.product_solution == 'openwrt':
                wifi_info = OpenWrtGetWifiInfo(tel)
            ssid_2g = wifi_info.get_wifi_2g_ssid()
            password_2g = wifi_info.get_wifi_2g_password()
            ssid_5g = wifi_info.get_wifi_5g_ssid()
            password_5g = wifi_info.get_wifi_5g_password()
            return ssid_2g, password_2g, ssid_5g, password_5g
        except Exception as e:
            self.logger.error(f'通道 {power_num} 获取 WiFi ssid和password 失败：{e}')
            self.show_signal_error[str].emit(f'通道 {power_num} 获取 WiFi ssid和password 失败：{e}')
            return False

    def set_run_flag_1(self, power_num):
        if power_num == 1:
            self.channel_1_flag = 1
        elif power_num == 2:
            self.channel_2_flag = 1
        elif power_num == 3:
            self.channel_3_flag = 1
        elif power_num == 4:
            self.channel_4_flag = 1
        elif power_num == 5:
            self.channel_5_flag = 1
        elif power_num == 6:
            self.channel_6_flag = 1
        elif power_num == 7:
            self.channel_7_flag = 1
        elif power_num == 8:
            self.channel_8_flag = 1
        elif power_num == 9:
            self.channel_9_flag = 1
        elif power_num == 10:
            self.channel_10_flag = 1
        elif power_num == 11:
            self.channel_11_flag = 1
        elif power_num == 12:
            self.channel_12_flag = 1
        elif power_num == 13:
            self.channel_13_flag = 1
        elif power_num == 14:
            self.channel_14_flag = 1
        elif power_num == 15:
            self.channel_15_flag = 1
        elif power_num == 16:
            self.channel_16_flag = 1
        return 1

    def set_run_flag_0(self, power_num):
        if power_num == 1:
            self.channel_1_flag = 0
        elif power_num == 2:
            self.channel_2_flag = 0
        elif power_num == 3:
            self.channel_3_flag = 0
        elif power_num == 4:
            self.channel_4_flag = 0
        elif power_num == 5:
            self.channel_5_flag = 0
        elif power_num == 6:
            self.channel_6_flag = 0
        elif power_num == 7:
            self.channel_7_flag = 0
        elif power_num == 8:
            self.channel_8_flag = 0
        elif power_num == 9:
            self.channel_9_flag = 0
        elif power_num == 10:
            self.channel_10_flag = 0
        elif power_num == 11:
            self.channel_11_flag = 0
        elif power_num == 12:
            self.channel_12_flag = 0
        elif power_num == 13:
            self.channel_13_flag = 0
        elif power_num == 14:
            self.channel_14_flag = 0
        elif power_num == 15:
            self.channel_15_flag = 0
        elif power_num == 16:
            self.channel_16_flag = 0
        return 0

    def get_current_flag(self, power_num):
        if power_num == 1:
            return self.channel_1_flag
        elif power_num == 2:
            return self.channel_2_flag
        elif power_num == 3:
            return self.channel_3_flag
        elif power_num == 4:
            return self.channel_4_flag
        elif power_num == 5:
            return self.channel_5_flag
        elif power_num == 6:
            return self.channel_6_flag
        elif power_num == 7:
            return self.channel_7_flag
        elif power_num == 8:
            return self.channel_8_flag
        elif power_num == 9:
            return self.channel_9_flag
        elif power_num == 10:
            return self.channel_10_flag
        elif power_num == 11:
            return self.channel_11_flag
        elif power_num == 12:
            return self.channel_12_flag
        elif power_num == 13:
            return self.channel_13_flag
        elif power_num == 14:
            return self.channel_14_flag
        elif power_num == 15:
            return self.channel_15_flag
        elif power_num == 16:
            return self.channel_16_flag

    def sleep_time(self, power_num, times, stop_event=None):
        """
        改进的睡眠函数，支持停止检查
        """
        if stop_event is None:
            stop_event = self._stop_event
        times = times * 2
        count = 0
        print(
            f'{power_num}_{times}_{stop_event},{count < times and not self.is_stop_requested()},{count}-{times}-{self.is_stop_requested()}')
        while count < times:
            # 每次只睡眠较短时间，以便及时响应停止请求
            if stop_event.wait(0.5):
                return True  # 被中断
            count += 1
            print(f'通道{power_num} 正在等待')
        return False

    def login_telnet_loop(self, tel, network_card_ip, power_num, f):
        times = 1
        while True:
            result = self.login_telnet(tel, network_card_ip, power_num, f)
            if result is False:
                self.show_signal_error[str].emit(
                    f'通道 {power_num} 第 {times} 次连接telnet 失败，等待10s再连接一次')
                if times == 5:
                    self.telnet_status_list[power_num - 1] = 1
                    self.run_status_list[power_num - 1] = 0
                    self.write_to_file(f'通道 {power_num} 发送 telnet error 信号')
                    self.logger.error(f'通道 {power_num} 发送 telnet error 信号')
                    self.telnet_status_signal[list].emit(self.telnet_status_list)
                    self.send_email.send_email_without_attachments(
                        f'通道 {power_num} 发送 telnet error 信号',
                        self.recv_email)
                    return False
                self.sleep_time(power_num, 10)
                times += 1
            else:
                # self.show_signal[str].emit(
                #     f'通道 {power_num} 第 {times} 连接telnet成功')
                return True

    def execute_command_loop(self, tel, f, key, value, timeout, execute_times, power_num, network_card_ip):
        self.login_telnet_loop(tel, network_card_ip, power_num, f)
        result1 = tel.execute_some_command_iwconfig_all(f, key, value, timeout,
                                                        execute_times, self.device_type,
                                                        power_num)
        tel.logout_host()
        return result1

    def run_case(self, network_card_ip, power_num, stop_event=None):

        """
               :param network_card_ip: 网卡IP
               :param power_num: 对应的程控电源口序号
               :return:
        """
        if stop_event is None:
            stop_event = self._stop_event

        run_flag = self.set_run_flag_1(power_num)
        command_result_log = self.create_command_exec_result_file(power_num)
        with open(command_result_log, 'wb', buffering=0) as f:
            self.show_signal[str].emit('通道' + str(power_num) + '开始测试')
            result = self.selected_scheme_path()
            if type(result) is not bool:
                if '异常' in result:
                    self.show_signal_error[str].emit(result)
                    return False

            # 用户名和密码全局变量赋值
            TelnetClient.username = self.username
            TelnetClient.password = self.password
            print('赋值', TelnetClient.username, TelnetClient.password)

            times = 1
            match_gateway_ip = re.compile(r'[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}')
            gateway_ip = match_gateway_ip.search(self.url).group()
            self.logger.info(gateway_ip)
            count_pcie_error = 0
            order_ = self.cf.read_config_file('./config/' + (self.config_file_path),
                                              'order')  # 返回所有命令的键值对

            if 'NME5410_T' in self.config_file_path:
                self.mac_data = str(67 + power_num)
                self.pramer_data = {f'ppctl set LAN_BASE_MAC_ADDRESS="B0:B3:69:24:{self.mac_data}:50"': '',
                                    f'ppctl set WIFI_MAC_24G="B0:B3:69:24:{self.mac_data}:54"': '',
                                    f'ppctl set WIFI_MAC_5G="B0:B3:69:24:{self.mac_data}:58"': '',
                                    f'ppctl set SERIAL_NUMBER="SDME240305017450"': '',
                                    f'ppctl set WIFI_SSID_24G="PLAY_Swiatlowod_{self.mac_data}50"': '',
                                    'ppctl set WIFI_KEY_24G="9%mfK48v6v#E"': '',
                                    f'ppctl set WIFI_SSID_5G="PLAY_Swiatlowod_{self.mac_data}50"': '',
                                    'ppctl set WIFI_KEY_5G="9%mfK48v6v#E"': '',
                                    f'ppctl set WIFI_SSID_24G_GUEST="PLAY_Swiatlowod_{self.mac_data}50_GOSC"': '',
                                    'ppctl set WIFI_KEY_24G_GUEST="\$G7WPj8BhKWE"': '',
                                    f'ppctl set WIFI_SSID_5G_GUEST="PLAY_Swiatlowod_{self.mac_data}50_GOSC_5G"': '',
                                    'ppctl set WIFI_KEY_5G_GUEST="\$G7WPj8BhKWE"': '',
                                    'ppctl set S_PRODUCT_ID="NME5410"': '',
                                    'ppctl set S_HARDWARE_VERSION="V1.0"': '',
                                    'ppctl set MANUFACTURER_OUI="B0B369"': '',
                                    'ppctl set ADMIN_USERNAME="play"': '',
                                    'ppctl set ADMIN_PASSWORD="p!@yd3bUgm@St3r"': '',
                                    'ppctl set USER_USERNAME="admin"': '',
                                    'ppctl set USER_PASSWORD="ERT1g\$GqpUYD"': '',
                                    'ppctl set ACS_USERNAME="B0B369-SDME240305017450"': '',
                                    'ppctl set ACS_PASSWORD="YjM0NjNjNDgxOGFk"': ''}
                self.pramer_data.update(order_)
                order_ = self.pramer_data
            print('&&&&&&&&&&&&&&&&&&&&&', order_)
            while not self.is_stop_requested() and times <= self.test_number:
                web_open_telnet_flag = 0
                try:
                    self.show_signal[str].emit(f"*******通道 【{power_num}】 开始第{times}次测试*******")

                    commands_loop_times = self.commands_loop_times
                    retry_times = self.retry_times
                    interval_time = self.telnet_enable_fail_retry_interval

                    if self.flag:
                        self.reset_status(power_num - 1)
                        # 装入power 开关的 生产者
                        commandturple1 = (self.power_control.power_off, self.ser, int(power_num))
                        self.power_control.producer(commandturple1)
                        # self.logger.info(int(power_num))
                        time.sleep(1.5)
                        if times > 1:
                            # 每次测试完成后等待时间
                            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                            f.write(f'{timestamp} ：本次测试断电之后等待：{self.interval_time}s后启动\n'.encode())

                            sleep_result = self.sleep_time(power_num, self.interval_time)
                            if sleep_result:
                                self.show_signal[str].emit(
                                    f'通道 {power_num} 发送手动停止的信号')
                                return True
                        # 队列处理发命令
                        commandturple = (self.power_control.power_on, self.ser, int(power_num))
                        self.power_control.producer(commandturple)
                        # 等待设备启动
                        f.write('only power off on flag:{}\n'.format(self.only_power_off_on).encode())
                        sleep_result = self.sleep_time(power_num, self.startup_time)
                        print(f'通道 {power_num} 发送手动停止的信号:{sleep_result}')
                        if sleep_result:
                            self.show_signal[str].emit(
                                f'通道 {power_num} 发送手动停止的信号')
                            return True

                        if self.only_power_off_on:
                            f.write(f'The device of channel {power_num} only power off on {times} times\n'.encode())
                            if times == self.test_number:
                                self.logger.info(
                                    f'The device of channel {power_num} of programmable power supply  restarts {self.test_number} times, please replace the device！')
                                self.show_signal[str].emit(
                                    f'通道 {power_num} 发送 Test Complete 信号，总测试次数：{times}')
                                self.normal_status_list[power_num - 1] = 1
                                self.run_status_list[power_num - 1] = 0
                                self.normal_status_signal[list].emit(self.normal_status_list)
                                self.send_email.send_email_without_attachments(
                                    f'通道 {power_num} 测试完成，总测试次数：{times}', self.recv_email)
                                return True
                            else:
                                times += 1
                                print("times:", times)
                                continue
                        # ping -S 网卡IP 网关IP
                        print('pingllllllllllllllllll')
                        result = self.cmd_ping.cmd_ping_gen7(network_card_ip, gateway_ip, f)
                        if result:
                            f.write('only power off on:{}\n'.format(self.only_power_off_on).encode())
                            # if self.only_power_off_on:
                            #     f.write('only power off on\n'.encode())
                            #     continue
                            f.write(f'通道 {power_num} ping 通\n'.encode())
                            if not self.open_telnet_enable(network_card_ip, self.url, f, retry_times, interval_time,
                                                           power_num):
                                return False

                            self.logger.info('./config/' + (self.config_file_path))

                            self.logger.info(order_)
                            f.write(f'\n\n测试指令集order:{order_}\n'.encode())

                            tel = TelnetClient(
                                network_card_ip,
                                gateway_ip,
                                self.port,
                                self.logger,
                                self.config_file_path,
                                on_retry=lambda command, attempt, total: self.show_signal_warning[str].emit(
                                    f'通道 {power_num} 执行指令：{command}，在第{attempt}次时出现错误；'
                                    f'准备第{attempt + 1}/{total}次验证'
                                ),
                            )
                            # self.logger.info(f'通道 {power_num} enable telnet success')
                            # f.write(f'通道 {power_num} enable telnet success\n'.encode())
                            # 20231120 打开telnet后给延迟，等待进程起来
                            time.sleep(1)
                            result = self.login_telnet_loop(tel, network_card_ip, power_num, f)
                            # result = tel.login_host(network_card_ip, self.username, self.password, f)
                            if result is False:
                                return False
                            else:
                                # 先退出登录
                                tel.logout_host()
                                # 执行命令
                                # 循环执行指令，特殊场景
                                loop_times = 0
                                while True:
                                    if "NP6541_stress_test_config" in self.config_file_path:
                                        loop_times += 1
                                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                                        if loop_times > commands_loop_times:
                                            break
                                        self.logger.info(f"{timestamp}：特殊场景，指令集循环执行第{loop_times}次")
                                        f.write((f"{timestamp}：特殊场景，指令集循环执行第{loop_times}次\n").encode())

                                    for key, value in order_.items():
                                        run_flag = self.get_current_flag(power_num)
                                        if run_flag == 0:
                                            self.show_signal[str].emit(
                                                f'通道 {power_num} 发送手动停止的信号')
                                            return True
                                        if 'wait_time' in key and 'retry_times' not in key:
                                            list1 = key.rsplit(' ', maxsplit=1)
                                            print('xxxxxxxxxxxxxxx', list1[0])
                                            key = list1[0]
                                            time_str = list1[-1].split('wait_time_')[1]
                                            if '-' in time_str:
                                                time_list = time_str.split('-')
                                                print(time_list)
                                                min_time = int(time_list[0])
                                                max_time = int(time_list[1])
                                                timeout = round(random.uniform(min_time, max_time), 1)
                                            else:
                                                timeout = int(time_str)
                                            execute_times = 1

                                        elif 'wait_time' not in key and 'retry_times' in key:
                                            list1 = key.rsplit(' ', maxsplit=1)
                                            print('xxxxxxxxxxxxxxx', list1[0])
                                            key = list1[0]
                                            execute_times = int(list1[-1].split('retry_times_')[1])
                                            timeout = 1

                                        elif 'wait_time' in key and 'retry_times' in key:
                                            list1 = key.rsplit(' ', maxsplit=2)
                                            print(list1)
                                            key = list1[0]
                                            time_str = list1[-2].split('wait_time_')[1]
                                            if '-' in time_str:
                                                time_list = time_str.split('-')
                                                print(time_list)
                                                min_time = int(time_list[0])
                                                max_time = int(time_list[1])
                                                timeout = round(random.uniform(min_time, max_time), 1)
                                            else:
                                                timeout = int(time_str)
                                            execute_times = int(list1[-1].split('retry_times_')[1])

                                        else:
                                            execute_times = 1
                                            timeout = 1
                                        if '&&' in key:
                                            key = key.split('&&')[0]
                                        print('指令{}的执行timeout:{},execute_times:{}\n'.format(key, timeout,
                                                                                                 execute_times))
                                        # tel.get_status()

                                        f.write('\n\n'.encode() + '*'.encode() * 150 + '\n\n'.encode())
                                        f.write('指令: {} 的执行 timeout: {},execute_times: {}\n'.format(key, timeout,
                                                                                                         execute_times).encode())

                                        # 对执行指令时间超过100s的特殊指令进行处理，实际不需要那么久，只是测试场景需要
                                        if timeout > 100:
                                            timeout_1 = 2
                                            result1 = self.execute_command_loop(tel, f, key, value, timeout_1,
                                                                                execute_times,
                                                                                power_num, network_card_ip)
                                            sleep_time = timeout - timeout_1
                                            now_time = datetime.datetime.now()
                                            f.write(
                                                f'{str(now_time)}: 通道{power_num}下挂的设备，等待{sleep_time}s，在重新连接telnet\n'.encode())
                                            tel.logout_host()
                                            # 更改时间循环
                                            sleep_result = self.sleep_time(power_num, self.interval_time)
                                            if sleep_result:
                                                self.show_signal[str].emit(
                                                    f'通道 {power_num} 发送手动停止的信号')
                                                return True
                                            # 防止telnet打开之后又自动关闭
                                            if not self.open_telnet_enable(network_card_ip, self.url, f, retry_times,
                                                                           interval_time, power_num):
                                                desc = f'通道 {power_num} Open_telnet_Enable 失败'
                                                dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                                     desc)
                                                if dingtalk_result is not True:
                                                    self.show_signal_error[str].emit(
                                                        f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                                return False

                                            result = self.login_telnet_loop(tel, network_card_ip, power_num, f)
                                            if not result:
                                                desc = f'通道 {power_num} telnet_login 失败'
                                                dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                                     desc)
                                                if dingtalk_result is not True:
                                                    self.show_signal_error[str].emit(
                                                        f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                                return False
                                        else:
                                            result1 = self.execute_command_loop(tel, f, key, value, timeout,
                                                                                execute_times,
                                                                                power_num, network_card_ip)

                                        # 判断为真的时候才传入
                                        if result1:
                                            if result1 > 1:
                                                # 增加 指令重试次数 的打印，20250104
                                                f.write(f'指令 {key} 重试了 {result1 - 1}次之后，执行成功'.encode())
                                                self.show_signal_warning[str].emit(
                                                    f'通道 {power_num} 发送指令 {key} 重试了 {result1 - 1}次之后，执行成功')
                                                # f.write('开始执行下一个指令\n'.encode())
                                        else:
                                            # 指令执行失败之后执行 ps 查看一下进程
                                            self.execute_command_loop(tel, f, 'ps', '', timeout,
                                                                      1,
                                                                      power_num, network_card_ip)

                                            self.check_status_code(power_num, key, f, execute_times)
                                            now_time = datetime.datetime.now()
                                            f.write(
                                                f'{str(now_time)}: 通道{power_num}下挂的设备在第{times}次测试时失败\n'.encode())
                                            return False

                                    if "NP6541_stress_test_config" not in self.config_file_path:
                                        break

                                # 在此处增加 WiFi_信息的获取操作
                                if times == 1:
                                    self.connect_wifi_enable = OnuCongfig.connect_wifi_enable_status
                                    self.product_solution = OnuCongfig.Onu_solution_type
                                    self.onu_ciper = OnuCongfig.connect_wifi_ciper
                                    self.onu_auth_mode = OnuCongfig.connect_wifi_auth_mode
                                    self.test_2g_wifi_flag = OnuCongfig.choose_test_2g_flag
                                    self.test_5g_wifi_flag = OnuCongfig.choose_test_5g_flag
                                    self.appoint_wireless_card_flag = OnuCongfig.choose_wireless_card_flag
                                    self.wireless_card = OnuCongfig.choose_wireless_card_name
                                print('self.test_2g_wifi_flag', self.test_2g_wifi_flag, self.test_5g_wifi_flag,
                                      self.wireless_card, self.onu_auth_mode, self.onu_ciper)
                                print('............................................................', times)

                                print('self.times', times)

                                if self.connect_wifi_enable == 1:
                                    if times == 1:
                                        iface_name = OnuCongfig.iface_names
                                        if iface_name is []:
                                            return False
                                        # 只获取一次WiFi ssid和密码
                                        self.login_telnet_loop(tel, network_card_ip, power_num, f)
                                        wifi_info = self.get_wifi_info(power_num, tel)
                                    if wifi_info:
                                        desc = f'通道{power_num} 的WiFi：{wifi_info}'
                                        self.show_signal[str].emit(desc)
                                        self.logger.info(desc)
                                        if self.test_2g_wifi_flag:
                                            wifi_connect_result = self.wifi_connect.connect_wifi(wifi_info[0],
                                                                                                 wifi_info[1],
                                                                                                 self.wireless_card,
                                                                                                 psk=self.onu_auth_mode,
                                                                                                 cipher=self.onu_ciper)
                                            if not wifi_connect_result:
                                                desc = f'连接通道【{power_num}】的2g ssid 失败:({wifi_info[0]},{wifi_info[1]})'
                                                self.show_signal_error[str].emit(desc)
                                                self.wifi_status_list[power_num - 1] = 1
                                                self.run_status_list[power_num - 1] = 0
                                                self.wifi_status_signal[list].emit(self.wifi_status_list)
                                                dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                                     desc)
                                                if dingtalk_result is not True:
                                                    self.show_signal_error[str].emit(
                                                        f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                                return False
                                            else:
                                                desc = f'连接通道【{power_num}】的2g ssid 成功:({wifi_info[0]},{wifi_info[1]})'
                                                self.show_signal[str].emit(desc)
                                        if self.test_5g_wifi_flag:
                                            wifi_connect_result = self.wifi_connect.connect_wifi(wifi_info[2],
                                                                                                 wifi_info[3],
                                                                                                 self.wireless_card,
                                                                                                 psk=self.onu_auth_mode,
                                                                                                 cipher=self.onu_ciper)
                                            if not wifi_connect_result:
                                                desc = f'连接通道【{power_num}】的5g ssid 失败:({wifi_info[2]},{wifi_info[3]})'
                                                self.show_signal_error[str].emit(desc)
                                                self.wifi_status_list[power_num - 1] = 1
                                                self.run_status_list[power_num - 1] = 0
                                                self.wifi_status_signal[list].emit(self.wifi_status_list)
                                                dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                                     desc)
                                                if dingtalk_result is not True:
                                                    self.show_signal_error[str].emit(
                                                        f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                                return False
                                            else:
                                                desc = f'连接通道【{power_num}】的5g ssid 成功:({wifi_info[2]},{wifi_info[3]})'
                                                self.show_signal[str].emit(desc)
                                    else:
                                        desc = f'获取通道【{power_num}】 的WiFi信息失败'
                                        self.show_signal_error[str].emit(desc)
                                        self.wifi_status_list[power_num - 1] = 1
                                        self.run_status_list[power_num - 1] = 0
                                        self.wifi_status_signal[list].emit(self.wifi_status_list)
                                        dingtalk_result = self.dingtalk.webhook_send_message(self.device_type, desc)
                                        if dingtalk_result is not True:
                                            self.show_signal_error[str].emit(
                                                f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                        return False

                                # # 关闭 telnet
                                # tel.logout_host()
                                # 增加 下发指令后的ping包测试，有的设备会出现卡死的情况
                                result = self.cmd_ping.cmd_ping_gen7(network_card_ip, gateway_ip, f)
                                if not result:
                                    self.ping_status_list[power_num - 1] = 1
                                    self.run_status_list[power_num - 1] = 0
                                    f.write(f'通道 {power_num} 发送 ping error 信号'.encode())
                                    self.logger.error(f'通道 {power_num} 发送 ping error 信号')
                                    self.show_signal_error[str].emit(f'通道 {power_num} 发送 ping error 信号')
                                    self.ping_status_signal[list].emit(self.ping_status_list)
                                    self.send_email.send_email_without_attachments(
                                        f'通道 {power_num} 发送 ping error 信号',
                                        self.recv_email)
                                    dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                         f'通道 {power_num} 发送 ping error 信号')
                                    if dingtalk_result is not True:
                                        self.show_signal_error[str].emit(f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                    return False
                                # 记录测试次数
                                now_time = datetime.datetime.now()
                                f.write(
                                    f'{str(now_time)}: 通道{power_num}下挂的设备在第{times}次测试时正常\n'.encode())
                            # 跳出循环说明指令执行成功

                            if times == self.test_number:
                                self.logger.info(
                                    f'The device of channel {power_num} of programmable power supply  restarts {self.test_number} times, please replace the device！')
                                self.show_signal[str].emit(
                                    f'通道 {power_num} 发送 Test Complete 信号，总测试次数：{times}')
                                self.normal_status_list[power_num - 1] = 1
                                self.run_status_list[power_num - 1] = 0
                                self.normal_status_signal[list].emit(self.normal_status_list)
                                self.send_email.send_email_without_attachments(
                                    f'通道 {power_num} 测试完成，总测试次数：{times}', self.recv_email)
                                dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                     f'通道 {power_num} 测试完成，总测试次数：{times}',
                                                                                     1)
                                if dingtalk_result is not True:
                                    self.show_signal_error[str].emit(f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                                return True
                            times += 1
                            # self.show_signal[str].emit(
                            #     f'通道 {power_num} 发送 Test Complete 信号，总测试次数：{times}')

                        else:
                            self.ping_status_list[power_num - 1] = 1
                            self.run_status_list[power_num - 1] = 0
                            f.write(f'通道 {power_num} 发送 ping error 信号'.encode())
                            self.logger.error(f'通道 {power_num} 发送 ping error 信号')
                            self.show_signal_error[str].emit(f'通道 {power_num} 发送 ping error 信号')
                            self.ping_status_signal[list].emit(self.ping_status_list)
                            self.send_email.send_email_without_attachments(f'通道 {power_num} 发送 ping error 信号',
                                                                           self.recv_email)
                            dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                                 f'通道 {power_num} 发送 ping error 信号')
                            if dingtalk_result is not True:
                                self.show_signal_error[str].emit(f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                            return False

                        # 每次测试完成后等待时间
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        f.write(f'{timestamp}指令执行完成，等待：{self.wait_command_done}s后断电\n'.encode())
                        time.sleep(self.wait_command_done)
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        f.write(f'{timestamp} :本次测试之后等待：{self.wait_command_done}s后断电\n'.encode())
                    else:
                        time.sleep(1)
                        return True
                except Exception as e:
                    self.show_signal_error[str].emit(f'通道 {power_num} 程序运行异常：{e}')
                    self.ping_status_list[power_num - 1] = 1
                    self.run_status_list[power_num - 1] = 0
                    self.logger.error(f'通道 {power_num} 程序运行异常：{e}')
                    self.ping_status_signal[list].emit(self.ping_status_list)
                    self.send_email.send_email_without_attachments(f'通道 {power_num} 程序运行异常：{str(e)}',
                                                                   self.recv_email)
                    f.write(f'通道 {power_num} 程序运行异常：{str(e)}\n'.encode())
                    dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                                         f'通道 {power_num} 程序运行异常：{str(e)}')
                    if dingtalk_result is not True:
                        self.show_signal_error[str].emit(f'dingTalk 发送消息失败 ：{dingtalk_result}\n')
                    return False

    def check_status_code(self, power_num, code, f, attempts=1):
        """

        :param power_num: 电源通道
        :param code: 错误指令
        :param f: 保存的文件
        :return:
        """
        if 'ifconfig' in code:
            self.command_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.command_status_signal[list].emit(self.command_status_list)
        elif 'eth' in code:
            self.eth_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.eth_status_signal[list].emit(self.eth_status_list)
        elif 'voip' in code:
            self.voip_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.voip_status_signal[list].emit(self.voip_status_list)
        elif 'wan' in code:
            self.wan_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.wan_status_signal[list].emit(self.wan_status_list)
        elif 'pon' in code:
            self.pon_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.pon_status_signal[list].emit(self.pon_status_list)
        else:
            self.command_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.command_status_signal[list].emit(self.command_status_list)

        self.write_to_file(f'通道 {power_num} 执行 {code} 错误')
        self.logger.error(f'通道 {power_num} 发送 {code}  error 信号')
        self.show_signal_error[str].emit(
            f'通道 {power_num} 尝试执行指令：{code} {attempts}次进行验证，验证失败\n'
        )
        self.send_email.send_email_without_attachments(f'通道 {power_num} 发送 {code} error 信号',
                                                       self.recv_email)
        f.write(f'通道 {power_num} 执行 {code} 错误\n'.encode())

        # 发送钉钉消息到 2025.0104
        dingtalk_result = self.dingtalk.webhook_send_message(self.device_type,
                                                             f'通道 {power_num} 尝试执行指令：{code} 多次进行验证，验证失败')
        if dingtalk_result is not True:
            self.show_signal_error[str].emit(f'dingTalk 发送消息失败 ：{dingtalk_result}\n')

    def check_PCIE_status_code(self, list1):
        # self.logger.info(list1)
        for i in list1:
            if '0xbfb80050' in i:
                return i.split()[-1][-1]

    def open_telnet_enable(self, network_card_ip, url, f, retry_times, interval_time, power_num):
        if self.telnet_enable_flag:
            if not Web_Page_Open_Telnet(network_card_ip, url, f, retry_times, interval_time,
                                        flag=1):
                self.web_status_list[power_num - 1] = 1
                self.run_status_list[power_num - 1] = 0
                self.write_to_file(f'通道 {power_num}  发送 web open telnet fail 信号')
                self.logger.error(f'通道 {power_num}  发送 web open telnet fail 信号')
                self.show_signal_error[str].emit(f'通道 {power_num} 发送 web open telnet fail 信号')
                self.web_status_signal[list].emit(self.web_status_list)
                self.send_email.send_email_without_attachments(
                    f'通道 {power_num} 发送 web open telnet fail 信号',
                    self.recv_email)
                f.write(f'通道 {power_num} telnet 打开失败\n'.encode())
                self.logger.error('telnet 打开失败')
                return False
            else:
                return True
        else:
            return True

    def login_telnet(self, tel, network_card_ip, power_num, f):
        result = tel.login_host(network_card_ip, self.username, self.password, f)
        if result is False:
            self.logger.error(f'通道 {power_num} 登录telnet 失败')  # 看是否会连续发送同一个信号
            # 9.11
            self.show_signal_error[str].emit(f'通道 {power_num} 登录telnet 失败')
            f.write(f'通道 {power_num} 登录telnet 失败\n'.encode())
            # self.telnet_status_list[power_num - 1] = 1
            # self.run_status_list[power_num - 1] = 0
            # self.write_to_file(f'通道 {power_num} 发送 telnet error 信号')
            # self.logger.error(f'通道 {power_num} 发送 telnet error 信号')
            # self.telnet_status_signal[list].emit(self.telnet_status_list)
            # self.send_email.send_email_without_attachments(
            #     f'通道 {power_num} 发送 telnet error 信号',
            #     self.recv_email)
            return False
        elif result == 2:
            self.show_signal_error[str].emit(f'通道 {power_num} 登录telnet timed out')
            f.write(f'通道 {power_num} 登录telnet 失败\n'.encode())
            # self.telnet_status_list[power_num - 1] = 1
            # self.run_status_list[power_num - 1] = 0
            # self.write_to_file(f'通道 {power_num} 发送 telnet error 信号')
            # self.logger.error(f'通道 {power_num} 发送 telnet error 信号')
            # self.telnet_status_signal[list].emit(self.telnet_status_list)
            # self.send_email.send_email_without_attachments(
            #     f'通道 {power_num} 发送 telnet error 信号',
            #     self.recv_email)
            return False
        else:
            return True

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.request_stop()
        self.wait(10)  # 等待10秒线程结束
        if self.isRunning():
            self.terminate()
        # 清理其他资源，如串口连接
        if hasattr(self, 'ser') and self.ser:
            self.ser.close()


if __name__ == '__main__':
    gen = PowerOnOffTelnet('com6', '19200', "altfactory", "pPRodU6c17!0nN", 1288)
    gen.run()
    os.system('pause')

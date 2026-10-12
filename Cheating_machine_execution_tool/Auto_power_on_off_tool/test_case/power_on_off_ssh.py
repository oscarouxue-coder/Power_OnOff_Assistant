import datetime
import logging
import os
import random
import re
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

from common.dingtalk_send_message import DingTalk
from common.fuzzy_match import Fuzzy_Match
from common.my_logging import creat_logger
from common.power_on_off import PowerOnOff
from common.execute_network_card_ping import Cmd
from clients.ssh import SSHClient
from common.send_email import SendEmail
from config.config_driver import OperationConfig

# 8.31号
lock = threading.Lock()


class PowerOnOffSsh(QThread):
    run_status_signal = pyqtSignal(list)
    ping_status_signal = pyqtSignal(list)
    pcie_status_signal = pyqtSignal(list)
    normal_status_signal = pyqtSignal(list)

    wifi_status_signal = pyqtSignal(list)
    eth_status_signal = pyqtSignal(list)
    voip_status_signal = pyqtSignal(list)
    wan_status_signal = pyqtSignal(list)
    pon_status_signal = pyqtSignal(list)
    command_status_signal = pyqtSignal(list)

    show_signal = pyqtSignal(str)
    show_signal_error = pyqtSignal(str)
    # 重试多次之后指令才执行成功
    show_signal_warning = pyqtSignal(str)

    def __init__(self, ser, logger, startup_time, interval_time, wait_command_done, test_number, config_file_path,
                 recv_email=[], device_type='', *, initialize_power=True):
        super(PowerOnOffSsh, self).__init__()
        self.dingtalk = DingTalk()
        self.cf = OperationConfig()
        # self.ip_list=get_local_ip()
        self.logger = logger
        self.ser = ser
        self.username = ""
        self.password = ""
        self.port = 0
        self.startup_time = int(startup_time)
        self.interval_time = int(interval_time)
        self.test_number = int(test_number)
        self.wait_command_done = int(wait_command_done)
        self.send_email = SendEmail(self.logger)
        self.recv_email = recv_email

        self.device_type = device_type
        # 把页面选择的配置传进来做处理 9.7
        self.config_file_path = config_file_path
        self.power_control = PowerOnOff(self.logger)
        # self.ser = Serial(self.serial_num, self.baud_rate, self.logger)
        self.cmd_ping = Cmd(self.logger)
        if initialize_power:
            self.power_control.power_all_off(self.ser)
        time.sleep(1)
        # 各个通道运行标志
        self.all_channel_flag = 1
        self.channel_1_flag = 1
        self.channel_2_flag = 1
        self.channel_3_flag = 1
        self.channel_4_flag = 1
        self.channel_5_flag = 1
        self.channel_6_flag = 1
        self.channel_7_flag = 1
        self.channel_8_flag = 1
        self.channel_9_flag = 1
        self.channel_10_flag = 1
        self.channel_11_flag = 1
        self.channel_12_flag = 1
        self.channel_13_flag = 1
        self.channel_14_flag = 1
        self.channel_15_flag = 1
        self.channel_16_flag = 1

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
        self.results_filename = file_path + self.timestamp + '_error' + '.log'
        # self.cpu_memory_monitor_filename = file_path + portx + '_cpu_memory_monitor' + '.log'
        # 实时写入文件,buffering=0
        # self.results_file = open(self.results_filename, 'wb', buffering=0)

        self.run_flag = 0

    def __del__(self):
        # self.ser.serial_close()
        pass

    def selected_scheme_path(self):
        # self.config_file_path = path
        try:
            self.username = self.cf.read_ini('ssh', 'user',
                                             path='./config/' + (self.config_file_path)).strip()
            self.password = self.cf.read_ini('ssh', 'password',
                                             path='./config/' + (self.config_file_path)).strip()
            self.url = self.cf.read_ini('ssh', 'request_url',
                                        path='./config/' + (self.config_file_path)).strip()
            self.port = int(self.cf.read_ini('ssh', 'port',
                                             path='./config/' + (self.config_file_path)).strip())
        except Exception as e:
            self.logger.error(f'读取{self.config_file_path}文件异常:{e}')
            return f'读取{self.config_file_path}文件异常:{e}'
        # self.network_card_ip = self.cf.read_ini('channel_01', 'network_card_ip',
        #                                           path=self.config_file_path)
        else:
            self.logger.info(f"{self.username},{self.password},{self.url},{self.port}")
            return True

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
        self.command_status_list[num] = 0
        self.pon_status_list[num] = 0
        self.wan_status_list[num] = 0
        self.voip_status_list[num] = 0
        self.eth_status_list[num] = 0
        self.wifi_status_list[num] = 0

    def run_case(self, network_card_ip, power_num, flag, *, start_cycle=1, result_suffix=""):
        """
        :param network_card_ip: 网卡IP
        :param power_num: 对应的程控电源口序号
        :param flag: 运行的标志，为时运行，为0时停止
        :return:
        """
        times = start_cycle

        if not 1 <= start_cycle <= self.test_number:
            raise ValueError("起始轮次超出测试范围")
        command_result_log = self.create_command_exec_result_file(power_num)
        if result_suffix:
            command_result_log = command_result_log[:-4] + "_resume_" + result_suffix + ".log"
        with open(command_result_log, 'wb', buffering=0) as file:
            self.show_signal[str].emit('通道' + str(power_num) + '开始测试')
            times = start_cycle
            match_gateway_ip = re.compile(r'[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}')
            result = self.selected_scheme_path()
            if type(result) is not bool:
                if '异常' in result:
                    self.show_signal_error[str].emit(result)
                    return False
            gateway_ip = match_gateway_ip.search(self.url).group()
            self.logger.info(gateway_ip)
            order_ = self.cf.read_config_file('./config/' + (self.config_file_path),
                                              'order')  # 返回所有命令的键值对
            while True:
                try:
                    if self.flag:
                        self.reset_status(power_num - 1)
                        # run
                        # if self.run_flag:
                        #     self.logger.info('发送run信号')
                        #     self.run_flag = 0
                        #     self.run_status_list[power_num - 1] = 1
                        #     self.run_status_signal[list].emit(self.run_status_list)
                        #     self.power_control.power_off(self.ser, int(power_num))

                        commandturple1 = (self.power_control.power_off, self.ser, int(power_num))
                        self.power_control.producer(commandturple1)
                        # self.logger.info(int(power_num))
                        time.sleep(1.5)
                        if times > 1:
                            # 每次测试完成后等待时间
                            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                            file.write(f'{timestamp} :本次测试断电之后等待：{self.interval_time}s后启动\n'.encode())
                            time.sleep(self.interval_time)
                        # 队列处理发命令
                        commandturple = (self.power_control.power_on, self.ser, int(power_num))
                        self.power_control.producer(commandturple)

                        time.sleep(self.startup_time)
                        # time.sleep(create_float_num(3))
                        result = self.cmd_ping.cmd_ping_gen7(network_card_ip, gateway_ip, file)
                        if result:
                            print(order_)
                            timestamp = time.strftime('%Y_%m_%d %H:%M:%S ', time.localtime(time.time()))
                            file.write(f'\n\n{timestamp}测试指令集order:{order_}\n'.encode())
                            print(self.password)
                            ssh = SSHClient(
                                self.url,
                                self.username,
                                self.password,
                                network_card_ip,
                                self.port,
                                timeout=50,
                                logger=self.logger,
                                file=file,
                                on_retry=lambda command, attempt, total: self.show_signal_warning[str].emit(
                                    f'通道 {power_num} 执行指令：{command}，在第{attempt}次时出现错误；'
                                    f'准备第{attempt + 1}/{total}次验证'
                                ),
                            )
                            result = ssh.connect_ssh()
                            if not result:
                                self.ping_status_list[power_num - 1] = 1
                                self.run_status_list[power_num - 1] = 0
                                # self.logger.error(f'通道 {power_num} 发送 SSH 信号')  # 看是否会连续发送同一个信号
                                self.ping_status_signal[list].emit(self.ping_status_list)  # 连续发同一个信号可能导致闪退
                                self.logger.error(f'通道 {power_num} 登录ssh 失败')  # 看是否会连续发送同一个信号
                                # 9.11
                                self.show_signal_error[str].emit(f'通道 {power_num} 登录ssh 失败')
                                return False
                            else:
                                for key, value in order_.items():
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
                                    print('指令: {} 的执行timeout:{},execute_times:{}\n'.format(key, timeout,
                                                                                                execute_times))
                                    file.write('\n\n'.encode() + '*'.encode() * 150 + '\n\n'.encode())
                                    file.write('指令: {} 的执行 timeout: {},execute_times: {}\n'.format(key, timeout,
                                                                                                        execute_times).encode())
                                    result1 = ssh.exec_ShellCommand_all(file, key, value, timeout,
                                                                        execute_times)
                                    if result1:
                                        if result1 > 1:
                                            # 增加 指令重试次数 的打印，20250104
                                            f.write(f'指令 {key} 重试了 {result1 - 1}次之后，执行成功'.encode())
                                            self.show_signal_warning[str].emit(
                                                f'通道 {power_num} 发送指令 {key} 重试了 {result1 - 1}次之后，执行成功')
                                            # f.write('开始执行下一个指令\n'.encode())
                                    else:
                                        # 指令执行失败之后执行 ps 查看一下进程
                                        ssh.exec_ShellCommand_all(f, 'ps', '', timeout,
                                                                  1)
                                        self.check_status_code(power_num, key, execute_times)
                                        now_time = datetime.datetime.now()
                                        f.write(
                                            f'{str(now_time)}: 通道{power_num}下挂的设备在第{times}次测试时失败\n'.encode())
                                        return False
                            # 8.25 关闭SSH
                            ssh.close()
                            now_time = datetime.datetime.now()
                            file.write(
                                f'{str(now_time)}: 通道{power_num}下挂的设备在第{times}次测试时正常\n'.encode())
                        else:
                            self.ping_status_list[power_num - 1] = 1
                            self.run_status_list[power_num - 1] = 0
                            self.show_signal_error[str].emit(f'通道 {power_num} 发送 ping error 信号')
                            self.write_to_file(f'通道 {power_num} 发送 ping error 信号\n')
                            self.logger.error(f'通道 {power_num} 发送 ping error 信号')  # 看是否会连续发送同一个信号
                            self.ping_status_signal[list].emit(self.ping_status_list)  # 连续发同一个信号可能导致闪退
                            self.send_email.send_email_without_attachments(f'通道 {power_num} 发送 ping error 信号',
                                                                           self.recv_email)
                            # time.sleep(create_float_num(3))  # 给个随机时间试试
                            return False
                        times += 1

                        if times == self.test_number:
                            self.logger.info(
                                f'The device of channel {power_num} of programmable power supply  restarts {self.test_number} times, please replace the device！')

                            self.normal_status_list[power_num - 1] = 1
                            self.run_status_list[power_num - 1] = 0
                            self.normal_status_signal[list].emit(self.normal_status_list)
                            self.send_email.send_email_without_attachments(
                                f'通道 {power_num} 测试完成，总测试次数：{times}', self.recv_email)
                            return True

                            # return False  # 8.25
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        file.write(f'{timestamp}指令执行完成，等待：{self.wait_command_done}s后断电\n'.encode())
                        time.sleep(self.wait_command_done)
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        file.write(f'{timestamp}本次测试之后已等待：{self.wait_command_done}s\n'.encode())
                    else:
                        # continue
                        self.logger.info(f'{power_num} stop func')
                        return False
                except Exception as e:
                    if 'WinError' in str(e):
                        timestamp = time.strftime('%Y_%m_%d %H:%M:%S ', time.localtime(time.time()))
                        file.write(f'{timestamp}出现一次{str(e)}异常，等待20s后再次连接\n'.encode())
                        time.sleep(20)
                        continue

                    self.show_signal_error[str].emit(f'通道 {power_num} 程序运行异常：{e}')
                    # self.logger.error(f'通道 {power_num} 程序运行异常：{e}')
                    self.ping_status_list[power_num - 1] = 1
                    self.run_status_list[power_num - 1] = 0
                    # self.write_to_file(f'通道 {power_num} 程序运行异常：{e}')
                    self.logger.error(f'通道 {power_num} 程序运行异常：{e}')
                    self.ping_status_signal[list].emit(self.ping_status_list)
                    self.send_email.send_email_without_attachments(f'通道 {power_num} 程序运行异常：{str(e)}',
                                                                   self.recv_email)
                    file.write(f'通道 {power_num} 程序运行异常：{e}\n'.encode())
                    return False

    def check_status_code(self, power_num, code, attempts=1):
        """
        发送失败是的status code
        """
        if 'ifconfig' in code:
            self.wifi_status_list[power_num - 1] = 1
            self.run_status_list[power_num - 1] = 0
            self.wifi_status_signal[list].emit(self.wifi_status_list)
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

    # def channel_x_run(self, network_card_ip):

    def channel_1_run(self, network_card_ip):
        self.run_case(network_card_ip, 1, self.channel_1_flag)

    def channel_2_run(self, network_card_ip):
        self.run_case(network_card_ip, 2, self.channel_2_flag)

    def channel_3_run(self, network_card_ip):
        self.run_case(network_card_ip, 3, self.channel_3_flag)

    def channel_4_run(self, network_card_ip):
        self.run_case(network_card_ip, 4, self.channel_4_flag)

    def channel_5_run(self, network_card_ip):
        self.run_case(network_card_ip, 5, self.channel_5_flag)

    def channel_6_run(self, network_card_ip):
        self.run_case(network_card_ip, 6, self.channel_6_flag)

    def channel_7_run(self, network_card_ip):
        self.run_case(network_card_ip, 7, self.channel_7_flag)

    def channel_8_run(self, network_card_ip):
        self.run_case(network_card_ip, 8, self.channel_8_flag)

    def channel_9_run(self, network_card_ip):
        self.run_case(network_card_ip, 9, self.channel_9_flag)

    def channel_10_run(self, network_card_ip):
        self.run_case(network_card_ip, 10, self.channel_10_flag)

    def channel_11_run(self, network_card_ip):
        self.run_case(network_card_ip, 11, self.channel_11_flag)

    def channel_12_run(self, network_card_ip):
        self.run_case(network_card_ip, 12, self.channel_12_flag)

    def channel_13_run(self, network_card_ip):
        self.run_case(network_card_ip, 13, self.channel_13_flag)

    def channel_14_run(self, network_card_ip):
        self.run_case(network_card_ip, 14, self.channel_14_flag)

    def channel_15_run(self, network_card_ip):
        self.run_case(network_card_ip, 15, self.channel_15_flag)

    def channel_16_run(self, network_card_ip):
        self.run_case(network_card_ip, 16, self.channel_16_flag)


if __name__ == '__main__':
    with open('command_result_log.txt', 'wb', buffering=0) as f:
        logger = creat_logger('Power_on_off')

        po = PowerOnOffSsh('cm1', logger, 4, 50, 50, 'NP1269GC_config.ini', recv_email=[])
        po.run_('192.168.1.12')
        po.run_case('192.168.1.12', 1, 1)

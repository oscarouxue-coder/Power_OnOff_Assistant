import codecs
import json
import logging
import sys
from telnetlib import *
import time

from common.dingtalk_send_message import DingTalk
from common.fuzzy_match import Fuzzy_Match
from common.my_logging import creat_logger
import re
import socket
from common.web_page_open_telnet import Web_Page_Open_Telnet
from config.config_driver import OperationConfig

TELNET_PORT = 23


class TelnetEngine(Telnet):

    def __init__(self, source=None, host=None, port=0, timeout=15):
        # <<<<
        # MUST before super __init__ call
        self._source = source
        # >>>>

        super().__init__(host, port, timeout)
        self.file = None

    def open(self, host, port=0, timeout=15):
        # self.eof = 0
        if not port:
            port = TELNET_PORT

        self.host = host
        self.port = port
        self.timeout = timeout
        logging.info(f'{self._source} telnet socket create_connection {host}')
        self.sock = socket.create_connection((host, port), timeout, self._source)


class TelnetClient():
    username = None
    password = None

    def __init__(self, source, host, port, logger, config_file_path, on_retry=None):
        """
        :param source: 网卡IP
        :param host: 网关IP
        :param port: 端口
        :param logger:
        """
        self.cf = OperationConfig()
        self.source = source
        self.source_ = (source, 0)
        self.host = host
        self.port = port
        # self.tn = ''

        self.logger = logger
        self.config_file_path = config_file_path
        self.dingtalk = DingTalk()
        self.on_retry = on_retry

    def selected_scheme_path(self):
        # self.input_user_flag = self.cf.read_ini('telnet', 'input_user_flag',
        #                                         path=(self.config_file_path)).strip()
        # self.input_password_flag = self.cf.read_ini('telnet', 'input_password_flag',
        #                                             path=(self.config_file_path)).strip()
        # self.login_success_flag = self.cf.read_ini('telnet', 'login_success_flag',
        #                                            path=(self.config_file_path)).strip()
        # return True
        try:
            # self.logger.info('selected_scheme_path')
            self.input_user_flag = self.cf.read_ini('telnet', 'input_user_flag',
                                                    path='./config/' + self.config_file_path).strip()
            self.input_password_flag = self.cf.read_ini('telnet', 'input_password_flag',
                                                        path='./config/' + self.config_file_path).strip()
            self.login_success_flag = self.cf.read_ini('telnet', 'login_success_flag',
                                                       path='./config/' + self.config_file_path).strip()
            self.telnet_need_enter_password_flag = self.cf.read_ini('telnet', 'telnet_need_enter_password_flag',
                                                                    path='./config/' + self.config_file_path).strip()

            self.command_execute_fail_interval_time = int(self.cf.read_ini('other_config',
                                                                           'command_fail_retry_interval_time',
                                                                           path='./config/config.ini').strip())
            self.telnet_no_user_password_flag = int(self.cf.read_ini('telnet', 'telnet_no_user_password_flag',
                                                                     path='./config/' + self.config_file_path).strip())

        except Exception as e:
            self.logger.error(f'读取配置文件数据错误：{e}')
            return False
        else:
            self.logger.info(f'selected_scheme_path: {self.config_file_path}')
            return True

    # 此函数实现telnet登录主机
    def login_host(self, host_ip, username, password, file_no):
        if self.selected_scheme_path():
            try:
                self.logger.info(f'{self.source}  telnet init)')
                self.tn = TelnetEngine(self.source_, self.host, self.port)
                # self.tn.open(host_ip)
                # if not self.tn.open(host_ip):
                #     return False
                # self.logger.info(str(type(self.tn.get_socket())))
                self.logger.info(f'{self.source} telnet init success')
                file_no.write(f'{self.source} telnet init success\n'.encode())
            except Exception as e:
                self.logger.info(f'{self.source} telnet初始化失败：{e} {type(e)}')
                if 'out' in str(e):
                    file_no.write(f'{self.source} telnet初始化失败：{e} {type(e)}\n'.encode())
                    return 2
                else:
                    file_no.write(f'{self.source} telnet初始化失败：{e} {type(e)}\n'.encode())
                    return False
            else:
                print('aaaaaaaaaaa', TelnetClient.username, TelnetClient.password)
                if self.begin_login(TelnetClient.username, TelnetClient.password, file_no):
                    return True
                else:
                    return False
        else:
            return False

    def begin_login(self, username, password, file_no):
        try:
            self.file = file_no
            if int(self.telnet_no_user_password_flag) == 1:
                self.tn.write(b'\n')
                response_01 = self.tn.read_until(self.login_success_flag.encode(), timeout=3)
                print(response_01)
                if '#'.encode() in response_01:
                    return True
            if int(self.telnet_need_enter_password_flag) == 1:
                self.tn.write(b'\n')
                time.sleep(0.5)
                command_result = self.tn.read_very_eager().decode('utf-8')
                self.logger.info(command_result)
                self.tn.write(b'\n')
                # time.sleep(0.5)
                response_01 = self.tn.read_until(self.input_user_flag.encode(), timeout=10)
                print(response_01)
                if '#'.encode() in response_01:
                    return True

            # time.sleep(5)
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            file_no.write(f'{timestamp} 获取输入用户名的标志\n'.encode())
            response_01 = self.tn.read_until(self.input_user_flag.encode(), timeout=150)
            if response_01.endswith(self.input_user_flag.encode()):
                self.logger.info(f'{self.source} input username :{username}')
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                file_no.write(f'{timestamp} {self.source} input username :{username}\n'.encode())
                self.tn.write(username.encode() + b'\n')
                time.sleep(0.5)
            else:
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))

                self.logger.error(f'{self.source} input_user_flag error：{response_01}')
                file_no.write(f'{timestamp} {self.source} input_user_flag error：{response_01}\n'.encode())
                return False
            # 等待Password出现后输入用户名，最多等待10秒
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            file_no.write(f'{timestamp} 获取输入密码的标志\n'.encode())
            response_02 = self.tn.read_until(self.input_password_flag.encode(), timeout=10)
            # self.logger.info(self.input_password_flag)
            if self.input_password_flag in response_02.decode():
                self.logger.info(f'{self.source} Input password :{password}')
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))

                file_no.write(f'{timestamp} {self.source} Input password :{password}\n'.encode())
                self.tn.write(password.encode() + b'\n')
                time.sleep(0.5)
            else:
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                file_no.write(f'{timestamp} {self.source} input_password_flag error：{response_02}\n'.encode())
                self.logger.error(f'{self.source} input_password_flag error：{response_02}')
                return False
            # self.logger.info('1111')
            # 延时两秒再收取返回结果，给服务端足够响应时间
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            file_no.write(f'{timestamp} 获取登录成功的标志\n'.encode())
            time.sleep(0.5)
            response_03 = self.tn.read_until(self.login_success_flag.encode(), timeout=20)
            if response_03.endswith(self.login_success_flag.encode()):
                self.logger.info('%s登录成功' % self.source)
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                file_no.write(f'{timestamp} {self.source} 登录成功\n'.encode())
                # time.sleep(1)
                if '>' == self.login_success_flag:
                    login_after_input_str = self.cf.read_ini('telnet', 'login_after_input_str',
                                                             path='./config/' + self.config_file_path).strip()
                    self.tn.write(login_after_input_str.encode() + b'\n')
                    print('执行 ', login_after_input_str)
                    file_no.write(f'login_after_input_str ：{login_after_input_str}\n'.encode())
                    time.sleep(0.5)
                return True
            elif 'Login incorrect' in response_03.decode():
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                self.logger.info(f'{self.source} 登录失败，用户名或密码错误:{response_03}\n')
                file_no.write(f'{timestamp} {self.source} 登录失败，用户名或密码错误:{response_03}\n'.encode())
                self.tn.close()
                return False

            else:
                timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                self.logger.info('%s获取登录标志失败' % self.source)
                file_no.write(f'{timestamp} {self.source} 获取登录标志失败：{response_03}\n'.encode())
                for i in range(2, 7):
                    self.tn.write(b'\n')
                    time.sleep(0.5)
                    response_03 = self.tn.read_until(self.login_success_flag.encode(), timeout=20)
                    if response_03.endswith(self.login_success_flag.encode()):
                        self.logger.info('%s登录成功' % self.source)
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        file_no.write(f'{timestamp} {self.source} 登录成功\n'.encode())
                        # time.sleep(1)
                        if '>' == self.login_success_flag:
                            login_after_input_str = self.cf.read_ini('telnet', 'login_after_input_str',
                                                                     path='./config/' + self.config_file_path).strip()
                            self.tn.write(login_after_input_str.encode() + b'\n')
                            print('执行 ', login_after_input_str)
                            file_no.write(f'login_after_input_str ：{login_after_input_str}\n'.encode())
                            time.sleep(1)
                        return True
                    else:
                        timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
                        self.logger.info('%s登录失败' % self.source)
                        file_no.write(f'{timestamp} {self.source} {i}次获取登录标志失败：{response_03}\n'.encode())
                return False

        except Exception as e:
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            self.logger.error(f'telnet 登录失败：{e}')
            file_no.write(f'{timestamp} telnet 登录失败:{e}\n'.encode())
            return False

    def execute_some_command(self, command, wait_time=2):
        # 执行命令

        try:
            self.tn.write(command.encode() + b'\n')
            timestamp = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
            print(f'{timestamp}   执行{command}')
            time.sleep(wait_time)
            command_result = self.tn.read_very_eager().decode('utf-8', errors='replace').strip()
            self.logger.info(
                command + '执行结果：' + command_result + "\n长度：" + str(len(command_result)))
            return command_result
        except Exception as e:
            self.logger.error(f'执行指令错误时发生异常：{e}')
            return False

    def execute_some_command_01(self, command, waittime):
        """
        命令执行的结果前面包含了 }'
        :param command:
        :param waittime:
        :return:
        """
        try:
            # command = 'ubus call ctcapd.initd status'
            self.tn.write(command.encode() + b'\n')
            print(f'执行{command}')
            time.sleep(waittime)
            # 获取命令结果
            command_result = self.tn.read_very_eager().decode('utf-8').strip()
            self.logger.info(command_result)
            command_result1 = ''.join(command_result.split("}\'")[1:])
            result_json = json.loads(command_result1.replace(" ", "").replace("/#", ""))
            self.logger.info(result_json)
            return result_json
        except Exception as e:
            self.logger.info('错误信息：{}'.format(e))

    def execute_some_command_02(self, command, waittime):
        """
        命令执行的结果前面包含了 '
        :param command:
        :param waittime:
        :return:
        """
        re.compile('')
        try:
            # command = 'ubus call ctcapd.initd status'
            self.tn.write(command.encode() + b'\n')
            time.sleep(waittime)
            # 获取命令结果
            command_result = self.tn.read_very_eager().decode('utf-8')
            command_result1 = ''.join(command_result.split("\r\n\'")[1:])
            # print(command_result1)
            result_json = json.loads(command_result1.replace(" ", "").replace("/#", ""))
            # print(result_json)
            self.logger.info('执行结果：{}'.format(result_json))
            return result_json
        except Exception as e:
            self.logger.info('错误信息：{}'.format(e))

    def sleep_time(self, power_num, times):
        """
        判断是否是外部停止
        """
        count = 0
        times = int(times) * 2
        from test_case.powe_on_off_telnet import PowerOnOffTelnet
        while True:
            run_flag = PowerOnOffTelnet.get_current_flag(PowerOnOffTelnet, power_num)
            if run_flag == 0:
                return True
            if count == times:
                return False
            time.sleep(0.5)
            count += 1

    def execute_some_command_iwconfig_all(self, f, command, value, wait_time, execute_times, device_type, power_num):
        times = 1
        flag = 0

        f.write(f'开始执行指令： {command}\n'.encode())
        while execute_times >= times:
            print('1111111111111111')
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            f.write(f'\n{timestamp} ：第{times}次执行 {command} 指令 ===============================》\n\n'.encode())
            response = self.execute_some_command_iwconfig(f, command, wait_time, power_num, value)
            if response is False:
                if times < execute_times and callable(self.on_retry):
                    self.on_retry(command, times, execute_times)
                times += 1
                # 指令执行失败之后等待10s再去执行下一次
                if self.sleep_time(power_num, self.command_execute_fail_interval_time, ):
                    return True
                self.login_host(self.host, username='username', password='password', file_no=f)
            else:
                if Fuzzy_Match(command, value, response, f):
                    flag = 1
                    break
                else:
                    if times < execute_times and callable(self.on_retry):
                        self.on_retry(command, times, execute_times)
                    if times == 1:
                        # 发送钉钉消息到 2025.0104
                        dingtalk_result = self.dingtalk.webhook_send_message(device_type,
                                                                             f'通道 {power_num} 执行指令：{command} ，在第一次时出现错误')
                    times += 1
                    # 指令执行失败之后等待10s再去执行下一次
                    time.sleep(self.command_execute_fail_interval_time)
        f.write('\n'.encode() + '*'.encode() * 150 + '\n\n'.encode())
        if flag:
            return times
        else:
            return False

    def execute_some_command_iwconfig(self, f, command, wait_time, power_num, value):
        """
        f:记录命令的文件
        command：命令
        waittime:执行命令所需时间
        """
        try:
            self.tn.write(command.encode() + b'\n')
            timestamp = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
            print(f'{timestamp}   执行{command}:{wait_time}')
            f.write((timestamp + ' : 执行' + command + '\n').encode())
            if self.sleep_time(wait_time, power_num):
                return True
            output = b""
            while True:
                chunk = self.tn.read_very_eager()
                if not chunk:
                    break
                output += chunk
                time.sleep(0.1)  # 避免忙等
            # 修改为等待结果出现
            # output = self.tn.read_until(value.encode(), timeout=wait_time)

            command_result = output.decode('utf-8', errors='replace').strip()
            # command_result = self.tn.read_very_eager().decode('gbk').strip()
            self.logger.info(
                command + f'在通道{power_num}:执行结果：' + command_result + "\n长度：" + str(len(command_result)))
            f.write(
                (command + f'在通道{power_num}:执行结果：' + command_result + "\n长度：" + str(len(command_result)) + '\n').encode())
            return command_result

        except Exception as e:
            f.write((command + f'在通道{power_num}:执行错误时发生异常:{e}'
                     + '\n').encode())
            self.logger.error(command + f'在通道{power_num}:执行错误时发生异常:{e}')
            return False

    def execute_read_until(self, command, timeout=10, stable_time=2):
        """
        执行命令，等待返回完整的执行结果后再返回

        :param command: 要执行的命令
        :param timeout: 总超时上限（秒），防止死循环
        :param stable_time: 数据稳定时间（秒），连续 stable_time 秒没有新数据认为命令执行完成
        """
        try:
            # 1) 写入前先把 buffer 里的残留数据清空，避免上一次命令的残余混入本次结果
            try:
                self.tn.read_very_eager()
            except Exception:
                pass

            # 2) 发送命令
            self.tn.write(command.encode() + b'\n')

            # 3) 循环读取：只要 socket 里有数据就一直读，直到"连续 stable_time 秒没有新数据"
            start_time = time.time()
            output = b""
            last_data_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    chunk = self.tn.read_very_eager()
                    if chunk:
                        output += chunk
                        last_data_time = time.time()  # 有新数据，重置稳定计时
                    else:
                        # 已经读到过数据，且连续 stable_time 秒没有新数据 → 认为命令执行完毕
                        if output and (time.time() - last_data_time) > stable_time:
                            break
                except Exception:
                    break
                time.sleep(0.1)

            command_result = output.decode('utf-8', errors='replace').strip()
            self.logger.info(
                command + '执行结果：' + command_result + "\n长度：" + str(len(command_result)))
            self.file.write(
                (command + '执行结果：' + command_result + "\n长度：" + str(len(command_result)) + '\n').encode())
            return command_result

        except Exception as e:
            self.file.write((command + f'执行指令错误时发生异常:{e}'
                             + '\n').encode())
            self.logger.error(f'执行指令错误时发生异常：{e}')
            return False

    # def execute_read_until(self, command):
    #     try:
    #         self.tn.write(command.encode() + b'\n')
    #         # 获取命令结果
    #         # command_result = self.tn.read_until(self.login_success_flag.encode(),timeout=10)
    #         # time.sleep(5)
    #         output = b""
    #         while True:
    #             chunk = self.tn.read_all()
    #             if not chunk:
    #                 break
    #             output += chunk
    #             time.sleep(0.1)  # 避免忙等
    #         command_result = output.decode('utf-8', errors='replace').strip()
    #         self.logger.info(
    #             command + '执行结果：' + command_result + "\n长度：" + str(len(command_result)))
    #         self.file.write(
    #             (command + '执行结果：' + command_result + "\n长度：" + str(len(command_result)) + '\n').encode())
    #         return command_result
    #
    #     except Exception as e:
    #         self.file.write((command + f'执行指令错误时发生异常:{e}'
    #                  + '\n').encode())
    #         self.logger.error(f'执行指令错误时发生异常：{e}')
    #         return False

    # 退出telnet
    def logout_host(self):
        self.tn.write(b"exit\n")
        time.sleep(0.5)
        self.tn.close()

    def get_status(self):
        socket = self.tn.get_socket()
        fileno = self.tn.fileno()
        print(f'执行指令之前 get_socket() :{socket} 和 fileno() :{fileno} 查看 telnet 连接状态')
        return socket, fileno


if __name__ == "__main__":
    f = open('a.txt', 'wb', buffering=0)

    device_ip = '192.168.29.179'
    gateway_ip = '192.169.29.1'
    username = 'sdmc'
    password = '1234'
    # Web_Page_Open_Telnet('192.168.1.2', 'http://192.168.1.1/ubus/xlink.system.TelnetSet')
    # Web_Page_Open_Telnet('192.168.1.3', 'http://192.168.1.1/cgi-bin/sdmctelnet_enable.asp', f)
    logger = creat_logger('AX3000999_')
    tel = TelnetClient(device_ip, gateway_ip, 23, logger, config_file_path='../config/NP5487G_config.ini')
    tel.login_host(device_ip, username, password, f)
    # tel.execute_some_command("ubus call ctcapd.wifi.timer add \'{\"weekday\":\"1\",\"time\":\"09:30\",\"enable\":\"no\"}\'",5)
    a = tel.execute_some_command_iwconfig(f, 'ps', 2)
    print(a)
    # a = tel.execute_some_command_iwconfig(f, chr(0x13), 2)
    # print(a)
    # print(type(a))
    # pattern = re.compile(r' (\d+)')
    # for i in a.split('\n'):
    #     # print(i)
    #     if 'bytesReceived' in i:
    #         print(pattern.search(i).group(1))
    #
    # a = tel.execute_some_command_iwconfig(f, 'ubus call xlink.wan netstate_get ', 2)
    # print(type(a))
    # print('"txRate": 1' in a)
    #
    # a = tel.execute_some_command_iwconfig(f, 'ubus call xlink.wan ipv4Get ', 2)
    # print(type(a))
    # print('"txRate": 1' in a)
    # tel = TelnetClient('192.168.1.3', '192.168.1.1', 23, logger, config_file_path='../config/NP1257GB_config.ini')
    # tel.login_host('192.168.1.1', 'sdmc', '1234')
    # # tel.execute_some_command("ubus call ctcapd.wifi.timer add \'{\"weekday\":\"1\",\"time\":\"09:30\",\"enable\":\"no\"}\'",5)
    # tel.execute_some_command_iwconfig('ifconfig br0', 2)
    # tel.execute_some_command_iwconfig('cat /proc/version', 2)

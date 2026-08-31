import time

import paramiko
import socket
import paramiko.transport
from paramiko.ssh_exception import SSHException

from common.fuzzy_match import Fuzzy_Match
from common.power_on_off import PowerOnOff
from common.my_logging import creat_logger
from common.serilal_client import Serial
from common.execute_network_card_ping import Cmd
from common.create_float_data import create_float_num
from config.config_driver import OperationConfig


class SSHClient():
    ssh_client = None

    def __init__(
        self,
        ip,
        username,
        password,
        source='',
        port=1288,
        timeout=50,
        logger='',
        file='',
        on_retry=None,
    ):
        """

        :param ip: 设备网关IP 192.168.1.1
        :param username: ssh登录用户名
        :param password: ssh登录密码
        :param logger: log
        :param source: 网卡IP
        :param port: SSH 端口号
        :param timeout: 超时
        """
        file.write(f"实例化 SSH\n".encode())
        self.ip = ip
        self.username = username
        self.password = password
        self.port = int(port)
        self.timeout = timeout
        self.source = source
        self.logger = logger
        self.file = file
        self.on_retry = on_retry
        self.cf = OperationConfig()
        # self.logger.info('设置banner_timeout')
        # transport = paramiko.Transport((self.ip, self.port))
        # self.logger.info(f"当前banner_timeout:{transport.banner_timeout}")
        # self.file.write(f"当前banner_timeout:{transport.banner_timeout}\n".encode())
        # print(transport.banner_timeout)
        # transport.banner_timeout = 50
        # print(transport.banner_timeout)
        # self.logger.info(f"设置banner_timeout:{transport.banner_timeout}")
        # self.file.write(f"\n".encode())
        # 初始化SSH 客户端
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client = ssh_client
        # 创建socket
        self.socket = socket.socket()
        # # 设置超时时间
        self.socket.settimeout(30)
        socket_timeout = self.socket.gettimeout()
        self.file.write(f"创建socket，设置socket_timeout:{socket_timeout}\n".encode())

    def selected_scheme_path(self):
        # self.input_user_flag = self.cf.read_ini('telnet', 'input_user_flag',
        #                                         path=(self.config_file_path)).strip()
        # self.input_password_flag = self.cf.read_ini('telnet', 'input_password_flag',
        #                                             path=(self.config_file_path)).strip()
        # self.login_success_flag = self.cf.read_ini('telnet', 'login_success_flag',
        #                                            path=(self.config_file_path)).strip()
        # return True
        try:
            self.command_execute_fail_interval_time = int(self.cf.read_ini('other_config',
                                                                           'command_fail_retry_interval_time',
                                                                           path='./config/config.ini').strip())
        except Exception as e:
            self.logger.error(f'读取配置文件数据错误：{e}')
            return False
        else:
            self.logger.info(f'selected_scheme_path: {"./config/config.ini"}')
            return True

    def connect_ssh(self):
        self.selected_scheme_path()
        retry_times = int(
            self.cf.read_ini('other_config', 'SSH_connect_fail_retry_times', './config/config.ini'))
        interval_time = int(
            self.cf.read_ini('other_config', 'SSH_connect_fail_retry_interval', './config/config.ini'))

        self.file.write(f'\n\nSSH 连接异常时的：retry_times: {retry_times}，interval_time: {interval_time}\n\n'.encode())
        times = 1
        while True:
            try:
                print(self.username, self.port, self.password, self.source, self.ip, self.timeout, type(self.username),
                      type(self.port),
                      type(self.password), type(self.source), type(self.ip), type(self.timeout))

                self.logger.info(f'ssh from {self.source} to {self.ip}.')
                self.file.write(f'ssh from {self.source} to {self.ip}.\n'.encode())

                time.sleep(0.1)
                # 当我们不需要确定的服务端口时，我们就可以让ip=0
                self.socket.bind((self.source, 0))
                time.sleep(0.1)
                self.logger.info(f"bind {self.source}")
                self.file.write(f"bind {self.source}\n".encode())
                time.sleep(0.1)
                # 连接网关IP
                # time.sleep(1)
                # 更换连接方式
                self.socket.connect((self.ip, int(self.port)))
                self.logger.info(f"socket connect {self.source}")
                self.file.write(f"socket connect {self.source},timeout: {self.timeout}\n".encode())

                self.ssh_client.connect(hostname=self.ip, port=self.port, username=self.username,
                                        password=self.password,
                                        timeout=int(self.timeout), sock=self.socket)
                print(self.ssh_client)
                self.file.write(f'{self.ssh_client}\n'.encode())

            except Exception as e:
                self.ssh_client.close()
                self.socket.close()
                self.logger.info(f'{self.source}创建SSH 失败： {e}')
                self.file.write(
                    f'@@@@@@@@@@@@@@@@@@   {self.source} 第 {times}创建SSH 失败@@@@@@@@@@@@@@@@@@ ： {e}\n'.encode())
                times += 1
                self.file.write(f'\n {self.source} 开始第 {times}次尝试创建SSH \n'.encode())

                if times > retry_times:
                    return False
                else:
                    time.sleep(interval_time)
                    # 重新创建套接字
                    self.socket = socket.socket()
                    continue

            else:
                if self.ssh_client:
                    time.sleep(0.1)
                    self.logger.info('SSH login ok！')
                    time.sleep(0.1)
                    return self.ssh_client
                else:
                    self.close()
                    return False

    def exec_commands(self, command, timeout):
        if command:
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
            return stdout
        else:
            self.close()
            raise Exception("The command cannot be an empty string.")

    def exec_ShellCommand_all(self, f, command, value, timeout, execute_times):
        times = 1
        flag = 0
        f.write(f'开始执行指令： {command}\n'.encode())
        while execute_times >= times:
            timestamp = time.strftime('%Y-%m-%d-%H:%M:%S', time.localtime(time.time()))
            f.write(f'\n{timestamp}：第{times}次执行 {command} 指令 ===============================》\n\n'.encode())
            response = self.exec_ShellCommand(f, command, timeout)
            if response is False:
                if times < execute_times and callable(self.on_retry):
                    self.on_retry(command, times, execute_times)
                times += 1
                time.sleep(self.command_execute_fail_interval_time)
            else:
                if Fuzzy_Match(command, value, response, f):
                    flag = 1
                    break
                else:
                    if times < execute_times and callable(self.on_retry):
                        self.on_retry(command, times, execute_times)
                    times += 1
                    time.sleep(self.command_execute_fail_interval_time)

        f.write('\n'.encode() + '*'.encode() * 150 + '\n\n'.encode())
        if flag:
            return times
        else:
            return False

    def exec_ShellCommand(self, f, command, timeout=2):
        if command:
            print('aaa')
            print(self.ssh_client)
            self.shell = self.ssh_client.invoke_shell()

            # # #发指令前输入回车，以免没有进入输入指令的那个地方
            print(self.shell)
            self.shell.send('\n'.encode())
            if timeout > 5:
                self.shell.settimeout(timeout)
            else:
                self.shell.settimeout(5)
            print(2323)
            f.write(f'开始执行指令：{command}\n'.encode())
            self.shell.send(command.encode('UTF-8') + '\n'.encode('UTF-8'))
            response = ''
            command_count = 0

            while True:
                try:
                    # print("-------recv data---------")
                    # 增大recv字节
                    recv = self.shell.recv(1024).decode('utf-8')
                    command_count += 1
                    # print("-------recv data---------")
                    if recv:
                        if len(recv):
                            # print("-------------respon data -----------", recv)
                            response += recv
                    else:
                        # print(f"{command} recv {recv}")
                        time.sleep(1)
                        if command_count > 10:
                            break
                        continue
                except:
                    # if command=="restore_default":
                    #     print("--------into except-----------")
                    #     #command = input(">>>") + "\n"
                    #     shell.send(command)
                    # print("--------except------------")
                    # return self.response
                    break
            # self.shell.close()
            f.write(f'指令执行结果：{response}\n'.encode())
            print(f"{command} 执行结束")
            # print("the respon is:",self.response)
            return response

    def close(self):
        """
        关闭当前连接
        :return:
        """
        try:
            if self.ssh_client:
                self.ssh_client.close()
                time.sleep(1)
                self.socket.close()
        except Exception as e:
            # print(str(e))
            time.sleep(0.1)
            self.logger.error(f"ssh shutdown failed. The current object does not have an ssh connection：{e}")
            time.sleep(0.1)
            # raise Exception("ssh shutdown failed. The current object does not have an ssh connection.")


if __name__ == '__main__':
    with open('command_result_log.txt', 'wb', buffering=0) as f:
        logger = creat_logger('power_test')
        # power_control = PowerOnOff(logger)
        # ser = Serial('com16', '19200', logger)
        # power_control.power_all_off(ser)
        # time.sleep(2)
        # power_control.power_on(ser, 1)
        # power_control.power_on(ser, 8)
        # time.sleep(180)
        ssh = SSHClient('192.168.1.1', "altfactory", "pPRodU6c17!0nN", '192.168.1.105', 1288, timeout=50, logger=logger,
                        file=f)
        ssh.connect_ssh()
        # print(ssh.exec_commands('echo ; sys memrl bfb80050\n'))
        # print(ssh.exec_commands('echo ; dmesg -c\n').readlines())
        # result=ssh.exec_commands('restore_default_full', 10)
        # print(result)

        # ssh.exec_ShellCommand('\n')
        result = ssh.exec_ShellCommand(f, 'restore_default_full', timeout=10)
        print(result)
        # # print('----------')
        # ssh.exec_ShellCommand('echo ; sys memrl bfb80050\n', f)
        # # print('----------')
        # result_list = ssh.exec_ShellCommand('echo ; dmesg -c\n', f).split('\r\n')
        # print(ssh.exec_ShellCommand('echo ; dmesg -c\n').split('\r\n'))

        # for i in result_list:
        #     if '00006' in i:
        #         print(True)
        #     if '0xbfb80050' in i:
        #         print(i.split()[-1][-1])
        # mac = ssh.exec_ShellCommand('ifconfig ra0\n', f).split('\r\n')
        # print(mac)

        # ssh = SSHClient('192.168.1.1', "altfactory", "pPRodU6c17!0nN", '192.168.1.28', 1288)
        # ssh.connect_ssh()
        # # print(ssh.exec_commands('echo ; sys memrl bfb80050\n'))
        # # print(ssh.exec_commands('echo ; dmesg -c\n').readlines())
        #
        # # ssh.exec_ShellCommand('\n')
        # ssh.exec_ShellCommand('echo ; dmesg -c\n')
        # # print('----------')
        # ssh.exec_ShellCommand('echo ; sys memrl bfb80050\n')
        # # print('----------')
        # result_list = ssh.exec_ShellCommand('echo ; dmesg -c\n').split('\r\n')
        # # print(ssh.exec_ShellCommand('echo ; dmesg -c\n').split('\r\n'))
        # for i in result_list:
        #     if '00006' in i:
        #         print(True)
        # mac = ssh.exec_ShellCommand('ifconfig br0\n').split('\r\n')
        # print(mac)

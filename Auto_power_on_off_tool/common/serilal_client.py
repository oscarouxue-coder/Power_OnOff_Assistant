import time
import os
from threading import Thread
import serial
import serial.tools.list_ports
from common.my_logging import creat_logger


# from config.config_driver import OperationConfig


class Serial(object):
    def __init__(self, portx, bps, logger, timeout=5):
        """
        :param portx:com口
        :param bps: 设备波特率
        :param timex: timeout是指在设定的timeout时间范围内，如果读取的字节数据是有效的（就是非空）那就直接返回，
        否则一直会等到这个设定的timeout时间并返回这段时间所读的全部字节数据；
        """
        # 连接串口后，第一行就读取到了 password：,就跳过，当先读取到login： 在读取到 password后才能将flag=1
        self.flag = 0
        # 登录失败的次数
        self.login_error_times = 0
        # 串口登录成功的标志，成功之后才
        self.login_success_flag = 0
        self.serial_create_flag = 0
        # self.cf = OperationConfig()
        # 打开串口，并得到串口对象
        self.logger = logger
        self.port = portx
        # 线程停止串口
        self.logger.info(f'Opening serial port {portx} ')
        self.ser = serial.Serial(portx, int(bps), timeout=int(timeout))

        self.serial_create_flag = 1
        # self.cpu_memory_monitor_file = open(self.cpu_memory_monitor_filename, 'ab', buffering=0)
        # self.logger.info('串口：{} is_open'.format(portx))
        self.logger.info('serial port:{} is_open'.format(portx))
        # 串口指令列表
        self.command_list = []

    def __del__(self):
        # self.log_filename.close()
        # self.cpu_memory_monitor_file.close()
        # self.ser.write(chr(0x03))
        self.ser.close()

    def write(self, cmd):
        self.ser.write(cmd)

    def serial_write(self, cmd):
        cmd = cmd.encode('utf-8') + b'\n'
        self.ser.write(cmd)
        time.sleep(0.2)

    def serial_write_byte(self, cmd):
        """
        接收从GUI发送过来的指令
        :param cmd:
        :return:
        """
        cmd = cmd + b'\n'
        self.ser.write(cmd)

    def read_all(self):
        return self.ser.read_all()

    def serial_close(self):
        # self.logger.info('------关闭串口:{}---------'.format(self.ser.port))
        self.logger.info('------close the serial port:{}---------'.format(self.ser.port))
        # self.serial_log_file.close()
        # self.cpu_memory_monitor_file.close()
        # self.ser.write(chr(0x03))
        self.ser.close()
        # self.logger.info('{}串口状态：{}'.format(self.ser.port, self.ser.is_open))
        self.logger.info('{}serial status：{}'.format(self.ser.port, self.ser.is_open))

    def is_open(self):
        if self.ser.isOpen():
            print('串口已经打开')
            return True
        else:
            print('串口未打开')
            self.ser.open()
            return False


if __name__ == "__main__":
    logger = creat_logger('AX3000t_Mmaster_serial')
    # ser1 = Serial('COM6', 19800, 2, 'telecomadmin', 'nE7jA%5m', 'login:', 'Password:', '#', logger)
    ser1 = Serial('COM6', 19800, 2, 'telecomadmin')

    while True:
        if ser1.serial_create_flag:
            t1 = Thread(target=ser1.write_log_file)
            t1.start()
            if ser1.connect_serial():
                ser1.serial_write('ifconfig')
                time.sleep(1)
                break
        else:
            break

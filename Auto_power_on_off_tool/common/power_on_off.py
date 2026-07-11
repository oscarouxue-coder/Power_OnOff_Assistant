import time
import queue
from common.my_logging import creat_logger
from common.serilal_client import Serial


class PowerOnOff(object):
    stopthreadevent = 0
    def __init__(self, logger):
        self.logger = logger
        self.interval = 1  # 200毫秒

        self.PowerTaskQueue = queue.Queue()
        self.switch_status_list = [0] * 16

    def set_interval(self, interval):
        self.interval = interval

    def producer(self, task_turple):
        ''''
        调用方法 Poo = PowerOnOff()
        poo.set_interval(1)
        poo.producer((poo.power_on(), ser, num))
        '''
        # print(f"生产者存入数据{task_turple[0].__name__}_串口操作开关序号{task_turple[2]}") #(power_on[power_off], ser, num)
        self.PowerTaskQueue.put(task_turple)  # 生产者线程函数,向队列存入数据
        print('我在生产。。。。。。。。。')

    def consumer(self):
        '''
        # 消费者线程,从队列取出数据,需要用独立线程执行,不要包含在别的线程内,主线程起来之后就调用
        t1 = threading.Thread(target=consumer)
        t1.start()
        # 等待线程结束
        t1.join()

        '''
        while True:
            if self.stopthreadevent == 1:
                break
            time.sleep(self.interval)
            (task, ser, num) = self.PowerTaskQueue.get()
            print('self.stopthreadevent',self.stopthreadevent)
            task(ser, num)
            self.PowerTaskQueue.task_done()
            # print("消费者取出数据")

    def power_on(self, ser, num):
        ch_open = []
        ch_close = []
        if num == 1:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x01, 0xA0]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x01, 0xA1]
        elif num == 2:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x02, 0xA3]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x02, 0xA2]
        elif num == 3:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x03, 0xA2]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x03, 0xA3]

        elif num == 4:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x04, 0xA5]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x04, 0xA4]
        elif num == 5:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x05, 0xA4]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x05, 0xA5]
        elif num == 6:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x06, 0xA7]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x06, 0xA6]

        elif num == 7:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x07, 0xA6]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x07, 0xA7]

        elif num == 8:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x08, 0xA9]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x08, 0xA8]

        elif num == 9:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x09, 0xA8]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x09, 0xA9]

        elif num == 10:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x0A, 0xAB]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x0A, 0xAA]

        elif num == 11:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x0B, 0xAA]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x0B, 0xAB]

        elif num == 12:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0C, 0XAD]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0C, 0XAC]

        elif num == 13:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0D, 0XAC]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0D, 0XAD]

        elif num == 14:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0E, 0XAF]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0E, 0XAE]

        elif num == 15:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0F, 0XAE]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0F, 0XAF]
        elif num == 16:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x10, 0xB1]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x10, 0xB0]

        # 避免误操作
        if self.switch_status_list[num - 1] == 1:
            return

        else:
            if self.switch_status_list[num - 1] == 0:
                self.switch_status_list[num - 1] = 1

        # while True:
        # 通道开
        byte_data = bytearray(ch_open)
        write_len = ser.write(byte_data)
        time.sleep(3)
        # self.logger.info(f'通道{num}开')
        self.logger.info(f'channel {num} open')

    def power_off(self, ser, num):
        ch_open = []
        ch_close = []
        if num == 1:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x01, 0xA0]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x01, 0xA1]
        elif num == 2:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x02, 0xA3]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x02, 0xA2]
        elif num == 3:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x03, 0xA2]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x03, 0xA3]

        elif num == 4:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x04, 0xA5]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x04, 0xA4]
        elif num == 5:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x05, 0xA4]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x05, 0xA5]
        elif num == 6:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x06, 0xA7]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x06, 0xA6]

        elif num == 7:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x07, 0xA6]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x07, 0xA7]

        elif num == 8:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x08, 0xA9]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x08, 0xA8]

        elif num == 9:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x09, 0xA8]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x09, 0xA9]

        elif num == 10:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x0A, 0xAB]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x0A, 0xAA]

        elif num == 11:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x0B, 0xAA]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x0B, 0xAB]

        elif num == 12:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0C, 0XAD]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0C, 0XAC]
        elif num == 13:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0D, 0XAC]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0D, 0XAD]
        elif num == 14:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0E, 0XAF]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0E, 0XAE]

        elif num == 15:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0X0F, 0XAE]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0X0F, 0XAF]
        elif num == 16:
            ch_open = [0x55, 0x01, 0xA0, 0x00, 0x10, 0xB1]
            ch_close = [0x55, 0x01, 0xA1, 0x00, 0x10, 0xB0]

        # 避免误操作
        if self.switch_status_list[num - 1] == 0:
            return
        else:
            self.switch_status_list[num - 1] = 0

        # while True:
        # 通道开
        ch_open = [0x55, 0x00, 0xac, 0x00, 0x00, 0xac]
        byte_data = bytearray(ch_close)
        write_len = ser.write(byte_data)
        time.sleep(0.5)
        self.logger.info(f'通道{num}关')
        print('通道{num}关')

    def power_all_on(self, ser):
        # ch_open = '55 00 AC 00 00 AC'
        # ch_open = [55, 00, ac, 00, 00, ac]
        ch_open = [0x55, 0x00, 0xac, 0x00, 0x00, 0xac]
        byte_data = bytearray(ch_open)
        ser.write(ch_open)
        # ser.serial_write(ch_open)
        time.sleep(0.5)
        # self.logger.info(f'所有通道开')
        self.logger.info(f'all channels open')

        self.switch_status_list = [1] * 16

    def power_all_off(self, ser):
        print("ser---", ser)
        # byte_data = '55 00 ad 00 00 ad'.encode()
        ch_close = [0x55, 0x00, 0xad, 0x00, 0x00, 0xad]
        byte_data = bytearray(ch_close)
        ser.write(byte_data)
        time.sleep(0.5)
        # self.logger.info(f'所有通道关')
        self.logger.info(f'all channels off')
        print(f'all channels off')
        self.switch_status_list = [0] * 16


#
# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    logger = creat_logger('test_power_control')
    ser = Serial('com16', '19200', logger)
    power = PowerOnOff(logger)
    power.power_all_off(ser)
    time.sleep(1)
    for i in range(1, 17):
        power.power_on(ser, i)
        time.sleep(1)
    # for i in range(1, 17):
    #     power.power_off(ser, i)
    #     time.sleep(1)
    # power.power_all_on(ser)
    # time.sleep(2)
    # power.power_all_off(ser)
    # time.sleep(1)
    # power.power_on(ser, 9)
    # time.sleep(0.5)
    # power.power_off(ser, 9)

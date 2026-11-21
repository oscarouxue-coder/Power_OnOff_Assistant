import time
import queue
from threading import Event
from common.my_logging import creat_logger
from common.serilal_client import Serial


class PowerCommandCancelled(InterruptedError):
    """The operator stopped the run before the channel could continue."""


class PowerCommandError(IOError):
    """The shared power port could not complete a queued command."""


class PowerOnOff(object):
    stopthreadevent = 0
    def __init__(self, logger):
        self.logger = logger
        self.interval = 1  # 200毫秒

        self.PowerTaskQueue = queue.Queue()
        self.switch_status_list = [0] * 16
        self.stop_event = None
        self._dispatch_error = ''

    def set_interval(self, interval):
        self.interval = interval

    def _stopping(self):
        return self.stopthreadevent or (self.stop_event is not None and self.stop_event.is_set())

    def _check_dispatch(self):
        if self._stopping():
            raise PowerCommandCancelled('用户已停止程控电源队列')
        if self._dispatch_error:
            raise PowerCommandError(self._dispatch_error)

    def producer(self, task_tuple):
        """Wait for this channel's write before starting its configured delay."""
        task, serial_port, channel = task_tuple
        written = Event()

        def dispatch():
            try:
                self._check_dispatch()
                if not written.is_set():
                    if task in (self.power_on, self.power_off):
                        task(serial_port, channel, on_written=written.set)
                    else:
                        task(serial_port, channel)
            except PowerCommandCancelled:
                pass
            except Exception as exc:
                self._dispatch_error = f'通道 {channel} 程控电源指令执行失败：{exc}'
                self.logger.error(self._dispatch_error)
            finally:
                # Includes a redundant on/off suppressed by the original state cache.
                written.set()

        self._check_dispatch()
        self.PowerTaskQueue.put(dispatch)
        try:
            while not written.wait(0.1):
                self._check_dispatch()
            self._check_dispatch()
        finally:
            written.set()

    def consumer(self):
        '''
        # 消费者线程,从队列取出数据,需要用独立线程执行,不要包含在别的线程内,主线程起来之后就调用
        t1 = threading.Thread(target=consumer)
        t1.start()
        # 等待线程结束
        t1.join()

        '''
        while not self._stopping() and not self._dispatch_error:
            time.sleep(self.interval)
            while not self._stopping():
                try:
                    dispatch = self.PowerTaskQueue.get(timeout=0.1)
                    break
                except queue.Empty:
                    continue
            else:
                return
            try:
                dispatch()
            finally:
                self.PowerTaskQueue.task_done()

    def power_on(self, ser, num, *, on_written=None):
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

        # while True:
        # 通道开
        byte_data = bytearray(ch_open)
        if on_written is not None:
            self._check_dispatch()
        ser.write(byte_data)
        self.switch_status_list[num - 1] = 1
        if on_written is not None:
            on_written()
        time.sleep(3)
        # self.logger.info(f'通道{num}开')
        self.logger.info(f'channel {num} open')

    def power_off(self, ser, num, *, on_written=None):
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

        # while True:
        # 通道开
        ch_open = [0x55, 0x00, 0xac, 0x00, 0x00, 0xac]
        byte_data = bytearray(ch_close)
        if on_written is not None:
            self._check_dispatch()
        ser.write(byte_data)
        self.switch_status_list[num - 1] = 0
        if on_written is not None:
            on_written()
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

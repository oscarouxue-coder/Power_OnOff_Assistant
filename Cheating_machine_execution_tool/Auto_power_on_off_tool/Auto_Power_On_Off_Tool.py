import datetime
import os.path
import queue
import random
import sys
import threading
import time

from PyQt5.QtCore import pyqtSignal, QTimer

from common.serilal_client import Serial
import serial.tools.list_ports
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QMessageBox, QWidget, QListView, QMainWindow
from UI.power_control_ui import Ui_MainWindow
from common.my_logging import creat_logger
from PyQt5 import QtWidgets
from common.stop_thread import StoppableThread
from test_case.powe_on_off_telnet import PowerOnOffTelnet
from test_case.power_on_off_ssh import PowerOnOffSsh
from config.config_driver import OperationConfig
from common.read_config_netword_card_ip import get_network_card_ip
from common.delete_files import FileDeleteWorker

from test_case.Onu_config import OnuCongfig


class UiCase(QMainWindow, Ui_MainWindow):
    show_signal = pyqtSignal(str)
    show_signal_error = pyqtSignal(str)

    def __init__(self):
        super(UiCase, self).__init__()

        self.stop_event = threading.Event()
        self.threads = []
        self.active_threads = {}  # 存储活动线程及其停止事件

        self.show_signal_error.connect(self.update_text_error)
        self.show_signal.connect(self.update_text)

        # self.delete_timer = QTimer()
        self.cf = OperationConfig()
        self.setupUi(self)
        self.port_list_name = []
        self.logger = creat_logger('Power_on_off')
        # 初始化ONU config 页面
        self.onu_config = OnuCongfig()
        self.onu_config.show_signal.connect(self.update_text)
        self.onu_config.show_signal_error.connect(self.update_text_error)

        # timestamp = time.strftime('%Y%m%d', time.localtime(time.time()))
        self.setWindowTitle(f'Auto_power_on_off_tool_V3.1_20260331')
        self.stop_thread = StoppableThread()
        self.setup()
        # 串口号出现冲突的标志
        self.conflict_flag = 0
        # 串口列表
        self.port_list = []
        # 基本信息
        self.serial_num = ''
        self.baud_rate = ''
        self.startup_need_time = 0
        self.interval_time = 0
        self.wait_command_done = 0
        self.test_number = 0
        self.username = ''
        self.password = ''
        self.recv_Email = []
        self.telnet_enable_flag = 0

        # 正在运行的线程
        self.thread_list = []
        self.stopthreadevent = 0

        # 初始化程控电源
        self.gen_power_control = ''

        self.comboBox_schemes.setStyleSheet("QAbstractItemView::item {height: 22px;}")
        self.comboBox_schemes.setView(QListView())
        self.comboBox_schemes.setStyleSheet("""
            QComboBox QAbstractItemView::item {
                padding-bottom: 2px;
                border-bottom: 1px solid black;
                color:black;

            }
        """)

        self.gen_power_control_list = [self.gen_power_control]
        # channel_elements
        self.channel_ui_list = [
            self.pushButton_power_1_channel_1, self.pushButton_power_1_channel_2, self.pushButton_power_1_channel_3,
            self.pushButton_power_1_channel_4,
            self.pushButton_power_1_channel_5, self.pushButton_power_1_channel_6, self.pushButton_power_1_channel_7,
            self.pushButton_power_1_channel_8,
            self.pushButton_power_1_channel_9, self.pushButton_power_1_channel_10, self.pushButton_power_1_channel_11,
            self.pushButton_power_1_channel_12,
            self.pushButton_power_1_channel_13, self.pushButton_power_1_channel_14, self.pushButton_power_1_channel_15,
            self.pushButton_power_1_channel_16]

        # # btn text
        # self.channel_btn_text_list=["Channel 1 Start","Channel 2 Start","Channel 3 Start","Channel 4 Start","Channel 5 Start",
        #                             "Channel 6 Start","Channel 7 Start","Channel 8 Start","Channel 1 Start","Channel 1 Start",
        #                             "Channel 1 Start","Channel 1 Start","Channel 1 Start","Channel 1 Start","Channel 1 Start",
        #                             "Channel 1 Start"]

        # channel_box elements
        self.channel_box_list = [self.checkBox_power_1_channel_1, self.checkBox_power_1_channel_2,
                                 self.checkBox_power_1_channel_3, self.checkBox_power_1_channel_4,
                                 self.checkBox_power_1_channel_5, self.checkBox_power_1_channel_6,
                                 self.checkBox_power_1_channel_7, self.checkBox_power_1_channel_8,
                                 self.checkBox_power_1_channel_9, self.checkBox_power_1_channel_10,
                                 self.checkBox_power_1_channel_11, self.checkBox_power_1_channel_12,
                                 self.checkBox_power_1_channel_13, self.checkBox_power_1_channel_14,
                                 self.checkBox_power_1_channel_15, self.checkBox_power_1_channel_16]
        # start_times 统计start all运行次数
        self.start_all_times = 0
        self.ButtonTaskQueue = queue.Queue()

        self.ser = ''
        self.serdict = {}  # 保存一个serialnum 跟 serial对象的映射关系

        # # 线程list
        # self.thread_list = []
        self.clear_files_flag = 0

        self.run_flag = 1

    def setup(self):
        try:
            ports_list = list(serial.tools.list_ports.comports())

        except Exception as e:
            # self.logger.info('没有检测到串口！')
            self.logger.error(f'Serial port not detected:{e}')
        else:
            for i in ports_list:
                self.port_list_name.append(i.name)
        self.comboBox_serial_num.addItems(self.port_list_name)
        try:
            # 添加从页面获取当前选择的配置文件9.7
            self.config_files = self.cf.read_config_file('./config/config.ini', 'config')
            self.logger.info(self.config_files)
            self.comboBox_schemes.addItems(self.config_files.keys())
            self.comboBox_schemes.currentIndexChanged.connect(self.on_scheme_selected)
            # 初始化从 ini文件读取 email配置
            email = self.cf.read_ini("Emails", 'emails', './config/config.ini').strip().replace('"','')
            print(f'email:{email}')
            self.textEdit_email_list.setText(email)
        except Exception as e:
            self.logger.error(f'Failed to add config file:{e}')

    def get_onu_config_info(self):
        enable_status = OnuCongfig.connect_wifi_enable_status
        self.test_2g_wifi_flag = OnuCongfig.choose_test_2g_flag
        self.test_5g_wifi_flag = OnuCongfig.choose_test_5g_flag
        # self.appoint_wireless_card_flag = OnuCongfig.appoint_wireless_card(self)
        # self.wireless_card = OnuCongfig.get_choose_wireless_card()
        print('self.test_5g_wifi_flag', self.test_2g_wifi_flag, self.test_5g_wifi_flag,
              )
        if enable_status:
            wifi_cards = self.onu_config.get_wireless_cards()

    def clear_files(self):
        # 需要改变 按钮文字，再次按下，停止线程
        self.scheduler_delete_file()

    def scheduler_delete_file(self):
        """
        定时删除指定文件夹的文件（优化版本）- 使用工作线程执行删除操作
        """
        try:
            # 获取文件路径和后缀
            files_path = self.delete_file_path_lineEdit.text().strip()
            files_suffix = self.file_suffix_lineEdit.text().strip()
            clear_files_button_text = self.manual_clear_pushButton.text()

            # 验证输入
            if not files_path:
                self.show_signal_error[str].emit('未填写文件路径，请重新填写！')
                return False

            if not os.path.isdir(files_path):
                self.show_signal_error[str].emit('不是有效目录，请重新填写！')
                return False

            # 处理按钮状态切换
            if clear_files_button_text == "Clearing":
                # 停止清除操作
                self.manual_clear_pushButton.setText('开始清除')
                time.sleep(0.5)
                self.manual_clear_pushButton.setStyleSheet("""
                    QPushButton {
                     background-color: #293847;
                    color:rgb(255, 255, 255);
                    border-radius: 10px;}

                    QPushButton:pressed {
                        background-color: #C0C0C0;
                    color:rgb(255, 255, 255);
                    border-radius: 10px;
                    }
                """)
                self.clear_files_flag = 1
                self.stop_file_deletion()
                return True
            else:
                # 开始清除操作
                self.manual_clear_pushButton.setText('Clearing')
                time.sleep(0.5)
                self.manual_clear_pushButton.setStyleSheet("""
                    QPushButton {background-color:rgb(255,140,0);
                    color:rgb(0, 0, 0);
                    font-size:12px;
                    border-radius: 10px;
                    }

                     QPushButton:pressed {
                        background-color: gray;
                        color: white;
                    }
                """)

                # 立即执行一次删除（使用工作线程）
                self.start_file_deletion_worker(files_path, files_suffix)

                # 计算定时时间
                auto_clear_mouth = int(self.month_comboBox.currentText().strip())
                auto_clear_day = int(self.day_comboBox.currentText().strip())
                auto_clear_hour = int(self.hour_comboBox.currentText().strip())

                if auto_clear_hour == 0 and auto_clear_day == 0 and auto_clear_mouth == 0:
                    scheduler_time = 60  # 默认60秒（测试用，实际应为172800秒）
                else:
                    # 注意：月份计算可能不准确，这里保持原逻辑
                    scheduler_time = auto_clear_mouth * 31 * 86400 + auto_clear_day * 86400 + auto_clear_hour * 3600

                self.show_signal[str].emit(f'定时删除时间 {scheduler_time}秒：{scheduler_time // 3600}小时')

                # 停止现有的定时器（如果存在）
                if hasattr(self, 'delete_timer') and self.delete_timer.isActive():
                    self.delete_timer.stop()
                    self.delete_timer.deleteLater()

                # 创建新的定时器并保持引用
                self.delete_timer = QTimer(self)  # 指定父对象，防止被垃圾回收
                # 连接定时器到启动工作线程的方法
                self.delete_timer.timeout.connect(
                    lambda: self.start_file_deletion_worker(files_path, files_suffix))

                # 设置定时器为重复触发
                self.delete_timer.setSingleShot(False)

                # 启动定时器（单位：毫秒）
                self.delete_timer.start(scheduler_time * 1000)

                # 添加调试信息
                print(f"定时器已启动，间隔: {scheduler_time}秒")

                return True

        except Exception as e:
            error_msg = f'删除文件报错：{e}'
            self.show_signal_error[str].emit(error_msg)
            self.stop_file_deletion()
            # log.error(error_msg)
            return False

    def start_file_deletion_worker(self, files_path, files_suffix):
        """
        启动文件删除工作线程
        """
        # 如果前一个工作线程还在运行，等待它完成
        if hasattr(self, 'deletion_worker') and self.deletion_worker.isRunning():
            print("前一个删除任务仍在运行，跳过此次执行")
            return

        # 创建并启动工作线程
        self.deletion_worker = FileDeleteWorker(files_path, files_suffix)
        self.deletion_worker.finished_signal.connect(lambda: print("文件删除完成"))
        self.deletion_worker.error_signal.connect(
            lambda msg: self.show_signal_error[str].emit(f"文件删除错误: {msg}"))
        self.deletion_worker.start()

    def stop_file_deletion(self):
        """
        停止文件删除操作
        """
        # 停止定时器
        if hasattr(self, 'delete_timer') and self.delete_timer.isActive():
            self.delete_timer.stop()

        # 停止工作线程
        if hasattr(self, 'deletion_worker') and self.deletion_worker.isRunning():
            self.deletion_worker.quit()
            self.deletion_worker.wait()

    def on_scheme_selected(self):
        self.selected_scheme = self.comboBox_schemes.currentText()
        if '请选择' not in self.selected_scheme:
            self.config_file_path = self.config_files[self.selected_scheme]
            self.logger.info(self.config_file_path)

    def select_and_cancel_all(self):
        if self.checkBox_power_1_channel_1.isChecked():
            for i in self.channel_box_list:
                i.click()
        else:
            for i in self.channel_box_list:
                i.click()

    def stop_all_thread(self):
        """优雅停止所有线程"""
        self.show_signal[str].emit('------------准备停止线程，请等待几秒----------')

        # 设置停止事件
        self.stop_event.set()

        # 停止所有PowerOnOffTelnet线程
        if hasattr(self, 'gen_power_control') and self.gen_power_control != '':
            # 设置所有通道标志为停止
            for i in range(1, 17):
                setattr(self.gen_power_control, f'channel_{i}_flag', 0)

            # 调用PowerOnOffTelnet的停止方法（如果存在）
            if hasattr(self.gen_power_control, 'request_stop'):
                self.gen_power_control.request_stop()

        # 停止电源控制线程
        if hasattr(self, 'gen_power_control') and hasattr(self.gen_power_control, 'power_control'):
            self.gen_power_control.power_control.stopthreadevent = 1

        # 等待所有线程结束（带超时）
        timeout = 10  # 最大等待30秒
        start_time = time.time()

        for t in self.threads[:]:  # 创建副本以避免在迭代时修改列表
            if t.is_alive():
                remaining = timeout - (time.time() - start_time)
                if remaining > 0:
                    t.join(remaining)
                else:
                    continue
                    self.show_signal_error[str].emit(f'线程 {t.name} 停止超时')

            # 从线程列表中移除
            if not t.is_alive():
                self.threads.remove(t)

        # 清理资源
        self.__del__()
        if hasattr(self, 'ser') and self.ser != '':
            self.ser.__del__()

        # 重置UI状态
        self.reset_ui_after_stop()

        self.show_signal[str].emit('所有线程已停止')

    def reset_ui_after_stop(self):
        """停止后重置UI状态"""
        # 重置所有通道按钮
        for i in range(16):
            self.channel_ui_list[i].setText(f'Channel {i + 1} Start')
            time.sleep(0.1)
            self.channel_ui_list[i].setStyleSheet(
                "QPushButton {background-color: #293847;\n"
                "color:rgb(255, 255, 255);\n"
                "border-radius: 10px;\n"
                "}\n"
                "\n"
                "QPushButton:pressed {\n"
                "background-color: #C0C0C0;\n"
                "color:rgb(255, 255, 255);\n"
                "border-radius: 10px;\n"
                "}")
            time.sleep(0.1)

        # 重置Start All按钮
        if self.pushButton_power_1_start_all.text() == 'Running':
            self.pushButton_power_1_start_all.setStyleSheet(
                "QPushButton {    background-color: #293847;\n"
                "    color:rgb(255, 255, 255);\n"
                "font-size:12px;\n"
                "border-radius: 15px;\n"
                "}\n"
                "\n"
                " QPushButton:pressed {\n"
                "background-color: #C0C0C0;\n"
                "color:rgb(255, 255, 255);\n"
                "border-radius: 10px;\n"
                "}")
            time.sleep(0.1)
            self.pushButton_power_1_start_all.setText('Start All')
            self.pushButton_power_1_start_all.setEnabled(True)

        self.start_all_times = 0
        self.show_signal[str].emit('$$$$$$$$ 所有线程已停止 $$$$$$$$')

    def modify_channel_button_color(self, num):
        for i in range(1, 17):
            if i == num:
                self.channel_ui_list[i - 1].setStyleSheet(
                    "QPushButton {background-color: #293847;\n"
                    "color:rgb(255, 255, 255);\n"
                    "border-radius: 10px;\n"
                    "}\n"
                    "\n"
                    "QPushButton:pressed {\n"
                    "background-color: #C0C0C0;\n"
                    "color:rgb(255, 255, 255);\n"
                    "border-radius: 10px;\n"
                    "}"
                )
        time.sleep(0.1)

    def change_status(self, status_type, status_list):
        """
        改变按键值
        :param status_type:
        :param status_list:
        :return:
        """
        message_dict = {'ping': 'Ping Error', 'pcie': 'PCIE Error', 'normal': 'Test Complete', 'run': 'Run',
                        'wifi': 'Wifi error', 'voip': 'Voip error', 'eth': 'Eth error', 'wan': 'Wan error',
                        'pon': 'Pon error', 'telnet': 'Telnet error', 'web': 'Telnet open fail',
                        'command': 'Command Error'}

        for i in range(16):
            # 状态码位为1
            if status_list[i] == 1:
                time.sleep(0.1)
                # 将对应的状态值写入修改到对应的按键
                self.channel_ui_list[i].setText(message_dict[status_type])
                time.sleep(0.1)
                if status_type == "normal":
                    self.channel_ui_list[i].setStyleSheet(
                        "QPushButton {background-color: white;\n"
                        "color:green;\n"
                        "border-radius: 10px;\n"
                        "}\n"
                        "\n"
                        "QPushButton:pressed {\n"
                        "background-color: #C0C0C0;\n"
                        "color:rgb(255, 255, 255);\n"
                        "border-radius: 10px;\n"
                        "}")
                    time.sleep(0.1)

                elif status_type == 'run':
                    # self.logger.info('设置黑色')
                    self.channel_ui_list[i].setStyleSheet(
                        "QPushButton {background-color: #293847;\n"
                        "color:rgb(255, 255, 255);\n"
                        "border-radius: 10px;\n"
                        "}\n"
                        "\n"
                        "QPushButton:pressed {\n"
                        "background-color: #C0C0C0;\n"
                        "color:rgb(255, 255, 255);\n"
                        "border-radius: 10px;\n"
                        "}"
                    )
                    time.sleep(0.1)
                else:
                    self.channel_ui_list[i].setStyleSheet(
                        "QPushButton {background-color: white;\n"
                        "color:red;\n"
                        "border-radius: 10px;\n"
                        "}\n"
                        "\n"
                        "QPushButton:pressed {\n"
                        "background-color: #C0C0C0;\n"
                        "color:rgb(255, 255, 255);\n"
                        "border-radius: 10px;\n"
                        "}")
                    time.sleep(0.1)

    def check_status(self, data):
        status_type = data[-1]
        # self.logger.info(f'{data}')
        # self.logger.info(f'{status_type}')
        # self.change_status(control_num, status_type, data)
        t1 = threading.Thread(target=self.change_status, args=[status_type, data])
        t1.setDaemon(True)
        t1.start()

    def update_text(self, text):
        """
            更新textBrowser
        """
        now = datetime.datetime.now()
        cursor = self.textBrowser_logs.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.textBrowser_logs.append(str(now) + ": <font color='green'>" + text + "<font>")
        self.textBrowser_logs.setTextCursor(cursor)
        self.textBrowser_logs.ensureCursorVisible()

    def update_text_error(self, text):
        """
            更新textBrowser
        """
        now = datetime.datetime.now()
        cursor = self.textBrowser_logs.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.textBrowser_logs.append(str(now) + ": <font color='red'>" + text + "<font>")
        self.textBrowser_logs.setTextCursor(cursor)
        self.textBrowser_logs.ensureCursorVisible()

    def update_text_warning(self, text):
        """
            更新textBrowser
        """
        now = datetime.datetime.now()
        cursor = self.textBrowser_logs.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.textBrowser_logs.append(str(now) + ": <font color='#FF7F24'>" + text + "<font>")
        self.textBrowser_logs.setTextCursor(cursor)
        self.textBrowser_logs.ensureCursorVisible()

    # def accept(self):
    #     self.message_dialog.close()
    #
    # def reject(self):
    #     self.message_dialog.close()

    def producer(self, threadObj):
        """
        调用方法 Poo = self.producer(th)
        """
        self.ButtonTaskQueue.put(threadObj)  # 生产者线程函数,向队列存入数据

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
            th = self.ButtonTaskQueue.get()
            th.start()
            self.thread_list.append(th)
            time.sleep(1)
            self.ButtonTaskQueue.task_done()
            # print("消费者取出数据")

    def append_text_to_text_browser(self, text):
        now = datetime.datetime.now()
        self.textBrowser_logs.append(str(now) + ": <font color='red'>" + text + "<font>")

    def get_base_info(self):
        """
        从界面获取需要传输的信息
        :return:
        """
        self.serial_num = self.comboBox_serial_num.currentText().strip().lower()
        print(1111111111111111111111111111)
        self.baud_rate = self.comboBox_band_rate.currentText().strip()
        self.startup_need_time = self.lineEdit_start_need_times.text().strip()
        self.interval_time = self.lineEdit_interval_time.text().strip()
        self.test_number = self.lineEdit_test_number.text().strip()
        self.recv_Email = self.textEdit_email_list.toPlainText().strip()
        self.wait_command_done = self.lineEdit_wait_command_done.text().strip()
        # print('~!@#$%^&*()!@#$%^&*()')
        if self.checkBox_telnet_enable.isChecked():
            self.telnet_enable_flag = 1
        else:
            self.telnet_enable_flag = 0

        config_file_name = self.comboBox_schemes.currentText()
        if '请选择' in config_file_name:
            self.append_text_to_text_browser('请选择配置文件！')
            return False
        try:
            self.startup_need_time = int(self.startup_need_time)
            self.interval_time = int(self.interval_time)
            self.test_number = int(self.test_number)
            self.wait_command_done = int(self.wait_command_done)
            self.current_device_type = self.comboBox_schemes.currentText()

        except:
            self.show_signal_error[str].emit('请在”Device Information“的对应栏输入数字！！！')
            self.logger.error('time is not number！')
            return False
        try:
            self.cf.set_ini('Emails', 'emails', self.recv_Email, './config/config.ini')
            return True
        except Exception as e:

            self.show_signal_error[str].emit(str(e))
            self.logger.error(e)

            return False

    def init_gen_power_control(self):
        # 判断是Telent登录还是SSH登录
        if self.radioButton_telnet.isChecked():
            if self.gen_power_control == '':
                self.gen_power_control = PowerOnOffTelnet(self.ser, self.logger, self.startup_need_time,
                                                          self.interval_time, self.wait_command_done,
                                                          self.test_number,
                                                          self.config_file_path, self.recv_Email,
                                                          self.telnet_enable_flag, self.current_device_type)
                self.gen_power_control.run_status_signal.connect(self.check_status)
                self.gen_power_control.ping_status_signal.connect(self.check_status)
                self.gen_power_control.normal_status_signal.connect(self.check_status)
                self.gen_power_control.pcie_status_signal.connect(self.check_status)
                self.gen_power_control.show_signal.connect(self.update_text)
                self.gen_power_control.show_signal_error.connect(self.update_text_error)
                self.gen_power_control.show_signal_warning.connect(self.update_text_warning)

                self.gen_power_control.wifi_status_signal.connect(self.check_status)
                self.gen_power_control.voip_status_signal.connect(self.check_status)
                self.gen_power_control.eth_status_signal.connect(self.check_status)
                self.gen_power_control.wan_status_signal.connect(self.check_status)
                self.gen_power_control.pon_status_signal.connect(self.check_status)
                self.gen_power_control.telnet_status_signal.connect(self.check_status)
                self.gen_power_control.web_status_signal.connect(self.check_status)
                self.gen_power_control.command_status_signal.connect(self.check_status)
        else:
            if self.gen_power_control == '':
                print('SSH 登录')
                self.gen_power_control = PowerOnOffSsh(self.ser, self.logger, self.startup_need_time,
                                                       self.interval_time, self.wait_command_done, self.test_number,
                                                       self.config_file_path, self.recv_Email,
                                                       self.current_device_type)
                self.gen_power_control.run_status_signal.connect(self.check_status)
                self.gen_power_control.ping_status_signal.connect(self.check_status)
                self.gen_power_control.normal_status_signal.connect(self.check_status)
                self.gen_power_control.pcie_status_signal.connect(self.check_status)
                self.gen_power_control.show_signal.connect(self.update_text)
                self.gen_power_control.show_signal_error.connect(self.update_text_error)
                self.gen_power_control.show_signal_warning.connect(self.update_text_warning)

                self.gen_power_control.wifi_status_signal.connect(self.check_status)
                self.gen_power_control.voip_status_signal.connect(self.check_status)
                self.gen_power_control.eth_status_signal.connect(self.check_status)
                self.gen_power_control.wan_status_signal.connect(self.check_status)
                self.gen_power_control.pon_status_signal.connect(self.check_status)
                # self.gen_power_control.telnet_status_signal.connect(self.check_status)
                # self.gen_power_control.web_status_signal.connect(self.check_status)
                self.gen_power_control.command_status_signal.connect(self.check_status)

    def power_control_01_run(self):
        # 先初始化程控电源
        t21 = threading.Thread(target=self.power_control_01_run_thread, name='all_channel')
        t21.setDaemon(True)
        t21.start()
        time.sleep(1)
        # t21.join(3)

    def power_control_01_run_thread(self):
        """
        start all 程控电源1下面的设备
        :return:
        """
        self.stop_event.clear()
        self.get_onu_config_info()

        if self.onu_config.connect_wifi_enable_status == 1:
            if self.onu_config.iface_names == []:
                return False
            product_solution = self.onu_config.get_onu_solution_type()
            if product_solution is False:
                return False

        self.stopthreadevent = 0
        self.start_all_times += 1

        if not self.get_base_info():
            return False

        try:
            self.logger.info(f'串口 {self.serial_num} init')
            self.ser = Serial(self.serial_num, self.baud_rate, self.logger, timeout=5)
            self.ser.is_open()
        except Exception as e:
            self.logger.error(f'{self.serial_num} init failed :{e}')
            self.append_text_to_text_browser(f'{self.serial_num} init failed :{e}')
            return False

        self.serdict[self.serial_num] = self.ser

        # 初始化 self.gen_power_control
        self.init_gen_power_control()

        if self.gen_power_control != '':
            # 设置所有通道标志为运行
            for i in range(1, 17):
                setattr(self.gen_power_control, f'channel_{i}_flag', 1)

            # 在power_on_off 里面
            self.gen_power_control.power_control.stopthreadevent = 0

        # 针对每个串口,给发送控制电源的指令进行排队发出
        # 在此处调用 Power的消费者，开始控制电源
        tsendpowercommand = threading.Thread(
            target=self.gen_power_control.power_control.consumer,
            name='power_control_consumer'
        )
        tsendpowercommand.start()
        self.threads.append(tsendpowercommand)

        # 接收每个按钮发送的工作任务和全部启动后的case
        taskconsumer = threading.Thread(target=self.consumer, name='task_consumer')
        taskconsumer.start()
        self.threads.append(taskconsumer)

        self.pushButton_power_1_start_all.setEnabled(False)

        if self.pushButton_power_1_start_all.text() == 'Start All':
            self.pushButton_power_1_start_all.setStyleSheet(
                "QPushButton {    background-color:green;\n"
                "    color:white;\n"
                "font-size:15px;\n"
                "    border-radius: 15px;\n"
                "    font-weight: bold;\n"
                "}\n"
                "")
            self.pushButton_power_1_start_all.setText('Running')

            # 启动所有选中的通道
            channels_to_start = []
            for i in range(1, 17):
                if getattr(self, f'checkBox_power_1_channel_{i}').isChecked():
                    channels_to_start.append(i)

            # 为每个通道创建线程
            for channel in channels_to_start:
                if self.stop_event.is_set():
                    break

                thread_func = getattr(self, f'power_control_01_channel_{channel:02d}_case')
                thread_func()
                time.sleep(1)  # 稍微延迟一下，避免同时启动太多线程

            # 等待所有通道线程启动
            self.logger.info('Starting thread, please wait for {} seconds!'.format(self.startup_need_time))

            # 使用可中断的等待
            wait_time = self.startup_need_time
            while wait_time > 0 and not self.stop_event.is_set():
                time.sleep(1)
                wait_time -= 1
                if wait_time % 5 == 0:
                    self.logger.info(f'还剩 {wait_time} 秒...')
        else:
            # 停止所有线程
            self.stop_all_thread()

    def power_control_01_channel_01_case(self):
        t1 = threading.Thread(target=self.power_control_01_channel_01_case_thread, name='channel_1')
        t1.setDaemon(True)
        # t1.start()
        # time.sleep(1)
        # t1.join(3)
        self.producer(t1)
        self.threads.append(t1)

    def power_control_channels(self):
        btn = self.sender()
        print(btn.text())

        if self.get_base_info():
            if btn.text != 'Run':
                time.sleep(0.1)
                self.pushButton_power_1_channel_1.setText('Run')
                # self.gen_power_control.run_flag = 1
                network_card_ip = get_network_card_ip(1)
                self.gen_power_control.channel_1_flag = 1
                # 打开第一个通道
                self.gen_power_control.channel_1_run(network_card_ip)

    def config_device_wifi_param(self):
        self.onu_config.show()

    def power_control_channel_x_case_thread(self):
        pass

    def power_control_01_channel_01_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(1)
            if self.pushButton_power_1_channel_1.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_1.setText('Run')
                self.modify_channel_button_color(1)
                self.gen_power_control.channel_1_flag = 1

                # 打开第1个通道
                self.gen_power_control.run_case(network_card_ip, 1, self.stop_event)

    def power_control_01_channel_02_case(self):
        t2 = threading.Thread(target=self.power_control_01_channel_02_case_thread, name='channel_2')
        t2.setDaemon(True)
        # t2.start()
        # time.sleep(1)
        # t2.join(3)
        self.producer(t2)
        self.threads.append(t2)

    def power_control_01_channel_02_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(2)
            if self.pushButton_power_1_channel_2.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_2.setText('Run')
                self.modify_channel_button_color(2)
                self.gen_power_control.channel_2_flag = 1

                # 打开第2个通道
                self.gen_power_control.run_case(network_card_ip, 2, self.stop_event)

    def power_control_01_channel_03_case(self):
        t3 = threading.Thread(target=self.power_control_01_channel_03_case_thread, name='channel_3')
        t3.setDaemon(True)
        # t3.start()
        # time.sleep(1)
        # t3.join(3)
        self.producer(t3)
        self.threads.append(t3)

    def power_control_01_channel_03_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """

        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(3)
            if self.pushButton_power_1_channel_3.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_3.setText('Run')
                self.modify_channel_button_color(3)
                self.gen_power_control.channel_3_flag = 1

                # 打开第3个通道
                self.gen_power_control.run_case(network_card_ip, 3, self.stop_event)

    def power_control_01_channel_04_case(self):

        t4 = threading.Thread(target=self.power_control_01_channel_04_case_thread, name='channel_4')
        t4.setDaemon(True)
        # t4.start()
        # time.sleep(1)
        # t4.join(3)
        self.producer(t4)
        self.threads.append(t4)

    def power_control_01_channel_04_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(4)
            if self.pushButton_power_1_channel_4.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_4.setText('Run')
                self.modify_channel_button_color(4)
                self.gen_power_control.channel_4_flag = 1

                # 打开第4个通道
                self.gen_power_control.run_case(network_card_ip, 4, self.stop_event)

    def power_control_01_channel_05_case(self):
        t5 = threading.Thread(target=self.power_control_01_channel_05_case_thread, name='channel_5')
        t5.setDaemon(True)
        # t5.start()
        # time.sleep(1)
        # t5.join(3)
        self.producer(t5)
        self.threads.append(t5)

    def power_control_01_channel_05_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(5)
            if self.pushButton_power_1_channel_5.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_5.setText('Run')
                self.modify_channel_button_color(5)
                self.gen_power_control.channel_5_flag = 1

                # 打开第5个通道
                self.gen_power_control.run_case(network_card_ip, 5, self.stop_event)

    def power_control_01_channel_06_case(self):
        t6 = threading.Thread(target=self.power_control_01_channel_06_case_thread, name='channel_6')
        t6.setDaemon(True)
        # t6.start()
        # time.sleep(1)
        # t6.join(3)
        self.producer(t6)
        self.threads.append(t6)

    def power_control_01_channel_06_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(6)
            if self.pushButton_power_1_channel_6.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_6.setText('Run')
                self.modify_channel_button_color(6)
                self.gen_power_control.channel_6_flag = 1

                # 打开第6个通道
                self.gen_power_control.run_case(network_card_ip, 6, self.stop_event)

    def power_control_01_channel_07_case(self):
        t7 = threading.Thread(target=self.power_control_01_channel_07_case_thread, name='channel_7')
        t7.setDaemon(True)
        # t7.start()
        # time.sleep(1)
        # t7.join(3)
        self.producer(t7)
        self.threads.append(t7)

    def power_control_01_channel_07_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(7)
            if self.pushButton_power_1_channel_7.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_7.setText('Run')
                self.modify_channel_button_color(7)
                self.gen_power_control.channel_7_flag = 1

                # 打开第7个通道
                self.gen_power_control.run_case(network_card_ip, 7, self.stop_event)

    def power_control_01_channel_08_case(self):
        t8 = threading.Thread(target=self.power_control_01_channel_08_case_thread, name='channel_8')
        t8.setDaemon(True)
        # t8.start()
        # time.sleep(1)
        # t8.join(3)
        self.producer(t8)
        self.threads.append(t8)

    def power_control_01_channel_08_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(8)
            if self.pushButton_power_1_channel_8.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_8.setText('Run')
                self.modify_channel_button_color(8)
                self.gen_power_control.channel_8_flag = 1

                # 打开第8个通道
                self.gen_power_control.run_case(network_card_ip, 8, self.stop_event)

    def power_control_01_channel_09_case(self):
        t9 = threading.Thread(target=self.power_control_01_channel_09_case_thread, name='channel_9')
        t9.setDaemon(True)
        # t9.start()
        # time.sleep(1)
        # t9.join(3)
        self.producer(t9)
        self.threads.append(t9)

    def power_control_01_channel_09_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(9)
            if self.pushButton_power_1_channel_9.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_9.setText('Run')
                self.modify_channel_button_color(9)
                self.gen_power_control.channel_9_flag = 1

                # 打开第9个通道
                self.gen_power_control.run_case(network_card_ip, 9, self.stop_event)

    def power_control_01_channel_10_case(self):
        t10 = threading.Thread(target=self.power_control_01_channel_10_case_thread, name='channel_10')
        t10.setDaemon(True)
        # t10.start()
        # time.sleep(1)
        # t10.join(3)
        self.producer(t10)
        self.threads.append(t10)

    def power_control_01_channel_10_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(10)
            if self.pushButton_power_1_channel_10.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_10.setText('Run')
                self.modify_channel_button_color(10)
                self.gen_power_control.channel_10_flag = 1

                # 打开第10个通道
                self.gen_power_control.run_case(network_card_ip, 10, self.stop_event)

    def power_control_01_channel_11_case(self):
        t11 = threading.Thread(target=self.power_control_01_channel_11_case_thread, name='channel_11')
        t11.setDaemon(True)
        # t11.start()
        # time.sleep(1)
        # t11.join(3)
        self.producer(t11)
        self.threads.append(t11)

    def power_control_01_channel_11_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(11)
            if self.pushButton_power_1_channel_11.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_11.setText('Run')
                self.modify_channel_button_color(11)
                self.gen_power_control.channel_11_flag = 1

                # 打开第11个通道
                self.gen_power_control.run_case(network_card_ip, 11, self.stop_event)

    def power_control_01_channel_12_case(self):
        t12 = threading.Thread(target=self.power_control_01_channel_12_case_thread, name='channel_12')
        t12.setDaemon(True)
        # t12.start()
        # time.sleep(1)
        # t12.join(3)
        self.producer(t12)
        self.threads.append(t12)

    def power_control_01_channel_12_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(12)
            if self.pushButton_power_1_channel_12.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_12.setText('Run')
                self.modify_channel_button_color(12)
                self.gen_power_control.channel_12_flag = 1

                # 打开第12个通道
                self.gen_power_control.run_case(network_card_ip, 12, self.stop_event)

    def power_control_01_channel_13_case(self):
        t13 = threading.Thread(target=self.power_control_01_channel_13_case_thread, name='channel_13')
        t13.setDaemon(True)
        # t13.start()
        # time.sleep(1)
        # t13.join(3)
        self.producer(t13)
        self.threads.append(t13)

    def power_control_01_channel_13_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(13)
            if self.pushButton_power_1_channel_13.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_13.setText('Run')
                self.modify_channel_button_color(13)
                self.gen_power_control.channel_13_flag = 1

                # 打开第13个通道
                self.gen_power_control.run_case(network_card_ip, 13, self.stop_event)

    def power_control_01_channel_14_case(self):
        t14 = threading.Thread(target=self.power_control_01_channel_14_case_thread, name='channel_14')
        t14.setDaemon(True)
        # t14.start()
        # time.sleep(1)
        # t14.join(3)
        self.producer(t14)
        self.threads.append(t14)

    def power_control_01_channel_14_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(14)
            if self.pushButton_power_1_channel_14.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_14.setText('Run')
                self.modify_channel_button_color(14)
                self.gen_power_control.channel_14_flag = 1

                # 打开第14个通道
                self.gen_power_control.run_case(network_card_ip, 14, self.stop_event)

    def power_control_01_channel_15_case(self):
        t15 = threading.Thread(target=self.power_control_01_channel_15_case_thread, name='channel_15')
        t15.setDaemon(True)
        # t15.start()
        # time.sleep(1)
        # t15.join(3)
        self.producer(t15)
        self.threads.append(t15)

    def power_control_01_channel_15_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(15)
            if self.pushButton_power_1_channel_15.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_15.setText('Run')
                self.modify_channel_button_color(15)
                self.gen_power_control.channel_15_flag = 1

                # 打开第15个通道
                self.gen_power_control.run_case(network_card_ip, 15, self.stop_event)

    def power_control_01_channel_16_case(self):
        print(13)
        t16 = threading.Thread(target=self.power_control_01_channel_16_case_thread, name='channel_16')
        t16.setDaemon(True)
        # t16.start()
        # time.sleep(1)
        # t16.join(3)
        self.producer(t16)
        self.threads.append(t16)

    def power_control_01_channel_16_case_thread(self):
        """
        程控电源1 的第一个电源控制口
        :return:
        """
        print(16)
        if self.get_base_info() and not self.stop_event.is_set():
            network_card_ip = get_network_card_ip(16)
            if self.pushButton_power_1_channel_16.text() != 'Run' and self.gen_power_control != '':
                self.pushButton_power_1_channel_16.setText('Run')
                self.modify_channel_button_color(16)
                self.gen_power_control.channel_16_flag = 1

                # 打开第16个通道
                self.gen_power_control.run_case(network_card_ip, 16, self.stop_event)

    def clear_logs(self):
        self.textBrowser_logs.clear()

    def closeEvent(self, event):
        # 创建一个消息盒子（提示框）
        quitMsgBox = QMessageBox()
        # 设置提示框的标题
        quitMsgBox.setWindowTitle('Tip')
        # 设置提示框的内容
        quitMsgBox.setText('Are you sure to exit?')
        # 设置按钮标准，一个yes一个no
        quitMsgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        # 获取两个按钮并且修改显示文本
        buttonY = quitMsgBox.button(QMessageBox.Yes)
        buttonY.setText('Confirm')
        buttonN = quitMsgBox.button(QMessageBox.No)
        buttonN.setText('Cancel')
        quitMsgBox.exec_()
        # 判断返回值，如果点击的是Yes按钮，我们就关闭组件和应用，否则就忽略关闭事件
        if quitMsgBox.clickedButton() == buttonY:
            event.accept()
            try:
                self.__del__()
            except:
                pass
            finally:
                app.quit()
        else:
            event.ignore()

    def __del__(self):
        """确保所有资源被正确清理"""
        self.logger.info('关闭线程和清理资源!')
        self.stopthreadevent = 1
        self.stop_event.set()

        # 关闭所有串口
        for k, v in self.serdict.items():
            try:
                v.serial_close()
            except Exception as e:
                self.logger.error(f'关闭串口 {k} 时出错: {e}')

        # 停止所有PowerOnOffTelnet线程
        if hasattr(self, 'gen_power_control') and self.gen_power_control != '':
            # 设置所有通道标志为停止
            for i in range(1, 17):
                setattr(self.gen_power_control, f'channel_{i}_flag', 0)

            # 调用停止方法（如果存在）
            if hasattr(self.gen_power_control, 'request_stop'):
                self.gen_power_control.request_stop()

            # 复位
            self.gen_power_control = ''

    def __exit__(self):
        for k, v in self.serdict.items():
            v.serial_close()  # 关闭每一个电源对应的串口

    def stop_all_run(self):
        t1 = threading.Thread(target=self.stop_all_thread)
        t1.setDaemon(True)
        t1.start()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ui = UiCase()
    ui.show()
    sys.exit(app.exec_())
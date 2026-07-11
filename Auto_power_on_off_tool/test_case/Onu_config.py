import pywifi
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from UI.config_device_wifi_param_ui import Ui_MainWindow
from common.wifi_connect import WifiConnect


class OnuCongfig(QMainWindow, Ui_MainWindow):
    show_signal = pyqtSignal(str)
    show_signal_error = pyqtSignal(str)

    connect_wifi_enable_status = 0
    choose_test_2g_flag = 0
    choose_test_5g_flag = 0
    connect_wifi_auth_mode = ''
    connect_wifi_ciper = ''
    Onu_solution_type = ''
    choose_wireless_card_flag = 0
    choose_wireless_card_name = ''
    iface_names = []

    def __init__(self, parent=None):
        super(OnuCongfig, self).__init__(parent)
        self.setupUi(self)
        window_title = self.windowTitle()
        self.setWindowTitle(window_title + '_V2.1')
        self.get_connect_wifi_enable()
        self.get_wifi_ciper()
        self.get_wifi_auth_mode()
        self.get_onu_solution_type()
        self.get_test_2g_flag()
        self.get_test_5g_flag()
        print('choose_test_5g_flag', OnuCongfig.choose_test_5g_flag, OnuCongfig.choose_test_2g_flag)

    def get_onu_solution_type(self):
        """
        获取ONU 解决方案
        """
        onu_solution_type = self.lineEdit_onu_solution_type.text().strip()
        OnuCongfig.Onu_solution_type = self.lineEdit_onu_solution_type.text().strip().lower()
        if OnuCongfig.Onu_solution_type == 'openwrt':
            self.show_signal[str].emit('当前填写的 ONU 解决方案类型是： 【OpenWrt】')
            return OnuCongfig.Onu_solution_type
        elif OnuCongfig.Onu_solution_type == 'bcm':
            self.show_signal_error[str].emit('当前填写的 ONU 解决方案类型是： 【BCM】，暂不支持，请联系开发人员进行添加！')
            return False
        elif OnuCongfig.Onu_solution_type == 'mtk':
            self.show_signal_error[str].emit('当前填写的 ONU 解决方案类型是： 【MTK】，暂不支持，请联系开发人员进行添加！')
            return False
        else:
            self.show_signal_error[str].emit(
                f'当前填写的 ONU 解决方案类型是： 【{onu_solution_type}】，暂不支持，请联系开发人员进行添加！')
            return False

    def get_connect_wifi_enable(self):
        status = self.checkBox_connect_wifi.isChecked()
        if status:
            self.show_signal[str].emit('勾选测试 WiFi 连接功能')
            OnuCongfig.connect_wifi_enable_status = 1
        else:
            self.show_signal[str].emit('未勾选测试 WiFi 连接功能，不进行WiFi连接测试')
            OnuCongfig.connect_wifi_enable_status = 0
        print(OnuCongfig.connect_wifi_enable_status)
        return OnuCongfig.connect_wifi_enable_status

    def get_test_2g_flag(self):

        status = self.checkBox_2g_wifi.isChecked()
        print(2222222222222222222222222222, OnuCongfig.connect_wifi_enable_status, status)
        if status:
            self.show_signal[str].emit(f'勾选测试 2g WiFi连接功能:{OnuCongfig.choose_test_2g_flag}')
            OnuCongfig.choose_test_2g_flag = 1
        else:
            OnuCongfig.choose_test_2g_flag = 0
            self.show_signal[str].emit(f'不勾选测试 2g WiFi连接功能：{OnuCongfig.choose_test_2g_flag}')
        return OnuCongfig.choose_test_2g_flag

    def get_test_5g_flag(self):
        status = self.checkBox_5g_wifi.isChecked()
        print(5555555555555555555555555555, OnuCongfig.connect_wifi_enable_status, status)
        if status:
            self.show_signal[str].emit(f'勾选测试 5g WiFi连接功能:{OnuCongfig.choose_test_5g_flag}')
            OnuCongfig.choose_test_5g_flag = 1
        else:
            OnuCongfig.choose_test_5g_flag = 0
            self.show_signal[str].emit(f'不勾选测试 5g WiFi连接功能：{OnuCongfig.choose_test_5g_flag}')
            print(7777777777777)
        print(666666666, OnuCongfig.connect_wifi_enable_status)
        return OnuCongfig.choose_test_5g_flag

    def appoint_wireless_card(self):
        """
        指定无线网卡的标志
        :return:
        """
        status = self.checkBox_choose_wireless_card.isChecked()
        if status and OnuCongfig.connect_wifi_enable_status:
            self.show_signal[str].emit('勾选指定网卡')
            OnuCongfig.choose_wireless_card_flag = 1
        else:
            OnuCongfig.choose_wireless_card_flag = 0
        return OnuCongfig.choose_wireless_card_flag

    def get_choose_wireless_card(self):
        """
        获取选择的无线网卡名称
        :return:
        """
        wireless_card_name = self.com_Box_wifi_network_card.currentText()
        if wireless_card_name and OnuCongfig.choose_wireless_card_flag:
            self.show_signal[str].emit(f'指定网卡: {wireless_card_name} 进行WiFi连接测试')
            OnuCongfig.choose_wireless_card_name = wireless_card_name
            return OnuCongfig.choose_wireless_card_name
        else:
            self.show_signal[str].emit(f'未指定网卡，随机选择无线网卡进行WiFi连接测试')
            return OnuCongfig.choose_wireless_card_name

    def get_wifi_auth_mode(self):
        OnuCongfig.connect_wifi_auth_mode = self.com_Box_wifi_auth_mode.currentText().strip()
        print(OnuCongfig.connect_wifi_auth_mode)
        return OnuCongfig.connect_wifi_auth_mode

    def get_wifi_ciper(self):
        OnuCongfig.connect_wifi_ciper = self.com_Box_wifi_cipher.currentText().strip()
        print(OnuCongfig.connect_wifi_ciper)
        return OnuCongfig.connect_wifi_ciper

    def save_config(self):
        self.get_connect_wifi_enable()
        self.get_test_2g_flag()
        self.get_test_5g_flag()
        self.get_wifi_ciper()
        self.get_wifi_auth_mode()
        self.get_onu_solution_type()
        self.appoint_wireless_card()
        self.get_choose_wireless_card()

        # self.hide()

    def get_wireless_cards(self):
        print("获取无线网卡")
        OnuCongfig.iface_names = []
        self.wifi = pywifi.PyWiFi()
        for i in self.wifi.interfaces():
            OnuCongfig.iface_names.append(i.name())
        self.com_Box_wifi_network_card.clear()
        self.com_Box_wifi_network_card.addItems(OnuCongfig.iface_names)
        if OnuCongfig.iface_names == []:
            self.show_signal_error[str].emit('当前测试PC没有找到开启的无线网卡')
            self.com_Box_wifi_network_card.clear()
            return False
        return OnuCongfig.iface_names

    def closeEvent(self, event):
        # 创建一个消息盒子（提示框）
        quitMsgBox = QMessageBox()
        # 设置提示框的标题
        quitMsgBox.setWindowTitle('Tip')
        # 设置提示框的内容
        quitMsgBox.setText('确认保存退出？')
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
            self.save_config()
            try:
                self.__del__()
            except:
                pass
        else:
            event.ignore()

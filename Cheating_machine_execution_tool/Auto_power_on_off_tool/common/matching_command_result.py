from PyQt5.QtCore import QThread, pyqtSignal

from common.fuzzy_match import Fuzzy_Match
from common.my_logging import creat_logger
from config.config_driver import OperationConfig
from clients.telnet_client import TelnetClient
class Matching_Command_Result(QThread):
    run_status_signal = pyqtSignal(list)
    def __init__(self, ):
        super(Matching_Command_Result, self).__init__()
        self.conf = OperationConfig()
        self.logging = creat_logger('log')


    def run(self):
        self.Read_configuration_file()


    def network_card_ip_num(self,num):
        self.num=num


    def selected_scheme_path(self,path):
        self.config_file_path=path
        self.username = self.conf.read_ini('telnet', 'user',
                                           path=self.config_file_path).strip()
        self.password = self.conf.read_ini('telnet', 'password',
                                           path=self.config_file_path).strip()
        # self.network_card_ip = self.conf.read_ini('channel_01', 'network_card_ip',
        #                                           path=self.config_file_path)

    def Read_configuration_file(self):
        order_ = self.conf.read_config_file(self.config_file_path, 'order') #返回所有命令的键值对
        tel = TelnetClient(self.num, '192.168.1.1', 23, self.logging)
        tel.login_host('192.168.1.1', self.username, self.password)
        for key, value in order_.items():
            a = tel.execute_some_command_iwconfig(key, 2)
            Fuzzy_Match(value, a)


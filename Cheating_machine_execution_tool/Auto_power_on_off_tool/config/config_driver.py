# -*- coding: utf-8 -*-
import configparser
from configparser import RawConfigParser
from configobj import ConfigObj


class myconf(configparser.ConfigParser):
    def __init__(self, defaults=None):
        configparser.ConfigParser.__init__(self, defaults=None)

    # 让section不变小写，默认会变成小写
    def optionxform(self, optionstr):
        return optionstr


class OperationConfig():

    def __init__(self):
        self.conf = myconf()
        self.conf_01 = RawConfigParser()

    # 获取命令的键值对 9.7
    def read_config_file(self, file_path, option):
        # 创建 configparser 对象

        # 读取配置文件
        self.conf.read(file_path, encoding='utf-8')

        # 创建一个空字典用于存储键值对
        config_data = {}

        # 获取 [config] 下的所有键值对
        config_items = self.conf.items(section=option, raw=True)
        if option == 'config':
            # 遍历并存储键值对到字典中
            for key, value in config_items:
                # print(key, "=", value)
                key = key.upper()
                config_data[key] = value
        else:
            # 遍历并存储键值对到字典中
            for key, value in config_items:
                # print(key, "=", value)
                config_data[key] = value

        # 返回存储的配置数据字典
        return config_data

    def read_ini_raw(self, section, option, path='./config/network_card_ip.ini'):
        # 增加编码格式，放置ini文件有中文而产生报错
        self.conf_01.read(path, encoding='utf-8')
        value = self.conf.get(section, option)
        # if option == "device_url":
        #     print('读取config.ini里面的device_url值是：{}'.format(value))
        return value

    def read_ini(self, section, option, path='./config/network_card_ip.ini'):
        # 增加编码格式，放置ini文件有中文而产生报错
        self.conf.read(path, encoding='utf-8')
        value = self.conf.get(section, option)
        # if option == "device_url":
        #     print('读取config.ini里面的device_url值是：{}'.format(value))
        return value

    # def set_ini(self, section, option, value, path='./config/network_card_ip.ini'):
    #     # 需要先读取文件，才会进入这个文件，不然set的时候找不到section
    #     self.conf.read(path, encoding='utf-8')
    #     # print('设置config.ini文件：{}的值为{}'.format(option, value))
    #     self.conf.set(section, option, value)
    #     with open(path, 'w+', encoding='utf-8') as f:
    #         self.conf.write(f)
    #     return True
    #     # t1 = Thread(target=self.set_ini_thread, args=[section, option, value, path])
    #     # t1.start()

    def set_ini(self, section, option, value, path='./config/network_card_ip.ini'):
        try:
            # 读取INI文件（保留注释）
            config = ConfigObj(path, encoding='utf8')
            # 修改配置
            config[section][option] = value
            # 写入文件（保留原有注释和格式）
            config.write()
        except Exception as e:
            desc = f"设置 {value} 到 config.ini 文件报错: {str(e)}"
            raise Exception(desc)  # 使用 Exception 类包装错误信息



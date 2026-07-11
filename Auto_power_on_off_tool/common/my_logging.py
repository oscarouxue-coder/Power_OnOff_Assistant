import logging
import os
import time
from common.create_float_data import create_float_num

def creat_logger(name):
    """

    :param name: 设备型号
    :return:
    """
    # 创建一个日志器  别的文件使用日志  就用到这个日志器
    logger = logging.getLogger()
    # # 设置日志级别  日志信息输出info以上的级别信息  设置了等级但是没有出来info
    logger.setLevel(logging.INFO)
    # 删除log handlers
    try:
        logger.removeHandler(logger.handlers[0])
        logger.removeHandler(logger.handlers[1])
    except:
        pass
    if not logger.handlers:
        # print('1111')
        # # 设置日志格式 创建一个格式器  日志格式不是我们想要的
        # # 创建一个格式器  设置了格式
        fmt = '%(asctime)s %(filename)s %(levelname)s  %(funcName)s  %(message)s'
        formater = logging.Formatter(fmt)

        # # 处理器 Handler  我要把日志信息输出到哪
        # # # 创建一个输出到控制台的处理器  控制台
        sh = logging.StreamHandler()
        sh.setLevel(logging.ERROR)
        # # 把设置的日志信息放到控制台中
        logger.addHandler(sh)
        # 控制台设置格式器
        sh.setFormatter(formater)
        # 在文件里面生成日志信息  创建处理器  文件处理器  处理器的作用：把日志信息输出到指定的位置
        # 文件处理器创建  你的日志信息存放在哪
        if not os.path.exists('script_logs'):
            os.mkdir('script_logs')
        cwd = os.getcwd()
        log_path = cwd + '/script_logs/'
        rq = time.strftime('%Y%m%d%H%M', time.localtime(time.time()))
        log_name = log_path + name + '_' + rq + '.log'
        logfile = log_name
        # print(logfile)
        fh = logging.FileHandler(logfile, 'w', encoding='utf-8')
        sh.setLevel(logging.INFO)
        # 需要把日志信息放到文件处理器里面去
        logger.addHandler(fh)
        # 给谁设置格式，给fh设置格式,可以在去定义
        fh.setFormatter(formater)
    # else:
    #     print(2222)
    #     # # 设置日志格式 创建一个格式器  日志格式不是我们想要的
    #     # # 创建一个格式器  设置了格式
    #     fmt = '%(asctime)s %(filename)s %(levelname)s  %(funcName)s  %(message)s'
    #     formater = logging.Formatter(fmt)
    #
    #     # # 处理器 Handler  我要把日志信息输出到哪
    #     # # # 创建一个输出到控制台的处理器  控制台
    #     sh = logging.StreamHandler()
    #     # # 把设置的日志信息放到控制台中
    #     logger.addHandler(sh)
    #     # 控制台设置格式器
    #     sh.setFormatter(formater)
    #     # 在文件里面生成日志信息  创建处理器  文件处理器  处理器的作用：把日志信息输出到指定的位置
    #     # 文件处理器创建  你的日志信息存放在哪
    #     if not os.path.exists('script_logs'):
    #         os.mkdir('script_logs')
    #     cwd = os.getcwd()
    #     log_path = cwd + '/script_logs/'
    #     rq = time.strftime('%Y%m%d%H%M', time.localtime(time.time()))
    #     log_name = log_path + name + '_' + rq + '.log'
    #     logfile = log_name
    #     print(logfile)
    #
    #     fh = logging.FileHandler(logfile, 'w', encoding='utf-8')
    #     # 需要把日志信息放到文件处理器里面去
    #     logger.addHandler(fh)
    #     # 给谁设置格式，给fh设置格式,可以在去定义
    #     fh.setFormatter(formater)
    return logger


class ConsolePanelHandler(logging.Handler):

    def __init__(self, parent):
        logging.Handler.__init__(self)
        self.parent = parent

    def emit(self, record):
        """输出格式可以按照自己的意思定义HTML格式"""
        record_dict = record.__dict__
        # print(record_dict)
        asctime = record_dict['asctime'] + ">>"
        # line = record_dict['filename'] + "->" + str(record_dict['lineno']) + "|"
        levelname = record_dict['levelname']
        message = record_dict['message']
        if levelname == 'ERROR':
            color = "#FF0000"
        elif levelname == 'WARNING':
            color = "#FFD700"
        else:
            color = "#008000"
        html = f'''
        <div >
            <span>{asctime}</span>
            <span style="color: {color};">{levelname}</span>
            <span style="color:	#2E2E2E;">{message}</span>
        </div>
        '''
        time.sleep(create_float_num(2))
        self.parent.update_text(html)
        time.sleep(create_float_num(2))

# print(creat_logger('2'))

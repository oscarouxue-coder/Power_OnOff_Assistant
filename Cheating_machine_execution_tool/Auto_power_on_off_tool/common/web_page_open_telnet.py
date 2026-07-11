import logging
import re
import time
import socket
import urllib
import requests
from requests_toolbelt.adapters.source import SourceAddressAdapter
from config.config_driver import OperationConfig

cf = OperationConfig()


def enable_pon(network_card_ip, url, f):
    try:
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(network_card_ip))
        s.mount('https://', SourceAddressAdapter((network_card_ip, 8999)))
        # print(s.__dir__())
        # print(s.__getattribute__('mount'))
        if 'https' in url:
            #
            res = s.get(url, timeout=10, verify=False)
        else:
            res = s.post(url, timeout=10)
    except Exception as e:
        logging.error(f'{network_card_ip} open telnet url error:{e}')
        f.write(f'{network_card_ip} open telnet url error:{e}\n'.encode())
        return False
    else:
        if res.status_code == 400:
            print(res.status_code)
            logging.info(f'{network_card_ip} open telnet url success！')
            f.write(f'{network_card_ip} open telnet url success！\n'.encode())
            time.sleep(5)
            return True
        elif res.status_code == 404:
            print(res.status_code)
            try:
                if 'https' in url:
                    res = s.post(url, timeout=10, verify=False)
                else:
                    res = s.get(url, timeout=10)
            except Exception as e:
                logging.error(f'{network_card_ip} open telnet url error:{e}')
                f.write(f'{network_card_ip} open telnet url error:{e}\n'.encode())
                return False
            else:
                if res.status_code == 400:
                    print(res.status_code)
                    logging.info(f'{network_card_ip} open telnet url success！')
                    f.write(f'{network_card_ip} open telnet url success！\n'.encode())
                    time.sleep(5)
                    return True
                else:
                    logging.error(f'{network_card_ip} open telnet url error:{res.status_code}')
                    f.write(f'{network_card_ip} open telnet url error:{res.status_code}\n'.encode())
                    return False
    # print(res.json)


def enable_router(network_card_ip, url, f):
    try:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "call",
            "params": ["00000000000000000000000000000000", "xlink.system", "TelnetSet", {"data": {"enable": 1}}]
        }
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(network_card_ip))
        s.mount('https://', SourceAddressAdapter((network_card_ip, 8999)))
        # print(s.__dir__())
        # print(s.__getattribute__('mount'))
        if 'https' in url:
            res = s.post(url, json=data, timeout=10, verify=False)
        else:
            res = s.post(url, json=data, timeout=10)
        # print(res.text)
    except Exception as e:
        logging.error(f'{network_card_ip} open telnet url error:{e}')
        f.write(f'{network_card_ip} open telnet url error:{e}\n'.encode())
        return False
    else:
        logging.info(f'{network_card_ip} open telnet url success！')
        f.write(f'{network_card_ip} open telnet url success:{res.status_code}！\n'.encode())
        return True


def enable_router_html(network_card_ip, url, f):
    try:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "call",
            "params": ["00000000000000000000000000000000", "xlink.firewall", "TelnetSet", {"data": {"enable": 1}}]
        }
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(network_card_ip))
        s.mount('https://', SourceAddressAdapter((network_card_ip, 8999)))
        # print(s.__dir__())
        # print(s.__getattribute__('mount'))
        if 'https' in url:
            res = s.post(url, json=data, timeout=10, verify=False)
        else:
            res = s.post(url, json=data, timeout=10)
        print(res.text)
    except Exception as e:
        logging.error(f'{network_card_ip} open telnet url error:{e}')
        f.write(f'{network_card_ip} open telnet url error:{e}\n'.encode())
        return False
    else:
        logging.info(f'{network_card_ip} open telnet url success！')
        f.write(f'{network_card_ip} open telnet url success:{res.status_code}！\n'.encode())
        time.sleep(5)
        return True


# def enable_special_onu(network_card_ip, url, f):
#     try:
#         _create_socket = socket.create_connection
#         SOURCE_ADDRESS = (network_card_ip, 0)
#
#         def create_connection(*args, **kwargs):
#             in_args = False
#
#             if len(args) >= 3:
#                 args = list(args)
#                 args[2] = SOURCE_ADDRESS
#                 args = tuple(args)
#                 in_args = True
#
#             if not in_args:
#                 kwargs["source_address"] = SOURCE_ADDRESS
#
#             print("args", args)
#             print("kwargs", str(kwargs))
#
#             return _create_socket(*args, **kwargs)
#
#         socket.create_connection = create_connection
#         urllib.request.urlopen(url)
#         return True
#     except Exception as e:
#         logging.error(f'{network_card_ip} open telnet url error:{e}')
#         f.write(f'{network_card_ip} open telnet url error:{e}\n'.encode())
#
#         if '404' in str(e):
#             print('XXXXXXXXXXXXXXXXXXX')
#             return True
#         else:
#             print('cccccc', e)
#             return False
#     finally:
#         # 恢复原始的 create_connection 函数
#         socket.create_connection = _create_socket


def enable_special_onu(network_card_ip, url, f):
    try:
        # 指定本地IP地址和端口
        # host = '192.168.0.1'
        path = '/cgi-bin/TelnetEnabled.asp?username=telecomsdmc&password=nE7jA%5m'

        match_gateway_ip = re.compile(r'[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}')
        host = match_gateway_ip.search(url).group()

        # 指定本地IP地址（您希望使用的网卡的IP地址）
        local_ip = network_card_ip
        local_port = 0  # 系统会自动选择一个可用的端口

        # 创建套接字并绑定到指定的本地地址
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((local_ip, local_port))
        sock.connect((host, 80))

        # 构建 HTTP 请求
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"

        # 发送请求
        sock.sendall(request.encode('utf-8'))

        # 接收响应
        response = b''
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response += data
        # 关闭套接字
        sock.close()
        # 打印响应内容
        print(response.decode('utf-8'))
        f.write(response)
        return True
    except Exception as e:
        f.write(f'{network_card_ip} open telnet url success:{e}！\n'.encode())
        return False


def Web_Page_Open_Telnet(network_card_ip, url, f, retry_times, interval_time, flag=1):
    """
    flag=1 表示需要打开telnet
    """
    f.write(
        f'\n\n打开 telnet_enable 失败时的操作：retry_times: {retry_times}，interval_time:{interval_time}\n\n'.encode())
    if flag == 0:
        return True
    times = 1
    while True:
        if 'enable.asp' in url:
            if enable_pon(network_card_ip, url, f):
                return True
            else:
                f.write(f'\n\n@@@@@@@@@@@@@@@@@@ 第{times}次尝试打开 telnet enable @@@@@@@@@@@@@@@@@@\n\n'.encode())

                if times == retry_times:
                    return False
                time.sleep(interval_time)
                times += 1
        elif 'system.TelnetSet' in url:
            if enable_router(network_card_ip, url, f):
                return True
            else:
                f.write(f'\n\n@@@@@@@@@@@@@@@@@@ 第{times}次尝试打开 telnet enable @@@@@@@@@@@@@@@@@@\n\n'.encode())

                if times == retry_times:
                    return False
                time.sleep(interval_time)
                times += 1
        elif "firewall.TelnetSet" in url:
            if enable_router_html(network_card_ip, url, f):
                return True
            else:
                f.write(f'\n\n@@@@@@@@@@@@@@@@@@ 第{times}次尝试打开 telnet enable @@@@@@@@@@@@@@@@@@\n\n'.encode())

                if times == retry_times:
                    return False
                time.sleep(interval_time)
                times += 1

        elif "TelnetEnabled.asp" in url:

            if enable_special_onu(network_card_ip, url, f):
                return True
            else:
                f.write(f'\n\n@@@@@@@@@@@@@@@@@@ 第{times}次尝试打开 telnet enable @@@@@@@@@@@@@@@@@@\n\n'.encode())

                if times == retry_times:
                    return False
                time.sleep(interval_time)
                times += 1
        else:
            f.write(f'\n\n@@@@@@@@@@@@@@@@@@ 第{times}次尝试打开 telnet enable @@@@@@@@@@@@@@@@@@\n\n，url:{url} 错误'.encode())
            return False


if __name__ == '__main__':
    f = open('a.txt', 'wb', buffering=0)
    url = 'http://192.168.0.1/cgi-bin/TelnetEnabled.asp?username=telecomsdmc&password=nE7jA%5m'
    Web_Page_Open_Telnet('192.168.0.22', url, f, 5, 10)
    #
    # import socket
    #
    # # 目标 URL 和主机信息
    # host = '192.168.0.1'
    # path = '/cgi-bin/TelnetEnabled.asp?username=telecomsdmc&password=nE7jA%5m'
    #
    # # 指定本地IP地址（您希望使用的网卡的IP地址）
    # local_ip = '192.168.0.22'
    # local_port = 0  # 系统会自动选择一个可用的端口
    #
    # # 创建套接字并绑定到指定的本地地址
    # sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # sock.bind((local_ip, local_port))
    # sock.connect((host, 80))
    #
    # # 构建 HTTP 请求
    # request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    #
    # # 发送请求
    # sock.sendall(request.encode('utf-8'))
    #
    # # 接收响应
    # response = b''
    # while True:
    #     data = sock.recv(4096)
    #     if not data:
    #         break
    #     response += data
    #
    # # 关闭套接字
    # sock.close()

    # 打印响应内容
    # print(response.decode('utf-8'))

from socket import getaddrinfo
from socket import *
import socket

# def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
#                       source_address=None):
#     """If *source_address* is set it must be a tuple of (host, port)
#     for the socket to bind as a source address before making the connection.
#     An host of '' or port 0 tells the OS to use the default.
#     source_address 如果设置, 必须是传递元组 (host, port), 默认是 ("", 0)
#     """
#
#     host, port = address
#     err = None
#     for res in getaddrinfo(host, port, 0, SOCK_STREAM):
#         af, socktype, proto, canonname, sa = res
#         sock = None
#         try:
#             sock = socket(af, socktype, proto)
#             # sock.bind(("192.168.20.2", 0)) # en0
#             # sock.bind(("192.168.8.100", 0)) # en1
#             # sock.bind(("127.0.0.1", 0)) # lo0
#             if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
#                 sock.settimeout(timeout)
#             if source_address:
#                 print("socket bind source_address: %s" % source_address)
#                 sock.bind(source_address)
#             sock.connect(sa)
#             return sock
#
#         except error as _:
#             err = _
#             if sock is not None:
#                 sock.close()
#     if err is not None:
#         raise err
#     else:
#         raise error("getaddrinfo returns an empty list")
import requests
from requests_toolbelt.adapters.source import SourceAddressAdapter


def enable_router(network_card_ip, gateway_ip):
    ip_address = ['192.168.1.2', '192.168.1.3']  # 要使用的网卡的 IP 地址
    # network_card_name=['eth0','eth1']
    url = "http://192.168.1.1/ubus/xlink.system.TelnetSet"
    data = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "call",
        "params": ["00000000000000000000000000000000", "xlink.system", "TelnetSet", {"data": {"enable": 1}}]
    }

    # 指定特定网卡的IP地址'192.168.121.1'，使用该网卡发送POST请求
    for i in ip_address:
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(i))
        s.mount('https://', SourceAddressAdapter((i, 8999)))
        # print(s.__dir__())
        print(s.__getattribute__('mount'))
        res = s.post(url, json=data)
        # print(res.text)


def enable_pon():
    ip_address = ['192.168.1.2', '192.168.1.3']
    url = "http://192.168.1.1/cgi-bin/sdmctelnet_enable.asp"

    for i in ip_address:
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(i))
        s.mount('https://', SourceAddressAdapter((i, 8999)))
        # print(s.__dir__())
        print(s.__getattribute__('mount'))
        res = s.get(url)
        print(res.json)


# enable_pon()

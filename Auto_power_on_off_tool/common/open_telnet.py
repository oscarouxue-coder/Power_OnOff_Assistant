import requests
from requests_toolbelt.adapters.source import SourceAddressAdapter


def enable_router(network_card_ip, gateway_ip):
    url = 'http://' + gateway_ip + '/ubus/xlink.system.TelnetSet'
    # network_card_name=['eth0','eth1']
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
    res = s.post(url, json=data)
    # print(res.text)
    res.json()


def enable_pon():
    ip_address = ['192.168.1.2', '192.168.1.3']
    url = "http://192.168.1.1/cgi-bin/sdmctelnet_enable.asp"

    for i in ip_address:
        s = requests.Session()
        s.mount('http://', SourceAddressAdapter(i))
        s.mount('https://', SourceAddressAdapter((i, 8999)))
        # print(s.__dir__())
        # print(s.__getattribute__('mount'))
        res = s.get(url)
        # print(res.json)


# enable_pon()

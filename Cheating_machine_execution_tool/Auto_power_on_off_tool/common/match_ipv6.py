import re

import re
import socket


def match_ipv6_addr(ipv6_str):
    ipv6_pattern = r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,7}:|(?::[A-Fa-f0-9]{1,4}){1,7}\b|\b::(?:[A-Fa-f0-9]{1,4}:)*[A-Fa-f0-9]{1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,6}:(?:[A-Fa-f0-9]{1,4})\b|\b(?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}\b|\b[A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6}\b|\b::(?::[A-Fa-f0-9]{1,4}){1,7}\b|\b(?:[A-Fa-f0-9]{1,4}:){2}(?::[A-Fa-f0-9]{1,4}){1,4}(?:%[0-9a-zA-Z]+)\b|\b(?:[A-Fa-f0-9]{1,4}:){1}(?::[A-Fa-f0-9]{1,4}){1,6}(?:%[0-9a-zA-Z]+)\b|\bfe80:(?::[A-Fa-f0-9]{0,4}){0,4}%[0-9a-zA-Z]+\b'

    # 使用正则表达式查找所有IPv6地址
    ipv6_addresses = re.findall(ipv6_pattern, ipv6_str)

    # 过滤掉不完整的IPv6地址，只保留完整的IPv6地址
    ipv6_addresses = [addr for addr in ipv6_addresses if 'fe80' not in addr or '%' in addr]

    # 打印找到的IPv6地址
    print("Found IPv6 addresses:")
    for address in ipv6_addresses:
        print(address)
    return ipv6_addresses


def is_ipv6_address(address):
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return True
    except socket.error:
        return False


if __name__ == "__main__":
    # 测试
    print(is_ipv6_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334"))  # True
    print(is_ipv6_address("2001:db8:85a3::8a2e:370:7334"))  # True
    print(is_ipv6_address("::1"))  # True
    print(is_ipv6_address("::"))  # True
    print(is_ipv6_address("1::"))  # True
    print(is_ipv6_address("1::3:4:5:6:7:8"))  # True
    print(is_ipv6_address("a::b:c:d:e:f:1.2.3.4"))  # False
    print(is_ipv6_address("1.2.3.4"))  # False
    print(is_ipv6_address("2001:171:101::"))
    print(is_ipv6_address('2001:172:101:0:1f0:5482:6e4f:74ef'))
    print(is_ipv6_address('2001:172:101:0:7495:13cf:8b46:7067'))
    str1 = """
    tcapi get WanInfo_Entry8 IP6
# 
# tcapi get WanInfo_Entry8 IP6
2001:172:101:0:7495:13cf:8b46:7067
2001:171:101::7ef
# 
          """
    print(match_ipv6_addr(ipv6_str=str1))
    a=match_ipv6_addr(ipv6_str=str1)
    print(is_ipv6_address(a[0]))

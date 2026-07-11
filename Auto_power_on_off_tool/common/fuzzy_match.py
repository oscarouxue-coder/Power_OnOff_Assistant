import re
import socket

wan_pattern = re.compile(r' (\d+)')


def Fuzzy_Match(key, value, result, f):
    if 'list' in str(type(value)):
        value = value[0]
        f.write('value 的类型是 list\n'.encode())
    flag = 1
    if '&&' in value:
        for i in value.split('&&'):
            f.write(i.encode())
            f.write('\n'.encode())
            if Fuzzy_Match_01(key, i, result, f):
                pass
            else:
                flag = 0
    else:
        if Fuzzy_Match_01(key, value, result, f):
            flag = 1
        else:
            flag = 0
    print(f'flag:{flag}')
    if flag:
        return True
    else:
        return False


# 对返回结果进行模糊匹配的函数
def Fuzzy_Match_01(key, value, result, f):
    # 使用 re 模块的 findall 方法匹配模式
    try:
        # f.write(f'需要指令的指令:{key},type:{type(key)}\n'.encode())
        f.write(f'》》》》》》》》》》》》》》》》》》》开始对比结果》》》》》》》》》》》》》》》》》\n'.encode())
        f.write(f'需要对比的结果是:{value}\n'.encode())
        # f.write(f'指令返回的结果: \n {result},type:{type(result)}\n'.encode())
        print(f'value:{value},type:{type(value)}\n')
        print(f'key:{key},type:{type(key)}\n')
        print(f'result:\n {result},type:{type(result)}\n')

        desc_fail = f'指令：{key} 的执行结果匹配失败，预期字符串：{value} 不在 执行结果：{result} 里面\n'
        desc_sucess = f'指令：{key} 的执行结果匹配成功，预期字符串：{value} 在 执行结果：{result} 里面\n'

        if 'IP6' in key and 'tcapi get WanInfo_Entry' in key:
            f.write(f"检测获取到的是否是 IPV6格式的IP\n".encode())
            ipv6_ip = match_ipv6_addr(result)
            if len(ipv6_ip) == 0:
                f.write(f'{key} 查询实际信息为：{result}\n'.encode())
                return False
            else:
                if is_ipv6_address(ipv6_ip[0]):
                    f.write(desc_sucess.encode())
                    return True
                else:
                    f.write(desc_fail.encode())
                    return False

        if '!' in value:
            print('----', value.split('!'))
            value = value.split('!')[1]
            f.write(f"检测反向结果，验证 {value} 不在执行结果里面\n".encode())
            desc_fail = f'指令：{key} 的执行结果匹配失败，预期字符串：{value} 在 执行结果：{result} 里面\n'
            desc_sucess = f'指令：{key} 的执行结果匹配成功，预期字符串：{value} 不在 执行结果：{result} 里面\n'
            matches = re.findall(value, result)
            print(matches, type(matches), value)
            if not matches:
                f.write(desc_sucess.encode())
                return True
            else:
                f.write(desc_fail.encode())
                return False

        # matches = re.findall(value, result) # 无法匹配返回值里面有()的情况
        # print(matches, type(matches), value, value == '00:00:00:00:00:00')
        # 判断匹配结果是否为空
        if value not in result:
            print('匹配 fail')
            f.write(desc_fail.encode())
            return False
        # else:
        #     if 'wan' in key:
        #         for i in result.split('\n'):
        #             # print(i)
        #             if value in i:
        #                 val = wan_pattern.search(i).group(1)
        #                 if int(val) > 0:
        #                     f.write(desc_sucess.encode())
        #                     return True
        #                 else:
        #                     f.write(desc_fail.encode())
        #                     return False
        else:
            print('pass')
            f.write(desc_sucess.encode())
            return True
    except Exception as e:
        f.write(f'{key} 执行失败，出现exception ：{e}\n'.encode())
        print(f'{key} 执行失败，出现exception：{e}\n')
        return False

    # 返回匹配结果
    # return matches[0]  # 这里只返回第一个匹配结果，根据实际需求进行修改


def is_ipv6_address(address):
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return True
    except socket.error:
        return False


def match_ipv6_addr(ipv6_str):
    # 正则表达式匹配IPv6地址，包括可能的前缀长度
    ipv6_pattern = r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,7}:|(?::[A-Fa-f0-9]{1,4}){1,7}\b|\b::(?:[A-Fa-f0-9]{1,4}:)*[A-Fa-f0-9]{1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,6}:(?:[A-Fa-f0-9]{1,4})\b|\b(?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}\b|\b(?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}\b|\b[A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6}\b|\b::(?::[A-Fa-f0-9]{1,4}){1,7}\b|\b(?:[A-Fa-f0-9]{1,4}:){2}(?::[A-Fa-f0-9]{1,4}){1,4}(?:%[0-9a-zA-Z]+)\b|\b(?:[A-Fa-f0-9]{1,4}:){1}(?::[A-Fa-f0-9]{1,4}){1,6}(?:%[0-9a-zA-Z]+)\b|\bfe80:(?::[A-Fa-f0-9]{0,4}){0,4}%[0-9a-zA-Z]+\b'

    # 使用正则表达式查找所有IPv6地址
    ipv6_addresses = re.findall(ipv6_pattern, ipv6_str)

    # 打印找到的IPv6地址
    print("Found IPv6 addresses:")
    for address in ipv6_addresses:
        print(address)
    return ipv6_addresses

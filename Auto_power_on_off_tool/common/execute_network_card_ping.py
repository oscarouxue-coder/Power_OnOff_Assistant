import subprocess
import time

import ping3

from common.my_logging import creat_logger
from common.get_network_card_ip import GetNetworkCardInfo


class Cmd(object):
    """
    执行bat文件
    """

    def __init__(self, logger):
        self.logger = logger

    def cmds(self, path='ping 192.168.2.1 -n 10'):
        success_count = 0
        fail_count = 0
        # self.logger.info('{}进行ping包测试'.format(path))
        c = subprocess.Popen(path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        s_count = 0
        f_count = 0
        # cur_line = c.stdout.readline().decode('gbk', 'ignore')
        # cur_line = c.stdout.readline().decode('gbk', 'ignore')
        while True:
            cur_line = c.stdout.readline().decode('gbk', 'ignore')
            if 'ttl=' in cur_line or 'TTL=' in cur_line:
                success_count += 1
                s_count += 1
                if s_count == 3:
                    self.logger.info('ping通：{}'.format(cur_line))
                    c.kill()
                    return True
            else:
                # fail_count += 1
                f_count += 1
                if f_count > 8:
                    c.kill()
                    # self.logger.info('ping 不通{}'.format(cur_line))
                    return False
                self.logger.info('{} 不通'.format(path))
                time.sleep(0.5)
                continue

    def cmd_ping_gen7(self, network_card_ip, host_ip, f):
        """
        :param network_card_ip: 网卡IP
        :param host_ip: 网关IP
        :return:
        """
        times = 0
        success_count = 0
        fail_count = 0

        # cmd = 'ping -S ' + str(network_card_ip) + ' 192.168.1.1 -t -n 50'

        self.logger.info(f'start ping src：{network_card_ip} to {host_ip}')
        f.write(f'start ping src：{network_card_ip} to {host_ip}\n'.encode())
        while times <= 50:
            times += 1
            try:
                response_time = ping3.ping(dest_addr=host_ip, timeout=5, src_addr=network_card_ip)
                f.write(f'ping response_time:{response_time} {type(response_time)}\n'.encode())
            except Exception as e:
                # 防止出现一次异常就return False   errorTab[10049] = "Cannot assign requested address."
                self.logger.error(f'ping error:{e}')
                f.write(f'ping error:{e}\n'.encode())
                if fail_count >= 30:
                    return False
                else:
                    fail_count += 1
                    continue
            # self.time > 50
            else:
                print(response_time)
                if response_time is None or response_time is False:
                    fail_count += 1
                    # print('eeee')
                    # print(response_time)
                else:
                    success_count += 1

                time.sleep(1)
                if success_count >= 10:
                    self.logger.info(f'The network card with IP {network_card_ip} has been pinged')
                    f.write(f'The network card with IP {network_card_ip} has been pinged\n'.encode())
                    return True
                elif fail_count >= 30:
                    fail_count += 1
                    self.logger.error(f'The network card with IP {network_card_ip} is not OK:{response_time}')
                    f.write(f'The network card with IP {network_card_ip} is not OK\n'.encode())
                    return False

        # self.logger.info(f'execute：{cmd}')
        # success_count = 0
        # fail_count = 0
        # # self.logger.info('{}进行ping包测试'.format(path))
        # time.sleep(2)
        # c = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        # s_count = 0
        # f_count = 0
        # # cur_line = c.stdout.readline().decode('gbk', 'ignore')
        # # cur_line = c.stdout.readline().decode('gbk', 'ignore')
        # while True:
        #     cur_line = c.stdout.readline().decode('gbk', 'ignore')
        #     # self.logger.info(cur_line)
        #     if 'ttl=' in cur_line or 'TTL=' in cur_line:
        #         success_count += 1
        #         s_count += 1
        #         if s_count == 10:  # 减少次数为10次 8.25
        #             self.logger.info(f'The network adapter whose IP address is: {network_card_ip} PING is OK')
        #             c.kill()
        #             c.terminate()
        #             c.wait()
        #             if c.poll() == None:
        #                 time.sleep(0.5)
        #                 c.terminate()
        #                 time.sleep(0.5)
        #                 c.wait()
        #
        #             return True
        #     else:
        #         fail_count += 1
        #         if fail_count > 20:  # 增加失败次数，防止出现网络不稳定的情况   8.25
        #             # self.logger.error(f'IP为：{network_card_ip}的网卡没有ping通192.168.1.1')
        #             self.logger.info(f'The network adapter whose IP address is: {network_card_ip} PING is NOK')
        #             c.kill()
        #             c.terminate()
        #             c.wait()
        #             if c.poll() == None:
        #                 time.sleep(0.5)
        #                 c.terminate()
        #                 time.sleep(0.5)
        #                 c.wait()
        #             return False
        #         time.sleep(0.5)

    def cmd_stop(self, path):
        path = 'ping -S' + path + ' -n 10'
        success_count = 0
        fail_count = 0
        # self.logger.info('{}进行ping包测试'.format(path))
        c = subprocess.Popen(path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        s_count = 0
        f_count = 0
        cur_line = c.stdout.readline().decode('gbk', 'ignore')
        cur_line = c.stdout.readline().decode('gbk', 'ignore')
        while True:
            cur_line = c.stdout.readline().decode('gbk', 'ignore')
            self.logger.info(f'{cur_line}')
            if 'ttl=' in cur_line or 'TTL=' in cur_line:
                success_count += 1
                s_count += 1
                if s_count > 4:
                    c.kill()
                    return False
            else:
                # fail_count += 1
                f_count += 1
                if f_count > 4:
                    # self.logger.info('ping 不通{}'.format(cur_line))
                    c.kill()
                    return True
                self.logger.info('{} 不通'.format(path))

    def command(self, cmd='wmic nic where "Netenabled=True and PhysicalAdapter=True" get name,speed'):
        c = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        list1 = []
        result_01 = c.stdout.readline().decode('gbk', 'ignore')
        while result_01:
            result = c.stdout.readline().decode('gbk', 'ignore')
            result = result.strip()
            if len(result):
                list1.append(result)
            else:
                break
        times = 1
        fail_flag = 0
        for i in range(0, len(list1)):
            # print(type(i))
            result = list1[i].split()
            # print(type(result[-1]))
            if 1000000000 == int(result[-1]):
                self.logger.info('{}网卡速率是：{}M'.format(result[0], int(result[-1]) // 1000 // 1000))
            else:
                self.logger.error('{}网卡速率是：{}M，不是1000M'.format(result[0], int(result[-1]) // 1000 // 1000))
                fail_flag = 1
            times += 1
        if fail_flag:
            # print('error')
            c.kill()
            return False
        else:
            # print('ture')
            c.kill()
            return True


if __name__ == '__main__':
    f = open('a.txt', 'wb', buffering=0)
    logger = creat_logger('AX3000_')
    cmd = Cmd(logger)
    # # cmd.command('wmic nic where "Netenabled=True and PhysicalAdapter=True" get name,speed')
    # cmd.cmds('iperf3 -s -p 7890')
    cmd.cmd_ping_gen7('192.168.1.2', 'www.baidu.com', f)
from config.config_driver import OperationConfig

cf = OperationConfig()


def get_network_card_ip(num, path='./config/network_card_ip.ini'):
    channel = f'channel_{num}'
    network_card_ip = cf.read_ini(channel, 'network_card_ip', path=path)
    return network_card_ip


if __name__ == '__main__':

    print(get_network_card_ip(2))

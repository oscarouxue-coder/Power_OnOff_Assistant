import random


def create_float_num(range_num):
    # 产生1到10之间的随机浮点数
    float_num = random.uniform(0, range_num)
    # print(round(random_float, 3))
    return round(float_num, 3)


if __name__ == "__main__":
    print(create_float_num(1))
    print(create_float_num(6))
    import re

    pattern = re.compile(r'channel_(\d+), started daemon (\d+)')
    str = r'<Thread(channel_1, started daemon 7736)>'
    print(pattern.search(str).group(2))

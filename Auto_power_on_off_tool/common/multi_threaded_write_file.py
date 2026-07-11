from multiprocessing import pool
import os
import time


def multi_thread_write_file(name):
    timestamp = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
    file_path = f'test_results/{name}'
    if not os.path.exists(file_path):
        os.makedirs(file_path)
    file_name = file_path + '/' + name + '_' + timestamp + '_PCIE_error.log'
    return file_name


if __name__ == '__main__':
    file_name = multi_thread_write_file('test')
    print(file_name)
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write('a')

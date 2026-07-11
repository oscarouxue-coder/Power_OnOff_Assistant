import os
import sys
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, QCoreApplication


class FileDeleteWorker(QThread):
    """文件删除工作线程"""
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, files_path, files_suffix):
        super().__init__()
        self.files_path = files_path
        self.files_suffix = files_suffix

    def run(self):
        try:
            self.delete_files_in_directory(self.files_path, self.files_suffix)
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(f'删除文件报错：{e}')

    def delete_files_in_directory(self, directory, files_suffix=''):
        """删除目录中的文件"""
        try:
            print('开始删除文件', flush=True)
            for item in os.listdir(directory):
                item_full_path = os.path.join(directory, item)
                if os.path.isfile(item_full_path):
                    if files_suffix and not item_full_path.endswith(files_suffix):
                        continue
                    os.remove(item_full_path)
                    print(f"Deleted file: {item_full_path}", flush=True)
                elif os.path.isdir(item_full_path):
                    self.delete_files_in_directory(item_full_path, files_suffix)
        except Exception as e:
            print(f"删除文件出错: {e}", flush=True)
            raise e


class FileCleaner:
    """文件清理器 - 使用事件驱动模式"""

    def __init__(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.on_timer_timeout)
        self.worker = None

    def start_cleaning(self, files_path, files_suffix, interval_seconds):
        """启动定时清理"""
        self.files_path = files_path
        self.files_suffix = files_suffix

        # 立即执行一次清理
        self.start_deletion_worker()

        # 启动定时器
        self.timer.start(interval_seconds * 1000)
        print(f"定时清理已启动，间隔: {interval_seconds}秒", flush=True)

    def stop_cleaning(self):
        """停止定时清理"""
        self.timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
        print("定时清理已停止", flush=True)

    def on_timer_timeout(self):
        """定时器超时处理"""
        print("定时器触发，开始清理文件", flush=True)
        self.start_deletion_worker()

    def start_deletion_worker(self):
        """启动文件删除工作线程"""
        # 如果前一个工作线程还在运行，等待它完成
        if self.worker and self.worker.isRunning():
            print("前一个清理任务仍在运行，等待完成", flush=True)
            return

        self.worker = FileDeleteWorker(self.files_path, self.files_suffix)
        self.worker.finished_signal.connect(lambda: print("清理完成", flush=True))
        self.worker.error_signal.connect(lambda msg: print(f"清理错误: {msg}", flush=True))
        self.worker.start()


if __name__ == "__main__":
    # 创建Qt应用程序实例
    app = QCoreApplication(sys.argv)

    # 创建文件清理器
    cleaner = FileCleaner()

    # 启动定时清理（每30秒一次）
    target_directory = r'F:\script_logs'
    cleaner.start_cleaning(target_directory, '', 30)

    # 设置60秒后停止清理并退出程序
    QTimer.singleShot(60000, lambda: (cleaner.stop_cleaning()))

    # 启动Qt事件循环
    print("程序已启动，60秒后自动退出", flush=True)
    sys.exit(app.exec_())
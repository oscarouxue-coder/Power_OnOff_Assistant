import builtins
import time

class TimestampedFile:
    def __init__(self, filepath, mode='a',buffer=0):
        self.file = open(filepath, mode,buffering=0)

    def write(self, text):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.file.write(f'{timestamp} - {text}'.encode())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.close()

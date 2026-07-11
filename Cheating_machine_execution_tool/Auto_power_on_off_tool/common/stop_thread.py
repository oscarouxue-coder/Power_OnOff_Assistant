#!/usr/bin/env python
# coding: utf-8
import ctypes
import inspect
import sys
import threading
import time


class StoppableThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check

    regularly for the stopped() condition."""

    import threading
    import time
    import inspect
    import ctypes

    def _async_raise(self, tid, exctype):
        try:
            """raises the exception, performs cleanup if needed"""
            tid = ctypes.c_long(tid)
            if not inspect.isclass(exctype):
                exctype = type(exctype)
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
            if res == 0:
                # raise ValueError("invalid thread id")
                return False
            elif res != 1:
                # """if it returns a number greater than one, you're in trouble,
                # and you should call it again with exc=NULL to revert the effect"""
                ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
                # raise SystemError("PyThreadState_SetAsyncExc failed")
                return False
        except Exception as e:
            print(str(e))
            return False
    def stop_thread(self, thread):
        self._async_raise(thread.ident, SystemExit)

# class StoppableThread(threading.Thread):
#     """Thread class with a stop() method. The thread itself has to check
#     regularly for the stopped() condition."""
#
#     def __init__(self, *args, **keywords):
#         threading.Thread.__init__(self, *args, **keywords)
#         self.killed = False
#
#     def start(self):
#         self.__run_backup = self.run
#         self.run = self.__run
#         threading.Thread.start(self)
#
#     def __run(self):
#         sys.settrace(self.globaltrace)
#         self.__run_backup()
#         self.run = self.__run_backup
#
#     def globaltrace(self, frame, event, arg):
#         if event == 'call':
#             return self.localtrace
#         else:
#             return None
#
#     def localtrace(self, frame, event, arg):
#         if self.killed:
#             if event == 'line':
#                 raise SystemExit()
#         return self.localtrace
#
#     def kill(self):
#         self.killed = True

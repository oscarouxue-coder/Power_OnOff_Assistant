"""Authenticated per-user/session local IPC. Messages contain JSON, never pickle."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from multiprocessing.connection import Client, Listener
from multiprocessing import AuthenticationError

from src.core.ai_credentials import WindowsCredentialCipher
from src.core.host_resource_lock import HostResourceLock, HostResourceBusy


class WorkspaceInstance:
    def __init__(self, directory):
        self.directory = Path(directory)
        session = ctypes.c_ulong()
        if os.name == 'nt':
            ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        identity = str(self.directory.resolve()).casefold() + '|' + str(session.value)
        self.key = hashlib.sha256(identity.encode()).hexdigest()[:32]
        self.address = r'\\.\pipe\LineCheckWorkspace-' + self.key
        self.lease = HostResourceLock(['workspace:' + self.key], reentrant=False)
        self.listener = None
        self.stop = threading.Event()
        self.closing_requested = threading.Event()
        self.requests = queue.Queue(maxsize=64)
        self.authkey = None

    def start(self, project=None):
        """True for primary; False after forwarding to the existing main window."""
        try:
            self.lease.acquire()
        except HostResourceBusy:
            last_error = None
            for _ in range(20):
                try:
                    auth = self._read_key()
                    with Client(self.address, family='AF_PIPE', authkey=auth) as connection:
                        connection.send_bytes(json.dumps(dict(action='open', project=str(project or ''))).encode())
                        if not connection.poll(3):
                            raise RuntimeError('现有工作区未确认接收请求')
                        if connection.recv_bytes(1024) != b'accepted':
                            raise RuntimeError('现有工作区正在安全退出，请等待结束后重试')
                    return False
                except (OSError, EOFError, AuthenticationError, RuntimeError, ValueError) as exc:
                    last_error = exc
                    time.sleep(.1)
            raise RuntimeError('已有工作区正在启动或无响应；未启动第二个实例：' + str(last_error)) from None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.authkey = secrets.token_bytes(32)
            encrypted = WindowsCredentialCipher().encrypt(base64.b64encode(self.authkey).decode(), self.key)
            self._key_path().write_bytes(encrypted)
            self.listener = Listener(self.address, family='AF_PIPE', authkey=self.authkey)
            self.worker = threading.Thread(target=self._serve, name='workspace-ipc', daemon=True)
            self.worker.start()
            return True
        except BaseException:
            self.lease.close()
            raise

    def _key_path(self):
        return self.directory / ('ipc-' + self.key + '.key')

    def _read_key(self):
        return base64.b64decode(WindowsCredentialCipher().decrypt(self._key_path().read_bytes(), self.key))

    def _serve(self):
        while True:
            try:
                connection = self.listener.accept()
                with connection:
                    if not connection.poll(3):
                        continue
                    value = json.loads(connection.recv_bytes(32768).decode('utf-8'))
                    if not isinstance(value, dict) or value.get('action') != 'open' or not isinstance(value.get('project'), str):
                        continue
                    if self.closing_requested.is_set() and not self.stop.is_set():
                        connection.send_bytes(b'closing')
                        continue
                    if not self.stop.is_set():
                        self.requests.put_nowait(value)
                    connection.send_bytes(b'accepted')
                    if self.stop.is_set():
                        return
            except (OSError, EOFError, AuthenticationError, ValueError, queue.Full):
                # Invalid clients must not kill the authenticated listener. The
                # owner sends a valid wake-up request before closing the handle.
                continue

    def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        if self.listener:
            try:
                if self.worker.is_alive():
                    with Client(self.address, family='AF_PIPE', authkey=self.authkey) as connection:
                        connection.send_bytes(b'{"action":"open","project":""}')
                        if connection.poll(3):
                            connection.recv_bytes(1024)
            except (OSError, EOFError):
                pass
            self.listener.close()
        self.lease.close()

"""Windows 当前用户 DPAPI；测试可注入替代实现，生产不降级为明文。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsCredentialCipher:
    def _transform(self, value: bytes, entropy: bytes, encrypt: bool) -> bytes:
        if os.name != "nt":
            raise RuntimeError("API 密钥持久化需要 Windows 当前用户 DPAPI")
        buf = ctypes.create_string_buffer(value)
        salt = ctypes.create_string_buffer(entropy)
        source = _Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        extra = _Blob(len(entropy), ctypes.cast(salt, ctypes.POINTER(ctypes.c_ubyte)))
        output = _Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if encrypt:
            function = crypt.CryptProtectData
            function.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
            ok = function(ctypes.byref(source), "LineCheckAssistant AI", ctypes.byref(extra),
                          None, None, 1, ctypes.byref(output))
        else:
            function = crypt.CryptUnprotectData
            function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
            ok = function(ctypes.byref(source), None, ctypes.byref(extra), None, None, 1,
                          ctypes.byref(output))
        if not ok:
            raise RuntimeError("DPAPI 凭据加密/解密失败，请在当前 Windows 账号重新填写密钥")
        try:
            return ctypes.string_at(output.data, output.size)
        finally:
            kernel.LocalFree(output.data)

    def encrypt(self, value: str, binding: str) -> bytes:
        return self._transform(value.encode("utf-8"), binding.encode("utf-8"), True)

    def decrypt(self, value: bytes, binding: str) -> str:
        return self._transform(value, binding.encode("utf-8"), False).decode("utf-8")

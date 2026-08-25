from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol


class SecretProtector(Protocol):
    def protect(self, value: str) -> bytes: ...
    def unprotect(self, value: bytes) -> str: ...


class SecretProtectionUnavailable(RuntimeError):
    pass


class WindowsDpapiProtector:
    """Encrypt secrets for the current Windows user using native DPAPI."""

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def __init__(self) -> None:
        if os.name != "nt":
            raise SecretProtectionUnavailable("Windows DPAPI is unavailable on this platform")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    @classmethod
    def _input_blob(cls, value: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(value)
        blob = cls._Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def protect(self, value: str) -> bytes:
        source, keepalive = self._input_blob(value.encode("utf-8"))
        target = self._Blob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            self._kernel32.LocalFree(target.pbData)
            del keepalive

    def unprotect(self, value: bytes) -> str:
        source, keepalive = self._input_blob(value)
        target = self._Blob()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
        finally:
            self._kernel32.LocalFree(target.pbData)
            del keepalive


def platform_secret_protector() -> SecretProtector:
    if os.name == "nt":
        return WindowsDpapiProtector()
    raise SecretProtectionUnavailable(
        "configure a platform secret protector before running a worker"
    )

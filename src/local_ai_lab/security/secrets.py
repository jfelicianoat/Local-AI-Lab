from __future__ import annotations

import ctypes
import os
import secrets
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


class PassphraseProtector:
    """Encrypt Linux/WSL credentials with a caller supplied, non-persisted passphrase."""

    _PREFIX = b"LAL1"

    def __init__(self, passphrase: str) -> None:
        if len(passphrase) < 16:
            raise SecretProtectionUnavailable("LOCAL_AI_LAB_WORKER_PASSPHRASE must contain at least 16 characters")
        self._passphrase = passphrase.encode("utf-8")

    def _key(self, salt: bytes) -> bytes:
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

        return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(self._passphrase)

    def protect(self, value: str) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
        return self._PREFIX + salt + nonce + AESGCM(self._key(salt)).encrypt(
            nonce, value.encode("utf-8"), self._PREFIX
        )

    def unprotect(self, value: bytes) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if len(value) < 48 or not value.startswith(self._PREFIX):
            raise ValueError("protected Worker credential has an invalid format")
        salt, nonce, encrypted = value[4:20], value[20:32], value[32:]
        try:
            return AESGCM(self._key(salt)).decrypt(nonce, encrypted, self._PREFIX).decode("utf-8")
        except Exception as error:
            raise SecretProtectionUnavailable("Worker passphrase is wrong or credential is corrupt") from error

def platform_secret_protector() -> SecretProtector:
    if os.name == "nt":
        return WindowsDpapiProtector()
    passphrase = os.environ.get("LOCAL_AI_LAB_WORKER_PASSPHRASE", "")
    if not passphrase:
        raise SecretProtectionUnavailable(
            "set LOCAL_AI_LAB_WORKER_PASSPHRASE before pairing or running the Linux/WSL Worker"
        )
    return PassphraseProtector(passphrase)

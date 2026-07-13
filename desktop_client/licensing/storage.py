from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from .models import LicenseCredential


class CredentialStoreError(RuntimeError):
    pass


class CredentialProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...
    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, object]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


class DPAPIProtector:
    """Encrypt credentials for the current Windows user with CryptProtectData."""

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ENTROPY = b"xianyuxian-license-credential-v1"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows DPAPI is only available on Windows")
        self.crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
        self.crypt32.CryptProtectData.restype = wintypes.BOOL
        self.crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
        self.crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p

    def protect(self, plaintext: bytes) -> bytes:
        input_blob, input_buffer = _blob(plaintext)
        entropy_blob, entropy_buffer = _blob(self.ENTROPY)
        output_blob = _DATA_BLOB()
        success = self.crypt32.CryptProtectData(
            ctypes.byref(input_blob), "xianyuxian license", ctypes.byref(entropy_blob),
            None, None, self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output_blob),
        )
        _ = input_buffer, entropy_buffer
        if not success:
            raise CredentialStoreError(f"CryptProtectData failed: {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        input_blob, input_buffer = _blob(ciphertext)
        entropy_blob, entropy_buffer = _blob(self.ENTROPY)
        output_blob = _DATA_BLOB()
        success = self.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, ctypes.byref(entropy_blob),
            None, None, self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output_blob),
        )
        _ = input_buffer, entropy_buffer
        if not success:
            raise CredentialStoreError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)


def default_credential_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable; this client module requires Windows")
    return Path(local_app_data) / "xianyuxian" / "license" / "credential.bin"


class CredentialStore:
    def __init__(self, path: Path, protector: CredentialProtector):
        self.path = path
        self.protector = protector

    @classmethod
    def windows_default(cls) -> "CredentialStore":
        return cls(default_credential_path(), DPAPIProtector())

    def load(self) -> LicenseCredential | None:
        if not self.path.exists():
            return None
        try:
            plaintext = self.protector.unprotect(self.path.read_bytes())
            data = json.loads(plaintext.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("credential payload must be an object")
            return LicenseCredential.from_dict(data)
        except Exception as exc:
            raise CredentialStoreError("stored license credential is unreadable or corrupted") from exc

    def save(self, credential: LicenseCredential) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            credential.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = self.protector.protect(payload)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_bytes(ciphertext)
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

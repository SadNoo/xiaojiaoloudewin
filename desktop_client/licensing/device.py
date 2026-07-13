from __future__ import annotations

import hashlib
import os
import platform
import socket
import sys
from dataclasses import dataclass


DEVICE_NAMESPACE = b"xianyuxian-device-v1\0"


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    device_name: str
    os_version: str
    architecture: str


def derive_device_id(machine_guid: str) -> str:
    normalized = machine_guid.strip().lower()
    if len(normalized) < 8:
        raise ValueError("Windows MachineGuid is unavailable or invalid")
    digest = hashlib.sha256(DEVICE_NAMESPACE + normalized.encode("utf-8")).hexdigest()
    return f"win-{digest}"


def _read_machine_guid() -> str:
    if sys.platform != "win32":
        raise RuntimeError("Windows MachineGuid can only be read on Windows")
    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        access,
    ) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
    return str(value)


def get_windows_device_identity() -> DeviceIdentity:
    override = os.getenv("XIANYUXIAN_DEVICE_ID_OVERRIDE")
    if override:
        device_id = derive_device_id(override)
    else:
        device_id = derive_device_id(_read_machine_guid())
    return DeviceIdentity(
        device_id=device_id,
        device_name=socket.gethostname()[:160],
        os_version=platform.platform()[:100],
        architecture=platform.machine()[:40] or "x64",
    )


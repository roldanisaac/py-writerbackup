"""
Drive detection and ejection utilities for Windows.
Uses psutil for drive enumeration and ctypes/subprocess for safe removal.
"""

import os
import ctypes
import string
import subprocess
from dataclasses import dataclass, field
from typing import List


@dataclass
class RemovableDrive:
    letter: str          # e.g. "E"
    label: str           # volume label
    path: str            # e.g. "E:\\"

    def __str__(self) -> str:
        display = self.label if self.label else "Sin etiqueta"
        return f"{self.letter}:\\  [{display}]"


def get_removable_drives() -> List[RemovableDrive]:
    """Return all removable drives currently connected (Windows only)."""
    drives: List[RemovableDrive] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask >> i & 1):
            continue
        drive_path = f"{letter}:\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
        # DRIVE_REMOVABLE = 2
        if drive_type == 2:
            vol_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.kernel32.GetVolumeInformationW(
                drive_path, vol_buf, 256,
                None, None, None, None, 0
            )
            drives.append(RemovableDrive(
                letter=letter,
                label=vol_buf.value,
                path=drive_path,
            ))
    return drives


def eject_drive(drive_letter: str) -> bool:
    """
    Safely eject a removable drive by letter (e.g. "E").
    Uses ctypes DeviceIoControl: lock → dismount → eject media.
    This is synchronous and reliable even after recent writes to the drive.
    Falls back to PowerShell InvokeVerb if ctypes approach fails.
    Returns True on success, False on failure.
    """
    GENERIC_READ             = 0x80000000
    GENERIC_WRITE            = 0x40000000
    FILE_SHARE_READ          = 0x00000001
    FILE_SHARE_WRITE         = 0x00000002
    OPEN_EXISTING            = 3
    FSCTL_LOCK_VOLUME        = 0x00090018
    FSCTL_DISMOUNT_VOLUME    = 0x00090020
    IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808

    kernel32 = ctypes.windll.kernel32
    drive_unc = f"\\\\.\\{drive_letter}:"
    handle = kernel32.CreateFileW(
        drive_unc,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    INVALID_HANDLE = -1
    if handle == INVALID_HANDLE:
        return _eject_powershell(drive_letter)

    try:
        ret = ctypes.c_ulong(0)
        kernel32.DeviceIoControl(
            handle, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(ret), None)
        kernel32.DeviceIoControl(
            handle, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(ret), None)
        ok = kernel32.DeviceIoControl(
            handle, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(ret), None)
        return bool(ok)
    except Exception:
        return _eject_powershell(drive_letter)
    finally:
        kernel32.CloseHandle(handle)


def _eject_powershell(drive_letter: str) -> bool:
    """Fallback eject via PowerShell InvokeVerb."""
    drive_path = f"{drive_letter}:\\"
    ps_script = (
        f"$shell = New-Object -ComObject Shell.Application; "
        f"$folder = $shell.Namespace(17).ParseName('{drive_path}'); "
        f"$folder.InvokeVerb('Eject')"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False

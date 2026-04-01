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
    Safely eject a drive by letter (e.g. "E").
    Uses a PowerShell call to invoke the Windows shell verb 'Eject'.
    Returns True on success, False on failure.
    """
    drive_path = f"{drive_letter}:\\"
    ps_script = (
        f"$shell = New-Object -ComObject Shell.Application; "
        f"$folder = $shell.Namespace(17).ParseName('{drive_path}'); "
        f"$folder.InvokeVerb('Eject')"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, timeout=15
        )
        return result.returncode == 0
    except Exception:
        return False

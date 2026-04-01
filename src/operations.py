"""
File operations: compression and extraction for Writer Helper.
Handles ZIP/RAR compression of folders and extraction of ZIP/RAR/TAR archives.
"""

import os
import hashlib
import shutil
import subprocess
import zipfile
import tarfile
from datetime import datetime


def _time_suffix() -> str:
    """Return current date/time suffix like '04-01 07-47pm'."""
    now = datetime.now()
    meridian = "am" if now.hour < 12 else "pm"
    hour_12 = now.hour % 12 or 12
    return now.strftime(f"%m-%d {hour_12:02d}-%M") + meridian


def compress_folder(folder_path: str, rar_tool_path: str = "") -> list[str]:
    """
    Compress a folder to both ZIP and RAR files with date/time suffix.
    Returns a list of paths to the created files.
    Format: FolderName MM-DD HH-MMam.zip / .rar
    """
    folder_path = folder_path.rstrip("/\\")
    folder_name = os.path.basename(folder_path)
    parent_dir = os.path.dirname(folder_path)
    time_suffix = _time_suffix()
    base_name = f"{folder_name} {time_suffix}"
    results = []

    # ── ZIP ──
    zip_path = os.path.join(parent_dir, base_name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_abs = os.path.join(root, file)
                arcname = os.path.relpath(file_abs, start=os.path.dirname(folder_path))
                zf.write(file_abs, arcname)
    results.append(zip_path)

    # ── RAR ──
    if rar_tool_path and os.path.isfile(rar_tool_path):
        rar_path = os.path.join(parent_dir, base_name + ".rar")
        cmd = [
            rar_tool_path, "a", "-r", "-ep1", "-y",
            rar_path, folder_path + os.sep,
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode == 0:
            results.append(rar_path)
        else:
            raise RuntimeError(
                f"Rar.exe falló (código {proc.returncode}): "
                f"{proc.stderr.decode(errors='replace')}"
            )
    else:
        raise FileNotFoundError(
            f"No se encontró Rar.exe en: {rar_tool_path}\n"
            "Configura la ruta en Configuración."
        )

    return results


def build_output_names(folder_path: str) -> list[str]:
    """Return the filenames that compress_folder would produce (preview)."""
    folder_name = os.path.basename(folder_path.rstrip("/\\"))
    ts = _time_suffix()
    return [f"{folder_name} {ts}.zip", f"{folder_name} {ts}.rar"]


def file_sha256(path: str) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_and_verify(src_path: str, dest_dir: str) -> str:
    """
    Copy src_path into dest_dir and verify integrity via SHA-256.
    Returns the destination file path on success, raises RuntimeError on mismatch.
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(src_path))
    shutil.copy2(src_path, dest_path)
    if file_sha256(src_path) != file_sha256(dest_path):
        raise RuntimeError(f"Integrity check failed for {dest_path}")
    return dest_path


def extract_archive(archive_path: str, dest_folder: str, unrar_tool_path: str = None):
    """
    Extract a compressed file to dest_folder.
    Supports .zip, .rar, .tar, .tar.gz, .tgz
    Uses rarfile library for .rar (same approach as uncompress-sample.py).
    """
    os.makedirs(dest_folder, exist_ok=True)
    lower = archive_path.lower()

    if lower.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_folder)
        return True, "Extracción ZIP completada."

    elif lower.endswith(".rar"):
        if not unrar_tool_path or not os.path.isfile(unrar_tool_path):
            return False, f"La herramienta UnRAR no se encuentra: {unrar_tool_path}"
        # Call UnRAR.exe directly in a single pass (much faster than rarfile
        # which spawns one process per member). The CLI UnRAR.exe is a console
        # app so CREATE_NO_WINDOW hides it properly — no GUI popup.
        cmd = [unrar_tool_path, "x", "-y", "-o+", archive_path, dest_folder + os.sep]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode not in (0, 1):  # 1 = warnings, still OK
            return False, f"UnRAR falló (código {result.returncode}): {result.stderr.decode(errors='replace')}"
        return True, "Extracción RAR completada."

    elif lower.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest_folder)
        return True, "Extracción TAR completada."

    return False, "Formato de archivo no soportado."


def get_sha256(file_path):
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

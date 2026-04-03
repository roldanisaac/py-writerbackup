"""
Writer Helper — main application entry point.
Two modes:
  1. Compress a folder and copy it to selected removable drives.
  2. Extract a ZIP/RAR from a removable drive to a destination folder.
"""

import json
import os
import shutil
import sys
import threading
import time
import tkinter as tk
import winsound
from tkinter import filedialog, messagebox, ttk

# Allow running from repo root or from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from operations import build_output_names, compress_folder, copy_and_verify, extract_archive
from drive_manager import RemovableDrive, eject_drive, get_removable_drives

# ── Config helpers ────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_DEFAULTS = {
    "usb_destination_path": "My Folder",
    "extract_source_drive": "",
    "extract_destination_path": os.path.join(os.path.expanduser("~"), "Desktop"),
    "unrar_tool_path": r"C:\Program Files\UnRAR\UnRAR.exe",
    "rar_tool_path": r"C:\Program Files\TotalCommander2021\Packers\WinRAR\Rar.exe",
    "compressed_extensions": [".zip", ".rar", ".tar", ".tar.gz", ".tgz"],
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = {**_DEFAULTS, **data}
    else:
        cfg = dict(_DEFAULTS)
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


# ── Colour palette ────────────────────────────────────────────────────────────

BG = "#1e1e2e"
PANEL = "#2a2a3e"
ACCENT = "#7c6af7"
ACCENT_HOVER = "#9a8fff"
FG = "#cdd6f4"
FG_DIM = "#8890a8"
SUCCESS = "#a6e3a1"
ERROR = "#f38ba8"
BORDER = "#45475a"

BTN_STYLE = {
    "bg": ACCENT, "fg": "#ffffff", "activebackground": ACCENT_HOVER,
    "activeforeground": "#ffffff", "relief": "flat", "bd": 0,
    "font": ("Segoe UI", 11, "bold"), "cursor": "hand2",
    "padx": 18, "pady": 10,
}

LABEL_STYLE = {"bg": BG, "fg": FG, "font": ("Segoe UI", 10)}
TITLE_STYLE = {"bg": BG, "fg": FG, "font": ("Segoe UI", 14, "bold")}
DIM_STYLE = {"bg": BG, "fg": FG_DIM, "font": ("Segoe UI", 9)}
ENTRY_STYLE = {
    "bg": PANEL, "fg": FG, "insertbackground": FG,
    "relief": "flat", "bd": 0, "font": ("Segoe UI", 10),
    "highlightthickness": 1, "highlightbackground": BORDER,
    "highlightcolor": ACCENT,
}


def style_scrolledtext(widget):
    widget.config(bg=PANEL, fg=FG_DIM, font=("Consolas", 9),
                  relief="flat", bd=0, state="disabled",
                  highlightthickness=1, highlightbackground=BORDER)


# ── Shared log widget helper ──────────────────────────────────────────────────

def log_msg(text_widget: tk.Text, msg: str, color: str = FG_DIM) -> None:
    text_widget.config(state="normal")
    text_widget.insert("end", msg + "\n")
    text_widget.tag_add(color, f"end-{len(msg)+2}c", "end-1c")
    text_widget.tag_config(color, foreground=color)
    text_widget.see("end")
    text_widget.config(state="disabled")


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 1 — Home (option selector)
# ═══════════════════════════════════════════════════════════════════════════════

class HomeScreen(tk.Frame):
    def __init__(self, master: "App"):
        super().__init__(master, bg=BG)
        self.master: "App" = master
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)

        tk.Label(self, text="✍  Writer Backup", bg=BG, fg=FG,
                 font=("Segoe UI", 20, "bold")).grid(row=0, column=0, pady=(50, 8))
        tk.Label(self, text="¿Qué deseas hacer?", **DIM_STYLE).grid(row=1, column=0, pady=(0, 40))

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=2, column=0)

        compress_btn = tk.Button(
            btn_frame, text="📦  Comprimir y copiar a USB",
            command=lambda: self.master.show(CompressScreen),
            width=28, **BTN_STYLE,
        )
        compress_btn.grid(row=0, column=0, padx=20, pady=12)

        extract_btn = tk.Button(
            btn_frame, text="📂  Extraer desde USB",
            command=lambda: self.master.show(ExtractScreen),
            width=28, **BTN_STYLE,
        )
        extract_btn.grid(row=1, column=0, padx=20, pady=12)

        cfg_btn = tk.Button(
            btn_frame, text="⚙  Configuración",
            command=lambda: self.master.show(ConfigScreen),
            bg=PANEL, fg=FG_DIM, activebackground=BORDER, activeforeground=FG,
            relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
            padx=10, pady=6,
        )
        cfg_btn.grid(row=2, column=0, pady=(20, 0))


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 2 — Compress & Copy
# ═══════════════════════════════════════════════════════════════════════════════

class CompressScreen(tk.Frame):
    def __init__(self, master: "App"):
        super().__init__(master, bg=BG)
        self.master: "App" = master
        self.cfg = load_config()
        self.folder_var = tk.StringVar()
        self.preview_var = tk.StringVar(value="—")
        self.all_var = tk.BooleanVar(value=True)
        self.drive_vars: list[tuple[RemovableDrive, tk.BooleanVar]] = []
        self._build()

    # ── layout ───────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=1)
        row = 0

        # Back button
        tk.Button(self, text="← Volver", command=lambda: self.master.show(HomeScreen),
                  bg=BG, fg=FG_DIM, activebackground=BG, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  ).grid(row=row, column=0, sticky="w", padx=16, pady=(12, 0))
        row += 1

        tk.Label(self, text="Comprimir y copiar a USB", **TITLE_STYLE).grid(
            row=row, column=0, pady=(8, 20), padx=16, sticky="w")
        row += 1

        # Folder selection
        folder_frame = tk.Frame(self, bg=BG)
        folder_frame.grid(row=row, column=0, sticky="ew", padx=16)
        folder_frame.columnconfigure(0, weight=1)
        tk.Label(folder_frame, text="Carpeta a comprimir:", **LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        entry = tk.Entry(folder_frame, textvariable=self.folder_var, **ENTRY_STYLE)
        entry.grid(row=1, column=0, sticky="ew", ipady=6)
        tk.Button(folder_frame, text="Examinar…", command=self._browse,
                  bg=PANEL, fg=FG, activebackground=BORDER, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  padx=10, pady=6,
                  ).grid(row=1, column=1, padx=(8, 0))
        row += 1

        # Preview filename
        prev_frame = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        prev_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(14, 0))
        prev_frame.columnconfigure(1, weight=1)
        tk.Label(prev_frame, text="Nombre del archivo:", bg=PANEL, fg=FG_DIM,
                 font=("Segoe UI", 9)).grid(row=0, column=0, padx=12, pady=8, sticky="w")
        tk.Label(prev_frame, textvariable=self.preview_var, bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 10, "bold"), anchor="w").grid(
            row=0, column=1, padx=(0, 12), pady=8, sticky="ew")
        row += 1

        # USB drives
        usb_label_frame = tk.Frame(self, bg=BG)
        usb_label_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(18, 0))
        usb_label_frame.columnconfigure(0, weight=1)
        tk.Label(usb_label_frame, text="Unidades USB detectadas:", **LABEL_STYLE).grid(
            row=0, column=0, sticky="w")
        tk.Button(usb_label_frame, text="↺ Actualizar", command=self._refresh_drives,
                  bg=BG, fg=FG_DIM, activebackground=BG, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  ).grid(row=0, column=1, sticky="e")
        row += 1

        # "Copy to all" checkbox
        self.all_chk = tk.Checkbutton(
            self, text="Copiar a todos los dispositivos",
            variable=self.all_var, command=self._toggle_all,
            bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10),
        )
        self.all_chk.grid(row=row, column=0, sticky="w", padx=16, pady=(8, 4))
        row += 1

        # Drive list container (scrollable-ish)
        self.drive_frame = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                                    highlightthickness=1)
        self.drive_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 4))
        row += 1

        self._refresh_drives()

        # Progress & log
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=400)
        self.progress.grid(row=row, column=0, padx=16, pady=(14, 0), sticky="ew")
        row += 1

        self.log = tk.Text(self, height=6, wrap="word")
        style_scrolledtext(self.log)
        self.log.grid(row=row, column=0, padx=16, pady=(8, 0), sticky="ew")
        row += 1

        # Action button
        self.action_btn = tk.Button(
            self, text="Comprimir y copiar →",
            command=self._start_thread, **BTN_STYLE,
        )
        self.action_btn.grid(row=row, column=0, pady=20)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _browse(self):
        folder = filedialog.askdirectory(title="Selecciona la carpeta a comprimir")
        if folder:
            self.folder_var.set(folder)
            names = build_output_names(folder)
            self.preview_var.set("  +  ".join(names))

    def _refresh_drives(self):
        for w in self.drive_frame.winfo_children():
            w.destroy()
        self.drive_vars.clear()

        drives = get_removable_drives()
        if not drives:
            tk.Label(self.drive_frame,
                     text="  No se detectaron unidades extraíbles.",
                     bg=PANEL, fg=FG_DIM, font=("Segoe UI", 9),
                     ).pack(anchor="w", padx=12, pady=10)
        else:
            for drv in drives:
                var = tk.BooleanVar(value=self.all_var.get())
                chk = tk.Checkbutton(
                    self.drive_frame, text=str(drv), variable=var,
                    bg=PANEL, fg=FG, selectcolor=BG,
                    activebackground=PANEL, activeforeground=FG,
                    font=("Segoe UI", 10),
                )
                chk.pack(anchor="w", padx=12, pady=4)
                self.drive_vars.append((drv, var))

        self._toggle_all()

    def _toggle_all(self):
        all_checked = self.all_var.get()
        for _, var in self.drive_vars:
            var.set(all_checked)
        state = "disabled" if all_checked else "normal"
        for w in self.drive_frame.winfo_children():
            if isinstance(w, tk.Checkbutton):
                w.config(state=state)

    # ── main operation ────────────────────────────────────────────────────────

    def _start_thread(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Writer Backup",
                                   "Selecciona una carpeta válida primero.")
            return

        selected = [drv for drv, var in self.drive_vars if var.get()]
        if not selected:
            if not self.drive_vars:
                messagebox.showwarning("Writer Backup",
                                       "No hay unidades extraíbles conectadas.")
                return
            messagebox.showwarning("Writer Backup",
                                   "Selecciona al menos un dispositivo.")
            return

        if self.all_var.get():
            answer = messagebox.askyesno(
                "Confirmar",
                f"Se copiará a TODOS los dispositivos detectados "
                f"({len(selected)}).\n¿Continuar?",
            )
            if not answer:
                return

        self.action_btn.config(state="disabled")
        self.progress.start(10)
        thread = threading.Thread(
            target=self._run, args=(folder, selected), daemon=True
        )
        thread.start()

    def _run(self, folder: str, drives: list[RemovableDrive]):
        cfg = load_config()
        self._log("Comprimiendo carpeta (ZIP + RAR)…")
        try:
            archive_paths = compress_folder(folder, cfg.get("rar_tool_path", ""))
            for p in archive_paths:
                self._log(f"  ✔ {os.path.basename(p)}", SUCCESS)
        except Exception as exc:
            self._log(f"Error al comprimir: {exc}", ERROR)
            self._done()
            return

        errors: list[str] = []
        for drv in drives:
            dest_dir = os.path.join(drv.path, cfg.get("usb_destination_path", "My Folder"))
            self._log(f"Copiando a {drv}…")
            try:
                for arc in archive_paths:
                    copy_and_verify(arc, dest_dir)
                    self._log(f"  ✔ {os.path.basename(arc)} → {dest_dir}", SUCCESS)
            except Exception as exc:
                errors.append(str(drv))
                self._log(f"  ✗ Error en {drv}: {exc}", ERROR)

        if errors:
            self._log(f"Completado con errores en: {', '.join(errors)}", ERROR)
            self._done()
            return

        # Eject selected drives
        self._log("Expulsando unidades…")
        for drv in drives:
            ok = eject_drive(drv.letter)
            if ok:
                self._log(f"  ✔ {drv.letter}:\\ expulsada", SUCCESS)
            else:
                self._log(f"  ✗ No se pudo expulsar {drv.letter}:\\", ERROR)

        # Clean up: delete compressed files and source folder
        self._log("Limpiando archivos temporales…")
        for arc in archive_paths:
            try:
                os.remove(arc)
                self._log(f"  ✔ Eliminado {os.path.basename(arc)}", SUCCESS)
            except Exception as exc:
                self._log(f"  ✗ No se pudo eliminar {os.path.basename(arc)}: {exc}", ERROR)
        try:
            shutil.rmtree(folder)
            self._log(f"  ✔ Carpeta eliminada: {os.path.basename(folder)}", SUCCESS)
        except Exception as exc:
            self._log(f"  ✗ No se pudo eliminar la carpeta: {exc}", ERROR)

        self._log("¡Proceso completado con éxito!", SUCCESS)
        time.sleep(1)  # Give Windows time to complete ejection
        self.after(0, lambda: self._notify(
            "¡Copia completada!\nPuedes retirar las unidades."))
        self._done()

    def _notify(self, msg: str):
        """Show a topmost messagebox with a system sound."""
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        top = self.winfo_toplevel()
        top.attributes('-topmost', True)
        messagebox.showinfo("Writer Backup", msg)
        top.attributes('-topmost', False)

    def _log(self, msg: str, color: str = FG_DIM):
        self.after(0, lambda: log_msg(self.log, msg, color))

    def _done(self):
        self.after(0, lambda: (self.progress.stop(),
                               self.action_btn.config(state="normal")))


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 3 — Extract
# ═══════════════════════════════════════════════════════════════════════════════

class ExtractScreen(tk.Frame):
    def __init__(self, master: "App"):
        super().__init__(master, bg=BG)
        self.master: "App" = master
        self.cfg = load_config()
        self.src_var = tk.StringVar(value=self._detect_archive())
        self.dest_var = tk.StringVar(value=self.cfg.get("extract_destination_path", ""))
        self.eject_var = tk.BooleanVar(value=True)
        self._build()

    def _detect_archive(self) -> str:
        """Try to auto-detect a compressed file on removable drives.
        Searches the configured subfolder FIRST, then the drive root."""
        exts = tuple(self.cfg.get("compressed_extensions", [".zip", ".rar"]))
        drives = get_removable_drives()
        for drv in drives:
            sub = self.cfg.get("usb_destination_path", "")
            search_dirs = []
            if sub:
                search_dirs.append(os.path.join(drv.path, sub))
            search_dirs.append(drv.path)
            for search in search_dirs:
                if not os.path.isdir(search):
                    continue
                for f in sorted(os.listdir(search), reverse=True):
                    if f.lower().endswith(exts):
                        return os.path.join(search, f)
        return ""

    def _build(self):
        self.columnconfigure(0, weight=1)
        row = 0

        tk.Button(self, text="← Volver", command=lambda: self.master.show(HomeScreen),
                  bg=BG, fg=FG_DIM, activebackground=BG, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  ).grid(row=row, column=0, sticky="w", padx=16, pady=(12, 0))
        row += 1

        tk.Label(self, text="Extraer desde USB", **TITLE_STYLE).grid(
            row=row, column=0, pady=(8, 20), padx=16, sticky="w")
        row += 1

        # Source archive
        src_frame = tk.Frame(self, bg=BG)
        src_frame.grid(row=row, column=0, sticky="ew", padx=16)
        src_frame.columnconfigure(0, weight=1)
        tk.Label(src_frame, text="Archivo a extraer (.zip / .rar):", **LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Entry(src_frame, textvariable=self.src_var, **ENTRY_STYLE).grid(
            row=1, column=0, sticky="ew", ipady=6)
        tk.Button(src_frame, text="Examinar…", command=self._browse_src,
                  bg=PANEL, fg=FG, activebackground=BORDER, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  padx=10, pady=6,
                  ).grid(row=1, column=1, padx=(8, 0))
        row += 1

        # Destination folder
        dest_frame = tk.Frame(self, bg=BG)
        dest_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(14, 0))
        dest_frame.columnconfigure(0, weight=1)
        tk.Label(dest_frame, text="Carpeta de destino:", **LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Entry(dest_frame, textvariable=self.dest_var, **ENTRY_STYLE).grid(
            row=1, column=0, sticky="ew", ipady=6)
        tk.Button(dest_frame, text="Examinar…", command=self._browse_dest,
                  bg=PANEL, fg=FG, activebackground=BORDER, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  padx=10, pady=6,
                  ).grid(row=1, column=1, padx=(8, 0))
        row += 1

        # Eject checkbox
        tk.Checkbutton(
            self, text="Expulsar unidad USB al finalizar",
            variable=self.eject_var,
            bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10),
        ).grid(row=row, column=0, sticky="w", padx=16, pady=(14, 0))
        row += 1

        # Progress & log
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=400)
        self.progress.grid(row=row, column=0, padx=16, pady=(14, 0), sticky="ew")
        row += 1

        self.log = tk.Text(self, height=6, wrap="word")
        style_scrolledtext(self.log)
        self.log.grid(row=row, column=0, padx=16, pady=(8, 0), sticky="ew")
        row += 1

        self.action_btn = tk.Button(
            self, text="Extraer →", command=self._start_thread, **BTN_STYLE,
        )
        self.action_btn.grid(row=row, column=0, pady=20)

    def _browse_src(self):
        exts = self.cfg.get("compressed_extensions", [".zip", ".rar"])
        pattern = " ".join("*" + e for e in exts)
        path = filedialog.askopenfilename(
            title="Selecciona el archivo comprimido",
            filetypes=[("Archivos comprimidos", pattern), ("Todos", "*.*")],
        )
        if path:
            self.src_var.set(path)

    def _browse_dest(self):
        folder = filedialog.askdirectory(title="Selecciona la carpeta de destino")
        if folder:
            self.dest_var.set(folder)

    def _start_thread(self):
        src = self.src_var.get().strip()
        dest = self.dest_var.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showwarning("Writer Backup",
                                   "Selecciona un archivo .zip o .rar válido.")
            return
        if not dest:
            messagebox.showwarning("Writer Backup",
                                   "Selecciona la carpeta de destino.")
            return
        self.action_btn.config(state="disabled")
        self.progress.start(10)
        threading.Thread(target=self._run, args=(src, dest), daemon=True).start()

    def _run(self, src: str, dest: str):
        cfg = load_config()
        self._log("Extrayendo archivos…")
        try:
            ok, msg = extract_archive(src, dest, cfg.get("unrar_tool_path", ""))
            if not ok:
                self._log(msg, ERROR)
                self._done()
                return
            self._log(f"Extracción completada en:\n  {dest}", SUCCESS)
        except Exception as exc:
            self._log(f"Error: {exc}", ERROR)
            self._done()
            return

        # Eject the source drive if requested
        if self.eject_var.get():
            drive_letter = os.path.splitdrive(src)[0].rstrip(":\\")
            if drive_letter:
                self._log(f"Expulsando {drive_letter}:\\…")
                ok = eject_drive(drive_letter)
                if ok:
                    self._log(f"Unidad {drive_letter}:\\ expulsada.", SUCCESS)
                else:
                    self._log(f"No se pudo expulsar {drive_letter}:\\.", ERROR)

        self._log("¡Proceso completado!", SUCCESS)
        time.sleep(1)  # Give Windows time to complete ejection
        self.after(0, lambda: self._notify(
            "Extracción finalizada.\n\n✍  ¡Comienza a escribir!"))
        self._done()

    def _notify(self, msg: str):
        """Show a topmost messagebox with a system sound, then close app and open extracted folder."""
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        top = self.winfo_toplevel()
        top.attributes('-topmost', True)
        messagebox.showinfo("Writer Backup", msg)
        top.attributes('-topmost', False)
        # Close the app and open the extracted folder
        dest_folder = self.dest_var.get().strip()
        if dest_folder and os.path.isdir(dest_folder):
            # Open folder in Windows Explorer
            os.startfile(dest_folder)
        # Close the app
        self.after(100, self._close_app)

    def _close_app(self):
        self.master.destroy()

    def _log(self, msg: str, color: str = FG_DIM):
        self.after(0, lambda: log_msg(self.log, msg, color))

    def _done(self):
        self.after(0, lambda: (self.progress.stop(),
                               self.action_btn.config(state="normal")))


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 4 — Configuration
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigScreen(tk.Frame):
    def __init__(self, master: "App"):
        super().__init__(master, bg=BG)
        self.master: "App" = master
        cfg = load_config()
        self.usb_dest_var = tk.StringVar(value=cfg.get("usb_destination_path", ""))
        self.extract_dest_var = tk.StringVar(value=cfg.get("extract_destination_path", ""))
        self.unrar_var = tk.StringVar(value=cfg.get("unrar_tool_path", ""))
        self.rar_var = tk.StringVar(value=cfg.get("rar_tool_path", ""))
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        row = 0

        tk.Button(self, text="← Volver", command=lambda: self.master.show(HomeScreen),
                  bg=BG, fg=FG_DIM, activebackground=BG, activeforeground=FG,
                  relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                  ).grid(row=row, column=0, sticky="w", padx=16, pady=(12, 0))
        row += 1

        tk.Label(self, text="Configuración", **TITLE_STYLE).grid(
            row=row, column=0, pady=(8, 24), padx=16, sticky="w")
        row += 1

        fields = [
            ("Subcarpeta en el USB (destino de la copia):", self.usb_dest_var, False),
            ("Carpeta de extracción (destino):", self.extract_dest_var, True),
            ("Ruta de UnRAR.exe (para extraer .rar):", self.unrar_var, True),
            ("Ruta de Rar.exe (para crear .rar):", self.rar_var, True),
        ]

        for label_text, var, browse in fields:
            tk.Label(self, text=label_text, **LABEL_STYLE).grid(
                row=row, column=0, sticky="w", padx=16, pady=(0, 3))
            row += 1
            f = tk.Frame(self, bg=BG)
            f.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 14))
            f.columnconfigure(0, weight=1)
            tk.Entry(f, textvariable=var, **ENTRY_STYLE).grid(
                row=0, column=0, sticky="ew", ipady=6)
            if browse:
                tk.Button(f, text="Examinar…",
                          command=lambda v=var: self._browse_folder(v),
                          bg=PANEL, fg=FG, activebackground=BORDER, activeforeground=FG,
                          relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
                          padx=10, pady=6,
                          ).grid(row=0, column=1, padx=(8, 0))
            row += 1

        tk.Button(self, text="Guardar configuración", command=self._save,
                  **BTN_STYLE).grid(row=row, column=0, pady=10)

    def _browse_folder(self, var: tk.StringVar):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def _save(self):
        cfg = load_config()
        cfg["usb_destination_path"] = self.usb_dest_var.get().strip()
        cfg["extract_destination_path"] = self.extract_dest_var.get().strip()
        cfg["unrar_tool_path"] = self.unrar_var.get().strip()
        cfg["rar_tool_path"] = self.rar_var.get().strip()
        save_config(cfg)
        messagebox.showinfo("Writer Backup", "Configuración guardada.")


# ═══════════════════════════════════════════════════════════════════════════════
# App root — screen manager
# ═══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Writer Backup")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.geometry("520x620")
        self._current: tk.Frame | None = None
        # ttk theme tweaks
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=PANEL, background=ACCENT,
                        borderwidth=0, thickness=6)
        self.show(HomeScreen)

    def show(self, screen_cls):
        if self._current:
            self._current.destroy()
        self._current = screen_cls(self)
        self._current.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = App()
    app.mainloop()

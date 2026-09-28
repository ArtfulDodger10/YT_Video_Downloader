"""Small formatting and OS helpers."""

from __future__ import annotations

import os
import subprocess
import sys


def ensure_std_streams():
    """pythonw / windowed builds have no console: give print() and yt-dlp somewhere to write."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def human_bytes(n: float | None) -> str:
    if not n:
        return "–"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def human_eta(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(frac: float, width: int = 10) -> str:
    frac = min(max(frac, 0.0), 1.0)
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled) + f" {frac * 100:5.1f}%"


def open_path(path: str):
    """Open a file or folder with the OS default handler."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_in_folder(path: str):
    """Show a file selected in the system file manager."""
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin" and os.path.exists(path):
        subprocess.Popen(["open", "-R", path])
    else:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if os.path.isdir(folder):
            open_path(folder)

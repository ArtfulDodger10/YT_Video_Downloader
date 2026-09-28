"""Detection of the external tools yt-dlp can use: ffmpeg, JavaScript runtimes, aria2c."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

# yt-dlp needs a JS runtime to solve YouTube's signature challenges; without one most
# YouTube formats are missing. Order = preference.
JS_RUNTIMES = ("deno", "node", "bun", "quickjs")
_JS_EXECUTABLES = {"deno": ("deno",), "node": ("node",), "bun": ("bun",), "quickjs": ("qjs", "quickjs")}


def app_dir() -> Path:
    """Folder of the .exe when frozen, otherwise the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _find(name: str) -> str | None:
    """Look next to the app first (portable installs), then on PATH."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    base = app_dir()
    for folder in (base, base / "bin", base / name, base / name / "bin", base / "ffmpeg" / "bin"):
        if (folder / exe).is_file():
            return str(folder / exe)
    return shutil.which(name)


@dataclass
class Environment:
    ytdlp_version: str = ""
    ffmpeg: str | None = None
    ffprobe: str | None = None
    aria2c: str | None = None
    js_runtimes: dict = field(default_factory=dict)  # name -> executable path
    has_ejs: bool = False  # bundled YouTube challenge solver scripts (yt-dlp-ejs)
    frozen: bool = False

    @property
    def ffmpeg_dir(self) -> str | None:
        return str(Path(self.ffmpeg).parent) if self.ffmpeg else None

    def problems(self) -> list[str]:
        out = []
        if not self.ffmpeg:
            out.append("ffmpeg not found: merging HD video+audio, audio conversion and "
                       "embedding will not work. Install it (winget install Gyan.FFmpeg) "
                       "or put ffmpeg.exe next to this app.")
        elif not self.ffprobe:
            out.append("ffprobe not found next to ffmpeg: some post-processing may fail.")
        if not self.js_runtimes:
            out.append("No JavaScript runtime found: YouTube will offer only a few low-quality "
                       "formats. Install Deno (winget install DenoLand.Deno) or Node.js.")
        return out


def detect() -> Environment:
    env = Environment(ytdlp_version=yt_dlp.version.__version__,
                      frozen=bool(getattr(sys, "frozen", False)))
    env.ffmpeg = _find("ffmpeg")
    if env.ffmpeg:
        probe = Path(env.ffmpeg).with_name(Path(env.ffmpeg).name.replace("ffmpeg", "ffprobe"))
        env.ffprobe = str(probe) if probe.is_file() else _find("ffprobe")
    env.aria2c = _find("aria2c")
    for name in JS_RUNTIMES:
        for exe in _JS_EXECUTABLES[name]:
            path = _find(exe)
            if path:
                env.js_runtimes[name] = path
                break
    try:
        import yt_dlp_ejs  # noqa: F401
        env.has_ejs = True
    except ImportError:
        env.has_ejs = False
    return env

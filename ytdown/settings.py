"""User settings: a typed dataclass persisted as JSON in the per-user config folder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_NAME


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> str:
    home = Path.home()
    for candidate in ("Videos", "Downloads"):
        if (home / candidate).is_dir():
            return str(home / candidate)
    return str(home)


# Choice lists shared by the GUI, CLI and validation: (value, label)
VIDEO_QUALITIES = [("best", "Best available"), ("2160", "2160p (4K)"), ("1440", "1440p (2K)"),
                   ("1080", "1080p"), ("720", "720p"), ("480", "480p"), ("360", "360p"),
                   ("240", "240p"), ("144", "144p")]
VIDEO_CONTAINERS = [("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WEBM"), ("original", "Original")]
VIDEO_CODECS = [("compat", "Compatible (H.264 / AAC, plays everywhere)"),
                ("best", "Best quality (AV1 / VP9 when available)")]
AUDIO_FORMATS = [("mp3", "MP3"), ("m4a", "M4A (AAC)"), ("opus", "OPUS"), ("flac", "FLAC"),
                 ("wav", "WAV"), ("original", "Original (no re-encode)")]
AUDIO_QUALITIES = [("0", "Best (VBR)"), ("320K", "320 kbps"), ("256K", "256 kbps"),
                   ("192K", "192 kbps"), ("128K", "128 kbps")]
SPONSORBLOCK_MODES = [("off", "Off"), ("mark", "Mark segments as chapters"),
                      ("remove", "Cut segments out")]
SPONSORBLOCK_CATEGORIES = [("sponsor", "Sponsors"), ("selfpromo", "Self-promotion"),
                           ("interaction", "Like/subscribe reminders"), ("intro", "Intros"),
                           ("outro", "Outros / end cards"), ("preview", "Previews / recaps"),
                           ("music_offtopic", "Non-music in music videos"), ("filler", "Filler")]
BROWSERS = [("", "None"), ("firefox", "Firefox"), ("chrome", "Chrome"), ("edge", "Edge"),
            ("brave", "Brave"), ("opera", "Opera"), ("vivaldi", "Vivaldi"),
            ("chromium", "Chromium"), ("safari", "Safari")]
FILENAME_TEMPLATES = [
    "%(title)s.%(ext)s",
    "%(title)s [%(id)s].%(ext)s",
    "%(uploader)s - %(title)s.%(ext)s",
    "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s",
]

_CHOICES = {
    "mode": [("video", ""), ("audio", "")],
    "video_quality": VIDEO_QUALITIES,
    "video_container": VIDEO_CONTAINERS,
    "video_codec": VIDEO_CODECS,
    "audio_format": AUDIO_FORMATS,
    "audio_quality": AUDIO_QUALITIES,
    "sponsorblock": SPONSORBLOCK_MODES,
    "cookies_browser": BROWSERS,
    "theme": [("dark", ""), ("light", "")],
}

_RANGES = {"max_concurrent": (1, 10), "fragments": (1, 32), "retries": (0, 100)}


@dataclass
class Settings:
    # what to download
    output_dir: str = ""
    mode: str = "video"
    video_quality: str = "best"
    video_container: str = "mp4"
    video_codec: str = "compat"
    audio_format: str = "mp3"
    audio_quality: str = "0"
    download_playlist: bool = False
    playlist_items: str = ""
    # files
    filename_template: str = FILENAME_TEMPLATES[0]
    playlist_subfolder: bool = True
    playlist_numbering: bool = True
    no_mtime: bool = True
    use_archive: bool = False
    # extras
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    embed_chapters: bool = True
    subtitles: bool = False
    subtitle_langs: str = "en.*"
    auto_subtitles: bool = False
    embed_subtitles: bool = True
    sponsorblock: str = "off"
    sponsorblock_categories: str = "sponsor,selfpromo,interaction"
    # network
    max_concurrent: int = 3
    fragments: int = 4
    rate_limit: str = ""
    retries: int = 10
    proxy: str = ""
    cookies_browser: str = ""
    cookies_file: str = ""
    use_aria2c: bool = False
    system_certs: bool = sys.platform == "win32"
    # advanced / UI
    extra_args: str = ""
    theme: str = "dark"
    watch_clipboard: bool = False
    window_geometry: str = ""

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = default_output_dir()

    # persistence ---------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Build settings from untrusted JSON, dropping unknown keys and bad values."""
        s = cls()
        if not isinstance(data, dict):
            return s
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(s, f.name)
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    continue
            elif isinstance(default, int):
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                lo, hi = _RANGES.get(f.name, (value, value))
                value = max(lo, min(hi, value))
            elif not isinstance(value, str):
                continue
            if f.name in _CHOICES and value not in {v for v, _ in _CHOICES[f.name]}:
                continue
            setattr(s, f.name, value)
        if not s.output_dir:
            s.output_dir = default_output_dir()
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

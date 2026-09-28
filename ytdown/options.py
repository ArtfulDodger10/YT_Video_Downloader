"""Translate Settings into yt-dlp command-line arguments.

Building a real argv (instead of hand-writing the options dict) lets yt-dlp's own
parser wire up postprocessors exactly like the official CLI does, and lets users add
any extra yt-dlp flag they like.
"""

from __future__ import annotations

import re
import shlex

from .deps import Environment
from .settings import Settings

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def build_args(s: Settings, env: Environment, *, subdir: str = "", prefix: str = "",
               noplaylist: bool | None = None, archive_path: str | None = None) -> list[str]:
    """Return yt-dlp arguments (without the URL) for one download job."""
    a: list[str] = ["--ignore-config", "--abort-on-error", "--no-progress", "--no-color"]
    video = s.mode == "video"

    # --- format selection -------------------------------------------------
    if video:
        sort = []
        if s.video_quality != "best":
            sort.append(f"res:{s.video_quality}")
        if s.video_container == "webm":
            sort += ["vcodec:vp9", "acodec:opus"]
        elif s.video_codec == "compat":
            sort += ["vcodec:h264", "acodec:aac"]
        a += ["-f", "bv*+ba/b"]
        if sort:
            a += ["-S", ",".join(sort)]
        if s.video_container != "original":
            a += ["--merge-output-format", s.video_container, "--remux-video", s.video_container]
    else:
        pick = {"m4a": "ba[ext=m4a]/ba/b", "opus": "ba[acodec=opus]/ba/b"}
        a += ["-f", pick.get(s.audio_format, "ba/b"), "-x"]
        if s.audio_format != "original":
            a += ["--audio-format", s.audio_format]
            if s.audio_format in ("mp3", "m4a", "opus"):
                a += ["--audio-quality", s.audio_quality]

    # --- files ----------------------------------------------------------------
    template = s.filename_template.strip() or "%(title)s.%(ext)s"
    if prefix:
        template = prefix.replace("%", "%%") + template
    if subdir:
        template = subdir.replace("%", "%%") + "/" + template
    a += ["-P", s.output_dir, "-o", template, "--trim-filenames", "180"]
    if s.no_mtime:
        a.append("--no-mtime")
    if archive_path and s.use_archive:
        a += ["--download-archive", archive_path]
    if noplaylist is None:
        noplaylist = not s.download_playlist
    a.append("--no-playlist" if noplaylist else "--yes-playlist")
    if s.playlist_items.strip():
        a += ["-I", s.playlist_items.strip()]

    # --- embedding / extras ---------------------------------------------------
    container = s.video_container if video else s.audio_format
    if s.embed_metadata:
        a.append("--embed-metadata")
    if s.embed_chapters:
        a.append("--embed-chapters")
    if s.embed_thumbnail and container not in ("webm", "wav", "original"):
        a.append("--embed-thumbnail")
    if s.subtitles:
        a += ["--write-subs", "--sub-langs", s.subtitle_langs.strip() or "en.*"]
        if s.auto_subtitles:
            a.append("--write-auto-subs")
        if video and s.embed_subtitles and container != "original":
            a.append("--embed-subs")
        else:
            a += ["--convert-subs", "srt"]
    cats = ",".join(c.strip() for c in s.sponsorblock_categories.split(",") if c.strip())
    if s.sponsorblock == "mark" and cats:
        a += ["--sponsorblock-mark", cats]
    elif s.sponsorblock == "remove" and cats:
        a += ["--sponsorblock-remove", cats]

    # --- network / performance ----------------------------------------------
    a += ["-N", str(s.fragments), "-R", str(s.retries), "--fragment-retries", str(s.retries),
          "--retry-sleep", "http:exp=1:20", "--retry-sleep", "fragment:exp=1:20"]
    if s.rate_limit.strip():
        a += ["-r", s.rate_limit.strip()]
    if s.proxy.strip():
        a += ["--proxy", s.proxy.strip()]
    if s.cookies_file.strip():
        a += ["--cookies", s.cookies_file.strip()]
    elif s.cookies_browser:
        a += ["--cookies-from-browser", s.cookies_browser]
    if s.use_aria2c and env.aria2c:
        a += ["--downloader", f"http:{env.aria2c}",
              "--downloader-args", "aria2c:-x 16 -s 16 -k 1M --summary-interval=0"]
    if s.system_certs:
        a += ["--compat-options", "no-certifi"]

    # --- tools --------------------------------------------------------------
    if env.ffmpeg_dir:
        a += ["--ffmpeg-location", env.ffmpeg_dir]
    for name, path in env.js_runtimes.items():
        a += ["--js-runtimes", f"{name}:{path}"]
    if env.js_runtimes and not env.has_ejs:
        a += ["--remote-components", "ejs:github"]

    if s.extra_args.strip():
        a += split_args(s.extra_args)
    return a


def split_args(text: str) -> list[str]:
    return shlex.split(text, posix=True)


def validate_extra_args(text: str) -> str | None:
    """Return an error message if the user's extra yt-dlp arguments don't parse."""
    if not text.strip():
        return None
    import yt_dlp
    try:
        args = split_args(text)
    except ValueError as e:
        return f"Quoting error: {e}"
    try:
        parsed = yt_dlp.parse_options(["--ignore-config", *args])
    except SystemExit:
        return "yt-dlp rejected these arguments (unknown option or bad value)."
    except Exception as e:  # yt-dlp validation errors
        return str(e)
    if parsed.urls:
        return "Extra arguments must not contain URLs: " + " ".join(parsed.urls)
    return None


def extract_targets(text: str) -> list[str]:
    """Pull download targets out of pasted text.

    URLs are found anywhere in the text. Lines without a URL are treated as a
    YouTube search ("ytsearch1:<line>") unless they already use a yt-dlp search prefix.
    """
    out: list[str] = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        urls = [u.rstrip(").,;]}>") for u in _URL_RE.findall(line)]
        if not urls:
            if re.match(r"^[a-z0-9]+search\d*(all)?:", line, re.I):
                urls = [line]
            else:
                urls = ["ytsearch1:" + line]
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.fullmatch(text.strip()))


_HINTS = [
    (("confirm you're not a bot", "confirm you’re not a bot", "confirm your age",
      "age-restricted", "inappropriate for some users", "members-only", "join this channel"),
     "The site wants a signed-in session. Settings > Network > Cookies: choose a browser "
     "where you are logged in (Firefox is the most reliable on Windows), or a cookies.txt file."),
    (("could not copy chrome cookie", "failed to decrypt", "cookies database",
      "cookie database", "keyring"),
     "Couldn't read that browser's cookies. Close the browser completely and retry, use "
     "Firefox, or export a cookies.txt file with a browser extension."),
    (("certificate verify failed", "certificate_verify_failed"),
     "TLS certificate problem (often antivirus HTTPS scanning or a proxy). Enable "
     "Settings > Network > 'Use the system certificate store'."),
    (("http error 429", "too many requests"),
     "Rate-limited by the site. Lower 'Simultaneous downloads', wait a while, or use cookies."),
    (("http error 403", "forbidden"),
     "Access denied. Update yt-dlp (About tab), then try again or use cookies."),
    (("ffmpeg", "ffprobe"),
     "ffmpeg is missing or failed. Install it (winget install Gyan.FFmpeg) or place "
     "ffmpeg.exe next to the app, then restart."),
    (("n challenge", "signature solving", "js runtime", "javascript runtime", "ejs"),
     "YouTube's challenge couldn't be solved. Install Deno or Node.js and update yt-dlp."),
    (("requested format is not available", "no video formats"),
     "That quality/format isn't offered. Pick 'Best available' or another container."),
    (("unsupported url",), "This link isn't supported by yt-dlp."),
    (("http error 404", "404: not found"), "Nothing was found at this address. Check that the link is complete."),
    (("private video", "video unavailable", "has been removed", "not available in your country"),
     "The video is private, removed or region-locked."),
    (("unable to download webpage", "getaddrinfo", "timed out", "connection reset",
      "network is unreachable", "remote end closed"),
     "Network problem. Check your connection or proxy and retry."),
    (("no space left", "disk full", "errno 28"), "The destination drive is full."),
    (("permission denied", "access is denied", "errno 13"),
     "Can't write to the download folder, or the file is open in another program."),
]


def hint_for(error: str) -> str:
    low = error.lower()
    for needles, hint in _HINTS:
        if any(n in low for n in needles):
            return hint
    return ""


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean_error(msg: str) -> str:
    msg = _ANSI.sub("", str(msg)).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r";?\s*please report this issue on\s+https://\S+.*$", "", msg, flags=re.S | re.I)
    msg = re.sub(r"\s*\(caused by <?[A-Za-z]+Error.*?\)\s*$", "", msg, flags=re.S)
    return msg.strip()

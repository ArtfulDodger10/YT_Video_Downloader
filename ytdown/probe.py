"""Quick look at a link before downloading: title, thumbnail, available qualities, playlist size.

For single videos the extracted info is kept so the download can reuse it instead of
extracting the same page again.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import yt_dlp

from .deps import Environment
from .engine import best_thumbnail, quality_label
from .options import build_args, clean_error, hint_for
from .settings import Settings


class _Quiet:
    def debug(self, msg):
        pass

    info = warning = debug

    def error(self, msg):
        pass


@dataclass
class ProbeResult:
    url: str
    kind: str = "video"  # "video" | "playlist" | "error"
    title: str = ""
    uploader: str = ""
    site: str = ""
    duration: float | None = None
    thumbnail: str = ""
    heights: list = field(default_factory=list)  # available video heights, descending
    has_video: bool = True
    count: int | None = None  # playlist entries (capped)
    count_capped: bool = False
    info: dict | None = field(default=None, repr=False)  # reusable raw info (videos only)
    fetched_at: float = field(default_factory=time.time)
    error: str = ""
    hint: str = ""


def probe(url: str, settings: Settings, env: Environment, max_count: int = 1000) -> ProbeResult:
    argv = build_args(settings, env)
    opts = yt_dlp.parse_options(argv).ydl_opts
    opts.update(logger=_Quiet(), extract_flat="in_playlist", quiet=True, no_warnings=True,
                noprogress=True)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ie = ydl.extract_info(url, download=False, process=False)
            for _ in range(3):
                if ie and ie.get("_type") == "url" and ie.get("url"):
                    ie = ydl.extract_info(ie["url"], download=False, process=False,
                                          ie_key=ie.get("ie_key"))
                else:
                    break
            if not ie:
                raise yt_dlp.utils.DownloadError("Nothing found at this link.")
            return _summarize(url, ie, max_count)
    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
        msg = clean_error(getattr(e, "msg", None) or e)
        return ProbeResult(url=url, kind="error", error=msg, hint=hint_for(msg))
    except Exception as e:  # never crash the UI over a preview
        msg = clean_error(e)
        return ProbeResult(url=url, kind="error", error=msg, hint=hint_for(msg))


def _summarize(url: str, ie: dict, max_count: int) -> ProbeResult:
    r = ProbeResult(url=url, site=str(ie.get("extractor_key") or ie.get("ie_key") or ""))
    r.title = str(ie.get("title") or ie.get("id") or url)
    r.uploader = str(ie.get("uploader") or ie.get("channel") or "")
    if ie.get("_type") in ("playlist", "multi_video"):
        r.kind = "playlist"
        entries = ie.get("entries") or []
        first = None
        n = 0
        for e in itertools.islice(entries, max_count + 1):
            if e:
                first = first or e
                n += 1
        r.count = min(n, max_count)
        r.count_capped = n > max_count
        r.count = ie.get("playlist_count") or r.count
        r.thumbnail = best_thumbnail(ie) or (best_thumbnail(first) if first else "")
        if not r.uploader and first:
            r.uploader = str(first.get("uploader") or first.get("channel") or "")
        return r
    formats = ie.get("formats") or []
    r.heights = sorted({int(quality_label(f.get("width"), f["height"])[:-1]) for f in formats
                        if isinstance(f.get("height"), int) and f.get("vcodec") != "none"}, reverse=True)
    r.has_video = bool(r.heights) or any(f.get("vcodec") not in (None, "none") for f in formats) \
        or (not formats and ie.get("vcodec") != "none")
    if isinstance(ie.get("duration"), (int, float)):
        r.duration = ie["duration"]
    r.thumbnail = best_thumbnail(ie)
    r.info = ie
    return r
